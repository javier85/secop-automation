# utils/helpers.py
from datetime import datetime
from pathlib import Path
import re
from config import BASE_SECOP_DIR


def calcular_semaforo(fecha_limite) -> str:
    """Calcula dinámicamente el semáforo en tiempo de ejecución (al abrir la app)."""
    if not fecha_limite or str(fecha_limite).strip() in (
        "",
        "None",
        "POR_DEFINIR",
    ):
        return "⚪ Sin fecha"

    # Si la fecha ya viene como datetime desde PostgreSQL
    if isinstance(fecha_limite, datetime):
        dt = fecha_limite
    else:
        txt = str(fecha_limite).strip().upper()
        es_pm = "PM" in txt or "P.M." in txt
        es_am = "AM" in txt or "A.M." in txt

        txt_limpio = re.sub(
            r"\s*(AM|PM|A\.M\.|P\.M\.)", "", txt, flags=re.IGNORECASE
        ).strip()

        dt = None
        formatos = (
            "%d/%m/%Y %H:%M:%S",
            "%d/%m/%Y %H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
        )
        for fmt in formatos:
            try:
                dt = datetime.strptime(txt_limpio, fmt)
                break
            except ValueError:
                continue

        if not dt:
            return "⚪ Formato no válido"

        if es_pm and dt.hour < 12:
            dt = dt.replace(hour=dt.hour + 12)
        elif es_am and dt.hour == 12:
            dt = dt.replace(hour=0)

    # Cálculo en tiempo real relativo a este instante exacto
    ahora = datetime.now()
    diferencia = dt - ahora
    segundos_totales = int(diferencia.total_seconds())

    if segundos_totales < 0:
        segundos_abs = abs(segundos_totales)
        dias = segundos_abs // 86400
        horas = (segundos_abs % 86400) // 3600
        return f"🔴 Vencido ({dias}d {horas}h)"

    dias = segundos_totales // 86400
    horas = (segundos_totales % 86400) // 3600

    if dias == 0:
        return f"🟠 {horas}h restantes"
    elif dias <= 2:
        return f"🟡 {dias}d {horas}h"
    else:
        return f"🟢 {dias}d {horas}h"


def crear_carpeta_licitacion(numero_proceso: str) -> str:
    """Crea la carpeta física de la licitación en la ruta configurada (OneDrive/Local)."""
    num_limpio = re.sub(r'[\\/*?:"<>|]', "_", numero_proceso.strip())
    path_carpeta = Path(BASE_SECOP_DIR) / num_limpio
    try:
        path_carpeta.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"[WARN] Error creando carpeta {path_carpeta}: {e}")
    return str(path_carpeta)