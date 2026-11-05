"""Conservative Gerber geometry checks for the two-layer Mianguang carrier.

Requires gerbonara==1.6.3, shapely==2.2.0. No files are extracted or modified.
Unsupported geometry/registration is UNVERIFIED, never an implicit PASS.
Copper checks concern nominal exported geometry, not manufactured tolerances.
"""
from collections import Counter, defaultdict
from dataclasses import replace
import importlib.metadata
import math
from pathlib import Path
import re
import warnings
import zipfile

from gerbonara import GerberFile, ExcellonFile
from gerbonara import graphic_objects as go, graphic_primitives as gp
from gerbonara.apertures import CircleAperture
from gerbonara.utils import MM
from shapely import affinity
from shapely.geometry import Point, Polygon, LineString, GeometryCollection, box
from shapely.ops import unary_union, polygonize

MIL = 0.0254
POSITION_TOL = 0.02  # Export quantization/coordinate comparison, never copper expansion.
ARC_ERROR = 0.0005


class Unsupported(ValueError):
    pass


def _disk(x, y, radius, error=ARC_ERROR):
    if radius <= 0:
        return GeometryCollection()
    n = max(16, math.ceil(math.pi / (4 * math.acos(max(-1, 1-min(error/radius, 1))))))
    return Point(x, y).buffer(radius, quad_segs=n)


def _valid(geom):
    if not geom.is_valid:
        raise Unsupported('Invalid/self-touching polygon; no automatic topology repair is allowed')
    return geom


def _primitive(prim, error):
    # Explicit rectangle rotation avoids relying on a library's rectangle-to-polygon shortcut.
    if isinstance(prim, gp.Rectangle):
        geom = box(-prim.w/2, -prim.h/2, prim.w/2, prim.h/2)
        return affinity.translate(affinity.rotate(geom, prim.rotation, use_radians=True), prim.x, prim.y)
    if isinstance(prim, gp.Circle):
        return _disk(prim.x, prim.y, prim.r, error)
    if not isinstance(prim, (gp.Line, gp.Arc, gp.ArcPoly)):
        raise Unsupported('Unsupported graphic primitive: '+type(prim).__name__)
    pts = prim.to_arc_poly().approximate_arcs(max_error=error).outline
    if len(pts) < 3:
        raise Unsupported('Degenerate Gerber primitive')
    return _valid(Polygon(pts))


def copper_geometry(layer, error=ARC_ERROR):
    """Compose objects separately: holes in an aperture do not erase prior objects."""
    result = GeometryCollection()
    for obj in layer.objects:
        if not isinstance(obj, (go.Flash, go.Line, go.Arc, go.Region)):
            raise Unsupported('Unsupported copper object: '+type(obj).__name__)
        if isinstance(obj, (go.Line, go.Arc)):
            if not isinstance(obj.aperture, CircleAperture) or obj.aperture.hole_dia:
                raise Unsupported('Stroked non-circular/holed apertures require separate validation')
        if isinstance(obj, go.Flash):
            local = replace(obj, polarity_dark=True)
        elif isinstance(obj, go.Region):
            local = go.Region(obj.outline, obj.arc_centers, unit=obj.unit, polarity_dark=True)
        else:
            local = replace(obj, polarity_dark=True)
        shape = GeometryCollection()
        for prim in local.to_primitives(unit=MM):
            part = _primitive(prim, error)
            shape = shape.union(part) if prim.polarity_dark else shape.difference(part)
        _valid(shape)
        result = result.union(shape) if obj.polarity_dark else result.difference(shape)
    return _valid(result)


def _outline(layer):
    lines = []
    for obj in layer.objects:
        if not isinstance(obj, go.Line) or not obj.polarity_dark:
            raise Unsupported('Outline must contain dark straight centerline segments only')
        o = obj.converted(MM)
        if abs(o.x1-o.x2)>1e-6 and abs(o.y1-o.y2)>1e-6:
            raise Unsupported('Non-rectangular outline segment')
        lines.append(LineString([(o.x1,o.y1),(o.x2,o.y2)]))
    if not lines:
        raise Unsupported('Empty outline')
    degree = Counter(tuple(round(v,6) for v in p) for line in lines for p in line.coords)
    if any(n != 2 for n in degree.values()):
        raise Unsupported('Outline centerline is not one closed simple loop')
    polygons = list(polygonize(lines))
    if len(polygons)!=1 or abs(polygons[0].area-polygons[0].envelope.area)>1e-6:
        raise Unsupported('Outline is not one closed rectangle')
    return polygons[0]


