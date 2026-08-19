# sports-updater — IN-316

Ingesta de resultados deportivos desde football-data.org v4. Genera un snapshot
JSON estatico y descarga escudos y emblemas, para que el componente
`ResultadosDepor.astro` (IN-307) no consulte la API en tiempo de render.

Solo libreria estandar de Python 3.9+. No requiere `pip install`.

## Puesta en marcha

```bash
cp config.example.json config.json     # config.json esta en .gitignore
export FOOTBALL_DATA_TOKEN="tu_token"  # la variable de entorno gana sobre el archivo
python script.py
```

Ajusta `paths.data` y `paths.images` para que apunten a la carpeta `public/`
del proyecto Astro.

## Codigos de salida

| Codigo | Significado                                      |
| ------ | ------------------------------------------------ |
| 0      | Snapshot escrito correctamente                   |
| 1      | Error de configuracion o error inesperado        |
| 2      | La API no respondio — **no se escribe snapshot** |

El codigo 2 es intencional: si la API falla, el snapshot anterior se conserva
intacto y el componente sigue mostrando los ultimos resultados buenos.

## Cadencia recomendada

El plan gratuito permite 10 peticiones por minuto. El script hace **una**
peticion a la API por corrida (todas las competiciones van en el mismo
`competitions=`), mas una descarga por imagen nueva. Cada 30 minutos es
holgado:

```cron
*/30 * * * * cd /ruta/sports-updater && FOOTBALL_DATA_TOKEN=xxx /usr/bin/python3 script.py
```

## Modo de imagenes

- `images.mode = "snapshot"` (por defecto): `public/images/{fecha}/{hora}/`.
  Es el layout que pide el ticket. Cada corrida re-descarga los escudos.
- `images.mode = "shared"`: `public/images/crests/`. Los escudos se descargan
  una sola vez y se reutilizan. Recomendado en produccion: evita el crecimiento
  lineal de disco y el trafico repetido.

Cambiar de modo no requiere tocar el componente: las rutas viajan dentro del
propio JSON.

## Cuota por competicion

`filters.max_results_per_competition` limita cuantos partidos se guardan de
cada liga **antes** del tope global `max_results`. Sin esa cuota, la
competicion con mas partidos recientes (el Brasileirao juega entre semana) se
come el cupo y las ligas europeas llegan al componente con uno o ningun
partido.

```json
"filters": {
  "status": "FINISHED",
  "days_back": 10,
  "max_results_per_competition": 5,
  "max_results": 60
}
```

Guarda 5 por liga aunque el componente muestre 3: asi hay margen si una
jornada trae pocos partidos finalizados. `max_results` queda como tope duro
del tamano del snapshot.

## Contrato del snapshot

Lo consume `src/lib/resultadosDeportivos.ts` en el proyecto Astro. Cualquier
cambio de forma debe acordarse entre IN-316 e IN-307.

```json
{
  "generated_at": "2026-07-22T18:16:43Z",
  "competitions": ["WC"],
  "count": 1,
  "matches": [
    {
      "id": 537406,
      "competition": {
        "code": "WC",
        "name": "FIFA World Cup",
        "emblem": "/images/22-07-2026/18-16/wm26.png"
      },
      "status": "FINISHED",
      "utcDate": "2026-07-15T19:00:00Z",
      "stage": "SEMI_FINALS",
      "group": null,
      "home": {
        "name": "England",
        "tla": "ENG",
        "crest": "/images/22-07-2026/18-16/770.svg"
      },
      "away": {
        "name": "Argentina",
        "tla": "ARG",
        "crest": "/images/22-07-2026/18-16/762.png"
      },
      "score": { "home": 1, "away": 2 }
    }
  ]
}
```

## Se elige las competencias en base a:

códigos oficiales de competición de football-data.org. Para las principales ligas europeas que mencionas, la correspondencia es esta:

Código Competición País
🇪🇸 PD LaLiga / Primera División España
🏴 PL Premier League Inglaterra
🇩🇪 BL1 Bundesliga Alemania
🇮🇹 SA Serie A Italia
🇫🇷 FL1 Ligue 1 Francia
🇵🇹 PPL Primeira Liga Portugal
🇳🇱 DED Eredivisie Países Bajos
🏴 ELC Championship Inglaterra
🇧🇷 BSA Brasileirão Série A Brasil
🇪🇺 CL UEFA Champions League Europa
🌍 WC Copa Mundial de la FIFA Mundial
🇪🇺 EC European Championship / Eurocopa Europa
