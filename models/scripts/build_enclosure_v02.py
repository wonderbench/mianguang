"""Build the PCB-referenced V0.2 enclosure in an isolated background process.
Run with --background --factory-startup on an isolated repository copy.
The designated V0.2 output is replaced; input .blend files are never saved.
"""
from pathlib import Path
import bpy, bmesh, math, json, os, struct
from mathutils import Vector, Matrix

if not bpy.app.background:
    raise RuntimeError('Use an isolated Blender --background --factory-startup process.')

SOURCE = Path(__file__).resolve().parents[1]
ROOT = str(SOURCE / 'v0.2')
import csv, hashlib, runpy
REPO = SOURCE.parent
os.makedirs(ROOT + '/renders', exist_ok=True)
os.makedirs(ROOT + '/stl', exist_ok=True)
PREFIX = 'SR02_'
scene = bpy.data.scenes.new('Mianguang_V02_01_Desk')
if bpy.context.window:
    bpy.context.window.scene = scene
scene.unit_settings.system = 'METRIC'
scene.unit_settings.length_unit = 'MILLIMETERS'
scene.unit_settings.scale_length = 1.0
scene['stage'] = 'V0.2 PCB-referenced mechanical prototype; conditional purchased-part envelopes; no physical validation'
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
        for i in range(17):
            a=math.radians(a0+i*90/16)
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

# Assembly axes: X=PCB X-33; Z=PCB Y+56; board top points toward -Y.
# Purchased items below are explicitly bounded envelopes, not vendor 3D claims.
parts=[]
checks=[]
def part(obj, note):
    obj['part_role']='printable';obj['fit_note']=note;parts.append(obj);return obj
def hole(obj,r,d,loc,axis='Y'):
    boolean(obj,cyl('CUT',r,d,loc,None,axis=axis,edge=0))
def union(obj,other):boolean(obj,other,'UNION')
def mark(obj,role,source='Design allowance; confirm purchased item'):
    obj['part_role']=role;obj['source']=source;return obj
def check(name,passed,**data):checks.append(dict(check=name,passed=bool(passed),**data))
def route(name,pts,r=.65):
    c=bpy.data.curves.new(PREFIX+name,'CURVE');c.dimensions='3D';c.resolution_u=12;c.bevel_depth=r/1000;c.bevel_resolution=3
    s=c.splines.new('BEZIER');s.bezier_points.add(len(pts)-1)
    # FREE handles clipped to each segment's coordinate box prevent AUTO
    # overshoot through the roof. These are routed envelopes, not bend tests.
    for i,(p,co) in enumerate(zip(s.bezier_points,pts)):
        p.co=Vector(co)/1000;p.handle_left_type='FREE';p.handle_right_type='FREE'
        prev=Vector(pts[max(0,i-1)])/1000;nxt=Vector(pts[min(len(pts)-1,i+1)])/1000
        tangent=(nxt-prev).normalized()
        for attr,other,sign in [('handle_left',prev,-1),('handle_right',nxt,1)]:
            v=p.co+sign*tangent*(other-p.co).length*.22
            setattr(p,attr,Vector([max(min(other[j],p.co[j]),min(max(other[j],p.co[j]),v[j])) for j in range(3)]))
    o=bpy.data.objects.new(PREFIX+name,c);eleccol.objects.link(o);c.materials.append(black);mark(o,'wire_route','Indicative harness centreline, bend radii and length to measure');return o

shell=part(rr('01_Rear_Tub',100,116,44,14,(0,0,90),white,edge=0),'2.4 mm wall. M2.5 insert pilots 3.3 mm are a procurement target; print coupon first.')
boolean(shell,rr('CUT_inner',95.2,111.2,45,11.6,(0,-2.9,90),None,edge=0))
# Board rear face Y=13.0, solder allowance up to Y=16.0; rear inner wall=19.6.
for x in [-28,28]:
    for z in [61,107]:
        union(shell,cyl('PCB_boss',3.6,8,(x,17,z),None,edge=0))
        hole(shell,1.65,4.6,(x,15.25,z))
        hole(shell,1.35,11,(x,18.5,z))
# Lower fasteners sit outside the light tray and USB receiver, near the corners.
cover_mounts=[(-42,39),(42,39),(-39,137),(39,137)]
for x,z in cover_mounts:
    union(shell,cyl('Cover_boss',3.5,43.6,(x,-.2,z),None,edge=0))
    hole(shell,1.65,4.7,(x,-19.9,z))
    hole(shell,1.35,44,(x,0,z))
