#!/usr/bin/env python3
"""Fail-closed offline release checks for the Mianguang V0.2 carrier.

Reads only release inputs. Reports are written only when --output is supplied.
PASS means the implemented checks passed; it is not fabrication authorization.
"""
import argparse
import collections
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re
import sys
import zipfile

MIL = 0.0254
CORE = {
    'U1': {'14':'5V_MCU','13':'GND','12':'3V3','7':'MCU_TX','8':'MCU_RX',
           '3':'LED_PWM','2':'BUTTON_N','5':'I2C_SDA','6':'I2C_SCL'},
    'J1': {'1':'5V_IN','2':'GND'}, 'F1': {'1':'5V_IN','2':'5V_SYS'},
    'D1': {'1':'5V_ISO','2':'5V_SYS'}, 'JP1': {'1':'5V_ISO','2':'5V_MCU'},
    'D2': {'1':'5V_SYS','2':'GND'}, 'C1': {'1':'5V_SYS','2':'GND'},
    'C2': {'1':'5V_SYS','2':'GND'},
    'C4': {'1':'5V_SYS','2':'GND'}, 'C5': {'1':'5V_SYS','2':'GND'},
    'J2': {'1':'5V_SYS','2':'GND','3':'RADAR_RX','4':'RADAR_TX'},
    'J3': {'1':'5V_SYS','2':'LED_LOW'},
    'Q1': {'1':'LED_GATE','2':'GND','3':'LED_LOW'},
    'R1': {'1':'LED_PWM','2':'LED_GATE'}, 'R2': {'1':'LED_GATE','2':'GND'},
    'J4': {'1':'BUTTON_N','2':'GND'}, 'R3': {'1':'3V3','2':'BUTTON_N'},
    'C3': {'1':'BUTTON_N','2':'GND'},
    'J5': {'1':'3V3','2':'GND','3':'I2C_SDA','4':'I2C_SCL'},
    'R4': {'1':'MCU_TX'}, 'R5': {'1':'MCU_RX'},
}
PARTS = {'F1': ('1206L110/16WR','C3761685'),
         'D1': ('SS14','C2480'), 'Q1': ('AO3400A','C20917')}


class Report:
    def __init__(self, context=None):
        self.checks = []
        self.context = context or {}

    def add(self, key, status, detail, evidence=None):
        item = dict(id=key, status=status, detail=detail)
        if evidence is not None:
            item['evidence'] = evidence
        self.checks.append(item)

    def test(self, key, condition, detail, evidence=None):
        self.add(key, 'PASS' if condition else 'FAIL', detail, evidence)

    def result(self):
        states = {c['status'] for c in self.checks}
        status = 'FAIL' if 'FAIL' in states else ('UNVERIFIED' if 'UNVERIFIED' in states else 'PASS')
        return dict(status=status, counts=dict(collections.Counter(c['status'] for c in self.checks)),
                    context=self.context,
                    checks=self.checks,
                    scope='Offline consistency and geometry checks; no physical assembly, electrical or EMC validation.')


def native_documents(source, origin=''):
    """Parse newline native sources; same-UUID repeated headers do not lose pads."""
    docs, current = {}, None
    for line_no, line in enumerate(source.splitlines(), 1):
        if '||' not in line:
            continue
        head, payload = line.split('||', 1)
        try:
            h = json.loads(head)
            raw = payload.rstrip('|')
            # Native project archives retain deleted records as header|||
            # tombstones. They delete the earlier ID, rather than merely vanish.
            d = json.loads(raw) if raw.strip() else None
        except (ValueError, TypeError) as exc:
            raise ValueError(f'{origin}:{line_no}: invalid native record: {exc}') from exc
        if h.get('type') == 'DOCHEAD':
            if not isinstance(d,dict):
                raise ValueError(f'{origin}:{line_no}: empty document header')
            current = (d.get('docType'), d.get('uuid'))
            if current not in docs:
                docs[current] = {'head': d, 'records': [], 'origin': origin}
            else:
                docs[current]['head'] = d
        elif current is not None:
            docs[current]['records'].append((h, d, line_no))
    # Repeated record IDs in native sources are last-write-wins.
    for doc in docs.values():
        unique = {}
        for i, rec in enumerate(doc['records']):
            key=(rec[0].get('type'), rec[0].get('id', f'__{i}'))
            if rec[1] is None:
                unique.pop(key,None)
            else:
                unique[key] = rec
        doc['records'] = list(unique.values())
    return list(docs.values())


def unwrap_json(value):
    if isinstance(value, dict) and 'result' in value and 'success' in value:
        if value['success'] is False:
            raise ValueError('export wrapper reports success=false')
        return value['result']
    return value


