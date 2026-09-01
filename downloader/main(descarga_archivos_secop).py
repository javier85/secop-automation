import json
import os
import re
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="SECOP II Downloader API", version="0.7.0")

COOKIES_PATH = os.getenv("COOKIES_PATH", "/data/cookies.json")
BASE_DOCS_PATH = os.getenv("BASE_DOCS_PATH", "/data/documentos")

DEFAULT_PUBLIC_BASE_URL = (
    "https://community.secop.gov.co/Public/Tendering/OpportunityDetail/Index"
)
PUBLIC_DOWNLOAD_ENDPOINT = "https://community.secop.gov.co/Public/Tendering/OpportunityDetail/DownloadFile"


class SecopRequest(BaseModel):
  url: str
  cookies_raw: Optional[str] = None


class CookieUpdateRequest(BaseModel):
  cookies_raw: str


def sanitizar_nombre_archivo(nombre: str) -> str:
  nombre_limpio = re.sub(r'[\\/*?:"<>|]', "_", nombre)
  nombre_limpio = re.sub(r"\s+", " ", nombre_limpio).strip()
  return nombre_limpio or "documento_anexo.pdf"


def parsear_cookies_raw(cookie_str: str) -> Dict[str, str]:
  cookies_dict = {}
  for item in cookie_str.split(";"):
    if "=" in item:
      k, v = item.strip().split("=", 1)
      cookies_dict[k.strip()] = v.strip().strip('"')
  return cookies_dict


