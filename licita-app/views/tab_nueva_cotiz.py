# views/tab_nueva_cotiz.py
import pandas as pd
import streamlit as st
from database.cotizaciones_db import (
    generar_numero_cotizacion,
    guardar_cotizacion,
)
from database.secop_db import cargar_licitaciones
from services.excel_service import generar_excel_cotizacion


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

    # Estado de la sesión para manejar la lista de ítems dinámicos
    if "items_cotizacion" not in st.session_state:
        st.session_state.items_cotizacion = []

    # ----------------------------------------------------
    # 1. FORMULARIO DE CABECERA (Únicamente st.form_submit_button dentro)
    # ----------------------------------------------------
    with st.form("form_nueva_cotizacion_cabecera"):
        st.markdown("##### 📄 Datos Comerciales")
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
                ["GENERAL", "EPP", "SOFTWARE", "INFRAESTRUCTURA", "SERVICIOS"],
            )

        col_c4, col_c5 = st.columns([2, 4])
        with col_c4:
            iva_pct = st.number_input(
                "Porcentaje IVA (%)", value=19.0, min_value=0.0, max_value=100.0
            )
        with col_c5:
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
                # Cálculo de totales acumulados
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
                else:
                    st.error(f"Error al guardar: {res.get('error')}")

    st.markdown("---")

    # ----------------------------------------------------
    # 2. GESTIÓN DE ÍTEMS (Fuera del formulario principal)
    # ----------------------------------------------------
    st.markdown("##### 📦 Ítems de la Cotización")

    with st.expander("➕ Agregar nuevo ítem a la lista", expanded=True):
        col_i1, col_i2, col_i3 = st.columns([4, 1, 1])
        with col_i1:
            desc_item = st.text_input(
                "Descripción del Insumo / Servicio", key="input_desc_item"
            )
        with col_i2:
            cant_item = st.number_input(
                "Cantidad", min_value=1.0, value=1.0, step=1.0
            )
        with col_i3:
            unid_item = st.text_input("Unidad", value="UNIDAD")

        col_i4, col_i5 = st.columns(2)
        with col_i4:
            costo_item = st.number_input(
                "Costo Unitario (COP)", min_value=0.0, step=1000.0
            )
        with col_i5:
            margen_item = st.number_input(
                "Margen (%)", min_value=0.0, value=20.0, step=1.0
            )

        if st.button("Añadir Ítem", use_container_width=True):
            if desc_item.strip():
                precio_venta = costo_item * (1 + (margen_item / 100.0))
                subtotal_item = precio_venta * cant_item

                st.session_state.items_cotizacion.append({
                    "numero_item": len(st.session_state.items_cotizacion) + 1,
                    "descripcion": desc_item.strip(),
                    "cantidad": cant_item,
                    "unidad_medida": unid_item.strip(),
                    "costo_unitario": costo_item,
                    "margen_porcentaje": margen_item,
                    "precio_venta_unitario": precio_venta,
                    "subtotal_item": subtotal_item,
                })
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
            },
        )

        if st.button("🗑️ Limpiar lista de ítems"):
            st.session_state.items_cotizacion = []
            st.rerun()

    st.markdown("---")

    # ----------------------------------------------------
    # 3. EXPORTACIÓN A EXCEL (Ubicado FUERA de st.form)
    # ----------------------------------------------------
    st.markdown("##### 📥 Exportar Borrador")
    if st.session_state.items_cotizacion:
        excel_bytes = generar_excel_cotizacion(
            num_cotizacion=num_cotiz,
            items=st.session_state.items_cotizacion,
            iva_pct=iva_pct,
        )
        st.download_button(
            label="📄 Descargar Cotización Actual en Excel",
            data=excel_bytes,
            file_name=f"Cotizacion_{num_cotiz}.xlsx",
            mime=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            use_container_width=True,
        )
    else:
        st.button(
            "📄 Descargar Cotización Actual en Excel",
            disabled=True,
            use_container_width=True,
        )