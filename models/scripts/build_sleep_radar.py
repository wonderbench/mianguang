"""Build an isolated, editable Blender concept for a C1001 sleep radar/nightlight.
Run with Blender --background --python on an isolated project copy. Units below are mm.
Never deletes or overwrites other project scenes. Outputs prototype geometry only.
"""
from pathlib import Path
import bpy, bmesh, math, json, os, struct
from mathutils import Vector, Matrix

ROOT = str(Path(__file__).resolve().parents[1])
os.makedirs(ROOT + '/renders', exist_ok=True)
os.makedirs(ROOT + '/stl', exist_ok=True)
PREFIX = 'SR01_'
scene = bpy.data.scenes.new('SleepRadar_01_Desk')
if bpy.context.window:
    bpy.context.window.scene = scene
scene.unit_settings.system = 'METRIC'
scene.unit_settings.length_unit = 'MILLIMETERS'
scene.unit_settings.scale_length = 1.0
scene['stage'] = 'Mechanical concept for prototype; fit and RF performance unverified'
scene['dimensions_mm'] = 'Body 100W x 116H x 44D; PCB 66 x 56; C1001 22 x 22'
scene['radome_note'] = '1.6 mm nonmetal polymer starting sample; measure RF loss'
scene['mount_note'] = 'Target 0 to 45 deg downward wall aim; table location requires validation'

def collection(name):
    c = bpy.data.collections.new(PREFIX + name)
    scene.collection.children.link(c)
    return c

bodycol = collection('01_Enclosure')
eleccol = collection('02_Electronics_Envelopes')
standcol = collection('03_Desk_Stand')
wallcol = collection('04_Wall_Mount')
refcol = collection('05_Reference')
studiocol = collection('06_Studio')

def move_to(obj, coll):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    coll.objects.link(obj)
    return obj

def mat(name, color, roughness=.4, metal=0., emission=None, strength=0.):
    m = bpy.data.materials.new(PREFIX + name)
    m.diffuse_color = (*color, 1)
    m.use_nodes = True
    bs = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    bs.inputs['Base Color'].default_value = (*color, 1)
    bs.inputs['Roughness'].default_value = roughness
    bs.inputs['Metallic'].default_value = metal
    if emission:
        bs.inputs['Emission Color'].default_value = (*emission, 1)
        bs.inputs['Emission Strength'].default_value = strength
    return m

white = mat('Warm_Matte_White_PC_ABS', (.86,.875,.875), .31)
radome = mat('Unfilled_White_Polymer_RF_Sample', (.91,.925,.92), .38)
diffuser = mat('Opal_PC_Diffuser', (.95,.76,.49), .48, emission=(1,.59,.22), strength=1.25)
rubber = mat('Silicone_Stone', (.22,.26,.27), .75)
black = mat('Dark_Port', (.025,.032,.035), .5)
pcbmat = mat('Green_PCB', (.018,.19,.14), .44)
gold = mat('Contact_Gold', (.68,.43,.12), .25, .65)
metal = mat('Stainless_Hardware', (.37,.41,.43), .23, .8)
labelmat = mat('Warm_Grey_Marking', (.32,.38,.38), .52)
statusmat = mat('Muted_Status_LED', (.12,.35,.27), .4, emission=(.2,.65,.42), strength=.5)
stagemat = mat('Studio_Sand', (.61,.64,.64), .72)

def apply(obj, modifier):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=modifier.name)

def bevel(obj, mm=.3, seg=3, apply_now=False):
    m = obj.modifiers.new('Edge softening', 'BEVEL')
    m.width = mm/1000
    m.segments = seg
    if apply_now:
        apply(obj,m)
    return obj