def source_strings(obj):
    if isinstance(obj, str) and '||' in obj and 'DOCHEAD' in obj:
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from source_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from source_strings(v)


def inventory(root):
    docs, nets, boms, gerbers = [], [], [], []
    for path in sorted(root.rglob('*')):
        if not path.is_file() or path.name.startswith('.'):
            continue
        rel = str(path.relative_to(root))
        suffix = path.suffix.lower()
        if suffix in ('.zip', '.epro2'):
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                if any(re.search(r'\.(gtl|gbl|gbr|ger|gko|gm1)$', n, re.I) for n in names):
                    gerbers.append(path)
                for info in archive.infolist():
                    if info.file_size > 100_000_000:
                        raise ValueError(f'oversized archive member: {rel}!{info.filename}')
                    if Path(info.filename).suffix.lower() in ('.epru','.esch','.epcb','.efoo'):
                        docs.extend(native_documents(archive.read(info).decode('utf-8-sig'), rel+'!'+info.filename))
        elif suffix in ('.esch','.epcb','.epru','.efoo','.esch2','.epcb2'):
            docs.extend(native_documents(path.read_text(encoding='utf-8-sig'), rel))
        elif suffix == '.json' and path.name != 'manifest.json':
            obj = unwrap_json(json.loads(path.read_text(encoding='utf-8-sig')))
            if isinstance(obj, str):
                try:
                    obj = json.loads(obj)
                except ValueError:
                    pass
            if isinstance(obj, dict) and isinstance(obj.get('components'), dict):
                nets.append((rel, obj))
            for source in source_strings(obj):
                docs.extend(native_documents(source, rel))
        elif suffix in ('.csv','.tsv') and 'bom' in path.name.lower():
            text = path.read_text(encoding='utf-8-sig')
            if text.strip():
                dialect = '\t' if '\t' in text.splitlines()[0] else ','
                rows=list(csv.DictReader(io.StringIO(text), delimiter=dialect))
                # Supplementary external-parts lists are retained in the manifest,
                # but are not mistaken for the electrical PCB BOM.
                if rows and any(k in rows[0] for k in ('Designator','Reference')):
                    boms.append((rel,rows))
    return docs, nets, boms, gerbers


def attributes(doc):
    comps = {}
    for h,d,_ in doc['records']:
        if h['type'] == 'COMPONENT':
            comps[h['id']] = {'id':h['id'], 'data':d, 'props':dict(d.get('attrs',{}))}
    for h,d,_ in doc['records']:
        if h['type'] == 'ATTR' and d.get('parentId') in comps:
            comps[d['parentId']]['props'][d['key']] = d.get('value')
    return {str(c['props']['Designator']):c for c in comps.values() if c['props'].get('Designator')}


def net_components(netlist):
    result = {}
    for key, comp in netlist['components'].items():
        props = comp.get('props', {})
        ref = props.get('Designator')
        if not ref:
            continue
        if ref in result:
            raise ValueError(f'duplicate designator in netlist: {ref}')
        result[ref] = {'props':props, 'pins':{str(p):str(v.get('net') or '')
                          for p,v in comp.get('pinInfoMap',{}).items()}}
    return result


def normalized_net_components(comps):
    """Resolve SCH display formulas and PCB-specific representation defaults."""
    result={}
    for ref,c in comps.items():
        props=dict(c['props'])
        name=props.get('Name')
        if isinstance(name,str) and re.fullmatch(r'=\{[^}]+\}',name):
            props['Name']=props.get(name[2:-1],'')
        # A PCB export has no schematic symbol field and resolves the default
        # placement side. Actual placement side is independently checked.
        props.pop('Symbol',None)
        if props.get('PCB Layer')=='Default':props['PCB Layer']='TopLayer'
        result[ref]={'pins':dict(c['pins']),'props':props}
    return result


def pcb_nets(doc, comps):
    ids = {v['id']:k for k,v in comps.items()}
    pins, primitives = collections.defaultdict(lambda:collections.defaultdict(set)), []
    for h,d,_ in doc['records']:
        if h['type'] != 'PAD_NET':
            continue
        key = json.loads(h['id'])
        if len(key) < 4 or key[1] not in ids:
            continue
        ref, pin, primitive = ids[key[1]], str(key[2]), key[3]
        pins[ref][pin].add(str(d.get('padNet') or ''))
        primitives.append((ref,pin,primitive,str(d.get('padNet') or '')))
    return pins, primitives


