import sys
from pathlib import Path
import streamlit as st

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from database.secop_db import calcular_semaforo, guardar_licitacion_secop
from services.ai_service import (
    extraer_licitacion_con_ollama,
    verificar_conexion_ollama,
)
from services.filesystem_service import crear_carpeta_licitacion


def render_tab_ingesta_manual():
    st.subheader("📋 Ingesta Manual Asistida por IA (SECOP II)")
    st.caption("Extracción inteligente de pliegos y registro directo en PostgreSQL evitando bloqueos por CAPTCHA.")

    ollama_activo = verificar_conexion_ollama()

    # Panel de Control UX
    col_input, col_info = st.columns([3, 2])

    with col_info:
        st.markdown("##### ⚙️ Estado del Asistente")
        if ollama_activo:
            st.markdown(
                """
                <div style="background: rgba(34,197,94,0.1); border: 1px solid #22c55e; border-radius: 8px; padding: 12px; margin-bottom: 15px;">
                    <span style="color: #4ade80; font-weight: 700;">🟢 Ollama Conectado</span>
                    <p style="color: #cbd5e1; font-size: 0.82rem; margin-top: 4px; margin-bottom: 0;">
                        El motor de procesamiento de lenguaje natural está listo para estructurar el pliego.
                    </p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                """
                <div style="background: rgba(239,68,68,0.1); border: 1px solid #ef4444; border-radius: 8px; padding: 12px; margin-bottom: 15px;">
                    <span style="color: #f87171; font-weight: 700;">🔴 Ollama Desconectado</span>
                    <p style="color: #cbd5e1; font-size: 0.82rem; margin-top: 4px; margin-bottom: 0;">
                        Inicie el servicio de Ollama en su servidor local para habilitar el parsing.
                    </p>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.markdown("##### 💡 Instrucciones Rápida")
        st.markdown(
            """
            1. **Enlace:** Copia la URL del detalle del proceso en SECOP II.
            2. **Contenido:** Selecciona todo el texto de la pantalla del portal (`Ctrl + A`) y pégalo.
            3. **Procesar:** El asistente estructurará el número de proceso, presupuesto, entidad y vigencia.
            """
        )

    with col_input:
        with st.form("form_ingesta_manual", clear_on_submit=False):
            enlace_secop = st.text_input(
                "Enlace del Proceso SECOP II *",
                placeholder="https://community.secop.gov.co/Public/Tendering/OpportunityDetail/Index...",
            )

            raw_content = st.text_area(
                "Contenido Copiado del Portal SECOP II *",
                height=240,
                placeholder="Pega aquí el texto copiado de la pantalla...",
            )

            col_m1, col_m2 = st.columns(2)
            with col_m1:
                modelo_llm = st.selectbox(
                    "Modelo IA",
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
            st.warning("⚠️ Debe ingresar tanto la URL como el contenido del portal.")
            return

        with st.spinner("🤖 Extrayendo parámetros con Ollama y creando estructura local..."):
            datos = extraer_licitacion_con_ollama(raw_content, model=modelo_llm)

            num_proceso = datos.get("numero_proceso", "SIN_NUMERO")
            entidad = datos.get("entidad", "SIN_ENTIDAD")
            objeto = datos.get("objeto", "")
            presupuesto = float(datos.get("presupuesto") or 0.0)
            plazo = datos.get("plazo_presentacion", "")
            obs = datos.get("observaciones", "")

            carpeta_val = crear_carpeta_licitacion(num_proceso)
            semaforo_val = calcular_semaforo(plazo)

            guardar_licitacion_secop(
                numero_proceso=num_proceso,
                entidad=entidad,
                objeto=objeto,
                presupuesto=presupuesto,
                plazo_presentacion=plazo,
                estado="EN EVALUACIÓN",
                carpeta=carpeta_val,
                enlace_secop=enlace_secop.strip(),
                observaciones=obs,
            )

            st.toast(f"✅ Proceso {num_proceso} registrado exitosamente.", icon="🎉")

            st.markdown("---")
            st.markdown("### 📊 Resultado de la Ingesta")
            
            m1, m2, m3 = st.columns(3)
            with m1:
                st.metric("Número Proceso", num_proceso)
            with m2:
                st.metric("Presupuesto Oficial", f"$ {presupuesto:,.2f}")
            with m3:
                st.metric("Semáforo Calculado", semaforo_val)

            st.markdown(
                f"""
                <div style="background: #1e222d; border: 1px solid #2d3345; padding: 12px; border-radius: 8px; margin-top: 10px;">
                    <div style="color: #a0a6b5; font-size: 0.8rem; font-weight: 700;">ENTIDAD COMPRADORA</div>
                    <div style="color: #ffffff; font-size: 1.05rem; font-weight: 600;">{entidad}</div>
                    <div style="color: #a0a6b5; font-size: 0.8rem; font-weight: 700; margin-top: 8px;">CARPETA GENERADA</div>
                    <div style="color: #64b5f6; font-family: monospace; font-size: 0.85rem;">{carpeta_val}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )