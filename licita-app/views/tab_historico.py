import datetime
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
                "Con IVA Incluido",
                "Sin IVA (Antes de IVA)",
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
            st.toast("✅ Ítem actualizado y totales recalculados.", icon="🎉")

            # 1. Limpiar la selección asignando un nuevo diccionario al state del widget
            tabla_key = f"tabla_items_{cot_id_sel}"
            st.session_state[tabla_key] = {"selection": {"rows": [], "columns": []}}

            # 2. Rerun para cerrar el modal y refrescar la vista
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

def render_card_html(label, value, badge_text=None, card_type="neutral"):
    """Genera tarjetas compactas con sombreado de color para lectura rápida."""
    styles = {
        "neutral": "background: #1e222d; border: 1px solid #2d3345;",
        "green": "background: rgba(30, 70, 45, 0.45); border: 1px solid #2e7d32;",
        "blue": "background: rgba(25, 55, 85, 0.45); border: 1px solid #1565c0;",
        "red": "background: rgba(90, 25, 25, 0.45); border: 1px solid #d32f2f;",
    }
    val_colors = {
        "neutral": "#ffffff",
        "green": "#66bb6a",
        "blue": "#64b5f6",
        "red": "#ef5350",
    }
    
    bg_style = styles.get(card_type, styles["neutral"])
    val_color = val_colors.get(card_type, "#ffffff")
    
    badge_html = f'<div style="font-size: 0.78rem; font-weight: 600; margin-top: 4px; color: {val_color};">{badge_text}</div>' if badge_text else ""
    
    return f"""
    <div style="{bg_style} border-radius: 8px; padding: 10px 14px; margin-bottom: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.15);">
        <div style="font-size: 0.72rem; font-weight: 700; text-transform: uppercase; color: #a0a6b5; letter-spacing: 0.5px; margin-bottom: 2px;">{label}</div>
        <div style="font-size: 1.2rem; font-weight: 700; color: {val_color}; line-height: 1.2;">{value}</div>
        {badge_html}
    </div>
    """

