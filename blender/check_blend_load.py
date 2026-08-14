"""Check user-annotated .blend: list objects and predicted classification.

Usage:
    blender -b -P check_blend_load.py -- <blend_path>
"""
import bpy
import os
import sys

argv = sys.argv
args = argv[argv.index('--') + 1:] if '--' in argv else []
if args:
    blend_path = args[0]
else:
    blend_path = r"F:\钱室\卫星图像仿真\output\blend_files\NavSat_1_Beidou-GEO.blend"

# Blender resolves relative library paths against C:\ on Windows — force absolute
blend_path = os.path.abspath(blend_path)

with bpy.data.libraries.load(blend_path, link=False) as (data_from, data_to):
    data_to.objects = data_from.objects

print("Objects in .blend:")
for obj in data_to.objects:
    if obj is None:
        continue
    name = obj.name
    n = name.lower()
    if n.startswith('panel') or 'solar' in n:
        cat = 'solar_panel'
    elif 'phased' in n or 'array' in n:
        cat = 'phased_array_antenna'
    elif 'reflector' in n or 'dish' in n:
        cat = 'reflector_antenna'
    elif 'tripod' in n or 'truss' in n:
        cat = 'solar_panel_tripod'
    elif n.startswith('body') or n.startswith('satellite') or 'bus' in n:
        cat = 'body'
    else:
        cat = 'body (default)'
    print(f"  [{obj.type}] {name:40s} -> {cat}")
