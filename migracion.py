"""
migracion.py — Importa datos históricos desde archivos JSON/TXT a la base de datos Postgres.

Ejecutar UNA sola vez (o múltiples veces: es idempotente, no duplica registros):
    python migracion.py

Qué importa:
  - usuarios_habilitados.json   → tabla usuario
  - perfiles.json               → tabla perfil
  - obras_estado.json           → tabla obra_social  (precio + estado)
  - obras_entero.txt            → tabla obra_social  (precio para obras sin precio en JSON)
  - anexo_config.json           → columna cubre_anexo en obra_social
  - CODIGO_ESTUDIO_UB.txt       → tabla estudio      (es_anexo=False)
  - Anexo_Codigos.txt           → tabla estudio      (es_anexo=True)
  - modificaciones_programadas.json → tabla modificacion_programada
  - instructivos.json           → tabla instructivo
"""

import json
import os
import sys

from dotenv import load_dotenv
load_dotenv()

from app import app, db
from app import Usuario, Perfil, ObraSocial, Estudio, ModificacionProgramada, Instructivo
from werkzeug.security import generate_password_hash


def run():
    with app.app_context():
        db.create_all()
        print("Tablas verificadas/creadas.")

        _migrar_usuarios()
        _migrar_perfiles()
        _migrar_obras()
        _migrar_estudios()
        _migrar_modificaciones()
        _migrar_instructivos()

        print("\nMigracion completa.")


# ---------------------------------------------------------------------------
# Funciones individuales
# ---------------------------------------------------------------------------

def _migrar_usuarios():
    archivo = 'usuarios_habilitados.json'
    if not os.path.exists(archivo):
        print(f"  [SKIP] {archivo} no encontrado.")
        return
    with open(archivo, 'r', encoding='utf-8') as f:
        usuarios = json.load(f)
    nuevos = 0
    for username, data in usuarios.items():
        if not Usuario.query.filter_by(username=username).first():
            db.session.add(Usuario(
                username=username,
                password=data.get('password', generate_password_hash('cambiar')),
                email=data.get('email', ''),
                habilitado=bool(data.get('habilitado', True)),
            ))
            nuevos += 1
    db.session.commit()
    print(f"  Usuarios: {nuevos} nuevos (de {len(usuarios)} totales).")


def _migrar_perfiles():
    archivo = 'perfiles.json'
    if not os.path.exists(archivo):
        print(f"  [SKIP] {archivo} no encontrado.")
        return
    with open(archivo, 'r', encoding='utf-8') as f:
        perfiles = json.load(f)
    nuevos = 0
    for username, data in perfiles.items():
        if not Perfil.query.filter_by(username=username).first():
            db.session.add(Perfil(
                username=username,
                nombre_lab=data.get('nombre_lab', 'Laboratorio'),
                subtitulo=data.get('subtitulo', 'Análisis Clínicos'),
                profesionales=data.get('profesionales', ''),
                direccion=data.get('direccion', ''),
                ciudad=data.get('ciudad', 'Trelew'),
                telefono=data.get('telefono', ''),
                logo_path=data.get('logo_path', ''),
                info_bancaria=data.get('info_bancaria', ''),
                firma_texto=data.get('firma_texto', ''),
                firma_path=data.get('firma_path', ''),
            ))
            nuevos += 1
    db.session.commit()
    print(f"  Perfiles: {nuevos} nuevos (de {len(perfiles)} totales).")


def _migrar_obras():
    # 1. Cargar estado desde obras_estado.json
    obras_dict = {}  # nombre -> {precio, estado, ultima_actualizacion}

    archivo_estado = 'obras_estado.json'
    if os.path.exists(archivo_estado):
        with open(archivo_estado, 'r', encoding='utf-8') as f:
            estado_data = json.load(f)
        for nombre, data in estado_data.get('obras', {}).items():
            obras_dict[nombre] = {
                'precio': data.get('precio'),
                'estado': data.get('estado', 'vigente'),
                'ultima_actualizacion': data.get('ultima_actualizacion'),
            }
        print(f"  obras_estado.json: {len(obras_dict)} obras cargadas.")
    else:
        print(f"  [SKIP] {archivo_estado} no encontrado.")

    # 2. Completar precios desde obras_entero.txt (si falta precio en JSON)
    archivo_txt = 'obras_entero.txt'
    txt_count = 0
    if os.path.exists(archivo_txt):
        with open(archivo_txt, 'r', encoding='utf-8') as f:
            for line in f:
                if ':' in line:
                    nombre, precio = line.strip().split(':', 1)
                    nombre = nombre.strip()
                    precio = precio.strip()
                    if nombre not in obras_dict:
                        obras_dict[nombre] = {'precio': precio, 'estado': 'vigente', 'ultima_actualizacion': None}
                        txt_count += 1
                    elif not obras_dict[nombre].get('precio'):
                        obras_dict[nombre]['precio'] = precio
        print(f"  obras_entero.txt: {txt_count} obras nuevas agregadas.")
    else:
        print(f"  [SKIP] {archivo_txt} no encontrado.")

    # 3. Cargar configuración de anexo (cubre_anexo=False)
    obras_sin_cobertura = set()
    archivo_anexo = 'anexo_config.json'
    if os.path.exists(archivo_anexo):
        with open(archivo_anexo, 'r', encoding='utf-8') as f:
            anexo_cfg = json.load(f)
        obras_sin_cobertura = set(anexo_cfg.get('obras_sin_cobertura', []))
        print(f"  anexo_config.json: {len(obras_sin_cobertura)} obras sin cobertura de anexo.")

    # 4. Upsert en DB
    nuevos = 0
    actualizados = 0
    for nombre, data in obras_dict.items():
        obra = ObraSocial.query.filter_by(nombre=nombre).first()
        es_nueva = obra is None
        if es_nueva:
            obra = ObraSocial(nombre=nombre)
            db.session.add(obra)
            nuevos += 1
        else:
            actualizados += 1
        obra.precio = data.get('precio')
        obra.estado = data.get('estado', 'vigente')
        obra.ultima_actualizacion = data.get('ultima_actualizacion')
        # cubre_anexo: False si está en la lista de sin cobertura
        obra.cubre_anexo = nombre not in obras_sin_cobertura

    db.session.commit()
    print(f"  ObraSocial: {nuevos} nuevas, {actualizados} actualizadas ({len(obras_dict)} total).")