def _role(name, text):
    name = Path(name).name.lower()
    function = re.search(r'(?:TF\.FileFunction|FILE_FORMAT_FUNCTION),([^*%\r\n]+)',text,re.I)
    f = function.group(1).lower() if function else ''
    if 'copper' in f:
        if re.search(r'(?:^|,)top(?:,|$)', f): return 'top'
        if re.search(r'(?:^|,)bot(?:tom)?(?:,|$)', f): return 'bottom'
        return 'unsupported_copper'
    if 'profile' in f: return 'outline'
    if name.endswith('.gtl'): return 'top'
    if name.endswith('.gbl'): return 'bottom'
    if name.endswith('.gtp') or 'toppastemasklayer' in name: return 'top_paste'
    if name.endswith(('.gko','.gm1')) or re.search(r'(boardoutline|board_outline|edge_cuts)', name): return 'outline'
    if re.search(r'(npth|non.?plated)',name): return 'npth'
    if re.search(r'(^|[_ .-])pth([_ .-]|$)',name): return 'pth'
    if name.endswith(('.drl','.xln','.exc')) or 'M48' in text[:200]: return 'unknown_drill'
    if re.search(r'(toplayer|top_copper)',name): return 'top'
    if re.search(r'(bottomlayer|bottom_copper)',name): return 'bottom'
    if re.search(r'\.(g[1-9]|g[0-9]{2})$',name) or re.search(r'(inner|copper)',name): return 'unsupported_copper'
    return None


def _parse_zip(path):
    layers, drills, notes, unsupported = {}, [], [], []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if len(names)!=len(set(names)):
            raise Unsupported('Duplicate ZIP member names')
        for info in z.infolist():
            if info.is_dir(): continue
            if info.file_size>30_000_000: raise Unsupported('Oversized Gerber archive member')
            try: text=z.read(info).decode('utf-8-sig')
            except UnicodeDecodeError: continue
            role=_role(info.filename,text)
            if role is None: continue
            if role.startswith('unsupported'):
                unsupported.append(info.filename+': '+role);continue
            if role in ('top','bottom','outline','top_paste'):
                if role in layers: raise Unsupported('Multiple '+role+' Gerber files')
                if re.search(r'%\s*(IPNEG|AB|SR|MI|OF|SF|IR|AS)',text,re.I):
                    unsupported.append(info.filename+': unsupported image/block/repeat/legacy transform')
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter('always')
                    layer=GerberFile.from_string(text,filename=info.filename)
                notes.extend(info.filename+': '+str(w.message) for w in caught)
                layers[role]=(info.filename,layer)
            else:
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter('always')
                    layer=ExcellonFile.from_string(text,filename=info.filename)
                notes.extend(info.filename+': '+str(w.message) for w in caught
                             if 'G90 header statement found after end of header' not in str(w.message))
                for obj in layer.objects:
                    if not isinstance(obj,go.Flash):
                        raise Unsupported('Routed slots/arc drills are unsupported: '+info.filename)
                    o=obj.converted(MM)
                    p=obj.aperture.plated
                    filename_p={'pth':True,'npth':False}.get(role)
                    if p is not None and filename_p is not None and p!=filename_p:
                        raise Unsupported('Drill plating metadata contradicts filename')
                    p=filename_p if p is None else p
                    if p is None: unsupported.append(info.filename+': unknown drill plating')
                    drills.append({'x':o.x,'y':o.y,'d':MM(obj.aperture.diameter,obj.aperture.unit),
                                   'plated':p,'file':info.filename})
    if not all(k in layers for k in ('top','bottom','outline')):
        raise Unsupported('Cannot identify exactly one top, bottom and outline Gerber')
    if not drills: raise Unsupported('No drill data')
    # EasyEDA exports a complete PTH file plus a redundant Via-only drill file.
    # Ignore the latter only after proving it is an exact geometric subset.
    redundant = [d for d in drills if re.search(r'_via\.drl$',d['file'],re.I)]
    primary = [d for d in drills if d not in redundant]
    for d in redundant:
        if not any(all(d[k]==p[k] for k in ('x','y','d','plated')) for p in primary):
            raise Unsupported('Via drill file is not an exact subset of the main drill files')
    drills = primary if redundant else drills
    keys=[(d['x'],d['y'],d['d'],d['plated']) for d in drills]
    if len(keys)!=len(set(keys)):raise Unsupported('Duplicate drill hits outside validated redundant Via file')
    return layers,drills,notes,unsupported