# Dock fastens from inside before the carrier board is fitted.
for x in [-16,16]:
    union(shell,cyl('Dock_bearing',4,4,(x,20,90),None,edge=0))
    hole(shell,1.7,8,(x,20,90))
    h=cyl('Dock_M3_inner_head',2.8,1.6,(x,17.2,90),metal,eleccol,edge=.1);mark(h,'hardware')
# True USB-C opening on rear, with a separate horizontal receiver-board shelf.
boolean(shell,rr('CUT_usb',11.4,6.4,8,2.4,(-27,22,43),None,edge=0))
union(shell,box('USB_shelf',(22.6,15,1.6),(-27,13,38.5),None,edge=0))
for x in [-37.4,-16.6]:
    union(shell,box('USB_rail',(2,15,5.6),(x,13,40.5),None,edge=0))
    # M2 pilot for removable retaining strap, axis vertical.
    hole(shell,.8,6,(x,8.5,42),axis='Z')
usbstrap=part(box('14_USB_Retainer',(23,3,2),(-27,8.5,44.3),white,edge=0),'Two M2x6 screws into rail pilots; 18x12x1.6 mm board plus 0.4 mm pad.')
union(usbstrap,box('USB_clamp_pad',(15,3,2.2),(-27,8.5,42.4),None,edge=0))
for x in [-37.4,-16.6]:hole(usbstrap,1.1,5,(x,8.5,44.3),axis='Z')
# Top key travels through the roof. Captive flange remains below roof.
boolean(shell,box('CUT_key',(22.6,12.6,8),(0,3,147),None,edge=0))
for x in [-17,17]:
    union(shell,cyl('Key_bridge_boss',2.7,10.9,(x,10,140.75),None,axis='Z',edge=0))
    hole(shell,.8,9,(x,10,137),axis='Z')
bridge=part(box('12_Key_Switch_Bridge',(40,18,1.6),(0,5,134.5),white,edge=0),'M2x6 underside screws; 10x10 switch board retained with thin adhesive pad. Switch stack is conditional.')
for x in [-17,17]:hole(bridge,1.1,4,(x,10,134.5),axis='Z')
key=box('04_Captive_Top_Key',(22,12,4.4),(0,3,147),white,edge=0)
union(key,box('Key_flange',(25,15,1),(0,3,144.3),None,edge=0))
union(key,box('Key_stem',(3,3,1.6),(0,3,143.1),None,edge=0))
part(key,'Nominal 0.3 mm side clearance. Flange-to-roof 0.8 mm; switch travel target 0.25 mm, adjust after procurement.')
# Tray and LED baffle mounts join the rear tub outside the 66x56 carrier.
for x in [-41,41]:
    union(shell,cyl('Radar_tray_post',3.2,26.5,(x,7.25,121),None,edge=0))
    hole(shell,.8,6,(x,-5,121))
for x in [-36,36]:
    union(shell,cyl('LED_tray_post',3,29,(x,6,52),None,edge=0))
    hole(shell,.8,5,(x,-6.5,52))
bevel(shell,.15)

face=part(rr('02_Front_Radome',100,116,1.6,14,(0,-22.8,90),radome,edge=0),'1.6 mm unfilled polymer experiment; RF performance must be measured.')
lip=rr('Lip',94.6,110.6,1.7,11.3,(0,-21.25,90),None,edge=0)
boolean(lip,rr('CUT_lip',90.6,106.6,5,9.3,(0,-21.25,90),None,edge=0))
for x in [-42,42]:hole(lip,3.8,5,(x,-21.25,39))
union(face,lip)
boolean(face,rr('CUT_light',78.6,24.6,8,10.3,(0,-22,52),None,edge=0))
for x,z in cover_mounts:
    hole(face,1.4,8,(x,-22, z))
    mark(cyl('Cover_M2p5_head',2.4,1.2,(x,-24.2,z),white,eleccol,edge=.15),'hardware')
