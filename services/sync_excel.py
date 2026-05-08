import io
import logging
import os
import re
import urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from extensions import db
from models import ObraSocial, ObraSocialHistorial

logger = logging.getLogger(__name__)


def _normalize_name(value):
    if value is None:
        return None
    value = re.sub(r"\s+", " ", str(value).strip())
    return value or None


def _normalize_price(value):
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    s = str(value).strip().replace("$", "").replace("€", "").replace(" ", "")
    if not s or s.lower() == "nan":
        return None

    # 1.253,28 -> 1253.28
    if "," in s:
        s2 = s.replace(".", "").replace(",", ".")
    else:
        s2 = s
    try:
        n = float(s2)
        # Formato argentino con 2 decimales
        return f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return None


def _price_to_float(value):
    if value is None:
        return None
    s = str(value).strip().replace(" ", "").replace("$", "").replace("€", "")
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None


def _is_real_price(value):
    n = _price_to_float(value)
    return n is not None and n > 0


def _same_price(a, b):
    fa = _price_to_float(a)
    fb = _price_to_float(b)
    if fa is None and fb is None:
        return True
    if fa is None or fb is None:
        return False
    return abs(fa - fb) <= 0.01


def _estado_desde_vigente(value):
    if value is None or pd.isna(value):
        return "vigente"
    s = re.sub(r"\s+", " ", str(value).strip().lower())
    if not s:
        return "vigente"
    if "suspend" in s:
        return "suspendida"
    if "sin convenio" in s or "sinconvenio" in s or "cortada" in s:
        return "sin_convenio"
    return "vigente"


def _candidate_urls_for_excel(url_origen):
    """Genera variantes de URL a probar (OneDrive a veces solo acepta una de ellas)."""
    if not url_origen:
        return []
    raw = url_origen.strip()
    seen = set()
    out = []

    def add(u):
        if not u or u in seen:
            return
        seen.add(u)
        out.append(u)

    add(raw)
    converted = convert_onedrive_url(raw)
    add(converted)
    # Variante download.aspx (OneDrive personal)
    if "onedrive.live.com" in raw and "/download?" in raw:
        add(raw.replace("/download?", "/download.aspx?"))
    if converted and "onedrive.live.com" in converted and "/download?" in converted:
        add(converted.replace("/download?", "/download.aspx?"))
    return out


def _read_excel_dataframe(url_origen):
    """
    Lee el Excel desde URL. OneDrive suele devolver 401 a urllib/pandas directo;
    por eso priorizamos requests con User-Agent de navegador y varias URLs.
    """
    if not url_origen or not str(url_origen).strip():
        raise ValueError("URL vacía")

    raw = str(url_origen).strip()
    is_onedrive = "onedrive.live.com" in raw or "1drv.ms" in raw or ":x:/g/personal/" in raw
    is_google = "docs.google.com/spreadsheets" in raw

    candidates = _candidate_urls_for_excel(raw)
    errors = []

    # 1) OneDrive / enlaces problemáticos: primero bytes por requests (más parecido a un navegador)
    if is_onedrive or is_google:
        for url in candidates:
            content = download_file_with_requests(url)
            if not content:
                continue
            try:
                return pd.read_excel(io.BytesIO(content), engine="openpyxl", header=None)
            except Exception as e:
                errors.append(f"{url[:60]}… (bytes): {e}")

    # 2) Pandas leyendo URL (a veces funciona con Google export)
    for url in candidates:
        try:
            return pd.read_excel(url, engine="openpyxl", header=None)
        except Exception as e:
            errors.append(f"{url[:60]}… (pandas): {e}")

    # 3) Último intento: requests sobre cada candidato si el paso 1 no corrió
    if not is_onedrive and not is_google:
        for url in candidates:
            content = download_file_with_requests(url)
            if content:
                try:
                    return pd.read_excel(io.BytesIO(content), engine="openpyxl", header=None)
                except Exception as e:
                    errors.append(f"{url[:60]}… (bytes): {e}")

    detail = errors[-1] if errors else "sin detalle"
    raise RuntimeError(f"No se pudo leer el archivo. Último intento: {detail}")


def _db_estado_map():
    obras = ObraSocial.query.all()
    out = {}
    for o in obras:
        n = _normalize_name(o.nombre)
        if n:
            out[n] = {
                "precio": o.precio,
                "estado": o.estado or "vigente",
                "ultima_actualizacion": o.ultima_actualizacion,
            }
    return out


def convert_onedrive_url(url):
    """
    Convierte enlaces de vista/edición de OneDrive a algo descargable cuando es posible.
    Los enlaces :x:/g/personal/ a menudo funcionan mejor con ?download=1 o sin convertir.
    """
    if not url:
        return url

    if "docs.google.com/spreadsheets" in url:
        if "/export?" in url:
            return url
        m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
        if m:
            sid = m.group(1)
            return f"https://docs.google.com/spreadsheets/d/{sid}/export?format=xlsx&id={sid}"
        return url

    if "onedrive.live.com" in url or "1drv.ms" in url:
        if "/download?" in url and "resid=" in url:
            return url
        if "/download.aspx?" in url and "resid=" in url:
            return url

        if ":x:/g/personal/" in url:
            if "download=1" not in url:
                sep = "&" if "?" in url else "?"
                return f"{url}{sep}download=1"
            return url

        m = re.search(r"resid=([^&]+)", url)
        if m:
            resid = urllib.parse.unquote(m.group(1)).strip()
            return f"https://onedrive.live.com/download?resid={resid}"

        if "1drv.ms" in url:
            logger.warning("URL corta 1drv.ms: puede requerir expansión manual. %s", url[:80])
        return url

    return url


