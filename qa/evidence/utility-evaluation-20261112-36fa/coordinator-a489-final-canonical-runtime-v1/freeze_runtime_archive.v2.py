import base64
import datetime
import gzip
import hashlib
import json
import pathlib
import re

ROOT = pathlib.Path('/tmp/hepta-36fa-coordinator-a489-final-canonical-runtime-v1')
PREFIX = 'coordinator-a489-final-canonical-runtime-v1'

def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def create(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == raw
    else:
        with path.open('xb') as stream:
            stream.write(raw)
    return {'path': str(path), **identity(raw)}

def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()

assert not (ROOT / 'CLOSED_RUNTIME_ARCHIVE_INPUTS.json').exists()
request_raw = (ROOT / 'ACTUAL_PROCESS_INPUT.original.json').read_bytes()
assert identity(request_raw) == {'bytes': 940279, 'sha256': 'a83c5966abbbc5af9b6f6ea555cd8f671698f2f54f48b78e6743929c51ac8048', 'git_blob': 'fd655e0dea612e9dd13d4026c11d01b811c8fd8d'}
compressed = gzip.compress(request_raw, mtime=0)
assert gzip.decompress(compressed) == request_raw
request_parts = []
for number, start in enumerate(range(0, len(compressed), 307200), 1):
    block = compressed[start:start + 307200]
    raw = base64.b64encode(block) + b'\n'
    row = create(ROOT / 'request-representation' / f'ACTUAL_PROCESS_INPUT.original.json.gz.part-{number:03}.b64', raw)
    row.update(decoded_offset=start, decoded_bytes=len(block), decoded_sha256=hashlib.sha256(block).hexdigest())
    request_parts.append(row)
catalogue = {row['name']: row for row in json.loads((ROOT / 'ARTIFACTS.json').read_bytes())}
representations = {'format': 'hepta-canonical-runtime-bounded-lossless-representations-v1', 'request': {'raw': identity(request_raw), 'gzip': identity(compressed), 'parts': request_parts, 'scope': 'Exact locally retained dispatched request; not a second request or dispatch.'}, 'original_native_large_indices': [{'name': name, 'original': catalogue[name], 'local_parts_directory': str(ROOT / 'artifacts'), 'scope': 'Actual complete original native gzip downloaded with fixed versions, then losslessly represented in the producer original part format.'} for name in ('INDEX.before.raw.gz', 'INDEX.final.raw.gz')], 'index_audit_recovery': {'review': identity((ROOT / 'recovered-index-audit/EXACT_RECOVERY_REVIEW.json').read_bytes()), 'original_aliases': [catalogue[name] for name in ('INDEX.pre-head-cas.audit.json.gz', 'INDEX.final.audit.json.gz')], 'local_unique_parts_directory': str(ROOT / 'recovered-index-audit'), 'scope': 'Exact original audit content recovered from actually downloaded raw index; no new lstat or external audit-file download.'}, 'external_inventory_recovery_placement': '29bff7138b54ec375b8cd96779edfa090f271e2d', 'external_immutable_input_placement': '0b4f421c6cd740dc5b6c4f0275e45ebc6006f960', 'external_exact_launch_placement': '37b040747e9ebe2b3640a595f1ed730af5465909', 'native_files_not_independently_downloaded_again': ['ACTUAL_BOOTSTRAP_PAYLOAD.json', 'CANONICAL_PACKET.json', 'SOURCE.before.inventory.json.gz', 'SOURCE.final.inventory.json.gz', 'INDEX.pre-head-cas.raw.gz', 'INDEX.pre-head-cas.audit.json.gz', 'INDEX.final.audit.json.gz'], 'qualification': False}
create(ROOT / 'RUNTIME_LARGE_REPRESENTATIONS.json', encoded(representations))

top = ['ROOT_EXACT_APPROVAL.original.json', 'ROOT_EXACT_APPROVAL.GIT_GET.original.json', 'MAIN_DISPATCH_INTENT.json', 'MAIN_ADMISSION.original.json', 'STATUS_01.original.json', 'STATUS_02.original.json', 'STREAM_READ_01.original.json', 'STDOUT.original.txt', 'STDERR.original.txt', 'RESULT.json', 'ARTIFACTS.json', 'STAGING_READBACK.json', 'CORE_READBACK_REVIEW.json', 'ACTUAL_RUNTIME_READBACK_REVIEW.json', 'STAGING_IDENTITY_REVIEW.json', 'decode_core.py', 'decode_artifact.py', 'recover_index_audit.py', 'verify_actual_runtime.py', 'verify_actual_runtime.initial.py', 'verify_actual_runtime.v2.py', 'LOCAL_VERIFIER_EXEC_01.original.json', 'LOCAL_VERIFIER_EXEC_02.original.json', 'LOCAL_REVIEW_SCHEMA_CORRECTION.json', 'LOCAL_REVIEW_SCHEMA_CORRECTION.diff', 'LOCAL_INTENT_PREPARE_EXEC.original.json', 'LOCAL_METADATA_DECODE_EXEC.original.json', 'LOCAL_SCHEMA_CORRECTION_EXEC.original.json', 'LOCAL_SCHEMA_INSPECTION_EXEC.original.json', 'RUNTIME_LARGE_REPRESENTATIONS.json', 'freeze_runtime_archive.py']
top += ['freeze_runtime_archive.v2.py', 'LOCAL_ARCHIVE_FREEZE_EXEC_01.original.json', 'LOCAL_ARCHIVE_FREEZE_CORRECTION.json', 'LOCAL_ARCHIVE_FREEZE_CORRECTION.diff']
selected = [(ROOT / name, 'fixed-runtime-control-or-review') for name in top]
selected += [(path, 'original-native-binary-read-sdk') for path in sorted(ROOT.iterdir()) if re.fullmatch(r'.+\.READ_[0-9]{2}\.original\.json', path.name)]
selected += [(path, 'complete-actual-native-file-readback-proof') for path in sorted(ROOT.iterdir()) if path.name.endswith('.DECODED_READBACK.json')]
for path in sorted((ROOT / 'artifacts').iterdir()):
    if path.name == 'transport-save-parts':
        assert path.is_dir()
        continue
    if '.PUBLISH_' in path.name or path.name.endswith('.gz') or path.name in ('INDEX.before.raw', 'INDEX.final.raw'):
        continue
    selected.append((path, 'decoded-original-native-artifact-or-exact-original-format-part'))
for name in ('ACTUAL_BOOTSTRAP.py', 'ACTUAL_BOOTSTRAP_ARGV.json', 'driver.py', 'APPROVED_CONFIG.json', 'FINAL_FORMAT_NORMAL.original.json'):
    selected.append((ROOT / 'staging' / name, 'complete-actual-native-staging-file'))
for path in sorted((ROOT / 'recovered-index-audit').iterdir()):
    if '.PUBLISH_' not in path.name and (path.name == 'EXACT_RECOVERY_REVIEW.json' or path.name.endswith('.b64')):
        selected.append((path, 'exact-recovered-original-index-audit-material'))
selected += [(pathlib.Path(row['path']), 'bounded-exact-dispatched-request') for row in request_parts]
assert len({str(path) for path, _ in selected}) == len(selected)
rows = []
for path, provenance in selected:
    raw = path.read_bytes()
    raw.decode('utf-8')
    assert len(raw) <= 512000, str(path)
    row = {'path': str(path), 'evidence_path': PREFIX + '/' + path.relative_to(ROOT).as_posix(), 'provenance': provenance, **identity(raw)}
    ledger = path.with_name(path.name + '.PUBLISH_LEDGER_ENTRY.json')
    if ledger.exists():
        claim = json.loads(ledger.read_bytes())
        assert all(claim[key] == row[key] for key in ('bytes', 'sha256', 'git_blob'))
        assert claim['actual_git_create'] and claim['actual_full_get_equal']
        get_path = path.with_name(path.name + '.PUBLISH_GET.original.json')
        response = json.loads(get_path.read_bytes())
        assert not response.get('isError') and response['structuredContent']['content'].encode() == raw
        row['prior_actual_git_full_get'] = {'ledger_path': str(ledger), 'original_get_sdk_path': str(get_path), 'original_get_sdk_identity': identity(get_path.read_bytes())}
    rows.append(row)
index = {'format': 'hepta-canonical-fixed-completed-runtime-archive-inputs-v1', 'cut_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'job_id': '1a1d4cbd33e-392-5a9', 'scope': 'Only the completed canonical job and its explicitly fixed original-read/decoded/recovered records; no subsequent source/native job.', 'entries': rows, 'count': len(rows), 'maximum_leaf_bytes': max(row['bytes'] for row in rows), 'prior_actual_git_full_get_claims': sum('prior_actual_git_full_get' in row for row in rows), 'large_raw_and_binary_objects': 'Preserved through RUNTIME_LARGE_REPRESENTATIONS.json; no oversized evidence leaf is included.', 'native_failures': 0, 'local_reviewer_initial_schema_error_retained': True, 'qualification': False}
raw = encoded(index)
print(json.dumps({'index': create(ROOT / 'CLOSED_RUNTIME_ARCHIVE_INPUTS.json', raw), 'count': len(rows), 'prior_published': index['prior_actual_git_full_get_claims'], 'maximum_leaf_bytes': index['maximum_leaf_bytes']}))
