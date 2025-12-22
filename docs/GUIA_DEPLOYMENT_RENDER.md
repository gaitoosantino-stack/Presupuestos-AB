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
- ✅ `render.yaml` - Configuración para Render (opcional, facilita el deployment)

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
| **Runtime** | `Python 3` |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `gunicorn app:app` |

### 2.4 Variables de Entorno (Opcional pero Recomendado)

En la sección **"Environment Variables"**, agregá:

| Key | Value | Descripción |
|-----|-------|-------------|
| `SECRET_KEY` | `(generá una clave segura)` | Clave para sesiones y CSRF tokens |

**Para generar SECRET_KEY:**
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

O podés usar cualquier string largo y aleatorio.

**⚠️ IMPORTANTE:** 
- No compartas nunca tu SECRET_KEY
- Si no configurás SECRET_KEY, la aplicación funcionará pero generará una nueva cada vez que se reinicie (las sesiones no persistirán)

### 2.5 Plan y Deploy

- **Plan:** Seleccioná **"Free"** (es suficiente para empezar)
- Click en **"Create Web Service"**

Render va a:
1. Clonar tu repositorio
2. Instalar dependencias (`pip install -r requirements.txt`)
3. Iniciar la aplicación con gunicorn
4. Asignar una URL pública

---

## ✅ Paso 3: Verificar el Deployment

### 3.1 Ver logs

En el dashboard de Render, andá a la sección **"Logs"** para ver si hay errores.

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

- ✅ `SECRET_KEY` configurada en variables de entorno
- ✅ `debug=False` en producción (ya está configurado)
- ✅ Protección CSRF activada
- ✅ Sesiones seguras con HttpOnly y SameSite

---

## 📝 Resumen de Comandos Importantes

```bash
# Generar SECRET_KEY segura
python -c "import secrets; print(secrets.token_hex(32))"

# Probar localmente con gunicorn (como en Render)
gunicorn app:app

# Ver logs locales
# (gunicorn muestra logs en la terminal)
```

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
1. Revisá los logs en Render
2. Verificá que todos los archivos estén en el repositorio
3. Asegurate de que las variables de entorno estén configuradas

---

**¡Listo! Tu aplicación debería estar funcionando en Render.** 🎉

---

**Última actualización:** 2025-01-27

