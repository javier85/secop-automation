import os
import platform
import re
import subprocess
import pandas as pd
import streamlit as st
import pypdf
import psycopg2

from pathlib import Path
from sqlalchemy import text
from datetime import datetime
from config import BASE_SECOP_DIR
from database.connection import get_engine

def normalizar_y_calcular_semaforo(fecha_limite_str: str):
    """1. Convierte fechas con AM/PM o de 12 horas a formato limpio 24 Horas (DD/MM/YYYY HH:MM:SS).
    2. Calcula el estado del semáforo antes de guardar en la base de datos.
    Devuelve (plazo_24h, semaforo_calculado).
    """
    if not fecha_limite_str or not isinstance(fecha_limite_str, str):
        return str(fecha_limite_str or ""), "Sin fecha"

    txt = fecha_limite_str.strip().upper()

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
        "%d/%m/%Y",
        "%Y-%m-%d",
    )

    for fmt in formatos:
        try:
            dt = datetime.strptime(txt_limpio, fmt)
            break
        except ValueError:
            continue

    if not dt:
        return fecha_limite_str, fecha_limite_str

    if es_pm and dt.hour < 12:
        dt = dt.replace(hour=dt.hour + 12)
    elif es_am and dt.hour == 12:
        dt = dt.replace(hour=0)

    plazo_24h = dt.strftime("%d/%m/%Y %H:%M:%S")

    ahora = datetime.now()
    diferencia = dt - ahora
    segundos_totales = abs(int(diferencia.total_seconds()))

    dias = segundos_totales // 86400
    horas = (segundos_totales % 86400) // 3600

    if diferencia.total_seconds() < 0:
        semaforo = f"Vencido ({dias} días {horas} h)"
    else:
        semaforo = f"{dias} días {horas} h"

    return plazo_24h, semaforo


def calcular_semaforo(fecha_limite) -> str:
    """Calcula el estado del semáforo replicando la fórmula de Excel.
    Soporta formatos de 12 horas (AM/PM) y 24 horas.
    """
    if not fecha_limite:
        return "Sin fecha"

    if isinstance(fecha_limite, str):
        fecha_clean = fecha_limite.strip()
        formatos = (
            "%d/%m/%Y %I:%M:%S %p",
            "%d/%m/%Y %I:%M %p",
            "%d/%m/%Y %H:%M:%S",
            "%d/%m/%Y %H:%M",
            "%Y-%m-%d %I:%M:%S %p",
            "%Y-%m-%d %I:%M %p",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%d/%m/%Y",
            "%Y-%m-%d",
        )
        for fmt in formatos:
            try:
                fecha_limite = datetime.strptime(fecha_clean, fmt)
                break
            except ValueError:
                continue

    if not isinstance(fecha_limite, datetime):
        return str(fecha_limite)

    ahora = datetime.now()
    diferencia = fecha_limite - ahora
    segundos_totales = abs(int(diferencia.total_seconds()))

    dias = segundos_totales // 86400
    horas = (segundos_totales % 86400) // 3600

    if diferencia.total_seconds() < 0:
        return f"Vencido ({dias} días {horas} h)"
    else:
        return f"{dias} días {horas} h"


def obtener_datos_ejemplo() -> pd.DataFrame:
    """Devuelve un registro de respaldo en caso de que la tabla esté vacía o falle la conexión."""
    return pd.DataFrame([
        {
            "id": 1,
            "numero_proceso": "PMM-MC-009-2026",
            "entidad": "Personería Municipal de Manizales",
            "objeto": (
                "Prestar el servicio de revisión, mantenimiento y recarga de"
                " extintores..."
            ),
            "presupuesto": 4296365.0,
            "plazo_presentacion": "20/08/2026 18:00:00",
            "semaforo": "Vencido (7 días 0 h)",
            "estado": "PRESENTADA",
            "carpeta": "/data/secop/PMM-MC-009-2026",
            "enlace_secop": "https://community.secop.gov.co/...",
            "observaciones": "Esperando evaluación",
        }
    ])


@st.cache_data(ttl=60)
def cargar_licitaciones() -> pd.DataFrame:
    """Obtiene el listado completo de licitaciones SECOP registradas en la base de datos."""
    query = """
        SELECT id, numero_proceso, entidad, objeto, presupuesto, 
               plazo_presentacion, semaforo, estado, carpeta, enlace_secop, 
               observaciones, dictamen_ia, fecha_auditoria 
        FROM licitaciones_secop 
        ORDER BY id DESC;
    """
    try:
        with get_engine().connect() as conn:
            df = pd.read_sql(text(query), conn)
            return df if not df.empty else obtener_datos_ejemplo()
    except Exception:
        return obtener_datos_ejemplo()


