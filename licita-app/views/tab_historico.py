import datetime
import pandas as pd
import streamlit as st

from database.cotizaciones_db import (
    actualizar_encabezado_cotizacion,
    actualizar_estado_cotizacion,
    actualizar_items_y_cotizacion_db,
    cargar_cotizaciones,
    cargar_detalle_cotizacion,
    eliminar_cotizacion_completa,
    insertar_item_cotizacion,
)
from database.secop_db import (
    cargar_licitaciones,
)
from services.excel_service import generar_excel_cotizacion

# Mapeo global de Margen Real -> Factor Divisor (de 0% a 90% en pasos de 5%)
OPCIONES_MARGEN = {
    f"{p}% Margen Real (÷ {1 - p/100:.2f})": p / 100.0 for p in range(0, 95, 5)
}

# ==============================================================================
# MODAL NATIVO: CALCULADORA Y EDICIÓN AVANZADA DE ÍTEM (ANCHO ESTÁNDAR)
# ==============================================================================
@st.dialog("🛠️ Calculadora y Edición de Ítem")
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

    # --- LECTURA DINÁMICA DEL MODO DE IVA PREVIO ---
    opciones_modo_iva = [
        "Con IVA Incluido",
        "Sin IVA (Antes de IVA)",
        "Exento / Excluido (0%)",
    ]
    modo_actual = str(item_row.get("tratamiento_iva", "Con IVA Incluido"))
    idx_modo = opciones_modo_iva.index(modo_actual) if modo_actual in opciones_modo_iva else 0

    col_mc3, col_mc4 = st.columns(2)
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
            options=opciones_modo_iva,
            index=idx_modo,
        )

    iva_dis = edit_modo_iva == "Exento / Excluido (0%)"
    iva_previo = float(item_row.get("porcentaje_iva", 19.0))
    
    edit_tarifa_iva = st.number_input(
        "% IVA Ítem",
        min_value=0.0,
        max_value=100.0,
        value=0.0 if iva_dis else (iva_previo if iva_previo > 0 else 19.0),
        disabled=iva_dis,
    )

    # Determinación estricta de la tarifa de IVA según exención
    edit_tarifa_iva_final = 0.0 if iva_dis else edit_tarifa_iva

    # Cálculo del Costo Base Neto según origen
    if edit_modo_iva == "Con IVA Incluido" and edit_tarifa_iva_final > 0:
        c_base = edit_costo_ingresado / (1 + (edit_tarifa_iva_final / 100.0))
    else:
        c_base = edit_costo_ingresado

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

    m_decimal = OPCIONES_MARGEN[edit_margen_label]
    f_divisor = 1.0 - m_decimal
    p_venta_calc = c_base / f_divisor if f_divisor > 0 else c_base
    subt_calc = p_venta_calc * edit_cant
    iva_item_monto = subt_calc * (edit_tarifa_iva_final / 100.0)

    st.info(
        f"💡 **Desglose del Ítem Actualizado:**\n"
        f"- Costo Base Neto: **${c_base:,.2f}**\n"
        f"- Tratamiento IVA: **{edit_modo_iva}** ({edit_tarifa_iva_final:.1f}% -> ${iva_item_monto:,.2f})\n"
        f"- Factor Divisor: **÷ {f_divisor:.2f}** ({m_decimal*100:.0f}% Margen Real)\n"
        f"- Precio Venta Unitario: **${p_venta_calc:,.2f}**\n"
        f"- Subtotal Ítem (sin IVA): **${subt_calc:,.2f}**"
    )

    if st.button("💾 Guardar Cambios del Ítem", type="primary", use_container_width=True):
        df_items.loc[df_items["id"] == item_id_edit, "descripcion"] = edit_desc.strip()
        df_items.loc[df_items["id"] == item_id_edit, "cantidad"] = edit_cant
        df_items.loc[df_items["id"] == item_id_edit, "unidad_medida"] = edit_unid.strip()
        df_items.loc[df_items["id"] == item_id_edit, "costo_unitario"] = c_base
        df_items.loc[df_items["id"] == item_id_edit, "porcentaje_iva"] = edit_tarifa_iva_final
        df_items.loc[df_items["id"] == item_id_edit, "tratamiento_iva"] = edit_modo_iva
        df_items.loc[df_items["id"] == item_id_edit, "margen_porcentaje"] = m_decimal * 100.0
        df_items.loc[df_items["id"] == item_id_edit, "precio_venta_unitario"] = p_venta_calc
        df_items.loc[df_items["id"] == item_id_edit, "subtotal_item"] = subt_calc
        df_items.loc[df_items["id"] == item_id_edit, "enlace_referencia"] = edit_enlace.strip()

        exito = actualizar_items_y_cotizacion_db(cot_id_sel, df_items)
        if exito:
            st.toast("✅ Ítem actualizado y totales recalculados.", icon="🎉")
            tabla_key = f"tabla_items_{cot_id_sel}"
            st.session_state[tabla_key] = {"selection": {"rows": [], "columns": []}}
            st.rerun()
        else:
            st.error("Error al guardar en la base de datos.")

