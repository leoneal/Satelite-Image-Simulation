"""
render_scene.py - Blender satellite image simulation renderer

Usage:
    blender -b -P render_scene.py -- --ephem_dir <path> [--start N] [--end N] [--samples 64]

The --ephem_dir should contain:
    observer_state.csv, target_state.csv, sun_state.csv, aux_data.csv, scene_config.json

Output:
    output/images/frame_0001.png ... (RGB renders)
    output/annotations/instance_masks/frame_0001.png ... (per-component instance masks)
    output/annotations/pose/frame_0001.txt ... (pose ground truth per frame)
    output/annotations/coco_detection.json (COCO detection annotations)
    output/annotations/coco_segmentation.json (COCO segmentation annotations)
    output/annotations/yolo/ (YOLO-format detection labels)
"""

import bpy
import csv
import json
import os
import sys
import math
import random
import argparse
from mathutils import Vector, Matrix, Quaternion, Euler

# ============================================================
# Command-line argument parsing
# ============================================================

def parse_args():
    argv = sys.argv
    if '--' in argv:
        argv = argv[argv.index('--') + 1:]
    else:
        argv = []

    parser = argparse.ArgumentParser()
    parser.add_argument('--ephem_dir', required=True, help='Path to ephemeris data directory')
    parser.add_argument('--start', type=int, default=0, help='First frame index (0-based)')
    parser.add_argument('--end', type=int, default=None, help='Last frame index (exclusive)')
    parser.add_argument('--stride', type=int, default=1, help='Frame stride (1=every frame, 60=every 60th frame)')
    parser.add_argument('--samples', type=int, default=64, help='Cycles render samples')
    parser.add_argument('--resolution', type=int, default=2048, help='Render resolution (square)')
    parser.add_argument('--batch_size', type=int, default=500, help='Frames per batch')
    parser.add_argument('--batch_offset', type=int, default=0, help='Batch offset multiplier')
    parser.add_argument('--tag', type=str, default=None,
                        help='Batch tag for output subfolder naming (default: auto from start/end)')
    parser.add_argument('--camera_mode', type=str, default='track',
                        choices=['track', 'stare'],
                        help='track: camera follows target; stare: fixed ECI boresight')
    parser.add_argument('--fov', type=float, default=0.117, help='Camera FOV in degrees')
    parser.add_argument('--model_scale', type=float, default=1.0,
                        help='Scale factor for satellite model (e.g. 10.0 = 10x larger)')
    parser.add_argument('--model_type', type=str, default='auto',
                        choices=['auto', 'dsp_blend', 'simple'],
                        help='Satellite model: auto (detect), dsp_blend, simple')
    parser.add_argument('--no_annotations', action='store_true', help='Skip mask/COCO/YOLO/pose generation')
    parser.add_argument('--frame_variations', type=int, default=1,
                        help='Number of attitude variations per frame (1=original only)')
    parser.add_argument('--attitude_jitter_deg', type=float, default=0.0,
                        help='Max random attitude perturbation in degrees (uniform cone)')
    parser.add_argument('--sun_phase_offsets', type=str, default='',
                        help='Comma-separated sun phase offsets in degrees (e.g. "30,90,150")')
    parser.add_argument('--sun_energy_range', type=str, default='',
                        help='Sun energy range "min,max" for random sampling (e.g. "40,120")')
    parser.add_argument('--render_device', type=str, default='gpu',
                        choices=['gpu', 'cpu'],
                        help='Render device: gpu (OptiX) or cpu')
    parser.add_argument('--sat_class_id', type=int, default=None,
                        help='Satellite model class ID for YOLO detection label '
                             '(0-based, added as extra line per frame)')
    parser.add_argument('--fbx_path', type=str, default=None,
                        help='Path to FBX model file (overrides default)')
    parser.add_argument('--blend_path', type=str, default=None,
                        help='Path to user-annotated .blend model (takes priority; '
                             'textures are linked from fbx_path directory)')
    parser.add_argument('--output_root', type=str, default=None,
                        help='Override output root directory (default: dirname of ephem_dir)')
    return parser.parse_args(argv)


# ============================================================
# Data loading
# ============================================================

def load_csv(filepath):
    """Load CSV into list of dicts, converting numeric values"""
    rows = []
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({k: float(v) for k, v in row.items()})
    return rows


def load_config(filepath):
    with open(filepath, 'r') as f:
        return json.load(f)


def load_all_data(ephem_dir):
    """Load all ephemeris data files"""
    print(f"Loading data from: {ephem_dir}")
    obs_data = load_csv(os.path.join(ephem_dir, 'observer_state.csv'))
    tgt_data = load_csv(os.path.join(ephem_dir, 'target_state.csv'))
    sun_data = load_csv(os.path.join(ephem_dir, 'sun_state.csv'))
    config = load_config(os.path.join(ephem_dir, 'scene_config.json'))
    print(f"  Loaded {len(obs_data)} frames")
    return obs_data, tgt_data, sun_data, config


# ============================================================
# Scene setup
# ============================================================

KM_SCALE = 0.001       # Convert meters to km for Blender scene
EARTH_RADIUS = 6371.0   # km

# FBX models may have an inherent rotation (modeling convention artifact).
# This quaternion is captured during loading and compensated in update_frame
# so that tgt_quat (satellite attitude) applies cleanly without double-rotation.
_fbx_model_rot_inv = Quaternion((1, 0, 0, 0))  # identity = no compensation


def clear_scene():
    """Remove all default objects"""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()


def create_earth():
    """Create Earth sphere with Blue Marble texture (fallback to solid blue if not found)."""
    bpy.ops.mesh.primitive_uv_sphere_add(
        radius=EARTH_RADIUS,
        location=(0, 0, 0),
        segments=128, ring_count=64
    )
    earth = bpy.context.active_object
    earth.name = 'Earth'

    mat = bpy.data.materials.new('EarthMaterial')
    nodes = mat.node_tree.nodes
    nodes.clear()

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tex_path = os.path.join(project_root, 'data', 'earth_textures', '8k_earth_daymap.jpg')

    if os.path.exists(tex_path):
        img_tex = nodes.new('ShaderNodeTexImage')
        img = bpy.data.images.load(tex_path)
        img_tex.image = img
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        bsdf.inputs['Roughness'].default_value = 0.7
        nodes.new('ShaderNodeTexCoord')
        output = nodes.new('ShaderNodeOutputMaterial')
        mat.node_tree.links.new(img_tex.outputs['Color'], bsdf.inputs['Base Color'])
        mat.node_tree.links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
        print('  Earth: 8K textured')
    else:
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        bsdf.inputs['Base Color'].default_value = (0.1, 0.2, 0.5, 1.0)
        bsdf.inputs['Roughness'].default_value = 0.7
        output = nodes.new('ShaderNodeOutputMaterial')
        mat.node_tree.links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
        print(f'  Earth: solid blue (texture not found at {tex_path})')

    earth.data.materials.append(mat)
    return earth


# ============================================================
# Satellite model loading — unified pipeline with correct transform baking
# ============================================================
#
# Every loading path follows the same rules (from CLAUDE.md lessons learned):
#   1. Import/load geometry
#   2. Remove non-mesh objects (cameras, lights, empties)
#   3. Unparent meshes (CLEAR_KEEP_TRANSFORM preserves world positions)
#   4. Bake ALL transforms → identity (location, rotation, scale)
#   5. Center geometry at origin (shift vertices so geometric center = origin)
#   6. Scale vertex data to km, apply
#   7. Assign emission+BSDF mix material (NOT 100% emission — kills 3D detail)
#   8. Return flat list of independent meshes with identity transforms
#
# The key fixes vs the old code:
#   - transform_apply(location=True, rotation=True, scale=True) on EVERY mesh
#   - Centering: model center maps to origin → update_frame places center at tgt_pos
#   - Materials: 40% emission + 60% BSDF (was 100% emission — made all surfaces
#     look like flat colored silhouettes with zero depth cues)
#   - No parent-child hierarchy → flat list, no hidden transform compounding

