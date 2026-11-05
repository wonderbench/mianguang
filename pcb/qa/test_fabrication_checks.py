"""Failure-oriented tests for the supplementary manufacturing gates."""
import copy
import csv
import math
from pathlib import Path
import tempfile
import unittest

import check_fabrication as f
import check_release as q
from gerbonara import GerberFile, graphic_objects as go, graphic_primitives as gp
from gerbonara.apertures import CircleAperture
from gerbonara.utils import MM
from shapely.geometry import box, Point
from shapely.ops import unary_union


def record(kind, ident, data):
    return ({'type': kind, 'id': ident}, data, 1)


def doc(records, kind='PCB'):
    return {'head': {'docType': kind, 'uuid': 'test'}, 'origin': 'synthetic', 'records': records}


def status(report, key):
    return next(c['status'] for c in report.checks if c['id'] == key)


def flash(x, y, diameter):
    return go.Flash(x, y, CircleAperture(diameter, unit=MM), unit=MM)


def geometry_fixture():
    copper = GerberFile(objects=[flash(2, 2, 1), flash(4, 2, 1)])
    mask = GerberFile(objects=[flash(2, 2, 1.1), flash(4, 2, 1.1)])
    silk = GerberFile(objects=[go.Line(7, 7, 8, 7, CircleAperture(.2, unit=MM), unit=MM)])
    layers = {s: (s, copper) for s in ('top', 'bottom')}
    auxiliary = {s+'_mask': (s+'_mask', mask) for s in ('top', 'bottom')}
    auxiliary.update({s+'_silk': (s+'_silk', silk) for s in ('top', 'bottom')})
    anchors = [dict(ref='J1', pin=str(i+1), x=x, y=2, d=0, r=.5, width=1, height=1,
                    land_shape='ROUND', land_angle=0, layers=(1, 2)) for i, x in enumerate((2, 4))]
    return layers, auxiliary, anchors