# ==============================================================================
# MODAL NATIVO: EDICIÓN DE ENCABEZADO Y PARÁMETROS GLOBALES (ANCHO ESTÁNDAR)
# ==============================================================================
@st.dialog("📄 Modificar Parámetros Globales")
def modal_editar_encabezado(cot_info, cot_id_sel):
    df_lics = cargar_licitaciones()
    opciones_lic = {"-- Sin Asociación (General) --": ""}
    if not df_lics.empty:
        for _, r_lic in df_lics.iterrows():
            opciones_lic[f"{r_lic['numero_proceso']} - {r_lic['entidad']}"] = r_lic["numero_proceso"]

    proc_actual = cot_info["numero_proceso"] if pd.notna(cot_info["numero_proceso"]) else ""
    keys_lic = list(opciones_lic.keys())
    vals_lic = list(opciones_lic.values())
    idx_proc = vals_lic.index(proc_actual) if proc_actual in vals_lic else 0

    proceso_sel = st.selectbox("Asociar a Licitación SECOP", keys_lic, index=idx_proc)
    nuevo_proc = opciones_lic[proceso_sel]

    col_e1, col_e2, col_e3 = st.columns(3)
    
    with col_e1:
        tipos_estandar = ["GENERAL", "EPP", "SOFTWARE", "INFRAESTRUCTURA", "SERVICIOS"]
        tipo_actual = cot_info["tipo_cotizacion"] if pd.notna(cot_info["tipo_cotizacion"]) else "GENERAL"
        idx_tipo = tipos_estandar.index(tipo_actual) if tipo_actual in tipos_estandar else 0
        nuevo_tipo = st.selectbox("Tipo Cotización", tipos_estandar, index=idx_tipo)

    with col_e2:
        margen_actual = float(cot_info.get("margen_global", 20.0)) if pd.notna(cot_info.get("margen_global")) else 20.0
        nuevo_margen = st.number_input(
            "Margen Base (%)", 
            min_value=0.0, 
            max_value=500.0, 
            value=margen_actual, 
            step=0.5,
            help="Margen base predeterminado aplicable a los ítems de esta cotización"
        )

    with col_e3:
        iva_actual = float(cot_info.get("porcentaje_iva", 19.0)) if pd.notna(cot_info.get("porcentaje_iva")) else 19.0
        nuevo_iva = st.number_input("IVA Global (%)", min_value=0.0, max_value=100.0, value=iva_actual, step=1.0)

    nuevas_obs = st.text_area(
        "Observaciones / Términos", 
        value=(cot_info["observaciones"] if pd.notna(cot_info["observaciones"]) else "")
    )

    if st.button("💾 Guardar Cambios de Encabezado", type="primary", use_container_width=True):
        exito = actualizar_encabezado_cotizacion(
            cotizacion_id=cot_id_sel,
            tipo_cotizacion=nuevo_tipo,
            numero_proceso=nuevo_proc,
            margen_global=nuevo_margen,
            porcentaje_iva=nuevo_iva,
            observaciones=nuevas_obs.strip(),
        )
        if exito:
            df_items = cargar_detalle_cotizacion(cot_id_sel)
            if not df_items.empty and "tratamiento_iva" in df_items.columns:
                mask_no_exento = df_items["tratamiento_iva"] != "Exento / Excluido (0%)"
                if mask_no_exento.any():
                    df_items.loc[mask_no_exento, "porcentaje_iva"] = nuevo_iva
                    actualizar_items_y_cotizacion_db(cot_id_sel, df_items)

            st.toast("✅ Encabezado e IVA global actualizados.", icon="🎉")
            st.rerun()
        else:
            st.error("Error actualizando el encabezado en la base de datos.")

