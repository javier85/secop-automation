import os
import platform
import re
import subprocess
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from pathlib import Path
from datetime import datetime, time
from config import BASE_SECOP_DIR
from utils.helpers import (
    obtener_fecha_hora_objetos,
)
from services.ai_service import (
    analizar_licitacion_con_gesstionando, 
    verificar_conexion_ollama,
)
from database.cotizaciones_db import (
    cargar_cotizaciones,
    cargar_items_por_cotizacion,
    actualizar_encabezado_cotizacion,
    crear_cotizacion_db,
    generar_numero_cotizacion,
)
from database.secop_db import (
    calcular_semaforo,
    cargar_licitaciones,
    eliminar_licitacion_secop,
    guardar_licitacion_secop,
    registrar_auditoria_ia,
)
from services.excel_service import generar_excel_licitaciones
from services.filesystem_service import (
    crear_carpeta_licitacion, 
    consolidar_documentos_licitacion,
)
from services.n8n_service import disparar_sincronizacion_secop

ESTADOS_LICITACION = [
    "EN EVALUACIÓN",
    "AUDITADO POR IA",
    "DESCARTADA",
    "PRESENTADA",
    "NO GANADA",
    "GANADA / EN EJECUCIÓN",
    "FINALIZADA",
]

if hasattr(st, "fragment"):
    fragment_decorator = st.fragment(run_every="60s")
else:
    def fragment_decorator(func):
        return func

dialog_decorator = st.dialog if hasattr(st, "dialog") else st.experimental_dialog
BASE_WINDOWS_SECOP = r"E:\OneDrive\Documentos\Empresa Puentes\Secop"

def obtener_ruta_windows_completa(ruta: str) -> str:
    if not ruta or pd.isna(ruta) or not str(ruta).strip():
        return ""
    ruta_str = str(ruta).strip()
    ruta_normalizada = ruta_str.replace("\\", "/")
    if re.match(r"^[a-zA-Z]:", ruta_str) and "data" not in ruta_str.lower():
        return str(Path(ruta_normalizada)).replace("/", "\\")
    nombre_subcarpeta = Path(ruta_normalizada).name
    return rf"{BASE_WINDOWS_SECOP}\{nombre_subcarpeta}"

def abrir_carpeta_sistema(ruta: str):
    ruta_win = obtener_ruta_windows_completa(ruta)
    if not ruta_win:
        st.warning("No se especificó ninguna ruta válida.")
        return
    sistema = platform.system()
    try:
        if sistema == "Windows" and os.path.exists(ruta_win):
            os.startfile(ruta_win)
            st.toast("📁 Carpeta abierta en el explorador", icon="✅")
        elif sistema == "Darwin" and os.path.exists(ruta_win):
            subprocess.Popen(["open", ruta_win])
            st.toast("📁 Carpeta abierta en el explorador", icon="✅")
        else:
            st.toast("📋 Copia la ruta directamente desde el recuadro superior", icon="ℹ️")
    except Exception as e:
        st.toast(f"No se pudo abrir automáticamente: {e}", icon="⚠️")

def estilo_semaforo(val):
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

def categorizar_semaforo(val: str) -> str:
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

