"""Validate design examples and negative cases; this is not platform/API testing.

Requires jsonschema (Draft202012). Run from any directory; no network or devices.
"""
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import re

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
schema_path = ROOT / 'contracts/telemetry.schema.json'
schema = json.loads(schema_path.read_text())
Draft202012Validator.check_schema(schema)
formats = FormatChecker()

@formats.checks('date-time')
def utc_timestamp(value):
    if not isinstance(value, str):
        return True  # JSON Schema's type keyword handles nonstrings.
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z', value):
        return False
    try:
        return datetime.fromisoformat(value[:-1] + '+00:00').utcoffset().total_seconds() == 0
    except ValueError:
        return False

validator = Draft202012Validator(schema, format_checker=formats)
results = []
def case(name, data, expected):
    actual = not list(validator.iter_errors(data))
    results.append({'case': name, 'expected_valid': expected, 'passed': actual == expected})

examples = sorted((ROOT/'examples').glob('*.json'))
for path in examples:
    case(path.name, json.loads(path.read_text()), True)
base = json.loads((ROOT/'examples/telemetry.synthetic.valid.json').read_text())

def changed(path, value):
    obj = deepcopy(base)
    at = obj
    for key in path[:-1]:
        at = at[key]
    at[path[-1]] = value
    return obj

for name, path, value in [
    ('extra_top', ['extra'], 1),
    ('extra_sample', ['sample','diagnosis'], 'not part of MVP'),
    ('bad_device_uuid', ['device_id'], 'device-1'),
    ('bad_binding_uuid', ['binding_id'], 'bed-1'),
    ('uuid_boot_rejected', ['boot_id'], 'c2914abc-d19f-4d2b-8da8-3e0a58b80db4'),
    ('zero_boot', ['boot_id'], 0), ('overflow_boot', ['boot_id'], 2**32),
    ('boolean_boot', ['boot_id'], True), ('negative_seq', ['seq'], -1),
    ('overflow_seq', ['seq'], 2**32), ('boolean_seq', ['seq'], True),
    ('overflow_uptime', ['uptime_ms'], 2**53),
    ('invalid_month', ['captured_at'], '2026-13-04T22:00:00Z'),
    ('invalid_day', ['captured_at'], '2026-02-30T22:00:00Z'),
    ('no_UTC_Z', ['captured_at'], '2026-11-04T22:00:00+00:00'),
    ('bad_schema_version', ['schema_version'], 2),
    ('string_boolean', ['sample','ready'], 'true'),
    ('unavailable_but_valid', ['sample','rr','available'], False),
    ('valid_wrong_reason', ['sample','hr','reason'], 'stale'),
    ('stale_but_valid', ['sample','rr','age_ms'], 5001),
    ('RR_out_of_range', ['sample','rr','raw'], 26),
    ('HR_invalid_zero', ['sample','hr','raw'], 0),
    ('HR_high', ['sample','hr','raw'], 101),
    ('motion_with_valid_vitals', ['sample','low_motion','raw'], 0),
    ('no_installation_with_valid_fields', ['sample','installation_confirmed'], False),
    ('no_transport_with_valid_fields', ['sample','transport_ok'], False),
    ('radar_disabled_with_valid_fields', ['sample','radar_enabled'], False),
    ('bad_lamp_pwm', ['sample','lamp','pwm'], 256),
]:
    case(name, changed(path, value), False)
for name, path, value in [
    ('unbound', ['binding_id'], None), ('first_boot', ['boot_id'], 1),
    ('last_boot_number', ['boot_id'], 2**32-1), ('last_seq', ['seq'], 2**32-1),
    ('millisecond_UTC', ['captured_at'], '2026-11-04T22:00:00.123Z'),
]:
    case(name, changed(path, value), True)

# Keep the integration document's example synchronized with the actual schema.
integration = ROOT/'docs/firmware_integration.md'
for i, block in enumerate(re.findall(r'```json\s*\n(.*?)\n```', integration.read_text(), re.S)):
    case(f'integration_json_{i+1}', json.loads(block), True)

broken = []
link_count = 0
for path in [ROOT/'README.md', *sorted((ROOT/'docs').glob('*.md'))]:
    for target in re.findall(r'\]\(([^)]+)\)', path.read_text()):
        if target.startswith(('https://', 'http://', '#')):
            continue
        link_count += 1
        if not (path.parent/target.split('#')[0]).exists():
            broken.append({'file': str(path.relative_to(ROOT)), 'target': target})
inputs = [schema_path, *examples, integration, Path(__file__)]
report = {
    'date': '2026-11-04', 'scope': 'Documentation contract checks only; no server, firmware network or hardware tests',
    'jsonschema_version': version('jsonschema'), 'explicit_UTC_format_checker': True,
    'cases': results, 'case_count': len(results),
    'passed': sum(x['passed'] for x in results), 'failed': sum(not x['passed'] for x in results),
    'local_link_count': link_count, 'broken_links': broken,
    'inputs': [{'path': str(p.relative_to(ROOT)), 'sha256': sha256(p.read_bytes()).hexdigest()} for p in inputs],
    'not_executed': ['HTTP authentication and freshness', 'database concurrency/idempotency/binding', 'deployment/load/restore', 'network firmware and real devices'],
}
report['status'] = 'PASS' if report['failed'] == 0 and not broken else 'FAIL'
(ROOT/'docs/validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
print(json.dumps({k: report[k] for k in ['status','case_count','passed','failed','local_link_count','broken_links']}, ensure_ascii=False))
raise SystemExit(0 if report['status']=='PASS' else 1)
