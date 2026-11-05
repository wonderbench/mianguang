#!/usr/bin/env python3
"""Read-only supplementary fabrication checks for a Mianguang release directory.

This is not the EDA DRC or the fabricator's CAM approval. It complements
check_release.py, using the same pinned Gerber parser and geometry library.
Every output identifies its input bytes and the checks that actually ran.
"""
import argparse
from collections import Counter, defaultdict
import csv
from dataclasses import replace
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import re
import sys
import warnings
import zipfile

import check_release as q
import gerber_checks as g
from gerbonara import GerberFile, graphic_objects as go, graphic_primitives as gp
from gerbonara.apertures import CircleAperture
from gerbonara.utils import MM
from shapely import affinity
from shapely.geometry import GeometryCollection, LineString, Point, box
from shapely.ops import nearest_points, unary_union

MIL = 0.0254
ERRORS = (0.0005, 0.000125)
LIMITS = {
    'silk_text_height_mm': 1.0, 'silk_stroke_mm': 0.15,
    'silk_to_pad_mm': 0.15, 'mask_bridge_mm': 0.10,
    'mask_to_other_copper_island_mm': 0.09,
    'different_copper_islands_mm': 0.20,
    'copper_to_routed_edge_mm': 0.20, 'npth_to_copper_mm': 0.20,
    'pth_annular_ring_mm': 0.25, 'via_annular_ring_mm': 0.15,
    'via_drill_mm': 0.20, 'independent_hole_edge_gap_mm': 0.45,
    'native_track_width_mm': 0.2032,
}
PROFILES = {
    'baseline': dict(LIMITS),
    'online-preflight': dict(LIMITS, silk_stroke_mm=0.20,
                            silk_to_mask_mm=0.25, silk_to_all_drill_mm=0.25),
}
SOURCES = [{
    'url': 'https://jlcpcb.com/capabilities/pcb-capabilities',
    'retrieved': '2026-11-05',
    'applies_to': '2-layer FR-4, 1 oz, green solder mask, routed outline',
    'note': 'Silk 1 mm / 0.15 mm / pad gap 0.15 mm; mask bridge 0.10 mm; '
            'mask-to-neighbor trace 0.09 mm; routed-edge copper 0.20 mm. '
            'PTH ring 0.25 mm follows recommendation. Other project gates '
            'may be more conservative than the absolute factory limits.',
}]


class Unsupported(ValueError):
    pass


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def input_identity(root):
    return [{'path': str(p.relative_to(root)), 'bytes': p.stat().st_size, 'sha256': sha(p)}
            for p in sorted(root.rglob('*')) if p.is_file() and not p.name.startswith('.')]


def visible_text(kind, d):
    if kind in ('STRING', 'TEXT'):
        return bool(str(d.get('text', d.get('value', ''))).strip())
    if kind == 'ATTR':
        return bool((d.get('keyVisible') and str(d.get('key', '')).strip()) or
                    (d.get('valueVisible') and str(d.get('value', '')).strip()))
    return False