def _size(data, axis):
    if not isinstance(data,dict): raise Unsupported('Non-dictionary pad geometry')
    return float(data.get(axis,0))*MIL


def _native_points(pcb_doc, comps, footprints, actual_pins):
    anchors,holes=[],[]
    for ref,c in comps.items():
        d=c['data'];uid=str(c['props'].get('Footprint','')).split('|')[0]
        if uid not in footprints: raise Unsupported('Missing footprint geometry: '+ref)
        if d.get('layerId')!=1: raise Unsupported('Bottom-side component transform not validated: '+ref)
        angle=math.radians(d.get('angle',0));co,si=math.cos(angle),math.sin(angle)
        for h,p,_ in footprints[uid]['records']:
            if h['type']!='PAD': continue
            pin=str(p.get('num','')); x=p['centerX']*MIL; y=p['centerY']*MIL
            x,y=d['x']*MIL+co*x-si*y,d['y']*MIL+si*x+co*y
            layer=p.get('layerId');hole=p.get('hole') or {}; dia=_size(hole,'width')
            if dia and (hole.get('holeType')!='ROUND' or abs(dia-_size(hole,'height'))>1e-5):
                raise Unsupported('Slotted/noncircular native pad hole: '+ref+'.'+pin)
            if p.get('specialPad'): raise Unsupported('Layer-specific pad geometry: '+ref+'.'+pin)
            if max(abs(p.get('padOffsetX') or 0),abs(p.get('padOffsetY') or 0))*MIL>0.002:
                raise Unsupported('Substantial pad-to-hole offset: '+ref+'.'+pin)
            pd=p.get('defaultPad') or {}
            if pd.get('padType') not in ('RECT','ELLIPSE','ROUND','OVAL'):
                raise Unsupported('Unsupported native pad shape: '+ref+'.'+pin)
            radius=min(_size(pd,'width'),_size(pd,'height'))/2
            if radius<=0 or radius<=dia/2: raise Unsupported('Invalid native pad land')
            nets=actual_pins.get(ref,{}).get(pin,set())
            if isinstance(nets,str): nets={nets}
            if len(nets)>1: raise Unsupported('Ambiguous physical pad net: '+ref+'.'+pin)
            net=next(iter(nets),'') or '@UNCONNECTED:'+ref+'.'+pin
            if layer not in (1,2,12): raise Unsupported('Unsupported pad layer: '+ref+'.'+pin)
            if dia:
                if p.get('plated') is not True or layer!=12: raise Unsupported('Unsupported component drill plating')
                holes.append(dict(x=x,y=y,d=dia,plated=True,ref=ref,pin=pin))
            anchors.append(dict(x=x,y=y,d=dia,r=radius,net=net,ref=ref,pin=pin,layers=(1,2) if layer==12 else (layer,),
                                land_shape=pd.get('padType'),width=_size(pd,'width'),height=_size(pd,'height'),
                                land_angle=d.get('angle',0)+p.get('padAngle',0),land_radius=pd.get('radius',0)))
    for h,d,_ in pcb_doc['records']:
        if h['type']=='VIA':
            if d.get('viaType') not in ('NORMAL',None): raise Unsupported('Blind/buried via')
            holes.append(dict(x=d['centerX']*MIL,y=d['centerY']*MIL,d=d['holeDiameter']*MIL,plated=True,ref='VIA',pin=h['id']))
        elif h['type']=='PAD':
            hole=d.get('hole') or {};dia=_size(hole,'width')
            if dia:
                if hole.get('holeType')!='ROUND' or abs(dia-_size(hole,'height'))>1e-5: raise Unsupported('Unsupported board hole')
                if d.get('plated') is not False: raise Unsupported('Standalone plated pad requires a net anchor')
                holes.append(dict(x=d['centerX']*MIL,y=d['centerY']*MIL,d=dia,plated=False,ref='BOARD',pin=d.get('num')))
        elif h['type']=='FILL' and d.get('layerId')==12:
            from check_release import round_slot_hole
            try:
                x,y,dia=round_slot_hole(d)
            except ValueError as exc:
                raise Unsupported(str(exc)) from exc
            holes.append(dict(x=x,y=y,d=dia,plated=False,ref='BOARD',pin=h['id']))
    return anchors,holes


