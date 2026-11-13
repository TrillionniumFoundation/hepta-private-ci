"""One deterministic offline candidate from two actually read transition packets."""
import base64
import copy
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path('/tmp/hepta-36fa-provider-0c59-fix101-apply-fmt-runtime-v1')


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def compare(raw, expected):
    observed = pin(raw)
    assert observed == {key: expected[key] for key in observed}, (observed, expected)
    return observed


def put(name, raw):
    target = ROOT / name
    if target.exists():
        assert target.read_bytes() == raw
    else:
        with target.open('xb') as stream:
            stream.write(raw)
    return {'name': name, **pin(raw)}


def compact(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode()


artifacts = json.loads((ROOT / 'ARTIFACTS.json').read_bytes())
meta = {row['name']: row for row in artifacts['files']}
inputs = []
packets = {}
for name in ('apply.after.postimages.json', 'fmt.after.postimages.json'):
    raw = (ROOT / name).read_bytes()
    anchor = meta[name + '.gz']
    compare(raw, {'bytes': anchor['raw_bytes'], 'sha256': anchor['raw_sha256'], 'git_blob': anchor['raw_git_blob']})
    actual_gzip = (ROOT / (name + '.gz')).read_bytes()
    compare(actual_gzip, anchor)
    assert gzip.decompress(actual_gzip) == raw
    packets[name] = json.loads(raw)
    inputs.append({'name': name, **pin(raw), 'actual_full_gzip_readback': pin(actual_gzip)})
application = packets['apply.after.postimages.json']
formatter = packets['fmt.after.postimages.json']
assert application['stage'] == 'apply.after' and formatter['stage'] == 'fmt.after'
assert application['after_inventory_sha256'] == formatter['base_inventory_sha256']
assert application['source_commit_unchanged'] == formatter['source_commit_unchanged']
assert application['qualification'] is False and formatter['qualification'] is False
assert len(application['changes']) == 4 and len(formatter['changes']) == 62
manual = {row['path']: row for row in application['changes']}
assert set(manual) <= {row['path'] for row in formatter['changes']}
candidate = copy.deepcopy(formatter)
candidate['stage'] = 'final'
candidate['base_inventory_sha256'] = application['base_inventory_sha256']
replacements = []
for row in candidate['changes']:
    if row['path'] in manual:
        earlier = manual[row['path']]
        assert row['before'] == earlier['after']
        assert row['before_raw_base64'] == earlier['after_raw_base64']
        row['before'] = copy.deepcopy(earlier['before'])
        row['before_raw_base64'] = earlier['before_raw_base64']
        replacements.append(row['path'])
assert len(replacements) == 4
assert [row['path'] for row in candidate['changes']] == sorted(row['path'] for row in candidate['changes'])
raw = compact(candidate)
anchor = meta['final.postimages.json.gz']
compare(raw, {'bytes': anchor['raw_bytes'], 'sha256': anchor['raw_sha256'], 'git_blob': anchor['raw_git_blob']})
compressed = gzip.compress(raw, mtime=0)
compare(compressed, anchor)
parts = []
for item in anchor['parts']:
    chunk = compressed[item['decoded_offset']:item['decoded_offset'] + item['decoded_bytes']]
    assert len(chunk) == item['decoded_bytes'] and hashlib.sha256(chunk).hexdigest() == item['decoded_sha256']
    encoded = base64.b64encode(chunk) + b'\n'
    compare(encoded, item)
    parts.append((item['name'], encoded))
assert sum(item['decoded_bytes'] for item in anchor['parts']) == len(compressed)
assert gzip.decompress(b''.join(base64.b64decode(value, validate=False) for _, value in parts)) == raw
raw_row = put('final.postimages.exact_recovered.json', raw)
gzip_row = put('final.postimages.exact_recovered.json.gz', compressed)
part_rows = [put(name, encoded) for name, encoded in parts]
review = {
    'format': 'hepta-final-postimages-exact-recovery-v1',
    'qualification': False,
    'scope': 'Single deterministic reconstruction of an original retained output, accepted only after all actual producer raw/gzip/part identities match.',
    'actual_artifacts': pin((ROOT / 'ARTIFACTS.json').read_bytes()),
    'actually_read_inputs': inputs,
    'changes': ['stage fmt.after to final', 'base inventory from actual apply.before',
                'four manual paths: exact earlier before rows and original bytes replace formatter before'],
    'four_before_replacements': replacements,
    'unchanged_final_after_rows': 62,
    'raw': raw_row, 'gzip': gzip_row, 'parts': part_rows,
    'matches_all_original_artifact_pins': True,
    'new_native_read': False, 'new_execution': False,
    'claim_boundary': 'These final-output bytes were reconstructed offline. They are not a second native download or a new observed formatter run. Actual apply/fmt packets and original ARTIFACTS anchor this exact recovery.'}
review_row = put('FINAL_POSTIMAGES_EXACT_RECOVERY_REVIEW.json', (json.dumps(review, sort_keys=True, indent=2) + '\n').encode())
print(json.dumps({'review': review_row, 'raw': raw_row, 'gzip': gzip_row, 'parts': part_rows}, sort_keys=True))