def rr(name, w, h, d, r, loc, material, coll=bodycol, edge=.15):
    points=[]
    for cx,cz,a0 in [(w/2-r,h/2-r,0),(-w/2+r,h/2-r,90),(-w/2+r,-h/2+r,180),(w/2-r,-h/2+r,270)]:
        for i in range(13):
            a=math.radians(a0+i*90/12)
            points.append((cx+r*math.cos(a),cz+r*math.sin(a)))
    n=len(points)
    verts=[(x/1000,y/1000,z/1000) for y in [-d/2,d/2] for x,z in points]
    faces=[tuple(reversed(range(n))),tuple(range(n,2*n))]
    faces += [(i,(i+1)%n,(i+1)%n+n,i+n) for i in range(n)]
    mesh=bpy.data.meshes.new(PREFIX+name+'_mesh')
    mesh.from_pydata(verts,[],faces)
    mesh.update()
    obj=bpy.data.objects.new(PREFIX+name,mesh)
    coll.objects.link(obj)
    obj.location=Vector(loc)/1000
    if material: obj.data.materials.append(material)
    bm=bmesh.new();bm.from_mesh(mesh);bmesh.ops.recalc_face_normals(bm,faces=bm.faces);bm.to_mesh(mesh);bm.free()
    if edge: bevel(obj,edge)
    return obj

def box(name, dims, loc, material, coll=bodycol, edge=.4):
    bpy.ops.mesh.primitive_cube_add(size=1,location=Vector(loc)/1000)
    obj=bpy.context.object;obj.name=PREFIX+name
    obj.dimensions=Vector(dims)/1000
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    move_to(obj,coll)
    if material:obj.data.materials.append(material)
    if edge:bevel(obj,edge)
    return obj

def cyl(name,radius,depth,loc,material,coll=bodycol,axis='Y',edge=.15):
    bpy.ops.mesh.primitive_cylinder_add(vertices=64,radius=radius/1000,depth=depth/1000,location=Vector(loc)/1000)
    obj=bpy.context.object;obj.name=PREFIX+name
    if axis=='Y':obj.rotation_euler[0]=math.pi/2
    if axis=='X':obj.rotation_euler[1]=math.pi/2
    bpy.ops.object.transform_apply(location=False,rotation=True,scale=True)
    move_to(obj,coll)
    if material:obj.data.materials.append(material)
    if edge:bevel(obj,edge)
    return obj

def boolean(obj,cut,op='DIFFERENCE'):
    for m in list(obj.modifiers):apply(obj,m)
    for m in list(cut.modifiers):apply(cut,m)
    m=obj.modifiers.new('Prototype '+op,'BOOLEAN');m.operation=op;m.solver='EXACT';m.object=cut
    apply(obj,m)
    bpy.data.objects.remove(cut,do_unlink=True)

parts=[]
shell=rr('01_Rear_Tub',100,116,44,14,(0,0,84),white,edge=0)
cut=rr('CUT_inner',95.2,111.2,45,11.6,(0,-3,84),None,edge=0)
boolean(shell,cut)
# Rear lower USB panel opening; connector is a separate wired 5 V input board.
cut=rr('CUT_usb',11.4,5.8,8,2.5,(-27,22,42),None,edge=0)
boolean(shell,cut)
# Four rear cover screws and PCB standoffs are outside the antenna projection.
for x in [-28,28]:
    for z in [55,101]:
        boss=cyl('PCB_boss',3.5,9.0,(x,15.5,z),None,edge=0)
        boolean(shell,boss,'UNION')
        hole=cyl('PCB_pilot',1.1,12,(x,15,z),None,edge=0)
        boolean(shell,hole)
for x in [-39,39]:
    for z in [40,128]:
        boss=cyl('Cover_boss',3.4,42.4,(x,-.3,z),None,edge=0)
        boolean(shell,boss,'UNION')
        hole=cyl('Cover_pilot',1.1,45,(x,0,z),None,edge=0)
        boolean(shell,hole)
bevel(shell,.25)
parts.append(shell)

face=rr('02_Front_Radome_Frame',96,112,1.6,12,(0,-22.3,84),radome,edge=0)
cut=rr('CUT_light',78.6,24.6,5,10.3,(0,-22.3,50),None,edge=0)
boolean(face,cut)
cut=cyl('CUT_lux',1.6,5,(33,-22.3,72),None,edge=0)
boolean(face,cut)
for x in [-39,39]:
    for z in [40,128]:
        cut=cyl('CUT_cover_screw',1.4,5,(x,-22.3,z),None,edge=0)
        boolean(face,cut)
        cyl('White_Cover_Screw_Head',2.5,.7,(x,-23.3,z),white,edge=.25)
