#!/usr/bin/env python3
"""Derive SMT upload CSVs from the frozen V0.3 release, without editing it."""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import zipfile

PCB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PCB / 'qa'))
from check_release import attributes, footprint_id, native_documents

SOURCE = PCB / 'release_v03'
OUT = PCB / 'preflight_v03' / 'smt'
SMT = set('C1 C2 C3 C4 C5 D1 D2 F1 Q1 R1 R2 R3 R4 R5'.split())
MANUAL = set('J1 J2 J3 J4 J5 JP1 JP2 JP3 U1'.split())
BOM_NAME = 'BOM_Mianguang_V0.3.csv'
CPL_NAME = 'PickPlace_Mianguang_V0.3.csv'
PROJECT_NAME = 'Mianguang_V0.3.epro2'
CPL_FIELDS = ['Designator', 'Mid X', 'Mid Y', 'Layer', 'Rotation']
BOM_MAP = {'Comment': 'Comment', 'Designator': 'Designator',
           'Footprint': 'Footprint', 'Quantity': 'Quantity',
           '嘉立创元件编号': 'Supplier Part', 'Manufacturer Part': 'Manufacturer Part'}
GUIDES = [
    'https://www.jlc.com/portal/server_guide_48022.html',
    'https://jlcpcb.com/help/article/pick-place-file-for-pcb-assembly',
    'https://jlcpcb.com/help/article/bill-of-materials-for-pcb-assembly',
]


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_csv(data):
    return list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))


def csv_bytes(fields, rows):
    text = io.StringIO(newline='')
    writer = csv.DictWriter(text, fieldnames=fields, lineterminator='\r\n')
    writer.writeheader()
    writer.writerows(rows)
    return text.getvalue().encode('utf-8-sig')


def refs(row):
    return row['Designator'].split(',')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', type=Path, default=SOURCE)
    parser.add_argument('--output', type=Path, default=OUT)
    args = parser.parse_args()
    source, out = args.release.resolve(), args.output.resolve()
    require(source != out and source not in out.parents, 'Output must be outside the frozen release')
    require(source == SOURCE or out != OUT,
            'A different release requires a separate --output directory')
    prepare(source, out)


