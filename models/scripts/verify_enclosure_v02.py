"""Read-only QA of the saved V0.2 Blender assembly against frozen PCB evidence.
Run: blender --background models/v0.2/Mianguang_Enclosure_V0.2.blend \
             --python models/scripts/verify_enclosure_v02.py
Writes geometry_checks.json only. It never saves or edits the delivered .blend.
"""
from pathlib import Path
import bpy, bmesh, math, json, hashlib, itertools, re
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree

MODELS=Path(__file__).resolve().parents[1]
REPO=MODELS.parent
OUT=MODELS/'v0.2/geometry_checks.json'
REF=json.loads((MODELS/'mechanical/pcb_v02_reference.json').read_text())
SCENE=bpy.data.scenes['Mianguang_V02_01_Desk']
bpy.context.window.scene=SCENE
# Hidden alternate installation is made evaluable in memory only.
for c in SCENE.collection.children:c.hide_viewport=False
bpy.context.view_layer.update()
P='SR02_'
objects={o.name:o for o in SCENE.objects}
rows=[]
def add(name,ok,**details):
    rows.append(dict(check=name,status='PASS' if ok else 'FAIL',**details))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def obj(name):return objects[P+name]
def geometry(o):
    eo=o.evaluated_get(bpy.context.evaluated_depsgraph_get());m=eo.to_mesh()
    m.calc_loop_triangles()
    vs=[o.matrix_world@v.co for v in m.vertices];fs=[tuple(t.vertices) for t in m.loop_triangles]
    eo.to_mesh_clear()
    return make_geom(vs,fs)
def make_geom(vs,fs):
    return dict(vertices=vs,faces=fs,tree=BVHTree.FromPolygons(vs,fs),
                lo=Vector([min(v[i] for v in vs) for i in range(3)]),
                hi=Vector([max(v[i] for v in vs) for i in range(3)]))
cache={}
def geom(o):
    if o not in cache:cache[o]=geometry(o)
    return cache[o]
def bbox_intersects(a,b):
    return all(a['lo'][i]<=b['hi'][i]+1e-8 and b['lo'][i]<=a['hi'][i]+1e-8 for i in range(3))
def size_mm(o):
    g=geom(o);return [(g['hi'][i]-g['lo'][i])*1000 for i in range(3)]
# A 0.05mm classification tolerance suppresses coplanar float32 noise. It is
# a numerical checking tolerance, not an allowed manufacturing interference.
TOL=.00005
DIRECTIONS=[Vector(v).normalized() for v in [(1,.234,.355),(.234,1,.51),(.355,.51,1)]]
def penetration(g,p):
    if any(p[i]<g['lo'][i]-1e-8 or p[i]>g['hi'][i]+1e-8 for i in range(3)):return None
    nearest,normal,index,distance=g['tree'].find_nearest(p)
    if distance is None or distance<=TOL:return None
    votes=0
    for d in DIRECTIONS:
        origin=p.copy();hits=0
        for _ in range(100):
            hit,n,i,dist=g['tree'].ray_cast(origin,d)
            if hit is None:break
            hits+=1;origin=hit+d*.000001  # 1um, above BVH float32 duplicate-hit noise.
        votes+=hits%2
    return distance*1000 if votes>=2 else None

def penetrating_samples(a,b,both=True):
    if not bbox_intersects(a,b):return []
    pairs=[(a,b),(b,a)] if both else [(a,b)]
    hits=[]
    for source,target in pairs:
        # Mesh vertices plus triangulated face centres catch both corner penetration and
        # a thin solid crossing the middle of a larger face. This is sampled QA.
        samples=list(source['vertices'])
        for face in source['faces']:
            samples.append(sum((source['vertices'][i] for i in face),Vector())/len(face))
        for p in samples:
            d=penetration(target,p)
            if d is not None:hits.append(dict(point_mm=[round(v*1000,5) for v in p],depth_mm=round(d,5)))
    return hits

# Frozen evidence integrity and actual saved mesh location measurements.
add('frozen_reference_hashes',all(sha(REPO/s['path'])==s['sha256'] for s in REF['sources']),files=len(REF['sources']))
board=obj('PCB_V02_66x56');board_size=size_mm(board)
add('carrier_outline_and_thickness',max(abs(a-b) for a,b in zip(board_size,[66,1.6,56]))<.001,measured_xyz_mm=board_size)
placements=[]
for c in REF['components']:
    ref=c['designator'];x,y=c['reference_xy_mm']
    if ref=='U1':continue
    candidates=[o for o in objects.values() if o.get('designator')==ref]
    if len(candidates)!=1:
        placements.append(dict(ref=ref,ok=False,reason='missing or duplicate object'));continue
    o=candidates[0];actual=[o.matrix_world.translation.x*1000+33,o.matrix_world.translation.z*1000-56]
    error=max(abs(actual[i]-c['reference_xy_mm'][i]) for i in range(2))
    placements.append(dict(ref=ref,ok=error<.001,measured_pcb_xy_mm=actual,error_mm=error))
