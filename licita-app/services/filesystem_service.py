# services/filesystem_service.py
import re
from pathlib import Path
from config import BASE_SECOP_DIR


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