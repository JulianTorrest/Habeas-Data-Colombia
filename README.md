# Sistema de Gestión de Habeas Data (WhatsApp)

Este sistema permite solicitar masivamente la autorización de tratamiento de datos personales a través de WhatsApp, registrando la evidencia legal (IP, fecha, hora) de la aceptación o rechazo.

## 📂 Estructura del Proyecto

Para que Docker funcione correctamente, organiza tus archivos así:

```
/Habeas-Data
├── .env                    # Variables de entorno (Crear basado en ejemplo)
├── docker-compose.yml      # Orquestación de servicios
├── init.sql                # Script de base de datos
├── /admin-app              # Panel de Administración
│   ├── app.py
│   ├── Dockerfile
│   └── requirements.txt
├── /fastapi-landing        # Backend y Vistas Públicas
│   ├── main.py
│   ├── Dockerfile          # (Nuevo archivo provisto)
│   ├── requirements.txt
│   ├── /templates          # Archivos HTML (Jinja2)
│   └── /static             # Archivos PDF/CSS
└── /postgres-data          # (Se crea automático)
```

## 🚀 Opción 1: Ejecución Local (Recomendada para un solo uso)

Ideal si vas a correr la campaña una sola vez desde tu computador.

### Prerrequisitos
1.  Instalar **Docker Desktop**.
2.  Instalar **Ngrok** (para hacer público tu servidor local).

### Paso 1: Configuración
1.  Crea el archivo `.env` con tus credenciales (ver ejemplo abajo).
2.  En una terminal, levanta los servicios:
    ```bash
    docker-compose up --build
    ```

### Paso 2: Exponer a Internet
1.  Abre otra terminal y ejecuta Ngrok apuntando al puerto de FastAPI (8000):
    ```bash
    ngrok http 8000
    ```
2.  Copia la URL HTTPS que te da Ngrok (ej: `https://a1b2.ngrok-free.app`).
3.  Pega esa URL en tu archivo `.env` en la variable `PUBLIC_DOMAIN`.
4.  Reinicia los contenedores si cambiaste el `.env` (`Ctrl+C` y `docker-compose up`).

### Paso 3: Conectar WhatsApp
1.  Ve a `http://localhost:8501` (Panel de Admin).
2.  El sistema intentará conectar con la Evolution API.
3.  **Importante:** La primera vez, debes escanear el QR.
    *   Ve a los logs de la consola de Docker, o usa Postman para consultar el QR a la Evolution API si no tienes interfaz visual para ello.
    *   Endpoint para ver QR (si Evolution tiene UI activada): `http://localhost:8080`.

### Paso 4: Lanzar Campaña
1.  Sube tu CSV (columnas: `phone`, `name`).
2.  Configura el nombre de la campaña.
3.  Haz clic en "EJECUTAR ENVÍO MASIVO".

---

## ☁️ Opción 2: Despliegue en Fly.io

Para dejar el servicio corriendo 24/7 en la nube.

1.  Instala `flyctl` y haz login (`fly auth login`).
2.  Inicializa la app: `fly launch`.
3.  **Base de Datos:** Fly te preguntará si quieres crear una Postgres DB. Di que sí.
4.  **Volúmenes:** Para la Evolution API, necesitas persistencia:
    ```bash
    fly volumes create evolution_data --size 1
    ```
5.  **Secretos:** Configura las variables del `.env` en Fly:
    ```bash
    fly secrets set EVOLUTION_API_KEY=tu_clave ...
    ```
6.  Despliega: `fly deploy`.

---

## ⚙️ Configuración (.env Ejemplo)

```env
POSTGRES_USER=admin
POSTGRES_PASSWORD=secreto
POSTGRES_DB=habeas_db
DATABASE_URL=postgresql://admin:secreto@postgres-db:5432/habeas_db

EVOLUTION_API_URL=http://evolution-api:8080
EVOLUTION_API_KEY=mi_api_key_segura
WA_INSTANCE_NAME=mi-empresa

# URL de Ngrok o Dominio real
PUBLIC_DOMAIN=https://xxxx.ngrok-free.app
```

## 🛠️ Solución de Problemas Comunes

*   **Error de conexión a DB:** Asegúrate de que el contenedor `postgres-db` esté "healthy" antes de que arranquen los otros.
*   **WhatsApp no envía:** Verifica que la instancia en Evolution API esté en estado "open" (conectada).
*   **Enlace expirado:** Revisa la zona horaria de tu servidor/Docker.
```

### Resumen de Pasos para ti ahora:

1.  **Reorganiza las carpetas** como se muestra en el diagrama del README.
2.  **Aplica los cambios** en `app.py` y `main.py`.
3.  **Crea los archivos nuevos** (`Dockerfile` para FastAPI y los HTML en `templates/`).
4.  **Crea el `.env`**.
5.  Ejecuta `docker-compose up --build`.

<!--
[PROMPT_SUGGESTION]¿Cómo puedo ver el código QR de la Evolution API para escanearlo desde mi celular?[/PROMPT_SUGGESTION]
[PROMPT_SUGGESTION]¿Podrías darme el código para los archivos HTML faltantes (success.html, rejected.html, message.html)?[/PROMPT_SUGGESTION]
