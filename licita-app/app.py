import sys
from pathlib import Path
import streamlit as st

# Ajustar ROOT_DIR al nivel raíz donde reside app.py
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from config import APP_ICON, APP_LAYOUT, APP_TITLE
from database.connection import init_db_schema
from services.n8n_service import disparar_sincronizacion_secop
from views import (
    tab_banco_items,
    tab_historico,
    tab_homologador,
    tab_ingesta_manual,
    tab_nueva_cotiz,
    tab_secop,
)

# 1. Configuración global de la página
st.set_page_config(
    page_title=APP_TITLE,
    page_icon=APP_ICON,
    layout=APP_LAYOUT,
    initial_sidebar_state="expanded",
)


# 2. Inicialización cached del esquema de base de datos
@st.cache_resource
def inicializar_sistema():
    try:
        init_db_schema()
    except Exception as e:
        st.error(f"Error crítico al conectar o inicializar la base de datos: {e}")


inicializar_sistema()

if "vista_actual" not in st.session_state:
    st.session_state["vista_actual"] = "secop"

URL_OLLAMA = "http://localhost:11434"
URL_N8N = "http://localhost:5678"

with st.sidebar.container(border=True):
    st.markdown("### 📊 Estado del Núcleo")

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown(f"[🤖 **Ollama**]({URL_OLLAMA}) 🟢")
    with col_b:
        st.markdown(f"[⚡ **n8n**]({URL_N8N}) 🟢")

    if st.button(
        "🔍 Probar Conexiones", use_container_width=True, key="sb_test_conn"
    ):
        st.toast("Conexiones con Ollama y n8n operativas.", icon="✅")

    st.divider()

    st.markdown("### 🚀 Navegación Rápida")

    if st.button(
        "📌 Licitaciones (SECOP)", use_container_width=True, key="nav_secop"
    ):
        st.session_state["vista_actual"] = "secop"
        st.rerun()

    if st.button(
        "📋 Ingesta Manual SECOP", use_container_width=True, key="nav_ingesta"
    ):
        st.session_state["vista_actual"] = "ingesta_manual"
        st.rerun()

    if st.button(
        "🤖 Homologador IA", use_container_width=True, key="nav_homologador"
    ):
        st.session_state["vista_actual"] = "homologador"
        st.rerun()

    if st.button(
        "🔍 Banco de Ítems", use_container_width=True, key="nav_banco"
    ):
        st.session_state["vista_actual"] = "banco_items"
        st.rerun()

    if st.button(
        "📝 Nueva Cotización", use_container_width=True, key="nav_cotizacion"
    ):
        st.session_state["vista_actual"] = "nueva_cotizacion"
        st.rerun()

    if st.button(
        "📊 Histórico y Control", use_container_width=True, key="nav_historico"
    ):
        st.session_state["vista_actual"] = "historico"
        st.rerun()

    st.divider()

    if st.button(
        "🔄 Sincronizar SECOP",
        type="primary",
        use_container_width=True,
        key="sb_sync_secop",
    ):
        with st.spinner("Sincronizando con n8n..."):
            res_sync = disparar_sincronizacion_secop()
            if res_sync.get("exito"):
                st.toast("Sincronización iniciada en n8n.", icon="🚀")
                st.rerun()
            else:
                st.error(f"Error: {res_sync.get('error')}")

    st.caption("v2.5 • Orqidea Core")

vista = st.session_state.get("vista_actual", "secop")

if vista == "secop":
    tab_secop.render_tab_secop()
elif vista == "ingesta_manual":
    tab_ingesta_manual.render_tab_ingesta_manual()
elif vista == "homologador":
    tab_homologador.render_tab_homologador()
elif vista == "banco_items":
    tab_banco_items.render_tab_banco_items()
elif vista == "nueva_cotizacion":
    tab_nueva_cotiz.render_tab_nueva_cotiz()
elif vista == "historico":
    tab_historico.render_tab_historico()