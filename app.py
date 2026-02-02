import os
import random
import time
import base64
import uuid

import pandas as pd
import requests
import streamlit as st
from sqlalchemy import create_engine, text


# Configuración
DB_URL = os.getenv("DATABASE_URL")
EVO_URL = os.getenv("EVOLUTION_API_URL")
EVO_KEY = os.getenv("EVOLUTION_API_KEY")
INSTANCE = os.getenv("WA_INSTANCE_NAME")
PUBLIC_DOMAIN = os.getenv("PUBLIC_DOMAIN")

# --- Autodescubrimiento de Ngrok (Automatización Local) ---
if not PUBLIC_DOMAIN:
    try:
        # Ngrok expone una API local en el puerto 4040. Intentamos consultarla.
        # host.docker.internal apunta a tu máquina anfitriona desde Docker.
        resp = requests.get("http://host.docker.internal:4040/api/tunnels", timeout=1)
        if resp.status_code == 200:
            data = resp.json()
            # Buscamos el túnel que sea HTTPS
            public_url = next((t["public_url"] for t in data["tunnels"] if t["proto"] == "https"), None)
            if public_url:
                PUBLIC_DOMAIN = public_url
                print(f"✅ Ngrok detectado automáticamente: {PUBLIC_DOMAIN}")
    except Exception:
        pass  # Si falla, simplemente seguimos y mostramos el error abajo

if not PUBLIC_DOMAIN:
    st.error("⚠️ CRÍTICO: La variable PUBLIC_DOMAIN no está configurada. Los enlaces enviados serán inválidos (None/auth/...). Configure esto en su archivo .env o panel de Fly.io.")
if PUBLIC_DOMAIN and not PUBLIC_DOMAIN.startswith("https://"):
    st.warning("PUBLIC_DOMAIN no es HTTPS. Se recomienda usar siempre HTTPS para enlaces de consentimiento.")

engine = create_engine(DB_URL)

st.set_page_config(page_title="Habeas Data Manager", layout="wide")
st.title("🔐 Gestor de Autorizaciones Habeas Data")

# --- Auto-Migración de Base de Datos ---
# Esto ajusta la estructura de la DB automáticamente si ya existía con la versión anterior
def run_db_migrations():
    with engine.connect() as conn:
        try:
            # Intentar eliminar la restricción única antigua (solo teléfono)
            conn.execute(text("ALTER TABLE habeas_requests DROP CONSTRAINT IF EXISTS habeas_requests_phone_key"))
            # Asegurar que existe la nueva restricción compuesta (teléfono + campaña)
            conn.execute(text("ALTER TABLE habeas_requests ADD CONSTRAINT habeas_requests_phone_campaign_id_key UNIQUE (phone, campaign_id)"))
            conn.commit()
        except Exception as e:
            # Si falla (ej. ya existe), lo ignoramos silenciosamente o lo logueamos
            print(f"Nota de migración: {e}")

run_db_migrations()

# --- Funciones Auxiliares ---


def get_db_connection():
    return engine.connect()


def get_current_terms_version(conn):
    query = text(
        "SELECT version FROM legal_terms WHERE (valid_to IS NULL OR valid_to > NOW()) ORDER BY valid_from DESC LIMIT 1"
    )
    result = conn.execute(query).fetchone()
    return result[0] if result else None


def get_or_create_campaign(conn, name: str):
    if not name:
        return None
    existing = conn.execute(
        text("SELECT id FROM campaigns WHERE name = :name"), {"name": name}
    ).fetchone()
    if existing:
        return existing[0]
    result = conn.execute(
        text("INSERT INTO campaigns (name) VALUES (:name) RETURNING id"),
        {"name": name},
    )
    conn.commit()
    return result.fetchone()[0]


def log_send_result(conn, request_id: int, status_code: int | None, body: str | None):
    conn.execute(
        text(
            "INSERT INTO send_logs (request_id, response_status, response_body) "
            "VALUES (:request_id, :status, :body)"
        ),
        {"request_id": request_id, "status": status_code, "body": body},
    )
    conn.commit()