def inspect_source_silk(pcb, components, footprints, report, limits=None):
    """Check effective instance ATTR plus visible footprint text and strokes.

    Editor layer visibility is not manufacturing visibility. Instance ATTR
    records override matching footprint ATTR keys; otherwise a visible library
    ATTR is checked conservatively rather than silently omitted.
    """
    limits = LIMITS if limits is None else limits
    texts, strokes, unknown = [], [], []
    overrides = defaultdict(set)
    for h, d, _ in pcb['records']:
        if h['type'] == 'ATTR':
            overrides[d.get('parentId')].add(d.get('key'))

    def visit(doc, ref='', skip_attrs=()):
        for h, d, line in doc['records']:
            if d.get('layerId') not in (3, 4):
                continue
            kind = h['type']
            key = f'{ref+":" if ref else ""}{h.get("id", "?")}'
            if kind == 'ATTR' and d.get('key') in skip_attrs:
                continue
            origin = {'primitive': key, 'source': doc['origin'], 'line': line}
            if visible_text(kind, d):
                if d.get('fontFamily', 'default') != 'default':
                    unknown.append(dict(origin, reason='Non-default font stroke interpretation'))
                try:
                    texts.append(dict(origin, text=str(d.get('text', d.get('value', d.get('key', '')))),
                                      height_mm=float(d['fontSize'])*MIL,
                                      stroke_mm=float(d['strokeWidth'])*MIL))
                except (KeyError, TypeError, ValueError):
                    unknown.append(dict(origin, reason='Visible text has no numeric height/stroke'))
            elif kind in ('LINE', 'ARC', 'POLY'):
                width = d.get('width', d.get('lineWidth', d.get('strokeWidth')))
                if not isinstance(width, (int, float)):
                    unknown.append(dict(origin, reason='Silk stroke width unresolved'))
                else:
                    strokes.append(dict(origin, width_mm=width*MIL))
            elif kind in ('IMAGE', 'OBJ', 'DIMENSION'):
                unknown.append(dict(origin, reason='Raster/dimension silk needs separate interpretation'))
    visit(pcb)
    for ref, c in components.items():
        uid = str(c['props'].get('Footprint', '')).split('|')[0]
        if uid not in footprints:
            unknown.append({'primitive': ref, 'reason': 'Missing resolved footprint'})
            continue
        visit(footprints[uid], ref, overrides[c['id']])
    report.add('fabrication.source_silk_interpretation', 'UNVERIFIED' if unknown else 'PASS',
               'PCB text, visible instance ATTR, and resolved footprint text/strokes inspected',
               {'unresolved': unknown, 'visible_text_count': len(texts), 'stroke_count': len(strokes)})
    small = [t for t in texts if t['height_mm']+1e-9 < limits['silk_text_height_mm']]
    thin = [t for t in texts if t['stroke_mm']+1e-9 < limits['silk_stroke_mm']]
    thin += [s for s in strokes if s['width_mm']+1e-9 < limits['silk_stroke_mm']]
    report.test('fabrication.source_silk_text_height', bool(texts) and not small,
                'Every resolved visible silk text has nominal source height >= 1.0 mm',
                {'minimum_mm': min((t['height_mm'] for t in texts), default=None), 'violations': small})
    report.test('fabrication.source_silk_stroke', not thin,
                f"Resolved silk text and line/arc/poly strokes are >= {limits['silk_stroke_mm']:.2f} mm",
                {'violations': thin, 'text_count': len(texts), 'stroke_count': len(strokes)})


def bounded_primitive(p, error):
    # Gerbonara's arc outline divides by zero when inner radius is exactly zero.
    # Approximate this specific swept disk with a chord-bounded centerline and
    # bounded round buffer; never repair arbitrary invalid geometry with buffer(0).
    if isinstance(p, gp.Arc):
        radius = math.hypot(p.x1-p.cx, p.y1-p.cy)
        if radius > 0 and abs(radius-p.width/2) < 1e-9:
            a = math.atan2(p.y1-p.cy, p.x1-p.cx)
            b = math.atan2(p.y2-p.cy, p.x2-p.cx)
            sweep = (b-a) % (2*math.pi) if not p.clockwise else -((a-b) % (2*math.pi))
            if abs(sweep) < 1e-12:
                sweep = -2*math.pi if p.clockwise else 2*math.pi
            n = max(16, math.ceil(abs(sweep)/(2*math.acos(1-min(error/4/radius, 1)))))
            points = [(p.cx+radius*math.cos(a+sweep*i/n), p.cy+radius*math.sin(a+sweep*i/n))
                      for i in range(n+1)]
            quadrants = max(16, math.ceil(math.pi/(4*math.acos(1-min(error/4/radius, 1)))))
            return g._valid(LineString(points).buffer(radius, quad_segs=quadrants))
    return g._primitive(p, error)


def layer_geometry(layer, error):
    result = GeometryCollection()
    for obj in layer.objects:
        if not isinstance(obj, (go.Flash, go.Line, go.Arc, go.Region)):
            raise Unsupported('Unsupported Gerber object '+type(obj).__name__)
        if isinstance(obj, (go.Line, go.Arc)) and (
                not isinstance(obj.aperture, CircleAperture) or obj.aperture.hole_dia):
            raise Unsupported('Stroked noncircular/holed aperture')
        local = (go.Region(obj.outline, obj.arc_centers, unit=obj.unit, polarity_dark=True)
                 if isinstance(obj, go.Region) else replace(obj, polarity_dark=True))
        if isinstance(local, go.Line) and math.dist((local.x1, local.y1), (local.x2, local.y2)) < 1e-12:
            local = go.Flash(local.x1, local.y1, local.aperture, True, local.unit)
        shape = GeometryCollection()
        for primitive in local.to_primitives(unit=MM):
            part = bounded_primitive(primitive, error)
            shape = shape.union(part) if primitive.polarity_dark else shape.difference(part)
        g._valid(shape)
        result = result.union(shape) if obj.polarity_dark else result.difference(shape)
    return g._valid(result)