# Color+emission presets by component type (also used by _build_simple_model)
COMPONENT_COLORS = {
    'body':    (0.70, 0.70, 0.70),   # grey
    'panel':   (0.10, 0.20, 0.55),   # blue solar panel
    'phased':  (0.92, 0.90, 0.80),   # cream/light yellow
    'reflector': (0.88, 0.87, 0.92), # light silver
    'tripod':  (0.60, 0.50, 0.40),   # bronze
    'default': (0.65, 0.65, 0.68),   # neutral grey
}


def _classify_part(obj):
    """Return (component_type, pass_index_base) from object name.
    component_type is one of: 'body', 'panel', 'phased', 'reflector', 'tripod', 'default'
    """
    name = obj.name.lower()
    if name.startswith('panel') or 'solar' in name:
        return 'panel', 2
    elif 'phased' in name or 'array' in name:
        return 'phased', 100
    elif 'reflector' in name or 'dish' in name:
        return 'reflector', 150
    elif 'tripod' in name or 'truss' in name:
        return 'tripod', 200
    elif name.startswith('body') or name.startswith('satellite') or 'bus' in name:
        return 'body', 1
    else:
        return 'default', 1


def _add_component_material(obj, comp_type):
    """BSDF-dominant material with trace emission to prevent pure-black shadows."""
    mat = bpy.data.materials.new(obj.name + '_mat')
    nodes = mat.node_tree.nodes
    nodes.clear()

    color = COMPONENT_COLORS.get(comp_type, COMPONENT_COLORS['default'])

    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.inputs['Base Color'].default_value = (*color, 1.0)
    bsdf.inputs['Roughness'].default_value = 0.4
    bsdf.inputs['Metallic'].default_value = 0.3

    emit = nodes.new('ShaderNodeEmission')
    emit.inputs['Color'].default_value = (*color, 1.0)
    emit.inputs['Strength'].default_value = 1.0

    mix = nodes.new('ShaderNodeMixShader')
    mix.inputs['Fac'].default_value = 0.05  # 5% emission, barely visible

    output = nodes.new('ShaderNodeOutputMaterial')
    mat.node_tree.links.new(bsdf.outputs['BSDF'], mix.inputs[1])
    mat.node_tree.links.new(emit.outputs['Emission'], mix.inputs[2])
    mat.node_tree.links.new(mix.outputs['Shader'], output.inputs['Surface'])

    obj.data.materials.clear()
    obj.data.materials.append(mat)


def _bake_transform(obj):
    """Fully bake an object's transform into its mesh vertex data.
    After this call: obj.location=(0,0,0), obj.scale=(1,1,1), obj.rotation_quaternion=identity.
    """
    obj.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    obj.select_set(False)


def _unparent_meshes(meshes):
    """Unparent all meshes, preserving world positions via CLEAR_KEEP_TRANSFORM."""
    for obj in meshes:
        if obj.parent:
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
            obj.select_set(False)


def _center_and_scale_to_km(meshes, model_scale=1.0):
    """
    Compute geometric center of all mesh vertices, shift so center → origin,
    then scale all vertex data by KM_SCALE * model_scale.

    After this: all meshes have identity transforms, vertices in km units,
    model geometric center at origin. model_scale > 1 enlarges the model.
    """
    if not meshes:
        return

    # Compute geometric center (average of all vertex positions in world space)
    all_verts = []
    for obj in meshes:
        mw = obj.matrix_world
        for v in obj.data.vertices:
            all_verts.append(mw @ v.co)
    center = sum(all_verts, Vector((0, 0, 0))) / len(all_verts)

    # Build transform: translate center → origin, then scale to km * model_scale
    total_scale = KM_SCALE * model_scale
    to_km = Matrix.Scale(total_scale, 4) @ Matrix.Translation(-center)

    for obj in meshes:
        obj.data.transform(to_km)

    # Measure and report
    all_v = []
    for obj in meshes:
        for v in obj.data.vertices:
            all_v.append(v.co.copy())
    xs = [v.x for v in all_v]; ys = [v.y for v in all_v]; zs = [v.z for v in all_v]
    dims = (max(xs)-min(xs), max(ys)-min(ys), max(zs)-min(zs))
    scale_str = f' (x{model_scale})' if model_scale != 1.0 else ''
    print(f'  Model centered, km-scale: max dim {max(dims)*1000:.1f}m{scale_str}')


def _load_fbx_textures(fbx_path, meshes):
    """Create textured materials for each FBX mesh: BSDF + matched texture + emission.
    Combines material creation and texture linking in one step for reliability."""
    fbx_dir = os.path.dirname(os.path.abspath(fbx_path))
    img_exts = ('.jpg', '.jpeg', '.png', '.tga', '.bmp', '.tif', '.tiff')
    tex_files = sorted(f for f in os.listdir(fbx_dir)
                       if os.path.splitext(f)[1].lower() in img_exts)
    if not tex_files:
        # No textures: fall back to colored emission materials
        for obj in meshes:
            comp_type = _classify_part(obj)[0]
            _add_component_material(obj, comp_type)
        return

    loaded_imgs = []
    for f in tex_files:
        try:
            img = bpy.data.images.load(os.path.join(fbx_dir, f))
            loaded_imgs.append((f, img))
        except Exception:
            pass
    if not loaded_imgs:
        for obj in meshes:
            _add_component_material(obj, _classify_part(obj)[0])
        return

    # Match textures to meshes by original FBX name.
    # Texture naming varies across models. Common patterns:
    #   Gold:    lvbo金色.jpg, 金箔.jpg                      (keyword: 金, gold)
    #   Silver:  lvbo银色.jpg, 铝箔.jpg                      (keyword: 银, 铝, silver, alumin)
    #   Solar:   Solar panel.jpg, 太阳能电池阵列.jpg, tyb.jpg (keyword: solar, panel, 太阳, 电池, tyb, slrpnls)
    # Mesh names vary by modeler. Common patterns:
    #   "Aluminizing", "Gold-plating", "Solar panel _front", "White paint"

    def _tex_has(fname, *keywords):
        return any(kw in os.path.splitext(fname)[0].lower() for kw in keywords)

    for obj in meshes:
        # Meshes without a UV map cannot sample textures — use solid color
        if not obj.data.uv_layers.active:
            _add_component_material(obj, _classify_part(obj)[0])
            continue
        o_name = obj.get('fbx_original_name', obj.name).lower()

        def _mesh_has(*keywords):
            return any(kw in o_name for kw in keywords)

        # Default to silver/aluminum (most neutral), fallback to first image
        best_img = loaded_imgs[0][1]
        for fname, img in loaded_imgs:
            if _tex_has(fname, '银', 'silver', 'alumin', '铝'):
                best_img = img; break

        # Keyword matching: texture name ↔ mesh name
        for fname, img in loaded_imgs:
            # Solar panel
            if _tex_has(fname, 'solar', 'panel', '太阳', '电池', 'tyb', 'slrpnls'):
                if _mesh_has('solar', 'panel', '太阳', '电池', 'tyb', 'slrpnls'):
                    best_img = img; break
            # Gold
            if _tex_has(fname, '金', 'gold'):
                if _mesh_has('gold', '金'):
                    best_img = img; break
            # Silver/aluminum
            if _tex_has(fname, '银', 'silver', 'alumin', '铝'):
                if _mesh_has('alumin', '银', 'silver', '铝'):
                    best_img = img; break

        # Create material: textured BSDF + textured emission.
        # KEY: emission Color MUST be driven by the texture, same as BSDF Base Color.
        # Otherwise emission defaults to white and washes out all texture detail.
        # DSP uses 5% emission to prevent pure-black shadows; FBX uses 30% so
        # textures remain visible at km-scale distances where BSDF contribution is
        # minimal (small target, limited pixel coverage).
        mat = bpy.data.materials.new(obj.name + '_mat')
        nodes = mat.node_tree.nodes; nodes.clear()

        tex_node = nodes.new('ShaderNodeTexImage')
        tex_node.image = best_img
        tex_node.interpolation = 'Linear'

        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        bsdf.inputs['Roughness'].default_value = 0.4
        bsdf.inputs['Metallic'].default_value = 0.3

        emit = nodes.new('ShaderNodeEmission')
        emit.inputs['Strength'].default_value = 1.0

        mix = nodes.new('ShaderNodeMixShader')
        mix.inputs['Fac'].default_value = 0.30  # 30% emission — 6× DSP but preserves BSDF lighting

        output = nodes.new('ShaderNodeOutputMaterial')
        # Texture → BSDF base color
        mat.node_tree.links.new(tex_node.outputs['Color'], bsdf.inputs['Base Color'])
        # Texture → Emission color (critical: prevents white washout)
        mat.node_tree.links.new(tex_node.outputs['Color'], emit.inputs['Color'])
        # BSDF → Mix input 1 (bottom), Emission → Mix input 2 (top)
        mat.node_tree.links.new(bsdf.outputs['BSDF'], mix.inputs[1])
        mat.node_tree.links.new(emit.outputs['Emission'], mix.inputs[2])
        # Mix → Output
        mat.node_tree.links.new(mix.outputs['Shader'], output.inputs['Surface'])

        obj.data.materials.clear()
        obj.data.materials.append(mat)

    print(f'  Textures linked: {len(loaded_imgs)} image(s) from FBX directory')


