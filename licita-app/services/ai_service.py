import io
import json
import os
import re
import pdfplumber
from pathlib import Path
from config import (
    BASE_SECOP_DIR,
    DEFAULT_LLM_MODEL,
    OLLAMA_BASE_URL,
    OLLAMA_TIMEOUT,
)
import json_repair
import pandas as pd
import requests
from services.filesystem_service import (
    consolidar_documentos_licitacion,
    crear_carpeta_licitacion,
)

# Dependencias opcionales para extracción individual de archivos
try:
    import pypdf
except ImportError:
    pypdf = None

try:
    import docx
except ImportError:
    docx = None

def verificar_conexion_ollama() -> bool:
    """Verifica si el servicio de Ollama está activo y respondiendo."""
    try:
        url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/tags"
        res = requests.get(url, timeout=3)
        return res.status_code == 200
    except Exception:
        return False

def consultar_ollama(
    prompt: str,
    model: str = DEFAULT_LLM_MODEL,
    system_prompt: str = "",
    temperature: float = 0.0,
) -> str:
    """Envía una solicitud de generación de texto a la API de Ollama con parámetros optimizados."""
    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate"
    payload = {
        "model": model,
        "prompt": f"{system_prompt}\n\n{prompt}" if system_prompt else prompt,
        "system": system_prompt,
        "stream": False,
        "options": {
            "temperature": temperature,  # 0.0 para auditorías deterministas
            "num_predict": 4096,
            "num_ctx": 16384,  # Ventana amplia para procesar pliegos extensos
        },
    }

    try:
        response = requests.post(url, json=payload, timeout=OLLAMA_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        return data.get("response", "").strip()
    except Exception as e:
        raise RuntimeError(f"Error en la comunicación con Ollama: {str(e)}")

def parsear_monto_moneda(monto_str: str) -> float:
    """Convierte cadenas con formato numérico de moneda a float de forma segura."""
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
    
def extraer_fecha_presentacion_ofertas(texto_secop: str) -> str:
    """Extrae la fecha límite de presentación de ofertas en español e inglés."""
    if not texto_secop:
        return ""

    patron = r"(?:Presentación de [Oo]fertas|Submission of [Oo]ffers).*?(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}(?::\d{2})?(?:\s*(?:AM|PM|A\.M\.|P\.M\.))?)"
    match = re.search(patron, texto_secop, re.IGNORECASE | re.DOTALL)

    if match:
        fecha_raw = match.group(1).strip()
    else:
        patron_respaldo = r"(?:Presentación de Ofertas|Submission of Offers)[^\n\r]*?(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}(?::\d{2})?)"
        match_seccion = re.search(
            patron_respaldo, texto_secop, re.IGNORECASE | re.DOTALL
        )
        fecha_raw = match_seccion.group(1).strip() if match_seccion else ""

    return re.sub(r"\s*\([^)]*\)", "", fecha_raw).strip()

def filtrar_texto_inteligente(
    texto_consolidado: str, max_caracteres: int = 45000
) -> str:
    """En lugar de cortar a ciegas los primeros N caracteres, descompone el texto

    en bloques de páginas/secciones y prioriza aquellos que contienen datos contractuales clave.
    """
    if len(texto_consolidado) <= max_caracteres:
        return texto_consolidado

    # Separar por bloques de páginas o documentos
    bloques = re.split(r"(?=--- \[PÁGINA \d+ DE \d+\] ---|==========================================)", texto_consolidado)

    palabras_clave_criticas = [
        "cdp",
        "presupuesto",
        "cuantía",
        "unspsc",
        "experiencia",
        "plazo",
        "ubicación",
        "domicilio",
        "garantía",
        "reteica",
        "requisito",
        "habilitante",
        "consorcio",
        "techo",
        "unitario",
        "porcentaje",
        "impugnac",
        "estudios previos",
    ]

    bloques_prioritarios = []
    bloques_secundarios = []

    # El encabezado principal siempre se preserva
    encabezado = bloques[0] if bloques else ""
    caracteres_acumulados = len(encabezado)

    for bloque in bloques[1:]:
        bloque_lower = bloque.lower()
        if any(kw in bloque_lower for kw in palabras_clave_criticas):
            bloques_prioritarios.append(bloque)
        else:
            bloques_secundarios.append(bloque)

    resultado = [encabezado]

    # 1. Agregar bloques con palabras clave contractuales
    for b in bloques_prioritarios:
        if caracteres_acumulados + len(b) <= max_caracteres:
            resultado.append(b)
            caracteres_acumulados += len(b)

    # 2. Rellenar con bloques secundarios si aún queda espacio en la ventana
    for b in bloques_secundarios:
        if caracteres_acumulados + len(b) <= max_caracteres:
            resultado.append(b)
            caracteres_acumulados += len(b)

    if len(resultado) < len(bloques):
        resultado.append(
            "\n\n[... SECCIONES DE MENOR RELEVANCIA SELECCIONADAS Y OMITIDAS POR PYTHON PARA OPTIMIZAR EL CONTEXTO DE LA IA ...]\n"
        )

    return "".join(resultado)

def extraer_licitacion_con_ollama(
    raw_text: str, model: str = DEFAULT_LLM_MODEL
) -> dict:
    """Extrae datos base de SECOP II combinando RegEx con Ollama."""
    num_match = re.search(
        r"(?:Request Reference|Número del proceso|Número de proceso|Código del proceso|ID del proceso|Referencia)\s*:?\s*([A-Za-z0-9\-_\/\.]+)",
        raw_text,
        re.IGNORECASE,
    )
    num_regex = num_match.group(1).strip() if num_match else ""

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

    presupuesto_match = re.search(
        r"(?:Base Total Price|Precio estimado total|Cuantía estimada|Valor estimado|Presupuesto estimado|Precio Estimado)\s*:?\s*\$?[\s]*([\d\.\,]+)",
        raw_text,
        re.IGNORECASE,
    )
    monto_regex = (
        parsear_monto_moneda(presupuesto_match.group(1))
        if presupuesto_match
        else 0.0
    )

    desc_match = re.search(
        r"(?:Description|Descripción|Objeto del proceso|Objeto)\s*:?\s*([^\n\r]+(?:\n(?![A-Z][a-zA-Z\s]+:|\t)[^\n\r]+)*)",
        raw_text,
        re.IGNORECASE,
    )
    objeto_regex = desc_match.group(1).strip() if desc_match else ""

    plazo_presentacion = extraer_fecha_presentacion_ofertas(raw_text)

    system_prompt = (
        "Eres un extractor estricto de JSON especializado en contratación pública de Colombia (SECOP II). "
        "Responde EXCLUSIVAMENTE en formato JSON válido sin bloques markdown ```json."
    )

    prompt = f"""
    Extrae la información del siguiente texto copiado de SECOP II:
    - numero_proceso: Código o referencia del proceso
    - entidad: Nombre de la entidad pública
    - objeto: Descripción o resumen completo del objeto a contratar
    - presupuesto: Valor numérico del precio estimado
    - observaciones: Notas adicionales o modalidad del proceso

    Texto SECOP II:
    {raw_text}
    """

    parsed_ollama = {}
    try:
        respuesta_raw = consultar_ollama(
            prompt, model, system_prompt, temperature=0.0
        )
        try:
            parsed_ollama = json_repair.loads(respuesta_raw)
        except Exception:
            clean_json = re.sub(r"```json|```", "", respuesta_raw).strip()
            match = re.search(r"\{.*\}", clean_json, re.DOTALL)
            if match:
                parsed_ollama = json.loads(match.group(0))
    except Exception:
        parsed_ollama = {}

    def validar_campo(val_ia, val_regex, defecto):
        invalidos = [
            "POR_DEFINIR",
            "DESCONOCIDA",
            "SIN_NUMERO",
            "SIN_ENTIDAD",
            "NONE",
            "NULL",
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
        parsed_ollama.get("objeto"), objeto_regex, "Descripción no encontrada"
    )

    presupuesto_ia = parsed_ollama.get("presupuesto")
    try:
        presupuesto_final = parsear_monto_moneda(str(presupuesto_ia))
    except Exception:
        presupuesto_final = 0.0

    if presupuesto_final <= 0.0 and monto_regex > 0.0:
        presupuesto_final = monto_regex

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


PROMPT_SISTEMA_GESSTIONANDO = """
[ROL Y PERFIL DEL SISTEMA]
Actúa como Auditor Contractual Senior y Analista de Negocios para GESSTIONANDO CONSULTING S.A.S.
Tu objetivo es entregar un diagnóstico gerencial inmediato (decisión en 30 segundos) respaldado por una auditoría técnica, financiera, tributaria y jurídica profunda de procesos de contratación pública (SECOP I y II).

[REGLAS ESTRICTAS DE LECTURA Y ANTI-EVASIÓN]
1. PROHIBICIÓN ABSOLUTA DE EVASIÓN: Queda estrictamente PROHIBIDO responder "No se indica", "Debido a falta de datos" o "No es posible determinar". Escanea el texto y las etiquetas de página/carpeta suministradas.
2. PRECISIÓN DE ENTIDAD: Si el código o asunto incluye siglas, reporta siempre el nombre completo oficial de la entidad territorial.
3. PROHIBICIÓN DE RESÚMENES PASIVOS: Ve directo a las cifras, techos presupuestales, cantidades y requisitos eliminatorios.
4. EXTRACCIÓN OBLIGATORIA DE PRECIOS TECHO: En procesos de suministro de bienes o ítems cuantificables, extrae el desglose de cantidades y precios unitarios de referencia.

[BASE CORPORATIVA Y CRITERIOS DE VIABILIDAD - GESSTIONANDO CONSULTING S.A.S.]
- Empresa: GESSTIONANDO CONSULTING S.A.S. | NIT: 901483192-6 | Domicilio: Manizales, Caldas.
- Régimen Tributario: Régimen Simple de Tributación (RST) - Código RUT 47.
- EXENCIÓN RETEFUENTE: Exento de Retención en la Fuente a título de Renta (Art. 911 E.T.). NO se le debe aplicar ReteFuente.
- RETENCIONES APLICABLES: ReteICA local (según tarifa del municipio ejecutor) y Estampillas territoriales obligatorias.
- ALERTA DE DOMICILIO: Si el proceso exige domicilio contractual, oficina o bodega en el municipio ejecutor fuera de Manizales, marca inhabilitación individual e indica solución vía Unión Temporal o Impugnación.

[REGLAS DE CLASIFICACIÓN DEL VEREDICTO]
🟢 VIABLE: Cumplimos experiencia, margen adecuado y no hay barreras geográficas ni legales.
🟡 VIABLE CON CONDICIONES: Requiere Consorcio / UT con aliado local, o solicitar aclaraciones/impugnaciones en pliegos.
🔴 NO VIABLE: Inhabilitación insubsanable por domicilio estricto fuera de Manizales, experiencia UNSPSC no acreditable o presupuesto deficitario.

[ESTRUCTURA OBLIGATORIA DEL INFORME EN MARKDOWN]

# 🚦 INFORME DE AUDITORÍA CONTRACTUAL Y DICTAMEN DE VIABILIDAD

## 📢 VEREDICTO GERENCIAL: [ 🟢 VIABLE | 🟡 VIABLE CON CONDICIONES | 🔴 NO VIABLE ]
**Causa Principal:** [Explicación directa en 1 o 2 frases del porqué del veredicto].

---

### 1. ¿DE QUÉ TRATA EL PROCESO? (RESUMEN OPERATIVO Y DATOS DUROS)
* **Objeto Real en Simple:** [Explicación en lenguaje claro de negocios].
* **Entregables Clave:** [Listado puntual de los 3 a 5 productos o servicios principales].
* **Entidad Contratante:** [Nombre completo de la entidad y dependencia].
* **Código del Proceso / Modalidad:** [Código oficial] | [Mínima Cuantía / Selección Abreviada / Licitación Pública / Directa]
* **Presupuesto Oficial Estimado:** $ [Valor exacto en COP]
* **CDP N°:** [Número de CDP, Fecha de Expedición y Valor Registrado]
* **Plazo y Lugar de Ejecución:** [Plazo en días/meses] | [Municipio y Departamento]

### 2. DESGLOSE DE CANTIDADES Y PRECIOS MÁXIMOS DE REFERENCIA (TECHO)
*(Aplica obligatoriamente para suministros de bienes o componentes cuantificables).*

| Ítem / Elemento | Cantidad | Precio Ref. Unitario (IVA incl.) | Subtotal Máximo Estimado |
| :--- | :---: | :---: | :---: |
| [Descripción del ítem 1] | [Cant.] | $ [Valor] | $ [Subtotal] |
| [Descripción del ítem 2] | [Cant.] | $ [Valor] | $ [Subtotal] |

* **Alerta de Techo Presupuestal:** [Aclarar si la entidad rechaza ofertas que superen los precios unitarios de referencia].

### 3. MATRIZ RÁPIDA DE HABILITACIÓN Y TRAZABILIDAD
| Criterio | Requisito del Pliego | Evaluación GESSTIONANDO | ¿Cumple? |
| :--- | :--- | :--- | :--- |
| **Experiencia (UNSPSC)** | [Códigos y % RUP / SMMLV exigido] | [Evaluación rápida de la empresa] | [SI / NO / UT] |
| **Ubicación / Domicilio** | [Exigencia de sede, bodega o personal] | Sede principal en Manizales | [SI / NO / UT] |
| **Plazos y Capacidad** | [Tiempos de ejecución] | [Viabilidad operativa real] | [SI / NO] |

* **Trazabilidad y Planeación (CDP vs Pliegos):** [Evaluación de fechas clave y coherencia temporal].

### 4. AUDITORÍA FINANCIERA Y MATRIZ TRIBUTARIA (RST)
* **Presupuesto Bruto:** $ [Valor]
* **Retención en la Fuente Renta (0% - RST Art. 911 E.T.):** $ 0.00
* **Estimación ReteICA Local:** $ [Monto calculado según tarifa local]
* **Estampillas Territoriales:** $ [Monto calculado según pliego]
* **Total Descuentos Ley / Territorios:** $ [Suma de retenciones]
* **Neto Estimado a Recibir:** $ [Presupuesto - Descuentos]
* **Evaluación del Margen Operativo:** [Análisis de rentabilidad neta].

### 5. HALLAZGOS CRÍTICOS Y RIESGOS CONTRACTUALES
* [Lista con viñetas de errores de la entidad, ambigüedades, pólizas exigidas fuera de norma o cláusulas restrictivas].

### 6. RECOMENDACIÓN ESTRATÉGICA Y PASOS A SEGUIR
* [Indicación concreta para gerencia].
"""

def analizar_licitacion_con_gesstionando(
    texto_consolidado: str,
    datos_extraidos: dict = None,
    numero_proceso: str = "",
    model: str = DEFAULT_LLM_MODEL,
) -> str:
    """Ejecuta la auditoría utilizando filtrado inteligente de contexto y datos pre-extraídos."""
    # 1. Filtrado semántico de páginas y secciones en Python
    texto_filtrado = filtrar_texto_inteligente(
        texto_consolidado, max_caracteres=45000
    )

    # 2. Contexto de respaldo pre-calculado por Python
    contexto_datos = ""
    if datos_extraidos:
        contexto_datos = f"""
<contexto_verificado_python>
- Numero de Proceso: {datos_extraidos.get('numero_proceso', numero_proceso)}
- Entidad: {datos_extraidos.get('entidad', 'Por verificar')}
- Presupuesto Oficial: ${datos_extraidos.get('presupuesto', 0.0):,.2f} COP
- Plazo Presentacion: {datos_extraidos.get('plazo_presentacion', 'Por verificar')}
</contexto_verificado_python>
"""

    prompt_usuario = f"""
{contexto_datos}

<documentos_licitacion_consolidados>
{texto_filtrado}
</documentos_licitacion_consolidados>

Genera el INFORME DE AUDITORÍA CONTRACTUAL Y DICTAMEN DE VIABILIDAD completo para el proceso {numero_proceso or datos_extraidos.get('numero_proceso', '')} cumpliendo la estructura exigida.
"""

    return consultar_ollama(
        prompt=prompt_usuario,
        model=model,
        system_prompt=PROMPT_SISTEMA_GESSTIONANDO,
        temperature=0.0,
    )

def homologar_item_con_ia(
    descripcion_insumo: str,
    catalogo_historico,
    model: str = DEFAULT_LLM_MODEL,
) -> dict:
    """Compara un insumo requerido contra el catálogo histórico utilizando Ollama."""
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

    if not catalogo_list or not descripcion_insumo.strip():
        return {
            "coincidencia_encontrada": False,
            "id_historico": None,
            "item_sugerido": None,
            "unidad_medida": "UNIDAD",
            "costo_sugerido": 0.0,
            "confianza": 0,
            "justificacion": "Catálogo histórico vacío o descripción inválida.",
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
        # Fijar temperatura en 0.0 para comparaciones consistentes y deterministas
        respuesta_raw = consultar_ollama(
            prompt=prompt,
            model=model,
            system_prompt=system_prompt,
            temperature=0.0,
        )
        try:
            return json_repair.loads(respuesta_raw)
        except Exception:
            clean_json = re.sub(r"```json|```", "", respuesta_raw).strip()
            match = re.search(r"\{.*\}", clean_json, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            raise ValueError("No se extrajo un JSON válido")
    except Exception as e:
        return {
            "coincidencia_encontrada": False,
            "id_historico": None,
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
    """Recorre un DataFrame de insumos solicitados e integra las sugerencias del homologador."""
    if df_requeridos.empty:
        return df_requeridos.copy()

    df_resultado = df_requeridos.copy()
    items_sugeridos, costos_sugeridos = [], []
    unidades_sugeridas, confianzas, justificaciones = [], [], []

    for _, row in df_resultado.iterrows():
        desc = str(row.get("descripcion", row.get("Descripción", "")))
        res = homologar_item_con_ia(desc, catalogo_historico, model=model)

        items_sugeridos.append(res.get("item_sugerido"))
        costos_sugeridos.append(float(res.get("costo_sugerido", 0.0)))
        unidades_sugeridas.append(res.get("unidad_medida", "UNIDAD"))
        confianzas.append(int(res.get("confianza", 0)))
        justificaciones.append(res.get("justificacion", ""))

    df_resultado["Ítem Sugerido IA"] = items_sugeridos
    df_resultado["Unidad Sugerida"] = unidades_sugeridas
    df_resultado["Costo Sugerido (COP)"] = costos_sugeridos
    df_resultado["Confianza (%)"] = confianzas
    df_resultado["Justificación Match"] = justificaciones

    return df_resultado

def extraer_texto_de_archivo(file_bytes: bytes, filename: str) -> str:
    """Extrae texto de archivos PDF, Word (.docx), Excel (.xlsx/.xls) y TXT/CSV

    con soporte layout y decodificación segura.
    """
    ext = Path(filename).suffix.lower()
    texto_extraido = f"--- INICIO DOCUMENTO: {filename} ---\n"

    try:
        if ext == ".pdf":
            # 1. Preferir pdfplumber para mantener la disposición visual de tablas
            if pdfplumber is not None:
                with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                    for i, page in enumerate(pdf.pages):
                        txt = (
                            page.extract_text(
                                layout=True, use_text_flow=True
                            )
                            or ""
                        )
                        if txt.strip():
                            texto_extraido += (
                                f"\n[Página {i+1}]\n{txt.strip()}\n"
                            )
            # 2. Respaldo en pypdf si pdfplumber no está presente
            elif pypdf is not None:
                reader = pypdf.PdfReader(io.BytesIO(file_bytes))
                for i, page in enumerate(reader.pages):
                    txt = page.extract_text() or ""
                    if txt.strip():
                        texto_extraido += (
                            f"\n[Página {i+1}]\n{txt.strip()}\n"
                        )
            else:
                texto_extraido += (
                    "[Error: Se requiere pdfplumber o pypdf para leer PDF]\n"
                )

        elif ext == ".docx":
            if docx is None:
                return (
                    texto_extraido
                    + "[Error: Instalar python-docx para leer DOCX]\n"
                )
            doc = docx.Document(io.BytesIO(file_bytes))
            for p in doc.paragraphs:
                if p.text.strip():
                    texto_extraido += p.text.strip() + "\n"
            for table in doc.tables:
                for row in table.rows:
                    celdas = [
                        c.text.strip() for c in row.cells if c.text.strip()
                    ]
                    if celdas:
                        texto_extraido += " | ".join(celdas) + "\n"

        elif ext in [".xlsx", ".xls"]:
            excel_file = pd.ExcelFile(io.BytesIO(file_bytes))
            for sheet in excel_file.sheet_names:
                df = pd.read_excel(excel_file, sheet_name=sheet)
                if not df.empty:
                    texto_extraido += f"\n[Hoja: {sheet}]\n"
                    texto_extraido += df.to_string(index=False) + "\n"

        elif ext in [".txt", ".csv"]:
            try:
                texto_extraido += file_bytes.decode("utf-8")
            except UnicodeDecodeError:
                texto_extraido += file_bytes.decode("latin-1", errors="ignore")

        else:
            texto_extraido += f"[Formato {ext} no soportado para lectura directa]"

    except Exception as e:
        texto_extraido += f"[Error al extraer contenido de {filename}: {str(e)}]"

    texto_extraido += f"\n--- FIN DOCUMENTO: {filename} ---\n\n"
    return texto_extraido
