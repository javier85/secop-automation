# services/n8n_service.py
import os
import requests

N8N_WEBHOOK_SECOP_URL = os.getenv(
    "N8N_WEBHOOK_SECOP_URL",
    "http://localhost:5678/webhook/sync-secop",
)
N8N_WEBHOOK_NOTIFICACION_URL = os.getenv(
    "N8N_WEBHOOK_NOTIFICACION_URL",
    "http://localhost:5678/webhook/notificar-cotizacion",
)


def enviar_webhook_n8n(
    url: str, payload: dict, timeout: int = 15
) -> dict:
    """Envía un payload de datos a un webhook de n8n mediante una petición HTTP POST."""
    try:
        response = requests.post(url, json=payload, timeout=timeout)
        response.raise_for_status()

        try:
            contenido = response.json()
        except ValueError:
            contenido = response.text

        return {
            "exito": True,
            "status_code": response.status_code,
            "data": contenido,
        }

    except requests.exceptions.Timeout:
        return {
            "exito": False,
            "error": f"Tiempo de espera agotado ({timeout}s) al contactar el servidor n8n.",
        }
    except requests.exceptions.RequestException as e:
        return {
            "exito": False,
            "error": f"Error de comunicación con n8n: {str(e)}",
        }


def disparar_sincronizacion_secop(filtro_busqueda: str = "") -> dict:
    """Solicita a n8n ejecutar la extracción o raspado automático de licitaciones SECOP."""
    payload = {
        "evento": "sincronizar_secop",
        "filtro": filtro_busqueda,
        "origen": "streamlit_ui",
    }
    return enviar_webhook_n8n(N8N_WEBHOOK_SECOP_URL, payload)


def notificar_cotizacion_creada(
    cotizacion_id: int,
    numero_cotizacion: str,
    total: float,
    estado: str,
    destinatarios: list[str] | None = None,
) -> dict:
    """Envía los datos de una cotización a n8n para activar alertas por email, Teams o Telegram."""
    payload = {
        "evento": "notificar_cotizacion",
        "cotizacion_id": cotizacion_id,
        "numero_cotizacion": numero_cotizacion,
        "total": total,
        "estado": estado,
        "destinatarios": destinatarios or [],
    }
    return enviar_webhook_n8n(N8N_WEBHOOK_NOTIFICACION_URL, payload)