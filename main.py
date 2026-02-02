import os
from datetime import datetime

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, text

app = FastAPI()
templates = Jinja2Templates(directory="templates")

DB_URL = os.getenv("DATABASE_URL")
engine = create_engine(DB_URL)

# Montar archivos estáticos (asegúrate de crear la carpeta 'static' y poner ahí tu PDF)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/auth/{token}", response_class=HTMLResponse)
async def show_consent(token: str, request: Request):
    client_ip = request.client.host
    user_agent = request.headers.get("user-agent")

    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT h.id, h.name, h.status, h.accepted_at, h.ip_address, h.terms_version, h.expires_at, l.content "
                "FROM habeas_requests h "
                "LEFT JOIN legal_terms l ON h.terms_version = l.version "
                "WHERE h.token = :token"
            ),
            {"token": token},
        ).fetchone()

        if not result:
            return templates.TemplateResponse(
                "message.html",
                {"request": request, "title": "Token inválido", "message": "El enlace proporcionado no es válido."},
                status_code=404,
            )

        (
            request_id,
            name,
            status,
            accepted_at,
            ip_address,
            terms_version,
            expires_at,
            terms_content,
        ) = result

        # Verificar expiración
        if expires_at and datetime.now() > expires_at:
            return templates.TemplateResponse(
                "message.html",
                {"request": request, "title": "Enlace expirado", "message": "El enlace de autorización ha expirado. Solicita un nuevo enlace para continuar."},
                status_code=410,
            )

        # Vistas según estado actual
        if status == "accepted":
            # MEJORA: Permitir revocación. Pasamos un flag 'allow_revoke' para que la plantilla pueda mostrar un botón de "Revocar"
            return templates.TemplateResponse("already_accepted.html", {
                "request": request, 
                "name": name, 
                "accepted_at": accepted_at, 
                "token": token,
                "allow_revoke": True 
            })

        if status == "rejected":
            return templates.TemplateResponse("already_rejected.html", {"request": request, "name": name})

        # Estado pending/failed: mostrar formulario de consentimiento
        return templates.TemplateResponse("consent_form.html", {
            "request": request, 
            "name": name, 
            "token": token, 
            "client_ip": client_ip, 
            "user_agent": user_agent,
            "legal_content": terms_content  # Pasamos el contenido legal a la plantilla
        })


@app.post("/auth/{token}", response_class=HTMLResponse)
async def handle_consent(token: str, request: Request, decision: str = Form(...), terms_accepted: bool = Form(False)):
    client_ip = request.client.host
    user_agent = request.headers.get("user-agent")

    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT h.id, h.name, h.status, h.expires_at, l.content FROM habeas_requests h LEFT JOIN legal_terms l ON h.terms_version = l.version WHERE h.token = :token"),
            {"token": token},
        ).fetchone()

        if not result:
            return templates.TemplateResponse(
                "message.html",
                {"request": request, "title": "Token inválido o ya procesado", "message": "El enlace proporcionado no es válido o tu respuesta ya fue registrada."},
                status_code=404,
            )

        request_id, name, current_status, expires_at, terms_content = result

        # MEJORA: Verificar expiración también al recibir el POST (Seguridad)
        if expires_at and datetime.now() > expires_at:
            return templates.TemplateResponse(
                "message.html",
                {"request": request, "title": "Enlace expirado", "message": "El tiempo límite para responder ha finalizado."},
                status_code=410,
            )

        # VALIDACIÓN: Checkbox obligatorio solo para ACEPTAR
        if decision == "accept" and not terms_accepted:
            return templates.TemplateResponse("consent_form.html", {
                "request": request, 
                "name": name, 
                "token": token, 
                "client_ip": client_ip, 
                "user_agent": user_agent,
                "legal_content": terms_content,
                "error": "⚠️ Debes marcar la casilla para aceptar los términos."
            })

        new_status = "accepted" if decision == "accept" else "rejected"

        try:
            conn.execute(
                text(
                    """
                    UPDATE habeas_requests
                    SET status = :status,
                        accepted_at = :now,
                        ip_address = :ip,
                        user_agent = :ua,
                        updated_at = NOW()
                    WHERE id = :id
                    """
                ),
                {
                    "status": new_status,
                    "now": datetime.now(),
                    "ip": client_ip,
                    "ua": user_agent,
                    "id": request_id,
                },
            )
            conn.commit()

            if new_status == "accepted":
                return templates.TemplateResponse("success.html", {"request": request, "name": name, "token": token})
            else:
                return templates.TemplateResponse("rejected.html", {"request": request})

        except Exception as e:
            return templates.TemplateResponse(
                "message.html",
                {"request": request, "title": "Error del Servidor", "message": "Ocurrió un error al procesar tu solicitud."},
                status_code=500,
            )