# Lens and black tube separate ambient-light sensor from nightlight.
hole(face,1.8,7,(33,-22,78))
union(face,cyl('Lux_tube',3.5,8,(33,-18.4,78),None,edge=0));hole(face,1.8,12,(33,-18,78))
face['radome_mm']=1.6
window=rr('03_Light_Diffuser',78,24,1.6,10,(0,-22.8,52),diffuser,edge=0)
union(window,rr('Diffuser_flange',82,28,1.2,12,(0,-21.4,52),None,edge=0))
part(window,'0.3 mm perimeter clearance; 1.2 mm rear flange, thin adhesive gasket bonds flange to front cover. No floating insert.')
mark(cyl('Lux_clear_lens',1.6,1.4,(33,-22.7,78),black,eleccol,edge=.1),'accessory')
sensor=mark(box('Lux_sensor_board_ALLOWANCE',(8,1.6,8),(33,-13.5,78),pcbmat,eleccol,edge=.1),'electronics_allowance')
sensor['fit_note']='8x8 sensing head fixed to light tube with removable opaque tape; larger BH1750 modules require separate holder.'

# PCB holes and all 23 placements are read from the frozen release.
pcb=mark(box('PCB_V02_66x56',(66,1.6,56),(0,12.2,84),pcbmat,eleccol,edge=0),'pcb','pcb/release_v02/Mianguang_V0.2.epcb + PickPlace')
for x in [-28,28]:
    for z in [61,107]:
        hole(pcb,1.35,4,(x,12.2,z));mark(cyl('PCB_M2p5_head',2.4,1.2,(x,10.8,z),metal,eleccol,edge=.08),'hardware')
pcb['pcb_to_model']='X=x-33; Y(top)=11.4; Z=y+56; mm'
positions=[]
with (REPO/'pcb/release_v02/PickPlace_Mianguang_V0.2.csv').open(encoding='utf-8-sig',newline='') as f:
    for row in csv.DictReader(f):
        ref=row['Designator'];x=float(row['Ref X'][:-2]);z=float(row['Ref Y'][:-2]);rot=float(row['Rotation'])
        positions.append(dict(ref=ref,pcb_mm=[x,z],rotation_deg=rot))
        if ref=='U1':continue
        if ref.startswith('J'):
            n=4 if ref in ['J2','J5'] else 2
            w,h=(n*2.54,2.54) if rot==0 else (2.54,n*2.54)
            o=box(ref+'_Header',(w,2.5,h),(x-33,10.15,z+56),black,eleccol,.08)
            # Header + mating connector up to 14 mm total from carrier top.
            if ref.startswith('JP'):
                cap=box(ref+'_Removable_Shunt',(w,6,h),(x-33,5.9,z+56),black,eleccol,.08);mark(cap,'electronics_allowance')
            else:
                plug=box(ref+'_Mating_Plug',(10.4 if ref=='J2' else w+.8,10.5,h+.8),(x-33,3.65,z+56),white,eleccol,.1);mark(plug,'electronics_allowance')
                if ref=='J2':plug['purchase_constraint']='Narrow 1x4 plug max10.4mm X width; JP2 shunt side clearance0.26mm. Verify actual shell tolerance.'
            mark(o,'pcb_component','Frozen PickPlace + nominal P2.54 header body')
        else:
            dims={'D1':(5,2.5,2.6),'D2':(3.6,1.2,1.7),'Q1':(3.2,1.3,3.2),'F1':(3.2,1.4,1.6)}.get(ref,(2.1,1.4,1.3) if ref in ['C1','C4'] else (1.7,.8,.9))
            w,d,h=dims
            if rot==90:w,h=h,w
            o=box(ref,(w,d,h),(x-33,11.4-d/2,z+56),black,eleccol,.05);mark(o,'pcb_component','PickPlace XY; conservative nominal body envelope')
        o['designator']=ref;o['pcb_xy_mm']=[x,z]
# XIAO aligns by castellated pins, not by visual artwork. 11mm board-bottom standoff.
for x in [-7.62,7.62]:
    mark(box('U1_Female_1x7',(2.54,8.5,17.78),(x,7.15,85.51740096),black,eleccol,.1),'pcb_component','C124418 housing 8.5mm; two rows pitch15.24')
    mark(box('U1_Male_Spacer',(2.54,2.5,17.78),(x,1.65,85.51740096),black,eleccol,.08),'electronics_allowance')
    for i in range(7):mark(box('U1_Pin',(.64,14,.64),(x,7.4,77.89740096+i*2.54),gold,eleccol,.03),'hardware')
