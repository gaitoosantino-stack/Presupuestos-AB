"""
Resolución de logo/firma del perfil para FPDF: ruta local o URL remota (descarga temporal).
"""
import logging
import os
import tempfile
from typing import Optional, Tuple

import requests

logger = logging.getLogger(__name__)


def is_http_url(ref: Optional[str]) -> bool:
    if not ref:
        return False
    s = str(ref).strip()
    return s.startswith("http://") or s.startswith("https://")


def resolve_perfil_image(ref: Optional[str], local_folder: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Devuelve (ruta_absoluta_para_fpdf_o_None, ruta_temporal_a_borrar_o_None).
    Si ref es URL, descarga a un archivo temporal (hay que borrarlo después).
    """
    if not ref or not str(ref).strip():
        return None, None
    ref = str(ref).strip()

    if is_http_url(ref):
        try:
            r = requests.get(
                ref,
                timeout=45,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; PresupuestosLab/1.0)",
                },
            )
            r.raise_for_status()
            suffix = ".png"
            ct = (r.headers.get("Content-Type") or "").lower()
            if "jpeg" in ct or "jpg" in ct or ref.lower().endswith((".jpg", ".jpeg")):
                suffix = ".jpg"
            elif "gif" in ct or ref.lower().endswith(".gif"):
                suffix = ".gif"
            fd, path = tempfile.mkstemp(suffix=suffix)
            try:
                os.write(fd, r.content)
            finally:
                os.close(fd)
            return path, path
        except Exception as e:
            logger.warning("No se pudo descargar imagen de perfil: %s", e)
            return None, None

    local = os.path.join(local_folder, ref)
    if os.path.isfile(local):
        return local, None
    return None, None


def cleanup_temp_paths(paths):
    for p in paths:
        if not p:
            continue
        try:
            if os.path.isfile(p):
                os.unlink(p)
        except OSError:
            pass
