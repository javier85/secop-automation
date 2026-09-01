import os
import re
import platform
import subprocess
import pandas as pd
import streamlit as st
from pathlib import Path
from config import BASE_SECOP_DIR
from datetime import datetime
from database.secop_db import (
    cargar_licitaciones,
    eliminar_licitacion_secop,
    guardar_licitacion_secop,
)
from services.excel_service import generar_excel_licitaciones
from services.n8n_service import disparar_sincronizacion_secop
from services.filesystem_service import crear_carpeta_licitacion

# Pipeline Simplificado de Estados SECOP
ESTADOS_LICITACION = [
    "EN EVALUACIÓN",
    "DESCARTADA",
    "PRESENTADA",
    "NO GANADA",
    "GANADA / EN EJECUCIÓN",
    "FINALIZADA",
]

# Definición segura de fragment para versiones anteriores a Streamlit 1.33.0
if hasattr(st, "fragment"):
    fragment_decorator = st.fragment(run_every="60s")
else:

    def fragment_decorator(func):
        return func


def limpiar_fecha_plazo(plazo_str: str) -> str:
    """Limpia cadenas de fecha removiendo la zona horaria entre paréntesis y normalizando AM/PM."""
    if not plazo_str or pd.isna(plazo_str):
        return ""

    # Remueve el texto de zona horaria como (UTC-05:00) Bogotá, Lima, Quito
    texto_limpio = re.sub(r"\s*\([^)]*\)", "", str(plazo_str)).strip()

    # Normaliza variaciones de AM / PM
    texto_limpio = re.sub(r"\bA\.M\b", "AM", texto_limpio, flags=re.IGNORECASE)
    texto_limpio = re.sub(r"\bP\.M\b", "PM", texto_limpio, flags=re.IGNORECASE)

    return texto_limpio

# Verificación de compatibilidad para la API de Diálogos
dialog_decorator = (
    st.dialog if hasattr(st, "dialog") else st.experimental_dialog
)


@dialog_decorator("📄 Detalle y Edición del Proceso", width="large")
def mostrar_modal_licitacion(lic_data):
    tab_ver, tab_editar = st.tabs(
        ["👁️ Ver Información Completa", "✏️ Editar Datos"]
    )

    with tab_ver:
        st.markdown(f"**Objeto del Proceso:**\n{lic_data['objeto']}")
        st.markdown(
            f"**Presupuesto:** {lic_data.get('Presupuesto (COP)', '$ 0.00')}"
        )
        st.markdown(
            f"**Plazo:** {lic_data['plazo_presentacion']} ({lic_data['semaforo']})"
        )
        st.markdown(f"**Estado:** `{lic_data['estado']}`")

        if lic_data.get("observaciones"):
            st.info(f"**Observaciones:** {lic_data['observaciones']}")

        c1, c2 = st.columns(2)
        with c1:
            if lic_data.get("enlace_secop"):
                st.link_button(
                    "🌐 Abrir en SECOP",
                    lic_data["enlace_secop"],
                    use_container_width=True,
                )
        with c2:
            ruta_carp = str(lic_data.get("carpeta", ""))
            if ruta_carp and os.path.exists(ruta_carp):
                if st.button(
                    "📂 Abrir Carpeta Local", use_container_width=True
                ):
                    abrir_carpeta_sistema(lic_data["carpeta"])
            elif ruta_carp:
                st.caption(f"📁 Ruta: `{ruta_carp}`")

    with tab_editar:
        with st.form(f"form_modal_edit_{lic_data['id']}"):
            e_num = st.text_input(
                "Número Proceso", value=str(lic_data["numero_proceso"])
            )
            e_ent = st.text_input("Entidad", value=str(lic_data["entidad"]))
            e_obj = st.text_area(
                "Objeto Completo",
                value=str(lic_data["objeto"]),
                height=120,
            )
            e_pres = st.number_input(
                "Presupuesto (COP)",
                value=float(lic_data["presupuesto"] or 0.0),
            )
            e_plazo = st.text_input(
                "Plazo Presentación",
                value=str(lic_data["plazo_presentacion"] or ""),
            )

            idx_est = (
                ESTADOS_LICITACION.index(lic_data["estado"])
                if lic_data["estado"] in ESTADOS_LICITACION
                else 0
            )
            e_est = st.selectbox("Estado", ESTADOS_LICITACION, index=idx_est)

            e_carp = st.text_input(
                "Carpeta / Ruta", value=str(lic_data["carpeta"] or "")
            )
            e_link = st.text_input(
                "Enlace SECOP", value=str(lic_data["enlace_secop"] or "")
            )
            e_obs = st.text_area(
                "Observaciones", value=str(lic_data["observaciones"] or "")
            )

            if st.form_submit_button(
                "💾 Guardar Cambios",
                type="primary",
                use_container_width=True,
            ):
                guardar_licitacion_secop(
                    id=int(lic_data["id"]),  # <-- Convertir explicitamente a int nativo de Python
                    numero_proceso=e_num,
                    entidad=e_ent,
                    objeto=e_obj,
                    presupuesto=float(e_pres),
                    plazo_presentacion=e_plazo,
                    estado=e_est,
                    carpeta=e_carp,
                    enlace_secop=e_link,
                    observaciones=e_obs,
                )
                st.success("¡Licitación actualizada!")
                st.rerun()