def read_auxiliary_layers(path):
    result, notes = {}, []
    roles = {'.gts': 'top_mask', '.gbs': 'bottom_mask', '.gto': 'top_silk', '.gbo': 'bottom_silk'}
    with zipfile.ZipFile(path) as z:
        for member in z.infolist():
            role = roles.get(Path(member.filename).suffix.lower())
            if not role:
                continue
            if role in result or member.file_size > 30_000_000:
                raise Unsupported('Duplicate/oversized '+role+' layer')
            source = z.read(member).decode('utf-8-sig')
            if re.search(r'%\s*(IPNEG|AB|SR|MI|OF|SF|IR|AS)', source, re.I):
                raise Unsupported('Unsupported Gerber transform in '+member.filename)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter('always')
                layer = GerberFile.from_string(source, filename=member.filename)
            notes.extend(member.filename+': '+str(w.message) for w in caught)
            result[role] = (member.filename, layer)
    missing = set(roles.values())-result.keys()
    if missing:
        raise Unsupported('Missing soldermask/silkscreen layers: '+', '.join(sorted(missing)))
    if notes:
        raise Unsupported('Parser warnings: '+'; '.join(notes))
    return result


def pair_gap(parts):
    return min((a.distance(b) for i, a in enumerate(parts) for b in parts[i+1:]), default=None)


def pad_land(anchor, dx, dy, error):
    width, height = anchor['width'], anchor['height']
    kind = anchor['land_shape']
    if kind == 'RECT':
        if anchor.get('land_radius', 0):
            raise Unsupported('Rounded native rectangle land needs explicit interpretation')
        land = box(-width/2, -height/2, width/2, height/2)
    elif kind in ('ELLIPSE', 'ROUND'):
        land = affinity.scale(g._disk(0, 0, 1, error/max(width/2, height/2)), width/2, height/2, origin=(0, 0))
    elif kind == 'OVAL':
        radius = min(width, height)/2
        line = (LineString([(-(width-height)/2, 0), ((width-height)/2, 0)]) if width >= height else
                LineString([(0, -(height-width)/2), (0, (height-width)/2)]))
        quadrants = max(16, math.ceil(math.pi/(4*math.acos(1-min(error/radius, 1)))))
        land = line.buffer(radius, quad_segs=quadrants)
    else:
        raise Unsupported('Native pad land unsupported: '+str(kind))
    return affinity.translate(affinity.rotate(land, anchor['land_angle'], origin=(0, 0)), anchor['x']+dx, anchor['y']+dy)


def hole_gap(drills):
    return min((math.dist((a['x'], a['y']), (b['x'], b['y']))-(a['d']+b['d'])/2
                for i, a in enumerate(drills) for b in drills[i+1:]), default=None)


def without_drilled_npth_disks(copper, drills, error):
    """Remove only isolated circular copper exactly coincident with an NPTH.

    EasyEDA's nonplated mounting pad can export a land equal to the drill.
    This nominal land is drilled away; removing arbitrary copper near a hole
    would hide a real clearance fault and is forbidden here.
    """
    parts = g._polygons(copper)
    kept, removed = [], []
    for part in parts:
        match = None
        for d in drills:
            if d['plated'] or not part.contains(Point(d['x'], d['y'])):
                continue
            disk = g._disk(d['x'], d['y'], d['d']/2, error)
            if (abs(part.area-disk.area) < 1e-8 and
                    part.symmetric_difference(disk).area < 1e-8):
                match = d
                break
        if match:
            removed.append({k: match[k] for k in ('x', 'y', 'd')})
        else:
            kept.append(part)
    return unary_union(kept), removed