def prepare(source, out):
    manifest_bytes = (source / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    require(manifest['release'] == 'V0.3', 'Not a V0.3 release')
    # Bind and verify the complete frozen release, including the matching Gerber.
    inputs = {entry['path']: (source / entry['path']).read_bytes()
              for entry in manifest['files']}
    for entry in manifest['files']:
        data = inputs[entry['path']]
        require(sha(data) == entry['sha256'] and len(data) == entry['bytes'],
                'Frozen release hash/size mismatch: ' + entry['path'])
    source_hashes = {name: sha(data) for name, data in inputs.items()}
    source_hashes['manifest.json'] = sha(manifest_bytes)
    previous = out / 'validation.json'
    if previous.exists():
        require(json.loads(previous.read_text())['source_sha256'] == source_hashes,
                'Existing SMT package has different sources; choose a new --output directory')

    bom = read_csv(inputs[BOM_NAME])
    cpl = read_csv(inputs[CPL_NAME])
    bom_by_ref = {}
    for row in bom:
        designators = refs(row)
        require(int(row['Quantity']) == len(designators), 'BOM quantity mismatch')
        for ref in designators:
            require(ref not in bom_by_ref, 'Duplicate BOM reference: ' + ref)
            bom_by_ref[ref] = row
    cpl_by_ref = {row['Designator']: row for row in cpl}
    require(len(cpl_by_ref) == len(cpl), 'Duplicate CPL reference')
    require(set(bom_by_ref) == set(cpl_by_ref) == SMT | MANUAL,
            'Source reference set differs from the expected 23 components')
    require(not SMT & MANUAL and len(SMT) + len(MANUAL) == 23,
            'Invalid assembly partition')

    docs = []
    with zipfile.ZipFile(io.BytesIO(inputs[PROJECT_NAME])) as archive:
        for name in archive.namelist():
            if Path(name).suffix.lower() in ('.epru', '.epcb', '.efoo'):
                docs.extend(native_documents(archive.read(name).decode('utf-8-sig'), name))
    pcbs = [d for d in docs if d['head']['docType'] == 'PCB' and 'U1' in attributes(d)]
    require(len(pcbs) == 1, 'Expected one carrier PCB in the project')
    components = attributes(pcbs[0])
    require(set(components) == SMT | MANUAL, 'Project component set mismatch')
    footprints = {d['head']['uuid']: d for d in docs if d['head']['docType'] == 'FOOTPRINT'}
    pad_counts = {}
    for ref, comp in components.items():
        footprint = footprints[footprint_id(comp)]
        pads = [p for h, p, _ in footprint['records'] if h['type'] == 'PAD']
        pad_counts[ref] = len(pads)
        row = cpl_by_ref[ref]
        is_smt = ref in SMT
        require(len(pads) == int(row['Pins']) and len(pads) > 0,
                'CPL/project pad count mismatch: ' + ref)
        require(row['SMD'] == ('Yes' if is_smt else 'No'), 'SMD flag mismatch: ' + ref)
        require(all(p.get('hole') is None and p['layerId'] == 1 for p in pads)
                if is_smt else all(p.get('hole') and p['layerId'] == 12 for p in pads),
                'Physical pad classification mismatch: ' + ref)
        require(row['Layer'] == 'T' and comp['data']['layerId'] == 1,
                'Unexpected layer: ' + ref)
        require(re.fullmatch(r'-?\d+(?:\.\d+)?', row['Rotation']) is not None,
                'Invalid rotation: ' + ref)
        for key in ('Mid X', 'Mid Y'):
            require(re.fullmatch(r'-?\d+(?:\.\d+)?mm', row[key]) is not None,
                    'Expected native mm centroid: ' + ref)
    require(sum(pad_counts[r] for r in SMT) == 29, 'Expected 29 SMT pads')

    smt_bom = []
    for row in bom:
        selected = set(refs(row)) & SMT
        if not selected:
            continue
        require(selected == set(refs(row)), 'Mixed SMT/manual group requires review')
        require(row['Supplier'] == 'LCSC' and re.fullmatch(r'C\d+', row['Supplier Part']),
                'Missing or non-LCSC SMT sourcing')
        smt_bom.append({dest: row[src] for dest, src in BOM_MAP.items()})
    smt_cpl = [{key: row[key] for key in CPL_FIELDS}
               for row in cpl if row['Designator'] in SMT]
    manual_fields = ['Designator', 'Quantity', 'Comment', 'Footprint',
                     'Manufacturer Part', 'Manufacturer', 'Supplier Part', 'Supplier',
                     'Mid X', 'Mid Y', 'Layer', 'Rotation']
    manual = []
    for ref in sorted(MANUAL):
        row = {key: bom_by_ref[ref][key] for key in manual_fields[:8]}
        row.update(Designator=ref, Quantity='1')
        row.update({key: cpl_by_ref[ref][key] for key in CPL_FIELDS[1:]})
        manual.append(row)
    expected = {
        'BOM_SMT_Mianguang_V0.3.csv': (list(BOM_MAP), smt_bom),
        'CPL_SMT_Mianguang_V0.3.csv': (CPL_FIELDS, smt_cpl),
        'manual_assembly.csv': (manual_fields, manual),
    }
    blobs = {name: csv_bytes(fields, rows) for name, (fields, rows) in expected.items()}
    for name, (_, rows) in expected.items():
        require(read_csv(blobs[name]) == rows, 'CSV round-trip mismatch: ' + name)
    actual_bom = {ref: row for row in smt_bom for ref in refs(row)}
    require(set(actual_bom) == {r['Designator'] for r in smt_cpl} == SMT,
            'Output BOM/CPL reference set mismatch')
    require(sum(int(r['Quantity']) for r in smt_bom) == 14 and len(manual) == 9,
            'Output quantity mismatch')

    per_component = []
    for row in smt_cpl + manual:
        ref = row['Designator']
        coordinates_equal = all(row[k] == cpl_by_ref[ref][k] for k in CPL_FIELDS)
        bom_equal = (all(actual_bom[ref][k] == bom_by_ref[ref][v] for k, v in BOM_MAP.items())
                     if ref in SMT else all(row[k] == bom_by_ref[ref][k]
                                            for k in manual_fields[2:8]))
        require(coordinates_equal and bom_equal, 'Source/output mismatch: ' + ref)
        per_component.append({'designator': ref, 'assembly': 'SMT' if ref in SMT else 'manual',
                              'coordinates_equal_to_native_cpl': coordinates_equal,
                              'bom_fields_equal_to_native_bom': bom_equal,
                              'physical_pads': pad_counts[ref],
                              **{k: row[k] for k in CPL_FIELDS[1:]}})
    require(all(sha((source / name).read_bytes()) == digest
                for name, digest in source_hashes.items()), 'Release changed during preparation')
    out.mkdir(parents=True, exist_ok=True)
    for name, data in blobs.items():
        (out / name).write_bytes(data)
        require((out / name).read_bytes() == data, 'Saved CSV differs: ' + name)
    report = {
        'status': 'PASS', 'release': 'V0.3',
        'source': str(source.relative_to(PCB.parent)) if source.is_relative_to(PCB.parent) else str(source),
        'source_candidate': 'DFM_PRECHECK_02' if source == SOURCE else source.name,
        'project_uuid': manifest['project_uuid'], 'source_sha256': source_hashes,
        'output_sha256': {name: sha(data) for name, data in blobs.items()},
        'counts': {'bom_groups': len(smt_bom), 'smt_components': 14,
                   'manual_components': 9, 'total_components': 23, 'smt_pads': 29},
        'checks': {'frozen_manifest_verified': True, 'source_unchanged': True,
                   'csv_roundtrip_exact': True, 'bom_cpl_references_equal': True,
                   'quantity_matches_designators': True, 'physical_pad_classification': True,
                   'native_centroids_layer_rotation_preserved': True},
        'components': per_component, 'format_guides': GUIDES,
        'platform_smt_check': 'NOT_RUN', 'platform_rotation_corrections': 'NONE',
        'scope': 'Local file consistency only; platform matching, stock, polarity and placement preview remain pending.',
    }
    (out / 'validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'status': report['status'], **report['counts'], 'output': str(out)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