class FabricationFailureCases(unittest.TestCase):
    def test_online_profile_only_adds_or_tightens_baseline_limits(self):
        for key, baseline in f.PROFILES['baseline'].items():
            self.assertGreaterEqual(f.PROFILES['online-preflight'][key], baseline)
        self.assertEqual(f.PROFILES['online-preflight']['silk_to_mask_mm'], .25)
        self.assertEqual(f.PROFILES['online-preflight']['silk_to_all_drill_mm'], .25)

    def test_online_profile_rejects_six_mil_text_stroke(self):
        pcb = doc([record('STRING', 'label', {'layerId': 3, 'text': 'LABEL', 'fontSize': 40, 'strokeWidth': 6})])
        baseline, online = q.Report(), q.Report()
        f.inspect_source_silk(pcb, {}, {}, baseline)
        f.inspect_source_silk(pcb, {}, {}, online, f.PROFILES['online-preflight'])
        self.assertEqual(status(baseline, 'fabrication.source_silk_stroke'), 'PASS')
        self.assertEqual(status(online, 'fabrication.source_silk_stroke'), 'FAIL')

    def test_online_profile_catches_silk_near_mask_with_adequate_copper_gap(self):
        layers, auxiliary, anchors = geometry_fixture()
        auxiliary['top_silk'] = ('top_silk', GerberFile(objects=[go.Line(1.5, 2.85, 2.5, 2.85, CircleAperture(.2, unit=MM), unit=MM)]))
        report = q.Report()
        f.inspect_geometry(layers, auxiliary, anchors, [], box(0, 0, 10, 10), 0, 0,
                           report, f.PROFILES['online-preflight'])
        self.assertEqual(status(report, 'fabrication.top.silk_pad_gaps'), 'PASS')
        self.assertEqual(status(report, 'fabrication.top.silk_mask_overlap'), 'PASS')
        self.assertEqual(status(report, 'fabrication.top.silk_window_gaps'), 'FAIL')

    def test_online_profile_checks_tented_vias_and_npth_edges(self):
        for plated in (True, False):
            with self.subTest(plated=plated):
                layers, auxiliary, anchors = geometry_fixture()
                drill = {'x': 7.5, 'y': 7.35, 'd': .3, 'plated': plated, 'file': 'synthetic.DRL'}
                report = q.Report()
                f.inspect_geometry(layers, auxiliary, anchors, [drill], box(0, 0, 10, 10), 0, 0,
                                   report, f.PROFILES['online-preflight'])
                self.assertEqual(status(report, 'fabrication.top.silk_all_drill_gaps'), 'FAIL')
                self.assertEqual(status(report, 'fabrication.top.silk_mask_overlap'), 'PASS')

    def test_visible_instance_attribute_cannot_hide_behind_compliant_labels(self):
        records = [record('STRING', 'good', {'layerId': 3, 'text': 'GOOD', 'fontSize': 45, 'strokeWidth': 6}),
                   record('ATTR', 'bad', {'layerId': 3, 'value': 'Q1', 'valueVisible': True, 'fontSize': 32, 'strokeWidth': 6})]
        report = q.Report()
        f.inspect_source_silk(doc(records), {}, {}, report)
        self.assertEqual(status(report, 'fabrication.source_silk_text_height'), 'FAIL')

    def test_footprint_text_and_thin_arc_are_checked(self):
        pcb = doc([record('STRING', 'good', {'layerId': 3, 'text': 'GOOD', 'fontSize': 45, 'strokeWidth': 6})])
        footprint = doc([record('STRING', 'small', {'layerId': 3, 'text': 'FP', 'fontSize': 32, 'strokeWidth': 6}),
                         record('POLY', 'thin', {'layerId': 3, 'width': 3})], 'FOOTPRINT')
        comps = {'U1': {'id': 'u', 'props': {'Footprint': 'fp'}}}
        report = q.Report()
        f.inspect_source_silk(pcb, comps, {'fp': footprint}, report)
        self.assertEqual(status(report, 'fabrication.source_silk_text_height'), 'FAIL')
        self.assertEqual(status(report, 'fabrication.source_silk_stroke'), 'FAIL')

    def test_instance_hidden_attribute_overrides_library_visibility(self):
        pcb = doc([record('STRING', 'good', {'layerId': 3, 'text': 'GOOD', 'fontSize': 45, 'strokeWidth': 6}),
                   record('ATTR', 'hide', {'parentId': 'u', 'key': 'Name', 'value': 'x', 'layerId': 3, 'valueVisible': False})])
        footprint = doc([record('ATTR', 'small', {'key': 'Name', 'value': 'FP', 'layerId': 3,
                         'valueVisible': True, 'fontSize': 32, 'strokeWidth': 3})], 'FOOTPRINT')
        report = q.Report()
        f.inspect_source_silk(pcb, {'U1': {'id': 'u', 'props': {'Footprint': 'fp'}}}, {'fp': footprint}, report)
        self.assertEqual(status(report, 'fabrication.source_silk_text_height'), 'PASS')
        self.assertEqual(status(report, 'fabrication.source_silk_stroke'), 'PASS')

    def test_missing_mask_window_is_detected(self):
        layers, auxiliary, anchors = geometry_fixture()
        auxiliary['top_mask'] = ('top_mask', GerberFile(objects=[flash(4, 2, 1.1)]))
        report = q.Report()
        f.inspect_geometry(layers, auxiliary, anchors, [], box(0, 0, 10, 10), 0, 0, report)
        self.assertEqual(status(report, 'fabrication.top.mask_pad_coverage'), 'FAIL')

    def test_merged_mask_windows_do_not_pass_as_a_large_separate_gap(self):
        layers, auxiliary, anchors = geometry_fixture()
        auxiliary['top_mask'] = ('top_mask', GerberFile(objects=[go.Line(2, 2, 4, 2, CircleAperture(1.1, unit=MM), unit=MM)]))
        report = q.Report()
        f.inspect_geometry(layers, auxiliary, anchors, [], box(0, 0, 10, 10), 0, 0, report)
        self.assertEqual(status(report, 'fabrication.top.separate_pad_windows'), 'FAIL')

    def test_silk_touching_opening_is_detected(self):
        layers, auxiliary, anchors = geometry_fixture()
        auxiliary['top_silk'] = ('top_silk', GerberFile(objects=[go.Line(1, 2, 3, 2, CircleAperture(.2, unit=MM), unit=MM)]))
        report = q.Report()
        f.inspect_geometry(layers, auxiliary, anchors, [], box(0, 0, 10, 10), 0, 0, report)
        self.assertEqual(status(report, 'fabrication.top.silk_mask_overlap'), 'FAIL')
        self.assertEqual(status(report, 'fabrication.top.silk_pad_gaps'), 'FAIL')

    def test_thin_exported_silk_fails_even_without_source_text(self):
        layers, auxiliary, anchors = geometry_fixture()
        auxiliary['top_silk'] = ('top_silk', GerberFile(objects=[go.Line(7, 7, 8, 7, CircleAperture(.0762, unit=MM), unit=MM)]))
        report = q.Report()
        f.inspect_geometry(layers, auxiliary, anchors, [], box(0, 0, 10, 10), 0, 0, report)
        self.assertEqual(status(report, 'fabrication.top.exported_silk_stroke'), 'FAIL')

    def test_npth_disk_removal_does_not_erase_nearby_copper(self):
        error = f.ERRORS[0]
        disk = f.g._disk(0, 0, 1, error)
        other = box(1.05, -.5, 2, .5)
        cleaned, removed = f.without_drilled_npth_disks(unary_union([disk, other]),
                                                      [{'x': 0, 'y': 0, 'd': 2, 'plated': False}], error)
        self.assertEqual(len(removed), 1)
        self.assertAlmostEqual(cleaned.distance(Point(0, 0))-1, .05)
        larger = f.g._disk(0, 0, 1.01, error)
        cleaned, removed = f.without_drilled_npth_disks(larger, [{'x': 0, 'y': 0, 'd': 2, 'plated': False}], error)
        self.assertEqual(removed, [])
        self.assertGreater(cleaned.area, 3)

    def test_zero_inner_radius_arc_is_bounded_and_nonempty(self):
        radius = .127
        primitive = gp.Arc(-radius, 0, radius, 0, 0, 0, False, radius*2)
        areas = [f.bounded_primitive(primitive, e).area for e in f.ERRORS]
        target = 3*math.pi*radius**2
        for area in areas:
            self.assertLess(abs(area-target), .001)
        self.assertLess(abs(areas[0]-areas[1]), .001)

    def test_near_threshold_is_not_rounded_to_pass(self):
        report = q.Report()
        f.minimum_gate(report, 'near', [.15001, .15001], .15, 'test', {})
        self.assertEqual(status(report, 'near'), 'UNVERIFIED')
        f.minimum_gate(report, 'safe', [.152, .152], .15, 'test', {})
        self.assertEqual(status(report, 'safe'), 'PASS')
        f.minimum_gate(report, 'bad', [.148, .148], .15, 'test', {})
        self.assertEqual(status(report, 'bad'), 'FAIL')

    def test_refined_interval_proves_clearance_but_inconsistent_bounds_do_not(self):
        report = q.Report()
        f.minimum_gate(report, 'resolved', [.15065, .15065], .15, 'test', {})
        self.assertEqual(status(report, 'resolved'), 'PASS')
        f.minimum_gate(report, 'inconsistent', [.154, .15065], .15, 'test', {})
        self.assertEqual(status(report, 'inconsistent'), 'UNVERIFIED')

    def test_wrong_cpl_rotation_or_smd_class_fails(self):
        cols = ['Designator', 'Ref X', 'Ref Y', 'Rotation', 'Layer', 'SMD', 'Pins']
        comp = {'U1': {'id': 'u', 'data': {'x': 100, 'y': 100, 'angle': 0, 'layerId': 1}, 'props': {'Footprint': 'fp'}}}
        footprint = doc([record('PAD', 'p1', {'num': '1', 'hole': {'width': 40}})], 'FOOTPRINT')
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'PickPlace.csv'
            for rotation, smd, expected in [(0, 'No', 'PASS'), (90, 'No', 'FAIL'), (0, 'Yes', 'FAIL')]:
                with path.open('w', newline='') as stream:
                    writer = csv.writer(stream); writer.writerow(cols)
                    writer.writerow(['U1', '2.54mm', '2.54mm', rotation, 'T', smd, 1])
                report = q.Report()
                f.inspect_cpl(Path(td), comp, {'fp': footprint}, report)
                self.assertEqual(status(report, 'fabrication.cpl'), expected)


if __name__ == '__main__':
    unittest.main()