def check_manifest(root, report, version):
    path = root/'manifest.json'
    if not path.exists():
        report.add('manifest.present','FAIL','manifest.json missing')
        return None
    manifest = json.loads(path.read_text(encoding='utf-8-sig'))
    got_version = str(manifest.get('release',manifest.get('version','')))
    report.test('manifest.version', got_version.lower().lstrip('v') == version.lower().lstrip('v'),
                f'expected release {version}; got {got_version!r}')
    entries = manifest.get('files', [])
    if isinstance(entries, dict):
        entries = [dict(v,path=k) if isinstance(v,dict) else {'path':k,'sha256':v} for k,v in entries.items()]
    listed, errors = set(), []
    for entry in entries:
        rel = entry.get('path',entry.get('file',''))
        candidate = root/rel
        if not rel or Path(rel).is_absolute() or not candidate.resolve().is_relative_to(root.resolve()):
            errors.append(f'invalid relative manifest path: {rel!r}')
            continue
        if rel in listed:
            errors.append(f'duplicate entry: {rel}')
        listed.add(rel)
        if rel == 'manifest.json':
            errors.append('manifest must not hash itself')
        if not candidate.is_file():
            errors.append(f'missing {rel}')
            continue
        data = candidate.read_bytes()
        expected_hash = str(entry.get('sha256','')).lower()
        actual_hash = hashlib.sha256(data).hexdigest()
        if not re.fullmatch('[0-9a-f]{64}',expected_hash) or actual_hash != expected_hash:
            errors.append(f'SHA-256 mismatch or missing: {rel}')
        size = entry.get('bytes',entry.get('size'))
        if size is None or int(size) != len(data):
            errors.append(f'byte count mismatch or missing: {rel}')
    actual = {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()
              and not p.name.startswith('.') and p.name != 'manifest.json'}
    missing = actual-listed
    report.test('manifest.files',bool(entries) and not errors and not missing,
                'All exported files must be listed with matching hash and byte count.',
                {'errors':errors,'unlisted':sorted(missing),'file_count':len(listed)})
    return manifest


def select_document(docs, kind, report):
    choices = [d for d in docs if d['head'].get('docType') == kind and 'U1' in attributes(d)]
    if not choices:
        report.add('source.'+kind.lower(), 'FAIL', f'No {kind} source with U1 found')
        return None
    # Prefer standalone source. A full project serializes extra editor UI/defaults
    # absent from an individual document, so compare the design records rather
    # than pixel colours, placeholder counters, or saved tool settings.
    choices.sort(key=lambda d:('!' in d['origin'],d['origin']))
    fingerprints = set()
    ignored={'CANVAS','PREFERENCE','ACTIVE_LAYER','PRIMITIVE','META','ELE_PLACEHOLDER',
             'LAYER','RULE','RULE_SELECTOR','RULE_TEMPLATE','SILK_OPTS','D3_ATTRIBUTE'}
    symbol_pins={d['head']['uuid']:{h['id'] for h,v,_ in d['records'] if h['type']=='PIN'}
                 for d in docs if d['head'].get('docType')=='SYMBOL'}
    ignored_nc={}
    for d in choices:
        semantic=[]
        component_pins={c['id']:symbol_pins[c['props']['Symbol']]
                        for c in attributes(d).values() if c['props'].get('Symbol') in symbol_pins}
        for h,data,_ in d['records']:
            if h.get('type') in ignored:
                continue
            if h.get('type')=='ATTR' and data.get('key')=='NO_CONNECT':
                parent=str(data.get('parentId',''))
                cid,separator,pid=parent.rpartition('-')
                if separator and cid in component_pins and pid not in component_pins[cid]:
                    # Full projects can retain attributes of deleted symbol
                    # pins; a standalone SCH source omits these dead records.
                    ignored_nc.setdefault(d['origin'],[]).append(parent)
                    continue
            data=dict(data)
            data.pop('zIndex',None)
            if data.get('strikeout') is False:data.pop('strikeout')
            if h.get('type')=='COMPONENT':
                attrs=dict(data.get('attrs',{}))
                attrs.pop('DeviceName',None);attrs.pop('FootprintName',None)
                if attrs.get('isSwitchClose') is False:attrs.pop('isSwitchClose')
                data['attrs']=attrs
            if h.get('type')=='LAYER_PHYS':
                data={k:v for k,v in data.items() if not(k in ('lossTangent','permittivity') and v in (None,0))}
            semantic.append((h.get('type'),h.get('id'),data))
        fingerprints.add(json.dumps(sorted(semantic,key=lambda x:(str(x[0]),str(x[1]))),sort_keys=True))
    report.test('source.'+kind.lower()+'.copies',len(fingerprints)==1,
                f'{len(choices)} exported {kind} copies must contain the same geometry, electrical and annotation records',
                {'sources':[d['origin'] for d in choices],
                 'ignored_no_connect_attributes_of_deleted_pins':ignored_nc})
    return choices[0]


