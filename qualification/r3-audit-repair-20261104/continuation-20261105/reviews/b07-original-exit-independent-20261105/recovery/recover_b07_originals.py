#!/usr/bin/env python3
"""Recover two unchanged B07 originals from the already published V7 transport."""
import base64
import hashlib
import json
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PARTS = ROOT / 'v7-main-windows'
OUT = ROOT / 'originals'

def ident(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}

def check(data, expected):
    actual = ident(data)
    assert actual['bytes'] == expected['bytes'], (actual, expected)
    assert actual['sha256'] == expected['sha256'], (actual, expected)
    assert actual['git_blob'] == expected.get('git_blob', expected.get('computed_git_blob')), (actual, expected)
    return actual

def create_exact(path, data):
    if path.exists():
        assert path.read_bytes() == data, str(path)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as f:
            f.write(data)

manifest_raw = (PARTS / 'transport-manifest.json').read_bytes()
assert ident(manifest_raw)['git_blob'] == '794e77f47e99823d3155f80c28ab61d4e066bf04'
manifest = json.loads(manifest_raw)
file_manifest_raw = (PARTS / 'original-files-manifest.json').read_bytes()
check(file_manifest_raw, manifest['original_files_manifest'])
file_manifest = json.loads(file_manifest_raw)
assert len(manifest['parts']) == manifest['part_count'] == 85
chunk_rows = []
archive = bytearray()
for i, part in enumerate(manifest['parts']):
    assert part['index'] == i and part['compressed_offset'] == len(archive)
    raw = (PARTS / part['name']).read_bytes()
    file_id = check(raw, part['file'])
    assert raw.endswith(b'\n') and b'\n' not in raw[:-1] and b'\r' not in raw
    decoded = base64.b64decode(raw[:-1], validate=True)
    decoded_id = check(decoded, part['decoded_chunk'])
    archive.extend(decoded)
    chunk_rows.append({'index': i, 'path': str(PARTS / part['name']),
                       'file': file_id, 'decoded_chunk': decoded_id})
archive_id = check(archive, manifest['archive'])
archive_path = PARTS / 'original-ci.tar.gz'
create_exact(archive_path, archive)
del archive

prefix = 'research-audit/published-5b633-ci-20261105/terminal/main-win-shard2-127339255880/'
wanted = {
    prefix + 'artifact-13431285250/artifact.zip': 'artifact-13431285250.zip',
    prefix + 'job.log': 'job-127339255880.log',
}
declared = {row['member']: row for row in file_manifest['files']}
assert set(wanted).issubset(declared)
fixed = {
    'artifact-13431285250.zip': {'bytes': 4967167,
        'sha256': 'd0dd2347f5be91ae1f445d21e892ea5d4559499dc8e2f71554ce0ce2bb93ba85',
        'git_blob': '9b9fa486d7b33d003f9139ebce829f7afa982122'},
    'job-127339255880.log': {'bytes': 463383,
        'sha256': '1b7114b1ff639cc2cd5d38e5d53326e16796ffb1516fef1e960d8df371c3de65',
        'git_blob': 'e5519cc76138d773f491c7ea42655448655c0dc9'},
}
recovered = []
with tarfile.open(archive_path, mode='r|gz') as tf:
    for member in tf:
        if member.name not in wanted:
            continue
        assert member.isfile() and not member.issym() and not member.islnk()
        assert member.name not in {r['original_archive_member'] for r in recovered}
        data = tf.extractfile(member).read()
        got = check(data, declared[member.name])
        check(data, fixed[wanted[member.name]])
        path = OUT / wanted[member.name]
        create_exact(path, data)
        recovered.append({'original_archive_member': member.name,
                          'path': str(path), **got})
        if len(recovered) == len(wanted):
            break
assert len(recovered) == 2

b07 = ROOT.parent / 'published-eed4d6-ci-20261105/b07-source-review-v1/originals'
members = {
    'selected-target-test-logs/invocation-pj7csqys/manifest.json': 'windows-binding-collector.original.json',
    'selected-target-test-logs/invocation-pj7csqys/targets/0002/test.log': 'windows-binding-test.original.log',
    'selected-target-test-logs/invocation-pj7csqys/targets/0002/test.xml': 'windows-binding-test.original.xml',
}
comparisons = []
with zipfile.ZipFile(OUT / 'artifact-13431285250.zip') as zf:
    names = zf.namelist()
    for member, local_name in members.items():
        assert names.count(member) == 1, member
        data = zf.read(member)
        prior = b07 / local_name
        assert data == prior.read_bytes(), str(prior)
        comparisons.append({'zip_member': member, 'prior_full_original': str(prior),
                            'equal_bytes': True, 'zip_crc32': zf.getinfo(member).CRC,
                            **ident(data)})

receipt = {
    'schema': 'b07-published-originals-recovery-v1',
    'created_utc': datetime.now(timezone.utc).isoformat(),
    'source_audit_commit': '0fc276d03e7d90f2e4fc53d67a0de8b942d51559',
    'source_audit_tree': 'c592f5edf3969f5fc8bf5100b532c2823c4f8f8a',
    'source_v7_index_git_blob': 'aa418f3f697d1a0b37c99fe410a03485b336456a',
    'source_transport_manifest': {'path': str(PARTS / 'transport-manifest.json'), **ident(manifest_raw)},
    'original_files_manifest': {'path': str(PARTS / 'original-files-manifest.json'), **ident(file_manifest_raw)},
    'part_count': len(chunk_rows), 'parts': chunk_rows,
    'archive': {'path': str(archive_path), **archive_id},
    'recovered_originals': recovered,
    'prior_B07_full_target_members_byte_equal': comparisons,
    'limits': [
        'Read only retrieval of previously published Git transport; no CI rerun, native job, source change or new qualification.',
        'All 85 transport parts and the complete compressed archive were rehashed; only the two named complete originals were extracted and verified from TAR.',
        'Other TAR members were not independently revalidated in this recovery; historical V7 verification remains historical.',
        'Only the three named ZIP members were opened and compared here; complete ZIP bytes match the prior identity. Root may independently verify all ZIP members.',
        'Original five GNU project failures and all other Windows shard results remain unchanged.',
    ],
}
receipt_path = ROOT / 'recovery-receipt-v1.json'
create_exact(receipt_path, (json.dumps(receipt, indent=2, ensure_ascii=False) + '\n').encode())
print(json.dumps({'receipt': str(receipt_path), **ident(receipt_path.read_bytes()),
                  'originals': recovered, 'target_comparisons': len(comparisons)}, indent=2))