def _match_holes(expected,actual,dx,dy,sx=1,sy=1):
    remaining=list(range(len(actual)));matches=[]
    for p in expected:
        x,y=sx*p['x']+dx,sy*p['y']+dy
        candidates=[i for i in remaining if actual[i]['plated']==p['plated'] and
                    abs(actual[i]['d']-p['d'])<POSITION_TOL and math.hypot(actual[i]['x']-x,actual[i]['y']-y)<POSITION_TOL]
        if len(candidates)!=1:return None
        i=candidates[0];remaining.remove(i);matches.append(i)
    return matches if not remaining else None


def _polygons(g):
    if g.is_empty:return []
    if g.geom_type=='Polygon':return [g]
    if g.geom_type=='MultiPolygon':return list(g.geoms)
    raise Unsupported('Non-polygon copper result')


def connectivity(coppers,drills,anchors,dx,dy,error=ARC_ERROR):
    holes=unary_union([_disk(p['x'],p['y'],p['d']/2,error) for p in drills])
    islands={layer:_polygons(c.difference(holes)) for layer,c in coppers.items()}
    ids=[(l,i) for l,ps in islands.items() for i in range(len(ps))]; parent={i:i for i in ids}
    def root(i):
        while parent[i]!=i:
            parent[i]=parent[parent[i]];i=parent[i]
        return i
    def join(a,b):parent[root(a)]=root(b)
    def hits(layer,g):return [(layer,i) for i,p in enumerate(islands[layer]) if p.intersection(g).area>1e-10]
    for drill in drills:
        if not drill['plated']:continue
        # The complete narrow annulus must exist on both faces before a barrel may bridge them.
        r=drill['d']/2; ring=_disk(drill['x'],drill['y'],r+0.02,error).difference(_disk(drill['x'],drill['y'],r+0.005,error))
        group=[]
        for layer in (1,2):
            if ring.difference(coppers[layer]).area>1e-7:
                raise Unsupported('PTH lacks a full 20 um annulus on both layers at '+str((drill['x'],drill['y'])))
            h=hits(layer,ring)
            if len(h)!=1:raise Unsupported('Ambiguous PTH-to-copper contact')
            group.extend(h)
        join(*group)
    pin_roots={}; missing=[]
    for a in anchors:
        x,y=a['x']+dx,a['y']+dy
        if a['d']:
            inner=a['d']/2+0.025;outer=min(a['r']-0.025,inner+0.05)
            if outer<=inner:raise Unsupported('Insufficient land for reliable annulus probe')
            probe=_disk(x,y,outer,error).difference(_disk(x,y,inner,error))
        else:
            probe=_disk(x,y,min(0.10,a['r']/3),error)
        found=[]
        for layer in a['layers']:
            if probe.difference(coppers[layer]).area>1e-7:
                missing.append(a['ref']+'.'+a['pin']+' on layer '+str(layer));continue
            h=hits(layer,probe)
            if len(h)!=1:raise Unsupported('Pad probe crosses multiple copper components')
            found+=h
        if found:
            rr={root(i) for i in found}
            if len(rr)!=1:raise Unsupported('THT land is not bridged across layers')
            pin_roots[(a['ref'],a['pin'],a['net'])]=next(iter(rr))
    if missing:return {'missing_pad_copper':missing,'opens':{},'shorts':{},'islands':len(ids)}
    bynet=defaultdict(set);byisland=defaultdict(set)
    for (ref,pin,net),r in pin_roots.items():bynet[net].add(r);byisland[r].add(net)
    opens={n:len(rs) for n,rs in bynet.items() if len(rs)>1}
    shorts={str(i):sorted(ns) for i,ns in byisland.items() if len(ns)>1}
    unanchored=sorted(str(i) for i in {root(v) for v in ids}-set(byisland))
    return {'missing_pad_copper':[],'opens':opens,'shorts':shorts,'islands':len(ids),
            'anchors':len(pin_roots),'unanchored_components':unanchored,'net_count':len(bynet)}



