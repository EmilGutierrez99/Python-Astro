#!/usr/bin/env python3
"""
Script de ingesta de resultados deportivos — IN-316.

Consulta football-data.org v4, genera un snapshot JSON y descarga las imagenes
asociadas (escudos de equipos y emblemas de competicion), de modo que el
componente de Astro (IN-307) no tenga que llamar a la API en tiempo de render.

Salida:
  JSON:     {paths.data}/{DD-MM-YYYY}/{HH-MM}/matches.json
  Imagenes: {paths.images}/{DD-MM-YYYY}/{HH-MM}/            (modo "snapshot", por defecto)
            {paths.images}/crests/                          (modo "shared")

Contrato del JSON (consumido por src/lib/resultadosDeportivos.ts):

  {
    "generated_at": "2026-07-22T18:16:43Z",
    "competitions": ["WC", "PD"],
    "count": 3,
    "matches": [
      {
        "id": 537406,
        "competition": {"code": "WC", "name": "FIFA World Cup",
                        "emblem": "/images/22-07-2026/18-16/wm26.png"},
        "status": "FINISHED",
        "utcDate": "2026-07-15T19:00:00Z",
        "stage": "SEMI_FINALS",
        "group": null,
        "home": {"name": "England",   "tla": "ENG", "crest": "/images/.../770.svg"},
        "away": {"name": "Argentina", "tla": "ARG", "crest": "/images/.../762.png"},
        "score": {"home": 1, "away": 2}
      }
    ]
  }

Codigos de salida:
  0  OK (snapshot escrito)
  1  error de configuracion o error inesperado
  2  la API no respondio correctamente -> NO se escribe snapshot

Uso:
    python script.py
    python script.py --config /ruta/a/config.json
    python script.py --dry-run          # consulta y muestra, no escribe nada

Requisitos: solo libreria estandar de Python 3.9+.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = "config.json"

# Solo estos codigos justifican reintentar. Un 400/401/403/404 no se arregla
# solo: reintentarlo gasta cupo del limite de 10 req/min y retrasa el fallo.
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}

# Nombre de archivo seguro: sin separadores de ruta ni "..".
SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_API = 2


# --------------------------------------------------------------------------- #
# Configuracion y logging
# --------------------------------------------------------------------------- #

def load_config(config_path: str) -> dict:
    path = Path(config_path)
    if not path.is_file():
        raise FileNotFoundError(f"No se encontro el archivo de configuracion: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def resolve_api_key(config: dict) -> str:
    """La variable de entorno gana sobre el archivo, para no versionar el token."""
    env_var = config.get("api", {}).get("api_key_env", "FOOTBALL_DATA_TOKEN")
    return (os.environ.get(env_var) or config.get("api", {}).get("api_key") or "").strip()


def setup_logging(config: dict) -> logging.Logger:
    log_cfg = config.get("logging", {})
    logger = logging.getLogger("sports_script")
    logger.handlers.clear()
    logger.propagate = False

    if not log_cfg.get("enabled", True):
        logger.addHandler(logging.NullHandler())
        return logger

    logger.setLevel(getattr(logging, str(log_cfg.get("level", "INFO")).upper(), logging.INFO))
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    log_file = log_cfg.get("file")
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)
    return logger


def get_ssl_context(config: dict):
    if config.get("api", {}).get("verify_ssl", True):
        return None
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


# --------------------------------------------------------------------------- #
# Red: reintentos que respetan las cabeceras de espera
# --------------------------------------------------------------------------- #

class ApiError(RuntimeError):
    """La API no devolvio una respuesta utilizable."""


def _read_error_body(err: urllib.error.HTTPError) -> str:
    """football-data devuelve el motivo del fallo en el cuerpo. Sin esto el log
    solo dice 'HTTP Error 400:' y no hay forma de diagnosticar nada."""
    try:
        raw = err.read().decode("utf-8", errors="replace").strip()
    except Exception:
        return ""
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
        return str(parsed.get("message") or parsed.get("error") or raw)[:500]
    except json.JSONDecodeError:
        return raw[:500]


def _retry_delay(err: Exception, attempt: int, max_wait: int) -> float:
    """Espera que indica el servidor; si no dice nada, backoff exponencial.

    football-data usa 'X-RequestCounter-Reset' (segundos hasta que se reinicia
    la ventana del minuto). El estandar HTTP es 'Retry-After'. Con el backoff
    antiguo (tope 10 s) los tres reintentos caian dentro de la misma ventana.
    """
    if isinstance(err, urllib.error.HTTPError):
        headers = err.headers or {}
        for header in ("Retry-After", "X-RequestCounter-Reset"):
            value = headers.get(header)
            if value:
                try:
                    return min(float(str(value).strip()) + 1.0, max_wait)
                except ValueError:
                    continue
    return min(2.0 ** attempt, max_wait)


def http_get(
    url: str,
    *,
    headers: dict[str, str] | None,
    config: dict,
    logger: logging.Logger,
    what: str,
) -> bytes:
    """GET con reintentos solo ante errores reintentables."""
    api_cfg = config.get("api", {})
    download_cfg = config.get("download", {})
    max_retries = int(download_cfg.get("max_retries", 3))
    max_wait = int(download_cfg.get("max_retry_wait_seconds", 90))
    timeout = int(api_cfg.get("timeout", 30))
    ssl_context = get_ssl_context(config)

    request = urllib.request.Request(url, headers=headers or {})

    for attempt in range(1, max_retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=ssl_context) as response:
                return response.read()
        except urllib.error.HTTPError as e:
            body = _read_error_body(e)
            detail = f"HTTP {e.code}{' — ' + body if body else ''}"
            if e.code not in RETRYABLE_STATUS:
                # No reintentable: abortar ya, sin gastar cupo.
                raise ApiError(f"{what}: {detail}") from e
            if attempt == max_retries:
                raise ApiError(f"{what}: {detail} (agotados {max_retries} intentos)") from e
            delay = _retry_delay(e, attempt, max_wait)
            logger.warning(f"{what}: {detail}. Reintento {attempt}/{max_retries} en {delay:.0f}s")
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt == max_retries:
                raise ApiError(f"{what}: {e} (agotados {max_retries} intentos)") from e
            delay = _retry_delay(e, attempt, max_wait)
            logger.warning(f"{what}: {e}. Reintento {attempt}/{max_retries} en {delay:.0f}s")
            time.sleep(delay)

    raise ApiError(f"{what}: sin respuesta")


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #

def build_match_url(config: dict, date_from: str, date_to: str) -> str:
    api_cfg = config["api"]
    filters = config.get("filters", {})

    competitions = api_cfg.get("competitions") or filters.get("competitions") or ["WC"]
    if isinstance(competitions, str):
        competitions = [competitions]

    params = {
        "competitions": ",".join(c.strip() for c in competitions if c and c.strip()),
        "dateFrom": date_from,
        "dateTo": date_to,
    }
    status = filters.get("status", "FINISHED")
    if status:
        params["status"] = status

    return f"{api_cfg['base_url'].rstrip('/')}/matches?{urllib.parse.urlencode(params)}"


def fetch_matches(config: dict, logger: logging.Logger) -> list[dict]:
    filters = config.get("filters", {})
    days_back = int(filters.get("days_back", 7))

    today = datetime.now(timezone.utc)
    date_from = (today - timedelta(days=days_back)).strftime("%Y-%m-%d")
    date_to = today.strftime("%Y-%m-%d")

    url = build_match_url(config, date_from, date_to)
    logger.info(f"Consultando API: {url}")

    api_key = resolve_api_key(config)
    if not api_key:
        raise ApiError(
            "Falta la API key. Define la variable de entorno "
            f"{config.get('api', {}).get('api_key_env', 'FOOTBALL_DATA_TOKEN')} "
            "o el campo api.api_key en el config."
        )

    payload = http_get(
        url,
        headers={"X-Auth-Token": api_key, "Accept": "application/json"},
        config=config,
        logger=logger,
        what="Consulta de partidos",
    )

    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ApiError(f"Respuesta de la API no es JSON valido: {e}") from e

    matches = data.get("matches", [])
    logger.info(f"API respondio con {len(matches)} partido(s)")
    return matches


# --------------------------------------------------------------------------- #
# Imagenes
# --------------------------------------------------------------------------- #

def safe_filename(url: str) -> str:
    """Nombre de archivo a partir de la URL, sin asumir formato ni patron.

    Sirve tanto para '818.svg' (numerico) como para 'congo_dr.svg' (textual).
    Si el nombre no es seguro (contiene '/', '..', etc.) se descarta.
    """
    candidate = urllib.parse.unquote(urllib.parse.urlparse(url).path).split("/")[-1]
    candidate = candidate.strip()
    if not candidate or candidate in {".", ".."} or not SAFE_FILENAME_RE.match(candidate):
        return ""
    return candidate


def download_image(
    url: str,
    dest_folder: Path,
    web_prefix: str,
    config: dict,
    logger: logging.Logger,
    cache: dict[str, str],
) -> str:
    """Descarga una imagen y devuelve su ruta web. Cadena vacia si no se pudo."""
    if not url:
        return ""
    if url in cache:
        return cache[url]

    filename = safe_filename(url)
    if not filename:
        logger.warning(f"Nombre de archivo no seguro, se omite la imagen: {url}")
        return ""

    overwrite = config.get("download", {}).get("overwrite", False)
    dest_path = dest_folder / filename
    web_path = f"{web_prefix}/{filename}"

    # Se crea la carpeta solo cuando de verdad vamos a escribir en ella, para no
    # dejar carpetas de imagenes vacias en cada corrida.
    if dest_path.exists() and not overwrite:
        logger.debug(f"Imagen ya presente, se reutiliza: {dest_path}")
        cache[url] = web_path
        return web_path

    try:
        payload = http_get(url, headers=None, config=config, logger=logger, what=f"Descarga {filename}")
    except ApiError as e:
        logger.warning(f"No se pudo descargar la imagen ({e}). El componente usara el fallback.")
        return ""

    dest_folder.mkdir(parents=True, exist_ok=True)
    write_atomic(dest_path, payload)
    logger.info(f"Imagen descargada: {dest_path}")
    cache[url] = web_path
    return web_path


# --------------------------------------------------------------------------- #
# Transformacion al contrato del snapshot
# --------------------------------------------------------------------------- #

def _team(raw: dict) -> dict:
    return {
        "name": raw.get("shortName") or raw.get("name") or "",
        "tla": raw.get("tla") or "",
        "crest": "",
    }


def process_matches(
    raw_matches: list[dict],
    config: dict,
    image_folder: Path,
    web_prefix: str,
    logger: logging.Logger,
) -> list[dict]:
    filters = config.get("filters", {})
    max_results = int(filters.get("max_results", 0) or 0)
    max_per_competition = int(filters.get("max_results_per_competition", 0) or 0)
    wanted_status = filters.get("status", "FINISHED")
    download_images = config.get("download", {}).get("download_images", True)

    # El filtro de status ya va en la query, pero se repite aqui: es un criterio
    # de aceptacion y no debe depender de que el parametro siga soportado.
    if wanted_status:
        raw_matches = [m for m in raw_matches if m.get("status") == wanted_status]

    # Orden explicito por fecha descendente. No confiar en el orden de la API.
    raw_matches.sort(key=lambda m: m.get("utcDate") or "", reverse=True)

    # Cuota por competicion ANTES del tope global: sin esto, la liga con mas
    # partidos recientes (p.ej. el Brasileirao, que juega entre semana) se come
    # el cupo y las demas ligas llegan al componente con uno o ningun partido.
    if max_per_competition > 0:
        per_competition: dict[str, int] = {}
        balanced = []
        for m in raw_matches:
            code = (m.get("competition") or {}).get("code") or "?"
            if per_competition.get(code, 0) >= max_per_competition:
                continue
            per_competition[code] = per_competition.get(code, 0) + 1
            balanced.append(m)
        raw_matches = balanced

    if max_results > 0:
        raw_matches = raw_matches[:max_results]

    cache: dict[str, str] = {}
    processed: list[dict] = []

    for m in raw_matches:
        home = _team(m.get("homeTeam") or {})
        away = _team(m.get("awayTeam") or {})
        competition_raw = m.get("competition") or {}
        competition = {
            "code": competition_raw.get("code") or "",
            "name": competition_raw.get("name") or "",
            "emblem": "",
        }

        if download_images:
            home["crest"] = download_image(
                (m.get("homeTeam") or {}).get("crest", ""), image_folder, web_prefix, config, logger, cache
            )
            away["crest"] = download_image(
                (m.get("awayTeam") or {}).get("crest", ""), image_folder, web_prefix, config, logger, cache
            )
            competition["emblem"] = download_image(
                competition_raw.get("emblem", ""), image_folder, web_prefix, config, logger, cache
            )
        else:
            home["crest"] = (m.get("homeTeam") or {}).get("crest", "")
            away["crest"] = (m.get("awayTeam") or {}).get("crest", "")
            competition["emblem"] = competition_raw.get("emblem", "")

        full_time = (m.get("score") or {}).get("fullTime") or {}

        processed.append({
            "id": m.get("id"),
            "competition": competition,
            "status": m.get("status"),
            "utcDate": m.get("utcDate"),
            "stage": m.get("stage"),
            "group": m.get("group"),
            "home": home,
            "away": away,
            "score": {"home": full_time.get("home"), "away": full_time.get("away")},
        })

    return processed


# --------------------------------------------------------------------------- #
# Escritura
# --------------------------------------------------------------------------- #

def write_atomic(path: Path, payload: bytes) -> None:
    """Escribe via temporal + os.replace: nunca deja un archivo a medias que el
    componente de Astro no pueda parsear."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
        os.replace(tmp_name, path)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def save_snapshot(
    matches: list[dict], competitions: list[str], data_folder: Path, filename: str, logger: logging.Logger
) -> Path:
    document = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "competitions": competitions,
        "count": len(matches),
        "matches": matches,
    }
    output_path = data_folder / filename
    write_atomic(output_path, json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8"))
    logger.info(f"Snapshot guardado en: {output_path} ({len(matches)} partido(s))")
    return output_path


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def main() -> int:
    parser = argparse.ArgumentParser(description="Genera el snapshot de resultados deportivos.")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Ruta al archivo config.json")
    parser.add_argument("--dry-run", action="store_true", help="Consulta la API pero no escribe nada")
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[ERROR] No se pudo cargar la configuracion: {e}", file=sys.stderr)
        return EXIT_ERROR

    logger = setup_logging(config)

    try:
        paths_cfg = config["paths"]
        output_cfg = config.get("output", {})

        # Una sola referencia temporal para carpetas y para el rango de la query,
        # en UTC, para que no dependa de la zona horaria del servidor.
        now = datetime.now(timezone.utc)
        date_str = now.strftime(output_cfg.get("date_format", "%d-%m-%Y"))
        time_str = now.strftime(output_cfg.get("time_format", "%H-%M"))

        data_folder = Path(paths_cfg["data"]) / date_str / time_str

        # "snapshot": {images}/{fecha}/{hora}  — layout que pide IN-316
        # "shared":   {images}/crests          — evita re-descargar los mismos
        #                                        escudos en cada corrida
        images_mode = config.get("images", {}).get("mode", "snapshot")
        if images_mode == "shared":
            shared_dir = config.get("images", {}).get("shared_dir", "crests")
            image_folder = Path(paths_cfg["images"]) / shared_dir
            web_prefix = f"/images/{shared_dir}"
        else:
            image_folder = Path(paths_cfg["images"]) / date_str / time_str
            web_prefix = f"/images/{date_str}/{time_str}"

        raw_matches = fetch_matches(config, logger)

        competitions = config.get("api", {}).get("competitions") or ["WC"]
        if isinstance(competitions, str):
            competitions = [competitions]

        if args.dry_run:
            logger.info(f"[dry-run] {len(raw_matches)} partido(s); no se escribe nada.")
            return EXIT_OK

        matches = process_matches(raw_matches, config, image_folder, web_prefix, logger)

        if not matches:
            # La API respondio bien pero no hay partidos en la ventana. Es un
            # resultado valido: se escribe el snapshot vacio y el componente
            # hara fallback al ultimo snapshot con datos.
            logger.info("La API no devolvio partidos en el rango consultado.")

        filename = (output_cfg.get("json_filename") or "matches.json").strip()
        if not filename.lower().endswith(".json"):
            filename += ".json"

        save_snapshot(matches, competitions, data_folder, filename, logger)
        logger.info("Proceso finalizado correctamente.")
        return EXIT_OK

    except ApiError as e:
        # Diferencia clave frente a la version anterior: si la API falla NO se
        # escribe snapshot (no se pisa el bueno) y se sale con codigo != 0 para
        # que cron y la monitorizacion se enteren.
        logger.error(f"Fallo la consulta a la API, no se escribe snapshot: {e}")
        return EXIT_API
    except Exception as e:  # noqa: BLE001
        logger.exception(f"Error inesperado durante la ejecucion: {e}")
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())