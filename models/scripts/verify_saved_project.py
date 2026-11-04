from pathlib import Path
import bpy, bmesh, json, os, struct
ROOT = str(Path(__file__).resolve().parents[1])
project=[s for s in bpy.data.scenes if s.name.startswith('SleepRadar_')]
# This script is used only in a standalone project/background process.
if bpy.app.background:
    for s in list(bpy.data.scenes):
        if s not in project and len(s.objects)<=3:
            bpy.data.scenes.remove(s)
if bpy.context.window:bpy.context.window.scene=bpy.data.scenes['SleepRadar_01_Desk']
summary={'blender_version':bpy.app.version_string,'file':'Sleep_Radar_Nightlight_Concept.blend','file_path_base':'models directory','scenes':[],'missing_external_assets':[],'scope':'Geometry and file checks only; assembly and RF not validated'}
for s in project:
    if bpy.context.window:bpy.context.window.scene=s
    bpy.context.view_layer.update()
    body=next(o for o in s.objects if '01_Rear_Tub' in o.name)
    summary['scenes'].append({'name':s.name,'objects':len(s.objects),'camera':s.camera.name if s.camera else None,'body_center_mm':[round(c*1000,3) for c in body.matrix_world.translation]})
for im in bpy.data.images:
    if im.filepath and not im.packed_file and im.source=='FILE' and not os.path.exists(bpy.path.abspath(im.filepath)):
        summary['missing_external_assets'].append(im.filepath)
checks=json.load(open(ROOT+'/mesh_checks.json'))
for r in checks:
    data=open(ROOT+'/'+r['stl'],'rb').read();n=struct.unpack_from('<I',data,80)[0]
    r['stl_triangles']=n;r['binary_size_valid']=len(data)==84+50*n
assert len(project)==4 and all(s.camera for s in project)
assert len(checks)==10 and all(r['nonmanifold_edges']==0 and r['binary_size_valid'] for r in checks)
assert not summary['missing_external_assets']
json.dump(checks,open(ROOT+'/mesh_checks.json','w'),indent=2)
json.dump(summary,open(ROOT+'/project_checks.json','w'),indent=2)
if bpy.context.window:bpy.context.window.scene=bpy.data.scenes['SleepRadar_01_Desk']
bpy.ops.wm.save_as_mainfile(filepath=ROOT+'/Sleep_Radar_Nightlight_Concept.blend',compress=True)
print(json.dumps(summary,indent=2))