def _pad_land(anchor, dx=0, dy=0):
    """Resolved copper land envelope; used only for paste overlap, not net bridging."""
    w,h=anchor['width'],anchor['height'];kind=anchor['land_shape']
    if kind=='RECT':
        if anchor.get('land_radius',0):raise Unsupported('Rounded native rectangle not yet validated for full-area paste comparison')
        land=box(-w/2,-h/2,w/2,h/2)
    elif kind in ('ELLIPSE','ROUND'):
        land=affinity.scale(_disk(0,0,1),w/2,h/2,origin=(0,0))
    elif kind=='OVAL':
        r=min(w,h)/2
        line=LineString([(-(w-h)/2,0),((w-h)/2,0)]) if w>=h else LineString([(0,-(h-w)/2),(0,(h-w)/2)])
        land=line.buffer(r,quad_segs=64)
    else: raise Unsupported('Unsupported native paste land shape: '+str(kind))
    land=affinity.rotate(land,anchor['land_angle'],origin=(0,0))
    return affinity.translate(land,anchor['x']+dx,anchor['y']+dy)


def inspect_paste(layer, anchors, dx, dy, report):
    """Check paste presence, not stencil process suitability or full land coverage.

    Custom reduced/notched apertures are legitimate: a complete circular probe
    need not fit. The exact center and positive nearby area must have paste.
    """
    paste=copper_geometry(layer)
    missing=[];tht=[];coverage=[];smt_lands=[]
    for a in anchors:
        land=_pad_land(a,dx,dy)
        overlap=paste.intersection(land).area
        key=a['ref']+'.'+a['pin']
        if a['d']:
            if overlap>1e-7:tht.append({'pad':key,'paste_overlap_mm2':overlap})
        elif 1 in a['layers']:
            smt_lands.append(land)
            center=Point(a['x']+dx,a['y']+dy)
            nearby=_disk(center.x,center.y,min(0.02,a['r']/10))
            present=paste.contains(center) and paste.intersection(nearby).area>1e-8 and overlap>1e-8
            if not present:missing.append(key)
            coverage.append({'pad':key,'center_has_paste':bool(paste.contains(center)),
                             'paste_land_area_fraction':round(overlap/land.area,6)})
    report.test('gerber.paste_smt',bool(coverage) and not missing,
                'Every top SMT pad has paste at its center and positive paste area within its land; reduced/notched apertures accepted',
                {'missing':missing,'smt_pad_count':len(coverage),'coverage':coverage})
    report.test('gerber.paste_tht',not tht,'No top paste overlaps any through-hole copper land',tht)
    reduced=[v for v in coverage if v['paste_land_area_fraction']<0.98]
    report.test('gerber.paste_full_pad',bool(coverage) and not reduced,
                'Requested full-window stencil: paste covers at least 98% of every complete SMT land; reduced apertures are distinct from missing apertures',
                {'minimum_fraction':min((v['paste_land_area_fraction'] for v in coverage),default=0),'below_98_percent':reduced})
    if smt_lands:
        allowed=unary_union(smt_lands).buffer(0.02)
        outside=paste.difference(allowed)
        unassigned=[list(part.bounds) for part in _polygons(paste)
                    if not any(part.intersection(land).area>1e-8 for land in smt_lands)]
        report.test('gerber.paste_extent',outside.area<1e-6 and not unassigned,
                    'Paste stays within SMT land envelopes plus 0.02 mm tolerance and every paste component belongs to an SMT land',
                    {'outside_area_mm2':outside.area,'outside_bounds_mm':list(outside.bounds) if not outside.is_empty else [],
                     'unassigned_aperture_bounds_mm':unassigned})


