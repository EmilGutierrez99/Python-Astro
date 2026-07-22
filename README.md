# Cómo configurar `config.json`

Este archivo le dice al script **de dónde sacar los resultados** y **dónde guardarlos**. No hay que tocar el `script.py` para nada — todo se configura acá.

Antes de ejecutar el script por primera vez, hay que abrir `config.json` con el Bloc de notas (o cualquier editor de texto) y revisar/completar los campos de abajo.

⚠️ **Regla de oro del JSON:** no borrar ninguna coma `,`, ninguna llave `{ }`, ni ninguna comilla `" "`. Si se borra algo sin querer, el script no va a poder leer el archivo. Si tienen dudas, es más seguro copiar y pegar un bloque de ejemplo completo y solo cambiar los valores de adentro.

---

## 1. Bloque `api` — datos de conexión a la fuente de resultados

```json
"api": {
    "base_url": "https://api.football-data.org/v4",
    "api_key": "TU_API_KEY_AQUI",
    "timeout": 30,
    "verify_ssl": true
}
```

| Campo | Qué es | Qué poner |
|---|---|---|
| `base_url` | La dirección del proveedor de datos deportivos. | Normalmente **no se toca**. Solo cambiarlo si en algún momento se cambia de proveedor de API. |
| `api_key` | La "contraseña" que identifica la cuenta que consulta los datos. | Reemplazar `TU_API_KEY_AQUI` por la clave real que les dieron. Va entre comillas, tal cual: `"api_key": "abc123xyz"` |
| `timeout` | Cuántos segundos espera el script una respuesta antes de darse por vencido. | Dejarlo en `30` salvo que la conexión a internet sea muy lenta (ahí se puede subir a `60`). |
| `verify_ssl` | Si valida el certificado de seguridad del sitio. | Dejarlo siempre en `true`. Solo cambiarlo a `false` si alguien de sistemas se lo indica expresamente. |

---

## 2. Bloque `paths` — dónde se guardan los resultados

```json
"paths": {
    "data": "C:/ruta/al/proyecto/public/data",
    "images": "C:/ruta/al/proyecto/public/images"
}
```

| Campo | Qué es | Qué poner |
|---|---|---|
| `data` | La carpeta del proyecto Astro donde se va a guardar el JSON con los resultados. | La ruta **completa** hasta la carpeta `public/data` del proyecto. Ejemplo: `"C:/Users/usuario/Documents/astroplate/public/data"` |
| `images` | La carpeta del proyecto Astro donde se van a guardar los escudos de los equipos. | La ruta **completa** hasta la carpeta `public/images` del proyecto. Ejemplo: `"C:/Users/usuario/Documents/astroplate/public/images"` |