def send_whatsapp_message(phone, name, token, message_template):
    """Envía mensaje usando Evolution API con simulación humana"""
    url = f"{EVO_URL}/message/sendText/{INSTANCE}"
    headers = {"apikey": EVO_KEY, "Content-Type": "application/json"}

    auth_link = f"{PUBLIC_DOMAIN}/auth/{token}"
    
    try:
        message_body = message_template.format(name=name, auth_link=auth_link)
    except Exception as e:
        return None, f"Error en plantilla de mensaje: {str(e)}"

    payload = {
        "number": phone,
        "options": {"delay": 1200, "presence": "composing"},  # Simula escritura
        "textMessage": {"text": message_body},
    }

    try:
        response = requests.post(url, json=payload, headers=headers)
        return response.status_code, response.text
    except Exception as e:
        st.error(f"Error enviando a {phone}: {e}")
        return None, str(e)


DEFAULT_TEMPLATE = (
    "Hola *{name}*,\n\n"
    "Para continuar brindándote nuestro servicio, necesitamos actualizar tu autorización de tratamiento de datos.\n\n"
    "Por favor, acepta los términos aquí: {auth_link}\n\n"
    "Gracias."
)

# --- Funciones de Gestión Evolution API ---
def check_evolution_status():
    """Verifica el estado de la instancia de WhatsApp"""
    try:
        url = f"{EVO_URL}/instance/connectionState/{INSTANCE}"
        headers = {"apikey": EVO_KEY}
        resp = requests.get(url, headers=headers, timeout=2)
        if resp.status_code == 200:
            return resp.json().get("instance", {}).get("state", "unknown")
    except Exception:
        return "error"
    return "unknown"

def get_evolution_qr():
    """Obtiene el QR si la instancia no está conectada"""
    try:
        # 1. Asegurar que la instancia existe
        create_url = f"{EVO_URL}/instance/create"
        headers = {"apikey": EVO_KEY, "Content-Type": "application/json"}
        requests.post(create_url, json={"instanceName": INSTANCE}, headers=headers)

        # 2. Obtener QR
        connect_url = f"{EVO_URL}/instance/connect/{INSTANCE}"
        resp = requests.get(connect_url, headers=headers)
        if resp.status_code == 200:
            return resp.json().get("base64")
    except Exception as e:
        st.sidebar.error(f"Error obteniendo QR: {e}")
    return None

# --- Sidebar: Panel de Pruebas Rápidas ---
with st.sidebar:
    st.header("📱 Estado WhatsApp")
    
    # Verificación de estado
    wa_status = check_evolution_status()
    
    if wa_status == "open":
        st.success(f"🟢 Conectado: {INSTANCE}")
    elif wa_status == "close":
        st.warning("🔴 Desconectado")
        if st.button("Generar Código QR"):
            qr_code = get_evolution_qr()
            if qr_code:
                # El base64 a veces viene con prefijo, a veces no. Limpiamos.
                if "," in qr_code:
                    qr_code = qr_code.split(",")[1]
                try:
                    image_bytes = base64.b64decode(qr_code)
                    st.image(image_bytes, caption="Escanea con WhatsApp", width=200)
                    st.info("Recarga la página después de escanear.")
                except Exception:
                    st.error("No se pudo decodificar el QR.")
    elif wa_status == "connecting":
        st.info("🟡 Conectando...")
    else:
        st.error("❌ Error de conexión con API")
        st.caption("Verifica que el contenedor 'evolution-api' esté corriendo.")

    st.divider()
    st.header("🧪 Prueba Rápida")
    st.caption("Envía un mensaje unitario para validar el envío.")
    
    # Pre-llenado con el número solicitado (incluyendo código país 57)
    test_phone = st.text_input("Teléfono (con código país)", value="573004289163")
    test_name = st.text_input("Nombre", value="Usuario de Prueba")
    
    test_template = st.text_area(
        "Mensaje de Prueba", 
        value=DEFAULT_TEMPLATE,
        height=150,
        help="Usa {name} y {auth_link} como variables."
    )
    
    if st.button("Enviar Mensaje de Prueba", type="secondary"):
        with get_db_connection() as conn:
            # 1. Validar términos
            terms_version = get_current_terms_version(conn)
            if not terms_version:
                st.error("⚠️ No hay términos legales en la base de datos.")
            else:
                # 2. Preparar datos
                campaign_id = get_or_create_campaign(conn, "Campaña de Prueba")
                token = str(uuid.uuid4())
                
                # 3. Insertar o Actualizar solicitud (Upsert para permitir re-intentos)
                try:
                    query = text("""
                        INSERT INTO habeas_requests (
                            phone, name, token, status, expires_at, terms_version, campaign_id, language
                        ) VALUES (
                            :phone, :name, :token, 'pending', NOW() + interval '1 day', 
                            :terms_version, :campaign_id, 'es'
                        )
                        ON CONFLICT (phone, campaign_id) DO UPDATE 
                        SET token = EXCLUDED.token, status = 'pending', sent_at = NOW()
                        RETURNING id
                    """)
                    
                    result = conn.execute(query, {
                        "phone": test_phone, "name": test_name, "token": token,
                        "terms_version": terms_version, "campaign_id": campaign_id
                    })
                    request_id = result.fetchone()[0]
                    conn.commit()

                    # 4. Enviar Mensaje
                    with st.spinner("Enviando..."):
                        status, body = send_whatsapp_message(test_phone, test_name, token, test_template)
                        log_send_result(conn, request_id, status, body)
                    
                    if status == 201:
                        st.success("✅ Mensaje enviado exitosamente.")
                    else:
                        st.error(f"❌ Error al enviar: {body}")
                except Exception as e:
                    st.error(f"Error interno: {e}")