def measure_side(side, copper_layer, mask_layer, silk_layer, anchors, drills, outline, dx, dy, error):
    mask = layer_geometry(mask_layer, error)
    silk = layer_geometry(silk_layer, error)
    copper = layer_geometry(copper_layer, error)
    copper, removed = without_drilled_npth_disks(copper, drills, error)
    islands, windows = g._polygons(copper), g._polygons(mask)
    layer_id = 1 if side == 'top' else 2
    coverage, silk_gaps, mask_gaps = [], [], []
    window_pads = defaultdict(list)
    for a in anchors:
        if layer_id not in a['layers']:
            continue
        land = pad_land(a, dx, dy, error)
        coverage.append({'pad': a['ref']+'.'+a['pin'], 'area_fraction': mask.intersection(land).area/land.area})
        if not silk.is_empty:
            pts = nearest_points(silk, land)
            silk_gaps.append({'pad': a['ref']+'.'+a['pin'], 'gap_mm': silk.distance(land),
                              'nearest_points_mm': [[p.x-dx, p.y-dy] for p in pts]})
        center = Point(a['x']+dx, a['y']+dy)
        own = [i for i, part in enumerate(islands) if part.covers(center)]
        window_index = next((i for i, p in enumerate(windows) if p.covers(center)), None)
        window = windows[window_index] if window_index is not None else None
        if window_index is not None:
            window_pads[window_index].append(a['ref']+'.'+a['pin'])
        if len(own) != 1:
            raise Unsupported('Pad not attributable to exactly one copper island: '+a['ref']+'.'+a['pin'])
        if window is not None:
            gap = min((part.distance(window) for i, part in enumerate(islands) if i not in own), default=None)
            if gap is not None:
                mask_gaps.append({'pad': a['ref']+'.'+a['pin'], 'gap_mm': gap})
    npth = [{'xy_mm': [d['x']-dx, d['y']-dy],
             'gap_mm': copper.distance(Point(d['x'], d['y']))-d['d']/2}
            for d in drills if d['plated'] is False]
    via_masks = []
    for d in drills:
        if d['plated'] and d['d'] < .6:
            via_masks.append({'xy_mm': [d['x']-dx, d['y']-dy],
                              'drill_mask_overlap_mm2': mask.intersection(g._disk(d['x'], d['y'], d['d']/2, error)).area})
    silk_window_gaps, silk_drill_gaps = [], []
    if not silk.is_empty:
        for i, window in enumerate(windows):
            pts = nearest_points(silk, window)
            silk_window_gaps.append({'window': i, 'pads': window_pads.get(i, []),
                                     'bounds_mm': list(window.bounds), 'gap_mm': silk.distance(window),
                                     'nearest_points_mm': [[p.x-dx, p.y-dy] for p in pts]})
        for d in drills:
            hole = g._disk(d['x'], d['y'], d['d']/2, error)
            pts = nearest_points(silk, hole)
            silk_drill_gaps.append({'xy_mm': [d['x']-dx, d['y']-dy], 'diameter_mm': d['d'],
                                    'plated': d['plated'], 'file': d['file'], 'gap_mm': silk.distance(hole),
                                    'nearest_points_mm': [[p.x-dx, p.y-dy] for p in pts]})
    return {
        'curve_error_mm': error, 'removed_drilled_npth_disks': removed,
        'has_silk': not silk.is_empty,
        'copper_island_count': len(islands), 'mask_window_count': len(windows),
        'merged_pad_windows': [{'window': i, 'pads': pads} for i, pads in window_pads.items() if len(pads) > 1],
        'mask_pad_coverage': coverage, 'silk_pad_gaps': silk_gaps,
        'mask_other_island_gaps': mask_gaps, 'npth_copper_gaps': npth,
        'silk_window_gaps': silk_window_gaps, 'silk_all_drill_gaps': silk_drill_gaps,
        'via_mask_overlap': via_masks,
        'silk_mask_overlap_mm2': silk.intersection(mask).area,
        'silk_mask_gap_mm': None if silk.is_empty or mask.is_empty else silk.distance(mask),
        'silk_outside_board_mm2': silk.difference(outline).area,
        'copper_outside_board_mm2': copper.difference(outline).area,
        'copper_edge_gap_mm': copper.distance(outline.boundary),
        'copper_island_gap_mm': pair_gap(islands),
        'mask_window_gap_mm': pair_gap(windows),
    }