def check_networks(comps, report):
    errors = []
    for ref,pins in CORE.items():
        for pin,expected in pins.items():
            got = comps.get(ref,{}).get('pins',{}).get(pin)
            if got != expected:
                errors.append(f'{ref}.{pin}: expected {expected}, got {got!r}')
    report.test('netlist.core',not errors,'Core power, radar, lamp, button and I2C pin assignments',errors)
    allpins = {(ref,p):net for ref,c in comps.items() for p,net in c['pins'].items()}
    for jp,res,far in [('JP2','R4','RADAR_RX'),('JP3','R5','RADAR_TX')]:
        pins = comps.get(jp,{}).get('pins',{})
        near = allpins.get((res,'2'))
        ok = bool(near) and near != far and len(pins)==2 and set(pins.values())=={near,far}
        # The new middle segment may join test points, but not any other core endpoint.
        foreign = [(r,p) for (r,p),net in allpins.items() if net==near and r in CORE and (r,p)!=(res,'2')]
        report.test('netlist.'+jp.lower(),ok and not foreign,
                    f'{res}.2 -- {jp} -- {far}; removing the shunt must separate the two segments',
                    {'near':near,'jumper':pins,'unexpected_core_pins':foreign})
    unused = {p:n for p,n in comps.get('U1',{}).get('pins',{}).items() if p.isdigit() and int(p)>14 and n}
    report.test('netlist.xiao_bottom_nc',not unused,'U1 pins above 14 must be absent or NC',unused)
    distinct = ['5V_IN','5V_SYS','5V_ISO','5V_MCU','MCU_TX','MCU_RX','RADAR_RX','RADAR_TX']
    report.test('netlist.named_domains',all(n in allpins.values() for n in distinct),
                'Power and UART segments must remain distinct named nets')


def check_parts(comps, sch, pcb, boms, report):
    for ref,(part,supplier) in PARTS.items():
        nprops = comps.get(ref,{}).get('props',{})
        sprops = sch.get(ref,{}).get('props',{})
        for source,props in [('netlist',nprops),('schematic',sprops)]:
            report.test(f'parts.{ref}.{source}',props.get('Manufacturer Part')==part and props.get('Supplier Part')==supplier,
                        f'{ref} must be {part} / {supplier}',
                        {k:props.get(k) for k in ('Manufacturer Part','Supplier Part')})
        pprops = pcb.get(ref,{}).get('props',{})
        report.test(f'parts.{ref}.pcb_device',bool(pprops.get('Device')) and pprops.get('Device')==nprops.get('Device'),
                    'PCB Device ID must match the final schematic netlist',
                    {'pcb':pprops.get('Device'),'netlist':nprops.get('Device')})
    report.test('bom.present',bool(boms),'At least one BOM CSV/TSV is required')
    for origin,rows in boms:
        refs,duplicates,quantity_errors = {},[],[]
        for row in rows:
            row_refs=[ref for ref in re.split(r'[,;\s]+',row.get('Designator',row.get('Reference','')).strip()) if ref]
            if 'Quantity' in row:
                quantity=str(row['Quantity']).strip()
                if not quantity.isdigit() or int(quantity)!=len(row_refs):
                    quantity_errors.append(f'Quantity {quantity!r} does not match references {row_refs}')
            for ref in row_refs:
                if ref:
                    if ref in refs:
                        duplicates.append(ref)
                    refs[ref] = row
        errors = ['duplicate BOM reference '+ref for ref in duplicates]+quantity_errors
        for ref,(part,supplier) in PARTS.items():
            row=refs.get(ref,{})
            if row.get('Manufacturer Part')!=part or row.get('Supplier Part')!=supplier:
                errors.append(f'{ref} incorrect or missing ({part}/{supplier})')
        for ref in ('U1','JP1','JP2','JP3'):
            if ref not in refs:
                errors.append(ref+' missing')
        expected={ref for ref,c in comps.items()
                  if c['props'].get('Convert to PCB','yes')=='yes'
                  and c['props'].get('Add into BOM','yes')=='yes'}
        if set(refs)!=expected:
            errors.append('Reference set mismatch: missing '+str(sorted(expected-set(refs)))+
                          '; unexpected '+str(sorted(set(refs)-expected)))
        fields={'Value':'Value','Manufacturer Part':'Manufacturer Part',
                'Manufacturer':'Manufacturer','Supplier Part':'Supplier Part',
                'Supplier':'Supplier','Footprint':'FootprintName'}
        for ref in sorted(expected & refs.keys()):
            row,props=refs[ref],comps[ref]['props']
            if not str(props.get('FootprintName') or '').strip():
                errors.append(ref+' missing resolved FootprintName in netlist')
            for column,prop in fields.items():
                if column not in row:
                    errors.append(f'{ref} missing BOM column {column}')
                    continue
                actual='' if row[column] is None else str(row[column]).strip()
                wanted='' if props.get(prop) is None else str(props[prop]).strip()
                if actual!=wanted:
                    errors.append(f'{ref} {column}: BOM {actual!r}, netlist {wanted!r}')
        report.test('bom.parts.'+origin,not errors,
                    'BOM quantities, references and all value/purchase/footprint fields match the final netlist',errors)
    uprops = comps.get('U1',{}).get('props',{})
    report.test('parts.xiao_metadata','QFN' not in str(uprops.get('Supplier Footprint','')).upper(),
                'XIAO module must not retain QFN chip-package supplier metadata')