def _split_panel_meshes(meshes):
    """Split solar panel meshes spanning both sides of x=0 into left/right halves.

    Many 3ds Max models store BOTH wings in a single mesh (vertices span x<0
    and x>0). Splitting at the model center (x=0, after centering) produces
    two wing instances. Front/back faces of the same physical wing are
    co-located meshes with 'front'/'back' in their names — they are grouped
    so they share one instance ID (only the facing side is visible at once).
    """
    panels = [o for o in meshes
              if 'solar' in o.name.lower() or 'panel' in o.name.lower()]
    if not panels:
        return

    # Step 1: split panels spanning both sides of x=0
    for obj in list(panels):
        xs = [v.co.x for v in obj.data.vertices]
        if min(xs) > -1e-6 or max(xs) < 1e-6:
            continue  # single-sided wing, no split

        other = obj.copy()
        other.data = obj.data.copy()
        bpy.context.collection.objects.link(other)

        # obj keeps x<0 (left), other keeps x>0 (right). Bisect preserves UVs.
        for target, clear_inner, clear_outer, side in (
                (obj, False, True, 'left'),
                (other, True, False, 'right')):
            bpy.ops.object.select_all(action='DESELECT')
            target.select_set(True)
            bpy.context.view_layer.objects.active = target
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.bisect(plane_co=(0, 0, 0), plane_no=(1, 0, 0),
                                clear_inner=clear_inner, clear_outer=clear_outer)
            bpy.ops.object.mode_set(mode='OBJECT')
            target['panel_side'] = side
            target.select_set(False)

        panels.append(other)
        meshes.append(other)

    # Step 2: group front/back faces of the same wing by (base_name, side).
    # e.g. "Solar panel _front" / "Solar panel _back" → same group per side.
    # ONLY meshes with 'front'/'back' in the name are grouped — distinct
    # user-named panels (e.g. 'panel _1', 'panel _2') stay separate instances.
    groups = {}
    for obj in panels:
        n = obj.get('fbx_original_name', obj.name).lower()
        had_suffix = False
        for suffix in ('back', 'front'):
            if suffix in n:
                n = n.replace(suffix, '')
                had_suffix = True
                break
        if had_suffix:
            base = n.strip(' _0123456789')
            side = obj.get('panel_side', '')
            groups.setdefault((base, side), []).append(obj)
        else:
            # Distinct user-named panel → its own group (id() keeps it unique)
            groups.setdefault(('user', id(obj)), []).append(obj)

    # Step 3: assign instance IDs, ordered left-to-right for determinism
    ordered = sorted(groups.items(), key=lambda kv: min(
        min((v.co.x for v in o.data.vertices), default=0.0) for o in kv[1]))
    for gid, (_key, objs) in enumerate(ordered, start=1):
        for obj in objs:
            obj['panel_group'] = gid


def _load_fbx_model(fbx_path, model_scale=1.0):
    """Load single-mesh FBX model with proper transform baking."""
    pre_import = set(bpy.data.objects)

    bpy.ops.import_scene.fbx(filepath=fbx_path)

    # Gather imported objects, remove cameras/lights
    imported = [o for o in bpy.data.objects if o not in pre_import]
    for obj in list(imported):
        if obj.type in ('CAMERA', 'LIGHT'):
            bpy.data.objects.remove(obj, do_unlink=True)
            imported.remove(obj)

    meshes = [o for o in imported if o.type == 'MESH']
    if not meshes:
        print('  No mesh in FBX, falling back to simple model')
        return _build_simple_model()

    # Remove empties (we bake transforms, so hierarchy is moot)
    for obj in list(imported):
        if obj.type == 'EMPTY':
            bpy.data.objects.remove(obj, do_unlink=True)

    # Step 1: Unparent (in case an empty was a parent of a mesh in our list)
    _unparent_meshes(meshes)

    # Step 2: Capture FBX model rotation before baking (must set rotation_mode first)
    global _fbx_model_rot_inv
    if meshes:
        meshes[0].rotation_mode = 'QUATERNION'
        _fbx_model_rot_inv = meshes[0].rotation_quaternion.inverted()

    # Step 3: Bake all transforms on every mesh
    for obj in meshes:
        _bake_transform(obj)

    # Step 4: Center geometry, scale to km
    _center_and_scale_to_km(meshes, model_scale)

    # Step 5: Classify components, assign pass_index, preserve original FBX materials
    # FBX materials (with textures) are kept for beauty rendering.
    # Mask rendering uses assign_mask_materials which swaps to pure emission colors.
    # Step 5: Classify parts, assign textured materials
    # Save original names before renaming
    for obj in meshes:
        obj['fbx_original_name'] = obj.name

    # Split merged solar panel meshes into left/right wing instances.
    # Many 3ds Max models store BOTH wings in one mesh (spanning x=0),
    # and store front/back faces as separate co-located meshes. Split at x=0
    # and group front/back of the same wing into one instance.
    _split_panel_meshes(meshes)

    panel_idx = 1
    for obj in meshes:
        comp_type, base_idx = _classify_part(obj)
        if comp_type == 'panel':
            if 'panel_group' in obj:
                gid = obj['panel_group']
            else:
                gid = panel_idx
            obj.pass_index = base_idx + gid - 1
            obj.name = f'panel_{gid}'
            panel_idx += 1
        else:
            obj.pass_index = 1
            obj.name = 'body'

    # Load textures from FBX directory
    _load_fbx_textures(fbx_path, meshes)

    print(f'  Satellite: FBX loaded ({len(meshes)} mesh(es), transforms baked)')
    return meshes