# ==============================================================================
# MODAL NATIVO: AGREGAR NUEVO ÍTEM (ANCHO ESTÁNDAR)
# ==============================================================================
@st.dialog("➕ Añadir Nuevo Ítem a la Cotización")
def modal_agregar_item(cot_id_sel, cot_info):
    desc_item = st.text_input("Descripción *")
    
    c1, c2 = st.columns(2)
    with c1:
        cant_item = st.number_input("Cantidad", min_value=0.01, value=1.00, step=1.00)
    with c2:
        unidad_item = st.text_input("Unidad", value="UNIDAD")

    c3, c4 = st.columns(2)
    with c3:
        costo_item = st.number_input("Costo Unitario Ingresado (COP)", min_value=0.0, value=0.0, step=1000.0)
    with c4:
        enlace_item = st.text_input("Enlace / Proveedor (Opcional)")

    if st.button("➕ Insertar Ítem en Cotización", type="primary", use_container_width=True):
        if not desc_item.strip():
            st.error("La descripción del ítem es obligatoria.")
        else:
            margen_predeterminado = float(cot_info.get("margen_global", 20.0)) if pd.notna(cot_info.get("margen_global")) else 20.0
            iva_predeterminado = float(cot_info.get("porcentaje_iva", 19.0)) if pd.notna(cot_info.get("porcentaje_iva")) else 19.0
            
            exito = insertar_item_cotizacion(
                cotizacion_id=cot_id_sel,
                descripcion=desc_item.strip(),
                cantidad=cant_item,
                unidad=unidad_item.strip(),
                costo_unitario=costo_item,
                margen_aplicado=margen_predeterminado,
                porcentaje_iva=iva_predeterminado,
                tratamiento_iva="Con IVA Incluido",
                enlace_proveedor=enlace_item.strip()
            )
            if exito:
                st.toast("✅ Ítem agregado exitosamente.", icon="🎉")
                st.rerun()

# ==============================================================================
# VISTA 1: REGISTRO GENERAL MAESTRO
# ==============================================================================
def render_registro_general(df_cot):
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
            cot_id_clic = int(df_filtrado.iloc[idx_sel]["id"]) 
            st.session_state["cot_id_activa"] = cot_id_clic
            st.rerun()

    except TypeError:
        opciones = {f"Cotización #{r['numero_cotizacion']} (ID: {r['id']})": r["id"] for _, r in df_filtrado.iterrows()}
        cot_sel = st.selectbox("Selecciona una cotización para abrir:", options=["-- Seleccionar --"] + list(opciones.keys()))
        if cot_sel != "-- Seleccionar --":
            st.session_state["cot_id_activa"] = opciones[cot_sel]
            st.rerun()