def footprint_id(comp):
    return str(comp.get('props',{}).get('Footprint','')).split('|')[0]


def check_pad_references(pcb,footprints,pad_records,report):
    errors,unresolved=[],[]
    for ref,comp in pcb.items():
        doc=footprints.get(footprint_id(comp))
        if doc is None:
            unresolved.append(ref+' footprint '+footprint_id(comp))
            continue
        pads={h['id']:str(d.get('num')) for h,d,_ in doc['records'] if h['type']=='PAD'}
        for r,p,primitive,net in pad_records:
            if r==ref and pads.get(primitive)!=p:
                errors.append(f'{ref}.{p}: PAD_NET primitive {primitive} is absent or has a different pad number')
    report.test('pcb.pad_primitive_references',not errors,
                'PAD_NET primitive IDs must resolve to the final physical footprint pads',errors)
    report.add('pcb.footprint_sources','UNVERIFIED' if unresolved else 'PASS',
               'All component footprint sources are needed for independent physical copper verification',unresolved)


def dimension(value, name):
    if isinstance(value,dict):
        return float(value.get(name,0))*MIL
    if isinstance(value,list) and len(value)>1:
        return float(value[1 if name=='width' else 2])*MIL
    return 0.0


def check_xiao(pcb, footprints, pins, report):
    uid = footprint_id(pcb.get('U1',{}))
    doc = footprints.get(uid)
    if not doc:
        report.add('xiao.footprint_source','FAIL',f'Final U1 footprint source not found: {uid}')
        return None
    pads=[(h,d) for h,d,_ in doc['records'] if h['type']=='PAD']
    numbered={str(d.get('num')):d for h,d in pads}
    correct = (len(pads)==14 and set(numbered)=={str(i) for i in range(1,15)}
               and all(d.get('layerId')==12 and d.get('plated') is True
                       and dimension(d.get('hole'),'width')>0 for h,d in pads))
    report.test('xiao.only_14_tht',correct,'Exactly 14 uniquely numbered plated through-hole pads; no underside/SMD duplicates',
                {'source':doc['origin'],'footprint':uid,'pad_count':len(pads),
                 'pads':[{k:d.get(k) for k in ('num','layerId','plated','hole')} for h,d in pads]})
    badpcb={p:sorted(n) for p,n in pins.get('U1',{}).items() if p not in numbered}
    report.test('xiao.no_removed_pad_nets',not badpcb,'PCB must not retain PAD_NET entries for removed pad numbers',badpcb)
    geom_errors=[]
    if correct:
        left=[numbered[str(i)] for i in range(1,8)]
        right=[numbered[str(i)] for i in range(14,7,-1)]
        # Accept rotation of the footprint coordinate system but not pin permutation.
        step=(left[1]['centerX']-left[0]['centerX'],left[1]['centerY']-left[0]['centerY'])
        if abs(math.hypot(*step)*MIL-2.54)>.02:
            geom_errors.append('same-row pitch is not 2.54 mm')
        across=(right[0]['centerX']-left[0]['centerX'],right[0]['centerY']-left[0]['centerY'])
        if abs(math.hypot(*across)*MIL-15.24)>.02 or abs(step[0]*across[0]+step[1]*across[1])*MIL*MIL>.02:
            geom_errors.append('rows are not perpendicular and 15.24 mm apart')
        for i,(a,b) in enumerate(zip(left,right)):
            for point,base in [(a,left[0]),(b,right[0])]:
                if math.hypot(point['centerX']-base['centerX']-i*step[0],point['centerY']-base['centerY']-i*step[1])*MIL>.02:
                    geom_errors.append('incorrect sequence or position for pad '+str(point['num']))
        for _,d in pads:
            hole=dimension(d['hole'],'width')
            land=min(dimension(d['defaultPad'],'width'),dimension(d['defaultPad'],'height'))
            if not .85<=hole<=1.2 or (land-hole)/2<.15:
                geom_errors.append(f'pad {d["num"]}: drill {hole:.3f}, annular ring {(land-hole)/2:.3f} mm')
    else:
        geom_errors.append('requires exactly 14 THT pads before geometry can be checked')
    report.test('xiao.pitch_drills',not geom_errors,'15.24 mm rows, 2.54 mm pitch, conservative drill/ring bounds',geom_errors)
    return doc