def _load_blend_model(blend_path, model_scale=1.0, fbx_path=None):
    """Load user-annotated .blend model with proper transform baking.
    fbx_path (optional): directory source for texture linking — textures are
    matched by the user's mesh names (e.g. 'Gold-plating', 'panel_1')."""
    # Blender resolves relative library paths against the process cwd, which
    # is unreliable on Windows (may end up at a drive root). Force absolute.
    blend_path = os.path.abspath(blend_path)
    if fbx_path:
        fbx_path = os.path.abspath(fbx_path)
    with bpy.data.libraries.load(blend_path, link=False) as (data_from, data_to):
        data_to.objects = data_from.objects

    new_objects = []
    for obj in data_to.objects:
        if obj is not None:
            bpy.context.collection.objects.link(obj)
            new_objects.append(obj)

    # Remove cameras, lights, untitled empties that came from the model file
    for obj in list(new_objects):
        if obj.type in ('CAMERA', 'LIGHT') or (obj.type == 'EMPTY' and 'untitled' in obj.name.lower()):
            bpy.data.objects.remove(obj, do_unlink=True)
            new_objects.remove(obj)

    meshes = [obj for obj in new_objects if obj.type == 'MESH']
    if not meshes:
        print('  No meshes in .blend, falling back to simple model')
        return _build_simple_model()

    # Step 1: Unparent all meshes (CLEAR_KEEP_TRANSFORM preserves world pos)
    _unparent_meshes(meshes)

    # Step 2: Delete all empties (hierarchy is baked into mesh transforms now)
    for obj in list(new_objects):
        if obj.type == 'EMPTY':
            bpy.data.objects.remove(obj, do_unlink=True)

    # Step 3: Capture FBX model rotation before baking (all meshes share the same rot)
    # This rotation is a modeling convention artifact, NOT the satellite's attitude.
    # It gets baked into vertex data by _bake_transform; we compensate in update_frame.
    global _fbx_model_rot_inv
    if meshes:
        meshes[0].rotation_mode = 'QUATERNION'
        _fbx_model_rot_inv = meshes[0].rotation_quaternion.inverted()

    # Step 4: Bake all transforms → identity on every mesh
    for obj in meshes:
        _bake_transform(obj)

    # Step 5: Center geometry, scale to km
    _center_and_scale_to_km(meshes, model_scale)

    # Step 6: Separate full model from labeled parts.
    # Full model (digit-first name, legacy DSP.blend convention): used for
    # beauty RGB renders (complete geometry). New satellite .blend files do
    # NOT use this — all parts render in both beauty and mask.
    # Save user names for texture matching before renaming
    for obj in meshes:
        obj['fbx_original_name'] = obj.name

    # Split merged solar panel meshes into left/right wing instances (same
    # logic as FBX path; user-split single-sided meshes are skipped).
    _split_panel_meshes(meshes)

    full_model = None
    panel_idx, phased_idx, reflector_idx, tripod_idx = 1, 1, 1, 1
    labeled = []
    for obj in meshes:
        if obj.name[0].isdigit():
            # Original full mesh → keep for beauty rendering
            full_model = obj
            full_model.name = 'sat_full'
            full_model.pass_index = 1
            full_model['is_full_model'] = True
            _add_component_material(full_model, 'default')
            full_model.hide_render = False  # visible for beauty
        else:
            labeled.append(obj)
            comp_type, base_idx = _classify_part(obj)
            if comp_type == 'panel':
                if 'panel_group' in obj:
                    gid = obj['panel_group']
                else:
                    gid = panel_idx
                obj.pass_index = base_idx + gid - 1
                obj.name = f'panel_{gid}'
                panel_idx += 1
            elif comp_type == 'phased':
                obj.pass_index = base_idx + phased_idx - 1
                obj.name = f'antenna_phased_{phased_idx}'; phased_idx += 1
            elif comp_type == 'reflector':
                obj.pass_index = base_idx + reflector_idx - 1
                obj.name = f'antenna_reflector_{reflector_idx}'; reflector_idx += 1
            elif comp_type == 'tripod':
                obj.pass_index = base_idx + tripod_idx - 1
                obj.name = f'tripod_{tripod_idx}'; tripod_idx += 1
            else:
                obj.pass_index = 1
                obj.name = 'body'
            obj.hide_render = False  # visible for beauty

    # Textures: if fbx_path given, link textures matched by user mesh names.
    # Otherwise fall back to solid colors (legacy DSP.blend behavior).
    if fbx_path and os.path.exists(fbx_path):
        _load_fbx_textures(fbx_path, meshes)
    else:
        for obj in labeled:
            _add_component_material(obj, _classify_part(obj)[0])
        if full_model:
            _add_component_material(full_model, 'default')

    # Return: full model first (if exists), then labeled parts
    result = ([full_model] if full_model else []) + labeled
    label_count = len(labeled)
    full_str = ' + full model' if full_model else ''
    print(f'  Satellite: .blend loaded ({label_count} label parts{full_str}, transforms baked)')
    return result


def _build_simple_model(model_scale=1.0):
    """Fallback: build simple geometric satellite model with baked transforms."""
    S = KM_SCALE * model_scale  # 0.001 = 1 meter in km, scaled

    parts_spec = [
        # (name, shape, location_km, scale_factors, comp_type)
        # Body: 4m x 2m x 1.5m bus
        ('body', 'cube', (0, 0, 0), (2.0, 1.0, 0.75), 'body'),
        # Solar panels: 3.5m x 1m x 0.03m each, at ±3m from center
        ('panel_1', 'cube', (-3.0*S, 0, 0.1*S), (1.75, 0.5, 0.015), 'panel'),
        ('panel_2', 'cube', (3.0*S, 0, 0.1*S), (1.75, 0.5, 0.015), 'panel'),
        # Phased array antenna dish: z=+1.0m
        ('antenna_phased_1', 'cylinder', (0, 0, 1.0*S), None, 'phased'),
        # Reflector antenna: z=-1.0m
        ('antenna_reflector_1', 'cylinder', (0, 0, -1.0*S), None, 'reflector'),
    ]

    parts = []
    for name, shape, loc, sc, comp_type in parts_spec:
        if shape == 'cube':
            bpy.ops.mesh.primitive_cube_add(size=2.0*S, location=loc)
            obj = bpy.context.active_object
            if sc:
                obj.scale = sc
                bpy.ops.object.transform_apply(scale=True)
        else:
            if 'phased' in name:
                bpy.ops.mesh.primitive_cylinder_add(radius=0.4*S, depth=0.1*S, location=loc)
            else:
                bpy.ops.mesh.primitive_cylinder_add(radius=0.3*S, depth=0.5*S, location=loc)
            obj = bpy.context.active_object

        obj.name = name
        parts.append(obj)

        # Classify and assign pass_index
        ct, base_idx = _classify_part(obj)
        if ct == 'panel':
            obj.pass_index = base_idx + len([p for p in parts if 'panel' in p.name]) - 1
        else:
            obj.pass_index = base_idx

        _add_component_material(obj, ct)

    # Bake locations into vertex data so offsets are all zero
    for obj in parts:
        _bake_transform(obj)

    print(f'  Satellite: simple geometric model ({len(parts)} parts)')
    return parts


def create_satellite_model(model_scale=1.0, model_type='auto', fbx_path=None,
                           blend_path=None):
    """
    Load satellite model.

    model_type:
      - 'auto':      auto-detect (try .blend if given, then FBX, then simple)
      - 'dsp_blend': force .blend (user-annotated components + full model)
      - 'simple':    force simple geometric primitives

    fbx_path: optional path to a specific FBX file (overrides default).
    blend_path: optional path to a user-annotated .blend (textures come from
        fbx_path's directory).
    """
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_blend = os.path.join(project_root, 'output', 'blend_files', 'DSP.blend')
    default_fbx = os.path.join(project_root, 'data', 'sat_models', 'DSP', '1323.fbx')
    effective_fbx = fbx_path if fbx_path and os.path.exists(fbx_path) else default_fbx

    if model_type == 'simple':
        return _build_simple_model(model_scale)
    elif model_type == 'dsp_blend':
        effective_blend = blend_path if blend_path else default_blend
        if os.path.exists(effective_blend):
            # fbx_path (raw arg, may be None) is only used for texture linking;
            # None → solid colors (legacy DSP appearance)
            return _load_blend_model(effective_blend, model_scale, fbx_path)
        else:
            print(f'  .blend not found ({effective_blend}), falling back to simple')
            return _build_simple_model(model_scale)
    else:  # auto
        # User-annotated .blend takes priority over raw FBX
        if blend_path and os.path.exists(blend_path):
            return _load_blend_model(blend_path, model_scale, fbx_path)
        if fbx_path and os.path.exists(fbx_path):
            return _load_fbx_model(fbx_path, model_scale)
        if os.path.exists(default_blend):
            return _load_blend_model(default_blend, model_scale)
        elif os.path.exists(effective_fbx):
            return _load_fbx_model(effective_fbx, model_scale)
        else:
            return _build_simple_model(model_scale)


def setup_camera(fov_deg, resolution, camera_mode='track'):
    """Create camera for first-person view.
    In 'stare' mode, stores the initial boresight direction for fixed ECI pointing.
    """
    bpy.ops.object.camera_add(location=(0, 0, 0))
    cam = bpy.context.active_object
    cam.name = 'SensorCamera'
    cam.data.angle = math.radians(fov_deg)
    cam.data.sensor_fit = 'HORIZONTAL'
    cam.data.clip_start = 0.01
    cam.data.clip_end = 200000.0

    bpy.context.scene.render.resolution_x = resolution
    bpy.context.scene.render.resolution_y = resolution
    bpy.context.scene.render.resolution_percentage = 100

    # Store camera parameters for use by update_frame
    cam['camera_mode'] = camera_mode
    cam['stare_dir'] = None  # set on first update_frame

    return cam