def calcular_semaforo(plazo_str):
    """Calcula la diferencia de tiempo con el formato exacto de Excel."""
    if not plazo_str or "Por definir" in str(plazo_str):
        return "Oferta Abierta"

    fecha_limite = None
    formatos = [
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ]

    for fmt in formatos:
        try:
            fecha_limite = datetime.strptime(str(plazo_str).strip(), fmt)
            break
        except ValueError:
            continue

    if not fecha_limite:
        return str(plazo_str)

    ahora = datetime.now()
    diferencia = fecha_limite - ahora
    segundos_totales = int(diferencia.total_seconds())

    es_vencido = segundos_totales < 0
    segundos_abs = abs(segundos_totales)

    dias = segundos_abs // 86400
    horas = (segundos_abs % 86400) // 3600

    if es_vencido:
        return f"Vencido ({dias} días {horas} h)"
    return f"{dias} días {horas} h"


def estilo_semaforo(val):
    """Aplica el estilo de color CSS a las celdas de la columna Semáforo."""
    val_str = str(val).strip()

    if "Vencido" in val_str or "Cerrado" in val_str:
        return "background-color: #D32F2F; color: white; font-weight: bold; text-align: center;"

    if "días" in val_str:
        try:
            dias = int(val_str.split("días")[0].strip())
            if dias <= 2:
                return "background-color: #FBC02D; color: black; font-weight: bold; text-align: center;"
            else:
                return "background-color: #388E3C; color: white; font-weight: bold; text-align: center;"
        except ValueError:
            pass

    return "text-align: center;"


def abrir_carpeta_sistema(ruta: str):
    """Abre la carpeta del proceso según el sistema operativo subyacente."""
    if not os.path.exists(ruta):
        st.warning(f"La ruta no existe en el sistema actual: {ruta}")
        return

    sistema = platform.system()
    try:
        if sistema == "Windows":
            os.startfile(ruta)
        elif sistema == "Darwin":  # macOS
            subprocess.run(["open", ruta], check=True)
        else:  # Linux / Docker
            subprocess.run(["xdg-open", ruta], check=True)
    except Exception as e:
        st.error(
            f"No se puede abrir el explorador de archivos directamente desde este entorno ({sistema}): {e}"
        )


def categorizar_semaforo(val: str) -> str:
    """Clasifica el texto del semáforo en categorías de color."""
    val_str = str(val).strip()

    if not val_str or val_str in ["Sin fecha", "None", "nan"]:
        return "⚪ Sin Clasificación"

    if "Vencido" in val_str or "🔴" in val_str:
        return "🔴 Vencido"

    match = re.search(r"(\d+)\s*días", val_str)
    if match:
        dias = int(match.group(1))
        if dias <= 3:
            return "🟡 Urgente (≤ 3 días)"
        else:
            return "🟢 Vigente (> 3 días)"

    return "⚪ Sin Clasificación"


