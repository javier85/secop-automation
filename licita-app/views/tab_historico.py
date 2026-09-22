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
from database.secop_db import cargar_licitaciones
from services.excel_service import generar_excel_cotizacion

# Mapeo global de Margen Real -> Factor Divisor (de 0% a 90% en pasos de 5%)
OPCIONES_MARGEN = {
    f"{p}% Margen Real (÷ {1 - p/100:.2f})": p / 100.0 for p in range(0, 95, 5)
}


# ==============================================================================
# MODAL NATIVO: CALCULADORA Y EDICIÓN AVANZADA DE ÍTEM
# ==============================================================================
@st.dialog("🛠️ Calculadora y Edición Avanzada de Ítem", width="large")
def modal_editar_item(cot_id_sel, item_row, df_items):
    item_id_edit = item_row["id"]

    edit_desc = st.text_input(
        "Descripción del Insumo / Servicio *",
        value=str(item_row["descripcion"]),
    )

    col_mc1, col_mc2 = st.columns(2)
    with col_mc1:
        edit_cant = st.number_input(
            "Cantidad",
            min_value=0.0,
            value=float(item_row["cantidad"]),
            step=1.0,
        )
    with col_mc2:
        edit_unid = st.text_input(
            "Unidad",
            value=str(item_row.get("unidad_medida", "UNIDAD")),
        )

    col_mc3, col_mc4, col_mc5 = st.columns([2, 2, 2.5])
    with col_mc3:
        edit_costo_ingresado = st.number_input(
            "Costo Unitario (COP) *",
            min_value=0.0,
            value=float(item_row["costo_unitario"]),
            step=1000.0,
        )
    with col_mc4:
        edit_modo_iva = st.selectbox(
            "Origen del Costo",
            options=[
                "Sin IVA (Antes de IVA)",
                "Con IVA Incluido",
                "Exento / Excluido (0%)",
            ],
            index=0,
        )
    with col_mc5:
        iva_dis = edit_modo_iva == "Exento / Excluido (0%)"
        edit_tarifa_iva = st.number_input(
            "% IVA Ítem",
            min_value=0.0,
            max_value=100.0,
            value=0.0 if iva_dis else 19.0,
            disabled=iva_dis,
        )

    margen_actual_pct = float(item_row.get("margen_porcentaje", 20.0))
    closest_margen = min(
        OPCIONES_MARGEN.values(),
        key=lambda x: abs(x - (margen_actual_pct / 100.0)),
    )
    idx_margen_def = list(OPCIONES_MARGEN.values()).index(closest_margen)

    edit_margen_label = st.selectbox(
        "Margen Aplicado",
        options=list(OPCIONES_MARGEN.keys()),
        index=idx_margen_def,
    )

    edit_enlace = st.text_input(
        "Enlace / Proveedor (Opcional)",
        value=str(item_row.get("enlace_referencia", "") or ""),
    )

    if edit_modo_iva == "Con IVA Incluido" and edit_tarifa_iva > 0:
        c_base = edit_costo_ingresado / (1 + (edit_tarifa_iva / 100.0))
    else:
        c_base = edit_costo_ingresado

    m_decimal = OPCIONES_MARGEN[edit_margen_label]
    f_divisor = 1.0 - m_decimal
    p_venta_calc = c_base / f_divisor if f_divisor > 0 else c_base
    subt_calc = p_venta_calc * edit_cant

    st.info(
        f"💡 **Desglose del Ítem Actualizado:**\n"
        f"- Costo Base Neto: **${c_base:,.2f}**\n"
        f"- Factor Divisor: **÷ {f_divisor:.2f}** ({m_decimal*100:.0f}% Margen Real)\n"
        f"- Precio Venta Unitario: **${p_venta_calc:,.2f}**\n"
        f"- Subtotal Ítem: **${subt_calc:,.2f}**"
    )

    if st.button("💾 Guardar Cambios del Ítem", type="primary", use_container_width=True):
        df_items.loc[df_items["id"] == item_id_edit, "descripcion"] = edit_desc.strip()
        df_items.loc[df_items["id"] == item_id_edit, "cantidad"] = edit_cant
        df_items.loc[df_items["id"] == item_id_edit, "unidad_medida"] = edit_unid.strip()
        df_items.loc[df_items["id"] == item_id_edit, "costo_unitario"] = c_base
        df_items.loc[df_items["id"] == item_id_edit, "margen_porcentaje"] = m_decimal * 100.0
        df_items.loc[df_items["id"] == item_id_edit, "precio_venta_unitario"] = p_venta_calc
        df_items.loc[df_items["id"] == item_id_edit, "subtotal_item"] = subt_calc
        df_items.loc[df_items["id"] == item_id_edit, "enlace_referencia"] = edit_enlace.strip()

        exito = actualizar_items_y_cotizacion_db(cot_id_sel, df_items)
        if exito:
            st.success("Ítem recalculado y guardado correctamente.")
            st.rerun()
        else:
            st.error("Error al guardar en la base de datos.")


