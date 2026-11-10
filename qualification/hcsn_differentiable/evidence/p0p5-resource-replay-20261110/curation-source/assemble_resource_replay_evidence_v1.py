"""Copy explicit completed evidence bytes into a new, unfrozen archive prefix."""
import hashlib
import json
from pathlib import Path
import shutil
import time
import zipfile


ROOT = Path('/workspace/scratch/c385a7439f8e')
DEST = ROOT / 'hcsn-repo/qualification/hcsn_differentiable/evidence/p0p5-resource-replay-20261110'


def ident(path):
    raw = path.read_bytes()
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def main():
    started, cpu = time.perf_counter(), time.process_time()
    manifest_path = DEST / 'MANIFEST.json'
    if manifest_path.exists():
        raise RuntimeError('Archive already frozen; no mutation allowed')
    DEST.mkdir(parents=True, exist_ok=True)
    pairs = []
    trees = [
        ('resource-analysis-v1', 'resource-analysis-v1'),
        ('resource-analysis-independent-review-v1', 'independent-resource-review-v1'),
        ('committed-evidence-recovery-checks-v1', 'publication/committed-evidence-recovery-checks-v1'),
        ('committed-current-evidence-closure-v1', 'publication/committed-current-evidence-closure-v1'),
        ('committed-current-evidence-closure-v2', 'publication/committed-current-evidence-closure-v2'),
        ('final-retained-trace-labels-recovery-v1', 'trace-coverage/recovery-v1'),
        ('final-retained-trace-labels-archive-v1', 'trace-coverage/originals-v1'),
    ]
    for source_name, target_name in trees:
        source = ROOT / source_name
        if not source.is_dir():
            raise FileNotFoundError(source)
        for file in sorted(source.rglob('*')):
            if '__pycache__' in file.parts:
                continue
            if file.is_file():
                pairs.append((file, target_name + '/' + file.relative_to(source).as_posix()))
    source = ROOT / 'fresh42-c1-curves-recovered-v1'
    for file in sorted(source.iterdir()):
        if file.name != 'CURVES.json' and file.is_file():
            pairs.append((file, 'curves-originals/' + file.name))
    singles = {
        'resource-analysis-independent-review-v1.zip': 'independent-resource-review-v1.zip',
        'final-retained-trace-labels-20261110-v1.zip': 'trace-coverage/final-retained-trace-labels-20261110-v1.zip',
        'assemble_resource_replay_evidence_v1.py': 'curation-source/assemble_resource_replay_evidence_v1.py',
        'verify_committed_evidence_v1.py': 'publication/verify_committed_evidence_v1.py',
    }
    publication = [
        'archival-ignored-logs-recovery-local-v1.json', 'hcsn-archival-log-recovery-api-v1.json',
        'committed-evidence-coverage-failure-v1.json', 'committed-evidence-recovery-source-scope-addendum-v1.json',
        'hcsn-followup-prepublication-incomplete-stages-v1.json', 'hcsn-followup-pr-created-v1.json',
        'hcsn-current-local-stages-v1.json', 'hcsn-current-api-progress-v1.json',
        'hcsn-current-branch-create-v1.json', 'hcsn-current-pr-created-v1.json',
        'hcsn-resources-local-stages-v1.json', 'hcsn-resources-api-progress-v1.json',
        'hcsn-resources-branch-create-v1.json', 'hcsn-resources-pr-created-v1.json',
        'resource-analysis-just-fmt-preflight-failure-v1.json', 'resource-analysis-just-fmt-v2.json',
    ]
    singles.update({name: 'publication/' + name for name in publication})
    singles.update({name: 'ci/' + name for name in [
        'hcsn-ci-current-head-observation-v1.json', 'hcsn-ci-failure-and-current-jobs-v1.json']})
    for source_name, target_name in singles.items():
        pairs.append((ROOT / source_name, target_name))
    records = []
    for source, relative in pairs:
        if source.is_symlink() or not source.is_file():
            raise ValueError('Nonregular source: ' + str(source))
        target = DEST / relative
        expected = ident(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if ident(target) != expected:
                raise ValueError('Existing target differs: ' + relative)
        else:
            with target.open('xb') as out:
                out.write(source.read_bytes())
        if ident(source) != expected or ident(target) != expected:
            raise ValueError('Copy identity changed: ' + relative)
        records.append({'source': str(source), 'target': relative, **expected})
    ci_root = ROOT / 'current-ci-original-logs-v1'
    archive = DEST / 'ci/current-ci-decoded-logs-v1.zip'
    ci_files = sorted(ci_root.iterdir())
    if archive.exists():
        raise RuntimeError('CI archive already created; do not silently regenerate')
    members = {p.name: ident(p) for p in ci_files if p.is_file()}
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for file in ci_files:
            if file.is_file():
                z.write(file, file.name)
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None or set(z.namelist()) != set(members):
            raise ValueError('CI ZIP structure or CRC mismatch')
        for name, expected in members.items():
            raw = z.read(name)
            if {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()} != expected:
                raise ValueError('CI ZIP member differs')
    receipt = {'schema': 'hcsn-resource-replay-base-copy-v1', 'copied_files': records,
               'ci_decoded_log_archive': {'archive': ident(archive), 'members': members,
                    'scope': 'Exact UTF-8 encoding of connector-decoded job log strings; HTTP compressed transport bytes were not observed.'},
               'source_unchanged': True, 'main_entry_wall_seconds': time.perf_counter() - started,
               'main_entry_CPU_seconds': time.process_time() - cpu,
               'cost_scope': 'Base copy, file hashing and CI ZIP CRC/member verification; excludes imports and final receipt write/exit.'}
    with (DEST / 'BASE-COPY-RECEIPT.json').open('x') as stream:
        json.dump(receipt, stream, indent=2)
        stream.write('\n')
    print(json.dumps({'files': len(records), 'ci_archive': ident(archive), 'dest': str(DEST)}))


if __name__ == '__main__':
    main()