def obtener_cookies_str(req: SecopRequest) -> str:
  if req.cookies_raw and len(req.cookies_raw.strip()) > 0:
    return req.cookies_raw.strip()

  if os.path.exists(COOKIES_PATH):
    try:
      with open(COOKIES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
        if isinstance(data, dict):
          return "; ".join([f"{k}={v}" for k, v in data.items()])
        elif isinstance(data, str):
          return data
    except Exception as e:
      print(f"Error al leer cookies desde {COOKIES_PATH}: {e}")
  return ""


def obtener_notice_uid(url: str) -> str:
  parsed = urlparse(url)
  params = parse_qs(parsed.query)

  notice_uid = params.get("noticeUID") or params.get("notice")
  if not notice_uid or not notice_uid[0]:
    raise ValueError(
        "No se encontró un código 'noticeUID' o 'notice' válido en la URL."
    )
  return notice_uid[0]


def construir_url_privada(notice_uid: str) -> str:
  return f"https://www.secop.gov.co/CO1BusinessLine/Tendering/ContractNoticeView/Index?notice={notice_uid}"


def extraer_anexos_html(html_content: str, base_page_url: str) -> List[dict]:
  html_low = html_content.lower()

  if (
      "complete la validación para acceder" in html_low
      or "cf-captcha-container" in html_low
      or "attention required! | cloudflare" in html_low
  ):
    raise HTTPException(
        status_code=403,
        detail=(
            "Bloqueo activo de seguridad/WAF detectado. Actualiza las cookies"
            " con la extensión."
        ),
    )

  soup = BeautifulSoup(html_content, "html.parser")
  anexos = []

  enlaces_descarga = []

  # Detección de elementos de tabla/listado
  filas = soup.find_all(
      "tr", id=re.compile(r"DocumentList|Document|Grid", re.IGNORECASE)
  )
  if filas:
    for f in filas:
      a = (
          f.find("a", id=re.compile(r"lnkDownloadLink", re.IGNORECASE))
          or f.find(
              "a", href=re.compile(r"DownloadFile|documentFileId", re.IGNORECASE)
          )
          or f.find(
              "a",
              onclick=re.compile(
                  r"getAction|DownloadFile|documentFileId", re.IGNORECASE
              ),
          )
      )
      if a:
        enlaces_descarga.append((f, a))

  if not enlaces_descarga:
    todos_links = soup.find_all(
        "a", id=re.compile(r"lnkDownloadLink", re.IGNORECASE)
    )
    if not todos_links:
      todos_links = soup.find_all(
          "a", onclick=re.compile(r"getAction|documentFileId", re.IGNORECASE)
      )
    if not todos_links:
      todos_links = soup.find_all(
          "a", href=re.compile(r"DownloadFile|documentFileId", re.IGNORECASE)
      )

    for a in todos_links:
      padre_tr = a.find_parent("tr")
      enlaces_descarga.append((padre_tr, a))

  elementos_procesados = set()

  for fila, a_link in enlaces_descarga:
    try:
      link_id = a_link.get("id", "")
      if link_id and link_id in elementos_procesados:
        continue
      if link_id:
        elementos_procesados.add(link_id)

      nombre_original = "Sin_nombre.pdf"
      if fila:
        span_nombre = fila.find(
            "span", id=re.compile(r"spnDocumentName", re.IGNORECASE)
        )
        if span_nombre:
          nombre_original = span_nombre.get_text(strip=True)
        else:
          tds = fila.find_all("td")
          for td in tds:
            txt = td.get_text(strip=True)
            if txt and len(txt) > 3 and not txt.lower().startswith("descargar"):
              nombre_original = txt
              break

      if nombre_original == "Sin_nombre.pdf" and a_link.get_text(strip=True):
        txt_a = a_link.get_text(strip=True)
        if txt_a.lower() not in ["descargar", "download", "ver"]:
          nombre_original = txt_a

      nombre_seguro = sanitizar_nombre_archivo(nombre_original)

      onclick_val = a_link.get("onclick", "")
      href_val = a_link.get("href", "")
      target_text = f"{onclick_val} {href_val}".strip()

      url_descarga_directa = None

      # 1. Extraer identificadores explícitos documentFileId y mkey
      doc_id_match = re.search(
          r"documentFileId['\"\s=:\+]+([0-9]+)", target_text, re.IGNORECASE
      )
      mkey_match = re.search(
          r"mkey['\"\s=:\+]+([a-zA-Z0-9_-]+)", target_text, re.IGNORECASE
      )

      if doc_id_match and mkey_match:
        doc_id = doc_id_match.group(1)
        mkey = mkey_match.group(1)
        url_descarga_directa = f"{PUBLIC_DOWNLOAD_ENDPOINT}?documentFileId={doc_id}&mkey={mkey}"

      # 2. Parseo alternativo de getAction en vistas públicas
      if not url_descarga_directa:
        get_action_match = re.search(r"getAction\((.*?)\)", target_text)
        if get_action_match:
          quoted_parts = re.findall(
              r"['\"](.*?)['\"]", get_action_match.group(1)
          )
          if quoted_parts:
            path_reconstruido = "".join(quoted_parts)
            url_descarga_directa = urljoin(
                "https://community.secop.gov.co", path_reconstruido
            )

      # 3. Formato href relativo directo
      if (
          not url_descarga_directa
          and href_val
          and not href_val.startswith("javascript:")
          and href_val != "#"
      ):
        url_descarga_directa = urljoin(base_page_url, href_val)

      if url_descarga_directa:
        anexos.append({
            "nombre_original": nombre_original,
            "nombre": nombre_seguro,
            "element_id": link_id,
            "js_target": target_text,
            "url_descarga_directa": url_descarga_directa,
        })
    except Exception:
      continue

  return anexos


@app.post("/descargar-anexos", summary="Descargar Anexos")
def descargar_anexos(req: SecopRequest):
  try:
    notice_uid = obtener_notice_uid(req.url)
  except Exception as e:
    raise HTTPException(status_code=400, detail=str(e))

  cookie_string = obtener_cookies_str(req)
  cookies_dict = parsear_cookies_raw(cookie_string) if cookie_string else {}

  carpeta_destino = os.path.join(BASE_DOCS_PATH, notice_uid)
  os.makedirs(carpeta_destino, exist_ok=True)

  archivos_guardados = []
  logs = []

  # Forzamos la consulta inicial en la vista pública para obtener URLs de descarga directa (GET)
  url_publica = f"{DEFAULT_PUBLIC_BASE_URL}?noticeUID={notice_uid}"
  logs.append(f"Consultando vista de anexos: {url_publica}")

  try:
    session = requests.Session(
        impersonate="chrome120", cookies=cookies_dict
    )

    headers_base = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            " (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "es-CO,es-ES;q=0.9,es;q=0.8",
        "Referer": url_publica,
        "Sec-Ch-Ua": (
            '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"'
        ),
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Upgrade-Insecure-Requests": "1",
    }

    # 1. Obtener HTML
    resp_page = session.get(url_publica, headers=headers_base, timeout=30)
    anexos = extraer_anexos_html(resp_page.text, base_page_url=url_publica)

    # Fallback si se proporcionaron cookies y la pública está oculta
    if not anexos and cookie_string:
      url_privada = construir_url_privada(notice_uid)
      logs.append(
          f"⚠️ 0 anexos en vista pública. Intentando vista privada:"
          f" {url_privada}"
      )
      resp_privada = session.get(url_privada, headers=headers_base, timeout=30)
      anexos = extraer_anexos_html(
          resp_privada.text, base_page_url=url_privada
      )

    logs.append(f"Anexos detectados: {len(anexos)}")

    # 2. Procesar descargas en segundo plano
    for item in anexos:
      url_download = item.get("url_descarga_directa")
      nombre = item.get("nombre")

      if not url_download:
        logs.append(
            f"⚠️ No se pudo obtener enlace directo para"
            f" '{item.get('nombre_original')}'."
        )
        continue

      try:
        logs.append(f"Descargando {nombre}...")

        headers_download = headers_base.copy()
        headers_download["Accept"] = (
            "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        )

        resp_file = session.get(
            url_download,
            headers=headers_download,
            timeout=120,
            stream=True,
            allow_redirects=True,
        )
        content_type = resp_file.headers.get("Content-Type", "").lower()

        if "text/html" in content_type:
          logs.append(
              f"❌ Error descargando {nombre}: El servidor devolvió HTML (vista"
              " previa o sesión requerida)."
          )
          continue

        if resp_file.status_code == 200:
          path_final = os.path.join(carpeta_destino, nombre)
          bytes_descargados = 0

          with open(path_final, "wb") as f:
            for chunk in resp_file.iter_content(chunk_size=8192):
              if chunk:
                f.write(chunk)
                bytes_descargados += len(chunk)

          if bytes_descargados > 1024:
            archivos_guardados.append(nombre)
            logs.append(
                f"✓ Descargado exitosamente: {nombre}"
                f" ({round(bytes_descargados/1024, 2)} KB)"
            )
          else:
            if os.path.exists(path_final):
              os.remove(path_final)
            logs.append(
                f"⚠️ Archivo omitido {nombre}: Tamaño muy pequeño"
                f" ({bytes_descargados} bytes)."
            )
        else:
          logs.append(
              f"❌ Status {resp_file.status_code} al descargar {nombre}"
          )

      except Exception as err_dl:
        logs.append(f"❌ Error descargando {nombre}: {str(err_dl)}")

  except HTTPException as http_ex:
    raise http_ex
  except Exception as e:
    raise HTTPException(status_code=500, detail=f"Error general: {str(e)}")

  return {
      "status": "success",
      "noticeUID": notice_uid,
      "carpeta": carpeta_destino,
      "total_archivos": len(archivos_guardados),
      "archivos": archivos_guardados,
      "logs": logs,
  }


@app.post("/actualizar-cookies", summary="Guardar Cookie Global")
def actualizar_cookies(req: CookieUpdateRequest):
  try:
    cookies_dict = parsear_cookies_raw(req.cookies_raw)
    if not cookies_dict:
      raise HTTPException(
          status_code=400, detail="Cadena de cookies inválida."
      )

    with open(COOKIES_PATH, "w", encoding="utf-8") as f:
      json.dump(cookies_dict, f, indent=2)

    return {
        "status": "success",
        "message": "Cookie global actualizada correctamente.",
    }
  except Exception as e:
    raise HTTPException(
        status_code=500, detail=f"Error guardando cookies: {str(e)}"
    )