u1=next(c for c in REF['components'] if c['designator']=='U1')
pins=[o for o in objects.values() if re.fullmatch(r'SR02_U1_Pin(?:\.\d+)?',o.name)]
actual_pins=sorted((o.matrix_world.translation.x*1000+33,o.matrix_world.translation.z*1000-56) for o in pins)
expected_pins=sorted(tuple(p['center_xy_mm']) for p in u1['pads'])
pin_error=max((max(abs(a[i]-b[i]) for i in range(2)) for a,b in zip(actual_pins,expected_pins)),default=999)
placements.append(dict(ref='U1',ok=len(pins)==14 and pin_error<.001,measured_pad_count=len(pins),max_pad_error_mm=pin_error))
add('all_23_PCB_component_registrations',len(placements)==23 and all(p['ok'] for p in placements),placements=placements)

# Hole centres and diameters are fitted to actual saved mesh rim vertices,
# using the source position only to select the local rim neighbourhood.
def hole_rim(o,x,z,y,search_radius):
    points={(round(v.x*1000,6),round(v.z*1000,6)) for v in geom(o)['vertices']
            if abs(v.y*1000-y)<.003 and math.hypot(v.x*1000-x,v.z*1000-z)<search_radius}
    if len(points)<12:return None
    cx=sum(p[0] for p in points)/len(points);cz=sum(p[1] for p in points)/len(points)
    radii=[math.hypot(p[0]-cx,p[1]-cz) for p in points]
    return dict(center_xz_mm=[cx,cz],diameter_mm=2*sum(radii)/len(radii),rim_points=len(points),radial_spread_mm=max(radii)-min(radii))
mount_results=[]
for h in REF['board']['mounting_holes']:
    x,z=h['center_xy_mm'][0]-33,h['center_xy_mm'][1]+56
    pcb_hole=hole_rim(board,x,z,11.4,2.15)
    shell_pilot=hole_rim(obj('01_Rear_Tub'),x,z,13,2.05)
    ok=pcb_hole is not None and shell_pilot is not None
    if ok:
        error=max(abs(pcb_hole['center_xz_mm'][i]-[x,z][i]) for i in range(2))
        coaxial=math.dist(pcb_hole['center_xz_mm'],shell_pilot['center_xz_mm'])
        ok=error<.005 and abs(pcb_hole['diameter_mm']-h['diameter_mm'])<.005 and coaxial<.01
    else:error=coaxial=None
    mount_results.append(dict(ok=ok,pcb=pcb_hole,shell_insert_pilot=shell_pilot,centre_error_mm=error,coaxial_error_mm=coaxial))
add('four_carrier_holes_and_boss_axes',all(r['ok'] for r in mount_results),holes=mount_results)
radar_holes=[]
for x,z in [(9,112),(9,130)]:
    rim=hole_rim(obj('C1001_Board_22x22'),x,z,-17.3,1.4)
    pilot=hole_rim(obj('05_Radar_Carrier'),x,z,-16.3,1.2)
    ok=rim is not None and pilot is not None and abs(rim['diameter_mm']-2)<.005 and math.dist(rim['center_xz_mm'],pilot['center_xz_mm'])<.01
    radar_holes.append(dict(ok=ok,module=rim,tray=pilot))
add('C1001_holes_and_tray_axes',all(h['ok'] for h in radar_holes),holes=radar_holes)

# Independently reevaluate the printable meshes; never trust the builder's report.
printables=sorted([o for o in objects.values() if re.match(r'^SR02_\d\d_',o.name)],key=lambda o:o.name)
meshes=[]
for o in printables:
    g=geom(o);m=bpy.data.meshes.new('QA_Mesh');m.from_pydata(g['vertices'],[],g['faces']);m.update()
    bm=bmesh.new();bm.from_mesh(m);pending=set(bm.verts);islands=0
    while pending:
        islands+=1;stack=[pending.pop()]
        while stack:
            v=stack.pop()
            for e in v.link_edges:
                q=e.other_vert(v)
                if q in pending:pending.remove(q);stack.append(q)
    edges=sum(not e.is_manifold for e in bm.edges);volume=bm.calc_volume(signed=True)*1e9
    meshes.append(dict(part=o.name,nonmanifold_edges=edges,connected_islands=islands,volume_mm3=volume,ok=edges==0 and islands==1 and volume>0))
    bm.free();bpy.data.meshes.remove(m)