def setup_sun():
    """Create directional sun light. Energy boosted to light the BSDF component
    of satellite materials (40% emission + 60% BSDF needs good incident light)."""
    bpy.ops.object.light_add(type='SUN', location=(0, 0, 0))
    sun = bpy.context.active_object
    sun.name = 'SunLight'
    sun.data.energy = 200.0  # Moderate sunlight — bright enough for BSDF, avoids clipping

    # Create empty for easy orientation
    bpy.ops.object.empty_add(type='PLAIN_AXES', location=(0, 0, 0))
    sun_target = bpy.context.active_object
    sun_target.name = 'SunTarget'

    return sun, sun_target


def setup_stars(camera):
    """Starfield via emissive plane parented to camera (works around world shader bugs).
    A large textured plane is placed in front of the camera, acting as a backdrop.
    """
    # World: pure black
    world = bpy.context.scene.world
    nodes_w = world.node_tree.nodes
    links_w = world.node_tree.links
    nodes_w.clear()
    bg = nodes_w.new('ShaderNodeBackground')
    bg.inputs['Color'].default_value = (0.0, 0.0, 0.0, 1.0)
    bg.inputs['Strength'].default_value = 1.0
    out_w = nodes_w.new('ShaderNodeOutputWorld')
    links_w.new(bg.outputs['Background'], out_w.inputs['Surface'])

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tex_path = os.path.join(project_root, 'data', 'star_bg', '8k_stars.jpg')

    if not os.path.exists(tex_path):
        print(f'  Stars: fallback dark (no texture at {tex_path})')
        return

    # Create backdrop plane far behind any possible satellite distance
    # Camera looks along -Z. 100000 km ensures plane is always behind satellite.
    BACKDROP_DIST = 100000.0  # km, well beyond max satellite distance (~16300 km)
    # Plane size scales with camera FOV (read from camera after setup_camera)
    import math as m
    half_fov = camera.data.angle / 2.0  # actual FOV from camera
    plane_size = 2.0 * BACKDROP_DIST * m.tan(half_fov) * 2.5  # 2.5x margin
    bpy.ops.mesh.primitive_plane_add(size=plane_size, location=(0, 0, -BACKDROP_DIST))
    plane = bpy.context.active_object
    plane.name = 'StarBackdrop'

    # Parent to camera so it follows
    plane.parent = camera

    # Emission material with star texture
    mat = bpy.data.materials.new('StarBackdropMat')
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    img = bpy.data.images.load(tex_path)
    tex = nodes.new('ShaderNodeTexImage')
    tex.image = img
    # Window coordinates + Mapping to rotate stars as camera turns (celestial fix)
    coord = nodes.new('ShaderNodeTexCoord')
    mapping = nodes.new('ShaderNodeMapping')
    mapping.inputs['Location'].default_value = (0.0, 0.0, 0.0)
    links.new(coord.outputs['Window'], mapping.inputs['Vector'])
    links.new(mapping.outputs['Vector'], tex.inputs['Vector'])

    emit = nodes.new('ShaderNodeEmission')
    emit.inputs['Strength'].default_value = 1.0
    links.new(tex.outputs['Color'], emit.inputs['Color'])
    out = nodes.new('ShaderNodeOutputMaterial')
    links.new(emit.outputs['Emission'], out.inputs['Surface'])
    plane.data.materials.append(mat)

    # Store references for per-frame rotation compensation
    setup_stars.mapping_node = mapping
    setup_stars.ref_matrix = None  # set on first update_frame

    print('  Stars: backdrop plane with celestial-rotation compensation')


def setup_render(samples, render_device='gpu'):
    """Configure Cycles render settings."""
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'

    if render_device == 'gpu':
        prefs = bpy.context.preferences.addons['cycles'].preferences
        prefs.refresh_devices()
        prefs.compute_device_type = 'OPTIX'
        scene.cycles.device = 'GPU'
        for dev in prefs.devices:
            dev.use = dev.type == 'OPTIX'
        scene.cycles.tile_size = 2048  # large tiles for GPU
        print(f'  Render device: GPU (OptiX), {sum(1 for d in prefs.devices if d.use)} device(s)')
    else:
        scene.cycles.device = 'CPU'
        scene.cycles.tile_size = 64
        print(f'  Render device: CPU')

    scene.cycles.samples = samples
    scene.cycles.use_denoising = False  # Denoising kills small satellite targets
    scene.cycles.use_adaptive_sampling = False

    # Output format
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_depth = '8'
    scene.render.image_settings.compression = 15

    # Enable object index pass for segmentation masks
    scene.view_layers['ViewLayer'].use_pass_object_index = True


# ============================================================
# Frame-by-frame update
# ============================================================

def position_from_row(row, scale=KM_SCALE):
    """Extract position vector (scaled) from CSV row"""
    return Vector((
        row['pos_x_m'] * scale,
        row['pos_y_m'] * scale,
        row['pos_z_m'] * scale
    ))


def quaternion_from_row(row):
    """Extract quaternion from CSV row (qx, qy, qz, qw)"""
    return Quaternion((row['qw'], row['qx'], row['qy'], row['qz']))


def update_frame(obs_row, tgt_row, sun_row, camera, sat_parts, sun_light, sun_target,
                  earth=None, perturb_quat=None, sun_phase_offset=0.0, debug=False):
    """Update scene objects for a single frame.

    Coordinate system: camera at origin. All objects placed relative to camera.
    perturb_quat: optional Quaternion perturbation applied to target attitude.
    sun_phase_offset: rotate sun direction around observer-target axis (degrees).
    """
    obs_pos = position_from_row(obs_row)
    tgt_pos = position_from_row(tgt_row)
    tgt_quat = quaternion_from_row(tgt_row)
    sun_pos = position_from_row(sun_row)

    # Relative positions (camera at origin)
    rel_tgt = tgt_pos - obs_pos
    rel_sun = sun_pos - obs_pos

    if debug:
        print(f"  Frame 0: dist={rel_tgt.length:.1f} km")

    # Camera at origin
    camera.location = Vector((0, 0, 0))
    # Determine pointing direction
    camera_mode = camera.get('camera_mode', 'track')
    if camera_mode == 'stare':
        if camera['stare_dir'] is None:
            d0 = rel_tgt.normalized()
            camera['stare_dir'] = (d0.x, d0.y, d0.z)
            if debug:
                print(f"  Stare boresight set to: ({d0.x:.6f}, {d0.y:.6f}, {d0.z:.6f})")
        sd = camera['stare_dir']
        direction = Vector(sd)
    else:
        direction = rel_tgt.normalized()
    z_axis = -direction
    up = Vector((0, 0, 1))
    if abs(z_axis.dot(up)) > 0.9999:
        up = Vector((1, 0, 0))
    x_axis = up.cross(z_axis).normalized()
    y_axis = z_axis.cross(x_axis).normalized()
    rot = Matrix((
        (x_axis.x, y_axis.x, z_axis.x),
        (x_axis.y, y_axis.y, z_axis.y),
        (x_axis.z, y_axis.z, z_axis.z)
    )).to_4x4()
    camera.matrix_world = rot  # at origin, no translation

    # --- Starfield rotation compensation (celestial fix) ---
    if hasattr(setup_stars, 'mapping_node') and hasattr(setup_stars, 'ref_matrix'):
        mapping = setup_stars.mapping_node
        if setup_stars.ref_matrix is None:
            setup_stars.ref_matrix = rot.copy()
        else:
            R_delta = setup_stars.ref_matrix.inverted() @ rot
            R_comp = R_delta.inverted()
            euler = R_comp.to_3x3().to_euler('XYZ')
            mapping.inputs['Rotation'].default_value = (euler.x, euler.y, euler.z)

    # Satellite parts at relative target position
    # Apply perturbation if provided (data augmentation)
    if perturb_quat is not None:
        effective_quat = tgt_quat @ perturb_quat @ _fbx_model_rot_inv
    else:
        effective_quat = tgt_quat @ _fbx_model_rot_inv
    for part in sat_parts:
        part.location = rel_tgt
        part.rotation_mode = 'QUATERNION'
        part.rotation_quaternion = effective_quat

    # Earth at negative observer position (camera at origin → Earth relative to camera)
    if earth is not None:
        earth.location = -obs_pos

    # Sun light direction (with optional phase offset for augmentation)
    # Rotate sun around the axis perpendicular to camera-target and target-sun,
    # maximizing the change in sun-camera angle for visible lighting variation.
    if sun_phase_offset != 0.0:
        tgt_to_sun = sun_pos - tgt_pos
        rot_axis = rel_tgt.cross(tgt_to_sun).normalized()
        phase_quat = Quaternion(rot_axis, math.radians(sun_phase_offset))
        new_tgt_to_sun = phase_quat @ tgt_to_sun
        sun_dir = (new_tgt_to_sun + rel_tgt).normalized()
    else:
        sun_dir = rel_sun.normalized()
    if debug:
        cam_dir = rel_tgt.normalized()
        angle = math.degrees(math.acos(max(-1, min(1, cam_dir.dot(sun_dir)))))
        print(f"    sun_phase_offset={sun_phase_offset}, sun-camera angle={angle:.1f}°")
    z_sun = sun_dir
    up_sun = Vector((0, 0, 1))
    if abs(z_sun.dot(up_sun)) > 0.9999:
        up_sun = Vector((1, 0, 0))
    x_sun = up_sun.cross(z_sun).normalized()
    y_sun = z_sun.cross(x_sun).normalized()
    rot_sun = Matrix((
        (x_sun.x, y_sun.x, z_sun.x),
        (x_sun.y, y_sun.y, z_sun.y),
        (x_sun.z, y_sun.z, z_sun.z)
    )).to_4x4()
    sun_light.matrix_world = rot_sun
    # Ensure orientation sticks by also setting quaternion directly
    sun_light.rotation_mode = 'QUATERNION'
    sun_light.rotation_quaternion = rot_sun.to_quaternion()
    sun_target.location = Vector((0, 0, 0))

    # Return per-frame influencing factors for the factors CSV annotation:
    # (observer-target distance km, actual sun phase angle deg)
    cam_dir = rel_tgt.normalized()
    sun_ang = math.degrees(math.acos(max(-1.0, min(1.0, cam_dir.dot(sun_dir)))))
    return rel_tgt.length, sun_ang