@fragment_decorator
def render_tab_secop():
    st.subheader("📌 Tablero de Oportunidades SECOP")
    st.markdown(
        "Visualiza, gestiona y sincroniza los procesos de contratación pública"
        " de SECOP registrados en la plataforma."
    )

    df_lic = cargar_licitaciones()

    if not df_lic.empty and "presupuesto" in df_lic.columns:
        df_lic["presupuesto"] = (
            pd.to_numeric(df_lic["presupuesto"], errors="coerce")
            .fillna(0.0)
            .astype(float)
        )

        df_lic["Presupuesto (COP)"] = df_lic["presupuesto"].apply(
            lambda x: f"$ {x:,.2f}".replace(",", "X")
            .replace(".", ",")
            .replace("X", ".")
        )

    if not df_lic.empty and "plazo_presentacion" in df_lic.columns:
        df_lic["semaforo"] = df_lic["plazo_presentacion"].apply(
            calcular_semaforo
        )

    col_sync, col_add, col_exp = st.columns([2, 2, 2])

    with col_sync:
        if st.button(
            "🔄 Sincronizar con n8n", type="primary", use_container_width=True
        ):
            with st.spinner("Solicitando sincronización a n8n..."):
                res_sync = disparar_sincronizacion_secop()
                if res_sync.get("exito"):
                    st.success("Sincronización activada correctamente en n8n.")
                    st.rerun()
                else:
                    st.error(f"Error al sincronizar: {res_sync.get('error')}")

    with col_add:
        with st.popover("➕ Registrar Licitación", use_container_width=True):
            st.markdown("##### Nueva Licitacion SECOP")
            with st.form("form_nueva_licitacion"):
                num_proc = st.text_input(
                    "Número Proceso *", placeholder="Ej: PMM-MC-010-2026"
                )
                entidad = st.text_input(
                    "Entidad Compradora *",
                    placeholder="Ej: Alcaldía de Manizales",
                )
                objeto = st.text_area(
                    "Objeto del Proceso", placeholder="Descripción breve..."
                )
                presupuesto = st.number_input(
                    "Presupuesto Estimado (COP)", min_value=0.0, step=100000.0
                )
                plazo = st.text_input(
                    "Plazo Presentación", placeholder="Ej: 30/08/2026 17:00"
                )
                estado = st.selectbox(
                    "Estado",
                    ESTADOS_LICITACION,
                )
                carpeta = st.text_input(
                    "Carpeta / ID Drive", placeholder="Ej: Abrir 14 Alcaldia"
                )
                link = st.text_input(
                    "Enlace SECOP",
                    placeholder="https://community.secop.gov.co/...",
                )
                obs = st.text_area("Observaciones")

                if st.form_submit_button(
                    "💾 Guardar Licitación",
                    type="primary",
                    use_container_width=True,
                ):
                    if not num_proc.strip() or not entidad.strip():
                        st.error("El número de proceso y la entidad son obligatorios.")
                    else:
                        ruta_carpeta_final = crear_carpeta_licitacion(carpeta.strip() if carpeta.strip() else num_proc.strip())

                        guardar_licitacion_secop(
                            id=int(lic_data["id"]),  # <-- Convertir explicitamente a int nativo de Python
                            numero_proceso=edit_num,
                            entidad=edit_ent,
                            objeto=edit_obj,
                            presupuesto=float(edit_pres),
                            plazo_presentacion=edit_plazo,
                            estado=edit_est,
                            carpeta=edit_carp,
                            enlace_secop=edit_link,
                            observaciones=edit_obs,
                        )
                        st.success("Licitación registrada/actualizada exitosamente con su estructura de carpetas.")
                        st.rerun()

    with col_exp:
        if not df_lic.empty:
            excel_data = generar_excel_licitaciones(df_lic)
            st.download_button(
                label="📥 Exportar a Excel",
                data=excel_data,
                file_name="licitaciones_secop.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        else:
            st.button(
                "📥 Exportar a Excel", disabled=True, use_container_width=True
            )

    st.markdown("---")

    if df_lic.empty:
        st.info("No hay procesos de licitación registrados.")
        return

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Total Procesos", len(df_lic))
    with m2:
        nuevas_cnt = (
            len(df_lic[df_lic["estado"] == "NUEVA"])
            if "estado" in df_lic
            else 0
        )
        st.metric("Nuevas Oportunidades", nuevas_cnt)
    with m3:
        vencidas_cnt = (
            len(df_lic[df_lic["semaforo"].astype(str).str.contains("Vencido", na=False)])
            if "semaforo" in df_lic
            else 0
        )
        st.metric("Vencidas / Alerta", vencidas_cnt)

    st.markdown("##### 🔍 Filtros de Búsqueda")

    df_lic["estado_clean"] = df_lic["estado"].fillna("Sin Estado")
    df_lic["categoria_semaforo"] = df_lic["semaforo"].apply(
        categorizar_semaforo
    )

    col_f1, col_f2, col_f3 = st.columns([3, 2, 2])

    with col_f1:
        query = st.text_input(
            "Buscar por Entidad, Objeto o Número de Proceso", key="search_secop"
        )

    with col_f2:
        estados_disponibles = sorted(
            list(
                set(
                    ESTADOS_LICITACION + df_lic["estado_clean"].unique().tolist()
                )
            )
        )
        filtro_estado = st.multiselect(
            "Filtrar por Estado",
            options=estados_disponibles,
            default=[],
            placeholder="Todos los estados",
        )

    with col_f3:
        categorias_posibles = [
            "🔴 Vencido",
            "🟡 Urgente (≤ 3 días)",
            "🟢 Vigente (> 3 días)",
            "⚪ Sin Clasificación",
        ]
        opciones_sem = [
            cat
            for cat in categorias_posibles
            if cat in df_lic["categoria_semaforo"].values
        ]

        filtro_sem = st.multiselect(
            "Filtrar por Semáforo",
            options=opciones_sem,
            default=[],
            placeholder="Todos los colores",
        )

    df_filtrado = df_lic.copy()

    if query.strip():
        q_clean = query.strip().lower()
        df_filtrado = df_filtrado[
            df_filtrado["numero_proceso"].astype(str).str.lower().str.contains(q_clean)
            | df_filtrado["entidad"].astype(str).str.lower().str.contains(q_clean)
            | df_filtrado["objeto"].astype(str).str.lower().str.contains(q_clean)
        ]

    if filtro_estado:
        df_filtrado = df_filtrado[df_filtrado["estado_clean"].isin(filtro_estado)]

    if filtro_sem:
        df_filtrado = df_filtrado[
            df_filtrado["categoria_semaforo"].isin(filtro_sem)
        ]

    df_filtrado = df_filtrado.drop(
        columns=["estado_clean", "categoria_semaforo"], errors="ignore"
    )

    st.markdown("---")

    st.markdown(f"#### 📋 Lista de Procesos ({len(df_filtrado)})")
    st.caption(
        "💡 Haz clic sobre cualquier fila para abrir el panel con la información completa o editar."
    )

    df_estilizado = df_filtrado.style.map(
        estilo_semaforo, subset=["semaforo"]
    )

    evento_tabla = st.dataframe(
        df_estilizado,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_order=[
            "numero_proceso",
            "semaforo",
            "plazo_presentacion",
            "estado",
            "carpeta",
            "Presupuesto (COP)",
            "entidad",
            "objeto",
            "enlace_secop",
        ],
        column_config={
            "numero_proceso": st.column_config.TextColumn("Número Proceso", width="medium"),
            "semaforo": st.column_config.TextColumn("Semáforo"),
            "plazo_presentacion": st.column_config.TextColumn("Plazo Presentación", width="medium"),
            "estado": st.column_config.SelectboxColumn(
                "Estado",
                options=ESTADOS_LICITACION, width="medium",
            ),
            "carpeta": st.column_config.LinkColumn("Carpeta OneDrive", display_text="☁️ Abrir en OneDrive", width="medium"),
            "Presupuesto (COP)": st.column_config.TextColumn("Presupuesto (COP)", width="medium"),
            "entidad": st.column_config.TextColumn("Entidad", width="medium"),
            "objeto": st.column_config.TextColumn("Objeto", width="large"),
            "enlace_secop": st.column_config.LinkColumn("Enlace SECOP", width="medium"),
        },
    )

    filas_seleccionadas = evento_tabla.selection.rows if evento_tabla else []
    if filas_seleccionadas:
        idx_sel = filas_seleccionadas[0]
        lic_data = df_filtrado.iloc[idx_sel]
        mostrar_modal_licitacion(lic_data)

    with st.expander("⚙️ Gestor Individual de Licitaciones (Modificar / Eliminar)"):
        opciones_lic = (
            {
                f"{row['numero_proceso']} - {row['entidad']} (ID: {row['id']})": row["id"]
                for _, row in df_filtrado.iterrows()
            }
            if not df_filtrado.empty
            else {}
        )

        if opciones_lic:
            lic_sel_label = st.selectbox(
                "Seleccionar proceso a gestionar", list(opciones_lic.keys())
            )
            lic_id_sel = opciones_lic[lic_sel_label]
            lic_data = df_filtrado[df_filtrado["id"] == lic_id_sel].iloc[0]

            ce1, ce2 = st.columns([3, 1])

            with ce1:
                with st.popover("✏️ Editar Licitación", use_container_width=True):
                    with st.form(f"form_edit_lic_{lic_id_sel}"):
                        edit_num = st.text_input(
                            "Número Proceso",
                            value=str(lic_data["numero_proceso"]),
                        )
                        edit_ent = st.text_input(
                            "Entidad", value=str(lic_data["entidad"])
                        )
                        edit_obj = st.text_area(
                            "Objeto", value=str(lic_data["objeto"])
                        )
                        edit_pres = st.number_input(
                            "Presupuesto",
                            value=float(lic_data["presupuesto"] or 0.0),
                        )
                        edit_plazo = st.text_input(
                            "Plazo",
                            value=str(lic_data["plazo_presentacion"] or ""),
                        )

                        idx_est = (
                            ESTADOS_LICITACION.index(lic_data["estado"])
                            if lic_data["estado"] in ESTADOS_LICITACION
                            else 0
                        )
                        edit_est = st.selectbox(
                            "Estado", ESTADOS_LICITACION, index=idx_est
                        )

                        edit_carp = st.text_input(
                            "Carpeta", value=str(lic_data["carpeta"] or "")
                        )
                        edit_link = st.text_input(
                            "Enlace SECOP",
                            value=str(lic_data["enlace_secop"] or ""),
                        )
                        edit_obs = st.text_area(
                            "Observaciones",
                            value=str(lic_data["observaciones"] or ""),
                        )

                        if st.form_submit_button(
                            "💾 Guardar Cambios",
                            type="primary",
                            use_container_width=True,
                        ):
                            guardar_licitacion_secop(
                                id=lic_data["id"],  # <-- AGREGAR ESTA LÍNEA
                                numero_proceso=edit_num,
                                entidad=edit_ent,
                                objeto=edit_obj,
                                presupuesto=edit_pres,
                                plazo_presentacion=edit_plazo,
                                estado=edit_est,
                                carpeta=edit_carp,
                                enlace_secop=edit_link,
                                observaciones=edit_obs,
                            )
                            st.success("Licitación actualizada correctamente.")
                            st.rerun()

            with ce2:
                with st.popover("🗑️ Eliminar Licitación", use_container_width=True):
                    st.warning("⚠️ ¿Está seguro de eliminar esta licitación de la base de datos?")
                    if st.button(
                        "Confirmar Eliminación",
                        type="primary",
                        key=f"del_lic_{lic_id_sel}",
                        use_container_width=True,
                    ):
                        eliminar_licitacion_secop(lic_id_sel)
                        st.success("Licitación eliminada.")
                        st.rerun()