# ==============================================================================
# VISTA 1: REGISTRO GENERAL MAESTRO
# ==============================================================================
def render_registro_general(df_cot):
    """Muestra el catálogo completo de cotizaciones."""
    st.subheader("📊 Histórico y Control de Cotizaciones")
    st.caption("Consulta el catálogo general o haz clic en cualquier fila para abrir el editor completo.")

    col_b1, col_b2 = st.columns([3, 1])
    with col_b1:
        busqueda = st.text_input("🔍 Buscar por número de cotización o proceso...", "")
    with col_b2:
        filtro_estado = st.selectbox("Estado", ["TODOS", "BORRADOR", "ENVIADA", "APROBADA", "RECHAZADA"])

    df_filtrado = df_cot.copy()

    if busqueda:
        df_filtrado = df_filtrado[
            df_filtrado["numero_cotizacion"].astype(str).str.contains(busqueda, case=False) |
            df_filtrado["numero_proceso"].astype(str).str.contains(busqueda, case=False)
        ]

    if filtro_estado != "TODOS":
        df_filtrado = df_filtrado[df_filtrado["estado"] == filtro_estado]

    config_tabla = {
        "use_container_width": True,
        "hide_index": True,
        "column_config": {
            "id": st.column_config.NumberColumn("ID"),
            "numero_cotizacion": st.column_config.TextColumn("Cotización"),
            "numero_proceso": st.column_config.TextColumn("Proceso"),
            "tipo_cotizacion": st.column_config.TextColumn("Tipo"),
            "estado": st.column_config.TextColumn("Estado"),
            "subtotal": st.column_config.NumberColumn("Subtotal", format="$ %,.2f"),
            "impuesto_iva": st.column_config.NumberColumn("IVA", format="$ %,.2f"),
            "total": st.column_config.NumberColumn("Total", format="$ %,.2f"),
            "fecha_emision": st.column_config.DatetimeColumn("Fecha Emisión", format="DD/MM/YYYY HH:mm"),
        },
    }

    try:
        event = st.dataframe(
            df_filtrado,
            key="tabla_maestra_registro_general",
            on_select="rerun",
            selection_mode="single-row",
            **config_tabla,
        )

        if event and event.get("selection") and event["selection"].get("rows"):
            idx_sel = event["selection"]["rows"][0]
            # Convertir explícitamente a int nativo
            cot_id_clic = int(df_filtrado.iloc[idx_sel]["id"]) 
            st.session_state["cot_id_activa"] = cot_id_clic
            st.rerun()

    except TypeError:
        # Fallback para versiones previas
        opciones = {f"Cotización #{r['numero_cotizacion']} (ID: {r['id']})": r["id"] for _, r in df_filtrado.iterrows()}
        cot_sel = st.selectbox("Selecciona una cotización para abrir:", options=["-- Seleccionar --"] + list(opciones.keys()))
        if cot_sel != "-- Seleccionar --":
            st.session_state["cot_id_activa"] = opciones[cot_sel]
            st.rerun()


