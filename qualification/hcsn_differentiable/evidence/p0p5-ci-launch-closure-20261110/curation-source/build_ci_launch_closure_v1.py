"""Retain completed CI, source-tree and launch-index verifications as an appendix."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import zipfile


ROOT = Path('/workspace/scratch/c385a7439f8e')
DEST = ROOT / 'hcsn-repo/qualification/hcsn_differentiable/evidence/p0p5-ci-launch-closure-20261110'
COPIES = []


def ident(path):
    data = path.read_bytes()
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def write(relative, value):
    path = DEST / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as f:
        f.write(value if isinstance(value, str) else json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def copy(source, relative):
    path = ROOT / source
    before = ident(path)
    target = DEST / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as stream:
        stream.write(path.read_bytes())
    assert ident(path) == ident(target) == before
    COPIES.append({'source': str(path), 'target': relative, **before})


def directory(source, target):
    base = ROOT / source
    for path in sorted(base.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts:
            copy(str(path.relative_to(ROOT)), target + '/' + path.relative_to(base).as_posix())


def archive_originals(relative, originals):
    target = DEST / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    entries = []
    with zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source in originals:
            path = ROOT / source
            before = ident(path)
            data = path.read_bytes()
            archive.writestr(source, data)
            assert ident(path) == before
            entries.append({'source': str(path), 'member': source, **before})
        archive.writestr('MEMBER-MANIFEST.json', json.dumps({'files': entries}, indent=2, sort_keys=True) + '\n')
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        for row in entries:
            data = archive.read(row['member'])
            assert len(data) == row['bytes'] and hashlib.sha256(data).hexdigest() == row['sha256']
    write(relative + '.json', {'schema': 'original-byte-archive-v1', 'archive': relative, **ident(target), 'members': entries})


def main():
    start, cpu = time.perf_counter(), time.process_time()
    DEST.mkdir(exist_ok=False)
    for source, target in [
        ('resource-current-six-manifest-validation-v1', 'earlier-tree/worktree-integrity'),
        ('current-resource-git-object-proof-v1', 'earlier-tree/committed-blobs'),
        ('codespell-encoded-evidence-fix-v1', 'codespell-fix'),
        ('c2-launch-package-build-v1', 'c2-launch-checks/packaging'),
        ('c2-launch-integrity-v1', 'c2-launch-checks/integrity'),
        ('c2-launch-codespell-v1', 'c2-launch-checks/codespell'),
        ('c2-launch-formatter-v1', 'c2-launch-checks/formatter'),
        ('c2-launch-publication-screen-v1', 'c2-launch-checks/publication-screen'),
    ]:
        directory(source, target)
    for source, target in [
        ('science-ci-artifact-42899977177-v1.zip', 'science-original/collection-original.zip'),
        ('science-ci-artifact-42899977177-v1/VERIFICATION.json', 'science-original/VERIFICATION.json'),
        ('science-ci-artifact-42899977177-v1/COST-ADDENDUM.json', 'science-original/COST-ADDENDUM.json'),
        ('science-ci-artifact-42899977177-v1/originals/identity.json', 'science-original/identity.json'),
        ('science-ci-artifact-42899977177-v1/originals/outcome.json', 'science-original/outcome.json'),
        ('science-ci-artifact-42899977177-v1/originals/ARTIFACT-MEMBERS.json', 'science-original/ARTIFACT-MEMBERS.json'),
        ('science-ci-artifact-42899977177-v1/originals/science-run-42899977177-attempt1-artifact-13802347858.zip', 'science-original/artifact-13802347858.zip'),
        ('hcsn-current-resources-local-stages-v1.json', 'publication/current-resources-local-stages.json'),
        ('hcsn-current-resources-api-progress-v1.json', 'publication/current-resources-api-progress.json'),
        ('hcsn-current-resources-pr-updated-v2.json', 'publication/current-resources-pr.json'),
        ('hcsn_current_resources_publish_helpers_v1.js', 'publication/publish_helpers.js'),
        ('hcsn-c2-launch-local-stages-v1.json', 'c2-launch-checks/LOCAL-COMMIT.json'),
        ('hcsn-ci-codespell-head-observation-save-failure-v1.json', 'ci/observation-save-failure.json'),
        ('build_ci_launch_closure_v1.py', 'curation-source/build_ci_launch_closure_v1.py'),
    ]:
        copy(source, target)
    archive_originals('ci/observations-original.zip', [
        'hcsn-ci-resource-current-observation-v1.json',
        'hcsn-resource-ci-artifact-and-old-blocking-jobs-v1.json',
        'hcsn-ci-codespell-head-observation-v1.json',
    ])
    archive_originals('ci/older-blocking-decoded-logs.zip', [
        'ci-current-blocking-original-logs-v1/codespell.log',
        'ci-current-blocking-original-logs-v1/contract.log',
        'ci-current-blocking-original-logs-v1/RECEIPT.json',
    ])
    rows = []
    for identifier, path, scope in [
        ('six-manifest-worktree-proof', 'earlier-tree/worktree-integrity/EXECUTION.json', 'Whole child: six manifests and original Markdown inputs; not this later appendix.'),
        ('1068-committed-blob-proof', 'earlier-tree/committed-blobs/EXECUTION.json', 'Whole child: exact a33490 local commit/tree, matching remote652263 tree; not this later appendix.'),
        ('c2-launch-package', 'c2-launch-checks/packaging/EXECUTION.json', 'Whole child: exact original-byte packaging, not training.'),
        ('c2-launch-integrity', 'c2-launch-checks/integrity/EXECUTION.json', 'Whole child: 145 members,11 ZIPs,35 links; split archive reassembly is separately bound by the package builder.'),
        ('c2-launch-codespell', 'c2-launch-checks/codespell/EXECUTION.json', 'Whole child: codespell2.4.3 on new immutable archive text.'),
        ('c2-launch-formatter', 'c2-launch-checks/formatter/RESULT.json', 'Whole child: formatter; all146 frozen files unchanged.'),
    ]:
        d = json.loads((DEST / path).read_text())
        rows.append({'id': identifier, 'artifact': path, 'identity': ident(DEST / path),
                     'whole_child_wall_seconds': d['whole_child_wall_seconds'], 'waited_child_CPU_seconds': d['waited_child_CPU_seconds'], 'scope': scope})
    rows += [
        {'id': 'codespell-red-green-and-install', 'artifacts': ['codespell-fix/RESULT.json', 'codespell-fix/offline-resolution-failure.json', 'codespell-fix/online-tool-setup.json', 'codespell-fix/FORMATTER.json'],
         'scope': 'Retained failed offline tool resolution, isolated tool setup and exact red/green checks. No model-runtime change. Unknown failed-wrapper cost remains unknown.'},
        {'id': 'single-native-science-artifact-download', 'artifact': 'science-original/COST-ADDENDUM.json',
         'scope': 'One native GET plus cloud recovery. Native script CPU and wall are pre-final-serialization samples; waited gh CPU is nested. Hosted inner fixture times are separate, not complete job CPU or billing.'},
        {'id': 'public-archive-pattern-screen', 'artifact': 'c2-launch-checks/publication-screen/RESULT.json',
         'scope': 'Local main-entry interval and CPU prefix only; no complete process total or broad security certification.'},
        {'id': 'API-observations-and-publication', 'artifacts': ['ci/observations-original.zip.json', 'ci/observation-save-failure.json', 'publication/current-resources-api-progress.json'],
         'complete_wall_seconds': None, 'complete_CPU_seconds': None,
         'scope': 'Read-only CI observations and prior draft-branch publication. One local serialization request failed before process creation; original API bytes were retained and saved without another API read.'},
    ]
    write('COSTS.json', {'schema': 'ci-launch-closure-cost-index-v1', 'rows': rows, 'accounting_complete': False,
          'energy_joules': None, 'billed_currency': None, 'additive_grand_total': None,
          'rule': 'Keep failed attempts; do not add nested fixture, child, controller, download or job scopes. Unknown is not zero.', 'curation_cost': 'COPY-RECEIPT.json'})
    write('README.md', '''# Exact CI identities and C2 launch verification appendix

This appendix retains completed checks after the
[resource closure](../p0p5-resource-closure-20261110/README.md) and the
[C2 launch snapshot](../p0p5-c2-launch-20261110/README.md). It does not rewrite
either snapshot, grant numerical admission or declare the ongoing training complete.

## Exact hosted science result

The [original artifact](science-original/artifact-13802347858.zip) is GitHub
artifact13802347858, run42899977177 attempt1: 91,935 bytes, SHA-256
`df70358ffc892bfc535fd6d209fbc81b6c70bc20c0f7d295aec6d1df71c03d22`.
The original ZIP was downloaded once, then checked byte-for-byte and by every
member SHA and CRC. The [collection capsule](science-original/collection-original.zip)
retains frozen collection source, raw transport receipts and verification.

The [actual identity](science-original/identity.json) records source head
`652263b31ebebc4e85b5b2986cb144f0127cbad2`, tested merge
`ffa6eeaa90520ccf234cb6c79828e7d859614fe5`, and identical source/tested tree
`aa5cc6bc55b0dc1cb68adf62886fb9646962de03`. The original
[outcome](science-original/outcome.json) passes declared CPU fixtures. Its
[evidence result](science-original/VERIFICATION.json) binds six manifests,
1,053 files, 51 ZIPs and 287 relative links with zero errors. The 92 software
fixtures and these evidence checks establish neither whole-domain numerical
qualification nor repository-wide CI success.

The [local working-tree result](earlier-tree/worktree-integrity/RESULT.json)
agrees. The separate [committed-blob proof](earlier-tree/committed-blobs/RESULT.json)
checks 1,068 distinct regular Git blobs at local commit
`a33490f926debd60ce21f73b2ea64c1b90b8338a`, whose whole tree matches that remote
source. This proves committed availability, not just files left in a worktree.
Those historical checks do not include this later appendix or the C2 snapshot.

## Narrow spelling failure and later CI observation

The retained [older decoded job logs](ci/older-blocking-decoded-logs.zip)
belong to source `cd3b7ac49294174a98e02636247615534c19bd89` as identified by the
original observation receipts. These are the exact UTF-8 bytes returned by the
connector, not the compressed HTTP log-download payload. The spelling job
flagged five short strings inside one immutable Base64 transport receipt.

Only that exact encoded receipt path was added to the existing workflow skip
list. No original evidence bytes, word allow-list or scientific threshold was
changed. The [same-version red/green check](codespell-fix/RESULT.json) retains
both outcomes and costs using codespell2.4.3. The failed offline tool resolution
and subsequent isolated tool setup also remain. The
[source commit](codespell-fix/SOURCE-COMMIT.json) and
[whole-tree publication records](publication/current-resources-api-progress.json)
bind this narrow fix to remote head
`fdbc954bb259a709275771fe151b4f0c8d245b48`, tree
`626a3ee0ba89432a5203fc00687f8e21781a472b`, in
[draft PR5850](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5850).

The later [read-only CI observation archive](ci/observations-original.zip)
reports scientific run42902660902 and canary42902660830 successful at that
head. Architecture run42902660993 was in progress; blocking run42902661147
was queued. No passing hosted spelling job or all-green CI is inferred from a
queued workflow. The older blocking workflow failed, including an existing
README readiness-discovery contract failure; further unrelated failure causes
are not inferred from job names alone.

The [save-wrapper failure](ci/observation-save-failure.json) preserves a local
argument-length error before process creation. The already obtained API result
was saved in chunks. No API read or CI execution was repeated for that repair.

## C2 snapshot checks and limits

The [C2 manifest verification](c2-launch-checks/integrity/RESULT.json) checks
145 members, 11 directly stored ZIPs and 35 relative links with zero errors.
The snapshot's own archive index separately verifies two split archives by
reassembling their original byte parts, yielding 13 original archives in that
index. The [builder receipt](c2-launch-checks/packaging/EXECUTION.json),
[spelling result](c2-launch-checks/codespell/EXECUTION.json),
[formatter result](c2-launch-checks/formatter/RESULT.json) and
[local commit](c2-launch-checks/LOCAL-COMMIT.json) retain the exact scope.
Formatting changed none of its146 frozen files.

The C2 first-step snapshot records six actual continuations and corresponding
producer witnesses. It does not claim a terminal optimizer/checkpoint audit,
full probability-array verification, adequate training or scientific benefit.
The independent terminal auditor is separate preparation, and the original
terminal numerical audit is still a separate bounded execution.

## Cost and immutable source rules

[COSTS.json](COSTS.json) points to measured intervals and their exact original
receipts. Hosted fixture times are nested within the hosted job; native artifact
collection times are separate. Whole hosted CPU, energy and billing are unknown.
Partial script prefixes and failed-wrapper unknowns are not silently converted
to complete process totals or zero. No model, optimizer, oracle or CI job was
rerun to create this appendix.

Use [MANIFEST.json](MANIFEST.json) with the established module entry
`python -B -m qualification.hcsn_differentiable.evidence_chain`; choose a new
result path. [COPY-RECEIPT.json](COPY-RECEIPT.json) records the exact copied
inputs and curation samples. Scientific and whole-training numerical admission
remain HOLD; P5 remains gated on a demonstrated comparative benefit.
''')
    assert json.loads((ROOT / 'ci-current-blocking-original-logs-v1/RECEIPT.json').read_text())['head_sha'] == 'cd3b7ac49294174a98e02636247615534c19bd89'
    assert all(ident(Path(row['source'])) == ident(DEST / row['target']) == {'bytes': row['bytes'], 'sha256': row['sha256']} for row in COPIES)
    write('COPY-RECEIPT.json', {'schema': 'ci-launch-closure-copy-v1', 'copied': COPIES,
          'source_files_unchanged': True, 'recorded_utc': datetime.now(timezone.utc).isoformat(),
          'main_entry_wall_seconds': time.perf_counter()-start, 'main_entry_CPU_seconds': time.process_time()-cpu,
          'scope': 'Mechanical copies, ZIP creation/member verification and saved-metadata index; excludes imports, final receipt/manifest writes and exit.'})
    write('MANIFEST.json', {'schema': 'ci-launch-closure-manifest-v1',
          'files': {p.relative_to(DEST).as_posix(): ident(p) for p in sorted(DEST.rglob('*')) if p.is_file()},
          'scientific_admission': 'HOLD', 'whole_training_numerical_admission': 'HOLD'})
    print(json.dumps({'manifest': ident(DEST/'MANIFEST.json'), 'files': len(list(DEST.rglob('*')))}))


if __name__ == '__main__':
    main()
