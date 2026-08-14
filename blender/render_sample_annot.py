"""Render clean annotation visualization for report sample."""
import bpy, os, math, csv
from mathutils import Vector, Matrix, Quaternion

project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KM_SCALE = 0.001

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

# === Load frame 23386 data ===
ephem_dir = os.path.join(project, 'output', 'ephemeris')
def load_csv(fp):
    rows=[]
    with open(fp) as f:
        for row in csv.DictReader(f): rows.append({k:float(v) for k,v in row.items()})
    return rows
obs_data=load_csv(os.path.join(ephem_dir,'observer_state.csv'))
tgt_data=load_csv(os.path.join(ephem_dir,'target_state.csv'))
sun_data=load_csv(os.path.join(ephem_dir,'sun_state.csv'))
obs=obs_data[23386]; tgt=tgt_data[23386]; sun_r=sun_data[23386]

obs_pos=Vector((obs['pos_x_m']*KM_SCALE,obs['pos_y_m']*KM_SCALE,obs['pos_z_m']*KM_SCALE))
tgt_pos=Vector((tgt['pos_x_m']*KM_SCALE,tgt['pos_y_m']*KM_SCALE,tgt['pos_z_m']*KM_SCALE))
tgt_quat=Quaternion((tgt['qw'],tgt['qx'],tgt['qy'],tgt['qz']))
sun_pos=Vector((sun_r['pos_x_m']*KM_SCALE,sun_r['pos_y_m']*KM_SCALE,sun_r['pos_z_m']*KM_SCALE))
rel_tgt=tgt_pos-obs_pos

# === Load DSP model (same pipeline as render_scene.py) ===
blend_path=os.path.join(project,'output','DSP.blend')
with bpy.data.libraries.load(blend_path,link=False) as (df,dt):
    dt.objects=df.objects
new_objects=[]
for obj in dt.objects:
    if obj is not None:
        bpy.context.collection.objects.link(obj)
        new_objects.append(obj)
for obj in list(new_objects):
    if obj.type in ('CAMERA','LIGHT') or (obj.type=='EMPTY' and 'untitled' in obj.name.lower()):
        bpy.data.objects.remove(obj,do_unlink=True)
        new_objects.remove(obj)
meshes=[o for o in new_objects if o.type=='MESH']

# Unparent + bake + center + km
for obj in meshes:
    if obj.parent:
        obj.select_set(True); bpy.context.view_layer.objects.active=obj
        bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM'); obj.select_set(False)
for obj in list(new_objects):
    if obj.type=='EMPTY': bpy.data.objects.remove(obj,do_unlink=True)
for obj in meshes:
    obj.select_set(True); bpy.context.view_layer.objects.active=obj
    bpy.ops.object.transform_apply(location=True,rotation=True,scale=True); obj.select_set(False)
all_verts=[]
for obj in meshes:
    for v in obj.data.vertices: all_verts.append(obj.matrix_world@v.co)
center=sum(all_verts,Vector((0,0,0)))/len(all_verts)
to_km=Matrix.Scale(KM_SCALE,4)@Matrix.Translation(-center)
for obj in meshes: obj.data.transform(to_km)

# Delete full model, keep only label parts (for clean annotation vis)
digit_names=set(obj.name for obj in meshes if obj.name[0].isdigit())
meshes=[obj for obj in meshes if obj.name not in digit_names]
for name in digit_names:
    obj=bpy.data.objects.get(name)
    if obj: bpy.data.objects.remove(obj,do_unlink=True)

# Bright distinct colors per component
COLORS={
    'body':(0.7,0.7,0.7), 'panel':(0.1,0.3,0.8),
    'reflector':(0.9,0.7,0.2), 'default':(0.5,0.5,0.5),
}
for obj in meshes:
    nl=obj.name.lower()
    if 'panel' in nl: ct='panel'
    elif 'reflector' in nl: ct='reflector'
    elif 'body' in nl: ct='body'
    else: ct='default'
    color=COLORS[ct]
    mat=bpy.data.materials.new(obj.name+'_vis')
    nodes=mat.node_tree.nodes; nodes.clear()
    emit=nodes.new('ShaderNodeEmission')
    emit.inputs['Color'].default_value=(*color,1.0)
    emit.inputs['Strength'].default_value=1.0
    out=nodes.new('ShaderNodeOutputMaterial')
    mat.node_tree.links.new(emit.outputs['Emission'],out.inputs['Surface'])
    obj.data.materials.clear(); obj.data.materials.append(mat)
    obj.hide_render=False

# Camera at origin looking at target
bpy.ops.object.camera_add(location=(0,0,0))
cam=bpy.context.active_object; cam.data.angle=math.radians(0.08)
cam.data.clip_start=0.01; cam.data.clip_end=200000
d=rel_tgt.normalized(); z=-d; up=Vector((0,0,1))
if abs(z.dot(up))>0.9999: up=Vector((1,0,0))
x=up.cross(z).normalized(); y=z.cross(x).normalized()
cam.matrix_world=Matrix(((x.x,y.x,z.x),(x.y,y.y,z.y),(x.z,y.z,z.z))).to_4x4()
bpy.context.scene.camera=cam

# Model at target
for obj in meshes:
    obj.location=rel_tgt; obj.rotation_mode='QUATERNION'
    obj.rotation_quaternion=tgt_quat

# Sun
bpy.ops.object.light_add(type='SUN',location=(0,0,0))
sun=bpy.context.active_object; sun.data.energy=200
sd=(sun_pos-obs_pos).normalized(); z_s=sd; up_s=Vector((0,0,1))
if abs(z_s.dot(up_s))>0.9999: up_s=Vector((1,0,0))
xs=up_s.cross(z_s).normalized(); ys=z_s.cross(xs).normalized()
sun.matrix_world=Matrix(((xs.x,ys.x,z_s.x),(xs.y,ys.y,z_s.y),(xs.z,ys.z,z_s.z))).to_4x4()

# World
nw=bpy.context.scene.world.node_tree.nodes; nw.clear()
bg=nw.new('ShaderNodeBackground'); bg.inputs['Color'].default_value=(0,0,0,1)
ow=nw.new('ShaderNodeOutputWorld')
bpy.context.scene.world.node_tree.links.new(bg.outputs['Background'],ow.inputs['Surface'])

# Render
bpy.context.scene.render.engine='CYCLES'; bpy.context.scene.cycles.samples=32
bpy.context.scene.cycles.use_denoising=False
bpy.context.scene.cycles.use_adaptive_sampling=False
bpy.context.scene.render.resolution_x=2048; bpy.context.scene.render.resolution_y=2048

# Render top view (original attitude)
out=os.path.join(project,'output','sample_images','sample3_annot_vis.png')
bpy.context.scene.render.filepath=out
bpy.ops.render.render(write_still=True)
print(f'Saved: {out}')

# Render side view (apply 60° attitude perturbation around Y axis)
perturb=Quaternion(Vector((0,1,0)),math.radians(60))
for obj in meshes:
    obj.rotation_quaternion=tgt_quat @ perturb
out2=os.path.join(project,'output','sample_images','sample3_annot_side.png')
bpy.context.scene.render.filepath=out2
bpy.ops.render.render(write_still=True)
print(f'Saved: {out2}')