def outline_geometry(pcb_doc):
    paths=[]
    for h,d,_ in pcb_doc['records']:
        if d.get('layerId')!=11:
            continue
        if h['type']=='POLY':
            p=d.get('path',[])
            if any(isinstance(v,str) and v!='L' for v in p):
                raise ValueError('curved/nonlinear native outline not supported by rectangle check')
            values=[v for v in p if isinstance(v,(int,float))]
            if len(values)%2:
                raise ValueError('odd outline coordinate count')
            points=list(zip(values[::2],values[1::2]))
            paths.extend(zip(points,points[1:]))
        elif h['type']=='LINE':
            paths.append(((d['startX'],d['startY']),(d['endX'],d['endY'])))
    if not paths:
        raise ValueError('no board outline geometry')
    points=[tuple(round(v*MIL,5) for v in p) for seg in paths for p in seg]
    bounds=(min(p[0] for p in points),min(p[1] for p in points),max(p[0] for p in points),max(p[1] for p in points))
    degree=collections.Counter(points)
    return bounds,paths,degree


def round_slot_hole(data):
    """Return (x, y, diameter) mm for a native, drill-exportable round cutout.

    EasyEDA Pro >=1.9 exports multi-layer circular slot regions <=6.5 mm
    to NPTH drills. Other paths remain unsupported; outline stroke width
    is not part of the cutout diameter.
    https://prodocs.lceda.cn/cn/pcb/place-slot-region/index.html
    """
    path=data.get('path')
    if (data.get('layerId')!=12 or data.get('fillStyle')!='SOLID'
            or data.get('netName') or data.get('networkList')
            or data.get('isBridgingCopper')
            or not isinstance(path,list) or len(path)!=1
            or not isinstance(path[0],list) or len(path[0])!=4
            or path[0][0]!='CIRCLE'):
        raise ValueError('Unsupported mechanical cutout: requires one unnetted solid multi-layer CIRCLE')
    x,y,r=path[0][1:]
    if not all(type(v) in (int,float) and math.isfinite(v) for v in (x,y,r)):
        raise ValueError('Non-finite/non-numeric circular cutout geometry')
    diameter=2*r*MIL
    if not 0<diameter<=6.5:
        raise ValueError('Circular cutout outside supported NPTH drill diameter (0, 6.5] mm')
    return x*MIL,y*MIL,diameter


def check_board(pcb_doc,report):
    try:
        bounds,paths,degree=outline_geometry(pcb_doc)
        x0,y0,x1,y1=bounds
        rect=all(abs(a[0]-b[0])<.01 or abs(a[1]-b[1])<.01 for a,b in paths)
        graph=collections.defaultdict(set)
        for a,b in paths:
            a=tuple(round(v*MIL,5) for v in a)
            b=tuple(round(v*MIL,5) for v in b)
            graph[a].add(b);graph[b].add(a)
        reached=set();pending=[next(iter(graph))]
        while pending:
            node=pending.pop()
            if node not in reached:
                reached.add(node);pending.extend(graph[node]-reached)
        on_perimeter=all(min(abs(x-x0),abs(x-x1),abs(y-y0),abs(y-y1))<.02 for x,y in graph)
        perimeter=sum(math.dist(a,b)*MIL for a,b in paths)
        ok=(abs(x1-x0-66)<.02 and abs(y1-y0-56)<.02 and rect and on_perimeter
            and all(v==2 for v in degree.values()) and len(reached)==len(graph)
            and abs(perimeter-244)<.04)
        report.test('board.outline',ok,'Closed 66 × 56 mm rectangular outline',{'bounds_mm':bounds,'segments':len(paths)})
    except ValueError as exc:
        report.add('board.outline','UNVERIFIED',str(exc));return None
    holes=[];unsupported=[]
    for h,d,_ in pcb_doc['records']:
        if h['type']=='PAD' and d.get('plated') is False and dimension(d.get('hole'),'width')>0:
            holes.append((d['centerX']*MIL-x0,d['centerY']*MIL-y0,dimension(d['hole'],'width')))
        elif h['type']=='FILL' and d.get('layerId')==12:
            try:
                x,y,dia=round_slot_hole(d)
                holes.append((x-x0,y-y0,dia))
            except ValueError as exc:
                unsupported.append({'id':h['id'],'reason':str(exc)})
    if unsupported:
        report.add('board.npth','UNVERIFIED','Unsupported native mechanical cutout geometry',unsupported)
        return bounds
    expected=[(5,5,2.7),(61,5,2.7),(5,51,2.7),(61,51,2.7)]
    missing=[p for p in expected if not any(max(abs(a-b) for a,b in zip(p,q))<.02 for q in holes)]
    report.test('board.npth',not missing and len(holes)==4,'Four 2.7 mm NPTH mounting holes at (5,5), (61,5), (5,51), (61,51)',
                {'holes_mm':holes,'missing':missing})
    return bounds


