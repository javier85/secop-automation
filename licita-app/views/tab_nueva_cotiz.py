# views/tab_nueva_cotiz.py
import pandas as pd
import streamlit as st
from database.cotizaciones_db import (
    generar_numero_cotizacion,
    guardar_cotizacion,
)
from database.secop_db import cargar_licitaciones
from services.excel_service import generar_excel_cotizacion

# Mapeo global de Margen Real -> Factor Divisor (de 0% a 90% en pasos de 5%)
OPCIONES_MARGEN = {
    f"{p}% Margen Real (÷ {1 - p/100:.2f})": p / 100.0 for p in range(0, 95, 5)
}

def render_tab_nueva_cotiz():
    st.subheader("📝 Generador de Nueva Cotización")
    st.markdown(
        "Estructure y organice los ítems de costo, márgenes y precios de venta"
        " para la propuesta comercial."
    )

    df_lic = cargar_licitaciones()
    opciones_lic = {"-- Sin Asociación (Cotización General) --": ""}
    if not df_lic.empty:
        for _, row in df_lic.iterrows():
            opciones_lic[f"{row['numero_proceso']} - {row['entidad']}"] = row[
                "numero_proceso"
            ]

    if "items_cotizacion" not in st.session_state:
        st.session_state.items_cotizacion = []

    # ----------------------------------------------------
    # 1. FORMULARIO DE CABECERA (DATOS COMERCIALES Y REGLAS GLOBALES)
    # ----------------------------------------------------
    with st.form("form_nueva_cotizacion_cabecera"):
        st.markdown("##### 📄 Datos Comerciales & Parámetros Globales")
        col_c1, col_c2, col_c3 = st.columns(3)

        with col_c1:
            proceso_label = st.selectbox(
                "Asociar a Licitación SECOP", list(opciones_lic.keys())
            )
            num_proceso = opciones_lic[proceso_label]

        with col_c2:
            num_cotiz = st.text_input(
                "Número de Cotización *", value=generar_numero_cotizacion()
            )

        with col_c3:
            tipo_cotiz = st.selectbox(
                "Tipo de Cotización",
                [
                    "GENERAL",
                    "EPP",
                    "SOFTWARE",
                    "INFRAESTRUCTURA",
                    "SERVICIOS",
                ],
            )

        col_c4, col_c5, col_c6 = st.columns([1.5, 2.5, 3])
        with col_c4:
            iva_pct = st.number_input(
                "IVA Global (%)", value=19.0, min_value=0.0, max_value=100.0
            )
        with col_c5:
            # Selector de Margen Global predeterminado
            margen_global_sel = st.selectbox(
                "Margen Global Predeterminado",
                options=list(OPCIONES_MARGEN.keys()),
                index=4,  # Por defecto 20% Margen Real (÷ 0.80)
                help="Margen base que se aplicará por defecto a los ítems.",
            )
        with col_c6:
            observaciones = st.text_area(
                "Observaciones / Términos",
                placeholder="Validez de la oferta, tiempo de entrega, forma de pago...",
            )

        guardar_cabecera = st.form_submit_button(
            "💾 Registrar Cotización en BD",
            type="primary",
            use_container_width=True,
        )

        if guardar_cabecera:
            if not num_cotiz.strip():
                st.error("El número de cotización no puede estar vacío.")
            else:
                subtotal_acum = sum(
                    it.get("subtotal_item", 0.0)
                    for it in st.session_state.items_cotizacion
                )
                impuesto_val = subtotal_acum * (iva_pct / 100.0)
                total_val = subtotal_acum + impuesto_val

                res = guardar_cotizacion(
                    numero_cotizacion=num_cotiz.strip(),
                    numero_proceso=num_proceso,
                    tipo_cotizacion=tipo_cotiz,
                    porcentaje_iva=iva_pct,
                    subtotal=subtotal_acum,
                    impuesto_iva=impuesto_val,
                    total=total_val,
                    observaciones=observaciones.strip(),
                    items=st.session_state.items_cotizacion,
                )
                if res.get("exito"):
                    st.success(
                        f"Cotización {num_cotiz} registrada correctamente."
                    )
                    st.session_state.items_cotizacion = []
                    st.rerun()

    st.markdown("---")

    # ----------------------------------------------------
    # 2. GESTIÓN DE ÍTEMS (HEREDANDO MARGEN Y FACTOR)
    # ----------------------------------------------------
    st.markdown("### 📦 Ítems de la Cotización")

    with st.expander("➕ Agregar nuevo ítem a la lista", expanded=True):
        col_desc, col_cant, col_unid = st.columns([4, 1, 1])
        with col_desc:
            desc_item = st.text_input(
                "Descripción del Insumo / Servicio *", key="new_item_desc"
            )
        with col_cant:
            cant_item = st.number_input(
                "Cantidad", min_value=1.0, value=1.0, key="new_item_cant"
            )
        with col_unid:
            unid_item = st.text_input(
                "Unidad", value="UNIDAD", key="new_item_unid"
            )

        col_costo, col_modo_iva, col_tarifa_iva, col_margen = st.columns(
            [2, 2, 1.5, 2.5]
        )
        with col_costo:
            costo_ingresado = st.number_input(
                "Costo Unitario (COP) *",
                min_value=0.0,
                step=1000.0,
                key="new_item_costo",
            )
        with col_modo_iva:
            modo_iva = st.selectbox(
                "Origen del Costo",
                options=[
                    "Sin IVA (Antes de IVA)",
                    "Con IVA Incluido",
                    "Exento / Excluido (0%)",
                ],
                index=0,
                key="new_item_modo_iva",
            )
        with col_tarifa_iva:
            iva_disabled = modo_iva == "Exento / Excluido (0%)"
            tarifa_iva = st.number_input(
                "% IVA Ítem",
                min_value=0.0,
                max_value=100.0,
                value=0.0 if iva_disabled else iva_pct,  # Hereda el IVA Global
                disabled=iva_disabled,
                key="new_item_tarifa_iva",
            )
        with col_margen:
            # Carga por defecto el margen seleccionado en la cabecera
            idx_def = list(OPCIONES_MARGEN.keys()).index(margen_global_sel)
            margen_item_label = st.selectbox(
                "Margen Aplicado",
                options=list(OPCIONES_MARGEN.keys()),
                index=idx_def,
                key="new_item_margen_sel",
            )

        enlace_item = st.text_input(
            "Enlace / Proveedor (Opcional)",
            key="new_item_link",
            placeholder="https://...",
        )

        # Cálculo de la base del costo
        if modo_iva == "Con IVA Incluido" and tarifa_iva > 0:
            costo_base = costo_ingresado / (1 + (tarifa_iva / 100.0))
        else:
            costo_base = costo_ingresado

        # Extraer porcentaje y factor divisor
        margen_decimal = OPCIONES_MARGEN[margen_item_label]
        factor_divisor = 1.0 - margen_decimal

        # Cálculo del Precio con Factor Real (Costo / Factor)
        if factor_divisor <= 0:
            precio_venta_unitario = costo_base
        else:
            precio_venta_unitario = costo_base / factor_divisor

        subtotal_item = precio_venta_unitario * cant_item

        if costo_ingresado > 0:
            st.info(
                f"💡 **Desglose del Ítem:** "
                f"Costo Base Neto: **${costo_base:,.2f}** | "
                f"Factor: **÷ {factor_divisor:.2f}** | "
                f"Precio Venta Unitario: **${precio_venta_unitario:,.2f}** | "
                f"Subtotal Ítem: **${subtotal_item:,.2f}**"
            )

        if st.button(
            "➕ Añadir Ítem a la Lista",
            use_container_width=True,
            type="primary",
            key="btn_add_new_item",
        ):
            if not desc_item.strip():
                st.error("Por favor ingrese una descripción para el ítem.")
            else:
                nuevo_item = {
                    "descripcion": desc_item.strip(),
                    "cantidad": cant_item,
                    "unidad_medida": unid_item.strip(),
                    "costo_unitario": costo_base,
                    "margen_porcentaje": margen_decimal * 100.0,
                    "precio_venta_unitario": precio_venta_unitario,
                    "subtotal_item": subtotal_item,
                    "enlace_referencia": enlace_item.strip(),
                }
                st.session_state.items_cotizacion.append(nuevo_item)
                st.success(f"Ítem '{desc_item}' añadido a la lista.")
                st.rerun()

    # Tabla de resumen de ítems agregados
    if st.session_state.items_cotizacion:
        df_items = pd.DataFrame(st.session_state.items_cotizacion)
        st.dataframe(
            df_items,
            use_container_width=True,
            hide_index=True,
            column_config={
                "costo_unitario": st.column_config.NumberColumn(
                    "Costo Unit.", format="$ %,.2f"
                ),
                "precio_venta_unitario": st.column_config.NumberColumn(
                    "P. Venta Unit.", format="$ %,.2f"
                ),
                "subtotal_item": st.column_config.NumberColumn(
                    "Subtotal Ítem", format="$ %,.2f"
                ),
                "enlace_referencia": st.column_config.LinkColumn(
                    "Enlace / Ref.", display_text="Ver Origen"
                ),
            },
        )

        if st.button("🗑️ Limpiar lista de ítems"):
            st.session_state.items_cotizacion = []
            st.rerun()

    st.markdown("---")

    # ----------------------------------------------------
    # 3. EXPORTACIÓN A EXCEL
    # ----------------------------------------------------
    st.markdown("##### 📥 Exportar Borrador")
    if st.session_state.items_cotizacion:
        cotizacion_data = {
            "numero_cotizacion": num_cotiz,
            "numero_proceso": num_proceso,
            "tipo_cotizacion": tipo_cotiz,
            "porcentaje_iva": iva_pct,
            "observaciones": observaciones,
        }

        excel_bytes = generar_excel_cotizacion(
            cotizacion_data, pd.DataFrame(st.session_state.items_cotizacion)
        )

        st.download_button(
            label="📄 Descargar Cotización Actual en Excel",
            data=excel_bytes,
            file_name=f"Cotizacion_{num_cotiz}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    else:
        st.button(
            "📄 Descargar Cotización Actual en Excel",
            disabled=True,
            use_container_width=True,
        )

def render_modal_editar_encabezado(cotizacion_actual):
    """Formulario para editar el encabezado de una cotización existente."""
    with st.popover("✏️ Editar Encabezado", use_container_width=True):
        with st.form("form_editar_encabezado_cotizacion"):
            st.markdown("##### 📄 Modificar Parámetros de la Cotización")

            col1, col2 = st.columns(2)
            with col1:
                tipo_cotiz = st.selectbox(
                    "Tipo Cotización",
                    ["GENERAL", "EPP", "SOFTWARE", "INFRAESTRUCTURA", "SERVICIOS"],
                    index=["GENERAL", "EPP", "SOFTWARE", "INFRAESTRUCTURA", "SERVICIOS"].index(
                        cotizacion_actual.get("tipo_cotizacion", "GENERAL")
                    ),
                )
            with col2:
                num_proceso = st.text_input(
                    "Número Proceso",
                    value=cotizacion_actual.get("numero_proceso", ""),
                )

            col3, col4 = st.columns(2)
            with col3:
                iva_pct = st.number_input(
                    "IVA Global (%)",
                    value=float(cotizacion_actual.get("porcentaje_iva", 19.0)),
                    min_value=0.0,
                    max_value=100.0,
                )
            with col4:
                # Margen Global para aplicar/recalcular
                margen_global_sel = st.selectbox(
                    "Margen Global Predeterminado",
                    options=list(OPCIONES_MARGEN.keys()),
                    index=4,  # Default 20%
                )

            observaciones = st.text_area(
                "Observaciones",
                value=cotizacion_actual.get("observaciones", ""),
            )

            # Opción para recalcular o no todos los ítems de la lista
            recalcular_items = st.checkbox(
                "🔄 Recalcular precios de ítems existentes con la fórmula de Margen Real (÷ Factor)",
                value=False,
                help="Aplica el nuevo factor divisor a los ítems guardados en la cotización.",
            )

            guardar = st.form_submit_button("💾 Guardar Cambios", type="primary")

            if guardar:
                margen_decimal = OPCIONES_MARGEN[margen_global_sel]
                factor_divisor = 1.0 - margen_decimal

                # Si se solicita recalcular los ítems existentes
                if recalcular_items and "items_cotizacion_actual" in st.session_state:
                    for item in st.session_state.items_cotizacion_actual:
                        costo_base = item.get("costo_unitario", 0.0)
                        if factor_divisor > 0:
                            nuevo_precio = costo_base / factor_divisor
                        else:
                            nuevo_precio = costo_base

                        item["precio_venta_unitario"] = nuevo_precio
                        item["subtotal_item"] = nuevo_precio * item.get("cantidad", 1.0)
                        item["margen_porcentaje"] = margen_decimal * 100.0

                # Actualizar metadatos de la cotización
                res = actualizar_encabezado_cotizacion(
                    numero_cotizacion=cotizacion_actual["numero_cotizacion"],
                    tipo_cotizacion=tipo_cotiz,
                    numero_proceso=num_proceso,
                    porcentaje_iva=iva_pct,
                    observaciones=observaciones,
                    items=st.session_state.get("items_cotizacion_actual", []),
                )

                if res.get("exito"):
                    st.success("Encabezado e ítems actualizados correctamente.")
                    st.rerun()