def guardar_licitacion_secop(
    numero_proceso: str,
    entidad: str,
    objeto: str,
    presupuesto: float,
    plazo_presentacion: str,
    estado: str,
    carpeta: str,
    enlace_secop: str,
    observaciones: str,
    id=None,
):
    """Inserta o actualiza una licitación procesando la estructura de archivos y semáforos."""
    lic_id = int(id) if id is not None and not pd.isna(id) else None
    pres_val = (
        float(presupuesto)
        if presupuesto is not None and not pd.isna(presupuesto)
        else 0.0
    )

    entidad_clean = str(entidad)[:250] if entidad else ""
    plazo_24h, semaforo_calculado = normalizar_y_calcular_semaforo(
        plazo_presentacion
    )

    ruta_carpeta_obj = Path(BASE_SECOP_DIR) / str(numero_proceso)
    try:
        ruta_carpeta_obj.mkdir(parents=True, exist_ok=True)
        carpeta_final = str(ruta_carpeta_obj)
    except Exception as e:
        print(f"Error creando directorio físico: {e}")
        carpeta_final = carpeta or str(ruta_carpeta_obj)

    params = {
        "num": str(numero_proceso),
        "ent": entidad_clean,
        "obj": str(objeto or ""),
        "pres": pres_val,
        "plazo": plazo_24h,
        "sem": semaforo_calculado,
        "est": str(estado or ""),
        "car": str(carpeta_final),
        "link": str(enlace_secop or ""),
        "obs": str(observaciones or ""),
    }

    if lic_id is not None:
        query = """
            UPDATE licitaciones_secop 
            SET numero_proceso = :num, 
                entidad = :ent, 
                objeto = :obj, 
                presupuesto = :pres, 
                plazo_presentacion = :plazo, 
                semaforo = :sem, 
                estado = :est, 
                carpeta = :car, 
                enlace_secop = :link, 
                observaciones = :obs
            WHERE id = :id;
        """
        params["id"] = lic_id
    else:
        query = """
            INSERT INTO licitaciones_secop (
                numero_proceso, entidad, objeto, presupuesto, 
                plazo_presentacion, semaforo, estado, carpeta, 
                enlace_secop, observaciones
            )
            VALUES (
                :num, :ent, :obj, :pres, 
                :plazo, :sem, :est, :car, 
                :link, :obs
            )
            ON CONFLICT (numero_proceso) DO UPDATE SET
                entidad = EXCLUDED.entidad,
                objeto = EXCLUDED.objeto,
                presupuesto = EXCLUDED.presupuesto,
                plazo_presentacion = EXCLUDED.plazo_presentacion,
                semaforo = EXCLUDED.semaforo,
                estado = EXCLUDED.estado,
                carpeta = EXCLUDED.carpeta,
                enlace_secop = EXCLUDED.enlace_secop,
                observaciones = EXCLUDED.observaciones;
        """

    with get_engine().begin() as conn:
        conn.execute(text(query), params)

    cargar_licitaciones.clear()


def eliminar_licitacion_secop(licitacion_id: int):
    """Elimina permanentemente un proceso SECOP por su ID."""
    with get_engine().begin() as conn:
        conn.execute(
            text("DELETE FROM licitaciones_secop WHERE id = :id;"),
            {"id": licitacion_id},
        )
    cargar_licitaciones.clear()


# Alias de compatibilidad
obtener_licitaciones = cargar_licitaciones


def registrar_auditoria_ia(numero_proceso: str, dictamen_completo: str = "", **kwargs):
    """Guarda el dictamen completo de Ollama y actualiza el estado en PostgreSQL."""
    # Resuelve el contenido sin importar si usas dictamen_completo, resumen_dictamen o dictamen_ia
    informe_final = (
        dictamen_completo
        or kwargs.get("resumen_dictamen")
        or kwargs.get("dictamen_ia")
        or ""
    )

    query = """
        UPDATE licitaciones_secop 
        SET estado = 'AUDITADO POR IA',
            dictamen_ia = :dictamen,
            fecha_auditoria = CURRENT_TIMESTAMP
        WHERE numero_proceso = :num;
    """
    with get_engine().begin() as conn:
        conn.execute(
            text(query), 
            {
                "dictamen": informe_final, 
                "num": numero_proceso
            }
        )
    cargar_licitaciones.clear()  # Invalida la caché de Streamlit