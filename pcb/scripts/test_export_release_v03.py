"""Regression checks for footprint deletion and project allocation placeholders."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import export_release_v03 as exporter


def source(records):
    lines = [(dict(type='DOCHEAD'), dict(docType='FOOTPRINT', uuid='test'))] + records
    return '\n'.join(json.dumps(h) + '||' + (json.dumps(d) if d is not None else '') + '|'
                     for h, d in lines)


class ProjectFootprintTests(unittest.TestCase):
    def setUp(self):
        self.pad = (dict(type='PAD', id='pad1'), dict(centerX=0, centerY=0, layerId=1))
        self.poly = (dict(type='POLY', id='silk1'), dict(path=[0, 0, 'L', 1, 1], layerId=3))
        self.deleted = source([self.pad, self.poly, (self.poly[0], None)])

    def verify_package(self, actual, expected=None):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'project.epro2'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('project.epru', actual)
            exporter.require_project_footprints(path, {'sources': {'test': expected or self.deleted}})

    def test_tombstone_and_compacted_absence_are_equal(self):
        self.verify_package(source([self.pad]))

    def test_rebuilt_allocation_counters_only_are_allowed(self):
        a = source([self.pad, (dict(type='ELE_PLACEHOLDER', id='placeholder1'),
                              dict(dataType='POLY', max=2))])
        b = source([self.pad, (dict(type='ELE_PLACEHOLDER', id='placeholder5'),
                              dict(dataType='POLY', max=8))])
        self.verify_package(b, a)
        with self.assertRaises(RuntimeError):
            exporter.require_same_source(a, b, 'DRC must still retain placeholders')

    def test_deleted_polygon_cannot_reappear(self):
        with self.assertRaises(RuntimeError):
            self.verify_package(source([self.pad, self.poly]))

    def test_existing_pad_cannot_disappear(self):
        with self.assertRaises(RuntimeError):
            self.verify_package(source([]))

    def test_pad_geometry_cannot_change(self):
        changed = copy.deepcopy(self.pad)
        changed[1]['centerX'] = 0.1
        with self.assertRaises(RuntimeError):
            self.verify_package(source([changed]))

    def test_unknown_placeholder_payload_is_rejected(self):
        extra = (dict(type='ELE_PLACEHOLDER', id='placeholder1'),
                 dict(dataType='POLY', max=2, path=[0, 0, 1, 1]))
        with self.assertRaises(RuntimeError):
            self.verify_package(source([self.pad, extra]))


if __name__ == '__main__':
    unittest.main()