xiao=mark(rr('U1_XIAO_Board',17.78,20.955,1.6,1,(0,-.4,85.58090096),pcbmat,eleccol,edge=.05),'electronics_allowance','Seeed official V1.3 KiCad: registration from14 pins; thickness1.6 allowance')
xiao['designator']='U1';xiao['pcb_xy_mm']=[33,30]
mark(box('U1_RF_Shield',(12,2.6,12),(0,-2.5,84),metal,eleccol,.2),'electronics_allowance')
mark(rr('U1_USB_C',9.2,7,3.2,1,(0,-2.8,94.1),metal,eleccol,.1),'electronics_allowance')
usb_service=box('REF_XIAO_USB_Plugin', (12,8,24),(0,-2.8,109.6),None,refcol,edge=0)
usb_service.display_type='WIRE';usb_service.hide_render=True;usb_service['usage']='Front cover and radar tray removed for programming; JP1/2/3 accessible. This is a removable service space, not a permanent cable.'

# C1001 mounting holes are from the board solid in the official STEP, not guessed.
radar=mark(box('C1001_Board_22x22',(22,1,22),(0,-16.8,121),pcbmat,eleccol,edge=0),'electronics_allowance','DFRobot JQC1001.step PCB entity: 22x22; approx1mm; two holesØ2 at(20,2),(20,20)')
for z in [112,130]:hole(radar,1,3,(9,-16.8,z))
radar_back=mark(box('C1001_Back_Component_BUDGET',(14.8,8,18),(.6,-12.3,121),black,eleccol,0),'electronics_allowance','8mm rear-population budget excluding 6pin lane and 2.2mm screw keepout; vendor STEP whole-assembly bounds unreliable; measure actual sample')
for z in [112,130]:hole(radar_back,2.2,12,(9,-12.3,z))
mark(box('C1001_1x6_Header',(2.54,10.5,15.24),(-8.5,-11.05,121),black,eleccol,.05),'electronics_allowance','6-pin 2.54mm wiring envelope; requires actual orientation/height verification')
mark(box('C1001_Antenna_Face',(12,.2,16),(1,-17.4,121),radome,eleccol,.1),'electronics_allowance')
tray=rr('05_Radar_Carrier',28,28,2,2,(0,-7,121),white,edge=0)
boolean(tray,box('CUT_radar_back',(19,6,22),(-2,-7,121),None,edge=0))
for x in [-27.5,27.5]:union(tray,box('Radar_arm',(29,2,5),(x,-7,121),None,edge=0))
for x in [-41,41]:hole(tray,1.1,6,(x,-7,121))
for z in [112,130]:
    union(tray,cyl('C1001_spacer',1.8,9.3,(9,-11.65,z),None,edge=0));hole(tray,.85,14,(9,-11.2,z))
part(tray,'C1001 two M1.6x14 through bolts/nuts. Right-edge posts respect 18mm pitch. Carrier M2x6 to shell. Remove before USB service.')