# ============================================================
# Annotation generation (mask -> COCO/YOLO/pose)
# ============================================================

import numpy as np

DEBUG_MASK = False  # Set True to print per-frame mask pixel statistics

# Instance segmentation: category IDs and per-instance pixel values
COCO_CATEGORIES = [
    {"id": 1, "name": "body", "supercategory": "satellite"},
    {"id": 2, "name": "solar_panel", "supercategory": "satellite"},
    {"id": 3, "name": "phased_array_antenna", "supercategory": "satellite"},
    {"id": 4, "name": "reflector_antenna", "supercategory": "satellite"},
    {"id": 5, "name": "solar_panel_tripod", "supercategory": "satellite"},
]

# Object name prefix -> COCO category ID
CATEGORY_BY_NAME = {
    'body': 1, 'panel': 2, 'antenna_phased': 3, 'antenna_reflector': 4, 'tripod': 5,
}

# Pixel value assignment:
#   1=body, 2-99=panel_N(solar_panel), 100-149=phased_array, 150-199=reflector, 200-249=tripod_N
# Instance numbering is dynamic based on object names


def build_mask_material(name, pixel_value):
    """Pure-color emission encoding instance pixel value in red channel (0-255)."""
    mat = bpy.data.materials.new(name)
    nodes = mat.node_tree.nodes
    nodes.clear()
    emit = nodes.new('ShaderNodeEmission')
    emit.inputs['Color'].default_value = (pixel_value / 255.0, 0.0, 0.0, 1.0)
    emit.inputs['Strength'].default_value = 1.0
    out = nodes.new('ShaderNodeOutputMaterial')
    mat.node_tree.links.new(emit.outputs['Emission'], out.inputs['Surface'])
    return mat


def assign_mask_materials(sat_parts):
    """Swap each label part for mask color. Full model (is_full_model) is hidden;
    label parts are shown and get pure-emission mask materials.
    Star backdrop and Earth are hidden so the mask is pure black + satellite."""
    originals = {}
    # Hide all non-satellite renderable objects (star backdrop, earth) so
    # mask images contain ONLY satellite pixels. Save previous visibility.
    hidden_others = {}
    for obj in bpy.data.objects:
        if obj.type in ('MESH', 'CURVE', 'SURFACE') and obj not in sat_parts:
            hidden_others[obj.name] = obj.hide_render
            obj.hide_render = True

    for part in sat_parts:
        if part.type != 'MESH':
            continue
        if part.get('is_full_model', False):
            # Hide full model during mask render
            part.hide_render = True
        else:
            # Show label part, apply mask material
            part.hide_render = False
            pixval = part.pass_index
            if pixval == 0:
                pixval = 1
            originals[part.name] = [m for m in part.data.materials]
            part.data.materials.clear()
            part.data.materials.append(build_mask_material(f'mask_{part.name}', pixval))
    return originals, hidden_others


def restore_materials(sat_parts, originals, hidden_others=None):
    """Restore beauty materials. Full model is shown; star backdrop/earth restored."""
    # Restore previous visibility of non-satellite objects (star backdrop, earth)
    for obj in bpy.data.objects:
        if obj.type in ('MESH', 'CURVE', 'SURFACE') and obj not in sat_parts:
            if hidden_others is not None and obj.name in hidden_others:
                obj.hide_render = hidden_others[obj.name]
            else:
                obj.hide_render = False

    for part in sat_parts:
        if part.type != 'MESH':
            continue
        if part.get('is_full_model', False):
            # Show full model for beauty render
            part.hide_render = False
        else:
            # Show label part for beauty (completes full model), restore material
            part.hide_render = False
            part.data.materials.clear()
            for m in originals.get(part.name, []):
                part.data.materials.append(m)


def render_mask_image(resolution, samples_backup, tmp_exr_path):
    """
    Render current frame with mask materials at 1 sample into a temp EXR,
    read back as numpy mask (H,W) uint8. EXR preserves scene-linear values.
    """
    scene = bpy.context.scene
    scene.cycles.samples = 1

    # Render to temp EXR (linear floats)
    prev_fmt = scene.render.image_settings.file_format
    prev_depth = scene.render.image_settings.color_depth
    scene.render.image_settings.file_format = 'OPEN_EXR'
    scene.render.image_settings.color_depth = '32'
    scene.render.filepath = tmp_exr_path
    bpy.ops.render.render(write_still=True)
    scene.render.image_settings.file_format = prev_fmt
    scene.render.image_settings.color_depth = prev_depth
    scene.cycles.samples = samples_backup

    img = bpy.data.images.load(tmp_exr_path)
    w, h = img.size
    pixels = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(pixels)
    arr = pixels.reshape(h, w, 4)
    bpy.data.images.remove(img)
    try:
        os.remove(tmp_exr_path)
    except OSError:
        pass

    red = arr[:, :, 0]
    mask = np.flipud(np.rint(red * 255.0).astype(np.uint8))

    # Debug: report mask content (only when DEBUG_MASK enabled)
    if DEBUG_MASK:
        uniq, counts = np.unique(mask, return_counts=True)
        top = sorted(zip(counts, uniq), reverse=True)[:6]
        print(f"  [mask debug] red min/max: {red.min():.4f}/{red.max():.4f}, "
              f"top (val:count): {[(int(u), int(c)) for c, u in top]}")
    return mask


def save_mask_png(mask, filepath, scale=50):
    """Save uint8 mask as 8-bit grayscale PNG (pure stdlib, no Blender image API).
    Values are scaled by `scale` (default 50) so instance IDs 1-5 are visible
    in the PNG (1->50, 2->100, 3->150, ...), capped at 250. 0 stays 0 (background).
    Decode with value // scale (see build_coco.py)."""
    import zlib, struct
    h, w = mask.shape
    # Scale for visibility. Must widen to uint16 first: mask * 50 overflows
    # uint8 (150*50=7500 wraps to 76), corrupting large instance values.
    scaled = np.minimum(mask.astype(np.uint16) * scale, 250).astype(np.uint8)
    mask = scaled
    # PNG signature
    sig = b'\x89PNG\r\n\x1a\n'
    # IHDR: width, height, bitdepth=8, colortype=0 (grayscale), compression=0, filter=0, interlace=0
    ihdr_data = struct.pack('>IIBBBBB', w, h, 8, 0, 0, 0, 0)
    ihdr = struct.pack('>I', len(ihdr_data)) + b'IHDR' + ihdr_data
    ihdr += struct.pack('>I', zlib.crc32(b'IHDR' + ihdr_data) & 0xffffffff)
    # IDAT: each scanline prefixed with filter byte 0
    raw = b''.join(b'\x00' + mask[y].tobytes() for y in range(h))
    idat_data = zlib.compress(raw, 6)
    idat = struct.pack('>I', len(idat_data)) + b'IDAT' + idat_data
    idat += struct.pack('>I', zlib.crc32(b'IDAT' + idat_data) & 0xffffffff)
    # IEND
    iend = struct.pack('>I', 0) + b'IEND' + struct.pack('>I', zlib.crc32(b'IEND') & 0xffffffff)
    with open(filepath, 'wb') as f:
        f.write(sig + ihdr + idat + iend)


