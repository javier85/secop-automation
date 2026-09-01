# views/tab_banco_items.py
import io
import pandas as pd
import streamlit as st
from sqlalchemy import text
from database.cotizaciones_db import (
    buscar_items_globales,
    guardar_cambios_bd, 
    obtener_banco_items, 
    convertir_df_a_excel,
)
from database.connection import get_engine

# ==========================================
# HELPER: FORMATO PESOS COLOMBIANOS (COP)
# ==========================================
def formato_cop(valor: float) -> str:
    """Formatea un número flotante a moneda COP: $ 46.750,04"""
    if valor is None or pd.isna(valor):
        return "$ 0,00"
    # Formatear estándar y reemplazar coma por punto de miles y punto por coma decimal
    return f"$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

# ==========================================
# HELPER: EXPORTAR A EXCEL
# ==========================================
def _convertir_df_a_excel(df: pd.DataFrame) -> bytes:
    """Convierte un DataFrame a archivo Excel binario en memoria."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Banco_Items")
    return output.getvalue()

def render_tab_banco_items():
    st.subheader("🔍 Banco de Ítems e Insumos Históricos")
    st.markdown(
        "Explora y edita el histórico de precios y costos unitarios de los artículos cotizados."
    )

    # 1. Filtros y Búsqueda
    col_search, col_clean = st.columns([4, 1])
    with col_search:
        query = st.text_input(
            "🔎 Buscar por descripción o palabra clave",
            placeholder="Ej: Extintor, Guantes, Arnés...",
            key="search_banco_items",
        )
    with col_clean:
        st.markdown(
            "<div style='margin-top: 28px;'></div>", unsafe_allow_html=True
        )
        if st.button("🔄 Refrescar", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    # 2. Carga de datos desde PostgreSQL
    df_items = obtener_banco_items(busqueda=query)

    if df_items.empty:
        st.warning(
            "⚠️ No se encontraron ítems que coincidan con el criterio de búsqueda."
        )
        return

    st.caption(f"Total de artículos encontrados: **{len(df_items)}**")

    # 3. Tabla de Resultados e Interfaz Visual con Link Clickeable
    edited_df = st.data_editor(
        df_items,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        key="editor_banco_items",
        disabled=["ID", "Número del Proceso", "Valor Total", "Fecha Registro"],
        column_config={
            "ID": st.column_config.NumberColumn("ID", disabled=True),
            "Número del Proceso": st.column_config.TextColumn(
                "Proceso / Licitación", disabled=True, width="medium"
            ),
            "Descripción": st.column_config.TextColumn(
                "Descripción", width="large"
            ),
            "Unidad": st.column_config.TextColumn("Unidad", width="small"),
            "Cantidad": st.column_config.NumberColumn(
                "Cantidad", format="%d", min_value=1
            ),
            "Valor Unitario": st.column_config.NumberColumn(
                "Valor Unitario", format="$ %.2f", min_value=0.0
            ),
            "Valor Total": st.column_config.NumberColumn(
                "Valor Total", format="$ %.2f", disabled=True
            ),
            "Enlace / Proveedor": st.column_config.LinkColumn(
                "Enlace / Proveedor",
                display_text="🔗 Abrir Enlace",
                validate="^https?://.*",
                width="medium",
            ),
            "Fecha Registro": st.column_config.DatetimeColumn(
                "Fecha", format="DD/MM/YYYY", disabled=True
            ),
        },
    )

    # 4. Acciones y Persistencia
    cambios = st.session_state.get("editor_banco_items", {})
    st.markdown("---")
    col_btn1, col_btn2 = st.columns(2)

    with col_btn1:
        if st.button(
            "💾 Guardar Cambios en Base de Datos",
            type="primary",
            disabled=not (cambios.get("edited_rows") or cambios.get("deleted_rows")),
            use_container_width=True,
        ):
            guardar_cambios_bd(df_items, cambios)
            st.cache_data.clear()
            st.success("✅ Cambios guardados correctamente.")
            st.rerun()

    with col_btn2:
        st.download_button(
            label="📥 Exportar Búsqueda a Excel",
            data=convertir_df_a_excel(edited_df),
            file_name="banco_items_historico.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )