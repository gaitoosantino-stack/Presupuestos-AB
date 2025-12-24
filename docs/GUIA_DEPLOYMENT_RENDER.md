# 🚀 Guía de Deployment en Render

Esta guía te ayudará a subir tu aplicación de calculadora de presupuestos a Render.

---

## 📋 Pre-requisitos

1. ✅ Cuenta en [Render.com](https://render.com) (es gratis para empezar)
2. ✅ Código en un repositorio Git (GitHub, GitLab o Bitbucket)
3. ✅ Archivos del proyecto listos (ya están ✅)

---

## 🔧 Paso 1: Preparar el Proyecto Localmente

### 1.1 Verificar archivos necesarios

Tu proyecto ya tiene todo lo necesario:
- ✅ `requirements.txt` - Dependencias Python
- ✅ `app.py` - Aplicación Flask
- ✅ `gunicorn` en requirements.txt - Servidor para producción
- ✅ `render.yaml` - Configuración para Render (opcional, facilita el deployment con Blueprint)

**⚠️ IMPORTANTE sobre almacenamiento:**
- Tu aplicación usa archivos JSON (`usuarios_habilitados.json`, `perfiles.json`)
- En Render, estos archivos pueden perderse si el servicio se reinicia
- Considerá migrar a una base de datos (PostgreSQL en Render) para producción con datos críticos

### 1.2 Variables de entorno (opcional)

La aplicación funciona sin variables de entorno (genera una SECRET_KEY automáticamente), pero es recomendable configurar `SECRET_KEY` en Render para que las sesiones persistan entre reinicios.

---

## 🚀 Paso 2: Subir a Render

### 2.1 Crear cuenta en Render

1. Andá a [render.com](https://render.com)
2. Creá una cuenta (podés usar GitHub para login rápido)
3. Confirmá tu email

### 2.2 Crear nuevo Web Service

1. En el dashboard de Render, click en **"New +"**
2. Seleccioná **"Web Service"**
3. Conectá tu repositorio:
   - Si usás GitHub, autorizá Render a acceder
   - Seleccioná tu repositorio
   - Seleccioná la rama (generalmente `main` o `master`)

### 2.3 Configurar el servicio

**Configuración básica:**

| Campo | Valor |
|-------|-------|
| **Name** | `laboratorio-presupuestos` (o el nombre que prefieras) |
| **Region** | `Oregon (US West)` (más cerca de Argentina) |
| **Branch** | `main` (o tu rama principal) |
| **Root Directory** | Dejá vacío (si está en la raíz) |
| **Runtime** | `Python 3` (Render detecta automáticamente la versión) |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `gunicorn app:app` (o `gunicorn --workers 2 --bind 0.0.0.0:$PORT app:app` para mejor rendimiento) |

### 2.4 Variables de Entorno (Opcional pero Recomendado)

En la sección **"Environment Variables"**, agregá:

| Key | Value | Descripción |
|-----|-------|-------------|
| `SECRET_KEY` | `(generá una clave segura)` | **REQUERIDA** - Clave para sesiones y CSRF tokens |
| `PORT` | `(automático)` | Render lo configura automáticamente, no necesitás cambiarlo |
| `FLASK_ENV` | `production` | Opcional - Define el entorno de Flask |

**Para generar SECRET_KEY:**
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

O podés usar cualquier string largo y aleatorio (mínimo 32 caracteres recomendado).

**⚠️ IMPORTANTE:** 
- No compartas nunca tu SECRET_KEY
- Si no configurás SECRET_KEY, la aplicación funcionará pero generará una nueva cada vez que se reinicie (las sesiones no persistirán)
- Guardá tu SECRET_KEY en un lugar seguro (no en el repositorio)

### 2.5 Usar render.yaml (Opción Alternativa - Blueprint)

Si preferís usar el archivo `render.yaml` existente en tu proyecto:

1. En Render, click en **"New +"** → **"Blueprint"**
2. Conectá tu repositorio
3. Render detectará automáticamente el archivo `render.yaml`
4. Configurá la variable `SECRET_KEY` en el dashboard después de crear el servicio
5. Click en **"Apply"**

**Ventajas de usar Blueprint:**
- Toda la configuración está versionada en tu repositorio
- Más fácil de replicar y mantener
- Cambios de configuración más controlados

### 2.6 Plan y Deploy

- **Plan:** Seleccioná **"Free"** (es suficiente para empezar)
- Click en **"Create Web Service"** (o **"Apply"** si usaste Blueprint)

Render va a:
1. Clonar tu repositorio
2. Instalar dependencias (`pip install -r requirements.txt`)
3. Iniciar la aplicación con gunicorn
4. Asignar una URL pública (ej: `https://laboratorio-presupuestos.onrender.com`)

---

## ✅ Paso 3: Verificar el Deployment

### 3.1 Ver logs

En el dashboard de Render, andá a la sección **"Logs"** para ver si hay errores.

**Tip:** Los logs se muestran en tiempo real. Si ves errores:
- Buscá mensajes de error específicos
- Verificá que todas las dependencias se instalaron correctamente
- Revisá que las variables de entorno estén configuradas

### 3.2 Probar la aplicación

1. Render te dará una URL como: `https://tu-app.onrender.com`
2. Probá acceder a la URL
3. Verificá que el login funcione
4. Probá la calculadora de presupuestos

---

## 🔧 Paso 4: Configuración Adicional (Opcional)

### 4.1 Configurar dominio personalizado

Si tenés un dominio:
1. En Render, andá a **"Settings"** → **"Custom Domains"**
2. Agregá tu dominio
3. Configurá los registros DNS según las instrucciones de Render

### 4.2 Auto-deploy

Por defecto, Render hace auto-deploy cuando hacés push a tu rama principal. Podés desactivarlo en **"Settings"** → **"Auto-Deploy"**.

### 4.3 Monitoreo

Render te muestra:
- Logs en tiempo real
- Uso de recursos (CPU, memoria)
- Estado del servicio

---

## ⚠️ Problemas Comunes y Soluciones

### Problema 1: "Application failed to respond"

**Solución:**
- Verificá que el `startCommand` sea `gunicorn app:app`
- Revisá los logs en Render para ver el error específico
- Asegurate de que `gunicorn` esté en `requirements.txt`

### Problema 2: "Module not found"

**Solución:**
- Verificá que todas las dependencias estén en `requirements.txt`
- Revisá que el `buildCommand` se ejecute correctamente

### Problema 3: "SECRET_KEY not set"

**Solución:**
- Asegurate de configurar `SECRET_KEY` en las variables de entorno
- La aplicación funciona sin ella (genera una aleatoria), pero es mejor configurarla

### Problema 4: Sesiones que se pierden

**Solución:**
- Configurá `SECRET_KEY` en Render
- Verificá que esté configurada correctamente
- Asegurate de que el valor de `SECRET_KEY` sea lo suficientemente largo (32+ caracteres)

### Problema 5: Archivos JSON perdidos (usuarios, perfiles)

**Solución:**
- ⚠️ **Importante:** Los archivos JSON (`usuarios_habilitados.json`, `perfiles.json`) en Render pueden perderse en reinicios
- Para datos críticos, considerá migrar a PostgreSQL (Render ofrece bases de datos gratuitas)
- Como solución temporal, hacé backups regulares de estos archivos
- Podés usar el script `scripts/backup_database.py` para crear backups

### Problema 6: La aplicación no responde después de un tiempo

**Solución:**
- Esto es normal en el plan gratuito - el servicio se "duerme" después de 15 minutos de inactividad
- El primer request después de dormir puede tardar 30-50 segundos
- Si necesitás servicio siempre activo, considerá actualizar a un plan de pago

---

## 📊 Plan Free de Render

### Limitaciones del plan gratuito:

- ✅ 750 horas/mes gratis (suficiente para uso personal)
- ⚠️ El servicio se "duerme" después de 15 minutos de inactividad
- ⚠️ El primer request después de dormir puede tardar 30-50 segundos
- ✅ Ideal para desarrollo y proyectos pequeños

### Si necesitás servicio siempre activo:

Podés actualizar a un plan de pago (desde $7/mes aproximadamente).

---

## 🔐 Seguridad en Producción

### Checklist de seguridad:

- ✅ `SECRET_KEY` configurada en variables de entorno (obligatorio en producción)
- ✅ `debug=False` en producción (ya está configurado en el código - se activa solo si `FLASK_ENV=development`)
- ✅ Protección CSRF activada (Flask-WTF)
- ✅ Sesiones seguras con HttpOnly y SameSite
- ✅ Passwords hasheados (Werkzeug)

### Notas sobre archivos estáticos:

- Flask sirve automáticamente los archivos de `static/` (logos, CSS, JS)
- No necesitás configuración adicional en Render
- Los archivos estáticos se sirven desde la ruta `/static/`

---

## 📝 Resumen de Comandos Importantes

```bash
# Generar SECRET_KEY segura
python -c "import secrets; print(secrets.token_hex(32))"

# Probar localmente con gunicorn (como en Render)
gunicorn app:app

# Con configuración para producción (múltiples workers)
gunicorn --workers 2 --bind 0.0.0.0:5000 app:app

# Ver logs locales
# (gunicorn muestra logs en la terminal)
```

### Comandos útiles para Render:

- **Ver logs:** Dashboard → Tu servicio → Sección "Logs"
- **Reiniciar servicio:** Dashboard → Tu servicio → "Manual Deploy" → "Clear build cache & deploy"
- **Ver variables de entorno:** Dashboard → Tu servicio → "Environment"

---

## 🎯 Próximos Pasos

Una vez que esté funcionando en Render:

1. ✅ Probá todas las funcionalidades
2. ✅ Verificá que el login funcione
3. ✅ Probá crear usuarios desde el panel de Gaito
4. ✅ Verificá que la calculadora funcione correctamente
5. ✅ Compartí la URL con quienes necesiten usarla

---

## 📞 Soporte

Si tenés problemas:
1. Revisá los logs en Render (Dashboard → Logs)
2. Verificá que todos los archivos estén en el repositorio
3. Asegurate de que las variables de entorno estén configuradas (especialmente `SECRET_KEY`)
4. Verificá que `requirements.txt` incluya todas las dependencias
5. Revisá la sección "Problemas Comunes y Soluciones" arriba

### Recursos adicionales:

- [Documentación oficial de Render](https://render.com/docs)
- [Guía de Flask en Render](https://render.com/docs/deploy-flask)
- [Documentación de Gunicorn](https://docs.gunicorn.org/)

---

**¡Listo! Tu aplicación debería estar funcionando en Render.** 🎉

---

**Última actualización:** 2025-01-27

---

## 📌 Notas Adicionales

### Versión de Python

Render detecta automáticamente la versión de Python desde `requirements.txt`. Tu proyecto funciona con Python 3.8+.

### Persistencia de Datos

**⚠️ Importante:** Tu aplicación actualmente almacena datos en archivos JSON:
- `usuarios_habilitados.json` - Usuarios del sistema
- `perfiles.json` - Perfiles de laboratorios

En Render, estos archivos se almacenan en el sistema de archivos efímero. Esto significa:
- ✅ Los archivos persisten durante el ciclo de vida del servicio
- ⚠️ Los archivos pueden perderse si Render reinicia el servicio desde cero
- ⚠️ Los archivos NO se comparten entre múltiples instancias (si escalás)

**Recomendaciones para producción:**
1. **Corto plazo:** Hacé backups regulares de estos archivos
2. **Largo plazo:** Migrá a PostgreSQL (Render ofrece bases de datos gratuitas) o usa almacenamiento persistente

### Logging

Tu aplicación configura logging hacia `app.log`, pero en Render:
- Los logs se capturan automáticamente en el dashboard
- No necesitás acceder a `app.log` directamente
- Usá el dashboard de Render para ver todos los logs en tiempo real