def minimum_gate(report, key, values, limit, detail, evidence):
    """A bounded result straddling a gate is UNVERIFIED, never rounded into PASS."""
    if any(v is None or not math.isfinite(v) for v in values):
        report.add(key, 'UNVERIFIED', detail, evidence)
    else:
        intervals = [[v-2*e, v+2*e] for v, e in zip(values, ERRORS)]
        low, high = max(v[0] for v in intervals), min(v[1] for v in intervals)
        evidence = dict(evidence, distance_bounds_mm=intervals,
                        combined_distance_bounds_mm=[low, high])
        if low > high:
            report.add(key, 'UNVERIFIED', detail+'; curve-resolution error bounds disagree', evidence)
        elif low >= limit:
            report.add(key, 'PASS', detail, evidence)
        elif high < limit:
            report.add(key, 'FAIL', detail, evidence)
        else:
            report.add(key, 'UNVERIFIED', detail+'; numerical bounds straddle threshold', evidence)


def inspect_geometry(layers, auxiliary, anchors, drills, outline, dx, dy, report, limits=None):
    limits = LIMITS if limits is None else limits
    for side in ('top', 'bottom'):
        silk_layer = auxiliary[side+'_silk'][1]
        widths = Counter()
        unknown_widths = []
        filled_rectangles = []
        for i, obj in enumerate(silk_layer.objects):
            if isinstance(obj, (go.Line, go.Arc)) and isinstance(obj.aperture, CircleAperture):
                widths[round(MM(obj.aperture.diameter, obj.aperture.unit), 8)] += 1
            elif isinstance(obj, go.Flash) and isinstance(obj.aperture, CircleAperture):
                widths[round(MM(obj.aperture.diameter, obj.aperture.unit), 8)] += 1
            elif isinstance(obj, go.Region):
                shape = layer_geometry(GerberFile(objects=[obj]), ERRORS[1])
                if shape.is_empty or abs(shape.area-shape.envelope.area) > 1e-9:
                    unknown_widths.append({'object': i, 'type': 'Region', 'reason': 'Not a simple filled axis-aligned rectangle'})
                else:
                    x0, y0, x1, y1 = shape.bounds
                    filled_rectangles.append({'object': i, 'minimum_dimension_mm': min(x1-x0, y1-y0)})
            else:
                unknown_widths.append({'object': i, 'type': type(obj).__name__})
        has_thin_feature = (any(w < limits['silk_stroke_mm']-1e-9 for w in widths) or
                            any(v['minimum_dimension_mm'] < limits['silk_stroke_mm']-1e-9 for v in filled_rectangles))
        report.add('fabrication.'+side+'.exported_silk_stroke',
                   'FAIL' if has_thin_feature else ('UNVERIFIED' if unknown_widths else 'PASS'),
                   f"Actual circular-aperture strokes/dots and simple filled rectangles are >= {limits['silk_stroke_mm']:.2f} mm wide; empty bottom silk is allowed",
                   {'widths_mm_counts': dict(widths), 'filled_rectangles': filled_rectangles, 'unresolved': unknown_widths})
        measures = [measure_side(side, layers[side][1], auxiliary[side+'_mask'][1], silk_layer,
                                 anchors, drills, outline, dx, dy, e) for e in ERRORS]
        for field in ('copper_island_count', 'mask_window_count'):
            if measures[0][field] != measures[1][field]:
                raise Unsupported('Topology changes at refined curve approximation: '+side+'.'+field)
        fine = measures[1]
        prefix = 'fabrication.'+side+'.'
        report.test(prefix+'mask_pad_coverage',
                    all(m['mask_pad_coverage'] and all(v['area_fraction'] >= .99999 for v in m['mask_pad_coverage']) for m in measures),
                    'Every resolved physical land has >= 99.999% opening area coverage at both curve resolutions',
                    {'minimum_fraction': min((v['area_fraction'] for v in fine['mask_pad_coverage']), default=None),
                     'pads': fine['mask_pad_coverage']})
        report.test(prefix+'silk_mask_overlap', all(m['silk_mask_overlap_mm2'] < 1e-8 for m in measures),
                    'Actual silk does not overlap soldermask openings at either curve resolution',
                    {'overlap_area_mm2': [m['silk_mask_overlap_mm2'] for m in measures], 'minimum_gap_mm': fine['silk_mask_gap_mm']})
        report.test(prefix+'separate_pad_windows', all(not m['merged_pad_windows'] for m in measures),
                    'No soldermask opening merges multiple distinct physical pads in this separate-window design',
                    fine['merged_pad_windows'])
        report.test(prefix+'outside_board', all(m['silk_outside_board_mm2'] < 1e-8 and m['copper_outside_board_mm2'] < 1e-8 for m in measures),
                    'Copper and silk have no off-board geometry',
                    {'copper_mm2': fine['copper_outside_board_mm2'], 'silk_mm2': fine['silk_outside_board_mm2']})
        scalar_gates = [
            ('copper_edge_gap_mm', 'copper_to_routed_edge_mm', 'Copper-to-routed-outline clearance'),
            ('copper_island_gap_mm', 'different_copper_islands_mm', 'Separate same-layer copper islands clearance; not same-island internal geometry'),
            ('mask_window_gap_mm', 'mask_bridge_mm', 'Separate soldermask opening clearance for green mask'),
        ]
        for field, limitkey, detail in scalar_gates:
            minimum_gate(report, prefix+field, [m[field] for m in measures], limits[limitkey], detail,
                         {'minimum_mm': fine[field], 'coarse_mm': measures[0][field], 'limit_mm': limits[limitkey]})
        list_gates = [
            ('silk_pad_gaps', 'silk_to_pad_mm', 'Actual silk-to-physical-pad copper clearance'),
            ('mask_other_island_gaps', 'mask_to_other_copper_island_mm', 'Mask opening to other copper islands; excludes same-island internal geometry'),
            ('npth_copper_gaps', 'npth_to_copper_mm', 'NPTH edge to remaining copper; only exactly coincident isolated NPTH disks removed'),
        ]
        if 'silk_to_mask_mm' in limits:
            list_gates.append(('silk_window_gaps', 'silk_to_mask_mm',
                               'Actual silk to every soldermask opening, including openings not assigned to component pads'))
        if 'silk_to_all_drill_mm' in limits:
            list_gates.append(('silk_all_drill_gaps', 'silk_to_all_drill_mm',
                               'Actual silk to every independent PTH/via/NPTH drill edge, including tented vias'))
        for field, limitkey, detail in list_gates:
            if field.startswith('silk_') and not fine['has_silk']:
                report.add(prefix+field, 'PASS', 'No silk objects on this side; no silk clearance conflict', {'count': 0})
                continue
            values = [min((v['gap_mm'] for v in m[field]), default=None) for m in measures]
            minimum_gate(report, prefix+field, values, limits[limitkey], detail,
                         {'minimum_mm': values[1], 'limit_mm': limits[limitkey],
                          'near_limit': [v for v in fine[field] if v['gap_mm'] < limits[limitkey]+.02],
                          'count': len(fine[field]), 'removed_drilled_npth_disks': fine['removed_drilled_npth_disks'] if field == 'npth_copper_gaps' else []})
        report.test(prefix+'via_tenting', all(all(v['drill_mask_overlap_mm2'] < 1e-8 for v in m['via_mask_overlap']) for m in measures),
                    'All identified small plated drill locations have no mask opening (nominal tenting, not a guarantee of filled holes)',
                    fine['via_mask_overlap'])


