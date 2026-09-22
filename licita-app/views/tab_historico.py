import pandas as pd
import streamlit as st

from database.cotizaciones_db import (
    actualizar_encabezado_cotizacion,
    actualizar_estado_cotizacion,
    actualizar_items_y_cotizacion_db,
    agregar_item_a_cotizacion_existente,
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
    # 1. Cargar detalle de ítems con anticipación para calcular costos y utilidad
    # 2. Métricas Resumen
    df_items = cargar_detalle_cotizacion(cot_id_sel)

    if not df_items.empty:
        # Costo total acum
        costo_total_acum = (
            pd.to_numeric(df_items["costo_unitario"], errors="coerce").fillna(0.0)
            * pd.to_numeric(df_items["cantidad"], errors="coerce").fillna(0.0)
        ).sum()

        # Recalcular Subtotal Venta usando el factor divisor (1 - margen/100)
        margen_serie = pd.to_numeric(df_items["margen_porcentaje"], errors="coerce").fillna(0.0)
        divisor_serie = (1.0 - (margen_serie / 100.0)).apply(lambda x: x if x > 0 else 1.0)
        p_venta_serie = pd.to_numeric(df_items["costo_unitario"], errors="coerce").fillna(0.0) / divisor_serie
        
        subtotal_venta = (p_venta_serie * pd.to_numeric(df_items["cantidad"], errors="coerce").fillna(0.0)).sum()
    else:
        costo_total_acum = 0.0
        subtotal_venta = float(cot_info["subtotal"] or 0.0)

    utilidad_bruta = subtotal_venta - costo_total_acum
    margen_global_pct = (utilidad_bruta / subtotal_venta * 100.0) if subtotal_venta > 0 else 0.0
    
    # 2. Métricas Resumen Expandidas
    col_m1, col_m2, col_m3, col_m4, col_m5, col_m6 = st.columns(6)

    with col_m1:
        st.metric(
            label="Proceso",
            value=(
                cot_info["numero_proceso"]
                if pd.notna(cot_info["numero_proceso"]) and cot_info["numero_proceso"]
                else "GENERAL"
            ),
        )
    with col_m2:
        st.metric(
            label="Saldo Sin Margen",
            value=f"${costo_total_acum:,.2f}",
            help="Suma de los costos base de todos los ítems",
        )
    with col_m3:
        st.metric(
            label="Saldo Con Margen",
            value=f"${subtotal_venta:,.2f}",
            help="Subtotal de venta sin impuestos",
        )
    with col_m4:
        st.metric(
            label="Utilidad Bruta",
            value=f"${utilidad_bruta:,.2f}",
            delta=f"{margen_global_pct:.2f}% Margen",
            help="Ganancia neta esperada en la cotización",
        )
    with col_m5:
        st.metric(
            label="IVA",
            value=f"${cot_info['impuesto_iva']:,.2f}",
        )
    with col_m6:
        st.metric(
            label="Total Oferta",
            value=f"${cot_info['total']:,.2f}",
        )

    # -------------------------------------------------------------
    # AGREGAR AQUÍ (Línea 97 aprox.)
    # -------------------------------------------------------------
    if subtotal_venta > 0:
        st.info(
            f"💡 **Cálculo de Margen Aplicado:** Esta cotización tiene un costo base de **${costo_total_acum:,.2f}**"
            f"Un precio de venta de **${subtotal_venta:,.2f}**"
            f"Generando una utilidad neta de **${utilidad_bruta:,.2f}** ({margen_global_pct:.2f}% sobre venta)."
        )

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
                idx_tipo = (
                    tipos.index(tipo_actual) if tipo_actual in tipos else 0
                )

                nuevo_tipo = st.selectbox(
                    "Tipo Cotización", tipos, index=idx_tipo
                )
                nuevo_proc = st.text_input(
                    "Número Proceso",
                    value=(
                        cot_info["numero_proceso"]
                        if pd.notna(cot_info["numero_proceso"])
                        else ""
                    ),
                )
                nuevas_obs = st.text_area(
                    "Observaciones",
                    value=(
                        cot_info["observaciones"]
                        if pd.notna(cot_info["observaciones"])
                        else ""
                    ),
                )

                if st.form_submit_button(
                    "💾 Guardar Cambios",
                    type="primary",
                    use_container_width=True,
                ):
                    actualizar_encabezado_cotizacion(
                        cotizacion_id=cot_id_sel,
                        tipo_cotizacion=nuevo_tipo,
                        numero_proceso=nuevo_proc,
                        observaciones=nuevas_obs,
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

    # 4. Detalle de Ítems Editable (st.data_editor)
    st.markdown("#### 📦 Ítems Incluidos en la Cotización")
    if not df_items.empty:
        edited_df = st.data_editor(
            df_items,
            key=f"editor_items_{cot_id_sel}",
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            column_config={
                "id": st.column_config.NumberColumn("ID", disabled=True),
                "numero_item": st.column_config.NumberColumn(
                    "# Ítem", disabled=True
                ),
                "descripcion": st.column_config.TextColumn(
                    "Descripción", required=True
                ),
                "cantidad": st.column_config.NumberColumn(
                    "Cantidad", min_value=0.0, step=1.0, required=True
                ),
                "unidad_medida": st.column_config.TextColumn("Unidad"),
                "costo_unitario": st.column_config.NumberColumn(
                    "Costo Unit. (COP)",
                    format="$ %,.2f",
                    min_value=0.0,
                    required=True,
                ),
                "margen_porcentaje": st.column_config.NumberColumn(
                    "Margen (%)", format="%.2f %%", min_value=0.0
                ),
                "precio_venta_unitario": st.column_config.NumberColumn(
                    "Precio Venta Unit. (COP)",
                    format="$ %,.2f",
                    disabled=True,
                ),
                "subtotal_item": st.column_config.NumberColumn(
                    "Subtotal (COP)", format="$ %,.2f", disabled=True
                ),
                "enlace_referencia": st.column_config.LinkColumn(
                    "Enlace Referencia"
                ),
            },
        )

        # Recalcular valores derivados
        if not edited_df.empty:
            df_procesado = edited_df.copy()

            df_procesado["costo_unitario"] = (
                pd.to_numeric(df_procesado["costo_unitario"], errors="coerce")
                .fillna(0.0)
                .astype(float)
            )
            df_procesado["cantidad"] = (
                pd.to_numeric(df_procesado["cantidad"], errors="coerce")
                .fillna(0.0)
                .astype(float)
            )
            df_procesado["margen_porcentaje"] = (
                pd.to_numeric(
                    df_procesado["margen_porcentaje"], errors="coerce"
                )
                .fillna(0.0)
                .astype(float)
            )

            # CÓDIGO CORREGIDO (tab_historico_5.py)
            factor_divisor = 1.0 - (df_procesado["margen_porcentaje"] / 100.0)
            # Evitar división por cero si el margen fuera 100%
            factor_divisor = factor_divisor.apply(lambda x: x if x > 0 else 1.0)

            df_procesado["precio_venta_unitario"] = df_procesado["costo_unitario"] / factor_divisor
            df_procesado["subtotal_item"] = df_procesado["cantidad"] * df_procesado["precio_venta_unitario"]

            col_save, _ = st.columns([2, 6])
            with col_save:
                if st.button(
                    "💾 Guardar Cambios en Ítems",
                    type="primary",
                    key=f"btn_save_items_{cot_id_sel}",
                    use_container_width=True,
                ):
                    exito = actualizar_items_y_cotizacion_db(
                        cot_id_sel, df_procesado
                    )
                    if exito:
                        st.success(
                            "Ítems y totales de la cotización actualizados en"
                            " PostgreSQL."
                        )
                        st.rerun()
                    else:
                        st.error(
                            "Ocurrió un error al guardar las modificaciones."
                        )
    else:
        st.info("Esta cotización no contiene ítems asociados.")

    st.markdown("---")

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

    # 6. Bloque para agregar nuevos ítems
    with st.expander("➕ Añadir nuevo ítem a esta cotización", expanded=False):
        col_i1, col_i2, col_i3 = st.columns([4, 1, 1])
        with col_i1:
            desc_item = st.text_input(
                "Descripción *", key=f"add_desc_{cot_id_sel}"
            )
        with col_i2:
            cant_item = st.number_input(
                "Cantidad",
                min_value=1.0,
                value=1.0,
                key=f"add_cant_{cot_id_sel}",
            )
        with col_i3:
            unid_item = st.text_input(
                "Unidad", value="UNIDAD", key=f"add_unid_{cot_id_sel}"
            )

        col_c1, col_c2, col_c3, col_c4 = st.columns([2, 2, 1.5, 1.5])
        with col_c1:
            costo_ingresado = st.number_input(
                "Costo Unitario Ingresado (COP)",
                min_value=0.0,
                step=1000.0,
                key=f"add_costo_{cot_id_sel}",
            )
        with col_c2:
            modo_iva = st.selectbox(
                "Tratamiento de IVA del Costo",
                options=[
                    "Sin IVA (Antes de IVA)",
                    "Con IVA Incluido",
                    "Exento / Excluido (0%)",
                ],
                index=0,
                key=f"add_modo_iva_{cot_id_sel}",
            )
        with col_c3:
            iva_disabled = modo_iva == "Exento / Excluido (0%)"
            tarifa_iva = st.number_input(
                "% IVA",
                min_value=0.0,
                max_value=100.0,
                value=0.0 if iva_disabled else 19.0,
                disabled=iva_disabled,
                key=f"add_tarifa_iva_{cot_id_sel}",
            )
        with col_c4:
            margen_item = st.number_input(
                "Margen (%)",
                min_value=0.0,
                value=20.0,
                key=f"add_margen_{cot_id_sel}",
            )

        enlace_item = st.text_input(
            "Enlace / Proveedor (Opcional)", key=f"add_link_{cot_id_sel}"
        )

        if modo_iva == "Con IVA Incluido" and tarifa_iva > 0:
            costo_base = costo_ingresado / (1 + (tarifa_iva / 100.0))
        else:
            costo_base = costo_ingresado

        # CÓDIGO CORREGIDO (tab_historico_5.py)
        factor_item = 1.0 - (margen_item / 100.0)
        p_venta = costo_base / factor_item if factor_item > 0 else costo_base
        subt_item = p_venta * cant_item

        if costo_ingresado > 0:
            factor_display = f"{factor_item:.2f}" if factor_item > 0 else "1.00"
            st.info(
                f"💡 **Desglose del Ítem:** Costo Base (Sin IVA): **${costo_base:,.2f}** | "
                f"Factor Divisor: **÷ {factor_display}** (Margen {margen_item:.1f}%) | "
                f"Precio Venta Unitario: **${p_venta:,.2f}** | Subtotal: **${subt_item:,.2f}**"
            )

        if st.button(
            "➕ Insertar Ítem en Cotización",
            use_container_width=True,
            type="primary",
            key=f"btn_add_item_{cot_id_sel}",
        ):
            if not desc_item.strip():
                st.error("La descripción del ítem no puede estar vacía.")
            else:
                exito = agregar_item_a_cotizacion_existente(
                    cot_id_sel,
                    {
                        "descripcion": desc_item.strip(),
                        "cantidad": cant_item,
                        "unidad_medida": unid_item.strip(),
                        "costo_unitario": costo_base,
                        "margen_porcentaje": margen_item,
                        "precio_venta_unitario": p_venta,
                        "subtotal_item": subt_item,
                        "enlace_referencia": enlace_item.strip(),
                    },
                )
                if exito:
                    st.success(
                        "Ítem agregado y totales de la cotización recalculados."
                    )
                    st.rerun()