bevel(face,.18)
face['material_requirement']='Nonmetal, unfilled polymer; no metallized paint or conductive coating'
face['radome_nominal_mm']=1.6
face['status']='Starting experiment only: compare 1.0 / 1.6 / 2.2 mm samples and antenna gaps'
parts.append(face)
lightwindow=rr('03_Light_Diffuser',78,24,2.0,10,(0,-22.1,50),diffuser,edge=.25)
parts.append(lightwindow)
lux=cyl('Lux_Lens',1.35,1.6,(33,-22.5,72),black,edge=.08)
status=cyl('Status_Lightpipe',.65,1.5,(0,-22.7,72),statusmat,edge=.05)
# Large top mechanical key: present as separate part pending switch/retention development.
key=box('04_Top_Key_22x12',(22,12,2.2),(0,-2,142.4),white,edge=1.0)
key['status']='Key retention and switch actuator require detail design'
parts.append(key)
slot=box('Key_Gap',(23,13,1),(0,-2,141.7),rubber,edge=.5)
# Tiny, recessed front mark below the light window.
def text_obj(name,text,loc,size,material,rotation=(math.pi/2,0,0),coll=bodycol):
    c=bpy.data.curves.new(PREFIX+name,'FONT');c.body=text;c.align_x='CENTER';c.size=size/1000;c.space_character=1.35;c.extrude=.015/1000
    o=bpy.data.objects.new(PREFIX+name,c);coll.objects.link(o);o.location=Vector(loc)/1000;o.rotation_euler=rotation;c.materials.append(material);return o
text_obj('Front_Mark','S L E E P',(0,-23.18,33),2.0,labelmat)
text_obj('Key_Mark','○',(0,-2,143.55),3,labelmat,rotation=(0,0,0))

# Carrier and component envelopes are dimensioned placeholders, not native PCB export.
pcb=rr('Carrier_PCB_66x56_ENVELOPE',66,56,1.6,2,(0,10.2,78),pcbmat,eleccol,edge=0)
for x in [-28,28]:
    for z in [55,101]:
        cut=cyl('CUT_mount',1.4,4,(x,10.2,z),None,eleccol,edge=0);boolean(pcb,cut)
pcb['status']='Mechanical carrier envelope only; replace with reviewed EDA export'
xiao=rr('XIAO_ESP32C3_21x17p8',21,17.8,1.6,1,(-12,6.5,88),pcbmat,eleccol,edge=.1)
box('ESP32_RF_Can',(13,2.6,12),(-12,4.6,88),metal,eleccol,.25)
for z in [80.4,82.94,85.48,88.02,90.56,93.10,95.64]:
    for x in [-21.6,-2.4]:box('XIAO_Header',(1,2,1),(x,5,z),gold,eleccol,.05)
for x,z in [(21,87),(21,71),(-17,62)]:
    box('Connector_ENVELOPE',(10,6,7),(x,6,z),white,eleccol,.5)
radar=rr('C1001_PCB_22x22_ENVELOPE',22,22,1.2,1,(0,-11,115),pcbmat,eleccol,edge=.1)
radar['source']='DFRobot official SEN0623 drawing and JQC1001.step; outline 22 x 22 mm'
radar['status']='Approximate component model: verify populated height and exact holes from STEP'
box('C1001_Antenna_Keepclear_FACE',(12,.2,16),(3,-11.8,115),radome,eleccol,.1)
for z in [108.65,111.19,113.73,116.27,118.81,121.35]:
    cyl('C1001_2p54_Pad',.7,.15,(-8.5,-11.7,z),gold,eleccol,edge=0)