def inspect_native_drills_tracks(pcb, anchors, drills, report):
    rings = [{'pad': a['ref']+'.'+a['pin'], 'ring_mm': a['r']-a['d']/2}
             for a in anchors if a['d']]
    report.test('fabrication.pth_ring', bool(rings) and all(r['ring_mm'] >= LIMITS['pth_annular_ring_mm'] for r in rings),
                'Resolved concentric PTH lands have >= 0.25 mm nominal annular ring; manufacturing eccentricity not simulated',
                {'minimum_mm': min((r['ring_mm'] for r in rings), default=None), 'pads': rings})
    vias = [{'id': h['id'], 'drill_mm': d['holeDiameter']*MIL,
             'ring_mm': (d['viaDiameter']-d['holeDiameter'])*MIL/2}
            for h, d, _ in pcb['records'] if h['type'] == 'VIA']
    report.test('fabrication.via_ring_drill', all(v['ring_mm'] >= LIMITS['via_annular_ring_mm'] and v['drill_mm'] >= LIMITS['via_drill_mm'] for v in vias),
                'Native through vias have nominal ring >= 0.15 mm and drill >= 0.20 mm', vias)
    gap = hole_gap(drills)
    report.test('fabrication.hole_spacing', gap is not None and gap >= LIMITS['independent_hole_edge_gap_mm'],
                'All independent drill edges are >= 0.45 mm apart', {'minimum_mm': gap})
    widths = defaultdict(set)
    for h, d, _ in pcb['records']:
        if h['type'] in ('LINE', 'ARC', 'POLY') and d.get('layerId') in (1, 2):
            width = d.get('width', d.get('lineWidth'))
            if not isinstance(width, (int, float)):
                raise Unsupported('Native copper stroke width unresolved: '+h['id'])
            widths[d.get('netName', '')].add(width*MIL)
    report.test('fabrication.native_track_width', bool(widths) and all(w >= LIMITS['native_track_width_mm']-1e-8 for ws in widths.values() for w in ws),
                'Native copper LINE/ARC/POLY widths >= 8 mil; not a local-neck analysis of arbitrary filled copper',
                {n: sorted(ws) for n, ws in sorted(widths.items())})