# --- Interfaz de Usuario ---

col_left, col_right = st.columns([2, 1])

with col_left:
    uploaded_file = st.file_uploader(
        "Cargar archivo CSV (Columnas: phone, name, [language])", type="csv"
    )

    campaign_name = st.text_input(
        "Nombre de campaña", value="Campaña Actualización Habeas Data"
    )

    token_valid_days = st.number_input(
        "Días de validez del enlace de consentimiento",
        min_value=1,
        max_value=365,
        value=7,
    )

    st.markdown("### 📝 Personalización del Mensaje")
    campaign_template = st.text_area(
        "Plantilla del mensaje de WhatsApp",
        value=DEFAULT_TEMPLATE,
        height=150,
        help="Variables obligatorias: {name} (Nombre del usuario) y {auth_link} (Enlace único)."
    )

with col_right:
    st.info(
        "Configure el nombre de la campaña y la vigencia de los enlaces antes de ejecutar el envío."
    )
    
    # --- Gestión de Términos Legales ---
    st.divider()
    st.subheader("📜 Reglas Habeas Data")
    with st.expander("Gestionar Términos y Condiciones"):
        with get_db_connection() as conn:
            current_ver = get_current_terms_version(conn)
            st.write(f"**Versión Actual:** {current_ver if current_ver else 'Ninguna'}")
            
            st.markdown("---")
            st.write("**Crear nueva versión**")
            new_version_name = st.text_input("Identificador de versión (ej: v2.0-2024)")
            new_terms_content = st.text_area("Texto legal completo (HTML o Texto plano)", height=200)
            
            if st.button("Guardar Nuevos Términos"):
                if new_version_name and new_terms_content:
                    try:
                        conn.execute(
                            text("INSERT INTO legal_terms (version, content) VALUES (:v, :c)"),
                            {"v": new_version_name, "c": new_terms_content}
                        )
                        conn.commit()
                        st.success(f"Versión {new_version_name} creada y activa.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error guardando términos: {e}")
                else:
                    st.warning("Complete ambos campos.")

