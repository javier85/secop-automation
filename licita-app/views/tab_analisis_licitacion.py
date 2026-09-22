import sys
from pathlib import Path
import streamlit as st

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from database.secop_db import cargar_licitaciones, registrar_auditoria_ia
from services.ai_service import (
    analizar_licitacion_con_gesstionando,
    verificar_conexion_ollama,
)


def render_tab_analisis_licitacion():
    st.subheader("🏛️ Auditoría y Viabilidad de Licitaciones - GESSTIONANDO CONSULTING S.A.S.")
    st.markdown(
        "Sube los documentos del proceso (CDP, Estudios Previos, Pliegos, Anexos en PDF, Word o Excel) "
        "para ejecutar el análisis financiero, tributario y jurídico bajo normativa colombiana."
    )

    ollama_activo = verificar_conexion_ollama()
    if not ollama_activo:
        st.error("🔴 Servicio de Ollama desconectado. Inicie Ollama para realizar el análisis.")

    df_lics = cargar_licitaciones()
    opciones_proceso = ["Crear / Proceso Nuevo"] + (df_lics["numero_proceso"].tolist() if not df_lics.empty else [])

    col1, col2 = st.columns([2, 1])
    with col1:
        proceso_sel = st.selectbox("Asociar a Proceso Existente (Opcional)", opciones_proceso)
    with col2:
        modelo_llm = st.selectbox(
            "Modelo IA",
            ["llama3.2", "llama3.1", "mistral", "gemma2"],
            index=0,
            disabled=not ollama_activo
        )

    archivos_cargados = st.file_uploader(
        "Adjuntar Documentos de la Licitación (PDF, DOCX, XLSX, TXT)",
        type=["pdf", "docx", "xlsx", "xls", "txt"],
        accept_multiple_files=True,
    )

    if st.button("🔍 Ejecutar Auditoría Exhaustiva", type="primary", use_container_width=True, disabled=not ollama_activo):
        if not archivos_cargados:
            st.warning("Debe adjuntar al menos un documento para analizar.")
            return

        archivos_dict = {f.name: f.getvalue() for f in archivos_cargados}
        num_proc = proceso_sel if proceso_sel != "Crear / Proceso Nuevo" else "PROCESO_NUEVO"

        with st.spinner("Analizando pliegos y generando dictamen con Ollama..."):
            try:
                informe_resultado = analizar_licitacion_con_gesstionando(
                    archivos_dict=archivos_dict,
                    numero_proceso=num_proc,
                    model=modelo_llm
                )

                # Si el proceso existe en BD, actualizar estado a 'AUDITADO POR IA' y guardar dictamen
                if proceso_sel != "Crear / Proceso Nuevo":
                    registrar_auditoria_ia(
                        numero_proceso=proceso_sel,
                        dictamen_completo=informe_resultado  # <-- CORREGIDO: resumen_dictamen por dictamen_completo
                    )
                    st.toast(f"✅ Proceso {proceso_sel} actualizado a 'AUDITADO POR IA' en la base de datos.", icon="💾")

                st.success("✅ Auditoría completada con éxito.")
                st.markdown("---")
                st.markdown(informe_resultado)

                # Botón opcional por si el usuario desea guardar el informe individualmente
                st.download_button(
                    label="📥 Descargar Informe de Evaluación (.md)",
                    data=informe_resultado,
                    file_name=f"Informe_Viabilidad_{num_proc}.md",
                    mime="text/markdown",
                    use_container_width=True
                )

            except Exception as e:
                st.error(f"Error durante el procesamiento del análisis: {str(e)}")