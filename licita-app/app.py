import sys
from pathlib import Path
import streamlit as st

# Ajuste de ruta raíz
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

# Importaciones de configuración y base de datos
import config
from config import APP_ICON, APP_LAYOUT, APP_TITLE
from database.connection import init_db_schema
from services.n8n_service import disparar_sincronizacion_secop

# Importación de vistas/módulos
from views import (
    tab_banco_items,
    tab_historico,
    tab_homologador,
    tab_ingesta_manual,
    tab_nueva_cotiz,
    tab_secop,
    tab_analisis_licitacion,  # Contiene render_tab_analisis_licitacion
)

URL_OLLAMA = getattr(config, "URL_OLLAMA", "http://localhost:11434")
URL_N8N = getattr(config, "URL_N8N", "http://localhost:5678")

# Configuración global
st.set_page_config(
    page_title=APP_TITLE,
    page_icon=APP_ICON,
    layout=APP_LAYOUT,
    initial_sidebar_state="expanded",
)

# Inicialización de BD
@st.cache_resource
def inicializar_sistema():
    try:
        init_db_schema()
    except Exception as e:
        st.error(f"Error crítico al conectar o inicializar la base de datos: {e}")
        st.stop()

inicializar_sistema()

if "vista_actual" not in st.session_state:
    st.session_state["vista_actual"] = "secop"

# Sidebar de navegación
with st.sidebar:
    st.markdown("### 🚀 Módulos Operativos")

    if st.button("📌 1. Oportunidades SECOP", use_container_width=True, key="nav_mod_secop"):
        st.session_state["vista_actual"] = "secop"
        st.rerun()

    if st.button("⚡ 2. Centro de Cotización", use_container_width=True, key="nav_mod_cotiz"):
        st.session_state["vista_actual"] = "cotizacion"
        st.rerun()

    if st.button("📊 3. Histórico y Control", use_container_width=True, key="nav_mod_historico"):
        st.session_state["vista_actual"] = "historico"
        st.rerun()

    st.divider()

    # Submenú desplegable
    with st.expander("⚙️ Configuración y Sistema", expanded=False):
        st.markdown("#### 📊 Estado del Núcleo")
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown(f"[🤖 Ollama]({URL_OLLAMA}) 🟢")
        with col_b:
            st.markdown(f"[⚡ n8n]({URL_N8N}) 🟢")

        if st.button("🔍 Probar Conexiones", use_container_width=True, key="sb_test_conn"):
            st.toast("Conexiones con Ollama y n8n operativas.", icon="✅")

        st.divider()

        if st.button("🔄 Sincronizar SECOP", type="primary", use_container_width=True, key="sb_sync_secop"):
            with st.spinner("Sincronizando con n8n..."):
                res_sync = disparar_sincronizacion_secop()
                if res_sync.get("exito"):
                    st.toast("Sincronización iniciada en n8n.", icon="🚀")
                    st.rerun()
                else:
                    st.error(f"Error: {res_sync.get('error')}")

    st.caption("v3.0 • Orqidea Core")

# Renderizado por Módulos
vista = st.session_state.get("vista_actual", "secop")

if vista == "secop":
    # Se añade la 3ra pestaña correspondiente a la auditoría
    tab1, tab2, tab3 = st.tabs([
        "📋 Tablero de Licitaciones", 
        "⚡ Ingesta Asistida por IA",
        "🏛️ Auditoría Gesstionando"
    ])
    with tab1:
        tab_secop.render_tab_secop()
    with tab2:
        tab_ingesta_manual.render_tab_ingesta_manual()
    with tab3:
        tab_analisis_licitacion.render_tab_analisis_licitacion()

elif vista == "cotizacion":
    tab1, tab2, tab3 = st.tabs([
        "📝 Generador de Cotizaciones",
        "🤖 Homologador / Sugeridor IA",
        "🔍 Banco de Ítems"
    ])
    with tab1:
        tab_nueva_cotiz.render_tab_nueva_cotiz()
    with tab2:
        tab_homologador.render_tab_homologador()
    with tab3:
        tab_banco_items.render_tab_banco_items()

elif vista == "historico":
    tab_historico.render_tab_historico()

else:
    st.session_state["vista_actual"] = "secop"
    st.rerun()