"""
Subida de archivos a Supabase Storage (bucket público).
Requiere en el entorno:
  SUPABASE_URL=https://<ref>.supabase.co
  SUPABASE_SERVICE_ROLE_KEY=<service_role>  (solo servidor, nunca en el front)
  SUPABASE_STORAGE_BUCKET=laboratorio-assets  (opcional; default laboratorio-assets)

En Supabase: crear el bucket (público para lectura) y políticas de lectura pública si aplica.
"""
import logging
import os
import re
from typing import Optional, Tuple

import requests

logger = logging.getLogger(__name__)


def supabase_storage_configured():
    base = (os.environ.get("SUPABASE_URL") or "").strip()
    key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    return bool(base and key)


def _base_url():
    return (os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")


def _service_key():
    return (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()


def _bucket():
    return (os.environ.get("SUPABASE_STORAGE_BUCKET") or "laboratorio-assets").strip()


def public_url_for_object(object_path: str) -> str:
    """URL pública de un objeto en bucket público."""
    base = _base_url()
    bucket = _bucket()
    path = object_path.lstrip("/")
    return f"{base}/storage/v1/object/public/{bucket}/{path}"


def sanitize_storage_username(username: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", (username or "user").strip()) or "user"


def content_type_for_extension(ext: str) -> str:
    ext = (ext or "").lower().lstrip(".")
    if ext in ("jpg", "jpeg"):
        return "image/jpeg"
    if ext == "gif":
        return "image/gif"
    return "image/png"


def upload_profile_image(
    file_bytes: bytes,
    *,
    username: str,
    kind: str,
    extension: str,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Sube logo o firma. kind: 'logo' | 'firma'
    Devuelve (public_url, error_message).
    """
    if not supabase_storage_configured():
        return None, "Storage no configurado (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY)"

    if kind not in ("logo", "firma"):
        return None, "Tipo de archivo inválido"

    ext = (extension or "png").lower().lstrip(".")
    if ext not in ("png", "jpg", "jpeg", "gif"):
        return None, "Extensión no permitida"

    safe_user = sanitize_storage_username(username)
    object_path = f"perfiles/{safe_user}/{kind}.{ext}"

    base = _base_url()
    key = _service_key()
    bucket = _bucket()
    url = f"{base}/storage/v1/object/{bucket}/{object_path}"

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": content_type_for_extension(ext),
        "x-upsert": "true",
    }

    try:
        r = requests.post(url, data=file_bytes, headers=headers, timeout=60)
        if r.status_code not in (200, 201):
            logger.error(
                "Supabase Storage upload %s: %s %s",
                r.status_code,
                r.text[:500],
                object_path,
            )
            return None, f"Error al subir al bucket ({r.status_code})"
        return public_url_for_object(object_path), None
    except Exception as e:
        logger.exception("Fallo upload Supabase Storage")
        return None, str(e)


_IMAGE_EXTS = ("png", "jpg", "jpeg", "gif")


def public_bucket_object_path_from_url(url: str) -> Optional[str]:
    """
    Si la URL es la pública de un objeto en nuestro bucket, devuelve la ruta del objeto
    (p.ej. perfiles/usuario/logo.png). Si no coincide, None.
    """
    if not url or not str(url).strip():
        return None
    s = str(url).strip()
    base = _base_url()
    bucket = _bucket()
    if not base:
        return None
    marker = f"{base}/storage/v1/object/public/{bucket}/"
    if s.startswith(marker):
        return s[len(marker) :].split("?", 1)[0].strip().lstrip("/") or None
    return None


def delete_storage_object(object_path: str) -> None:
    """Elimina un objeto del bucket (ignora 404)."""
    if not supabase_storage_configured() or not object_path:
        return
    base = _base_url()
    key = _service_key()
    bucket = _bucket()
    path = object_path.lstrip("/")
    url = f"{base}/storage/v1/object/{bucket}/{path}"
    headers = {"Authorization": f"Bearer {key}"}
    try:
        r = requests.delete(url, headers=headers, timeout=45)
        if r.status_code in (200, 204):
            logger.info("Storage eliminado: %s", path)
            return
        if r.status_code == 404:
            return
        logger.warning(
            "Storage DELETE %s → %s %s",
            path,
            r.status_code,
            (r.text or "")[:300],
        )
    except Exception as e:
        logger.warning("Storage DELETE falló %s: %s", path, e)


def delete_profile_bucket_assets(
    username: str,
    *,
    logo_path: str = "",
    firma_path: str = "",
) -> None:
    """
    Borra logo/firma del usuario en Storage: rutas típicas perfiles/<user>/ y
    cualquier URL pública guardada en perfil que apunte a este bucket.
    """
    if not supabase_storage_configured():
        return

    seen = set()
    for ref in (logo_path, firma_path):
        p = public_bucket_object_path_from_url(ref or "")
        if p and p not in seen:
            seen.add(p)
            delete_storage_object(p)

    safe = sanitize_storage_username(username)
    prefix = f"perfiles/{safe}/"
    for kind in ("logo", "firma"):
        for ext in _IMAGE_EXTS:
            delete_storage_object(f"{prefix}{kind}.{ext}")