radartray=rr('05_Radar_Tray',30,30,2,3,(0,-6.5,115),white,edge=.2)
radartray['status']='Replaceable tray envelope; retention holes to match official STEP before print assembly'
parts.append(radartray)
ledboard=rr('Nightlight_PCB_ENVELOPE',65,9,1,1,(0,-13.5,50),pcbmat,eleccol,edge=.1)
for x in [-24,-12,0,12,24]:box('Warm_LED',(3,.8,3),(x,-14.4,50),diffuser,eleccol,.15)
usbpcb=rr('USB_C_Input_Board_ENVELOPE',18,12,1.6,1,(-27,16,42),pcbmat,eleccol,edge=.2)
usb=rr('USB_C_Metal_Receptacle',9.2,3.4,6,1.65,(-27,20,42),metal,eleccol,edge=.1)
usbcut=rr('CUT_usb_mouth',7.8,2.3,7,1.05,(-27,21,42),None,eleccol,edge=0)
boolean(usb,usbcut)
rr('USB_C_Center_Tongue',6.2,.65,4,.25,(-27,21,42),black,eleccol,edge=.03)
text_obj('USB_Label','5V  USB-C',(-27,22.3,35),1.6,labelmat,rotation=(math.pi/2,0,math.pi))

# Two-stage dock is shared by desk riser and wall standoff.
dock=rr('06_Rear_Dock',44,36,4,6,(0,24,84),white,edge=.3)
for x in [-16,16]:
    cut=cyl('Dock_hole',1.65,7,(x,24,84),None,edge=0);boolean(dock,cut)
parts.append(dock)
for x in [-16,16]:
    cyl('Dock_Screw',2.8,1.1,(x,26.7,84),metal,edge=.1)
hinge=cyl('Pivot_Bar',6.5,52,(0,29,84),white,standcol,axis='X',edge=.4)
for x in [-27,27]:cyl('Pivot_Cap',6.2,2,(x,29,84),white,standcol,axis='X',edge=.35)
stand=box('07_Desk_Riser',(18,14,75),(0,29,46),white,standcol,edge=3)
parts.append(stand)
base=rr('08_Desk_Base',94,78,7,20,(0,10,4.5),white,standcol,edge=.7)
base.rotation_euler[0]=math.pi/2
bpy.context.view_layer.update()
parts.append(base)
for x in [-30,30]:
    for y in [-12,31]:cyl('Anti_Slip_Foot',5.5,1.4,(x,y,.7),rubber,standcol,axis='Z',edge=.25)
wallplate=rr('09_Wall_Plate',68,88,5,10,(0,80,84),white,wallcol,edge=.3)
for z in [56,112]:
    big=cyl('Keyhole_entry',4.2,10,(0,80,z),None,wallcol,edge=0);boolean(wallplate,big)
    stem=rr('Keyhole_stem',4.4,10,10,2.1,(0,80,z+4.2),None,wallcol,edge=0);boolean(wallplate,stem)
parts.append(wallplate)
wallarm=box('10_Wall_Standoff',(20,50,16),(0,52,84),white,wallcol,edge=3)
parts.append(wallarm)
cyl('Wall_Pivot',6.5,52,(0,29,84),white,wallcol,axis='X',edge=.4)
for x in [-27,27]:cyl('Wall_Pivot_Cap',6.2,2,(x,29,84),white,wallcol,axis='X',edge=.35)
wallcol.hide_render=True
wallcol.hide_viewport=True

root=bpy.data.objects.new(PREFIX+'AIM_PIVOT_Adjust_X',None)
bodycol.objects.link(root);root.location=Vector((0,29,84))/1000;root.empty_display_size=.015
bpy.context.view_layer.update()
for coll in [bodycol,eleccol]:
    for o in list(coll.objects):
        if o!=root:
            o.parent=root;o.matrix_parent_inverse=root.matrix_world.inverted()
bpy.context.view_layer.update()
root['aim_range_deg']='Prototype target: 0 to +45 deg downward; physical travel/retention not tested'