def render_editor_cotizacion(cot_id_sel, df_cot):
    """Entorno enfocado en la gestión individual con tarjetas de lectura rápida."""
    cot_id_sel = int(cot_id_sel)
    cot_match = df_cot[df_cot["id"] == cot_id_sel]

    if cot_match.empty:
        st.error("No se encontró la cotización seleccionada.")
        if st.button("⬅️ Volver al Registro"):
            st.session_state.pop("cot_id_activa", None)
            st.rerun()
        return

    cot_info = cot_match.iloc[0]

    # --- OBTENER DATOS DEL PROCESO SECOP (PRESUPUESTO Y FECHA LÍMITE) ---
    presupuesto_oficial = 0.0
    fecha_limite_proc = None
    n_proc = (
        cot_info["numero_proceso"]
        if pd.notna(cot_info["numero_proceso"]) and cot_info["numero_proceso"]
        else "GENERAL"
    )

    if n_proc != "GENERAL":
        df_lics = cargar_licitaciones()
        lic_match = df_lics[df_lics["numero_proceso"] == n_proc]
        if not lic_match.empty:
            row_lic = lic_match.iloc[0]
            if pd.notna(row_lic.get("presupuesto")):
                presupuesto_oficial = float(row_lic["presupuesto"])

            # Extraer cualquier campo de fecha disponible en SECOP
            fecha_limite_proc = (
                row_lic.get("fecha_limite")
                or row_lic.get("fecha_cierre")
                or row_lic.get("fecha_presentacion_ofertas")
                or row_lic.get("plazo_presentacion")
            )

    # --- 1. CABECERA Y NAVEGACIÓN COMPACTA ---
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

    # Título con Badges y Plazo Justo Debajo (Limpio de indentación Markdown)
    badge_plazo_html = obtener_badge_plazo_html(fecha_limite_proc)

    html_header = (
        f'<div style="margin-top: 10px; margin-bottom: 10px;">'
        f'<div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">'
        f'<h2 style="margin: 0; font-size: 1.4rem; font-weight: 700; color: #FFFFFF;">🛠️ Cotización #{cot_info["numero_cotizacion"]}</h2>'
        f'<span style="background: #1b2e1e; color: #66bb6a; border: 1px solid #2e7d32; padding: 2px 10px; border-radius: 12px; font-size: 0.75rem; font-weight: 700;">{cot_info["estado"]}</span>'
        f'<span style="background: #252a37; color: #a0a6b5; border: 1px solid #3d4457; padding: 2px 10px; border-radius: 12px; font-size: 0.75rem; font-weight: 600;">{cot_info.get("tipo_cotizacion", "GENERAL")}</span>'
        f'</div>'
        f'<div style="margin-top: 8px;">{badge_plazo_html}</div>'
        f'</div>'
    )

    st.markdown(html_header, unsafe_allow_html=True)

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

    # --- 3. RESUMEN FINANCIERO CON TARJETAS SOMBREADAS Y SEMAFORIZACIÓN ---
    st.markdown("##### 📈 Resumen Financiero y Comparativa SECOP")
    
    # Evaluación de viabilidad contra el presupuesto oficial
    es_inviable = (total_oferta > presupuesto_oficial) if presupuesto_oficial > 0 else False
    diferencia = presupuesto_oficial - total_oferta
    monto_diferencia = abs(diferencia)
    
    pct_desviacion = (monto_diferencia / presupuesto_oficial * 100.0) if presupuesto_oficial > 0 else 0.0

    if es_inviable:
        badge_po = f"↓ -${monto_diferencia:,.2f} Exceso (+{pct_desviacion:.1f}%)"
        tipo_card_po = "red"
        tipo_card_oferta = "red"
        badge_oferta = "🚨 INVIABLE (Supera Techo)"
    else:
        badge_po = f"↑ +${diferencia:,.2f} Holgura (-{pct_desviacion:.1f}%)" if presupuesto_oficial > 0 else None
        tipo_card_po = "blue"
        tipo_card_oferta = "green"
        badge_oferta = "✅ VIABLE (Dentro de Techo)" if presupuesto_oficial > 0 else None

    # Fila 1: Datos Clave SECOP y Oferta
    r1_col1, r1_col2, r1_col3 = st.columns(3)
    with r1_col1:
        st.markdown(render_card_html("📋 Proceso / Licitación", str(n_proc), card_type="neutral"), unsafe_allow_html=True)
    with r1_col2:
        val_po = f"${presupuesto_oficial:,.2f}" if presupuesto_oficial > 0 else "N/A"
        st.markdown(render_card_html("🏛️ Presupuesto Oficial", val_po, badge_text=badge_po, card_type=tipo_card_po), unsafe_allow_html=True)
    with r1_col3:
        st.markdown(render_card_html("🚀 Total Oferta", f"${total_oferta:,.2f}", badge_text=badge_oferta, card_type=tipo_card_oferta), unsafe_allow_html=True)

    # Banner de advertencia si se excede el techo
    if es_inviable:
        st.error(
            f"🚨 **OFERTA INVIABLE:** El Total de la Oferta (**\\${total_oferta:,.2f}**) "
            f"supera el Presupuesto Oficial (**\\${presupuesto_oficial:,.2f}**) "
            f"por **\\${monto_diferencia:,.2f}** (+{pct_desviacion:.1f}%). "
            f"En SECOP esta propuesta será descalificada automáticamente."
        )

    # Fila 2: Desglose Monetario de Costos y Utilidad
    r2_col1, r2_col2, r2_col3, r2_col4 = st.columns(4)
    with r2_col1:
        st.markdown(render_card_html("📦 Costo Base Neto", f"${costo_total_acum:,.2f}", card_type="neutral"), unsafe_allow_html=True)
    with r2_col2:
        st.markdown(render_card_html("🏷️ Subtotal Venta", f"${subtotal_venta:,.2f}", card_type="neutral"), unsafe_allow_html=True)
    with r2_col3:
        st.markdown(render_card_html("🏛️ IVA Estimado", f"${cot_info['impuesto_iva']:,.2f}", card_type="neutral"), unsafe_allow_html=True)
    with r2_col4:
        badge_ub = f"↑ {margen_global_pct:.2f}% Margen Real"
        st.markdown(render_card_html("💰 Utilidad Bruta", f"${utilidad_bruta:,.2f}", badge_text=badge_ub, card_type="green"), unsafe_allow_html=True)
    st.markdown("---")

    # --- 4. PANEL DE ACCIONES ---
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

    # --- 5. TABLA DE ÍTEMS ---
    st.markdown(f"#### 📦 Ítems Incluidos ({len(df_items)} ítems)")
    st.caption("💡 **Tip:** Haz clic sobre cualquier fila para abrir la Calculadora y Editar el Ítem.")

    if not df_items.empty:
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
    # Inicializar la versión de las claves del formulario si no existe
    if f"form_ver_{cot_id_sel}" not in st.session_state:
        st.session_state[f"form_ver_{cot_id_sel}"] = 0

    form_ver = st.session_state[f"form_ver_{cot_id_sel}"]

    with st.expander("➕ Añadir nuevo ítem a esta cotización", expanded=False):
        col_i1, col_i2, col_i3 = st.columns([3, 1, 1])
        with col_i1:
            desc_item = st.text_input("Descripción *", key=f"add_desc_{cot_id_sel}_{form_ver}")
        with col_i2:
            cant_item = st.number_input("Cantidad", min_value=1.0, value=1.0, key=f"add_cant_{cot_id_sel}_{form_ver}")
        with col_i3:
            unid_item = st.text_input("Unidad", value="UNIDAD", key=f"add_unid_{cot_id_sel}_{form_ver}")

        col_c1, col_c2 = st.columns(2)
        with col_c1:
            costo_ingresado = st.number_input("Costo Unitario Ingresado (COP)", min_value=0.0, step=1000.0, key=f"add_costo_{cot_id_sel}_{form_ver}")
            modo_iva = st.selectbox(
                "Tratamiento de IVA del Costo",
                options=["Con IVA Incluido", "Sin IVA (Antes de IVA)", "Exento / Excluido (0%)"],
                index=0,
                key=f"add_modo_iva_{cot_id_sel}_{form_ver}",
            )
        with col_c2:
            iva_disabled = modo_iva == "Exento / Excluido (0%)"
            tarifa_iva = st.number_input(
                "% IVA",
                min_value=0.0,
                max_value=100.0,
                value=0.0 if iva_disabled else 19.0,
                disabled=iva_disabled,
                key=f"add_tarifa_iva_{cot_id_sel}_{form_ver}",
            )
            margen_add_label = st.selectbox(
                "Margen Aplicado",
                options=list(OPCIONES_MARGEN.keys()),
                index=4,
                key=f"add_margen_sel_{cot_id_sel}_{form_ver}",
            )

        enlace_item = st.text_input("Enlace / Proveedor (Opcional)", key=f"add_link_{cot_id_sel}_{form_ver}")

        # Cálculos del ítem en tiempo real
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

        if st.button("➕ Insertar Ítem en Cotización", use_container_width=True, type="primary", key=f"btn_add_item_{cot_id_sel}_{form_ver}"):
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
                    # 1. Notificación flotante que se desaparece sola en 4 segundos
                    st.toast("✅ Ítem agregado y totales recalculados.", icon="🎉")
                    
                    # 2. Incrementar la versión para forzar el reinicio limpio del formulario
                    st.session_state[f"form_ver_{cot_id_sel}"] += 1
                    
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