def inspect_cpl(root, pcb_components, footprints, report):
    paths = list(root.glob('*Pick*Place*.csv')) + list(root.glob('*CPL*.csv'))
    paths = sorted(set(paths))
    if len(paths) != 1:
        report.add('fabrication.cpl', 'UNVERIFIED', 'Exactly one PickPlace/CPL CSV is required', [p.name for p in paths])
        return
    with paths[0].open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    problems, measurements = [], []
    refs = [r.get('Designator') for r in rows]
    if len(set(refs)) != len(refs) or set(refs) != set(pcb_components):
        problems.append({'designator_set_or_duplicates': refs})
    for row in rows:
        ref = row.get('Designator')
        if ref not in pcb_components:
            continue
        comp = pcb_components[ref]
        data = comp['data']
        uid = str(comp['props'].get('Footprint', '')).split('|')[0]
        if uid not in footprints:
            raise Unsupported('CPL footprint unavailable: '+ref)
        pads = [d for h, d, _ in footprints[uid]['records'] if h['type'] == 'PAD']
        if not pads:
            raise Unsupported('CPL component has no physical pads: '+ref)
        expected_smd = 'Yes' if all(not (d.get('hole') or {}).get('width', 0) for d in pads) else 'No'
        def mm(key):
            value = row.get(key, '')
            if not re.fullmatch(r'-?(?:\d+(?:\.\d*)?|\.\d+)mm', value):
                raise Unsupported('CPL coordinate must explicitly use mm: '+ref+'.'+key)
            return float(value[:-2])
        try:
            item = {'ref': ref, 'ref_xy_mm': [mm('Ref X'), mm('Ref Y')],
                    'rotation': float(row['Rotation']), 'smd': row['SMD'], 'pins': int(row['Pins']), 'layer': row['Layer']}
        except (KeyError, TypeError, ValueError) as exc:
            raise Unsupported('CPL parse: '+str(exc)) from exc
        bad = (abs(item['ref_xy_mm'][0]-data['x']*MIL) > .001 or
               abs(item['ref_xy_mm'][1]-data['y']*MIL) > .001 or
               abs((item['rotation']-data.get('angle', 0)+180) % 360-180) > .001 or
               item['layer'] != {1: 'T', 2: 'B'}.get(data.get('layerId')) or
               item['smd'] != expected_smd or item['pins'] != len({p.get('num') for p in pads}))
        if bad:
            problems.append(item)
        measurements.append(item)
    report.test('fabrication.cpl', not problems and bool(rows),
                'CPL designators, reference coordinates, rotation, side, pin count and SMD/hand-insert class match native source; placement-machine origin calibration is not tested',
                {'file': paths[0].name, 'count': len(rows), 'problems': problems, 'measurements': measurements})