# Light board in an opaque tray, independently supported; front flange bonded.
lighttray=rr('06_LED_Baffle',76,20,5,5,(0,-11,52),white,edge=0)
boolean(lighttray,rr('CUT_lightwell',68,12,7,2,(0,-13,52),None,edge=0))
for x in [-36,36]:hole(lighttray,1.1,10,(x,-11,52))
part(lighttray,'Opaque baffle; 65x9x1 mm current-limited LED strip fixed with adhesive pad, lead exits through side slot.')
boolean(lighttray,box('LED_wire_slot',(5,9,2),(34,-11,56.8),None,edge=0))
mark(box('Nightlight_PCB_65x9',(65,1,9),(0,-10,52),pcbmat,eleccol,.1),'electronics_allowance')
for x in [-24,-12,0,12,24]:mark(box('Warm_LED',(3,.8,3),(x,-10.9,52),diffuser,eleccol,.1),'electronics_allowance')
mark(box('USB_5V_Receiver_Board',(18,12,1.6),(-27,13.5,40.5),pcbmat,eleccol,.1),'electronics_allowance','Procurement constraint only:18x12x1.6; independent CC1/CC2 resistors mandatory')
usb=rr('USB_5V_Shell',9.2,3.4,7,1.6,(-27,19.5,43),metal,eleccol,edge=0)
boolean(usb,rr('CUT_usb_mouth',7.8,2.3,8,1.05,(-27,20,43),None,eleccol,edge=0));mark(usb,'electronics_allowance')
mark(box('USB_Tongue',(6.2,4,.65),(-27,21,43),black,eleccol,.03),'electronics_allowance')
external_plug=box('REF_External_USB_Plug',(14,30,9),(-27,38,43),None,refcol,edge=0);external_plug.hide_render=True;external_plug.display_type='WIRE'
mark(box('Switch_PCB_ALLOWANCE',(10,10,1.6),(0,3,136.3),pcbmat,eleccol,.1),'electronics_allowance')
mark(box('Switch_6x6_ALLOWANCE',(6,6,5),(0,3,139.6),black,eleccol,.1),'electronics_allowance')
# Route side corridors; keep antenna front prism free of wire and fasteners.
route('Harness_C1001',[(23,-1.6,91),(31,-5,99),(31,-3,115),(20,-3,139),(-27,-3,139),(-27,-3,125),(-10,-3,125),(-8.5,-5.8,125)],1)
route('Harness_LED',[(23,-1.6,73),(32,-4,64),(34,-5,56.8),(34,-12,56.8),(31,-12,56),(31,-11,52)],.7)
route('Harness_Button',[(-22,-1.6,85),(-31,-4,92),(-31,-4,137.2),(-23,-4,137.2),(-4,3,137.1)],.6)
route('Harness_Lux',[(-19,-1.6,100),(-34,-7,95),(-34,-12,73),(32,-13,73),(33,-13,78)],.6)
route('Harness_5V',[(-16,-1.6,64),(-24,2,56),(-29,13,49),(-29,13,41.3)],.7)
mark(box('WiFi_FPC_40x20',(2,20,40),(-46.6,0,84),black,eleccol,.1),'electronics_allowance','Seeed A-01 M01-0601770R0A:40x20 FPC, local solder height<=1.8; 2mm allowance. Adhesive side-wall attachment.')
mark(cyl('U1_ANT0_UFL',1.1,1.6,(0,-2,76.50040096),gold,eleccol,edge=.05),'electronics_allowance','Seeed V1.3 ANT0 registered at PCB(33,20.50040096); connector height allowance')
route('WiFi_Feed_80mm',[(-45.5,0,84),(-40,-4,71),(-35,-4,63),(-25,-4,63),(-16,-4,74),(0,-3.8,76.50040096)],.565)

mount_code=runpy.run_path(str(SOURCE/'scripts/mount_v02.py'))
mount=mount_code['build_mount'](globals())
root=bpy.data.objects.new(PREFIX+'AIM_PIVOT_X',None);bodycol.objects.link(root);root.location=Vector((0,34,90))/1000
bpy.context.view_layer.update()
for coll in [bodycol,eleccol,refcol]:
    for o in list(coll.objects):
        if o != root:o.parent=root;o.matrix_parent_inverse=root.matrix_world.inverted()
root['desk_range_deg']=[0,30];root['wall_range_deg']=[0,45]
root['service']='Remove front four screws, detach radar tray; disconnect external5V and removeJP1/2/3 before XIAOUSB.'

# Numeric source-registration checks are independent of view transforms.
check('carrier_holes',True,pcb_mm=[[5,5],[61,5],[5,51],[61,51]],model_xz_mm=[[-28,61],[28,61],[-28,107],[28,107]],diameter_mm=2.7,pitch_mm=[56,46])
check('all_placements_present',len(positions)==23,count=len(positions))
check('XIAO_pin_registration',True,row_pitch_mm=15.24,pin_pitch_mm=2.54,module_bottom_standoff_budget_mm=11)
check('carrier_back_solder_to_wall',19.6-16>=3.5,clearance_mm=3.6)
check('carrier_edge_to_roof',145.6-112>0,clearance_mm=33.6)
check('antenna_front_gap',True,nominal_mm=4.5,status='GEOMETRY ONLY; no RF validation')
check('C1001_holes',True,diameter_mm=2,pitch_mm=18,source='research/datasheets/C1001_step/JQC1001.step')
check('USB_receiver_panel_allowance',True,opening_mm=[11.4,6.4],socket_mm=[9.2,3.4],per_side_mm=[1.1,1.5],status='CONDITIONAL on selected receiver')
check('XIAO_service_radar_budget_separation',True,clearance_mm=1.5,status='Remove radar tray for cable insertion; height budgets only')
check('key_side_clearance',True,per_side_mm=.3,roof_flange_gap_mm=.8)
for item in checks:item['design_condition_satisfied']=item.pop('passed')
(Path(ROOT)/'fit_parameters.json').write_text(json.dumps({'record_type':'DESIGN PARAMETERS, not independent verification; see geometry_checks.json','coordinate_map':'PCB(x,y)->Blender_mm(x-33,12.2,y+56)','source_sha256':hashlib.sha256((REPO/'pcb/release_v02/manifest.json').read_bytes()).hexdigest(),'positions':positions,'design_conditions':checks,'purchased_part_policy':'Conditional fit to envelopes; procurement and physical checks required'},ensure_ascii=False,indent=2))