# ==============================================================================
# VISTA 2: EDITOR COMPLETO DE COTIZACIÓN (DETALLE)
# ==============================================================================
def render_editor_cotizacion(cot_id_sel, df_cot):
    """Entorno responsivo enfocado en la gestión de cotización individual."""
    cot_id_sel = int(cot_id_sel)
    cot_match = df_cot[df_cot["id"] == cot_id_sel]

    if cot_match.empty:
        st.error("No se encontró la cotización seleccionada.")
        if st.button("⬅️ Volver al Registro"):
            st.session_state.pop("cot_id_activa", None)
            st.rerun()
        return

    cot_info = cot_match.iloc[0]

    # --- 1. CABECERA Y NAVEGACIÓN RESPONSIVA ---
    col_nav1, col_nav2 = st.columns([1, 2])
    with col_nav1:
        if st.button("⬅️ Volver al Registro", use_container_width=True):
            st.session_state.pop("cot_id_activa", None)
            st.rerun()
    with col_nav2:
        opciones_cambio = {
            f"#{r['numero_cotizacion']} ({r['estado']})": int(r["id"]) 
            for _, r in df_cot.iterrows()
        }
        idx_act = list(opciones_cambio.values()).index(cot_id_sel)
        cot_rapida = st.selectbox(
            "Cargar otra:",
            options=list(opciones_cambio.keys()),
            index=idx_act,
            key="selector_rapido_editor",
            label_visibility="collapsed",
        )
        if opciones_cambio[cot_rapida] != cot_id_sel:
            st.session_state["cot_id_activa"] = opciones_cambio[cot_rapida]
            st.rerun()

    st.title(f"🛠️ Cotización #{cot_info['numero_cotizacion']}")
    st.caption(f"**Estado actual:** `{cot_info['estado']}` | **Tipo:** `{cot_info.get('tipo_cotizacion', 'GENERAL')}`")

    st.markdown("---")

    # --- 2. CÁLCULOS DE MÉTRICAS ---
    num_cot_actual = cot_info.get("numero_cotizacion")
    df_items = cargar_detalle_cotizacion(cot_id_sel, numero_cotizacion=num_cot_actual)
    total_oferta = float(cot_info['total'] or 0.0)

    if df_items.empty and total_oferta > 0:
        st.warning(
            f"⚠️ **Atención:** Esta cotización tiene un valor registrado de **${total_oferta:,.2f}**, "
            f"pero no se hallaron renglones en `cotizacion_items` asociados al ID `{cot_id_sel}` o al número `{num_cot_actual}`."
        )

    if not df_items.empty:
        costo_total_acum = (
            pd.to_numeric(df_items["costo_unitario"], errors="coerce").fillna(0.0)
            * pd.to_numeric(df_items["cantidad"], errors="coerce").fillna(0.0)
        ).sum()

        margen_serie = pd.to_numeric(df_items["margen_porcentaje"], errors="coerce").fillna(0.0)
        divisor_serie = (1.0 - (margen_serie / 100.0)).apply(lambda x: x if x > 0 else 1.0)
        p_venta_serie = pd.to_numeric(df_items["costo_unitario"], errors="coerce").fillna(0.0) / divisor_serie
        subtotal_venta = (p_venta_serie * pd.to_numeric(df_items["cantidad"], errors="coerce").fillna(0.0)).sum()
    else:
        costo_total_acum = 0.0
        subtotal_venta = float(cot_info["subtotal"] or 0.0)

    utilidad_bruta = subtotal_venta - costo_total_acum
    margen_global_pct = (utilidad_bruta / subtotal_venta * 100.0) if subtotal_venta > 0 else 0.0

    presupuesto_oficial = 0.0
    n_proc = cot_info["numero_proceso"] if pd.notna(cot_info["numero_proceso"]) and cot_info["numero_proceso"] else "GENERAL"

    if n_proc != "GENERAL":
        df_lics = cargar_licitaciones()
        lic_match = df_lics[df_lics["numero_proceso"] == n_proc]
        if not lic_match.empty and pd.notna(lic_match.iloc[0].get("presupuesto")):
            presupuesto_oficial = float(lic_match.iloc[0]["presupuesto"])

    holgura_cop = presupuesto_oficial - total_oferta
    pct_uso_presupuesto = (total_oferta / presupuesto_oficial * 100.0) if presupuesto_oficial > 0 else 0.0

    # --- 3. RESUMEN FINANCIERO REORGANIZADO EN BLOQUES ---
    with st.container(border=True):
        st.markdown("##### 📈 Resumen Financiero y Comparativa SECOP")
        
        # Fila 1: Presupuesto vs Oferta (2 Columnas amplias)
        m_col1, m_col2 = st.columns(2)
        with m_col1:
            st.metric("📋 Proceso / Licitación", str(n_proc))
            if presupuesto_oficial > 0:
                st.metric(
                    "🏛️ Presupuesto Oficial", 
                    f"${presupuesto_oficial:,.2f}", 
                    delta=f"${holgura_cop:,.2f} Holgura ({100 - pct_uso_presupuesto:.1f}%)"
                )
            else:
                st.metric("🏛️ Presupuesto Oficial", "N/A")
        with m_col2:
            st.metric("🚀 Total Oferta", f"${total_oferta:,.2f}")
            st.metric(
                "💰 Utilidad Bruta",
                f"${utilidad_bruta:,.2f}",
                delta=f"{margen_global_pct:.2f}% Margen Real",
                help="Calculado sobre el valor de venta"
            )

        st.markdown("---")

        # Fila 2: Desglose de Costos (3 Columnas)
        m_col3, m_col4, m_col5 = st.columns(3)
        with m_col3:
            st.metric("📦 Costo Base Neto", f"${costo_total_acum:,.2f}")
        with m_col4:
            st.metric("🏷️ Subtotal Venta", f"${subtotal_venta:,.2f}")
        with m_col5:
            st.metric("🏛️ IVA Estimado", f"${cot_info['impuesto_iva']:,.2f}")

    st.markdown("---")

    # --- 4. PANEL DE ACCIONES EN GRID 2x2 ---
    act_col1, act_col2 = st.columns(2)

    with act_col1:
        estados_disponibles = ["BORRADOR", "ENVIADA", "APROBADA", "RECHAZADA"]
        idx_est = estados_disponibles.index(cot_info["estado"]) if cot_info["estado"] in estados_disponibles else 0
        nuevo_estado = st.selectbox("Estado de Cotización", estados_disponibles, index=idx_est, key=f"est_{cot_id_sel}")
        if nuevo_estado != cot_info["estado"]:
            actualizar_estado_cotizacion(cot_id_sel, nuevo_estado)
            st.success(f"Estado actualizado a {nuevo_estado}")
            st.rerun()

        with st.popover("✏️ Editar Encabezado", use_container_width=True):
            with st.form(f"form_edit_cot_{cot_id_sel}"):
                tipos = ["GENERAL", "LICITACION_SECOP", "VENTA_DIRECTA"]
                tipo_actual = cot_info["tipo_cotizacion"] if pd.notna(cot_info["tipo_cotizacion"]) else "GENERAL"
                idx_tipo = tipos.index(tipo_actual) if tipo_actual in tipos else 0

                nuevo_tipo = st.selectbox("Tipo Cotización", tipos, index=idx_tipo)
                nuevo_proc = st.text_input("Número Proceso", value=(cot_info["numero_proceso"] if pd.notna(cot_info["numero_proceso"]) else ""))
                nuevas_obs = st.text_area("Observaciones", value=(cot_info["observaciones"] if pd.notna(cot_info["observaciones"]) else ""))

                if st.form_submit_button("💾 Guardar Cambios", type="primary", use_container_width=True):
                    actualizar_encabezado_cotizacion(
                        cotizacion_id=cot_id_sel,
                        tipo_cotizacion=nuevo_tipo,
                        numero_proceso=nuevo_proc,
                        observaciones=nuevas_obs,
                    )
                    st.success("Encabezado actualizado correctamente.")
                    st.rerun()

    with act_col2:
        excel_bytes = generar_excel_cotizacion(cot_info.to_dict(), df_items)
        st.download_button(
            label="📥 Descargar Excel",
            data=excel_bytes,
            file_name=f"cotizacion_{cot_info['numero_cotizacion']}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

        with st.popover("🗑️ Eliminar Cotización", use_container_width=True):
            st.warning("⚠️ Acción permanente. Eliminará la cotización e ítems asociados.")
            if st.button("Confirmar Eliminación", type="primary", key=f"btn_del_{cot_id_sel}", use_container_width=True):
                eliminar_cotizacion_completa(cot_id_sel)
                st.session_state.pop("cot_id_activa", None)
                st.rerun()

    st.markdown("---")

    # --- 5. TABLA DE ÍTEMS LIMPIA Y SIN CAMPOS TÉCNICOS ---
    st.markdown(f"#### 📦 Ítems Incluidos ({len(df_items)} ítems)")
    st.caption("💡 **Tip:** Haz clic sobre cualquier fila para abrir la Calculadora y Editar el Ítem.")

    if not df_items.empty:
        # Definir orden explícito para ocultar 'cotizacion_id'
        columnas_visibles = [
            "id", "numero_item", "descripcion", "cantidad", 
            "unidad_medida", "costo_unitario", "margen_porcentaje", 
            "precio_venta_unitario", "subtotal_item", "enlace_referencia"
        ]
        cols_finales = [c for c in columnas_visibles if c in df_items.columns]

        event = st.dataframe(
            df_items,
            column_order=cols_finales,
            key=f"tabla_items_{cot_id_sel}",
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            column_config={
                "id": st.column_config.NumberColumn("ID", width="small"),
                "numero_item": st.column_config.NumberColumn("#", width="small"),
                "descripcion": st.column_config.TextColumn("Descripción", width="large"),
                "cantidad": st.column_config.NumberColumn("Cant.", format="%.2f", width="small"),
                "unidad_medida": st.column_config.TextColumn("Unid.", width="small"),
                "costo_unitario": st.column_config.NumberColumn("Costo Unit.", format="$ %,.2f"),
                "margen_porcentaje": st.column_config.NumberColumn("Margen", format="%.2f %%"),
                "precio_venta_unitario": st.column_config.NumberColumn("P. Venta Unit.", format="$ %,.2f"),
                "subtotal_item": st.column_config.NumberColumn("Subtotal", format="$ %,.2f"),
                "enlace_referencia": st.column_config.LinkColumn("Enlace", width="small"),
            },
        )

        if event and event.get("selection") and event["selection"].get("rows"):
            idx_seleccionado = event["selection"]["rows"][0]
            item_row = df_items.iloc[idx_seleccionado]
            modal_editar_item(cot_id_sel, item_row, df_items)
    else:
        st.info("Esta cotización aún no contiene ítems asociados.")

    st.markdown("---")

    # --- 6. FORMULARIO PARA AÑADIR ÍTEMS ---
    with st.expander("➕ Añadir nuevo ítem a esta cotización", expanded=False):
        col_i1, col_i2, col_i3 = st.columns([3, 1, 1])
        with col_i1:
            desc_item = st.text_input("Descripción *", key=f"add_desc_{cot_id_sel}")
        with col_i2:
            cant_item = st.number_input("Cantidad", min_value=1.0, value=1.0, key=f"add_cant_{cot_id_sel}")
        with col_i3:
            unid_item = st.text_input("Unidad", value="UNIDAD", key=f"add_unid_{cot_id_sel}")

        col_c1, col_c2 = st.columns(2)
        with col_c1:
            costo_ingresado = st.number_input("Costo Unitario Ingresado (COP)", min_value=0.0, step=1000.0, key=f"add_costo_{cot_id_sel}")
            modo_iva = st.selectbox(
                "Tratamiento de IVA del Costo",
                options=["Sin IVA (Antes de IVA)", "Con IVA Incluido", "Exento / Excluido (0%)"],
                index=0,
                key=f"add_modo_iva_{cot_id_sel}",
            )
        with col_c2:
            iva_disabled = modo_iva == "Exento / Excluido (0%)"
            tarifa_iva = st.number_input(
                "% IVA",
                min_value=0.0,
                max_value=100.0,
                value=0.0 if iva_disabled else 19.0,
                disabled=iva_disabled,
                key=f"add_tarifa_iva_{cot_id_sel}",
            )
            margen_add_label = st.selectbox(
                "Margen Aplicado",
                options=list(OPCIONES_MARGEN.keys()),
                index=4,
                key=f"add_margen_sel_{cot_id_sel}",
            )

        enlace_item = st.text_input("Enlace / Proveedor (Opcional)", key=f"add_link_{cot_id_sel}")

        if modo_iva == "Con IVA Incluido" and tarifa_iva > 0:
            costo_base = costo_ingresado / (1 + (tarifa_iva / 100.0))
        else:
            costo_base = costo_ingresado

        margen_add_dec = OPCIONES_MARGEN[margen_add_label]
        factor_item = 1.0 - margen_add_dec
        p_venta = costo_base / factor_item if factor_item > 0 else costo_base
        subt_item = p_venta * cant_item

        if costo_ingresado > 0:
            st.info(
                f"💡 **Desglose del Ítem:** Costo Base: **${costo_base:,.2f}** | "
                f"Divisor: **÷ {factor_item:.2f}** ({margen_add_dec*100:.0f}% Margen) | "
                f"P. Venta: **${p_venta:,.2f}** | Subtotal: **${subt_item:,.2f}**"
            )

        if st.button("➕ Insertar Ítem en Cotización", use_container_width=True, type="primary", key=f"btn_add_item_{cot_id_sel}"):
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
                        "margen_porcentaje": margen_add_dec * 100.0,
                        "precio_venta_unitario": p_venta,
                        "subtotal_item": subt_item,
                        "enlace_referencia": enlace_item.strip(),
                    },
                )
                if exito:
                    st.success("Ítem agregado y totales recalculados.")
                    st.rerun()

# ==============================================================================
# ENTRADA PRINCIPAL DEL MÓDULO (ENRUTADOR DE VISTAS)
# ==============================================================================
def render_tab_historico():
    """Conecta dinámicamente el Registro General con el Editor de Cotización."""
    df_cot = cargar_cotizaciones()

    if df_cot.empty:
        st.subheader("📊 Histórico y Control de Cotizaciones")
        st.info("No hay cotizaciones registradas en la base de datos.")
        return

    # Si hay una cotización activa en session_state, renderizamos la Vista Editor
    if "cot_id_activa" in st.session_state and st.session_state["cot_id_activa"]:
        render_editor_cotizacion(st.session_state["cot_id_activa"], df_cot)
    else:
        # De lo contrario, renderizamos la Vista Registro General
        render_registro_general(df_cot)