def run(root, profile='baseline'):
    if profile not in PROFILES:
        raise ValueError('Unknown fabrication check profile: '+profile)
    limits = PROFILES[profile]
    inputs = input_identity(root)
    scripts = {p.name: sha(p) for p in (Path(__file__), Path(q.__file__), Path(g.__file__))}
    report = q.Report({'release_directory': str(root), 'inputs': inputs, 'checker_hashes': scripts,
                       'profile': profile, 'limits': limits, 'sources': SOURCES, 'curve_errors_mm': list(ERRORS)})
    report.context['profile_note'] = (
        'online-preflight is a local corrective profile, not an online-service verdict. '
        'Its 0.25 mm silk-to-mask/drill and 0.20 mm silk-width targets respond to PRECHECK_02. '
        'It does not waive the original gates or assess the 3 mm through-hole-to-SMT assembly advisory.')
    versions = {name: importlib.metadata.version(name) for name in ('gerbonara', 'shapely')}
    report.context['dependency_versions'] = versions
    if versions != {'gerbonara': '1.6.3', 'shapely': '2.2.0'}:
        report.add('fabrication.dependencies', 'UNVERIFIED', 'Unvalidated dependency versions', versions)
        return report.result()
    try:
        docs, _, _, gerbers = q.inventory(root)
        pcb = q.select_document(docs, 'PCB', report)
        if pcb is None:
            raise Unsupported('No unique native PCB')
        footprints = {d['head']['uuid']: d for d in docs if d['head']['docType'] == 'FOOTPRINT'}
        components = q.attributes(pcb)
        inspect_source_silk(pcb, components, footprints, report, limits)
        inspect_cpl(root, components, footprints, report)
        if len(gerbers) != 1:
            raise Unsupported('Expected exactly one Gerber ZIP')
        layers, drills, notes, unsupported = g._parse_zip(gerbers[0])
        if notes or unsupported:
            raise Unsupported('Main Gerber interpretation: '+str(notes+unsupported))
        auxiliary = read_auxiliary_layers(gerbers[0])
        report.add('fabrication.layer_inventory', 'PASS', 'Exactly one top/bottom mask and silk parsed without warnings',
                   {key: value[0] for key, value in auxiliary.items()})
        actual, _ = q.pcb_nets(pcb, components)
        anchors, expected = g._native_points(pcb, components, footprints, actual)
        outline = g._outline(layers['outline'][1])
        bounds = q.outline_geometry(pcb)[0]
        dx, dy = outline.bounds[0]-bounds[0], outline.bounds[1]-bounds[1]
        if g._match_holes(expected, drills, dx, dy) is None:
            raise Unsupported('Native-to-Gerber registration could not be proven')
        report.add('fabrication.registration', 'PASS', 'All native holes match actual independent drill positions, sizes and plating',
                   {'translation_mm': [dx, dy], 'holes': len(drills)})
        inspect_native_drills_tracks(pcb, anchors, drills, report)
        inspect_geometry(layers, auxiliary, anchors, drills, outline, dx, dy, report, limits)
    except (Unsupported, g.Unsupported) as exc:
        report.add('fabrication.interpretation', 'UNVERIFIED', str(exc))
    except Exception as exc:
        report.add('fabrication.input_or_geometry', 'UNVERIFIED', type(exc).__name__+': '+str(exc))
    report.test('fabrication.inputs_stable', inputs == input_identity(root),
                'Release file set, byte sizes and SHA-256 hashes stayed unchanged during checks')
    result = report.result()
    result['scope'] = ('Supplementary nominal 2-layer green-mask fabrication checks only. '
                       'Not native EDA DRC, CAM acceptance, fabrication approval or physical verification. '
                       'Island gaps exclude internal geometry of one connected copper island; '
                       'no arbitrary copper neck analysis, stencil process qualification, placement-machine '
                       'rotation calibration, component-body collision, thermal or EMC validation.')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('release', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--profile', choices=tuple(PROFILES), default='baseline',
                        help='online-preflight adds mask/drill clearances and raises silk width; does not waive baseline gates')
    args = parser.parse_args()
    root = args.release.resolve()
    if args.output and args.output.resolve().is_relative_to(root):
        parser.error('Write the report outside the inspected release, to avoid changing or self-hashing the input')
    result = run(root, args.profile)
    rendered = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding='utf-8')
    print(rendered, end='')
    return {'PASS': 0, 'FAIL': 1, 'UNVERIFIED': 2}[result['status']]


if __name__ == '__main__':
    sys.exit(main())