if uploaded_file:
    df = pd.read_csv(uploaded_file)

    # Validación básica
    if "phone" not in df.columns or "name" not in df.columns:
        st.error("El CSV debe tener las columnas 'phone' y 'name'")
    else:
        st.dataframe(df.head())

        if st.button("EJECUTAR ENVÍO MASIVO", type="primary"):
            progress_bar = st.progress(0)
            status_text = st.empty()

            total = len(df)
            success_count = 0

            with get_db_connection() as conn:
                terms_version = get_current_terms_version(conn)
                if not terms_version:
                    st.error(
                        "No hay términos legales activos en la tabla legal_terms. Registre al menos una versión antes de enviar."
                    )
                else:
                    campaign_id = get_or_create_campaign(conn, campaign_name)

                    for index, row in df.iterrows():
                        phone = str(row["phone"]).strip()
                        name = row["name"]
                        language = row.get("language", "es")

                        # 1. Generar Token
                        token = str(uuid.uuid4())

                        # 2. Calcular expiración
                        expires_query = text(
                            "SELECT NOW() + (:days || ' days')::interval"
                        )
                        expires_at = conn.execute(
                            expires_query, {"days": int(token_valid_days)}
                        ).fetchone()[0]

                        # 3. Insertar en DB (Pending)
                        try:
                            insert_q = text(
                                """
                                INSERT INTO habeas_requests (
                                    phone, name, token, status, expires_at,
                                    terms_version, campaign_id, language
                                )
                                VALUES (
                                    :phone, :name, :token, 'pending', :expires_at,
                                    :terms_version, :campaign_id, :language
                                )
                                ON CONFLICT (phone, campaign_id) DO NOTHING
                                RETURNING id
                                """
                            )
                            result = conn.execute(
                                insert_q,
                                {
                                    "phone": phone,
                                    "name": name,
                                    "token": token,
                                    "expires_at": expires_at,
                                    "terms_version": terms_version,
                                    "campaign_id": campaign_id,
                                    "language": language,
                                },
                            )
                            row_db = result.fetchone()
                            conn.commit()
                            if not row_db:
                                st.warning(
                                    f"Registro duplicado o ya existente para {phone}, no se reenviará en esta ejecución."
                                )
                                continue
                            request_id = row_db[0]
                        except Exception:
                            st.warning(f"Error DB para {phone}")
                            continue

                        # 4. Enviar Mensaje
                        status_text.text(f"Enviando a {name} ({phone})...")
                        status_code, body = send_whatsapp_message(phone, name, token, campaign_template)

                        if status_code == 201:
                            success_count += 1
                        else:
                            # Marcar como failed si no fue exitoso
                            conn.execute(
                                text(
                                    "UPDATE habeas_requests SET status = 'failed' WHERE id = :id"
                                ),
                                {"id": request_id},
                            )
                            conn.commit()

                        log_send_result(conn, request_id, status_code, body)

                        # 5. Rate Limiting (Espera aleatoria entre 5 y 15 segundos)
                        time.sleep(random.uniform(5, 15))

                        # Actualizar barra
                        progress_bar.progress((index + 1) / total)

            st.success(
                f"Proceso finalizado. Mensajes enviados exitosamente: {success_count}/{total}"
            )


# --- Visualización de Estado y reenvíos ---
st.divider()
st.subheader("Estado de Solicitudes")

col_filtros, col_acciones = st.columns([3, 2])

with col_filtros:
    status_filter = st.multiselect(
        "Filtrar por estado",
        options=["pending", "accepted", "rejected", "failed"],
        default=["pending", "accepted"],
    )
    date_from = st.date_input("Desde (sent_at)", value=None)
    date_to = st.date_input("Hasta (sent_at)", value=None)

with col_acciones:
    export_button = st.button("Exportar evidencia (CSV)")
    resend_pending_button = st.button("Reenviar pendientes de campaña actual")