📌 **Importante:** usar siempre `/` (barra normal), aunque estén en Windows. Ejemplo correcto: `"C:/Users/usuario/proyecto/public/data"`. Si usan `\` (barra invertida) el archivo puede dar error al leerse.

📌 Si esta ruta está mal (por ejemplo, escriben solo `"public/data"` sin la ruta completa), el script va a crear las carpetas donde sea que esté guardado el `script.py`, no dentro del proyecto. Siempre usar la ruta completa.

---

## 3. Bloque `output` — nombre y formato de los archivos generados

```json
"output": {
    "date_format": "%d-%m-%Y",
    "time_format": "%H-%M",
    "image_folder_format": "{date}_{time}",
    "json_filename": "matches.json"
}
```

| Campo | Qué es | Qué poner |
|---|---|---|
| `date_format` | Cómo se arma el nombre de la carpeta de fecha. | Dejarlo tal cual: `"%d-%m-%Y"` (da como resultado, por ejemplo, `16-07-2026`). No tocar salvo indicación de un desarrollador. |
| `time_format` | Cómo se arma el nombre de la carpeta de hora. | Dejarlo tal cual: `"%H-%M"` (da como resultado, por ejemplo, `19-43`). No tocar. |
| `image_folder_format` | Cómo se arma el nombre de la carpeta de imágenes. | Dejarlo tal cual: `"{date}_{time}"`. No tocar. |
| `json_filename` | **El nombre del archivo JSON resultante.** Este es el campo que sí pueden y deben cambiar según la competición que estén mostrando. | Ejemplos: `"FifaWorldCup.json"`, `"LaLigaEs.json"`, `"CopaAmerica.json"`. Debe terminar en `.json`. Si lo dejan vacío, el script usa `matches.json` por defecto. |

---

## 4. Bloque `filters` — qué partidos traer

```json
"filters": {
    "competition": "WC",
    "status": "FINISHED",
    "days_back": 7,
    "max_results": 3
}
```

| Campo | Qué es | Qué poner |
|---|---|---|
| `competition` | El código de la competición de la que se quieren los resultados. | Ejemplos comunes: `"WC"` (Mundial), `"PL"` (Premier League), `"PD"` (La Liga España), `"CL"` (Champions League), `"SA"` (Serie A Italia), `"BL1"` (Bundesliga). Si tienen dudas de qué código usar, cualquier desarrollador puede confirmarlo con el proveedor de la API. |
| `status` | Qué estado deben tener los partidos. | Dejarlo en `"FINISHED"` para mostrar solo partidos ya jugados y con resultado. |
| `days_back` | Cuántos días hacia atrás buscar resultados. | `7` trae los resultados de la última semana. Se puede subir o bajar según lo que necesiten mostrar. |
| `max_results` | Cuántos partidos mostrar como máximo. | `3` muestra los últimos 3 partidos jugados dentro del rango de `days_back`. |

---

## 5. Bloque `download` — cómo se descargan las imágenes de los equipos

```json
"download": {
    "overwrite": false,
    "download_images": true,
    "max_retries": 3
}
```

| Campo | Qué es | Qué poner |
|---|---|---|
| `overwrite` | Si vuelve a descargar una imagen que ya existe. | Dejarlo en `false` (no hace falta re-descargar lo que ya está). |
| `download_images` | Si se descargan o no los escudos de los equipos. | Dejarlo en `true`. Solo poner `false` si no quieren descargar imágenes por algún motivo puntual. |
| `max_retries` | Cuántas veces reintenta si falla una descarga o la conexión a la API. | `3` es un buen valor por defecto. |

---

## 6. Bloque `logging` — el registro de lo que hizo el script

```json
"logging": {
    "enabled": true,
    "level": "INFO",
    "file": "logs/script.log"
}
```

| Campo | Qué es | Qué poner |
|---|---|---|
| `enabled` | Si se guarda un registro de la ejecución. | Dejarlo en `true`, ayuda mucho a detectar errores. |
| `level` | Qué tan detallado es el registro. | Dejarlo en `"INFO"`. |
| `file` | Dónde se guarda el archivo de registro. | Dejarlo en `"logs/script.log"`. Se crea solo, no hay que crear la carpeta a mano. |

---

## Ejemplo completo ya rellenado (Mundial de Fútbol)

```json
{
    "api": {
        "base_url": "https://api.football-data.org/v4",
        "api_key": "abc123xyz",
        "timeout": 30,
        "verify_ssl": true
    },
    "paths": {
        "data": "C:/Users/usuario/Documents/astroplate/public/data",
        "images": "C:/Users/usuario/Documents/astroplate/public/images"
    },
    "output": {
        "date_format": "%d-%m-%Y",
        "time_format": "%H-%M",
        "image_folder_format": "{date}_{time}",
        "json_filename": "FifaWorldCup.json"
    },
    "filters": {
        "competition": "WC",
        "status": "FINISHED",
        "days_back": 7,
        "max_results": 3
    },
    "download": {
        "overwrite": false,
        "download_images": true,
        "max_retries": 3
    },
    "logging": {
        "enabled": true,
        "level": "INFO",
        "file": "logs/script.log"
    }
}
```

Para cambiar a otra competición (ejemplo, La Liga Española), solo hace falta cambiar dos campos:
```json
"filters": { "competition": "PD", ... }
"output": { "json_filename": "LaLigaEs.json", ... }
```

---

## Los 2 únicos campos que normalmente van a necesitar cambiar seguido

En el día a día, lo más probable es que solo toquen esto:

1. **`filters.competition`** → para elegir qué torneo mostrar.
2. **`output.json_filename`** → para que el archivo tenga un nombre reconocible según ese torneo.

El resto de los campos se configura **una sola vez** al instalar el script y no hace falta volver a tocarlo.

---

## Checklist antes de ejecutar el script

- [ ] `api.api_key` tiene la clave real (no dice `TU_API_KEY_AQUI`).
- [ ] `paths.data` y `paths.images` tienen la ruta **completa** al proyecto, con `/` en vez de `\`.
- [ ] `output.json_filename` tiene el nombre que quieren ver (ej. `FifaWorldCup.json`).
- [ ] `filters.competition` tiene el código correcto del torneo que quieren mostrar.
- [ ] No falta ninguna coma ni comilla en el archivo (si tienen dudas, comparen con el "Ejemplo completo" de arriba).

Si después de revisar esto el script sigue sin funcionar, revisar el archivo `logs/script.log` — ahí queda anotado el motivo exacto del error.
