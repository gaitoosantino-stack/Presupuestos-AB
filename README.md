# 🏥 Laboratorio Scozzina - Calculadora de Presupuestos

Sistema web para cálculo de presupuestos de laboratorio clínico con obras sociales y estudios médicos.

---

## 🚀 Inicio Rápido

### 1. Instalar dependencias:
```bash
pip install -r requirements.txt
```

### 2. Ejecutar:
```bash
python app.py
```

Abrí: http://localhost:5000

---

## 🎯 Funcionalidades

✅ **Sistema de Login**
- Autenticación de usuarios
- Gestión de usuarios habilitados
- Sesiones seguras

✅ **Calculadora de Presupuestos**
- 51+ obras sociales
- Autocomplete de estudios médicos
- Cálculo automático basado en UB (Unidades Básicas)
- Soporte para estudios manuales con precio personalizado
- Formato argentino de números

✅ **Gestión de Usuarios** (Solo Gaito)
- Agregar nuevos usuarios
- Habilitar/deshabilitar usuarios
- Eliminar usuarios

✅ **Seguridad**
- Protección CSRF
- Contraseñas encriptadas
- Sesiones seguras
- Logging completo

---

## 📁 Estructura del Proyecto

```
├── app.py                      ← Aplicación Flask principal
├── requirements.txt            ← Dependencias Python
├── templates/                  ← Plantillas HTML
│   ├── login.html
│   ├── presupuestos.html
│   └── admin_usuarios.html
├── static/                     ← Archivos estáticos
│   ├── styles.css
│   └── images/
│       ├── favicon.ico
│       └── favicon.png
├── obras_entero.txt            ← Base de datos de obras sociales
├── CODIGO_ESTUDIO_UB.txt       ← Base de datos de estudios médicos
└── usuarios_habilitados.json   ← Usuarios del sistema (se crea automáticamente)
```

---

## 📚 Documentación

### Deployment:
- [🚀 Guía de Deployment en Render](docs/GUIA_DEPLOYMENT_RENDER.md) ⭐⭐⭐

### Usuario:
- [👥 Guía de Gestión de Usuarios](GUIA_USUARIOS.md)

---

## 🔐 Acceso y Usuarios

### Usuario Administrador

**Usuario:** `Gaito`  
**Contraseña:** `Simon@594*`

⚠️ **IMPORTANTE:** Solo Gaito puede gestionar usuarios (agregar, habilitar, deshabilitar o eliminar).

### Gestión de Usuarios

Los usuarios se gestionan desde `/admin/usuarios` (solo accesible para Gaito). Los usuarios se almacenan en `usuarios_habilitados.json`.

---

## 🔧 Variables de Entorno (Opcional)

Para producción, configurá estas variables de entorno:

- `SECRET_KEY` - Clave secreta para sesiones y CSRF (opcional, se genera automáticamente si no se configura)
- `PORT` - Puerto del servidor (opcional, por defecto 5000)
- `FLASK_ENV` - Entorno de Flask: `development` o `production` (opcional)

En Render, configurá `SECRET_KEY` en el dashboard. Ver [Guía de Deployment en Render](docs/GUIA_DEPLOYMENT_RENDER.md).

---

## 📞 Contacto

**Laboratorio Scozzina**  
Pellegrini 605, Trelew, Chubut  
Tel: (0280) 4627-531  
Instagram: [@laboratorio_scozzina_](https://instagram.com/laboratorio_scozzina_)

---

## 📝 Versión

**v2.0** - Calculadora de presupuestos con gestión de usuarios

Última actualización: 27 de Enero, 2025
