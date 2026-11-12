from pathlib import Path
import hashlib
import json
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parent
index = json.loads((root / 'ARTIFACTS.json').read_bytes())
expected = {x['path']: x for x in index['artifacts']}
actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
assert actual == set(expected) | {'ARTIFACTS.json'}, (sorted(actual - set(expected) - {'ARTIFACTS.json'}), sorted(set(expected) - actual))
for name, row in expected.items():
    p = root / name
    assert not p.is_symlink() and p.suffix != '.rs', name
    b = p.read_bytes()
    assert len(b) == row['bytes'] and len(b) < 512000, name
    assert hashlib.sha256(b).hexdigest() == row['sha256'], name
    assert hashlib.sha1(b'blob ' + str(len(b)).encode() + b'\0' + b).hexdigest() == row['git_blob'], name
native = root / 'native-cc22-focused-review'
raw = (native / 'focused.raw.log').read_bytes()
failure_records = json.loads((native / 'failed-cases-complete.json').read_bytes())
for item in failure_records['failures']:
    lo, hi = item['raw_byte_range_half_open']
    assert raw[lo:hi] == item['original_block'].encode(), item['case']
    assert hashlib.sha256(item['stderr'].encode()).hexdigest() == item['stderr_sha256'], item['case']
cases = ET.fromstring((native / 'originals/native-cc22a69972d0-focused-v1/focused.xml').read_bytes()).findall('.//testcase')
failed = [x for x in cases if x.find('failure') is not None]
assert len(cases) == 109 and len(failed) == 31
assert {x['case'] for x in failure_records['failures']} == {x.attrib['name'] for x in failed}
progress = json.loads((root / 'PROGRESS.json').read_bytes())
assert progress['status'] == 'IN_PROGRESS'
assert all(value == 0 for value in progress['ordinary_qualification'].values())
assert progress['results']['full_source_gate']['commit'] == 'cc22a69972d029d3ef28d49096f396eb5214c616'
assert progress['results']['cc22_focused_native']['status'] == 'FAILED'
assert progress['results']['test_repairs_and_diagnostics']['status'] == 'PUBLISHED_NATIVE_UNVERIFIED'
print(json.dumps({'package_integrity': 'PASS', 'indexed_files': len(expected), 'physical_files': len(actual), 'indexed_bytes': sum(x['bytes'] for x in expected.values()), 'maximum_blob_bytes': max(x['bytes'] for x in expected.values()), 'evidence_only': True, 'rust_source_caller_tests_executed': False}, sort_keys=True))