def _migrar_estudios():
    # Cargar estudios base (es_anexo=False)
    estudios = {}
    archivo_base = 'CODIGO_ESTUDIO_UB.txt'
    if os.path.exists(archivo_base):
        with open(archivo_base, 'r', encoding='utf-8') as f:
            for line in f:
                if ':' in line:
                    parts = line.strip().split(':', 2)
                    if len(parts) == 3:
                        codigo, nombre, ub = parts
                        estudios[codigo.strip()] = {
                            'nombre': nombre.strip(),
                            'ub': ub.strip().replace(',', '.'),
                            'es_anexo': False,
                        }
        print(f"  CODIGO_ESTUDIO_UB.txt: {len(estudios)} estudios base cargados.")
    else:
        print(f"  [SKIP] {archivo_base} no encontrado.")

    # Cargar estudios de anexo (es_anexo=True); si ya existe el código, marcar como anexo
    archivo_anexo = 'Anexo_Codigos.txt'
    anexo_count = 0
    if os.path.exists(archivo_anexo):
        with open(archivo_anexo, 'r', encoding='utf-8') as f:
            for line in f:
                if ':' in line:
                    parts = line.strip().split(':', 2)
                    if len(parts) == 3:
                        codigo, nombre, ub = parts
                        codigo = codigo.strip()
                        if codigo not in estudios:
                            estudios[codigo] = {
                                'nombre': nombre.strip(),
                                'ub': ub.strip().replace(',', '.'),
                                'es_anexo': True,
                            }
                            anexo_count += 1
                        else:
                            # Ya existe en base; marcarlo como anexo
                            estudios[codigo]['es_anexo'] = True
        print(f"  Anexo_Codigos.txt: {anexo_count} estudios de anexo nuevos, resto marcados como es_anexo=True.")
    else:
        print(f"  [SKIP] {archivo_anexo} no encontrado.")

    # Upsert en DB
    nuevos = 0
    actualizados = 0
    for codigo, data in estudios.items():
        e = Estudio.query.filter_by(codigo=codigo).first()
        if e is None:
            e = Estudio(codigo=codigo)
            db.session.add(e)
            nuevos += 1
        else:
            actualizados += 1
        e.nombre = data['nombre']
        e.ub = data['ub']
        e.es_anexo = data['es_anexo']

    db.session.commit()
    print(f"  Estudio: {nuevos} nuevos, {actualizados} actualizados ({len(estudios)} total).")


def _migrar_modificaciones():
    archivo = 'modificaciones_programadas.json'
    if not os.path.exists(archivo):
        print(f"  [SKIP] {archivo} no encontrado.")
        return
    with open(archivo, 'r', encoding='utf-8') as f:
        lista = json.load(f)
    if not isinstance(lista, list):
        lista = []

    # Limpiar y recargar (idempotente: borramos y recreamos)
    ModificacionProgramada.query.delete()
    for item in lista:
        db.session.add(ModificacionProgramada(
            nombre_obra=item.get('nombre_obra', ''),
            fecha_aplicar=item.get('fecha_aplicar', ''),
            precio=item.get('precio'),
            estado=item.get('estado'),
            no_cubre_anexo=bool(item.get('no_cubre_anexo', False)),
        ))
    db.session.commit()
    print(f"  ModificacionProgramada: {len(lista)} registros importados.")


def _migrar_instructivos():
    archivo = 'instructivos.json'
    if not os.path.exists(archivo):
        print(f"  [SKIP] {archivo} no encontrado.")
        return
    with open(archivo, 'r', encoding='utf-8') as f:
        lista = json.load(f)
    if not isinstance(lista, list):
        lista = []

    nuevos = 0
    for item in lista:
        nombre = (item.get('nombre') or '').strip()
        if not nombre:
            continue
        inst = Instructivo.query.filter_by(nombre=nombre).first()
        if not inst:
            inst = Instructivo(nombre=nombre)
            db.session.add(inst)
            nuevos += 1
        inst.contenido = item.get('contenido', '')
        inst.contacto = item.get('contacto', '')
        inst.telefonos = item.get('telefonos', '')
        inst.notas_especiales = item.get('notas_especiales', '')

    db.session.commit()
    print(f"  Instructivo: {nuevos} nuevos (de {len(lista)} totales).")


if __name__ == '__main__':
    print("=== Migración de datos a PostgreSQL ===\n")
    run()