def download_file_with_requests(url):
    """
    Descarga binarios; OneDrive rechaza muchas peticiones sin User-Agent de navegador real.
    """
    try:
        import requests
    except Exception:
        logger.warning("Instalá requests (pip install requests)")
        return None

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,"
            "application/vnd.ms-excel,application/octet-stream,*/*"
        ),
        "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
    }

    def _get(u):
        return requests.get(u, headers=headers, timeout=45, allow_redirects=True)

    try:
        # Enlaces personales: probar primero con download=1 explícito
        if ":x:/g/personal/" in url and "download=1" not in url:
            sep = "&" if "?" in url else "?"
            u2 = f"{url}{sep}download=1"
            try:
                r = _get(u2)
                r.raise_for_status()
                if len(r.content) > 500:
                    return r.content
            except Exception as e:
                logger.info("Intento download=1 falló, sigo con URL original: %s", e)

        r = _get(url)
        r.raise_for_status()
        ct = (r.headers.get("Content-Type") or "").lower()
        # Página HTML de login suele ser pequeña o text/html
        if "text/html" in ct and len(r.content) < 5000:
            logger.warning(
                "Respuesta parece HTML (¿login?). content-type=%s len=%s",
                ct,
                len(r.content),
            )
            return None
        if len(r.content) > 100:
            return r.content
        return None
    except Exception as e:
        logger.warning("download_file_with_requests: %s", e)
        return None


def preview_precios_google_sheet():
    url = os.environ.get("GOOGLE_SHEET_URL", "").strip()
    if not url:
        return False, "URL del archivo no configurada.", {}, 0

    try:
        df = _read_excel_dataframe(url)
    except Exception as e:
        return False, f"Error al obtener preview: {e}", {}, 0

    actuales = _db_estado_map()
    propuestos = {}

    # Bloque 1: B(nombre) D(vigente) F(precio)
    # Bloque 2: K(nombre) M(vigente) O(precio)
    blocks = [(1, 3, 5), (10, 12, 14)]
    for col_name, col_estado, col_precio in blocks:
        for idx in range(2, len(df)):
            nombre = df.iloc[idx, col_name] if len(df.columns) > col_name else None
            if pd.isna(nombre):
                continue
            nombre = _normalize_name(nombre)
            if not nombre or nombre.lower() in {"obras sociales", "obra social", "nombre"}:
                continue
            vigente = df.iloc[idx, col_estado] if len(df.columns) > col_estado else None
            precio = df.iloc[idx, col_precio] if len(df.columns) > col_precio else None
            propuestos[nombre] = {
                "estado": _estado_desde_vigente(vigente),
                "precio": _normalize_price(precio),
            }

    cambios = {}
    for nombre, nuevo in propuestos.items():
        actual = actuales.get(nombre, {"precio": None, "estado": "vigente"})
        estado_change = (actual.get("estado") or "vigente") != (nuevo["estado"] or "vigente")
        precio_change = not _same_price(actual.get("precio"), nuevo.get("precio"))
        if estado_change or precio_change:
            cambios[nombre] = {
                "precio_actual": actual.get("precio"),
                "precio_nuevo": nuevo.get("precio"),
                "cambio": "modificado" if nombre in actuales else "nuevo",
                "estado": nuevo.get("estado"),
            }

    cambios = dict(sorted(cambios.items(), key=lambda kv: kv[0]))
    if not cambios:
        return True, f"No hay cambios. Todas las obras ({len(actuales)}) ya tienen los precios actualizados.", {}, 0
    return True, f"Se encontraron {len(cambios)} cambio(s).", cambios, len(cambios)


def sync_precios_google_sheet():
    url = os.environ.get("GOOGLE_SHEET_URL", "").strip()
    if not url:
        return False, "URL del archivo no configurada. Configura GOOGLE_SHEET_URL.", 0

    ok, msg, cambios, _ = preview_precios_google_sheet()
    if not ok:
        return False, msg, 0
    if not cambios:
        return True, "No hay cambios para aplicar.", 0

    ahora = datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).replace(tzinfo=None)
    applied = 0
    try:
        for nombre, cambio in cambios.items():
            obra = ObraSocial.query.filter_by(nombre=nombre).first()
            if not obra:
                obra = ObraSocial(nombre=nombre)
                db.session.add(obra)

            precio_anterior = obra.precio
            estado_anterior = obra.estado
            precio_nuevo = cambio.get("precio_nuevo")
            estado_nuevo = cambio.get("estado") or "vigente"

            obra.precio = precio_nuevo
            obra.estado = estado_nuevo
            obra.ultima_actualizacion = ahora.isoformat()

            if (not _same_price(precio_anterior, precio_nuevo)) or ((estado_anterior or "vigente") != estado_nuevo):
                db.session.add(
                    ObraSocialHistorial(
                        obra_nombre=nombre,
                        fecha=ahora,
                        precio_anterior=precio_anterior,
                        precio_nuevo=precio_nuevo,
                        estado_anterior=estado_anterior,
                        estado_nuevo=estado_nuevo,
                    )
                )
            applied += 1

        db.session.commit()
        return True, f"Sincronizacion exitosa: {applied} obra(s) actualizada(s).", applied
    except Exception as e:
        db.session.rollback()
        logger.exception("Error al sincronizar precios")
        return False, f"Error al guardar en base de datos: {e}", 0
