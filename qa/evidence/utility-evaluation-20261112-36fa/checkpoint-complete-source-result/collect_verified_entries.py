"""Collect immutable post-2793 evidence; never update a ref or run a gate."""
import hashlib
import json
from pathlib import Path

OUT = Path('/tmp/hepta-36fa-after2793-20261112')
PREFIX = 'qa/evidence/utility-evaluation-20261112-36fa/'


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'sha': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def main():
    rows = []

    def add(path, local, sha, verified):
        raw = Path(local).read_bytes()
        actual = identity(raw)
        assert verified is True and actual['sha'] == sha, (path, actual, sha)
        if path.startswith(PREFIX):
            path = path[len(PREFIX):]
        assert path and not path.startswith('/') and all(p not in ('', '.', '..') for p in path.split('/'))
        rows.append({'path': path, 'local': str(local), **actual, 'full_readback_equal': True})

    for row in json.loads((OUT / 'ROOT_PUBLICATION_UPLOADED.json').read_text()):
        add(row['path'], row['local'], row['sha'], row['full_readback_equal'])

    canonical = Path('/tmp/hepta-36fa-canonical-inventory-exact-recovery-v1/output/PLACEMENT.json')
    package = json.loads(canonical.read_text())
    assert package['qualification'] is False and package['native_or_H_execution'] is False
    for row in package['files']:
        add(row['path'], row['local'], row['git_blob'], row['full_github_readback_equal'])

    core = Path('/tmp/hepta-36fa-final-source-qualification-launch-v1/SOURCE_FAILURE_CORE_PLACEMENT.json')
    package = json.loads(core.read_text())
    assert package['actual_status'] == 'failed' and package['native_execution_started'] is False
    for row in package['files']:
        add(row['path'], row['local_path'], row['git_blob_sha'], row['github_full_readback_equal'])

    hold = Path('/tmp/hepta-36fa-final-native-qualification-launch-hold-v1')
    for name in ['BOOTSTRAP_TEMPLATE.HOLD.py', 'PLAN.HOLD.json']:
        raw = (hold / name).read_bytes()
        sdk = json.loads((hold / (name + '.GITHUB.original.json')).read_text())
        sha = identity(raw)['sha']
        assert sdk['creation']['structuredContent']['sha'] == sha
        assert sdk['readback']['structuredContent']['content'].encode() == raw
        add('qualification-final/native-launch-hold/' + name, hold / name, sha, True)

    supplemental = OUT / 'EXTRA_FULL_READBACK_ENTRIES.json'
    if supplemental.exists():
        for row in json.loads(supplemental.read_text()):
            add(row['path'], row['local'], row['sha'], row['full_readback_equal'])

    unique = {}
    for row in rows:
        assert row['path'] not in unique or unique[row['path']]['sha'] == row['sha']
        unique[row['path']] = row
    result = sorted(unique.values(), key=lambda row: row['path'])
    (OUT / 'VERIFIED_INCREMENTAL_ENTRIES.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'verified_entries': len(result), 'bytes': sum(row['bytes'] for row in result),
                      'qualification': False, 'refs_updated': False}))


if __name__ == '__main__':
    main()
