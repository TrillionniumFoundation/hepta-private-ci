"""Copy immutable follow-up evidence without changing the earlier snapshot."""

import hashlib
import json
from pathlib import Path
from shutil import copyfile


ROOT = Path('/workspace/scratch/c385a7439f8e')
REPO = ROOT / 'hcsn-repo'
DEST = REPO / 'qualification/hcsn_differentiable/evidence/p0p5-followup-20261110'
RECEIPT = ROOT / 'followup-evidence-copy-progress-v1.json'
OLD_MANIFEST = REPO / 'qualification/hcsn_differentiable/evidence/p0p5-20261110/MANIFEST.json'
OLD_SHA = 'bc8721b37d4a69c28a25a028dd6375ebbeaaa41111bafc97a22b7239609f5bc6'


def identity(path):
    raw = path.read_bytes()
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def main():
    assert identity(OLD_MANIFEST)['sha256'] == OLD_SHA
    prior = json.loads(RECEIPT.read_text()) if RECEIPT.exists() else {'files': {}}
    rows = prior['files']

    def retain(source, name, expected=None):
        source = Path(source)
        target = DEST / name
        source_identity = identity(source)
        if expected is not None:
            assert source_identity == expected, (source, source_identity, expected)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            assert identity(target) == source_identity, target
        else:
            copyfile(source, target)
        assert identity(target) == source_identity
        rows[name] = {'source': str(source), **source_identity}

    handoff = json.loads((ROOT / 'independent-final-review-handoff-v1.json').read_text())
    for item in handoff['artifacts']:
        directory = Path(item['directory'])
        stem = directory.name
        for source in sorted(directory.rglob('*')):
            if source.is_file() and '__pycache__' not in source.parts:
                relative = source.relative_to(directory).as_posix()
                expected = item['reports'].get(relative)
                retain(source, 'review/' + stem + '/' + relative, expected)
        archive = item['archive']
        retain(archive['path'], 'review/' + stem + '.zip',
               {'bytes': archive['bytes'], 'sha256': archive['sha256']})

    # The delta reviewer imports this exact earlier helper outside its own ZIP.
    helper = ROOT / 'final-curation-independent-review-v1/review_final_curation_v1.py'
    exec_row = json.loads((ROOT / 'final-curation-delta-review-v2/EXECUTION.json').read_text())
    retain(helper, 'review/final-curation-independent-review-v1/review_final_curation_v1.py',
           exec_row['source_before'][str(helper)])
    retain(ROOT / 'independent-final-review-handoff-v1.json', 'review/HANDOFF.json')

    for name in ['baseline36-c1-aggregate-originals-v1.zip',
                 'baseline36-c1-aggregate-originals-v1-receipt.json']:
        retain(ROOT / name, 'review/' + name)
    for name in ['PLAN.json', 'MANIFEST.json', 'README.md', 'freeze_plan.py',
                 'recorder-scope-MANIFEST.json', 'recorder-scope-RESULT.json',
                 'recorder-scope-REVIEW.md', 'recorder-scope-fact_check.py',
                 'training-source-v8.zip']:
        retain(ROOT / 'final-hcsn-numerical-plan-v1' / name,
               'plans/final-hcsn-numerical-plan-v1/' + name)
    retain(ROOT / 'final-hcsn-numerical-plan-v1.zip', 'plans/final-hcsn-numerical-plan-v1.zip')

    upload_dir = ROOT / 'review-profile-evidence-upload-receipts-v1'
    upload_map = json.loads((upload_dir / 'MINIMAL-COPY-LIST.json').read_text())
    for row in upload_map['files']:
        source = Path(row['source'])
        if source.parent == upload_dir or source.name == 'archive_profile_upload_reviews_v1.py':
            retain(source, 'publication/review-profile-assets-v1/' + source.name,
                   {'bytes': row['bytes'], 'sha256': row['sha256']})
    retain(upload_dir / 'MINIMAL-COPY-LIST.json', 'publication/review-profile-assets-v1/MINIMAL-COPY-LIST.json')

    for name in ['hcsn-evidence-pr-created-v1.json', 'hcsn-protocol-pr-created-v1.json',
                 'hcsn-protocol-api-receipt-v1.json']:
        retain(ROOT / name, 'publication/' + name)
    for name in ['evidence-integrity-current-closure-v1.json',
                 'evidence-integrity-current-closure-v1-receipt.json',
                 'evidence-integrity-current-closure-v1.stdout',
                 'evidence-integrity-current-closure-v1.stderr',
                 'current-protocol-just-fmt-v1.json',
                 'current-protocol-just-fmt-v1.stdout',
                 'current-protocol-just-fmt-v1.stderr',
                 'current-protocol-just-fmt-v2.json',
                 'current-protocol-just-fmt-v2.stdout',
                 'current-protocol-just-fmt-v2.stderr']:
        retain(ROOT / name, 'verification/' + name)
    for name in ['native-hcsn-terminal-20261110-1851-v1.json',
                 'native-hcsn-terminal-20261110-1851-launch.json',
                 'native-hcsn-terminal-20261110-1851-status.json']:
        retain(ROOT / name, 'original42/' + name)

    assert identity(OLD_MANIFEST)['sha256'] == OLD_SHA
    receipt = {'schema': 'hcsn-followup-exact-copy-progress-v1',
               'frozen_previous_manifest_sha256': OLD_SHA,
               'files': dict(sorted(rows.items())),
               'status': 'working_followup_package_not_final_admission'}
    RECEIPT.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'files': len(rows), 'bytes': sum(row['bytes'] for row in rows.values()),
                      'destination': str(DEST), 'previous_manifest_unchanged': True}))


if __name__ == '__main__':
    main()
