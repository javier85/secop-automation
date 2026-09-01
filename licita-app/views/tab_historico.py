# views/tab_historico.py
import pandas as pd
import streamlit as st
from database.cotizaciones_db import (
    actualizar_encabezado_cotizacion,
    actualizar_estado_cotizacion,
    cargar_cotizaciones,
    cargar_detalle_cotizacion,
    eliminar_cotizacion_completa,
)
from services.excel_service import generar_excel_cotizacion


def render_tab_historico():
    st.subheader("📊 Histórico y Control de Cotizaciones")
    st.markdown(
        "Consulta, modifica, actualiza el estado o elimina cotizaciones"
        " registradas en la base de datos."
    )

    df_cot = cargar_cotizaciones()

    if df_cot.empty:
        st.info("No hay cotizaciones registradas en el sistema.")
        return

    # 1. Selector de Cotización activa
    opciones_cot = {
        f"Cotización #{row['numero_cotizacion']} (ID: {row['id']}) -"
        f" {row['estado']}": row["id"]
        for _, row in df_cot.iterrows()
    }

    cot_sel_label = st.selectbox(
        "📌 Selecciona una cotización para gestionar",
        list(opciones_cot.keys()),
    )
    cot_id_sel = opciones_cot[cot_sel_label]

    cot_info = df_cot[df_cot["id"] == cot_id_sel].iloc[0]

    # 2. Métricas Resumen
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric(
            "Número Proceso",
            cot_info["numero_proceso"]
            if pd.notna(cot_info["numero_proceso"])
            else "GENERAL",
        )
    with c2:
        st.metric("Subtotal", f"${cot_info['subtotal']:,.2f}")
    with c3:
        st.metric("IVA", f"${cot_info['impuesto_iva']:,.2f}")
    with c4:
        st.metric("Total", f"${cot_info['total']:,.2f}")

    st.markdown("---")

    # 3. Panel de Acciones CRUD y Estado
    col_estado, col_edit, col_del, col_export = st.columns([2, 2, 2, 2])

    with col_estado:
        estados_disponibles = ["BORRADOR", "ENVIADA", "APROBADA", "RECHAZADA"]
        idx_est = (
            estados_disponibles.index(cot_info["estado"])
            if cot_info["estado"] in estados_disponibles
            else 0
        )
        nuevo_estado = st.selectbox(
            "Cambiar Estado",
            estados_disponibles,
            index=idx_est,
            key=f"est_{cot_id_sel}",
        )
        if nuevo_estado != cot_info["estado"]:
            actualizar_estado_cotizacion(cot_id_sel, nuevo_estado)
            st.success(f"Estado actualizado a {nuevo_estado}")
            st.rerun()

    with col_edit:
        st.markdown(
            "<div style='margin-top: 28px;'></div>", unsafe_allow_html=True
        )
        with st.popover("✏️ Editar Encabezado", use_container_width=True):
            with st.form(f"form_edit_cot_{cot_id_sel}"):
                tipos = ["GENERAL", "LICITACION_SECOP", "VENTA_DIRECTA"]
                tipo_actual = (
                    cot_info["tipo_cotizacion"]
                    if pd.notna(cot_info["tipo_cotizacion"])
                    else "GENERAL"
                )
                idx_tipo = tipos.index(tipo_actual) if tipo_actual in tipos else 0

                nuevo_tipo = st.selectbox(
                    "Tipo Cotización", tipos, index=idx_tipo
                )
                nuevo_proc = st.text_input(
                    "Número Proceso",
                    value=cot_info["numero_proceso"]
                    if pd.notna(cot_info["numero_proceso"])
                    else "",
                )
                nuevas_obs = st.text_area(
                    "Observaciones",
                    value=cot_info["observaciones"]
                    if pd.notna(cot_info["observaciones"])
                    else "",
                )

                if st.form_submit_button(
                    "💾 Guardar Cambios",
                    type="primary",
                    use_container_width=True,
                ):
                    actualizar_encabezado_cotizacion(
                        cot_id_sel, nuevo_tipo, nuevo_proc, nuevas_obs
                    )
                    st.success("Encabezado actualizado correctamente.")
                    st.rerun()

    with col_del:
        st.markdown(
            "<div style='margin-top: 28px;'></div>", unsafe_allow_html=True
        )
        with st.popover("🗑️ Eliminar Cotización", use_container_width=True):
            st.warning(
                "⚠️ Esta acción es permanente y eliminará la cotización junto"
                " con todos sus ítems asociados."
            )
            if st.button(
                "Confirmar Eliminación",
                type="primary",
                key=f"btn_del_{cot_id_sel}",
                use_container_width=True,
            ):
                eliminar_cotizacion_completa(cot_id_sel)
                st.success("Cotización eliminada de la base de datos.")
                st.rerun()

    with col_export:
        st.markdown(
            "<div style='margin-top: 28px;'></div>", unsafe_allow_html=True
        )
        df_items = cargar_detalle_cotizacion(cot_id_sel)
        excel_bytes = generar_excel_cotizacion(cot_info.to_dict(), df_items)
        st.download_button(
            label="📥 Descargar Excel",
            data=excel_bytes,
            file_name=f"cotizacion_{cot_info['numero_cotizacion']}.xlsx",
            mime=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            use_container_width=True,
        )

    st.markdown("---")

    # 4. Detalle de Ítems
    st.markdown("#### 📦 Ítems Incluidos en la Cotización")
    if not df_items.empty:
        st.dataframe(
            df_items,
            use_container_width=True,
            hide_index=True,
            column_config={
                "item_id": None,
                "Costo Unit. (COP)": st.column_config.NumberColumn(
                    format="$ %,.2f"
                ),
                "Precio Venta Unit. (COP)": st.column_config.NumberColumn(
                    format="$ %,.2f"
                ),
                "Subtotal (COP)": st.column_config.NumberColumn(
                    format="$ %,.2f"
                ),
                "Margen (%)": st.column_config.NumberColumn(format="%.2f %%"),
                "enlace_referencia": st.column_config.LinkColumn(
                    "Enlace Referencia"
                ),
            },
        )
    else:
        st.info("Esta cotización no contiene ítems asociados.")

    # 5. Tabla Resumen Global
    with st.expander("📋 Ver Registro General de Cotizaciones"):
        st.dataframe(
            df_cot,
            use_container_width=True,
            hide_index=True,
            column_config={
                "id": None,
                "subtotal": st.column_config.NumberColumn(
                    "Subtotal", format="$ %,.2f"
                ),
                "impuesto_iva": st.column_config.NumberColumn(
                    "IVA", format="$ %,.2f"
                ),
                "total": st.column_config.NumberColumn(
                    "Total", format="$ %,.2f"
                ),
                "fecha_emision": st.column_config.DatetimeColumn(
                    "Fecha Emisión", format="DD/MM/YYYY HH:mm"
                ),
            },
        )