def inspect_gerber(zip_path, pcb_doc, pcb_comps, footprints, actual_pins, bounds, report):
    """Add physical geometry findings to the parent release Report."""
    try:
        versions={p:importlib.metadata.version(p) for p in ('gerbonara','shapely')}
        if versions!={'gerbonara':'1.6.3','shapely':'2.2.0'}:raise Unsupported('Unvalidated dependency versions: '+str(versions))
        layers,drills,notes,unsupported=_parse_zip(zip_path)
        report.add('gerber.parser','UNVERIFIED' if notes or unsupported else 'PASS','Parsed Gerber and drill data with fixed parser versions',
                   {'versions':versions,'layers':{k:v[0] for k,v in layers.items()},'warnings':notes,'unsupported':unsupported})
        outline=_outline(layers['outline'][1]);gx0,gy0,gx1,gy1=outline.bounds
        outline_ok=abs(gx1-gx0-66)<POSITION_TOL and abs(gy1-gy0-56)<POSITION_TOL
        report.test('gerber.outline',outline_ok,'Gerber centerline outline is one closed 66 × 56 mm rectangle',{'bounds_mm':list(outline.bounds)})
        npth=[(p['x']-gx0,p['y']-gy0,p['d']) for p in drills if p['plated'] is False]
        target=[(5,5,2.7),(61,5,2.7),(5,51,2.7),(61,51,2.7)]
        good=len(npth)==4 and all(any(max(abs(a-b) for a,b in zip(p,q))<POSITION_TOL for q in npth) for p in target)
        report.test('gerber.npth',good,'Four 2.7 mm NPTH mounting holes at required board-relative coordinates',npth)
        anchors,expected=_native_points(pcb_doc,pcb_comps,footprints,actual_pins)
        dx,dy=gx0-bounds[0],gy0-bounds[1]
        matches=_match_holes(expected,drills,dx,dy)
        if matches is None:
            alternatives=[]
            for sx,sy in [(-1,1),(1,-1),(-1,-1)]:
                tx=gx0-(bounds[0] if sx==1 else -bounds[2]);ty=gy0-(bounds[1] if sy==1 else -bounds[3])
                if _match_holes(expected,drills,tx,ty,sx,sy) is not None:alternatives.append([sx,sy,tx,ty])
            report.add('gerber.registration','UNVERIFIED','All native drills must match fabrication coordinates one-to-one with translation only; mirrored alternatives need explicit review',
                       {'native_holes':len(expected),'gerber_holes':len(drills),'mirrored_candidates':alternatives})
            report.add('gerber.actual_copper','UNVERIFIED','Copper net attribution requires verified coordinate registration');return
        report.add('gerber.registration','PASS','All native and exported drill centers, diameters and plating match one-to-one',{'translation_mm':[dx,dy],'holes':len(matches)})
        if 'top_paste' not in layers:
            report.add('gerber.paste_smt','FAIL','Top paste Gerber file is missing')
        else:
            try: inspect_paste(layers['top_paste'][1],anchors,dx,dy,report)
            except Exception as exc: report.add('gerber.paste','UNVERIFIED','Paste interpretation failed: '+str(exc))
        xiao=[p for p in expected if p['ref']=='U1']
        report.test('gerber.xiao_14_tht',len(xiao)==14 and {p['pin'] for p in xiao}=={str(i) for i in range(1,15)},
                    'Exactly 14 XIAO plated holes match the resolved native footprint',xiao)
        if notes or unsupported or not outline_ok:
            report.add('gerber.actual_copper','UNVERIFIED','Parser diagnostics or unsupported geometry must be resolved before copper PASS');return
        results=[]
        for error in (ARC_ERROR,ARC_ERROR/4):
            copper={i:copper_geometry(layers[name][1],error) for i,name in ((1,'top'),(2,'bottom'))}
            # Off-board geometry is preserved, not clipped: otherwise a short could disappear.
            results.append(connectivity(copper,drills,anchors,dx,dy,error))
        if results[0]!=results[1]:
            report.add('gerber.actual_copper','UNVERIFIED','Connectivity changed when curve approximation was refined',results);return
        result=results[1]
        if result.get('unanchored_components'):
            report.add('gerber.unassigned_copper','UNVERIFIED','Copper components with no resolved physical pad require review',result['unanchored_components'])
        report.test('gerber.actual_copper',not result['missing_pad_copper'] and not result['opens'] and not result['shorts'],
                    'Actual copper islands and plated barrels checked against every resolved pad net at two curve resolutions',result)
    except Unsupported as exc:
        report.add('gerber.actual_copper','UNVERIFIED',str(exc))
    except Exception as exc:
        report.add('gerber.actual_copper','UNVERIFIED','Geometry interpretation failed: '+type(exc).__name__+': '+str(exc))