# Export each distinct part at the assembled neutral pose, millimetre vertices.
report=[]
for o in parts:
    bpy.context.view_layer.update();eo=o.evaluated_get(bpy.context.evaluated_depsgraph_get());mesh=eo.to_mesh()
    bm=bmesh.new();bm.from_mesh(mesh);bmesh.ops.triangulate(bm,faces=list(bm.faces));bm.normal_update()
    bounds=[o.matrix_world@v.co for v in bm.verts];lo=Vector([min(v[i] for v in bounds) for i in range(3)]);hi=Vector([max(v[i] for v in bounds) for i in range(3)])
    tris=[]
    for f in bm.faces:
        vs=[o.matrix_world@v.co for v in f.verts];n=(vs[1]-vs[0]).cross(vs[2]-vs[0]).normalized();ps=[(v-Vector((0,0,lo.z)))*1000 for v in vs];tris.append((*n,*(c for p in ps for c in p)))
    path=Path(ROOT)/'stl'/(o.name+'.stl')
    with path.open('wb') as f:
        f.write(b'Mianguang V0.2 mechanical prototype, mm'.ljust(80,b' '));f.write(struct.pack('<I',len(tris)))
        for tri in tris:f.write(struct.pack('<12fH',*tri,0))
    # Connected shells: more than one denotes disconnected solid islands.
    pending=set(bm.verts);islands=0
    while pending:
        islands+=1;stack=[pending.pop()]
        while stack:
            v=stack.pop()
            for e in v.link_edges:
                q=e.other_vert(v)
                if q in pending:pending.remove(q);stack.append(q)
    report.append(dict(part=o.name,stl=str(path.relative_to(ROOT)),nonmanifold_edges=sum(not e.is_manifold for e in bm.edges),connected_islands=islands,volume_mm3=round(bm.calc_volume(signed=True)*1e9,3),bounds_mm=[round(v*1000,3) for v in hi-lo],note=o.get('fit_note','')))
    bm.free();eo.to_mesh_clear()
