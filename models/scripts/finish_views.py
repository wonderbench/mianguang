from pathlib import Path
import bpy, math, json, os
from mathutils import Vector
ROOT = str(Path(__file__).resolve().parents[1])
s=bpy.data.scenes['SleepRadar_01_Desk']
if bpy.context.window:bpy.context.window.scene=s
s.view_settings.exposure=-.7
diff=bpy.data.materials['SR01_Opal_PC_Diffuser']
next(n for n in diff.node_tree.nodes if n.type=='BSDF_PRINCIPLED').inputs['Emission Strength'].default_value=3
# Smooth curved walls while leaving planar front surfaces crisp.
for o in s.objects:
    if o.type=='MESH':
        for p in o.data.polygons:
            if abs(p.normal.y)<.99 and len(p.vertices)==4:p.use_smooth=True
        for m in o.modifiers:
            if m.type=='BEVEL':m.harden_normals=True

def clone(src,name):
    dst=bpy.data.scenes.new(name)
    dst.unit_settings.system='METRIC';dst.unit_settings.length_unit='MILLIMETERS'
    dst.render.engine='CYCLES';dst.cycles.samples=48;dst.cycles.use_denoising=True
    dst.render.resolution_x=1500;dst.render.resolution_y=1500;dst.render.resolution_percentage=100
    dst.render.image_settings.file_format='PNG';dst.view_settings.view_transform='AgX';dst.view_settings.exposure=-.7
    dst.world=src.world
    lookup={};cols={}
    for coll in src.collection.children:
        nc=bpy.data.collections.new(name+'_'+coll.name)
        dst.collection.children.link(nc);nc.hide_render=coll.hide_render;nc.hide_viewport=coll.hide_viewport;cols[coll.name.split('.')[0]]=nc
        for o in coll.objects:
            no=o.copy();nc.objects.link(no);lookup[o]=no
    for old,new in lookup.items():
        if old.parent:
            new.parent=lookup.get(old.parent)
            new.matrix_parent_inverse=old.matrix_parent_inverse.copy()
    dst.camera=lookup[src.camera]
    dst.camera.data=src.camera.data.copy()
    return dst,lookup,cols

def point(cam,p):cam.rotation_euler=(Vector(p)-cam.location).to_track_quat('-Z','Y').to_euler()
root=bpy.data.objects['SR01_AIM_PIVOT_Adjust_X']
rear,l,c=clone(s,'SleepRadar_02_Rear')
rear.camera.location=(-.24,.38,.21);point(rear.camera,(0,.015,.08));rear.camera.data.ortho_scale=.235
rear.render.filepath=ROOT+'/renders/02_rear.png'

wall,l,c=clone(s,'SleepRadar_03_Wall_45deg')
l[root].rotation_euler[0]=math.radians(45)
c['SR01_03_Desk_Stand'].hide_render=True;c['SR01_03_Desk_Stand'].hide_viewport=True
c['SR01_04_Wall_Mount'].hide_render=False;c['SR01_04_Wall_Mount'].hide_viewport=False
wall.camera.location=(.25,-.32,.18);point(wall.camera,(0,.02,.085));wall.camera.data.ortho_scale=.235
wall.render.filepath=ROOT+'/renders/03_wall_45deg.png'
# Wall surface makes the standoff and downward aiming visible.
floor=next(o for o in wall.objects if 'Studio_Floor' in o.name)
wallmesh=floor.copy();wallmesh.data=floor.data.copy();c['SR01_06_Studio'].objects.link(wallmesh)
wallmesh.name='SR01_Wall_Reference_Plane';wallmesh.location=(0,.086,.12);wallmesh.rotation_euler[0]=math.pi/2

exp,l,c=clone(s,'SleepRadar_04_Exploded')
l[root].rotation_euler[0]=0
c['SR01_03_Desk_Stand'].hide_render=True;c['SR01_03_Desk_Stand'].hide_viewport=True
c['SR01_04_Wall_Mount'].hide_render=True;c['SR01_04_Wall_Mount'].hide_viewport=True
frontnames=['02_Front','03_Light','Lux_Lens','Status_Lightpipe','Front_Mark','White_Cover']
rearnames=['01_Rear','06_Rear_Dock','Dock_Screw','USB_Label']
for old,new in l.items():
    if any(t in old.name for t in frontnames):new.location+=Vector((-.052,-.050,0))
    elif any(t in old.name for t in rearnames):new.location+=Vector((.050,.044,0))
    elif any(old in list(cc.objects) for cc in s.collection.children if cc.name.startswith('SR01_02_Electronics_Envelopes')):new.location+=Vector((0,-.009,0))
    elif '04_Top_Key' in old.name or 'Key_Mark' in old.name or 'Key_Gap' in old.name:new.location+=Vector((.050,.044,.025))
exp.camera.location=(.28,-.48,.30);point(exp.camera,(0,.005,.081));exp.camera.data.ortho_scale=.355
exp.render.filepath=ROOT+'/renders/04_exploded.png'
if bpy.context.window:bpy.context.window.scene=s
bpy.ops.wm.save_as_mainfile(filepath=ROOT+'/Sleep_Radar_Nightlight_Concept.blend',compress=True)
result={'scenes':[a.name for a in [s,rear,wall,exp]],'blend':ROOT+'/Sleep_Radar_Nightlight_Concept.blend'}
