"""Append exact review/publication originals without changing the frozen snapshot."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time


ROOT = Path('/workspace/scratch/c385a7439f8e')
DEST = ROOT / 'hcsn-repo/qualification/hcsn_differentiable/evidence/p0p5-resource-closure-20261110'


def identity(path):
    data = path.read_bytes()
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def write(name, value):
    path = DEST / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        if isinstance(value, str):
            stream.write(value)
        else:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write('\n')


def main():
    start, cpu = time.perf_counter(), time.process_time()
    DEST.mkdir(exist_ok=False)
    pairs = []
    for source, target in [
        ('resource-replay-index-independent-review-v1', 'independent-index'),
        ('resource-replay-integrity-v1', 'verification/integrity-v1-failed-entry'),
        ('resource-replay-integrity-v2', 'verification/integrity-v2'),
        ('committed-resource-evidence-closure-v1', 'verification/committed-v1-preflight-failure'),
        ('committed-resource-evidence-closure-v2', 'verification/committed-v2'),
    ]:
        directory = ROOT / source
        for path in sorted(directory.rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts:
                pairs.append((path, target + '/' + path.relative_to(directory).as_posix()))
    for name in ['hcsn-resource-evidence-local-stages-v1.json', 'hcsn-resource-evidence-api-progress-v1.json',
                 'hcsn-resource-evidence-branch-create-v1.json', 'hcsn-resource-evidence-pr-created-v1.json',
                 'hcsn-resource-evidence-api-attempt-v1-failure.json', 'hcsn-resource-evidence-api-attempt-v2-intent.json',
                 'hcsn_resource_evidence_publish_helpers_v1.js', 'hcsn_resource_evidence_publish_helpers_v2.js']:
        pairs.append((ROOT / name, 'publication/' + name))
    pairs += [(ROOT / 'resource-evidence-just-fmt-v1.json', 'verification/just-fmt-v1.json'),
              (ROOT / 'resource-replay-index-independent-review-v1.zip', 'independent-index.zip'),
              (Path(__file__), 'curation-source/build_resource_closure_v1.py')]
    copied = []
    for source, relative in pairs:
        expected = identity(source)
        target = DEST / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(source.read_bytes())
        assert identity(source) == identity(target) == expected
        copied.append({'source': str(source), 'target': relative, **expected})

    rows = []
    for name, path, scope, fields in [
        ('independent-index-review', 'independent-index/OUTER.json',
         'Complete read-only child; no resource algorithm, model or oracle rerun.', ['complete_child_wall_seconds', 'waited_child_CPU_seconds']),
        ('direct-file-import-failure', 'verification/integrity-v1-failed-entry/EXECUTION.json',
         'Complete failed child. Direct-file entry shadows stdlib operator before verifier main; no evidence check executed.', ['whole_child_wall_seconds', 'waited_child_CPU_seconds']),
        ('module-integrity-success', 'verification/integrity-v2/EXECUTION.json',
         'Distinct complete child, established module entry; same verifier and original evidence bytes.', ['whole_child_wall_seconds', 'waited_child_CPU_seconds']),
        ('Git-wrapper-preflight-failure', 'verification/committed-v1-preflight-failure/PREFLIGHT-FAILURE.json',
         'Wrapper selected -B as a source path; before child launch, not a failed Git evidence check. Cost unknown.', ['complete_process_wall_seconds', 'process_CPU_seconds']),
        ('Git-object-verification', 'verification/committed-v2/EXECUTION.json',
         'Complete child with source/explicit inputs hashed before and after; exact committed files, not ignored worktree availability.', ['whole_child_wall_seconds', 'waited_child_CPU_seconds']),
        ('archive-formatter', 'verification/just-fmt-v1.json',
         'Complete cached formatter invocation; all 229 frozen snapshot files unchanged.', ['whole_child_wall_seconds', 'waited_child_CPU_seconds']),
    ]:
        data = json.loads((DEST / path).read_text())
        rows.append({'id': name, 'artifact': path, 'artifact_identity': identity(DEST / path),
                     'measurements': {key: data[key] for key in fields}, 'scope': scope})
    rows.append({'id': 'hosted-fixture-timing-index', 'artifact': 'independent-index/HOSTED-FIXTURE-COST-ADDENDUM.json',
                 'artifact_identity': identity(DEST / 'independent-index/HOSTED-FIXTURE-COST-ADDENDUM.json'),
                 'scope': 'Five exact original artifact-member timings, nested within hosted CI and separate from artifact collection; no rerun or complete job total.'})
    rows.append({'id': 'API-publication', 'artifact': 'publication/hcsn-resource-evidence-api-progress-v1.json',
                 'artifact_identity': identity(DEST / 'publication/hcsn-resource-evidence-api-progress-v1.json'),
                 'scope': 'First content-addressed tree request disconnected; branch readback unchanged. Second invocation used smaller batches and verified the exact final tree. API transport wall/CPU/currency unknown; no model/CI rerun.',
                 'measurements': {'complete_transport_wall_seconds': None, 'transport_CPU_seconds': None, 'billed_currency': None}})
    write('COSTS.json', {'schema': 'resource-closure-costs-v1', 'previous_ledger': '../p0p5-resource-replay-20261110/COSTS.json',
          'rows': rows, 'index_curation_cost': 'COPY-RECEIPT.json', 'accounting_complete': False,
          'additive_grand_total': None, 'energy_joules': None, 'billed_currency': None,
          'rule': 'Keep failed attempts. Do not sum nested fixture/job/bootstrap/controller costs; unknown costs are not zero.'})
    write('README.md', '''# Resource evidence closure and cost-index supplement

This appendix preserves verification and publication records created after the
[resource/replay snapshot](../p0p5-resource-replay-20261110/README.md) was frozen.
It does not modify that snapshot or change numerical or scientific admission.

## Independent review and published Git objects

The [independent review](independent-index/REVIEW.md) binds all 228 snapshot
members, eight ZIPs, 21 original cost records and 34 document links. No resource
algorithm, model or numerical oracle was rerun. The
[working integrity result](verification/integrity-v2/RESULT.json) agrees.

The [committed-tree result](verification/committed-v2/RESULT.json) verifies
1,022 distinct regular blobs across five manifests and the explicitly bound
entrypoint dependencies. It checks local commit
`7c334a4de49aa711ca5aca5fee4a3443a026ec46`, tree
`da62f605dfa9771c439d0f91edf3deff5aed7818`. The
[API readback](publication/hcsn-resource-evidence-api-progress-v1.json) confirms
the identical whole tree at remote commit
`14e8427f46d6517d8d57649b8ac0b888b1c991e8`.
[Draft PR 5848](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5848)
contains the 229-file mechanical archival stage. This verifies those source
trees, not this later appendix, a future CURRENT edit, or overall CI success.

The first API attempt disconnected during a content-addressed tree request;
whether that tree object was created was not observed. The retained
[reconciliation](publication/hcsn-resource-evidence-api-attempt-v1-failure.json)
shows no completed commit stage and the branch still at its original base.
A distinct invocation used smaller tree batches and completed whole-tree and
branch readback. No model, oracle or original training job was rerun.

## Exact reproduction entry and retained wrapper failures

From the repository root, use the established module entry:

```bash
python -B -m qualification.hcsn_differentiable.evidence_chain \\
  --manifest qualification/hcsn_differentiable/evidence/p0p5-resource-replay-20261110/MANIFEST.json \\
  --markdown qualification/hcsn_differentiable/evidence/p0p5-resource-replay-20261110/README.md \\
  --output /tmp/hcsn-resource-integrity-new.json
```

Choose a new output path; the checker preserves existing results. The initial
direct-file invocation failed during Python imports because package
`operator.py` shadowed the standard-library module. Its
[original stderr](verification/integrity-v1-failed-entry/stderr) and cost are
retained. The subsequent module invocation used unchanged verifier/evidence
bytes and passed. This is an entry-command correction, not an acceptance-rule
change. A separate Git-proof wrapper preflight mistakenly selected `-B` as a
source filename before launching its child; the
[preflight failure](verification/committed-v1-preflight-failure/PREFLIGHT-FAILURE.json)
is retained, and the corrected invocation checks the actual verifier script.

## Hosted fixture cost supplement

The [member-level supplement](independent-index/HOSTED-FIXTURE-COST-ADDENDUM.json)
indexes existing measurements inside original science artifact 13797877354,
run 42890048946 attempt 1. Exact member sizes and hashes bind each value:

| Artifact member | Original timer | Scope |
| --- | ---: | --- |
| qualification.json | 8.136141368 s wall; 8.124293353 s process CPU | Qualification interval after imports |
| error-budget.json | 6.990235205 s wall | Historical error-budget fixtures |
| qvi-oracle.json | .044480695 s wall | Finite QVI fixture report interval |
| qvi-tests.log | .119 s | Unittest internal timer, three tests |
| memory-controls-tests.log | .003 s | Unittest internal timer, three tests |

These are nested hosted-job measurements. They are separate from the already
charged artifact-download/collection process; they are not a complete job CPU,
calendar, energy or billing total. No CI run was repeated to obtain them.
[COSTS.json](COSTS.json) also retains the independent review, both invocation
failures, successful integrity/Git checks, formatter and unknown API transport
costs. [COPY-RECEIPT.json](COPY-RECEIPT.json) records local curation samples.

The original six HCSN fits remain budget-censored, all original retained
training traces remain at update zero, and whole-training numerical admission
and scientific benefit remain HOLD. Current numerical-audit and C2-preparation
work are outside this completed appendix.
''')
    assert all(identity(DEST / row['target']) == {'bytes': row['bytes'], 'sha256': row['sha256']} for row in copied)
    write('COPY-RECEIPT.json', {'schema': 'resource-closure-copy-v1', 'copied': copied,
          'source_files_unchanged': True, 'curated_utc': datetime.now(timezone.utc).isoformat(),
          'main_entry_wall_seconds': time.perf_counter() - start, 'main_entry_CPU_seconds': time.process_time() - cpu,
          'scope': 'Main-entry exact copies, hashes and index construction; excludes imports and final receipt/manifest/exit.',
          'model_or_oracle_execution': False})
    files = {p.relative_to(DEST).as_posix(): identity(p) for p in sorted(DEST.rglob('*')) if p.is_file()}
    write('MANIFEST.json', {'schema': 'resource-closure-manifest-v1', 'files': files, 'scientific_admission': 'HOLD'})
    print(json.dumps({'files': len(files), 'manifest': identity(DEST / 'MANIFEST.json')}))


if __name__ == '__main__':
    main()
