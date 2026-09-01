import io
import pandas as pd
import streamlit as st
from database.cotizaciones_db import (
    convertir_df_a_excel,
    guardar_items_masivos_db,
    obtener_banco_items,
)
from services.ai_service import (
    homologar_item_con_ia,
    procesar_homologacion_masiva,
    verificar_conexion_ollama,
)
from services.excel_service import leer_excel_items


def _convertir_df_a_excel(df: pd.DataFrame) -> bytes:
    """Genera un archivo Excel en memoria a partir del resultado de la homologación."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Homologacion_IA", index=False)
    output.seek(0)
    return output.getvalue()


def render_tab_homologador():
    st.subheader("🤖 Homologador Semántico de Insumos (IA)")
    st.markdown(
        "Utiliza modelos locales en Ollama para homologar descripciones de"
        " licitaciones contra el catálogo histórico de precios y unidades."
    )

    # 1. Verificación del estado del servidor Ollama
    ollama_activo = verificar_conexion_ollama()
    col_status, col_model = st.columns([2, 2])

    with col_status:
        if ollama_activo:
            st.success("🟢 Servicio de Ollama activo y respondiendo.")
        else:
            st.error(
                "🔴 No se pudo conectar con Ollama. Verifica que el servicio esté"
                " activo en http://localhost:11434."
            )

    with col_model:
        modelo_ia = st.selectbox(
            "Modelo LLM Seleccionado",
            ["llama3.2", "llama3.1", "mistral", "gemma2"],
            index=0,
            disabled=not ollama_activo,
        )

    st.markdown("---")

    # 2. Modalidades de Homologación
    modo = st.radio(
        "Modo de Trabajo",
        ["🔍 Consulta Individual", "📁 Homologación Masiva (Excel / CSV)"],
        horizontal=True,
    )

    # Carga de catálogo en la pestaña
    if st.button("🔄 Recargar Catálogo BD"):
        st.cache_data.clear()
        st.rerun()

    catalogo = obtener_banco_items()

    if catalogo.empty:
        st.warning("⚠️ El catálogo histórico está vacío en el estado actual.")
    else:
        st.success(
            f"✅ Catálogo activo con **{len(catalogo)}** ítems listos para la IA."
        )

    # 3. Consulta Unitaria
    if modo == "🔍 Consulta Individual":
        st.markdown("#### Test de Coincidencia Unitaria")
        desc_test = st.text_input(
            "Descripción del Insumo a Requerir",
            placeholder="Ej: Mantenimiento y recarga de extintor Solkaflam 3700g",
        )

        if st.button(
            "⚡ Homologar con IA",
            type="primary",
            disabled=not ollama_activo or not desc_test.strip(),
        ):
            with st.spinner("Analizando similitud semántica con Ollama..."):
                resultado = homologar_item_con_ia(
                    desc_test, catalogo, model=modelo_ia
                )

            st.markdown("##### Resultado del Análisis")
            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric(
                    "Confianza Match", f"{resultado.get('confianza', 0)}%"
                )
            with c2:
                st.metric(
                    "Unidad Sugerida", resultado.get("unidad_medida", "UNIDAD")
                )
            with c3:
                st.metric(
                    "Costo Sugerido",
                    f"${resultado.get('costo_sugerido', 0.0):,.2f}",
                )

            st.info(
                f"**Ítem Sugerido:** {resultado.get('item_sugerido') or 'Sin coincidencia clara'}\n\n"
                f"**Justificación Técnica:** {resultado.get('justificacion', 'N/A')}"
            )

    # 4. Homologación Masiva mediante Excel/CSV
    else:
        st.markdown("#### Carga y Procesamiento Masivo")
        uploaded_file = st.file_uploader(
            "Cargar archivo de requerimientos (.xlsx, .csv)",
            type=["xlsx", "xls", "csv"],
            key="file_homologador",
        )

        if uploaded_file is not None:
            try:
                df_req = leer_excel_items(uploaded_file)
                st.write(
                    f"📋 Se cargaron **{len(df_req)}** ítems para homologación."
                )
                st.dataframe(df_req.head(5), use_container_width=True)

                if st.button(
                    "🚀 Iniciar Homologación Masiva",
                    type="primary",
                    disabled=not ollama_activo,
                ):
                    with st.spinner(
                        f"Procesando {len(df_req)} ítems con {modelo_ia}..."
                    ):
                        st.session_state["df_resultado"] = (
                            procesar_homologacion_masiva(
                                df_req, catalogo, model=modelo_ia
                            )
                        )
                    st.success("✅ Procesamiento masivo completado.")

                if "df_resultado" in st.session_state:
                    df_res = st.session_state["df_resultado"]

                    st.dataframe(
                        df_res,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Costo Sugerido (COP)": st.column_config.NumberColumn(
                                format="$ %,.2f"
                            ),
                            "Confianza (%)": st.column_config.NumberColumn(
                                format="%d %%"
                            ),
                        },
                    )

                    col_descarga, col_guardar = st.columns(2)

                    with col_descarga:
                        st.download_button(
                            label="📥 Descargar Resultado en Excel",
                            data=_convertir_df_a_excel(df_res),
                            file_name="homologacion_resultado.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True,
                        )

                    with col_guardar:
                        if st.button(
                            "💾 Guardar Ítems en Base de Datos",
                            type="primary",
                            use_container_width=True,
                        ):
                            exito, mensaje = guardar_items_masivos_db(df_res)
                            if exito:
                                st.success(f"✅ {mensaje}")
                                del st.session_state["df_resultado"]
                                st.rerun()
                            else:
                                st.error(
                                    f"❌ Error al insertar en la BD: {mensaje}"
                                )

            except Exception as e:
                st.error(f"Error al procesar el archivo: {str(e)}")