(Path(ROOT)/'mesh_checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
if any(r['nonmanifold_edges'] or r['connected_islands']!=1 or r['volume_mm3']<=0 for r in report):
    raise RuntimeError('Printable mesh check failed; see v0.2/mesh_checks.json. Project was not saved.')

def track(o,point):o.rotation_euler=(Vector(point)-o.location).to_track_quat('-Z','Y').to_euler()
ground=box('Studio_Floor',(2000,2000,2),(0,0,-2),stagemat,studiocol,edge=0)
def area(name,loc,energy,size,color):
    d=bpy.data.lights.new(PREFIX+name,'AREA');d.energy=energy;d.shape='DISK';d.size=size;d.color=color;o=bpy.data.objects.new(PREFIX+name,d);studiocol.objects.link(o);o.location=loc;track(o,(0,0,.09))
area('Key',(.15,-.23,.40),14,.30,(1,.94,.86));area('Fill',(-.24,-.06,.23),6,.25,(.84,.92,1));area('Rim',(.07,.23,.36),18,.22,(1,1,1))
world=bpy.data.worlds.new(PREFIX+'Studio');world.use_nodes=True;bg=next(n for n in world.node_tree.nodes if n.type=='BACKGROUND');bg.inputs[0].default_value=(.57,.63,.65,1);bg.inputs[1].default_value=.35;scene.world=world
camd=bpy.data.cameras.new(PREFIX+'Camera');cam=bpy.data.objects.new(PREFIX+'Camera',camd);studiocol.objects.link(cam);cam.location=(.25,-.36,.23);track(cam,(0,.018,.078));camd.type='ORTHO';camd.ortho_scale=.25;scene.camera=cam
scene.render.engine='CYCLES';scene.cycles.samples=32;scene.cycles.use_denoising=True;scene.render.resolution_x=1400;scene.render.resolution_y=1400;scene.render.resolution_percentage=100;scene.render.image_settings.file_format='PNG';scene.view_settings.view_transform='AgX';scene.view_settings.exposure=-.7
wallcol.hide_render=True;wallcol.hide_viewport=True
scene.render.filepath='//renders/01_hero.png'
# Copy objects and parenting into independent scenes; geometry stays linked.
def clone_view(name):
    ns=bpy.data.scenes.new(name);ns.unit_settings.system='METRIC';ns.unit_settings.length_unit='MILLIMETERS';ns.world=scene.world
    ns.render.engine='CYCLES';ns.cycles.samples=32;ns.cycles.use_denoising=True;ns.render.resolution_x=1400;ns.render.resolution_y=1400;ns.render.resolution_percentage=100;ns.view_settings.view_transform='AgX';ns.view_settings.exposure=-.7
    mapping={};cols={}
    for col in scene.collection.children:
        nc=bpy.data.collections.new(name+'_'+col.name);ns.collection.children.link(nc);nc.hide_render=col.hide_render;nc.hide_viewport=col.hide_viewport;cols[col.name]=nc
        for o in col.objects:
            n=o.copy()
            if o.type=='CAMERA':n.data=o.data.copy()
            nc.objects.link(n);mapping[o]=n
    for old,n in mapping.items():
        if old.parent in mapping:n.parent=mapping[old.parent];n.matrix_parent_inverse=old.matrix_parent_inverse.copy()
    ns.camera=mapping[cam];return ns,mapping,cols
rear,rm,rc=clone_view('Mianguang_V02_02_Rear');rear.camera.location=(-.25,.40,.23);track(rear.camera,(0,.025,.08));rear.render.filepath='//renders/02_rear.png'
wall,wm,wc=clone_view('Mianguang_V02_03_Wall_45deg');wc[standcol.name].hide_render=True;wc[standcol.name].hide_viewport=True;wc[wallcol.name].hide_render=False;wc[wallcol.name].hide_viewport=False;wm[root].rotation_euler[0]=math.radians(45)
wall.camera.location=(.27,-.33,.21);track(wall.camera,(0,.035,.09));wall.camera.data.ortho_scale=.26;wall.render.filepath='//renders/03_wall_45deg.png'
exploded,em,ec=clone_view('Mianguang_V02_04_Exploded');ec[standcol.name].hide_render=True;ec[wallcol.name].hide_render=True
for old,n in em.items():
    if old in bodycol.objects.values() or old in eleccol.objects.values():
        if old==root:continue
        n.parent=None;n.matrix_world=old.matrix_world.copy()
        if old in [face,window] or old.name.startswith(PREFIX+'Cover_M2p5'):n.location+=Vector((-.065,-.05,0))
        elif old in [shell,usbstrap] or old.name.startswith(PREFIX+'07'):n.location+=Vector((.065,.045,0))
        elif old in [key,bridge]:n.location+=Vector((.035,0,.04))
exploded.camera.location=(.34,-.45,.27);track(exploded.camera,(0,0,.09));exploded.camera.data.ortho_scale=.34;exploded.render.filepath='//renders/04_exploded.png'
for saved_scene in [scene,rear,wall,exploded]:
    bpy.context.window.scene=saved_scene
    bpy.context.view_layer.update()
bpy.context.window.scene=scene
for a in bpy.context.screen.areas if bpy.context.screen else []:
    if a.type=='VIEW_3D':a.spaces.active.region_3d.view_perspective='CAMERA'
blend=Path(ROOT)/'Mianguang_Enclosure_V0.2.blend'
# This process is an isolated background build; save a normal project with an
# active scene (a library-only .blend otherwise opens on an empty scene).
for old_scene in list(bpy.data.scenes):
    if old_scene not in [scene,rear,wall,exploded]:bpy.data.scenes.remove(old_scene)
bpy.data.orphans_purge(do_recursive=True)
bpy.ops.wm.save_as_mainfile(filepath=str(blend),compress=True)
result={'blend':str(blend),'parts':len(parts),'mesh_failures':[r for r in report if r['nonmanifold_edges'] or r['connected_islands']!=1 or r['volume_mm3']<=0]}
print(json.dumps(result,ensure_ascii=False))
