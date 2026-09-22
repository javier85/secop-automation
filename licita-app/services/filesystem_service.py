# services/filesystem_service.py
import re
import pdfplumber
import requests
from pathlib import Path
from config import BASE_SECOP_DIR

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

import pypdf



def crear_carpeta_licitacion(numero_proceso: str) -> str:
    """Crea la estructura física de carpetas dentro del directorio de OneDrive/Local."""
    num_limpio = re.sub(r'[\\/*?:"<>|]', '_', numero_proceso).strip()
    ruta_proceso = Path(BASE_SECOP_DIR) / num_limpio

    subcarpetas = [
        "01_Pliegos_y_Anexos",
        "02_Documentos_Juridicos_Financieros",
        "03_Propuesta_Tecnica",
        "04_Propuesta_Economica",
    ]

    for sub in subcarpetas:
        (ruta_proceso / sub).mkdir(parents=True, exist_ok=True)

    return str(ruta_proceso)

def consolidar_documentos_licitacion(ruta_carpeta: str) -> str:
    """Recorre la carpeta local del proceso y sus subcarpetas, extrae el texto

    manteniendo la estructura lógica, números de página y contexto de origen.
    """
    carpeta = Path(ruta_carpeta)

    if not carpeta.exists():
        raise FileNotFoundError(
            f"La ruta de la carpeta principal no existe: {ruta_carpeta}"
        )

    texto_consolidado = []

    # Filtrar descartando el archivo de salida previo para evitar bucles de relectura
    archivos_pdf = [
        f for f in carpeta.rglob("*.pdf") if f.name != "resumen_para_ia.txt"
    ]

    if not archivos_pdf:
        raise ValueError(
            "No se encontraron archivos PDF ni en la raíz ni en las"
            f" subcarpetas de: {ruta_carpeta}"
        )

    for archivo_pdf in archivos_pdf:
        nombre_relativo = archivo_pdf.relative_to(carpeta)
        categoria = (
            nombre_relativo.parts[0]
            if len(nombre_relativo.parts) > 1
            else "RAIZ"
        )

        texto_consolidado.append("\n" + "=" * 80)
        texto_consolidado.append(f"DOCUMENTO: {nombre_relativo}")
        texto_consolidado.append(f"CATEGORÍA / SUBCARPETA: {categoria}")
        texto_consolidado.append("=" * 80 + "\n")

        try:
            # 1. Intento preferente con pdfplumber (mantiene mejor tablas y alineación)
            if pdfplumber:
                with pdfplumber.open(archivo_pdf) as pdf:
                    for i, page in enumerate(pdf.pages):
                        texto_pag = page.extract_text(
                            layout=True,
                            use_text_flow=True,
                        )
                        if texto_pag and texto_pag.strip():
                            texto_limpio = limpiar_texto_con_contexto(
                                texto_pag
                            )
                            texto_consolidado.append(
                                f"--- [PÁGINA {i+1} DE {len(pdf.pages)}] ---"
                            )
                            texto_consolidado.append(texto_limpio + "\n")
            else:
                # 2. Respaldo con pypdf si pdfplumber no está instalado
                reader = pypdf.PdfReader(archivo_pdf)
                for i, page in enumerate(reader.pages):
                    texto_pag = page.extract_text()
                    if texto_pag and texto_pag.strip():
                        texto_limpio = limpiar_texto_con_contexto(texto_pag)
                        texto_consolidado.append(
                            f"--- [PÁGINA {i+1} DE {len(reader.pages)}] ---"
                        )
                        texto_consolidado.append(texto_limpio + "\n")

        except Exception as e:
            texto_consolidado.append(
                f"[Error al extraer contenido de {archivo_pdf.name}: {str(e)}]"
            )

    resultado_final = "\n".join(texto_consolidado)

    # Guardar archivo consolidado con codificación explícita
    path_salida = carpeta / "resumen_para_ia.txt"
    path_salida.write_text(resultado_final, encoding="utf-8")

    return resultado_final


def limpiar_texto_con_contexto(texto: str) -> str:
    """Limpia caracteres nulos y espacios basura sin destruir saltos de línea de listas y tablas."""
    # Eliminar caracteres nulos/invisibles comunes de extracciones PDF
    texto = texto.replace("\x00", "").replace("\r", "")

    # Normalizar espacios horizontales excesivos (más de 4) preservando tabulaciones razonables
    texto = re.sub(r"[ \t]{4,}", "    ", texto)

    # Evitar acumular más de dos saltos de línea seguidos para no inflar el token count
    texto = re.sub(r"\n{3,}", "\n\n", texto)

    return texto.strip()