# ==============================================================================
# VISTA 2: EDITOR COMPLETO DE COTIZACIÓN (REORGANIZADO)
# ==============================================================================
def render_card_html(label, value, badge_text=None, card_type="neutral"):
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
    cot_id_sel = int(cot_id_sel)
    cot_match = df_cot[df_cot["id"] == cot_id_sel]

    if cot_match.empty:
        st.error("No se encontró la cotización seleccionada.")
        if st.button("⬅️ Volver al Registro"):
            st.session_state.pop("cot_id_activa", None)
            st.rerun()
        return

    cot_info = cot_match.iloc[0]

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

            fecha_limite_proc = (
                row_lic.get("fecha_limite")
                or row_lic.get("fecha_cierre")
                or row_lic.get("fecha_presentacion_ofertas")
                or row_lic.get("plazo_presentacion")
            )

    # ==========================================
    # 1. BARRA DE NAVEGACIÓN SUPERIOR Y ENCABEZADO
    # ==========================================
    col_nav1, col_nav2 = st.columns([1, 1])

    with col_nav1:
        if st.button("⬅️ Volver al Registro", use_container_width=True, key=f"btn_back_{cot_id_sel}"):
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

    # Encabezado HTML con estado y plazo
    badge_plazo_html = obtener_badge_plazo_html(fecha_limite_proc)

    html_header = (
        f'<div style="margin-top: 10px; margin-bottom: 15px;">'
        f'<div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">'
        f'<h2 style="margin: 0; font-size: 1.4rem; font-weight: 700; color: #FFFFFF;">🛠️ Cotización #{cot_info["numero_cotizacion"]}</h2>'
        f'<span style="background: #1b2e1e; color: #66bb6a; border: 1px solid #2e7d32; padding: 2px 10px; border-radius: 12px; font-size: 0.75rem; font-weight: 700;">{cot_info["estado"]}</span>'
        f'<span style="background: #252a37; color: #a0a6b5; border: 1px solid #3d4457; padding: 2px 10px; border-radius: 12px; font-size: 0.75rem; font-weight: 600;">{cot_info.get("tipo_cotizacion", "GENERAL")}</span>'
        f'</div>'
        f'<div style="margin-top: 8px;">{badge_plazo_html}</div>'
        f'</div>'
    )
    st.markdown(html_header, unsafe_allow_html=True)

    # 2. CÁLCULO DINÁMICO DE TOTALES
    num_cot_actual = cot_info.get("numero_cotizacion")
    df_items = cargar_detalle_cotizacion(cot_id_sel, numero_cotizacion=num_cot_actual)

    if not df_items.empty:
        df_items["cantidad"] = pd.to_numeric(df_items["cantidad"], errors="coerce").fillna(0.0)
        df_items["costo_unitario"] = pd.to_numeric(df_items["costo_unitario"], errors="coerce").fillna(0.0)
        df_items["margen_porcentaje"] = pd.to_numeric(df_items["margen_porcentaje"], errors="coerce").fillna(0.0)
        
        iva_hdr_def = float(cot_info.get("porcentaje_iva", 19.0)) if pd.notna(cot_info.get("porcentaje_iva")) else 19.0

        if "porcentaje_iva" not in df_items.columns:
            df_items["porcentaje_iva"] = iva_hdr_def
        else:
            df_items["porcentaje_iva"] = pd.to_numeric(df_items["porcentaje_iva"], errors="coerce").fillna(iva_hdr_def)

        if "tratamiento_iva" not in df_items.columns:
            df_items["tratamiento_iva"] = "Con IVA Incluido"

        costo_total_acum = (df_items["costo_unitario"] * df_items["cantidad"]).sum()

        divisor_serie = (1.0 - (df_items["margen_porcentaje"] / 100.0)).apply(lambda x: x if x > 0 else 1.0)
        p_venta_serie = df_items["costo_unitario"] / divisor_serie
        subtotal_item_serie = p_venta_serie * df_items["cantidad"]
        subtotal_venta = subtotal_item_serie.sum()

        df_items["iva_pct_real"] = df_items.apply(
            lambda r: 0.0 if str(r.get("tratamiento_iva")) == "Exento / Excluido (0%)" else float(r.get("porcentaje_iva", iva_hdr_def)),
            axis=1
        )

        iva_total_acum = (subtotal_item_serie * (df_items["iva_pct_real"] / 100.0)).sum()
        total_oferta = subtotal_venta + iva_total_acum
    else:
        costo_total_acum = 0.0
        subtotal_venta = float(cot_info["subtotal"] or 0.0)
        iva_total_acum = float(cot_info["impuesto_iva"] or 0.0)
        total_oferta = float(cot_info["total"] or 0.0)

    utilidad_bruta = subtotal_venta - costo_total_acum
    margen_global_pct = (utilidad_bruta / subtotal_venta * 100.0) if subtotal_venta > 0 else 0.0

    # ==========================================
    # 3. RESUMEN FINANCIERO Y COMPARATIVA SECOP
    # ==========================================
    st.markdown("##### 📈 Resumen Financiero y Comparativa SECOP")

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
        badge_po = f"↑ +${diferencia:,.2f} Holgura (-{pct_desviacion:.1f}%)" if presupuesto_oficial > 0 else "📌 Sin Techo Oficial"
        tipo_card_po = "blue"
        tipo_card_oferta = "green"
        badge_oferta = "✅ VIABLE (Dentro de Techo)" if presupuesto_oficial > 0 else "ℹ️ Sin Límite Definido"

    # FILA 1 DE TARJETAS (Comparativa SECOP - 3 Columnas)
    r1_col1, r1_col2, r1_col3 = st.columns(3)

    with r1_col1:
        st.markdown(
            render_card_html(
                "📋 PROCESO / LICITACIÓN", 
                str(n_proc), 
                badge_text="📄 Código Registrado", 
                card_type="neutral"
            ), 
            unsafe_allow_html=True
        )

    with r1_col2:
        val_po = f"${presupuesto_oficial:,.2f}" if presupuesto_oficial > 0 else "N/A"
        st.markdown(
            render_card_html(
                "🏛️ PRESUPUESTO OFICIAL", 
                val_po, 
                badge_text=badge_po, 
                card_type=tipo_card_po
            ), 
            unsafe_allow_html=True
        )

    with r1_col3:
        st.markdown(
            render_card_html(
                "🚀 TOTAL OFERTA", 
                f"${total_oferta:,.2f}", 
                badge_text=badge_oferta, 
                card_type=tipo_card_oferta
            ), 
            unsafe_allow_html=True
        )

    # ==========================================
    # BANNER / TARJETA DE VIABILIDAD ESTRUCTURADA
    # ==========================================
    if es_inviable:
        st.markdown(
            f"""
            <div style="
                background-color: rgba(239, 68, 68, 0.12);
                border: 1px solid #ef4444;
                border-left: 6px solid #ef4444;
                border-radius: 8px;
                padding: 16px;
                margin: 15px 0;
                color: #ffffff;
            ">
                <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 12px;">
                    <span style="font-size: 1.3rem;">🚨</span>
                    <strong style="font-size: 1.05rem; color: #f87171; letter-spacing: 0.5px;">
                        OFERTA INVIABLE — SUPERACIÓN DE TECHO PRESUPUESTAL
                    </strong>
                </div>
                <div style="
                    display: grid; 
                    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); 
                    gap: 12px; 
                    background: rgba(0,0,0,0.25); 
                    padding: 12px 16px; 
                    border-radius: 6px;
                ">
                    <div>
                        <span style="color: #a0a6b5; font-size: 0.75rem; display: block; text-transform: uppercase; font-weight: 600;">Presupuesto Oficial</span>
                        <strong style="color: #ffffff; font-size: 1.1rem;">&#36;{presupuesto_oficial:,.2f}</strong>
                    </div>
                    <div>
                        <span style="color: #a0a6b5; font-size: 0.75rem; display: block; text-transform: uppercase; font-weight: 600;">Total Oferta</span>
                        <strong style="color: #f87171; font-size: 1.1rem;">&#36;{total_oferta:,.2f}</strong>
                    </div>
                    <div>
                        <span style="color: #a0a6b5; font-size: 0.75rem; display: block; text-transform: uppercase; font-weight: 600;">Exceso / Sobrecosto</span>
                        <strong style="color: #f87171; font-size: 1.1rem;">+&#36;{monto_diferencia:,.2f} <span style="font-size: 0.85rem; font-weight: 400;">(+{pct_desviacion:.1f}%)</span></strong>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )
    elif presupuesto_oficial > 0:
        st.markdown(
            f"""
            <div style="
                background-color: rgba(34, 197, 94, 0.12);
                border: 1px solid #22c55e;
                border-left: 6px solid #22c55e;
                border-radius: 8px;
                padding: 16px;
                margin: 15px 0;
                color: #ffffff;
            ">
                <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 12px;">
                    <span style="font-size: 1.3rem;">✅</span>
                    <strong style="font-size: 1.05rem; color: #4ade80; letter-spacing: 0.5px;">
                        OFERTA VIABLE — DENTRO DEL TECHO PRESUPUESTAL
                    </strong>
                </div>
                <div style="
                    display: grid; 
                    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); 
                    gap: 12px; 
                    background: rgba(0,0,0,0.25); 
                    padding: 12px 16px; 
                    border-radius: 6px;
                ">
                    <div>
                        <span style="color: #a0a6b5; font-size: 0.75rem; display: block; text-transform: uppercase; font-weight: 600;">Presupuesto Oficial</span>
                        <strong style="color: #ffffff; font-size: 1.1rem;">&#36;{presupuesto_oficial:,.2f}</strong>
                    </div>
                    <div>
                        <span style="color: #a0a6b5; font-size: 0.75rem; display: block; text-transform: uppercase; font-weight: 600;">Total Oferta</span>
                        <strong style="color: #4ade80; font-size: 1.1rem;">&#36;{total_oferta:,.2f}</strong>
                    </div>
                    <div>
                        <span style="color: #a0a6b5; font-size: 0.75rem; display: block; text-transform: uppercase; font-weight: 600;">Holgura Disponible</span>
                        <strong style="color: #4ade80; font-size: 1.1rem;">&#36;{monto_diferencia:,.2f} <span style="font-size: 0.85rem; font-weight: 400;">(-{pct_desviacion:.1f}%)</span></strong>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

    # FILA 2 DE TARJETAS (Métricas Económicas internas - 4 Columnas)
    r2_col1, r2_col2, r2_col3, r2_col4 = st.columns(4)

    with r2_col1:
        st.markdown(
            render_card_html(
                "📦 COSTO BASE NETO", 
                f"${costo_total_acum:,.2f}", 
                badge_text="📊 Total Insumos", 
                card_type="neutral"
            ), 
            unsafe_allow_html=True
        )

    with r2_col2:
        st.markdown(
            render_card_html(
                "🏷️ SUBTOTAL VENTA", 
                f"${subtotal_venta:,.2f}", 
                badge_text="💵 Antes de Impuestos", 
                card_type="neutral"
            ), 
            unsafe_allow_html=True
        )

    with r2_col3:
        st.markdown(
            render_card_html(
                "🏛️ IVA ESTIMADO", 
                f"${iva_total_acum:,.2f}", 
                badge_text="🧾 Impuesto Indirecto", 
                card_type="neutral"
            ), 
            unsafe_allow_html=True
        )

    with r2_col4:
        badge_ub = f"↑ {margen_global_pct:.2f}% Margen Real"
        st.markdown(
            render_card_html(
                "💰 UTILIDAD BRUTA", 
                f"${utilidad_bruta:,.2f}", 
                badge_text=badge_ub, 
                card_type="green"
            ), 
            unsafe_allow_html=True
        )

    st.markdown("---")

    # 4. PANEL REORGANIZADO DE ACCIONES Y CONTROLES (ESTANDARIZADO Y ALINEADO)
    st.markdown("##### ⚙️ Acciones y Gestión de Cotización")

    # FILA 1: Estado de Cotización (Selectbox) y Descargar Excel
    f1_col1, f1_col2 = st.columns(2)

    with f1_col1:
        estados_disponibles = ["BORRADOR", "ENVIADA", "APROBADA", "RECHAZADA"]
        idx_est = (
            estados_disponibles.index(cot_info["estado"])
            if cot_info["estado"] in estados_disponibles
            else 0
        )
        nuevo_estado = st.selectbox(
            "Estado de Cotización",
            estados_disponibles,
            index=idx_est,
            key=f"est_{cot_id_sel}",
        )
        if nuevo_estado != cot_info["estado"]:
            actualizar_estado_cotizacion(cot_id_sel, nuevo_estado)
            st.success(f"Estado actualizado a {nuevo_estado}")
            st.rerun()

    with f1_col2:
        # Compensador visual (28px) para alinear el botón con la caja del selectbox de la izquierda
        st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
        excel_bytes = generar_excel_cotizacion(cot_info.to_dict(), df_items)
        st.download_button(
            label="📥 Descargar Excel",
            data=excel_bytes,
            file_name=f"cotizacion_{cot_info['numero_cotizacion']}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key=f"btn_download_{cot_id_sel}",
        )

    # FILA 2: Editar Encabezado y Eliminar Cotización
    f2_col1, f2_col2 = st.columns(2)

    with f2_col1:
        if st.button(
            "✏️ Editar Encabezado",
            use_container_width=True,
            key=f"btn_edit_enc_{cot_id_sel}",
        ):
            modal_editar_encabezado(cot_info, cot_id_sel)

    with f2_col2:
        with st.popover("🗑️ Eliminar Cotización", use_container_width=True):
            st.warning("⚠️ Acción permanente. Eliminará la cotización e ítems asociados.")
            if st.button(
                "Confirmar Eliminación",
                type="primary",
                key=f"btn_del_{cot_id_sel}",
                use_container_width=True,
            ):
                eliminar_cotizacion_completa(cot_id_sel)
                st.session_state.pop("cot_id_activa", None)
                st.rerun()

    st.markdown("---")

    # 5. TABLA DE ÍTEMS CON BARRA INTEGRADA
    col_hdr_tbl, col_btn_tbl = st.columns([3, 1])
    with col_hdr_tbl:
        st.markdown(f"#### 📦 Ítems Incluidos ({len(df_items)} ítems)")
    with col_btn_tbl:
        btn_agregar_tabla = st.button("➕ Añadir Ítem", type="primary", use_container_width=True, key=f"btn_add_tbl_{cot_id_sel}")

    st.caption("💡 **Tip:** Haz clic sobre cualquier fila para abrir la Calculadora y Editar el Ítem.")

    idx_seleccionado = None

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
    else:
        st.info("Esta cotización aún no contiene ítems asociados.")

    # 6. DISPARO EXCLUSIVO DE MODALES
    if btn_agregar_tabla:
        modal_agregar_item(cot_id_sel, cot_info)
    elif idx_seleccionado is not None:
        item_row = df_items.iloc[idx_seleccionado]
        modal_editar_item(cot_id_sel, item_row, df_items)

