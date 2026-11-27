"""Read-only verification of this E archive; no network or native commands.

Use --original-artifact PATH to also recheck the six intentionally omitted
inventories against the retained original GitHub artifact ZIP.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def parsed_cases(data):
    root = ET.fromstring(data)
    cases = root.findall('.//testcase')
    assert not root.findall('.//failure')
    assert not root.findall('.//error')
    assert not root.findall('.//skipped')
    names = [(case.get('classname'), case.get('name')) for case in cases]
    assert len(names) == len(set(names))
    return cases


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--original-artifact', type=Path)
args = parser.parse_args()
base = Path(__file__).resolve().parent
manifest = json.loads((base / 'MANIFEST.json').read_text())
evidence = json.loads((base / 'CI_EVIDENCE.json').read_text())
index = json.loads((base / 'ARTIFACT_INDEX.json').read_text())
expected_names = {'MANIFEST.json'} | set(manifest['files'])
assert {p.name for p in base.iterdir() if p.is_file()} == expected_names
for name, item in manifest['files'].items():
    blob = (base / name).read_bytes()
    assert len(blob) == item['bytes'] <= manifest['maximum_blob_bytes'], name
    assert sha256(blob) == item['sha256'], name
assert (base / 'MANIFEST.json').stat().st_size <= manifest['maximum_blob_bytes']

api = json.loads(gzip.decompress((base / 'API_CAPTURE.json.gz').read_bytes()))
assert api['run']['head_sha'] == evidence['source_sha']
assert api['run']['head_commit']['tree_id'] == evidence['source_tree']
assert api['run']['id'] == evidence['run_id']
assert api['run']['run_attempt'] == evidence['run_attempt'] == 1
assert api['run']['conclusion'] == 'success'
job = next(j for j in api['jobs']['jobs'] if j['id'] == evidence['job_id'])
assert job['conclusion'] == 'success' and job['name'] == 'native'
assert len(api['artifacts']['artifacts']) == 1
artifact = api['artifacts']['artifacts'][0]
assert artifact['id'] == index['artifact_id']
assert artifact['size_in_bytes'] == index['original_zip_bytes']
assert artifact['digest'].removeprefix('sha256:') == index['original_zip_sha256']

with zipfile.ZipFile(base / 'RAW_ARTIFACT_RECORDS.zip') as selected:
    assert selected.testzip() is None
    records = {name: selected.read(name) for name in selected.namelist()}
    assert len(records) == len(selected.infolist()) == index['selected_member_count']
selected_names = {name for name, item in index['entries'].items() if item['preserved_in']}
assert set(records) == selected_names
for name, blob in records.items():
    assert len(blob) == index['entries'][name]['bytes'], name
    assert sha256(blob) == index['entries'][name]['sha256'], name

for lane in ('ordinary', 'root'):
    result = evidence['tests_independently_parsed'][lane]
    cases = parsed_cases(records[lane + '.xml'])
    assert len(cases) == result['passed'] == result['junit_testcases']
    assert sha256(records[lane + '.xml']) == result['junit_sha256']
    execution = json.loads(records[lane + '.json'])
    assert sha256(records[lane + '.json']) == result['execution_record_sha256']
    assert execution['returncode'] == 0
root_cases = parsed_cases(records['root.xml'])
assert sorted(case.get('name') for case in root_cases) == evidence['root_independence']['expected_names']
assert records['root-prior-junit-excluded.xml'] == records['ordinary.xml']
assert records['root.xml'] != records['root-prior-junit-excluded.xml']

job_gzip = (base / ('job-' + str(evidence['job_id']) + '.log.gz')).read_bytes()
job_log = gzip.decompress(job_gzip)
assert len(job_log) == evidence['decoded_job_log']['raw_bytes']
assert sha256(job_log) == evidence['decoded_job_log']['raw_sha256']
uid_lines = [
    {'line': number, 'text': line}
    for number, line in enumerate(job_log.decode('utf-8').splitlines(), 1)
    if re.fullmatch(r'\d{4}-\d\d-\d\dT[^ ]+Z Root test uid=0', line)
]
assert uid_lines == evidence['root_independence']['actual_uid_output']
assert len(uid_lines) == 1

for cut, expected in evidence['source_cuts'].items():
    actual = json.loads(records[cut + '.json'])
    assert actual == expected
    assert actual['commit'] == evidence['source_sha']
    assert actual['tree'] == evidence['source_tree']
    assert actual['status'] == ''
assert records['maintenance.patch'] == b''
assert records['maintenance-postimages.jsonl'] == b''
for name in ('fmt.json', 'fix.json', 'bins-check.json'):
    actual = json.loads(records[name])
    assert actual['returncode'] == 0
    assert not actual['timed_out'] and not actual['output_limit_exceeded']
assert json.loads(records['maintenance-summary.json'])['files'] == []
assert json.loads(records['maintenance-summary.json'])['complete']
helper_messages = [json.loads(line) for line in records['helpers/codex-hepta-infer-worker-host.jsonl'].splitlines()]
assert len(helper_messages) == evidence['helper']['compiler_jsonl_lines_parsed']
assert helper_messages[-1]['reason'] == 'build-finished' and helper_messages[-1]['success']

full_inventory_recheck = False
if args.original_artifact:
    original_blob = args.original_artifact.read_bytes()
    assert len(original_blob) == index['original_zip_bytes']
    assert sha256(original_blob) == index['original_zip_sha256']
    with zipfile.ZipFile(args.original_artifact) as original:
        assert original.testzip() is None
        assert set(original.namelist()) == set(index['entries'])
        assert len(original.infolist()) == index['member_count']
        inventory_reference = None
        inventory_count = 0
        for name, item in index['entries'].items():
            blob = original.read(name)
            assert len(blob) == item['bytes'] and sha256(blob) == item['sha256'], name
            if name in records:
                assert blob == records[name], name
            if name in index['large_source_inventories']:
                expanded = gzip.decompress(blob)
                expected = index['large_source_inventories'][name]
                assert len(expanded) == expected['uncompressed_bytes']
                assert sha256(expanded) == expected['uncompressed_sha256']
                assert len(json.loads(expanded)) == expected['parsed_file_count']
                if inventory_reference is None:
                    inventory_reference = expanded
                assert expanded == inventory_reference
                inventory_count += 1
        assert inventory_count == 6
    full_inventory_recheck = True

print(json.dumps({
    'verified': True,
    'source_sha': evidence['source_sha'],
    'source_tree': evidence['source_tree'],
    'run_id': evidence['run_id'],
    'job_id': evidence['job_id'],
    'ordinary_cases': 1146,
    'root_cases': 7,
    'complete_raw_members_preserved': len(records),
    'original_zip_and_six_inventories_rechecked_now': full_inventory_recheck,
    'maximum_delivered_blob_bytes': max(p.stat().st_size for p in base.iterdir() if p.is_file()),
    'new_native_or_ci_jobs_started': 0,
}, indent=2))