add('eleven_printable_meshes',len(meshes)==11 and all(m['ok'] for m in meshes),meshes=meshes)

# Static assembly: moving-shell printables against one another and every
# electronic envelope, plus indicative wire envelopes against printed parts.
body_parts=[o for o in printables if not o.name.startswith((P+'08_',P+'09_'))]
electronics=[o for o in objects.values() if o.get('part_role') in ('pcb','pcb_component','electronics_allowance','accessory') and o.type=='MESH']
wires=[o for o in objects.values() if o.get('part_role')=='wire_route']
static_results=[]
for a,b in list(itertools.combinations(body_parts,2))+[(a,b) for a in body_parts for b in electronics+wires]:
    ga,gb=geom(a),geom(b)
    if not bbox_intersects(ga,gb):continue
    hits=penetrating_samples(gb,ga,both=b not in wires)
    if hits:static_results.append(dict(a=a.name,b=b.name,sample_count=len(hits),deepest=max(hits,key=lambda h:h['depth_mm'])))
add('static_printed_parts_and_electronic_budgets',not static_results,penetrations=static_results,method='mesh vertices/triangulated face centres, nearest distance + three-direction ray parity; 0.05mm classification threshold; wire samples tested only against closed printed solid')
# Close connector pair: calculate genuine axis clearance from saved envelopes.
j2,jp2=geom(obj('J2_Mating_Plug')),geom(obj('JP2_Removable_Shunt'))
jgap=(j2['lo'].x-jp2['hi'].x)*1000
add('J2_to_JP2_narrow_plug_clearance',jgap>=.2,measured_x_clearance_mm=jgap,qualification='Conditional on purchased connector fitting the reserved envelope')
# Module stack is a measured design allowance, not a measured commercial assembly.
under=geom(obj('U1_XIAO_Board'))['hi'].y*1000
add('XIAO_reserved_stack',abs(11.4-under-11)<.001,reserved_carrier_to_module_bottom_mm=11.4-under,qualification='8.5mm female housing + 2.5mm male spacer; physically verify purchased header mating')
antenna=geom(obj('C1001_Antenna_Face'))
# Sample ray into the radome from antenna front centre to obtain actual gap.
ant_front=Vector((0,antenna['lo'].y,.121));hit,normal,idx,dist=geom(obj('02_Front_Radome'))['tree'].ray_cast(ant_front,Vector((0,-1,0)))
add('radar_antenna_to_radome_gap',hit is not None and dist>0,measured_gap_mm=dist*1000 if hit else None,qualification='Geometry only, no RF performance conclusion')
# External opening checked against the selected receiver envelope, ignoring its
# intentional protrusion through the opening and checking only interference.
usb_hits=penetrating_samples(geom(obj('USB_5V_Shell')),geom(obj('01_Rear_Tub')))
add('external_USB_receiver_opening',not usb_hits,penetrations=usb_hits[:5],qualification='Conditional USB receiver envelope and cable selected later')

# Sweep both installation modes from the neutral saved geometry. Fixed bracket
# surfaces remain fixed. Stop contact at endpoints is allowed; strict penetration
# at endpoints and any surface crossing at interior angles are reported.
pivot=Vector((0,.034,.09))
neutral={o:geom(o) for o in body_parts}
plugin=geom(obj('REF_External_USB_Plug'))
motion=[]
for label,stand_name,limit in [('desk','08_Desk_Stand_Base',30),('wall','09_Wall_Bracket_Plate',45)]:
    fixed=geom(obj(stand_name));bad=[];min_base_clearance=999;min_wall_clearance=999
    angles=[0,.1]+[i*.5 for i in range(1,limit*2)]+[limit-.1,limit]
    for angle in angles:
        transform=Matrix.Translation(pivot)@Matrix.Rotation(math.radians(angle),4,'X')@Matrix.Translation(-pivot)
        transformed=[]
        for o,g in neutral.items():
            moved=make_geom([transform@v for v in g['vertices']],g['faces']);transformed.append(moved)
            if not bbox_intersects(moved,fixed):continue
            crossings=moved['tree'].overlap(fixed['tree'])
            if not crossings:continue
            if angle in (0,limit):
                hits=penetrating_samples(moved,fixed)
                if hits:bad.append(dict(angle_deg=angle,part=o.name,penetration=max(hits,key=lambda h:h['depth_mm'])))
            else:bad.append(dict(angle_deg=angle,part=o.name,surface_crossings=len(crossings)))
        # Include the outside USB plug body as a conditional cable reservation.
        moved=make_geom([transform@v for v in plugin['vertices']],plugin['faces'])
        if bbox_intersects(moved,fixed):
            hits=penetrating_samples(moved,fixed)
            if hits:bad.append(dict(angle_deg=angle,part='external USB plug allowance',penetration=max(hits,key=lambda h:h['depth_mm'])))
        min_base_clearance=min(min_base_clearance,min(g['lo'].z for g in transformed)*1000-7)
        min_wall_clearance=min(min_wall_clearance,95-max(g['hi'].y for g in transformed+[moved])*1000)
    motion.append(dict(mode=label,angles_deg=angles,pose_count=len(angles),failure_count=len(bad),failures=bad,
                       min_body_to_base_plane_mm=min_base_clearance if label=='desk' else None,
                       min_body_and_USB_plug_to_wall_plane_mm=min_wall_clearance if label=='wall' else None))
