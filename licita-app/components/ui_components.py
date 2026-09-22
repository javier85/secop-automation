# components/ui_components.py
import re
import os
import platform
import subprocess
from pathlib import Path
import streamlit as st
import streamlit.components.v1 as components

from services.ai_service import verificar_conexion_ollama
from utils.cotizacion_utils import OPCIONES_MARGEN, calcular_desglose_item

BASE_WINDOWS_SECOP = r"E:\OneDrive\Documentos\Empresa Puentes\Secop"


def render_selector_ollama(key_prefix: str = "global"):
    """Renderiza el estado del servicio de Ollama y el selector unificado de modelos IA."""
    ollama_activo = verificar_conexion_ollama()
    if not ollama_activo:
        st.error("🔴 Servicio de Ollama desconectado. Inicie Ollama para realizar el análisis.")

    modelo_llm = st.selectbox(
        "Modelo IA",
        ["llama3.2", "llama3.1", "mistral", "gemma2"],
        index=0,
        disabled=not ollama_activo,
        key=f"sel_ollama_model_{key_prefix}"
    )
    return ollama_activo, modelo_llm


def obtener_ruta_windows_completa(ruta: str) -> str:
    """Convierte cualquier ruta (Docker/Linux/Relativa) a la ruta absoluta de Windows."""
    if not ruta or str(ruta).strip() in ["", "None", "nan"]:
        return ""
    
    ruta_str = str(ruta).strip()
    ruta_normalizada = ruta_str.replace("\\", "/")
    
    if re.match(r"^[a-zA-Z]:", ruta_str) and "data" not in ruta_str.lower():
        return str(Path(ruta_normalizada)).replace("/", "\\")
        
    nombre_subcarpeta = Path(ruta_normalizada).name
    return rf"{BASE_WINDOWS_SECOP}\{nombre_subcarpeta}"


def abrir_carpeta_sistema(ruta: str):
    """Abre la carpeta en el explorador de archivos local."""
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


def componente_copiar_ruta(ruta: str):
    """Componente en HTML/JS para copiar una ruta al portapapeles en 1 clic."""
    ruta_escapada = ruta.replace("\\", "\\\\").replace("'", "\\'")
    
    html_code = f"""
    <div style="margin-bottom: 5px;">
        <button id="btnCopy" onclick="copiarAlPortapapeles()" style="
            width: 100%; padding: 10px 14px; background-color: #0E1117; color: #FAFAFA;
            border: 1px solid #4A4A4A; border-radius: 8px; cursor: pointer;
            font-family: monospace; font-size: 13px; display: flex; align-items: center;
            justify-content: space-between; transition: background-color 0.2s ease;
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


def render_formulario_item_cotizacion(key_prefix: str, iva_global_default: float = 19.0, margen_default_label: str = None):
    """Formulario reutilizable para capturar y calcular el desglose financiero de un ítem."""
    col_desc, col_cant, col_unid = st.columns([4, 1, 1])
    with col_desc:
        desc_item = st.text_input("Descripción del Insumo / Servicio *", key=f"{key_prefix}_desc")
    with col_cant:
        cant_item = st.number_input("Cantidad", min_value=1.0, value=1.0, key=f"{key_prefix}_cant")
    with col_unid:
        unid_item = st.text_input("Unidad", value="UNIDAD", key=f"{key_prefix}_unid")

    col_costo, col_modo_iva, col_tarifa_iva, col_margen = st.columns([2, 2, 1.5, 2.5])
    with col_costo:
        costo_ingresado = st.number_input("Costo Unitario (COP) *", min_value=0.0, step=1000.0, key=f"{key_prefix}_costo")
    with col_modo_iva:
        modo_iva = st.selectbox(
            "Origen del Costo",
            options=["Sin IVA (Antes de IVA)", "Con IVA Incluido", "Exento / Excluido (0%)"],
            index=0,
            key=f"{key_prefix}_modo_iva",
        )
    with col_tarifa_iva:
        iva_disabled = modo_iva == "Exento / Excluido (0%)"
        tarifa_iva = st.number_input(
            "% IVA Ítem",
            min_value=0.0,
            max_value=100.0,
            value=0.0 if iva_disabled else iva_global_default,
            disabled=iva_disabled,
            key=f"{key_prefix}_tarifa_iva",
        )
    with col_margen:
        opciones_keys = list(OPCIONES_MARGEN.keys())
        idx_def = opciones_keys.index(margen_default_label) if margen_default_label in opciones_keys else 4
        margen_item_label = st.selectbox("Margen Aplicado", options=opciones_keys, index=idx_def, key=f"{key_prefix}_margen_sel")

    enlace_item = st.text_input("Enlace / Proveedor (Opcional)", key=f"{key_prefix}_link", placeholder="https://...")

    margen_decimal = OPCIONES_MARGEN[margen_item_label]
    costo_base, factor_divisor, precio_venta_unitario, subtotal_item = calcular_desglose_item(
        costo_ingresado, modo_iva, tarifa_iva, margen_decimal, cant_item
    )

    item_data = {
        "descripcion": desc_item.strip(),
        "cantidad": cant_item,
        "unidad_medida": unid_item.strip(),
        "costo_unitario": costo_base,
        "margen_porcentaje": margen_decimal * 100.0,
        "precio_venta_unitario": precio_venta_unitario,
        "subtotal_item": subtotal_item,
        "enlace_referencia": enlace_item.strip(),
    }
    return item_data