# ==============================================================================
# MODAL NATIVO: CREAR NUEVA COTIZACIÓN PARA PROCESO SECOP
# ==============================================================================
@dialog_decorator("➕ Crear Nueva Cotización para el Proceso")
def modal_crear_cotizacion_proceso(num_proceso):
    st.markdown(f"Asociando cotización a licitación: **`{num_proceso}`**")
    
    with st.form(f"form_crear_cot_{num_proceso}"):
        col1, col2 = st.columns(2)
        with col1:
            num_cotiz_input = st.text_input(
                "Número de Cotización *",
                value=generar_numero_cotizacion(num_proceso),
                key=f"modal_num_cot_{num_proceso}"
            )
            tipo_cot = st.selectbox("Tipo de Cotización", ["GENERAL", "EPP", "SOFTWARE", "INFRAESTRUCTURA", "SERVICIOS"])
            margen_base = st.number_input("Margen Base (%)", min_value=0.0, max_value=100.0, value=20.0, step=1.0)
        with col2:
            iva_base = st.number_input("IVA Global (%)", min_value=0.0, max_value=100.0, value=19.0, step=1.0)
            estado_ini = st.selectbox("Estado Inicial", ["BORRADOR", "ENVIADA"])
            
        obs = st.text_area("Observaciones Iniciales", placeholder="Condiciones o notas de la cotización...")
        
        if st.form_submit_button("🚀 Generar y Abrir en Editor", type="primary", use_container_width=True):
            if not num_cotiz_input.strip():
                st.error("El número de cotización no puede estar vacío.")
            else:
                cot_id = crear_cotizacion_db(
                    numero_cotizacion=num_cotiz_input.strip(),
                    tipo_cotizacion=tipo_cot,
                    numero_proceso=num_proceso,
                    margen_global=margen_base,
                    porcentaje_iva=iva_base,
                    observaciones=obs.strip(),
                    estado=estado_ini
                )
                if cot_id:
                    st.session_state["cot_id_activa"] = cot_id
                    st.session_state["vista_actual"] = "historico"
                    st.toast("✅ Cotización creada exitosamente.", icon="🎉")
                    st.rerun()
                else:
                    st.error("Error al registrar la cotización en la base de datos.")

def componente_copiar_ruta(ruta: str):
    """Genera un botón/recuadro interactivo que copia la ruta al portapapeles al hacer clic."""
    ruta_escapada = ruta.replace("\\", "\\\\").replace("'", "\\'")
    
    html_code = f"""
    <div style="margin-bottom: 5px;">
        <button id="btnCopy" onclick="copiarAlPortapapeles()" style="
            width: 100%;
            padding: 10px 14px;
            background-color: #0E1117;
            color: #FAFAFA;
            border: 1px solid #4A4A4A;
            border-radius: 8px;
            cursor: pointer;
            font-family: monospace;
            font-size: 13px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            transition: background-color 0.2s ease;
        ">
            <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{ruta}</span>
            <span id="txtCopy" style="background: #262730; padding: 4px 8px; border-radius: 4px; font-size: 11px; margin-left: 8px; min-width: 65px; text-align: center;">📋 Copiar</span>
        </button>
    </div>

    <script>
    function copiarAlPortapapeles() {{
        const textToCopy = '{ruta_escapada}';
        
        if (navigator.clipboard && window.isSecureContext) {{
            navigator.clipboard.writeText(textToCopy);
        }} else {{
            let textArea = document.createElement("textarea");
            textArea.value = textToCopy;
            textArea.style.position = "fixed";
            textArea.style.left = "-999999px";
            document.body.appendChild(textArea);
            textArea.focus();
            textArea.select();
            document.execCommand('copy');
            textArea.remove();
        }}

        const label = document.getElementById('txtCopy');
        const btn = document.getElementById('btnCopy');
        label.innerText = '✅ ¡Copiado!';
        label.style.background = '#2E7D32';
        btn.style.borderColor = '#2E7D32';

        setTimeout(() => {{
            label.innerText = '📋 Copiar';
            label.style.background = '#262730';
            btn.style.borderColor = '#4A4A4A';
        }}, 2000);
    }}
    </script>
    """
    components.html(html_code, height=55)

