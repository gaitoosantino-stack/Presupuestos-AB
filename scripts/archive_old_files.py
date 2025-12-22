#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script para archivar archivos de receta antiguos
"""

import os
import shutil
from datetime import datetime, timedelta
import argparse

def archive_old_files(days_old=180, dry_run=False):
    """
    Archiva archivos de receta más antiguos que X días
    
    Args:
        days_old: Días de antigüedad mínima (default: 180 = 6 meses)
        dry_run: Si es True, solo muestra qué se haría sin hacerlo
    """
    
    print("=" * 70)
    print("  📦 ARCHIVAR ARCHIVOS ANTIGUOS - LABORATORIO SCOZZINA")
    print("=" * 70)
    print()
    
    uploads_dir = "uploads"
    archive_dir = "archived_uploads"
    
    if not os.path.exists(uploads_dir):
        print("❌ La carpeta uploads/ no existe")
        return
    
    # Calcular fecha límite
    cutoff_date = datetime.now() - timedelta(days=days_old)
    print(f"📅 Archivando archivos anteriores a: {cutoff_date.strftime('%d/%m/%Y')}")
    print(f"   (Más de {days_old} días de antigüedad)")
    print()
    
    if dry_run:
        print("⚠️ MODO SIMULACIÓN (no se moverán archivos)")
        print()
    
    # Crear carpeta de archivo si no existe
    if not dry_run and not os.path.exists(archive_dir):
        os.makedirs(archive_dir)
        print(f"📁 Carpeta '{archive_dir}/' creada")
    
    # Buscar archivos antiguos
    files_to_archive = []
    total_size = 0
    
    print("🔍 Buscando archivos antiguos...")
    print("-" * 70)
    
    for filename in os.listdir(uploads_dir):
        file_path = os.path.join(uploads_dir, filename)
        
        if os.path.isfile(file_path):
            # Obtener fecha de modificación
            mtime = os.path.getmtime(file_path)
            file_date = datetime.fromtimestamp(mtime)
            
            if file_date < cutoff_date:
                file_size = os.path.getsize(file_path)
                files_to_archive.append({
                    'filename': filename,
                    'path': file_path,
                    'date': file_date,
                    'size': file_size
                })
                total_size += file_size
    
    if not files_to_archive:
        print("✅ No hay archivos antiguos para archivar")
        print()
        return
    
    # Mostrar archivos a archivar
    print(f"📄 Encontrados {len(files_to_archive)} archivos:")
    print()
    
    for i, file_info in enumerate(files_to_archive[:10], 1):  # Mostrar solo los primeros 10
        print(f"   {i}. {file_info['filename']}")
        print(f"      Fecha: {file_info['date'].strftime('%d/%m/%Y')}")
        print(f"      Tamaño: {file_info['size']/1024:.2f} KB")
        print()
    
    if len(files_to_archive) > 10:
        print(f"   ... y {len(files_to_archive) - 10} archivos más")
        print()
    
    print(f"💾 Espacio total a liberar: {total_size/1024/1024:.2f} MB")
    print()
    
    if dry_run:
        print("=" * 70)
        print("✅ SIMULACIÓN COMPLETADA")
        print("💡 Para archivar realmente, ejecutá sin --dry-run")
        print("=" * 70)
        return
    
    # Confirmar acción
    print("⚠️ ATENCIÓN:")
    print("   Los archivos se moverán a la carpeta 'archived_uploads/'")
    print("   Podés restaurarlos manualmente si es necesario")
    print()
    
    respuesta = input("¿Continuar? (s/n): ").lower().strip()
    
    if respuesta != 's':
        print("❌ Operación cancelada")
        return
    
    # Mover archivos
    print()
    print("📦 Archivando archivos...")
    print("-" * 70)
    
    archived_count = 0
    
    for file_info in files_to_archive:
        try:
            src = file_info['path']
            dst = os.path.join(archive_dir, file_info['filename'])
            
            shutil.move(src, dst)
            archived_count += 1
            
            if archived_count <= 5:  # Mostrar solo los primeros 5
                print(f"   ✓ {file_info['filename']}")
        
        except Exception as e:
            print(f"   ❌ Error al mover {file_info['filename']}: {e}")
    
    if archived_count > 5:
        print(f"   ... y {archived_count - 5} archivos más")
    
    print()
    print("=" * 70)
    print("✅ ARCHIVADO COMPLETADO")
    print("=" * 70)
    print(f"📦 Archivos movidos: {archived_count}")
    print(f"💾 Espacio liberado: {total_size/1024/1024:.2f} MB")
    print(f"📁 Ubicación: {archive_dir}/")
    print()
    print("💡 IMPORTANTE:")
    print("   1. Hacé un backup de archived_uploads/ a almacenamiento externo")
    print("   2. Podés eliminar archived_uploads/ después del backup")
    print("   3. Los registros en la BD siguen intactos")
    print()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Archiva archivos de receta antiguos'
    )
    parser.add_argument(
        '--days',
        type=int,
        default=180,
        help='Días de antigüedad mínima (default: 180 = 6 meses)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Simulación: muestra qué se haría sin hacerlo'
    )
    
    args = parser.parse_args()
    
    archive_old_files(days_old=args.days, dry_run=args.dry_run)

