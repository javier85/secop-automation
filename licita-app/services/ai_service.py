import json
import os
import re
from pathlib import Path
import pandas as pd
import requests
from config import (
    BASE_SECOP_DIR,
    DEFAULT_LLM_MODEL,
    OLLAMA_BASE_URL,
    OLLAMA_TIMEOUT,
)
from services.filesystem_service import crear_carpeta_licitacion


def verificar_conexion_ollama() -> bool:
    """Verifica si el servicio de Ollama está activo y respondiendo."""
    try:
        url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/tags"
        res = requests.get(url, timeout=3)
        return res.status_code == 200
    except Exception:
        return False


def consultar_ollama(
    prompt: str, model: str = DEFAULT_LLM_MODEL, system_prompt: str = ""
) -> str:
    """Envía una solicitud de generación de texto a la API de Ollama."""
    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate"
    payload = {
        "model": model,
        "prompt": f"{system_prompt}\n\n{prompt}" if system_prompt else prompt,
        "system": system_prompt,
        "stream": False,
        "options": {"temperature": 0.1},
    }

    try:
        response = requests.post(url, json=payload, timeout=OLLAMA_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        return data.get("response", "").strip()
    except Exception as e:
        raise RuntimeError(f"Error en la comunicación con Ollama: {str(e)}")

def extraer_fecha_presentacion_ofertas(texto_secop: str) -> str:
    """Extrae la fecha límite de presentación de ofertas en español e inglés y elimina marcas de zona horaria."""
    if not texto_secop:
        return ""

    # Usar .*? permite saltar contadores como '1 día para terminar (' hasta llegar a la fecha
    patron = r"(?:Presentación de [Oo]fertas|Submission of [Oo]ffers).*?(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}(?::\d{2})?(?:\s*(?:AM|PM|A\.M\.|P\.M\.))?)"
    match = re.search(patron, texto_secop, re.IGNORECASE | re.DOTALL)

    if match:
        fecha_raw = match.group(1).strip()
    else:
        # Respaldo anclado específicamente a la etiqueta 'Presentación de Ofertas'
        patron_respaldo = r"(?:Presentación de Ofertas|Submission of Offers)[^\n\r]*?(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}(?::\d{2})?)"
        match_seccion = re.search(patron_respaldo, texto_secop, re.IGNORECASE | re.DOTALL)
        fecha_raw = match_seccion.group(1).strip() if match_seccion else ""

    return re.sub(r"\s*\([^)]*\)", "", fecha_raw).strip()

def homologar_item_con_ia(
    descripcion_insumo: str,
    catalogo_historico,
    model: str = DEFAULT_LLM_MODEL,
) -> dict:
    """Compara un insumo nuevo contra el catálogo histórico utilizando Ollama."""
    if isinstance(catalogo_historico, pd.DataFrame):
        catalogo_list = (
            []
            if catalogo_historico.empty
            else catalogo_historico.to_dict(orient="records")
        )
    elif isinstance(catalogo_historico, list):
        catalogo_list = catalogo_historico
    else:
        catalogo_list = []

    if not catalogo_list:
        return {
            "coincidencia_encontrada": False,
            "item_sugerido": None,
            "unidad_medida": "UNIDAD",
            "costo_sugerido": 0.0,
            "confianza": 0,
            "justificacion": "Catálogo histórico vacío.",
        }

    catalogo_resumido = [
        {
            "id": i.get("id") or i.get("ID") or i.get("item_id"),
            "descripcion": i.get("descripcion") or i.get("Descripción"),
            "unidad_medida": i.get("unidad_medida")
            or i.get("Unidad")
            or "UNIDAD",
            "costo_unitario": float(
                i.get("costo_unitario")
                or i.get("Valor Unitario")
                or i.get("precio_unitario")
                or i.get("Costo Unit. (COP)")
                or 0.0
            ),
        }
        for i in catalogo_list[:150]
    ]

    system_prompt = (
        "Eres un experto analista de compras y licitaciones públicas en Colombia. "
        "Tu objetivo es homologar la descripción de un insumo requerido contra una lista "
        "de ítems históricos cotizados previamente. "
        "DEBES RESPONDER EXCLUSIVAMENTE EN FORMATO JSON VÁLIDO sin bloques markdown ```json."
    )

    prompt = f"""
    Requerimiento a homologar: "{descripcion_insumo}"

    Catálogo de Ítems Históricos disponibles:
    {json.dumps(catalogo_resumido, ensure_ascii=False, indent=2)}

    Analiza la similitud técnica y funcional. Devuelve únicamente el siguiente objeto JSON:
    {{
        "coincidencia_encontrada": true/false,
        "id_historico": <int o null>,
        "item_sugerido": "<nombre exacto del ítem del catálogo o null>",
        "unidad_medida": "<unidad de medida sugerida>",
        "costo_sugerido": <float con costo unitario sugerido>,
        "confianza": <entero entre 0 y 100 indicando el nivel de coincidencia>,
        "justificacion": "<breve explicación técnica del matching>"
    }}
    """

    try:
        respuesta_raw = consultar_ollama(
            prompt=prompt, model=model, system_prompt=system_prompt
        )
        clean_json = (
            respuesta_raw.replace("```json", "").replace("```", "").strip()
        )
        clean_json = re.sub(r"^[^{]*", "", clean_json)
        clean_json = re.sub(r"[^}]*$", "", clean_json)
        return json.loads(clean_json)
    except Exception as e:
        return {
            "coincidencia_encontrada": False,
            "item_sugerido": None,
            "unidad_medida": "UNIDAD",
            "costo_sugerido": 0.0,
            "confianza": 0,
            "justificacion": f"Error al procesar/parsear respuesta IA: {str(e)}",
        }


def procesar_homologacion_masiva(
    df_requeridos: pd.DataFrame,
    catalogo_historico,
    model: str = DEFAULT_LLM_MODEL,
) -> pd.DataFrame:
    """Recorre un DataFrame con ítems solicitados e integra los resultados del homologador."""
    df_resultado = df_requeridos.copy()
    items_sugeridos, costos_sugeridos = [], []
    unidades_sugeridas, confianzas, justificaciones = [], [], []

    for _, row in df_resultado.iterrows():
        desc = row.get("descripcion", row.get("Descripción", ""))
        res = homologar_item_con_ia(desc, catalogo_historico, model=model)

        items_sugeridos.append(res.get("item_sugerido", ""))
        costos_sugeridos.append(res.get("costo_sugerido", 0.0))
        unidades_sugeridas.append(res.get("unidad_medida", "UNIDAD"))
        confianzas.append(res.get("confianza", 0))
        justificaciones.append(res.get("justificacion", ""))

    df_resultado["Ítem Sugerido IA"] = items_sugeridos
    df_resultado["Unidad Sugerida"] = unidades_sugeridas
    df_resultado["Costo Sugerido (COP)"] = costos_sugeridos
    df_resultado["Confianza (%)"] = confianzas
    df_resultado["Justificación Match"] = justificaciones

    return df_resultado

def parsear_monto_moneda(monto_str: str) -> float:
    """Convierte cadenas con formato numérico de moneda (latino o anglosajón) a float de forma segura."""
    if not monto_str:
        return 0.0
    val = monto_str.strip().replace("$", "").strip()
    if "." in val and "," in val:
        if val.rfind(",") > val.rfind("."):
            val = val.replace(".", "").replace(",", ".")
        else:
            val = val.replace(",", "")
    elif "," in val and "." not in val:
        partes = val.split(",")
        if len(partes[-1]) == 2:
            val = val.replace(",", ".")
        else:
            val = val.replace(",", "")
    elif "." in val and "," not in val:
        partes = val.split(".")
        if len(partes) > 2 or (len(partes) == 2 and len(partes[-1]) != 2):
            val = val.replace(".", "")
    try:
        return float(val)
    except ValueError:
        return 0.0
    
def extraer_licitacion_con_ollama(
    raw_text: str, model: str = DEFAULT_LLM_MODEL
) -> dict:
    """Extrae datos de SECOP II combinando Ollama con un motor RegEx avanzado (Híbrido y Bilingüe)."""

    # ---------------------------------------------------------
    # 1. EXTRACCIÓN ROBUSTA POR REGEX (MOTOR DE RESPALDO)
    # ---------------------------------------------------------

    # Número de Proceso
    num_match = re.search(
        r"(?:Request Reference|Número del proceso|Número de proceso|Código del proceso|ID del proceso|Referencia)\s*:?\s*([A-Za-z0-9\-_\/\.]+)",
        raw_text,
        re.IGNORECASE,
    )
    num_regex = num_match.group(1).strip() if num_match else ""

    # Entidad Compradora (Descarta nombres de encabezado repetidos)
    entidad_regex = ""
    entidad_match = re.search(
        r"(?:Entidad Compradora|Nombre de la Entidad|Entidad|Procuring Entity|Comprador)\s*:?\s*([^\n\r]+)",
        raw_text,
        re.IGNORECASE,
    )
    if (
        entidad_match
        and entidad_match.group(1).strip().upper()
        not in ["SUMMARY INFORMATION", "CONTRACT NOTICE DETAIL"]
    ):
        entidad_regex = entidad_match.group(1).strip()

    if not entidad_regex:
        m_sum = re.search(
            r"(?:Summary Information|Información del procedimiento)\s*\n+(.+)",
            raw_text,
            re.IGNORECASE,
        )
        if m_sum:
            lineas = [
                l.strip() for l in m_sum.group(1).splitlines() if l.strip()
            ]
            for l in lineas:
                l_upper = l.upper()
                if (
                    l_upper
                    not in [
                        "SUMMARY INFORMATION",
                        "CONTRACT NOTICE DETAIL",
                        "INFORMACIÓN DEL PROCEDIMIENTO",
                    ]
                    and not l_upper.startswith("BASE TOTAL PRICE")
                    and not l_upper.startswith("REQUEST REFERENCE")
                ):
                    entidad_regex = l
                    break

    # Presupuesto Estimado
    presupuesto_match = re.search(
        r"(?:Base Total Price|Precio estimado total|Cuantía estimada|Valor estimado|Presupuesto estimado|Precio Estimado)\s*:?\s*\$?[\s]*([\d\.\,]+)",
        raw_text,
        re.IGNORECASE,
    )
    monto_regex = 0.0
    if presupuesto_match:
        monto_regex = parsear_monto_moneda(presupuesto_match.group(1))

    # Objeto del Proceso
    desc_match = re.search(
        r"(?:Description|Descripción|Objeto del proceso|Objeto)\s*:?\s*([^\n\r]+(?:\n(?![A-Z][a-zA-Z\s]+:|\t)[^\n\r]+)*)",
        raw_text,
        re.IGNORECASE,
    )
    titulo_match = re.search(
        r"(?:Título|Title)\s*:?\s*([^\n\r]+)", raw_text, re.IGNORECASE
    )

    if desc_match and len(desc_match.group(1).strip()) > 5:
        objeto_regex = desc_match.group(1).strip()
    elif titulo_match:
        objeto_regex = titulo_match.group(1).strip()
    else:
        objeto_regex = ""

    # Fecha límite de presentación
    plazo_presentacion = extraer_fecha_presentacion_ofertas(raw_text)

    # ---------------------------------------------------------
    # 2. PROCESAMIENTO CON OLLAMA (IA LOCAL)
    # ---------------------------------------------------------
    system_prompt = (
        "Eres un extractor estricto de JSON especializado en contratación pública de Colombia (SECOP II). "
        "El texto recibido puede estar en español o inglés (ej. 'Request Reference', 'Base Total Price', 'Description', 'Summary Information'). "
        "Extrae los campos requeridos y mapea los valores al esquema JSON sin modificar las llaves. "
        "Responde EXCLUSIVAMENTE en formato JSON válido sin bloques markdown ```json."
    )

    prompt = f"""
    Extrae la información del siguiente texto copiado de SECOP II:
    - numero_proceso: Código o referencia del proceso (Ej: MC-PMF-01-2026 o Request Reference)
    - entidad: Nombre de la entidad pública (Ej: MUNICIPIO DE PACORA o Personeria Filadelfia)
    - objeto: Descripción o resumen completo del objeto a contratar (Description / Objeto)
    - presupuesto: Valor numérico del precio estimado o Base Total Price (ejemplo: 13977020)
    - observaciones: Notas adicionales o modalidad del proceso

    Texto SECOP II:
    {raw_text}
    """

    parsed_ollama = {}
    try:
        respuesta_raw = consultar_ollama(prompt, model, system_prompt)
        clean_json = (
            respuesta_raw.replace("```json", "").replace("```", "").strip()
        )
        clean_json = re.sub(r"^[^{]*", "", clean_json)
        clean_json = re.sub(r"[^}]*$", "", clean_json)
        parsed_ollama = json.loads(clean_json)
    except Exception:
        parsed_ollama = {}

    # ---------------------------------------------------------
    # 3. FUSIÓN HÍBRIDA (IA + REGEX FALLBACK)
    # ---------------------------------------------------------
    def validar_campo(val_ia, val_regex, defecto):
        invalidos = [
            "POR_DEFINIR",
            "DESCONOCIDA",
            "SIN_NUMERO",
            "SIN_ENTIDAD",
            "NONE",
            "NULL",
            "SUMMARY INFORMATION",
            "CONTRACT NOTICE DETAIL",
            "INFORMACIÓN DEL PROCEDIMIENTO",
            "",
        ]
        if val_ia and str(val_ia).strip().upper() not in invalidos:
            return str(val_ia).strip()
        if val_regex and str(val_regex).strip().upper() not in invalidos:
            return str(val_regex).strip()
        return defecto

    num_proceso_final = validar_campo(
        parsed_ollama.get("numero_proceso"), num_regex, "POR_DEFINIR"
    )
    entidad_final = validar_campo(
        parsed_ollama.get("entidad"), entidad_regex, "DESCONOCIDA"
    )
    objeto_final = validar_campo(
        parsed_ollama.get("objeto"),
        objeto_regex,
        "Descripción no encontrada",
    )

    # Presupuesto
    presupuesto_ia = parsed_ollama.get("presupuesto")
    try:
        presupuesto_final = parsear_monto_moneda(str(presupuesto_ia))
    except (ValueError, TypeError):
        presupuesto_final = 0.0

    if presupuesto_final <= 0.0 and monto_regex > 0.0:
        presupuesto_final = monto_regex

    # Crear carpeta física de la licitación
    ruta_carpeta_str = crear_carpeta_licitacion(num_proceso_final)

    return {
        "numero_proceso": num_proceso_final,
        "entidad": entidad_final,
        "objeto": objeto_final,
        "presupuesto": presupuesto_final,
        "plazo_presentacion": plazo_presentacion,
        "carpeta": ruta_carpeta_str,
        "observaciones": parsed_ollama.get("observaciones", ""),
    }