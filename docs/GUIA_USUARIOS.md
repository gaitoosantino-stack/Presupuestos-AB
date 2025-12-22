# Guía de Gestión de Usuarios

## Sistema de Login

La aplicación ahora requiere iniciar sesión para acceder a la calculadora de presupuestos. Solo los usuarios que tú habilites pueden acceder.

## Usuario Administrador

Solo el usuario **Gaito** puede gestionar usuarios (agregar, habilitar, deshabilitar o eliminar usuarios).

- **Usuario:** `Gaito`
- **Contraseña:** `Simon@594*`

⚠️ **IMPORTANTE:** Solo Gaito tiene acceso al panel de "Gestionar Usuarios". Otros usuarios solo pueden usar la calculadora de presupuestos.

## Cómo Habilitar Nuevos Usuarios

### Desde la Interfaz Web (Solo para Gaito)

1. Inicia sesión con la cuenta de Gaito
2. Ve a la calculadora de presupuestos
3. Haz clic en el botón **"Gestionar Usuarios"** en el header (solo visible para Gaito)
4. En la sección "Agregar Nuevo Usuario", completa:
   - **Usuario:** Nombre de usuario (sin espacios)
   - **Contraseña:** Contraseña para el usuario
   - **Email:** (Opcional) Email del usuario
5. Haz clic en **"Agregar Usuario"**

El usuario se creará automáticamente **habilitado** y podrá iniciar sesión inmediatamente.

## Gestión de Usuarios (Solo Gaito)

Desde la página de "Gestionar Usuarios" puedes:

- **Agregar usuarios:** Crear nuevos usuarios y habilitarlos automáticamente
- **Habilitar usuarios:** Activar usuarios que estén deshabilitados
- **Deshabilitar usuarios:** Desactivar usuarios sin eliminarlos
- **Eliminar usuarios:** Eliminar usuarios permanentemente

**Nota:** La cuenta de Gaito está protegida y no puede ser deshabilitada ni eliminada.

## Estados de Usuario

- **Habilitado:** El usuario puede iniciar sesión
- **Deshabilitado:** El usuario NO puede iniciar sesión (aparece mensaje de error)

## Seguridad

- Las contraseñas se almacenan encriptadas usando `werkzeug.security`
- Solo usuarios habilitados pueden iniciar sesión
- Solo Gaito puede gestionar usuarios
- La sesión expira después de 24 horas de inactividad
- Protección CSRF en todos los formularios
- La cuenta de Gaito está protegida contra eliminación y deshabilitación

## Estructura del Archivo de Usuarios

El archivo `usuarios_habilitados.json` se crea automáticamente en la raíz del proyecto. Tiene esta estructura:

```json
{
  "Gaito": {
    "password": "hash_encriptado",
    "email": "",
    "habilitado": true
  },
  "otro_usuario": {
    "password": "hash_encriptado",
    "email": "usuario@ejemplo.com",
    "habilitado": true
  }
}
```

## Rutas de la Aplicación

- `/` o `/login` - Página de inicio de sesión
- `/presupuestos` - Calculadora de presupuestos (requiere login)
- `/admin/usuarios` - Gestión de usuarios (requiere login + ser Gaito)
- `/logout` - Cerrar sesión

## Solución de Problemas

### No puedo iniciar sesión
- Verifica que el usuario esté en `usuarios_habilitados.json`
- Verifica que `habilitado: true` para ese usuario
- Verifica que la contraseña sea correcta

### No veo el botón "Gestionar Usuarios"
- Solo el usuario "Gaito" puede ver y acceder a esta funcionalidad
- Si eres Gaito y no ves el botón, verifica que hayas iniciado sesión correctamente

### El archivo usuarios_habilitados.json no existe
- Se crea automáticamente al iniciar la aplicación con el usuario Gaito
- Si no existe, reinicia la aplicación

### Olvidé la contraseña de Gaito
- Edita manualmente el archivo `usuarios_habilitados.json` y reemplaza el hash de contraseña
- O ejecuta en Python:
  ```python
  from werkzeug.security import generate_password_hash
  print(generate_password_hash('Simon@594*'))
  ```
- Copia el hash generado al campo `password` de Gaito en el JSON