# ==============================================================================
# ENTRADA PRINCIPAL Y HELPERS
# ==============================================================================
def render_tab_historico():
    df_cot = cargar_cotizaciones()

    if df_cot.empty:
        st.subheader("📊 Histórico y Control de Cotizaciones")
        st.info("No hay cotizaciones registradas en la base de datos.")
        return

    if "cot_id_activa" in st.session_state and st.session_state["cot_id_activa"]:
        render_editor_cotizacion(st.session_state["cot_id_activa"], df_cot)
    else:
        render_registro_general(df_cot)

def obtener_badge_plazo_html(fecha_limite_val):
    if not fecha_limite_val or pd.isna(fecha_limite_val):
        return '<span style="color: #a0a6b5; font-size: 0.85rem;">📅 <strong>Plazo:</strong> Sin fecha registrada</span>'

    dt_limite = None
    if isinstance(fecha_limite_val, (datetime.datetime, pd.Timestamp)):
        dt_limite = fecha_limite_val
    elif isinstance(fecha_limite_val, str):
        formatos = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d"]
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
        abs_diff = abs(diferencia)
        dias = abs_diff.days
        horas = abs_diff.seconds // 3600
        tiempo_str = f"{dias} días {horas} h" if dias > 0 else f"{horas} h"
        return (
            f'<div style="display: inline-flex; align-items: center; background: rgba(211, 47, 47, 0.2); border: 1px solid #d32f2f; border-radius: 6px; padding: 4px 10px;">'
            f'<span style="color: #ef5350; font-size: 0.85rem; font-weight: 600;">'
            f'❌ <strong>Plazo:</strong> {str_fecha_fmt} '
            f'<span style="margin-left: 6px; background: #d32f2f; color: #ffffff; padding: 1px 6px; border-radius: 4px; font-size: 0.75rem;">Vencido ({tiempo_str})</span>'
            f'</span></div>'
        )
    else:
        dias = diferencia.days
        horas = diferencia.seconds // 3600
        return (
            f'<div style="display: inline-flex; align-items: center; background: rgba(46, 125, 50, 0.2); border: 1px solid #2e7d32; border-radius: 6px; padding: 4px 10px;">'
            f'<span style="color: #81c784; font-size: 0.85rem; font-weight: 600;">'
            f'⏳ <strong>Plazo:</strong> {str_fecha_fmt} '
            f'<span style="margin-left: 6px; background: #2e7d32; color: #ffffff; padding: 1px 6px; border-radius: 4px; font-size: 0.75rem;">Vigente (Quedan {dias} días {horas} h)</span>'
            f'</span></div>'
        )
  