add('desk_0_to_30_and_wall_0_to_45_motion',all(m['failure_count']==0 for m in motion),sweeps=motion,
    qualification='Discrete 0.5deg sweep plus endpoints and 0.1deg near stops; not continuous proof, load test or cable-bend validation')

# Confirm that each end stop is an actual geometric stop, not just a label.
stop_samples=[]
yoke=geom(obj('07_Common_Dock_Yoke'))
for label,name,limit in [('desk','08_Desk_Stand_Base',30),('wall','09_Wall_Bracket_Plate',45)]:
    fixed=geom(obj(name))
    for angle in [-.1,limit+.1]:
        transform=Matrix.Translation(pivot)@Matrix.Rotation(math.radians(angle),4,'X')@Matrix.Translation(-pivot)
        moved=make_geom([transform@v for v in yoke['vertices']],yoke['faces'])
        count=len(moved['tree'].overlap(fixed['tree']))
        stop_samples.append(dict(mode=label,angle_deg=angle,intersecting_face_pairs=count))
add('mechanical_stops_beyond_limits',all(s['intersecting_face_pairs']>0 for s in stop_samples),samples=stop_samples)
# Key travels down 0.45mm: 0.20mm free gap plus the specified 0.25mm tact travel.
key_obj=obj('04_Captive_Top_Key');key_geom=geom(key_obj);key_hits=[]
for stroke in [0,.2,.45]:
    transform=Matrix.Translation((0,0,-stroke/1000))
    moved=make_geom([transform@v for v in key_geom['vertices']],key_geom['faces'])
    for target in body_parts:
        if target==key_obj:continue
        hits=penetrating_samples(moved,geom(target))
        if hits:key_hits.append(dict(stroke_mm=stroke,part=target.name,deepest=max(hits,key=lambda h:h['depth_mm'])))
add('key_reserved_stroke',not key_hits,stroke_mm=[0,.2,.45],penetrations=key_hits,qualification='Switch spring/actuation force and actual stack are not verified')
service_geom=geom(obj('REF_XIAO_USB_Plugin'));service_hits=[]
for target in body_parts:
    if target.name in [P+'02_Front_Radome',P+'03_Light_Diffuser',P+'05_Radar_Carrier']:continue
    hits=penetrating_samples(service_geom,geom(target))
    if hits:service_hits.append(dict(part=target.name,deepest=max(hits,key=lambda h:h['depth_mm'])))
add('XIAO_USB_service_envelope',not service_hits,plug_xyz_budget_mm=size_mm(obj('REF_XIAO_USB_Plugin')),penetrations=service_hits,qualification='Front cover and radar carrier removed; real cable bend and finger access must be checked')

result={'schema':'mianguang.enclosure.geometry_checks.v1','date':'2026-11-04','blender_version':bpy.app.version_string,
        'source_blend':'Mianguang_Enclosure_V0.2.blend','source_blend_sha256':sha(MODELS/'v0.2/Mianguang_Enclosure_V0.2.blend'),
        'reference_sha256':sha(MODELS/'mechanical/pcb_v02_reference.json'),'checker_sha256':sha(Path(__file__)),
        'read_only':True,'classification_tolerance_mm':.05,'checks':rows,
        'status':'FAIL' if any(r['status']=='FAIL' for r in rows) else 'PASS',
        'failure_count':sum(r['status']=='FAIL' for r in rows),
        'checked_model_sha256':sha(MODELS/'v0.2/Mianguang_Enclosure_V0.2.blend'),
        'summary':{'pass':sum(r['status']=='PASS' for r in rows),'fail':sum(r['status']=='FAIL' for r in rows)},
        'limitations':['Purchased components remain conditional envelopes, especially XIAO stack/C1001 rear height/USB receiver/light sensor.','No actual hardware, RF, strength, heat, print-shrinkage or tipping validation.','Sampled penetration and discrete angle checks do not constitute an exact continuous collision proof.']}
OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps({'report':str(OUT),'summary':result['summary'],'failed':[r['check'] for r in rows if r['status']=='FAIL']},ensure_ascii=False))