with get_db_connection() as conn:
    base_query = "SELECT * FROM habeas_requests WHERE 1=1"
    params = {}

    if status_filter:
        base_query += " AND status = ANY(:statuses)"
        params["statuses"] = status_filter

    if date_from:
        base_query += " AND sent_at::date >= :date_from"
        params["date_from"] = date_from

    if date_to:
        base_query += " AND sent_at::date <= :date_to"
        params["date_to"] = date_to

    df_state = pd.read_sql(base_query + " ORDER BY sent_at DESC", conn, params=params)
    
    # --- KPIs y Gráficos ---
    st.markdown("### 📊 Estadísticas de Campaña")
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    
    total_kpi = len(df_state)
    accepted_kpi = len(df_state[df_state["status"] == "accepted"])
    rejected_kpi = len(df_state[df_state["status"] == "rejected"])
    pending_kpi = len(df_state[df_state["status"] == "pending"])
    
    kpi1.metric("Total Registros", total_kpi)
    kpi2.metric("Aceptados ✅", accepted_kpi, f"{((accepted_kpi/total_kpi)*100):.1f}%" if total_kpi > 0 else "0%")
    kpi3.metric("Rechazados ❌", rejected_kpi, f"{((rejected_kpi/total_kpi)*100):.1f}%" if total_kpi > 0 else "0%")
    kpi4.metric("Pendientes ⏳", pending_kpi)

    if total_kpi > 0:
        st.bar_chart(df_state["status"].value_counts())

    st.dataframe(df_state)

    if export_button and not df_state.empty:
        export_cols = [
            "phone",
            "name",
            "status",
            "sent_at",
            "accepted_at",
            "ip_address",
            "user_agent",
            "terms_version",
        ]
        available_cols = [c for c in export_cols if c in df_state.columns]
        export_df = df_state[available_cols]
        st.download_button(
            label="Descargar evidencia CSV",
            data=export_df.to_csv(index=False).encode("utf-8"),
            file_name="habeas_evidencia.csv",
            mime="text/csv",
        )

    if resend_pending_button:
        if "id" not in df_state.columns:
            st.error("No se puede reenviar: falta columna id en la consulta.")
        else:
            pending = df_state[df_state["status"] == "pending"]
            if pending.empty:
                st.info("No hay registros pendientes para reenviar con los filtros actuales.")
            else:
                progress = st.progress(0)
                total_p = len(pending)
                sent_ok = 0

                for idx, row in pending.iterrows():
                    phone = row["phone"]
                    name = row["name"]
                    token = row["token"]
                    request_id = row["id"]

                    status_code, body = send_whatsapp_message(phone, name, token, campaign_template)
                    if status_code == 201:
                        sent_ok += 1
                    else:
                        conn.execute(
                            text(
                                "UPDATE habeas_requests SET status = 'failed' WHERE id = :id"
                            ),
                            {"id": request_id},
                        )
                        conn.commit()

                    log_send_result(conn, request_id, status_code, body)
                    time.sleep(random.uniform(5, 15))
                    progress.progress((sent_ok) / total_p)

                st.success(
                    f"Reenvío completado. Mensajes reenviados exitosamente: {sent_ok}/{total_p}"
                )

    # --- Automatización de Reintentos (> 5 días) ---
    st.divider()
    st.subheader("🤖 Automatización de Reintentos")
    
    with st.expander("Reenviar solicitudes antiguas (> 5 días sin respuesta)"):
        # Consulta para buscar pendientes con más de 5 días
        old_pending_query = text("""
            SELECT * FROM habeas_requests 
            WHERE status = 'pending' 
            AND sent_at < NOW() - INTERVAL '5 days'
        """)
        df_old = pd.read_sql(old_pending_query, conn)
        count_old = len(df_old)
        
        st.write(f"Solicitudes pendientes antiguas encontradas: **{count_old}**")
        
        if count_old > 0:
            st.info("Esta acción reenviará el mensaje a los usuarios que no han respondido en 5 días y actualizará la fecha de envío a 'hoy'.")
            if st.button("Ejecutar Reenvío Automático (> 5 días)", type="primary"):
                progress_old = st.progress(0)
                sent_old_ok = 0
                
                for idx, row in df_old.iterrows():
                    phone = row["phone"]
                    name = row["name"]
                    token = row["token"]
                    request_id = row["id"]
                    
                    # Usamos la plantilla actual configurada en la UI
                    status_code, body = send_whatsapp_message(phone, name, token, campaign_template)
                    
                    if status_code == 201:
                        sent_old_ok += 1
                        # Actualizamos sent_at para reiniciar el contador de días
                        conn.execute(
                            text("UPDATE habeas_requests SET sent_at = NOW() WHERE id = :id"),
                            {"id": request_id}
                        )
                        conn.commit()
                        
                    log_send_result(conn, request_id, status_code, body)
                    time.sleep(random.uniform(5, 15)) # Rate limit
                    progress_old.progress((idx + 1) / count_old)
                
                st.success(f"Se reenviaron {sent_old_ok} solicitudes exitosamente.")
                time.sleep(2)
                st.rerun()