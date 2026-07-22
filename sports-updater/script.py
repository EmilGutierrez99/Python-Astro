#!/usr/bin/env python3
"""
Script de actualización de resultados deportivos.

Se conecta a la API de football-data.org, descarga los últimos resultados
finalizados de una competición y genera:

  - un JSON con los partidos en:   {paths.data}/{DD-MM-YYYY}/{HH-MM}/{output.json_filename}
                                    (por defecto "matches.json", configurable en config.json)
  - los escudos de los equipos en: {paths.images}/{DD-MM-YYYY_HH-MM}/

Pensado para ejecutarse FUERA del proyecto Astro (por cron, tarea programada,
CI, etc.), apuntando "paths.data" y "paths.images" del config.json a la
carpeta public/ del proyecto de destino.

Uso:
    python script.py
    python script.py --config /ruta/a/config.json

Requisitos: solo librería estándar de Python 3.8+. No necesita pip install.
"""

import argparse
import json
import logging
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

DEFAULT_CONFIG_PATH = "config.json"


def load_config(config_path: str) -> dict:
    path = Path(config_path)
    if not path.is_file():
        raise FileNotFoundError(f"No se encontró el archivo de configuración: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def setup_logging(config: dict) -> logging.Logger:
    log_cfg = config.get("logging", {})
    logger = logging.getLogger("sports_script")
    logger.handlers.clear()
    logger.propagate = False

    if not log_cfg.get("enabled", True):
        logger.addHandler(logging.NullHandler())
        return logger

    level = getattr(logging, str(log_cfg.get("level", "INFO")).upper(), logging.INFO)
    logger.setLevel(level)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    log_file = log_cfg.get("file")
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


def build_match_url(config: dict, date_from: str, date_to: str) -> str:
    api_cfg = config["api"]
    filters = config.get("filters", {})
    competition = filters.get("competition", "WC")
    status = filters.get("status", "FINISHED")
    base_url = api_cfg["base_url"].rstrip("/")
    return (
        f"{base_url}/matches"
        f"?competitions={competition}&status={status}"
        f"&dateFrom={date_from}&dateTo={date_to}"
    )


def get_ssl_context(config: dict):
    if config.get("api", {}).get("verify_ssl", True):
        return None
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def fetch_matches(config: dict, logger: logging.Logger) -> list:
    api_cfg = config["api"]
    filters = config.get("filters", {})
    download_cfg = config.get("download", {})

    days_back = filters.get("days_back", 7)
    today = datetime.utcnow()
    date_from = (today - timedelta(days=days_back)).strftime("%Y-%m-%d")
    date_to = today.strftime("%Y-%m-%d")

    url = build_match_url(config, date_from, date_to)
    logger.info(f"Consultando API: {url}")

    request = urllib.request.Request(
        url, headers={"X-Auth-Token": api_cfg.get("api_key", "")}
    )
    ssl_context = get_ssl_context(config)
    max_retries = download_cfg.get("max_retries", 3)
    timeout = api_cfg.get("timeout", 30)

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=ssl_context) as response:
                data = json.loads(response.read().decode("utf-8"))
                matches = data.get("matches", [])
                logger.info(f"API respondió con {len(matches)} partido(s)")
                return matches
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            last_error = e
            logger.warning(f"Intento {attempt}/{max_retries} fallido al consultar API: {e}")
            time.sleep(min(2 ** attempt, 10))

    logger.error(f"No se pudo consultar la API tras {max_retries} intentos: {last_error}")
    return []


def download_image(url: str, dest_folder: Path, config: dict, logger: logging.Logger, cache: dict) -> str:
    """Descarga una imagen y devuelve la ruta web relativa (ej: /images/16-07-2026_18-43/818.svg)."""
    if not url:
        return ""

    if url in cache:
        return cache[url]

    download_cfg = config.get("download", {})
    overwrite = download_cfg.get("overwrite", False)
    max_retries = download_cfg.get("max_retries", 3)
    timeout = config.get("api", {}).get("timeout", 30)
    ssl_context = get_ssl_context(config)

    filename = url.split("/")[-1].split("?")[0] or "escudo.png"
    dest_path = dest_folder / filename
    web_path = f"/images/{dest_folder.name}/{filename}"

    if dest_path.exists() and not overwrite:
        logger.info(f"Imagen ya existe, se omite descarga: {dest_path}")
        cache[url] = web_path
        return web_path

    for attempt in range(1, max_retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=timeout, context=ssl_context) as response:
                with dest_path.open("wb") as f:
                    f.write(response.read())
            logger.info(f"Imagen descargada: {dest_path}")
            cache[url] = web_path
            return web_path
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            logger.warning(f"Intento {attempt}/{max_retries} fallido descargando {url}: {e}")
            time.sleep(min(2 ** attempt, 10))

    logger.error(f"No se pudo descargar la imagen: {url}")
    return ""


