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


def _load_df(url_origen):
    url = convert_onedrive_url(url_origen)
    try:
        return pd.read_excel(url, engine="openpyxl", header=None)
    except Exception:
        content = download_file_with_requests(url)
        if content:
            return pd.read_excel(io.BytesIO(content), engine="openpyxl", header=None)
        raise


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
        if ":x:/g/personal/" in url and "download=1" not in url:
            sep = "&" if "?" in url else "?"
            return f"{url}{sep}download=1"

        m = re.search(r"resid=([^&]+)", url)
        if m:
            resid = urllib.parse.unquote(m.group(1)).strip()
            return f"https://onedrive.live.com/download?resid={resid}"
    return url


def download_file_with_requests(url):
    try:
        import requests
    except Exception:
        return None
    try:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel,*/*",
        }
        res = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
        res.raise_for_status()
        if len(res.content) > 100:
            return res.content
        return None
    except Exception as e:
        logger.warning("No se pudo descargar OneDrive por requests: %s", e)
        return None


def preview_precios_google_sheet():
    url = os.environ.get("GOOGLE_SHEET_URL", "").strip()
    if not url:
        return False, "URL del archivo no configurada.", {}, 0

    try:
        df = _load_df(url)
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
