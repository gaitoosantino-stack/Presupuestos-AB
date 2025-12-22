# 📋 Archivos No Utilizados - Referencia

Este documento lista los archivos y directorios que **NO se utilizan** en la aplicación actual.

Estos archivos son restos de versiones anteriores o funcionalidades que ya no están implementadas.

---

## 🗑️ Archivos que NO se usan

### Archivos de Datos No Referenciados

- **`NOMBRES_PARA_CARRUSEL.txt`** - No se referencia en el código
- **`turnos.db`** - Base de datos SQLite no utilizada (el sistema actual usa JSON para usuarios)

### Archivos Estáticos No Utilizados

- **`static/images/logo.png`** - No referenciado en templates
- **`static/images/hero-dark.jpg`** - No referenciado en templates
- **`static/images/obras/*`** - Todo el directorio de imágenes de obras sociales no se usa (32 archivos)
- **`static/js/`** - Directorio vacío, no hay JavaScript externo

### Scripts Obsoletos

Todos los scripts en `scripts/` son para un sistema de turnos que **ya no existe**:

- **`scripts/check_database_size.py`** - Analiza turnos.db (no existe en código actual)
- **`scripts/backup_database.py`** - Backup de turnos.db (no existe en código actual)
- **`scripts/archive_old_files.py`** - Archiva recetas antiguas (no hay sistema de subida de archivos)
- **`scripts/migrate_db.py`** - Migración de turnos.db (no existe en código actual)

### Directorios Potencialmente No Usados

- **`uploads/`** - Directorio para archivos subidos, pero no hay funcionalidad de subida de archivos en el código actual

---

## 📝 Archivos de Documentación Obsoleta

Estos archivos documentan funcionalidades que ya no existen:

- **`REPORTE_PROBLEMAS_ENCONTRADOS.md`** - Menciona sistema de turnos que no existe
- **`REVISION_COMPLETA_2025.md`** - Menciona sistema de turnos, ADMIN_PASSWORD, etc. que no existen
- **`REVISION_Y_MEJORAS.md`** - Menciona funcionalidades obsoletas
- Varios archivos en `docs/` que mencionan sistema de turnos, base de datos, etc.

---

## ✅ Archivos que SÍ se usan

Para referencia, estos son los archivos que **SÍ se utilizan**:

### Código Principal
- ✅ `app.py` - Aplicación Flask
- ✅ `requirements.txt` - Dependencias
- ✅ `runtime.txt` - Versión Python (Render lo detecta automáticamente o usa render.yaml)

### Templates
- ✅ `templates/login.html`
- ✅ `templates/presupuestos.html`
- ✅ `templates/admin_usuarios.html`

### Archivos Estáticos
- ✅ `static/styles.css`
- ✅ `static/images/favicon.ico`
- ✅ `static/images/favicon.png`

### Datos
- ✅ `obras_entero.txt` - Base de datos de obras sociales (usado en app.py línea 187)
- ✅ `CODIGO_ESTUDIO_UB.txt` - Base de datos de estudios (usado en app.py línea 206)
- ✅ `usuarios_habilitados.json` - Usuarios del sistema (se crea automáticamente)

### Documentación Actual
- ✅ `GUIA_USUARIOS.md` - Documentación actual del sistema de usuarios
- ✅ `docs/GUIA_DEPLOYMENT_RENDER.md` - Guía de deployment actualizada
- ✅ `README.md` - Documentación principal actualizada

---

## 💡 Recomendación

Si querés limpiar el proyecto, podés eliminar:

1. **Archivos de datos no usados**: `NOMBRES_PARA_CARRUSEL.txt`, `turnos.db`
2. **Imágenes no usadas**: Todo el contenido de `static/images/obras/`, `logo.png`, `hero-dark.jpg`
3. **Scripts obsoletos**: Todo el directorio `scripts/`
4. **Documentación obsoleta**: Los archivos de revisión que mencionan funcionalidades que no existen

**⚠️ Importante:** Antes de eliminar, asegurate de que no los necesitás para otra versión del proyecto o para referencia histórica.

---

**Última actualización:** 2025-01-27

