# views/tab_ingesta_manual.py
from datetime import datetime
from pathlib import Path
import sys
import streamlit as st

# 1. Asegurar la raíz del proyecto en sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

# 2. Importación corregida de la base de datos (secop_db en lugar de connection)
from database.secop_db import guardar_licitacion_secop
from services.ai_service import (
    extraer_licitacion_con_ollama,
    verificar_conexion_ollama,
)
from utils.helpers import calcular_semaforo, crear_carpeta_licitacion


def render_tab_ingesta_manual():
    st.subheader("📋 Ingesta Manual Asistida por IA (SECOP II)")
    st.markdown(
        "Pega el enlace del proceso y el contenido copiado de la pantalla para procesarlo"
        " e ingresarlo automáticamente a PostgreSQL sin bloqueos por CAPTCHA."
    )

    ollama_activo = verificar_conexion_ollama()
    if not ollama_activo:
        st.error(
            "🔴 Servicio de Ollama desconectado. Inicie Ollama para habilitar el parsing."
        )

    with st.form("form_ingesta_manual"):
        enlace_secop = st.text_input(
            "Enlace del Proceso SECOP II *",
            placeholder="https://community.secop.gov.co/Public/Tendering/OpportunityDetail/Index?noticeUID=...",
        )

        raw_content = st.text_area(
            "Contenido Copiado del Portal SECOP II *",
            height=220,
            placeholder="Pega aquí todo el texto copiado directamente desde la página del proceso...",
        )

        modelo_llm = st.selectbox(
            "Modelo IA para Parsing",
            ["llama3.2", "llama3.1", "mistral", "gemma2"],
            index=0,
            disabled=not ollama_activo,
        )

        submitted = st.form_submit_button(
            "⚡ Procesar e Ingresar a BD",
            type="primary",
            use_container_width=True,
            disabled=not ollama_activo,
        )

    if submitted:
        if not enlace_secop.strip() or not raw_content.strip():
            st.warning("Debe ingresar tanto la URL como el contenido copiado.")
            return

        with st.spinner("Analizando datos y creando carpetas físicas..."):
            datos = extraer_licitacion_con_ollama(
                raw_content, model=modelo_llm
            )

            num_proceso = datos.get("numero_proceso", "SIN_NUMERO")
            entidad = datos.get("entidad", "SIN_ENTIDAD")
            objeto = datos.get("objeto", "")
            presupuesto = float(datos.get("presupuesto") or 0.0)
            plazo = datos.get("plazo_presentacion", "")
            obs = datos.get("observaciones", "")

            semaforo_val = calcular_semaforo(plazo)
            carpeta_val = crear_carpeta_licitacion(num_proceso)

            guardar_licitacion_secop(
                numero_proceso=num_proceso,
                entidad=entidad,
                objeto=objeto,
                presupuesto=presupuesto,
                plazo_presentacion=plazo,  # Solo se persiste la fecha/hora absoluta
                estado="EN EVALUACIÓN",
                carpeta=carpeta_val,
                enlace_secop=enlace_secop.strip(),
                observaciones=obs,
            )

            st.success(
                f"✅ Licitación **{num_proceso}** guardada correctamente en la base de datos."
            )
            st.json(
                {
                    "Número Proceso": num_proceso,
                    "Entidad": entidad,
                    "Presupuesto": f"$ {presupuesto:,.2f}",
                    "Plazo": plazo,
                    "Semáforo": semaforo_val,
                    "Carpeta Generada": carpeta_val,
                }
            )