# Export triangulated single-part meshes in mm at neutral pose; check topology.
report=[]
for o in parts:
    deps=bpy.context.evaluated_depsgraph_get();eo=o.evaluated_get(deps);mesh=eo.to_mesh()
    bm=bmesh.new();bm.from_mesh(mesh)
    bmesh.ops.triangulate(bm,faces=list(bm.faces));bm.normal_update()
    nonmanifold=sum(not e.is_manifold for e in bm.edges)
    volume=bm.calc_volume(signed=False)*1e9
    bounds=[o.matrix_world@v.co for v in bm.verts]
    minv=Vector([min(v[i] for v in bounds) for i in range(3)])
    maxv=Vector([max(v[i] for v in bounds) for i in range(3)])
    # Ground each local part for slicer import; preserve X/Y orientation.
    tris=[]
    for f in bm.faces:
        vs=[o.matrix_world@v.co for v in f.verts]
        normal=(vs[1]-vs[0]).cross(vs[2]-vs[0]).normalized()
        ps=[(v-Vector((0,0,minv.z)))*1000 for v in vs]
        tris.append((*normal,*(c for p in ps for c in p)))
    path=ROOT+'/stl/'+o.name+'.stl'
    with open(path,'wb') as f:
        f.write(b'Prototype mesh mm; NOT manufacturing release'.ljust(80,b' '))
        f.write(struct.pack('<I',len(tris)))
        for tri in tris:f.write(struct.pack('<12fH',*tri,0))
    report.append({'part':o.name,'stl':os.path.relpath(path,ROOT),'nonmanifold_edges':nonmanifold,'mesh_volume_mm3':round(volume,2),'bounding_box_mm':[round(x*1000,3) for x in maxv-minv],'status':'Closed manifold mesh; mechanical fit unverified' if nonmanifold==0 else 'Topology requires repair'})
    bm.free();eo.to_mesh_clear()
with open(ROOT+'/mesh_checks.json','w') as f:json.dump(report,f,indent=2)

# Studio: muted architectural palette, large soft light, physically scaled device.
ground=box('Studio_Floor',(2000,2000,2),(0,0,-2),stagemat,studiocol,edge=0)
def track(o,point):o.rotation_euler=(Vector(point)-o.location).to_track_quat('-Z','Y').to_euler()
def area(name,loc,energy,size,color):
    d=bpy.data.lights.new(PREFIX+name,'AREA');d.energy=energy;d.shape='DISK';d.size=size;d.color=color
    o=bpy.data.objects.new(PREFIX+name,d);studiocol.objects.link(o);o.location=loc;track(o,(0,0,.08));return o
area('Key_Softbox',(.15,-.23,.40),14,.30,(1,.94,.86))
area('Fill_Softbox',(-.24,-.06,.23),6,.25,(.84,.92,1))
area('Rim_Softbox',(.07,.23,.36),18,.22,(1,1,1))
world=bpy.data.worlds.new(PREFIX+'Studio_World');world.use_nodes=True;bg=next(n for n in world.node_tree.nodes if n.type=='BACKGROUND');bg.inputs[0].default_value=(.57,.63,.65,1);bg.inputs[1].default_value=.35;scene.world=world
camd=bpy.data.cameras.new(PREFIX+'Hero_Camera');cam=bpy.data.objects.new(PREFIX+'Hero_Camera',camd);studiocol.objects.link(cam)
cam.location=(.23,-.34,.21);track(cam,(0,.005,.073));camd.type='ORTHO';camd.ortho_scale=.235;camd.lens=60;scene.camera=cam
scene.render.engine='CYCLES';scene.cycles.samples=48;scene.cycles.use_denoising=True
scene.render.resolution_x=1500;scene.render.resolution_y=1500;scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG';scene.render.film_transparent=False
scene.view_settings.view_transform='AgX'
scene.render.filepath=ROOT+'/renders/01_hero.png'
root.rotation_euler[0]=math.radians(-5)
bpy.context.view_layer.update()
for area_ in bpy.context.screen.areas if bpy.context.screen else []:
    if area_.type=='VIEW_3D':
        area_.spaces.active.region_3d.view_perspective='CAMERA'
        area_.spaces.active.clip_end=100

# Write only this project's scene and its dependencies, leaving the user's prior file intact.
bpy.data.libraries.write(ROOT+'/Sleep_Radar_Nightlight_Concept.blend',{scene},fake_user=True,compress=True)
result={'scene':scene.name,'objects':len(scene.objects),'blend':ROOT+'/Sleep_Radar_Nightlight_Concept.blend','parts':report,'existing_scenes_preserved':True}