def rle_encode(binary_mask):
    """COCO RLE encoding (column-major run-length)."""
    pixels = binary_mask.T.flatten()  # column-major (Fortran order)
    pixels = np.concatenate([[0], pixels, [0]])
    runs = np.where(pixels[1:] != pixels[:-1])[0] + 1
    runs[1::2] -= runs[::2]
    counts = runs.tolist()
    return {"size": list(binary_mask.shape), "counts": counts}


def mask_to_annotations(mask, frame_id, image_filename, ann_id_start):
    """
    Extract per-class annotations from instance mask.
    Returns (coco_image_entry, coco_ann_entries, yolo_lines, next_ann_id).
    """
    h, w = mask.shape
    coco_img = {
        "id": frame_id,
        "file_name": image_filename,
        "width": int(w),
        "height": int(h),
    }
    coco_anns = []
    yolo_lines = []
    ann_id = ann_id_start

    # pixel→category using nearest-neighbor (anti-alias spreads edge pixels)
    KNOWN_PIXELS = [1, 2, 3, 4, 5, 100, 150, 200]
    def pixel_to_category(pix):
        # Find nearest known pixel value
        nearest = min(KNOWN_PIXELS, key=lambda k: abs(k - pix))
        if nearest == 1: return 1
        if 2 <= nearest <= 99: return 2
        if 100 <= nearest <= 149: return 3
        if 150 <= nearest <= 199: return 4
        if 200 <= nearest <= 249: return 5
        return None
    # Only process pixel values actually present (naive 1..255 loop costs
    # 256 full-image comparisons per mask — ~4s each)
    for pixval in np.unique(mask):
        pixval = int(pixval)
        if pixval == 0:
            continue
        cat_id = pixel_to_category(pixval)
        if cat_id is None:
            continue
        binary = (mask == pixval)
        area = int(binary.sum())
        # Category-dependent area filter: small components need lower threshold
        min_area = 2 if cat_id in (3, 4, 5) else 30  # 30px body/panel, 2px antenna/tripod
        if area < min_area:
            continue

        ys, xs = np.nonzero(binary)
        x0, x1 = int(xs.min()), int(xs.max())
        y0, y1 = int(ys.min()), int(ys.max())
        bw, bh = x1 - x0 + 1, y1 - y0 + 1

        coco_anns.append({
            "id": ann_id,
            "image_id": frame_id,
            "category_id": cat_id,
            "bbox": [x0, y0, bw, bh],
            "area": area,
            "segmentation": rle_encode(binary),
            "iscrowd": 0,
        })
        ann_id += 1

        # YOLO: class is 0-based
        yolo_lines.append(
            f"{cat_id - 1} {(x0 + bw/2)/w:.6f} {(y0 + bh/2)/h:.6f} {bw/w:.6f} {bh/h:.6f}"
        )

    return coco_img, coco_anns, yolo_lines, ann_id


def random_cone_quaternion(max_angle_deg):
    """Generate a random quaternion with rotation angle <= max_angle_deg
    around a uniformly random axis (cone sampling)."""
    max_angle = math.radians(max_angle_deg)
    # Uniform random axis on sphere
    z = random.uniform(-1.0, 1.0)
    theta = random.uniform(0.0, 2.0 * math.pi)
    r = math.sqrt(1.0 - z * z)
    axis = Vector((r * math.cos(theta), r * math.sin(theta), z))
    # Random angle within cone
    angle = random.uniform(0.0, max_angle)
    return Quaternion(axis, angle)


def write_pose_file(pose_dir, frame_id, tgt_row, obs_row, perturb_quat=None, var_idx=0):
    qx, qy, qz, qw = tgt_row['qx'], tgt_row['qy'], tgt_row['qz'], tgt_row['qw']
    quat = Quaternion((qw, qx, qy, qz))
    if perturb_quat is not None:
        quat = quat @ perturb_quat
    rx = tgt_row['pos_x_m'] - obs_row['pos_x_m']
    ry = tgt_row['pos_y_m'] - obs_row['pos_y_m']
    rz = tgt_row['pos_z_m'] - obs_row['pos_z_m']
    if var_idx == 0:
        fname = f'frame_{frame_id:04d}.txt'
    else:
        fname = f'frame_{frame_id:04d}_v{var_idx:03d}.txt'
    with open(os.path.join(pose_dir, fname), 'w') as f:
        f.write(f'{quat.x:.8f} {quat.y:.8f} {quat.z:.8f} {quat.w:.8f} '
                f'{rx:.6f} {ry:.6f} {rz:.6f}\n')


# ============================================================
# Main rendering loop
# ============================================================