def render_resumen_financiero_secop(
    cotizacion_data, presupuesto_oficial, fecha_limite_dt=None
):
    """Renderiza el resumen financiero comparando la oferta contra el Presupuesto Oficial SECOP

    con semaforización de colores correcta.
    """
    total_oferta = cotizacion_data.get("total_oferta", 0.0)
    costo_base = cotizacion_data.get("costo_base_neto", 0.0)
    subtotal_venta = cotizacion_data.get("subtotal_venta", 0.0)
    iva_estimado = cotizacion_data.get("iva_estimado", 0.0)
    utilidad_bruta = cotizacion_data.get("utilidad_bruta", 0.0)
    margen_real = cotizacion_data.get("margen_real_pct", 0.0)
    codigo_proceso = cotizacion_data.get("codigo_proceso", "SMC-041-2026")

    # --- CÁLCULOS DE VIABILIDAD DE PRESUPUESTO ---
    diferencia = presupuesto_oficial - total_oferta
    es_inviable = total_oferta > presupuesto_oficial

    if presupuesto_oficial > 0:
        pct_desviacion = (
            abs(diferencia) / presupuesto_oficial
        ) * 100.0  # Porcentaje absoluto
    else:
        pct_desviacion = 0.0

    # Determinar etiquetas y estilos según viabilidad
    if es_inviable:
        # EXCEDE EL PRESUPUESTO (ROJO)
        monto_exceso = abs(diferencia)
        delta_str = (
            f"↓ -${monto_exceso:,.2f} Exceso (+{pct_desviacion:.1f}% sobre techo)"
        )
        color_oferta_card = "#ff4d4d"  # Rojo
        border_oferta = "1px solid #ff4d4d"
        bg_oferta = "rgba(255, 77, 77, 0.1)"
        icon_oferta = "🚨"
    else:
        # DENTRO DEL PRESUPUESTO (VERDE)
        delta_str = (
            f"↑ +${diferencia:,.2f} Holgura (-{pct_desviacion:.1f}% del techo)"
        )
        color_oferta_card = "#00e676"  # Verde
        border_oferta = "1px solid #00e676"
        bg_oferta = "rgba(0, 230, 118, 0.1)"
        icon_oferta = "🚀"

    st.markdown("### 📈 Resumen Financiero y Comparativa SECOP")

    # --- COMPONENTES VISUALES DE TARJETAS (MÉTRICAS) ---
    c1, c2, c3 = st.columns(3)

    with c1:
        st.markdown(
            f"""
            <div style="border: 1px solid #31333F; background-color: #0E1117; padding: 12px; border-radius: 8px;">
                <span style="font-size: 12px; color: #808495; font-weight: bold;">📋 PROCESO / LICITACIÓN</span>
                <h3 style="margin: 4px 0 0 0; color: #FFFFFF;">{codigo_proceso}</h3>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with c2:
        # Presupuesto Oficial y Estado de Holgura
        color_holgura = "#ff4d4d" if es_inviable else "#00e676"
        st.markdown(
            f"""
            <div style="border: 1px solid #1E88E5; background-color: #0E1117; padding: 12px; border-radius: 8px;">
                <span style="font-size: 12px; color: #90CAF9; font-weight: bold;">🏛️ PRESUPUESTO OFICIAL</span>
                <h3 style="margin: 4px 0 0 0; color: #90CAF9;">${presupuesto_oficial:,.2f}</h3>
                <span style="font-size: 12px; color: {color_holgura}; font-weight: bold;">{delta_str}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with c3:
        # Total Oferta con Semaforización Dinámica
        st.markdown(
            f"""
            <div style="border: {border_oferta}; background-color: {bg_oferta}; padding: 12px; border-radius: 8px;">
                <span style="font-size: 12px; color: {color_oferta_card}; font-weight: bold;">{icon_oferta} TOTAL OFERTA</span>
                <h3 style="margin: 4px 0 0 0; color: {color_oferta_card};">${total_oferta:,.2f}</h3>
                <span style="font-size: 12px; color: {color_oferta_card};">{'⚠️ INVIABLE (Supera Techo)' if es_inviable else '✅ VIABLE (Dentro de Techo)'}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.write("")  # Espaciador

    # Segundas Métricas: Costos, IVA y Utilidad
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("📦 COSTO BASE NETO", f"${costo_base:,.2f}")
    with m2:
        st.metric("🏷️ SUBTOTAL VENTA", f"${subtotal_venta:,.2f}")
    with m3:
        st.metric("🏛️ IVA ESTIMADO", f"${iva_estimado:,.2f}")
    with m4:
        st.metric(
            "💰 UTILIDAD BRUTA",
            f"${utilidad_bruta:,.2f}",
            delta=f"{margen_real:.2f}% Margen Real",
        )

    # --- BANNER DE ADVERTENCIA CRÍTICA ---
    if es_inviable:
        st.error(
            f"🚨 **OFERTA INVIABLE PARA PRESENTAR:** El Total de la Oferta (**\\${total_oferta:,.2f}**) "
            f"supera el Presupuesto Oficial (**\\${presupuesto_oficial:,.2f}**) por un monto de "
            f"**\\${abs(diferencia):,.2f}** ({pct_desviacion:.1f}% por encima). "
            f"En SECOP esta propuesta será **descalificada automáticamente**. Ajusta los márgenes o costos de los ítems."
        )
    else:
        st.success(
            f"✅ **OFERTA VIABLE:** El Total de la Oferta (**\\${total_oferta:,.2f}**) está dentro del límite del "
            f"Presupuesto Oficial (**\\${presupuesto_oficial:,.2f}**) con un margen disponible de **\\${diferencia:,.2f}**."
        )

# ==============================================================================
# HELPER PARA FORMATEAR Y EVALUAR EL PLAZO / VENCIMIENTO
# ==============================================================================
def obtener_badge_plazo(fecha_limite_str):
    """Convierte un string de fecha a badge formateado con tiempo restante / vencido."""
    if not fecha_limite_str:
        return "Sin fecha de cierre"

    try:
        # Ajusta el formato de fecha según venga en la DB / API
        dt_limite = datetime.datetime.strptime(
            fecha_limite_str, "%Y-%m-%d %H:%M:%S"
        )
        ahora = datetime.datetime.now()
        diferencia = dt_limite - ahora

        if diferencia.total_seconds() < 0:
            # Vencido
            abs_diff = abs(diferencia)
            dias = abs_diff.days
            horas = abs_diff.seconds // 3600
            return f"❌ **Plazo:** {dt_limite.strftime('%d/%m/%Y %H:%M:%S')} **(Vencido hace {dias} días {horas} h)**"
        else:
            # Vigente
            dias = diferencia.days
            horas = diferencia.seconds // 3600
            return f"⏳ **Plazo:** {dt_limite.strftime('%d/%m/%Y %H:%M:%S')} **(Quedan {dias} días {horas} h)**"
    except Exception:
        return f"📅 **Plazo:** {fecha_limite_str}"

def obtener_badge_plazo_html(fecha_limite_val):
    """Devuelve un badge HTML semaforizado con el estado del plazo (Vencido, Por Vencer o Vigente)."""
    if not fecha_limite_val or pd.isna(fecha_limite_val):
        return '<span style="color: #a0a6b5; font-size: 0.85rem;">📅 <strong>Plazo:</strong> Sin fecha registrada</span>'

    dt_limite = None

    if isinstance(fecha_limite_val, (datetime.datetime, pd.Timestamp)):
        dt_limite = fecha_limite_val
    elif isinstance(fecha_limite_val, str):
        formatos = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%d/%m/%Y %H:%M:%S",
            "%Y-%m-%d",
        ]
        for fmt in formatos:
            try:
                dt_limite = datetime.datetime.strptime(fecha_limite_val.strip(), fmt)
                break
            except ValueError:
                continue

    if not dt_limite:
        return f'<span style="color: #a0a6b5; font-size: 0.85rem;">📅 <strong>Plazo:</strong> {fecha_limite_val}</span>'

    ahora = datetime.datetime.now()
    diferencia = dt_limite - ahora
    str_fecha_fmt = dt_limite.strftime("%d/%m/%Y %H:%M:%S")

    if diferencia.total_seconds() < 0:
        # VENCIDO (ROJO)
        abs_diff = abs(diferencia)
        dias = abs_diff.days
        horas = abs_diff.seconds // 3600
        minutos = (abs_diff.seconds % 3600) // 60
        tiempo_str = f"{dias} días {horas} h" if dias > 0 else f"{horas} h {minutos} min"

        return (
            f'<div style="display: inline-flex; align-items: center; background: rgba(211, 47, 47, 0.2); border: 1px solid #d32f2f; border-radius: 6px; padding: 4px 10px;">'
            f'<span style="color: #ef5350; font-size: 0.85rem; font-weight: 600;">'
            f'❌ <strong>Plazo:</strong> {str_fecha_fmt} '
            f'<span style="margin-left: 6px; background: #d32f2f; color: #ffffff; padding: 1px 6px; border-radius: 4px; font-size: 0.75rem;">Vencido ({tiempo_str})</span>'
            f'</span></div>'
        )
    elif diferencia.total_seconds() <= 86400:
        # POR VENCER EN MENOS DE 24 HORAS (NARANJA)
        horas = diferencia.seconds // 3600
        minutos = (diferencia.seconds % 3600) // 60

        return (
            f'<div style="display: inline-flex; align-items: center; background: rgba(255, 152, 0, 0.2); border: 1px solid #ff9800; border-radius: 6px; padding: 4px 10px;">'
            f'<span style="color: #ffb74d; font-size: 0.85rem; font-weight: 600;">'
            f'⚠️ <strong>Plazo:</strong> {str_fecha_fmt} '
            f'<span style="margin-left: 6px; background: #ff9800; color: #000000; padding: 1px 6px; border-radius: 4px; font-size: 0.75rem;">¡Vence Hoy! (Quedan {horas} h {minutos} min)</span>'
            f'</span></div>'
        )
    else:
        # VIGENTE (VERDE)
        dias = diferencia.days
        horas = diferencia.seconds // 3600

        return (
            f'<div style="display: inline-flex; align-items: center; background: rgba(46, 125, 50, 0.2); border: 1px solid #2e7d32; border-radius: 6px; padding: 4px 10px;">'
            f'<span style="color: #81c784; font-size: 0.85rem; font-weight: 600;">'
            f'⏳ <strong>Plazo:</strong> {str_fecha_fmt} '
            f'<span style="margin-left: 6px; background: #2e7d32; color: #ffffff; padding: 1px 6px; border-radius: 4px; font-size: 0.75rem;">Vigente (Quedan {dias} días {horas} h)</span>'
            f'</span></div>'
        )

def render_form_agregar_item(conn, cotizacion_id_activa: int):
    st.subheader("➕ Añadir Nuevo Ítem a la Cotización")

    # 1. BÚSQUEDA Y AUTOCOMPLETADO DESDE EL BANCO DE ÍTEMS HISTÓRICO
    with st.expander("🔍 Buscar en Banco de Ítem Históricos (Opcional)", expanded=False):
        df_banco = pd.read_sql("SELECT id, descripcion, unidad_medida, costo_unitario, enlace FROM public.banco_items_historico ORDER BY id DESC LIMIT 200;", conn)
        
        item_seleccionado = st.selectbox(
            "Seleccionar ítem base para copiar datos:",
            options=[None] + df_banco['id'].tolist(),
            format_func=lambda x: "--- Seleccionar un ítem ---" if x is None else f"ID {x} | {df_banco.loc[df_banco['id']==x, 'descripcion'].values[0][:60]}... ($ {df_banco.loc[df_banco['id']==x, 'costo_unitario'].values[0]:,.0f})"
        )
        
        # Pre-cargar valores si el usuario selecciona un ítem
        default_desc = ""
        default_unidad = "UND"
        default_costo = 0.0
        default_enlace = ""
        
        if item_seleccionado:
            row = df_banco[df_banco['id'] == item_seleccionado].iloc[0]
            default_desc = str(row['descripcion'])
            default_unidad = str(row['unidad_medida']) if row['unidad_medida'] else "UND"
            default_costo = float(row['costo_unitario']) if row['costo_unitario'] else 0.0
            default_enlace = str(row['enlace']) if row['enlace'] else ""

    # 2. FORMULARIO DE INGRESO Y CÁLCULO
    with st.form(key="form_nuevo_item", clear_on_submit=True):
        col_num, col_desc, col_unid = st.columns([1, 4, 1.5])
        
        with col_num:
            num_item = st.number_input("N° Ítem", min_value=1, value=1, step=1)
        with col_desc:
            descripcion = st.text_area("Descripción del Ítem / Servicio", value=default_desc, height=80)
        with col_unid:
            unidad_medida = st.text_input("Unidad", value=default_unidad)

        col_cant, col_costo, col_margen = st.columns(3)
        
        with col_cant:
            cantidad = st.number_input("Cantidad", min_value=0.01, value=1.0, step=1.0, format="%.2f")
        with col_costo:
            costo_unitario = st.number_input("Costo Unitario ($)", min_value=0.0, value=default_costo, step=1000.0, format="%.2f")
        with col_margen:
            # Factor Divisor en %
            margen_pct = st.number_input("Margen Real (%)", min_value=0.0, max_value=99.0, value=20.0, step=5.0, help="Calcula el precio mediante: Costo / (1 - Margen%)")

        enlace_ref = st.text_input("Enlace / Referencia del Proveedor", value=default_enlace)

        # CÁLCULOS MATEMÁTICOS DIRECTOS
        margen_dec = margen_pct / 100.0
        precio_venta_unitario = costo_unitario / (1.0 - margen_dec) if margen_dec < 1.0 else costo_unitario
        subtotal_item = precio_venta_unitario * cantidad
        utilidad_estimada = (precio_venta_unitario - costo_unitario) * cantidad

        # VISTA PREVIA DE RESULTADOS
        st.info(
            f"**Precio Venta Unitario:** $ {precio_venta_unitario:,.2f}  |  "
            f"**Subtotal Ítem:** $ {subtotal_item:,.2f}  |  "
            f"**Utilidad Bruta:** $ {utilidad_estimada:,.2f}"
        )

        btn_guardar = st.form_submit_button("💾 Guardar Ítem en la Cotización", use_container_width=True)

        if btn_guardar:
            if not descripcion.strip():
                st.error("La descripción del ítem no puede estar vacía.")
            else:
                query_insert = """
                    INSERT INTO public.cotizacion_items (
                        cotizacion_id, numero_item, descripcion, cantidad, 
                        unidad_medida, costo_unitario, margen_porcentaje, 
                        precio_venta_unitario, subtotal_item, enlace_referencia
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                """
                with conn.cursor() as cur:
                    cur.execute(query_insert, (
                        cotizacion_id_activa, num_item, descripcion, cantidad,
                        unidad_medida, costo_unitario, margen_pct,
                        precio_venta_unitario, subtotal_item, enlace_ref
                    ))
                    conn.commit()
                st.success(f"Ítem N° {num_item} añadido correctamente.")
                st.rerun()