"""Remove only the proven duplicate Via drill appendix from an EDA Gerber ZIP.

All retained member bytes are preserved. Keep the original native archive as
evidence outside the release; never change an already frozen release.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'qa'))
from gerber_checks import _parse_zip


def sha(data):
    return hashlib.sha256(data).hexdigest()


def prepare(source, target, report_path):
    if source.resolve() == target.resolve():
        raise ValueError('Preserve the native input in a separate path')
    if (target.parent / 'manifest.json').exists():
        raise ValueError('Target release is frozen')
    _, before, notes, unsupported = _parse_zip(source)
    if notes or unsupported:
        raise ValueError('Native archive interpretation is not clean')
    # _parse_zip proves every Via appendix hit is an exact subset of primary
    # drills, and rejects duplicate primary hits or contradictory plating.
    with zipfile.ZipFile(source) as archive:
        removed = [n for n in archive.namelist()
                   if re.search(r'(^|/)Drill_PTH_Through_Via\.DRL$', n, re.I)]
        if len(removed) != 1:
            raise ValueError('Expected exactly one known Via appendix')
        retained = {n: archive.read(n) for n in archive.namelist() if n not in removed}
        removed_hash = sha(archive.read(removed[0]))
        target.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as output:
            for info in archive.infolist():
                if info.filename not in removed:
                    output.writestr(info, retained[info.filename])
    with zipfile.ZipFile(target) as result:
        if {n: result.read(n) for n in result.namelist()} != retained:
            raise ValueError('A retained manufacturing layer changed')
    _, after, notes, unsupported = _parse_zip(target)
    if notes or unsupported or before != after:
        raise ValueError('Independent drill set changed')
    if len(after) != 42 or sum(d['plated'] is True for d in after) != 38:
        raise ValueError('Expected 38 PTH + 4 NPTH')
    report = {
        'status': 'PASS', 'native_zip_sha256': sha(source.read_bytes()),
        'upload_zip_sha256': sha(target.read_bytes()),
        'removed': [{'path': removed[0], 'sha256': removed_hash,
                     'reason': 'Exact geometric subset of the primary PTH drill file'}],
        'retained_members_sha256': {n: sha(data) for n, data in retained.items()},
        'all_retained_member_bytes_identical': True,
        'independent_drills_unchanged': True, 'pth': 38, 'npth': 4,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    print('Prepared upload ZIP: unchanged manufacturing layers; 38 PTH + 4 NPTH')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('target', type=Path)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    prepare(args.source, args.target, args.report)
