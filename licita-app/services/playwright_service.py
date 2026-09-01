import os
import re
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from config import BASE_SECOP_DIR
from services.ai_service import extraer_licitacion_con_ollama
from services.filesystem_service import crear_carpeta_licitacion
from database.secop_db import guardar_licitacion_secop
from utils.helpers import calcular_semaforo


def procesar_proceso_secop_playwright(
    url_secop: str, 
    model_llm: str = "llama3.2", 
    headless: bool = True,
    timeout_ms: int = 45000
) -> dict:
    """Abre el proceso en SECOP II mediante Playwright, descarga los adjuntos

    detectados dinámicamente y registra la información procesada con Ollama en PostgreSQL.
    """
    resultados = {
        "exito": False,
        "datos": {},
        "adjuntos_descargados": [],
        "error": None
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            accept_downloads=True
        )
        page = context.new_page()

        try:
            # 1. Navegación e inspección del DOM
            page.goto(url_secop, wait_until="networkidle", timeout=timeout_ms)
            page.wait_for_selector("body", timeout=10000)

            # Obtener el HTML completamente renderizado por el motor JS
            full_html = page.content()

            # 2. Extracción inicial con Ollama a partir del contenido obtenido
            datos_extraidos = extraer_licitacion_con_ollama(full_html, model=model_llm) #[cite: 6]
            num_proceso = datos_extraidos.get("numero_proceso", "SIN_NUMERO")

            # 3. Creación física de la estructura de carpetas
            ruta_carpeta = crear_carpeta_licitacion(num_proceso) #[cite: 7]
            destino_adjuntos = Path(ruta_carpeta) / "01_Pliegos_y_Anexos" #[cite: 6, 7]
            destino_adjuntos.mkdir(parents=True, exist_ok=True)

            # 4. Localización y descarga interactiva de enlaces de archivos
            download_links = page.locator("a[onclick*='documentFileId']").all() #[cite: 6, 7]
            archivos_descargados = []

            for idx, link in enumerate(download_links):
                try:
                    nombre_elem = page.locator(f"span[id*='spnDocumentName']").nth(idx) #[cite: 6, 7]
                    nombre_archivo = nombre_elem.text_content().strip() if nombre_elem.count() > 0 else f"adjunto_{idx + 1}.pdf"
                    nombre_limpio = re.sub(r'[\\/*?:"<>|]', '_', nombre_archivo)
                    
                    # Manejo del evento de descarga de Playwright
                    with page.expect_download(timeout=15000) as download_info:
                        link.click()
                    
                    download = download_info.value
                    path_guardado = destino_adjuntos / nombre_limpio
                    download.save_as(path_guardado)
                    archivos_descargados.append(nombre_limpio)
                except Exception as e_descarga:
                    print(f"[WARN] No se pudo descargar el adjunto {idx + 1}: {e_descarga}")

            # 5. Guardado en la base de datos PostgreSQL
            presupuesto_val = float(datos_extraidos.get("presupuesto") or 0.0) #[cite: 6, 9]
            plazo_val = datos_extraidos.get("plazo_presentacion", "") #[cite: 6, 9]

            guardar_licitacion_secop( #[cite: 8, 9]
                numero_proceso=num_proceso,
                entidad=datos_extraidos.get("entidad", "DESCONOCIDA"), #[cite: 6, 9]
                objeto=datos_extraidos.get("objeto", ""), #[cite: 6, 9]
                presupuesto=presupuesto_val,
                plazo_presentacion=plazo_val,
                estado="EN EVALUACIÓN", #[cite: 8, 9]
                carpeta=ruta_carpeta, #[cite: 6, 9]
                enlace_secop=url_secop,
                observaciones=datos_extraidos.get("observaciones", "Extracción automatizada con Playwright") #[cite: 6, 9]
            )

            resultados["exito"] = True
            resultados["datos"] = datos_extraidos
            resultados["adjuntos_descargados"] = archivos_descargados

        except PlaywrightTimeoutError:
            resultados["error"] = "Tiempo de espera agotado al cargar la página de SECOP II."
        except Exception as e:
            resultados["error"] = f"Error durante la automatización: {str(e)}"
        finally:
            browser.close()

    return resultados