def process_matches(raw_matches: list, config: dict, image_folder: Path, logger: logging.Logger) -> list:
    filters = config.get("filters", {})
    max_results = filters.get("max_results", 3)
    download_images = config.get("download", {}).get("download_images", True)

    # Igual que el componente original: los últimos N del rango consultado.
    selected = raw_matches[-max_results:] if max_results else raw_matches

    image_cache: dict = {}
    processed = []

    for m in selected:
        home_crest_url = m["homeTeam"].get("crest", "")
        away_crest_url = m["awayTeam"].get("crest", "")

        if download_images:
            home_crest = download_image(home_crest_url, image_folder, config, logger, image_cache)
            away_crest = download_image(away_crest_url, image_folder, config, logger, image_cache)
        else:
            home_crest = home_crest_url
            away_crest = away_crest_url

        processed.append({
            "home": {
                "name": m["homeTeam"].get("shortName") or m["homeTeam"].get("name"),
                "crest": home_crest,
            },
            "away": {
                "name": m["awayTeam"].get("shortName") or m["awayTeam"].get("name"),
                "crest": away_crest,
            },
            "score": m.get("score", {}).get("fullTime", {"home": None, "away": None}),
            "group": m.get("group"),
            "date": m.get("utcDate"),
        })

    return processed


def ensure_directories(data_folder: Path, image_folder: Path, logger: logging.Logger) -> None:
    """Crea las carpetas de datos e imágenes si todavía no existen (incluye subcarpetas intermedias)."""
    for folder in (data_folder, image_folder):
        if not folder.exists():
            folder.mkdir(parents=True, exist_ok=True)
            logger.info(f"Carpeta creada: {folder}")
        else:
            logger.info(f"Carpeta ya existente, se reutiliza: {folder}")


def save_matches_json(matches: list, data_folder: Path, json_filename: str, logger: logging.Logger) -> Path:
    data_folder.mkdir(parents=True, exist_ok=True)
    output_path = data_folder / json_filename
    with output_path.open("w", encoding="utf-8") as f:
        json.dump({"matches": matches}, f, ensure_ascii=False, indent=2)
    logger.info(f"JSON guardado en: {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Actualiza resultados deportivos y descarga imágenes.")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Ruta al archivo config.json")
    args = parser.parse_args()

    config = load_config(args.config)
    logger = setup_logging(config)

    try:
        paths_cfg = config["paths"]
        output_cfg = config.get("output", {})

        now = datetime.now()
        date_str = now.strftime(output_cfg.get("date_format", "%d-%m-%Y"))
        time_str = now.strftime(output_cfg.get("time_format", "%H-%M"))
        image_folder_name = output_cfg.get("image_folder_format", "{date}_{time}").format(
            date=date_str, time=time_str
        )

        data_folder = Path(paths_cfg["data"]) / date_str / time_str
        image_folder = Path(paths_cfg["images"]) / image_folder_name

        # Garantiza que ambas carpetas existan (data e images), aunque la API falle
        # o no haya partidos que descargar.
        ensure_directories(data_folder, image_folder, logger)

        raw_matches = fetch_matches(config, logger)
        if not raw_matches:
            logger.warning("No se obtuvieron partidos de la API. Se guardará un JSON vacío.")

        json_filename = output_cfg.get("json_filename", "matches.json").strip()
        if not json_filename:
            json_filename = "matches.json"
        if not json_filename.lower().endswith(".json"):
            json_filename += ".json"

        matches = process_matches(raw_matches, config, image_folder, logger)
        save_matches_json(matches, data_folder, json_filename, logger)

        logger.info("Proceso finalizado correctamente.")
    except Exception as e:
        logger.exception(f"Error inesperado durante la ejecución: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()