def check_version(sch_doc,pcb_doc,report,version):
    target=version.lower().lstrip('v')
    sch_versions=[str(d.get('value')) for h,d,_ in sch_doc['records'] if h['type']=='ATTR' and d.get('key')=='Version']
    sch_labels=[str(d.get('text',d.get('value',''))) for h,d,_ in sch_doc['records'] if h['type'] in ('STRING','TEXT')]
    sch_text_versions=[v for s in sch_labels for v in re.findall(r'\bV(\d+\.\d+(?:\.\d+)?)\b',s,re.I)]
    report.test('version.schematic',bool(sch_versions) and
                all(v.lower().lstrip('v')==target for v in sch_versions) and
                all(v==target for v in sch_text_versions),
                f'Schematic title and drawing annotations must use {version}',
                {'title_block':sch_versions,'annotations':sch_text_versions})
    labels=[str(d.get('text',d.get('value',''))) for h,d,_ in pcb_doc['records'] if h['type'] in ('STRING','TEXT')]
    versions=[v for s in labels for v in re.findall(r'\bV(\d+\.\d+(?:\.\d+)?)\b',s,re.I)]
    report.test('version.pcb',bool(versions) and all(v==target for v in versions),
                f'PCB version silkscreen must be {version}',versions)


def check_native_checks(root,report,version):
    """Require fresh, strict, warning-free EDA evidence bound to exported sources.

    This checks the recorded evidence, not EDA itself. The final export must
    record strict=true and source_sha256 mapping every .esch/.epcb/.epro2
    relative path to SHA-256. The full project binds embedded library geometry
    that can change without changing a standalone PCB's footprint UUID.
    Older releases intentionally retaining warnings use the default offline
    mode; they cannot pass this opt-in pre-fabrication gate.
    """
    path=root/'native_checks.json'
    if not path.is_file():
        report.add('native.present','FAIL','native_checks.json is required for a clean native EDA release')
        return
    try:
        raw=path.read_bytes()
        native=json.loads(raw.decode('utf-8-sig'))
        if not isinstance(native,dict):
            raise ValueError('native check record must be an object')
    except (UnicodeDecodeError,ValueError) as exc:
        report.add('native.parse','FAIL',f'Invalid native check record: {exc}')
        return
    report.context['native_checks_sha256']=hashlib.sha256(raw).hexdigest()
    report.test('native.version',str(native.get('release','')).lower().lstrip('v')==version.lower().lstrip('v'),
                'Native check release must match the requested release',native.get('release'))
    report.test('native.strict',native.get('strict') is True,
                'The native run must explicitly record strict=true',native.get('strict'))
    for domain in ('schematic','pcb'):
        result=native.get(domain)
        clean=(isinstance(result,dict) and result.get('passed') is True and
               isinstance(result.get('details'),list) and result['details']==[])
        report.test('native.'+domain+'.clean',clean,
                    'Native strict DRC must return boolean true and an empty detailed error list',result)
    source_types={'.esch','.epcb','.epro2'}
    sources=sorted(p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in source_types)
    expected={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    kinds={p.suffix.lower() for p in sources}
    reported=native.get('source_sha256')
    report.test('native.source_binding',kinds==source_types and
                isinstance(reported,dict) and reported==expected,
                'Native check evidence must bind final schematic, PCB and complete project sources by SHA-256',
                {'expected':expected,'reported':reported})


def run(root,version='V0.2',require_native_clean=False):
    context={'release_directory':str(root),'expected_version':version,
             'require_native_clean':require_native_clean}
    if (root/'manifest.json').is_file():
        context['manifest_sha256']=hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest()
    report=Report(context)
    if not root.is_dir():
        report.add('release.present','FAIL',f'Release directory missing: {root}')
        return report.result()
    check_manifest(root,report,version)
    if require_native_clean:
        check_native_checks(root,report,version)
    docs,nets,boms,gerbers=inventory(root)
    sch_doc=select_document(docs,'SCH_PAGE',report)
    pcb_doc=select_document(docs,'PCB',report)
    footprints={}
    for d in docs:
        if d['head'].get('docType')=='FOOTPRINT':
            uid=d['head'].get('uuid')
            # Standalone final footprint exports override a package copy only if identical.
            if uid in footprints:
                a=[(h['type'],h.get('id'),v) for h,v,_ in footprints[uid]['records'] if h['type']=='PAD']
                b=[(h['type'],h.get('id'),v) for h,v,_ in d['records'] if h['type']=='PAD']
                report.test('footprint.copies.'+str(uid),a==b,'Repeated footprint sources must have identical pads',
                            [footprints[uid]['origin'],d['origin']])
            footprints[uid]=d
    report.test('netlist.present',bool(nets),'At least one exported schematic netlist JSON is required')
    if not nets or not sch_doc or not pcb_doc:
        return report.result()
    candidates=[(name,net_components(n)) for name,n in nets if 'U1' in net_components(n)]
    if not candidates:
        report.add('netlist.carrier','FAIL','No netlist contains U1');return report.result()
    candidates.sort(key=lambda item:('schematic' not in item[0].lower(),'pcb' in item[0].lower(),item[0]))
    name,comps=candidates[0]
    for other,values in candidates[1:]:
        a,b=normalized_net_components(comps),normalized_net_components(values)
        different=[ref for ref in a.keys()|b.keys() if a.get(ref)!=b.get(ref)]
        report.test('netlist.copies.'+other,not different,
                    'SCH/PCB netlists agree after display-formula and placement-default normalization',
                    {'sources':[name,other],'different_designators':sorted(different)})
    sch,pcb=attributes(sch_doc),attributes(pcb_doc)
    check_networks(comps,report)
    check_parts(comps,sch,pcb,boms,report)
    actual,pad_records=pcb_nets(pcb_doc,pcb)
    check_pad_references(pcb,footprints,pad_records,report)
    errors=[]
    for ref,c in comps.items():
        if ref not in pcb:
            if c['props'].get('Convert to PCB','yes')=='yes':
                errors.append(f'{ref} missing from PCB')
            continue
        for pin,net in c['pins'].items():
            if net and actual.get(ref,{}).get(pin)!={net}:
                errors.append(f'{ref}.{pin}: schematic {net!r}, PCB {sorted(actual.get(ref,{}).get(pin,set()))}')
    for ref,pin,primitive,net in pad_records:
        if net and comps.get(ref,{}).get('pins',{}).get(pin)!=net:
            errors.append(f'extra/stale PCB pad net: {ref}.{pin}/{primitive}={net}')
    report.test('pcb.netlist_matches',not errors,'Every physical PCB PAD_NET must agree with schematic pin net',errors)
    # Device names alone cannot verify a physical footprint; resolved library geometry is required.
    check_xiao(pcb,footprints,actual,report)
    bounds=check_board(pcb_doc,report)
    check_version(sch_doc,pcb_doc,report,version)
    report.test('gerber.present',len(gerbers)==1,'Exactly one Gerber manufacturing ZIP is required',[str(p.relative_to(root)) for p in gerbers])
    if len(gerbers)==1 and bounds:
        try:
            from gerber_checks import inspect_gerber
            inspect_gerber(gerbers[0],pcb_doc,pcb,footprints,actual,bounds,report)
        except ImportError as exc:
            report.add('gerber.actual_copper','UNVERIFIED',f'Gerber geometry dependency unavailable: {exc}')
    return report.result()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('release',nargs='?',default=str(Path(__file__).resolve().parents[1]/'release_v02'))
    parser.add_argument('--version',default='V0.2')
    parser.add_argument('--require-native-clean',action='store_true',
                        help='Require strict, warning-free SCH/PCB native checks bound to final source hashes')
    parser.add_argument('--output',type=Path,help='Write JSON report (default: stdout only)')
    args=parser.parse_args()
    try:
        result=run(Path(args.release).resolve(),args.version,args.require_native_clean)
    except Exception as exc:
        result={'status':'FAIL','checks':[{'id':'input.parse','status':'FAIL','detail':f'{type(exc).__name__}: {exc}'}]}
    text=json.dumps(result,ensure_ascii=False,indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(text+'\n',encoding='utf-8')
    print(text)
    return {'PASS':0,'FAIL':1,'UNVERIFIED':2}[result['status']]


if __name__=='__main__':
    sys.exit(main())