@dialog_decorator("📄 Detalle y Edición del Proceso", width="large")
def mostrar_modal_licitacion(lic_data):
    tab_ver, tab_editar, tab_cotiz, tab_auditoria = st.tabs(
        ["👁️ Ver Información Completa", "✏️ Editar Datos", "💰 Cotizaciones", "🏛️ Auditoría Gesstionando"]
    )

    # --- TAB 1: VER INFORMACIÓN ---
    with tab_ver:
        st.markdown(f"**Objeto del Proceso:**\n{lic_data['objeto']}")
        st.markdown(f"**Presupuesto:** {lic_data.get('Presupuesto (COP)', '$ 0.00')}")
        st.markdown(f"**Plazo:** {lic_data['plazo_presentacion']} ({lic_data['semaforo']})")
        st.markdown(f"**Estado:** `{lic_data['estado']}`")

        if lic_data.get("observaciones"):
            st.info(f"**Observaciones:** {lic_data['observaciones']}")

        if lic_data.get("dictamen_ia") and str(lic_data["dictamen_ia"]).strip():
            st.markdown("---")
            with st.expander("🤖 Ver Dictamen de Auditoría IA", expanded=True):
                if lic_data.get("fecha_auditoria"):
                    st.caption(f"Fecha de auditoría: {lic_data['fecha_auditoria']}")
                st.markdown(lic_data["dictamen_ia"])

        c1, c2 = st.columns(2)
        with c1:
            if lic_data.get("enlace_secop"):
                st.link_button("🌐 Abrir en SECOP", lic_data["enlace_secop"], use_container_width=True)
        with c2:
            ruta_raw = str(lic_data.get("carpeta", "")).strip()
            if ruta_raw:
                ruta_completa = obtener_ruta_windows_completa(ruta_raw)
                st.markdown("**📁 Ruta Carpeta Local (Windows):**")
                componente_copiar_ruta(ruta_completa)
                if st.button("📂 Intentar Abrir Localmente", use_container_width=True):
                    abrir_carpeta_sistema(ruta_raw)

    # --- TAB 2: EDITAR DATOS DEL PROCESO ---
    with tab_editar:
        with st.form(f"form_modal_edit_{lic_data['id']}"):
            e_num = st.text_input("Número Proceso", value=str(lic_data["numero_proceso"]))
            e_ent = st.text_input("Entidad", value=str(lic_data["entidad"]))
            e_obj = st.text_area("Objeto Completo", value=str(lic_data["objeto"]), height=120)
            e_pres = st.number_input("Presupuesto (COP)", value=float(lic_data["presupuesto"] or 0.0))

            # --- NUEVO SELECTOR DE FECHA Y HORA ---
            fecha_val, hora_val = obtener_fecha_hora_objetos(lic_data.get("plazo_presentacion"))
            
            c_fec, c_hor = st.columns(2)
            with c_fec:
                e_fecha = st.date_input(
                    "Fecha Límite *",
                    value=fecha_val,
                    format="DD/MM/YYYY",
                    key=f"edit_fec_{lic_data['id']}"
                )
            with c_hor:
                e_hora = st.time_input(
                    "Hora Límite *",
                    value=hora_val,
                    key=f"edit_hor_{lic_data['id']}"
                )

            idx_est = ESTADOS_LICITACION.index(lic_data["estado"]) if lic_data["estado"] in ESTADOS_LICITACION else 0
            e_est = st.selectbox("Estado", ESTADOS_LICITACION, index=idx_est)
            e_carp = st.text_input("Carpeta / Ruta", value=str(lic_data["carpeta"] or ""))
            e_link = st.text_input("Enlace SECOP", value=str(lic_data["enlace_secop"] or ""))
            e_obs = st.text_area("Observaciones", value=str(lic_data["observaciones"] or ""))

            if st.form_submit_button("💾 Guardar Cambios", type="primary", use_container_width=True):
                # Reconstruir la cadena estandarizada DD/MM/YYYY HH:MM:SS
                if e_fecha:
                    plazo_final = f"{e_fecha.strftime('%d/%m/%Y')} {e_hora.strftime('%H:%M:%S')}"
                else:
                    plazo_final = "Sin fecha"

                guardar_licitacion_secop(
                    id=int(lic_data["id"]),
                    numero_proceso=e_num,
                    entidad=e_ent,
                    objeto=e_obj,
                    presupuesto=float(e_pres),
                    plazo_presentacion=plazo_final,
                    estado=e_est,
                    carpeta=e_carp,
                    enlace_secop=e_link,
                    observaciones=e_obs,
                )
                st.success("¡Licitación actualizada correctamente!")
                st.rerun()

    # --- TAB 3: GESTIÓN DE COTIZACIONES ASOCIADAS ---
    with tab_cotiz:
        num_proceso = str(lic_data["numero_proceso"])
        st.markdown(f"##### 📄 Cotizaciones vinculadas a `{num_proceso}`")

        df_todas_cot = cargar_cotizaciones()
        df_cot_lic = (
            df_todas_cot[df_todas_cot["numero_proceso"] == num_proceso]
            if not df_todas_cot.empty
            else pd.DataFrame()
        )

        if not df_cot_lic.empty:
            st.dataframe(
                df_cot_lic,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "id": None,
                    "subtotal": st.column_config.NumberColumn("Subtotal", format="$ %,.2f"),
                    "impuesto_iva": st.column_config.NumberColumn("IVA", format="$ %,.2f"),
                    "total": st.column_config.NumberColumn("Total", format="$ %,.2f"),
                },
            )

            cot_ids = {
                f"Cotización #{r['numero_cotizacion']} ({r['estado']})": r["id"]
                for _, r in df_cot_lic.iterrows()
            }
            cot_sel = st.selectbox("Ver detalle de cotización", list(cot_ids.keys()))
            if cot_sel:
                cot_id_seleccionada = cot_ids[cot_sel]
                items_df = cargar_items_por_cotizacion(cot_id_seleccionada)
                st.dataframe(items_df, use_container_width=True, hide_index=True)
                
                if st.button("✏️ Abrir esta Cotización en Editor", key=f"btn_open_ed_{cot_id_seleccionada}", use_container_width=True):
                    st.session_state["cot_id_activa"] = cot_id_seleccionada
                    st.session_state["vista_actual"] = "historico"
                    st.rerun()
        else:
            st.info("No existen cotizaciones registradas para este proceso.")

        st.markdown("---")

        # FORMULARIO EMBEDIDO EN LUGAR DE MODAL ANIDADO
        with st.expander("➕ Crear Nueva Cotización para este Proceso", expanded=df_cot_lic.empty):
            with st.form(f"form_crear_cot_inline_{num_proceso}"):
                col1, col2 = st.columns(2)
                with col1:
                    # 1. Traer el consecutivo dinámico basado en num_proceso y permitir editarlo
                    num_cotiz_input = st.text_input(
                        "Número de Cotización *",
                        value=generar_numero_cotizacion(num_proceso),
                        key=f"num_cot_{num_proceso}"
                    )
                    tipo_cot = st.selectbox("Tipo de Cotización", ["GENERAL", "EPP", "SOFTWARE", "INFRAESTRUCTURA", "SERVICIOS"], key=f"tipo_cot_{num_proceso}")
                    margen_base = st.number_input("Margen Base (%)", min_value=0.0, max_value=100.0, value=20.0, step=1.0, key=f"margen_{num_proceso}")
                with col2:
                    iva_base = st.number_input("IVA Global (%)", min_value=0.0, max_value=100.0, value=19.0, step=1.0, key=f"iva_{num_proceso}")
                    estado_ini = st.selectbox("Estado Inicial", ["BORRADOR", "ENVIADA"], key=f"est_{num_proceso}")
                    
                obs = st.text_area("Observaciones Iniciales", placeholder="Condiciones o notas de la cotización...", key=f"obs_{num_proceso}")
                
                if st.form_submit_button("🚀 Generar y Abrir en Editor", type="primary", use_container_width=True):
                    if not num_cotiz_input.strip():
                        st.error("El número de cotización no puede estar vacío.")
                    else:
                        cot_id = crear_cotizacion_db(
                            numero_cotizacion=num_cotiz_input.strip(),
                            tipo_cotizacion=tipo_cot,
                            numero_proceso=num_proceso,
                            margen_global=margen_base,
                            porcentaje_iva=iva_base,
                            observaciones=obs.strip(),
                            estado=estado_ini
                        )
                        if cot_id:
                            st.session_state["cot_id_activa"] = cot_id
                            st.session_state["vista_actual"] = "historico"
                            st.toast("✅ Cotización creada exitosamente.", icon="🎉")
                            st.rerun()
                        else:
                            st.error("Error al registrar la cotización en la base de datos.")

        if st.button("📊 Ir al Histórico General", use_container_width=True):
            st.session_state["vista_actual"] = "historico"
            st.rerun()

    # --- TAB 4: AUDITORÍA GESSTIONANDO ---
    with tab_auditoria:
        num_proceso_actual = str(lic_data["numero_proceso"])
        ruta_carpeta_proceso = str(lic_data.get("carpeta", ""))
        ollama_activo = verificar_conexion_ollama()

        # Header de Estado
        col_status1, col_status2 = st.columns([3, 1])
        with col_status1:
            st.markdown(f"##### 🏛️ Auditoría y Viabilidad para `{num_proceso_actual}`")
        with col_status2:
            if ollama_activo:
                st.markdown("<span style='color: #4ade80; font-weight: 700; background: rgba(34,197,94,0.15); padding: 4px 10px; border-radius: 12px; border: 1px solid #22c55e;'>🟢 Ollama Online</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span style='color: #f87171; font-weight: 700; background: rgba(239,68,68,0.15); padding: 4px 10px; border-radius: 12px; border: 1px solid #ef4444;'>🔴 Ollama Offline</span>", unsafe_allow_html=True)

        st.caption("El motor escanea los expedientes en PDF dentro de la carpeta local y ejecuta la evaluación técnico-financiera con Ollama.")

        ruta_completa_win = obtener_ruta_windows_completa(ruta_carpeta_proceso)
        st.info(f"📁 **Carpeta Origen Escaneada:** `{ruta_completa_win or 'No especificada'}`")

        # Configuración y Ejecución
        col_cfg1, col_cfg2 = st.columns([1, 2])
        with col_cfg1:
            modelo_llm = st.selectbox(
                "Modelo IA Motor",
                ["llama3.2", "llama3.1", "mistral", "gemma2"],
                index=0,
                disabled=not ollama_activo,
                key=f"mod_ia_{lic_data['id']}"
            )
            
            btn_ejecutar = st.button(
                "🔍 Ejecutar Auditoría IA", 
                type="primary", 
                use_container_width=True, 
                disabled=not ollama_activo or not ruta_carpeta_proceso, 
                key=f"btn_auditoria_{lic_data['id']}"
            )

        with col_cfg2:
            if btn_ejecutar:
                with st.spinner("📄 Procesando documentos y evaluando viabilidad con Ollama..."):
                    try:
                        texto_plano_consolidado = consolidar_documentos_licitacion(ruta_carpeta_proceso)
                        informe_resultado = analizar_licitacion_con_gesstionando(
                            texto_consolidado=texto_plano_consolidado,
                            numero_proceso=num_proceso_actual,
                            model=modelo_llm
                        )
                        registrar_auditoria_ia(
                            numero_proceso=num_proceso_actual,
                            dictamen_completo=informe_resultado
                        )
                        st.toast(f"✅ Proceso {num_proceso_actual} auditado.", icon="💾")
                        st.session_state[f"last_audit_{lic_data['id']}"] = informe_resultado
                    except Exception as e:
                        st.error(f"Error al auditorizar: {str(e)}")

            informe_existente = st.session_state.get(f"last_audit_{lic_data['id']}") or lic_data.get("dictamen_ia")
            
            if informe_existente:
                st.markdown("### 📋 Dictamen Emitido")
                st.markdown(
                    f"<div style='background: #1e222d; border: 1px solid #2d3345; border-radius: 8px; padding: 15px; max-height: 400px; overflow-y: auto; color: #e2e8f0; font-size: 0.9rem;'>{informe_existente}</div>",
                    unsafe_allow_html=True
                )
                st.download_button(
                    label="📥 Descargar Informe Completo (.md)",
                    data=str(informe_existente),
                    file_name=f"Informe_Viabilidad_{num_proceso_actual}.md",
                    mime="text/markdown",
                    use_container_width=True,
                    key=f"dl_aud_{lic_data['id']}"
                )

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
            st.markdown("##### Nueva Licitación SECOP")
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

                # --- SELECTOR DE FECHA Y HORA ---
                c_fec_n, c_hor_n = st.columns(2)
                with c_fec_n:
                    n_fecha = st.date_input("Fecha Límite", value=None, format="DD/MM/YYYY")
                with c_hor_n:
                    n_hora = st.time_input("Hora Límite", value=time(17, 0, 0))

                estado = st.selectbox("Estado", ESTADOS_LICITACION)
                carpeta = st.text_input(
                    "Carpeta / ID Drive", placeholder="Ej: PMM-MC-010-2026"
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
                        st.error(
                            "El número de proceso y la entidad son obligatorios."
                        )
                    else:
                        ruta_carpeta_final = crear_carpeta_licitacion(
                            carpeta.strip()
                            if carpeta.strip()
                            else num_proc.strip()
                        )

                        # --- CONSTRUCCIÓN DEL PLAZO ---
                        if n_fecha:
                            plazo_nuevo = f"{n_fecha.strftime('%d/%m/%Y')} {n_hora.strftime('%H:%M:%S') if n_hora else '17:00:00'}"
                        else:
                            plazo_nuevo = "Sin fecha"

                        guardar_licitacion_secop(
                            id=None,
                            numero_proceso=num_proc.strip(),
                            entidad=entidad.strip(),
                            objeto=objeto.strip(),
                            presupuesto=float(presupuesto),
                            plazo_presentacion=plazo_nuevo,
                            estado=estado,
                            carpeta=ruta_carpeta_final,
                            enlace_secop=link.strip(),
                            observaciones=obs.strip(),
                        )
                        st.success("¡Licitación guardada correctamente!")
                        st.rerun()
    with col_exp:
        if not df_lic.empty:
            excel_data = generar_excel_licitaciones(df_lic)
            st.download_button(
                label="📥 Exportar a Excel",
                data=excel_data,
                file_name="licitaciones_secop.xlsx",
                mime=(
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                ),
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

    m1, m2, m3 = st.columns(3)
    with m1:
        st.metric("Total Procesos", len(df_lic))
    with m2:
        en_eval_cnt = (
            len(df_lic[df_lic["estado"] == "EN EVALUACIÓN"])
            if "estado" in df_lic
            else 0
        )
        st.metric("En Evaluación", en_eval_cnt)
    with m3:
        vencidas_cnt = (
            len(
                df_lic[
                    df_lic["semaforo"]
                    .astype(str)
                    .str.contains("Vencido", na=False)
                ]
            )
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
                    ESTADOS_LICITACION
                    + df_lic["estado_clean"].unique().tolist()
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
        df_filtrado = df_filtrado[
            df_filtrado["estado_clean"].isin(filtro_estado)
        ]

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
        "💡 Haz clic sobre cualquier fila para abrir el panel con la"
        " información completa o editar."
    )

    df_filtrado["ruta_windows"] = df_filtrado["carpeta"].apply(obtener_ruta_windows_completa)

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
            "ruta_windows",
            "Presupuesto (COP)",
            "entidad",
            "objeto",
            "enlace_secop",
        ],
        column_config={
            "numero_proceso": st.column_config.TextColumn(
                "Número Proceso", width="medium"
            ),
            "semaforo": st.column_config.TextColumn("Semáforo"),
            "plazo_presentacion": st.column_config.TextColumn(
                "Plazo Presentación", width="medium"
            ),
            "estado": st.column_config.SelectboxColumn(
                "Estado", options=ESTADOS_LICITACION, width="medium"
            ),
            "ruta_windows": st.column_config.TextColumn(
                "Ruta Carpeta",
                help="Doble clic o hover para copiar la ruta completa",
                width="large",
            ),
            "Presupuesto (COP)": st.column_config.TextColumn(
                "Presupuesto (COP)", width="medium"
            ),
            "entidad": st.column_config.TextColumn("Entidad", width="medium"),
            "objeto": st.column_config.TextColumn("Objeto", width="large"),
            "enlace_secop": st.column_config.LinkColumn(
                "Enlace SECOP", width="medium"
            ),
        },
    )
    
    filas_seleccionadas = evento_tabla.selection.rows if evento_tabla else []
    if filas_seleccionadas:
        idx_sel = filas_seleccionadas[0]
        lic_data = df_filtrado.iloc[idx_sel]
        mostrar_modal_licitacion(lic_data)

    with st.expander(
        "⚙️ Gestor Individual de Licitaciones (Modificar / Eliminar)"
    ):
        opciones_lic = (
            {
                f"{row['numero_proceso']} - {row['entidad']} (ID: {row['id']})": (
                    row["id"]
                )
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
                with st.popover(
                    "✏️ Editar Licitación", use_container_width=True
                ):
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
                                id=lic_data["id"],
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
                with st.popover(
                    "🗑️ Eliminar Licitación", use_container_width=True
                ):
                    st.warning(
                        "⚠️ ¿Está seguro de eliminar esta licitación de la base"
                        " de datos?"
                    )
                    if st.button(
                        "Confirmar Eliminación",
                        type="primary",
                        key=f"del_lic_{lic_id_sel}",
                        use_container_width=True,
                    ):
                        eliminar_licitacion_secop(lic_id_sel)
                        st.success("Licitación eliminada.")
                        st.rerun()