def main():
    args = parse_args()

    # Load data
    obs_data, tgt_data, sun_data, config = load_all_data(args.ephem_dir)
    fov_deg = args.fov  # command-line overrides config default, default matches
    resolution = args.resolution
    samples = args.samples
    camera_mode = args.camera_mode
    enable_annotations = not args.no_annotations

    # Determine frame range
    start_frame = args.start
    if args.end:
        end_frame = min(args.end, len(obs_data))
    else:
        end_frame = len(obs_data)

    # Apply batch offset
    if args.batch_offset > 0:
        start_frame = args.batch_offset * args.batch_size
        end_frame = min(start_frame + args.batch_size, len(obs_data))

    stride = max(1, args.stride)
    frame_indices = list(range(start_frame, end_frame, stride))
    num_render = len(frame_indices)
    print(f"\nRendering frames {start_frame} to {end_frame-1} stride {stride} ({num_render} frames)")
    print(f"Resolution: {resolution}x{resolution}, Samples: {samples}, FOV: {fov_deg} deg")
    print(f"Annotations: {'ON' if enable_annotations else 'OFF'}")

    # Batch tag: each render batch gets its own subfolder (project rule:
    # never mix frames from different batches in one directory)
    batch_tag = args.tag if args.tag else f'{start_frame}_{end_frame-1}_s{samples}_r{resolution}'

    # Output directories
    if args.output_root:
        output_root = os.path.abspath(args.output_root)
    else:
        ephem_abs = os.path.abspath(args.ephem_dir)
        output_root = os.path.normpath(os.path.dirname(ephem_abs))
    image_dir = os.path.join(output_root, 'images', batch_tag)
    mask_dir = os.path.join(output_root, 'annotations', 'instance_masks', batch_tag)
    pose_dir = os.path.join(output_root, 'annotations', 'pose', batch_tag)
    yolo_dir = os.path.join(output_root, 'annotations', 'yolo', batch_tag)
    coco_dir = os.path.join(output_root, 'annotations')
    for d in [image_dir, mask_dir, pose_dir, yolo_dir, coco_dir]:
        os.makedirs(d, exist_ok=True)
    print(f"Batch tag: {batch_tag}")

    # Clear default scene
    clear_scene()

    # Build scene
    print("\n--- Building Scene ---")
    earth = create_earth()
    sat_parts = create_satellite_model(args.model_scale, args.model_type,
                                       args.fbx_path, args.blend_path)
    camera = setup_camera(fov_deg, resolution, camera_mode)
    sun_light, sun_target = setup_sun()
    setup_stars(camera)
    setup_render(samples, args.render_device)

    bpy.context.scene.camera = camera

    # Annotation accumulators
    coco_images = []
    coco_annotations = []
    ann_id = 1
    factors_rows = []  # per-image influencing factors (distance, sun angle, energy)

    # Render loop — build combination matrix for attitude × sun variations
    num_attitude_vars = max(1, args.frame_variations)
    jitter_deg = args.attitude_jitter_deg

    # Parse sun phase offsets (deduplicated, 0.0 always present as baseline)
    sun_offsets = [0.0]
    if args.sun_phase_offsets:
        for x in args.sun_phase_offsets.split(','):
            val = float(x.strip())
            if val != 0.0 and val not in sun_offsets:
                sun_offsets.append(val)

    # Parse sun energy range
    sun_energy_min, sun_energy_max = 200.0, 200.0  # default
    if args.sun_energy_range:
        parts = [x.strip() for x in args.sun_energy_range.split(',')]
        if len(parts) == 2:
            sun_energy_min, sun_energy_max = float(parts[0]), float(parts[1])

    # Build flat list of (attitude_var_idx, sun_offset_deg) combinations
    # v000 = (0, 0.0) = original attitude + original sun
    combinations = [(0, 0.0)]
    for av in range(num_attitude_vars):
        for so in sun_offsets:
            if av == 0 and so == 0.0:
                continue
            combinations.append((av, so))
    total_combos = len(combinations)

    aug_info = f"{num_attitude_vars} att vars"
    if jitter_deg > 0:
        aug_info += f", jitter={jitter_deg}°"
    if len(sun_offsets) > 1:
        aug_info += f", {len(sun_offsets)} sun phases ({args.sun_phase_offsets})"
    if args.sun_energy_range:
        aug_info += f", sun energy {sun_energy_min}-{sun_energy_max}"
    print(f"\n--- Rendering ({total_combos} combinations/frame: {aug_info}) ---")

    for frame_idx, actual_idx in enumerate(frame_indices):

        obs_row = obs_data[actual_idx]
        tgt_row = tgt_data[actual_idx]
        sun_row = sun_data[actual_idx] if actual_idx < len(sun_data) else sun_data[0]

        for combo_idx, (av, so) in enumerate(combinations):
            # Attitude perturbation
            if jitter_deg > 0.0 and av > 0:
                random.seed(actual_idx * 1000 + av)
                perturb = random_cone_quaternion(jitter_deg)
            else:
                perturb = None

            # Sun phase offset (0.0 = original)
            sun_offset = so

            # Random sun energy within range
            if sun_energy_min != sun_energy_max:
                random.seed(actual_idx * 1000 + combo_idx + 9999)
                sun_light.data.energy = random.uniform(sun_energy_min, sun_energy_max)
            else:
                sun_light.data.energy = 200.0

            # Unique frame ID for annotations
            var_frame_id = actual_idx * 1000 + combo_idx

            # File naming
            if combo_idx == 0:
                fname = f'frame_{actual_idx:04d}'
            else:
                fname = f'frame_{actual_idx:04d}_v{combo_idx:03d}'

            dist_km, sun_angle_deg = update_frame(
                obs_row, tgt_row, sun_row, camera, sat_parts,
                sun_light, sun_target, earth,
                perturb_quat=perturb, sun_phase_offset=sun_offset)

            # 1. Beauty render (RGB)
            output_path = os.path.join(image_dir, f'{fname}.png')
            bpy.context.scene.render.filepath = output_path
            bpy.ops.render.render(write_still=True)

            # 0. Record influencing factors (per-image conditions annotation)
            factors_rows.append({
                'filename': f'{fname}.png',
                'frame_id': actual_idx,
                'variation': combo_idx,
                'distance_km': f'{dist_km:.3f}',
                'sun_phase_angle_deg': f'{sun_angle_deg:.2f}',
                'sun_energy': f'{sun_light.data.energy:.1f}',
            })

            if enable_annotations:
                # 2. Mask render (pure-color, 1 sample)
                originals, hidden_others = assign_mask_materials(sat_parts)
                tmp_exr = os.path.join(mask_dir, f'_tmp_{fname}.exr')
                mask = render_mask_image(resolution, samples, tmp_exr)
                restore_materials(sat_parts, originals, hidden_others)

                # Save mask PNG
                save_mask_png(mask, os.path.join(mask_dir, f'{fname}.png'))

                # 3. Extract annotations from mask
                img_entry, ann_entries, yolo_lines, ann_id = mask_to_annotations(
                    mask, var_frame_id, f'{fname}.png', ann_id)
                coco_images.append(img_entry)
                coco_annotations.extend(ann_entries)

                # Add satellite model class label (full satellite bbox)
                if args.sat_class_id is not None:
                    h, w = mask.shape
                    ys, xs = np.nonzero(mask)
                    if len(xs) > 0:
                        x0, x1 = int(xs.min()), int(xs.max())
                        y0, y1 = int(ys.min()), int(ys.max())
                        bw, bh = x1 - x0 + 1, y1 - y0 + 1
                        yolo_lines.insert(0,
                            f"{args.sat_class_id} {(x0 + bw/2)/w:.6f} {(y0 + bh/2)/h:.6f} {bw/w:.6f} {bh/h:.6f}")

                with open(os.path.join(yolo_dir, f'{fname}.txt'), 'w') as f:
                    f.write('\n'.join(yolo_lines) + ('\n' if yolo_lines else ''))

                # 4. Pose ground truth (with perturbed quaternion)
                write_pose_file(pose_dir, actual_idx, tgt_row, obs_row,
                                perturb_quat=perturb, var_idx=combo_idx)

        # Restore sun energy after all variations for this frame
        sun_light.data.energy = 200.0

        # Progress per original frame
        if frame_idx % 10 == 0 or frame_idx == num_render - 1:
            progress = (frame_idx + 1) / num_render * 100
            print(f"  [{frame_idx + 1}/{num_render}] {progress:.0f}% - Frame {actual_idx}"
                  f" ({total_combos} combos)")

    print(f"\n--- Rendering Complete ---")
    print(f"Images: {image_dir}")

    # Write factors CSV (per-image influencing conditions)
    if factors_rows:
        factors_path = os.path.join(coco_dir, f'factors_{start_frame}_{end_frame-1}.csv')
        with open(factors_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'filename', 'frame_id', 'variation',
                'distance_km', 'sun_phase_angle_deg', 'sun_energy'])
            writer.writeheader()
            writer.writerows(factors_rows)
        print(f"Factors CSV:          {factors_path} ({len(factors_rows)} rows)")

    # Write COCO JSON
    if enable_annotations and coco_images:
        # Detection (bbox only, no segmentation)
        coco_det = {
            "info": {"description": "Satellite rendezvous detection dataset",
                     "version": "1.0"},
            "licenses": [],
            "images": coco_images,
            "annotations": [
                {k: v for k, v in a.items() if k != 'segmentation'}
                for a in coco_annotations
            ],
            "categories": COCO_CATEGORIES,
        }
        det_path = os.path.join(coco_dir, f'coco_detection_{start_frame}_{end_frame-1}.json')
        with open(det_path, 'w') as f:
            json.dump(coco_det, f)

        # Segmentation (with RLE)
        coco_seg = {
            "info": {"description": "Satellite rendezvous instance segmentation dataset",
                     "version": "1.0"},
            "licenses": [],
            "images": coco_images,
            "annotations": coco_annotations,
            "categories": COCO_CATEGORIES,
        }
        seg_path = os.path.join(coco_dir, f'coco_segmentation_{start_frame}_{end_frame-1}.json')
        with open(seg_path, 'w') as f:
            json.dump(coco_seg, f)

        # Train/val split by interval sampling (every 5th frame -> val)
        val_ids = sorted(img['id'] for img in coco_images[::5])
        train_ids = sorted(img['id'] for img in coco_images if img['id'] not in set(val_ids))
        split = {"train": train_ids, "val": val_ids,
                 "rule": "every 5th rendered frame -> val"}
        with open(os.path.join(coco_dir, 'splits.json'), 'w') as f:
            json.dump(split, f)

        print(f"COCO detection:      {det_path} ({len(coco_images)} images, {len(coco_annotations)} anns)")
        print(f"COCO segmentation:   {seg_path}")
        print(f"Instance masks:      {mask_dir}")
        print(f"YOLO labels:         {yolo_dir}")
        print(f"Pose labels:         {pose_dir}")

    print("Done!")


if __name__ == '__main__':
    main()
