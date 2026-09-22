import json
import os
from pathlib import Path

# Ruta base del proyecto y archivo JSON de configuración
BASE_DIR = Path(__file__).resolve().parent
CONFIG_JSON_PATH = BASE_DIR / "config.json"


def cargar_config_json() -> dict:
    """Carga la configuración desde config.json si está disponible."""
    if CONFIG_JSON_PATH.exists():
        try:
            with open(CONFIG_JSON_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


# Instancia en memoria de la configuración JSON
_json_cfg = cargar_config_json()


def get_config(key: str, default: str = "", section: str = None):
    """Obtiene un parámetro priorizando config.json, luego variables de entorno y finalmente un fallback."""
    if section and section in _json_cfg and key in _json_cfg[section]:
        return _json_cfg[section][key]
    if key in _json_cfg:
        return _json_cfg[key]
    return os.getenv(key, default)


# --- RUTAS DE ALMACENAMIENTO Y DIRECTORIOS ---
BASE_SECOP_DIR = get_config(
    "BASE_SECOP_DIR",
    "/data/secop",
    section="paths",
)

# --- CONFIGURACIÓN GENERAL DE LA APLICACIÓN ---
APP_TITLE = get_config(
    "APP_TITLE", "Sistema de Cotizaciones & SECOP", section="app"
)
APP_ICON = get_config("APP_ICON", "📊", section="app")
APP_LAYOUT = get_config("APP_LAYOUT", "wide", section="app")

# --- CONEXIÓN A BASE DE DATOS (PostgreSQL) ---
DB_HOST = get_config("DB_HOST", "postgres", section="database")
DB_PORT = int(get_config("DB_PORT", "5432", section="database"))
DB_NAME = get_config("DB_NAME", "licitaciones_db", section="database")
DB_USER = get_config("DB_USER", "licita_user", section="database")
DB_PASS = get_config("DB_PASS", "licita_pass", section="database")

DATABASE_URL = get_config(
    "DATABASE_URL",
    f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}",
    section="database",
)

# --- SERVICIO DE IA (OLLAMA) ---
OLLAMA_BASE_URL = get_config(
    "OLLAMA_BASE_URL", "http://ollama:11434", section="ai"
)
DEFAULT_LLM_MODEL = get_config("DEFAULT_LLM_MODEL", "llama3.2", section="ai")
OLLAMA_TIMEOUT = int(get_config("OLLAMA_TIMEOUT", "600", section="ai"))

# --- INTEGRACIONES WEBHOOKS (n8n) ---
N8N_WEBHOOK_SECOP_SYNC = get_config(
    "N8N_WEBHOOK_SECOP_SYNC",
    "http://n8n:5678/webhook/sync-secop",
    section="n8n",
)
N8N_WEBHOOK_COTIZACION_CREADA = get_config(
    "N8N_WEBHOOK_COTIZACION_CREADA",
    "http://n8n:5678/webhook/notificar-cotizacion",
    section="n8n",
)