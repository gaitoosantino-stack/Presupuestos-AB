from datetime import datetime

from extensions import db


class Usuario(db.Model):
    __tablename__ = "usuario"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password = db.Column(db.Text, nullable=False)
    email = db.Column(db.String(120), default="")
    habilitado = db.Column(db.Boolean, default=True, nullable=False)
    perfil = db.relationship(
        "Perfil",
        back_populates="usuario",
        uselist=False,
        cascade="all, delete-orphan",
    )


class Perfil(db.Model):
    __tablename__ = "perfil"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(
        db.String(80),
        db.ForeignKey("usuario.username", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    nombre_lab = db.Column(db.String(200), default="Laboratorio")
    subtitulo = db.Column(db.String(200), default="Analisis Clinicos")
    profesionales = db.Column(db.String(300), default="Bioquimico: - MP: -")
    direccion = db.Column(db.String(200), default="")
    ciudad = db.Column(db.String(100), default="Trelew")
    telefono = db.Column(db.String(100), default="")
    logo_path = db.Column(db.Text, default="")  # URL pública (Storage) o nombre de archivo local legado
    info_bancaria = db.Column(db.Text, default="")
    firma_texto = db.Column(db.String(200), default="")
    firma_path = db.Column(db.Text, default="")  # URL pública (Storage) o nombre local legado
    usuario = db.relationship("Usuario", back_populates="perfil")


class ObraSocial(db.Model):
    __tablename__ = "obra_social"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), unique=True, nullable=False, index=True)
    precio = db.Column(db.String(50))
    estado = db.Column(db.String(20), default="vigente", nullable=False)
    cubre_anexo = db.Column(db.Boolean, default=True, nullable=False)
    ultima_actualizacion = db.Column(db.String(50))


class Estudio(db.Model):
    __tablename__ = "estudio"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(30), unique=True, nullable=False, index=True)
    nombre = db.Column(db.String(400), nullable=False)
    ub = db.Column(db.String(200), nullable=False)
    es_anexo = db.Column(db.Boolean, default=False, nullable=False)


class ObraSocialHistorial(db.Model):
    __tablename__ = "obra_social_historial"

    id = db.Column(db.Integer, primary_key=True)
    obra_nombre = db.Column(db.String(200), nullable=False, index=True)
    fecha = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    precio_anterior = db.Column(db.String(50))
    precio_nuevo = db.Column(db.String(50))
    estado_anterior = db.Column(db.String(20))
    estado_nuevo = db.Column(db.String(20))


class ModificacionProgramada(db.Model):
    __tablename__ = "modificacion_programada"

    id = db.Column(db.Integer, primary_key=True)
    nombre_obra = db.Column(db.String(200), nullable=False, index=True)
    fecha_aplicar = db.Column(db.String(20), nullable=False)
    precio = db.Column(db.String(50))
    estado = db.Column(db.String(20))
    no_cubre_anexo = db.Column(db.Boolean, default=False)


class Instructivo(db.Model):
    __tablename__ = "instructivo"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), unique=True, nullable=False, index=True)
    contenido = db.Column(db.Text, default="")
    contacto = db.Column(db.String(200), default="")
    telefonos = db.Column(db.String(200), default="")
    notas_especiales = db.Column(db.Text, default="")
