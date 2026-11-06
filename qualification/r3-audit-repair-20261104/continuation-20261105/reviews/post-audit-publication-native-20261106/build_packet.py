#!/usr/bin/env python3
"""Freeze the actual audit publication and the next bounded native observation."""
from pathlib import Path
import base64
import hashlib
import json
import re
import shutil
import zipfile

ROOT = Path(__file__).resolve().parent
DST = ROOT / 'post-audit-delivery'
DST.mkdir(exist_ok=True)


def identity(raw):
    return {'bytes': len(raw), 'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest(), 'sha256': hashlib.sha256(raw).hexdigest()}


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main():
    names = ['publication/' + name for name in [
        'commit-C1.created.json', 'commit-C1.actual.json', 'ref-C1.update.json', 'ref-C1.after.json',
        'precommit-root.actual.json', 'precommit-ref.actual.json', 'audit-prepublication-proof.json',
        'final-audit-intended-full-tree.json', 'root-followup-independent-review.actual.original.json',
        'windows-state-registry.actual.original.json', 'windows-state-assessment.actual.original.json',
        'b23-v3-independent-review.actual.original.json']]
    for number in (4797, 4884):
        names.extend('publication/metadata-pr-' + str(number) + suffix for suffix in [
            '.before.original.json', '.pre-update.original.json', '.update.original.json',
            '.after.original.json', '.verification.json', '.intended.md'])
    names.extend('documents/' + name for name in [
        'PROJECT_DIRECTION_AND_EXECUTION_PLAN_V7.zh-CN.md', 'CONTINUATION_PROGRESS_V9.zh-CN.md',
        'continuation-blocker-progress-v8.json', 'LATEST.md', 'LATEST.zh-CN.md'])
    names.extend(['old/continuation-blocker-progress-v7.json', 'windows-format/publication-originals.json',
                  'windows-format/job-127731162050.original.log'])
    names.extend(str(p.relative_to(ROOT)) for p in sorted((ROOT / 'post-C1-ci-cut').iterdir()) if p.is_file())
    names.extend(str(p.relative_to(ROOT)) for p in sorted((ROOT / 'windows-state-root-replay').iterdir()) if p.is_file())
    freeze_root = ROOT / 'b23-collector-v3-native'
    freeze = json.loads((freeze_root / 'freeze-manifest.json').read_bytes())
    assert len(freeze['files']) == 36
    for row in freeze['files']:
        path = freeze_root / row['path']
        expected = {'bytes': row['bytes'], 'git_blob': row['git_blob_sha'], 'sha256': row['sha256']}
        assert identity(path.read_bytes()) == expected
        names.append(str(path.relative_to(ROOT)))
    names.append('b23-collector-v3-native/freeze-manifest.json')
    payload = [(name, ROOT / name) for name in names]
    for label, folder in [
        ('root-followup-independent', '/tmp/hepta-runtime-recovery-20261106/root-followup-independent-review'),
        ('b23-v3-independent', '/tmp/hepta-runtime-recovery-20261106/b23-v3-native-independent-review')]:
        for path in sorted(Path(folder).iterdir()):
            if path.is_file():
                payload.append((label + '/' + path.name, path))
    state = Path('/tmp/hepta-runtime-recovery-20261106/windows-state-eof-feasibility-delivery')
    for name in ['registry.actual.json', 'ASSESSMENT.zh-CN.md']:
        payload.append(('windows-state-rejected/' + name, state / name))
    assert len(payload) == len({name for name, _ in payload})
    rows = []
    for name, path in payload:
        raw = path.read_bytes()
        # Signed transport URLs are not evidence and never belong in this packet.
        assert not re.search(rb'https://[^\s"<>]*(?:[?&](?:sig|X-Amz-Signature)=)', raw, re.I), name
        rows.append({'path': name, **identity(raw)})
    write(DST / 'manifest.json', {'schema': 'post-audit-exact-members-v1', 'files': rows,
        'temporary_signed_download_URLs_excluded': True})
    with zipfile.ZipFile(DST / 'snapshot.zip', 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, path in payload:
            info = zipfile.ZipInfo(name, (2026, 11, 6, 6, 0, 0))
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_STORED if name.endswith('.zip') else zipfile.ZIP_DEFLATED
            z.writestr(info, path.read_bytes())
    raw = (DST / 'snapshot.zip').read_bytes()
    encoded = base64.b64encode(raw)
    parts = []
    for offset in range(0, len(encoded), 400000):
        name = f'snapshot.zip.b64.part{len(parts) + 1:03d}'
        data = encoded[offset:offset + 400000]
        (DST / name).write_bytes(data)
        parts.append({'path': name, **identity(data)})
    write(DST / 'archive.json', {'schema': 'base64-parted-exact-zip-v1', 'archive': identity(raw),
        'parts': parts, 'payload_manifest': identity((DST / 'manifest.json').read_bytes())})
    shutil.copyfile(__file__, DST / 'build_packet.py')
    print(json.dumps({'archive': identity(raw), 'parts': len(parts), 'members': len(payload),
                      'original_bytes': sum(x['bytes'] for x in rows)}, indent=2))


if __name__ == '__main__':
    main()
