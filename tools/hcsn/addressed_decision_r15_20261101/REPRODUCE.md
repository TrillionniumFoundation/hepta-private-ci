# R15 evidence and reproduction

Run from the repository root. The measured environment was Python 3.12.14,
NumPy 2.3.5, SciPy 1.17.0 and threadpoolctl 3.6.0 on Linux. All scientific workers
used one BLAS thread. Matplotlib is needed only for the presentation figure.

## Immutable identities

| Stage | Commit |
| --- | --- |
| Original executable source/protocol, before training | `7d634a293500982db5beb37fa1d494a75b540a91` |
| Eight fitted candidates and policy selections, before original confirmation | `8aa146bdb9dc7fae8748393cf718e24a7a9db2d3` |
| Supplemental source, failure policy and references to the same frozen models | `e4b51213bd19b6532553d252056573c17abc4814` |
| All original and supplemental raw confirmation archives | `40b2846a86ee1fcc3045a76ac097ce6606ec2b6c` |

`SOURCE_MANIFEST.json` covers the original executable files and imported R11/R12
dependencies. `SUPPLEMENT_MANIFEST.json` covers the new execution wrapper,
supplemental statistics and supplemental protocol. Later reports, audits and
plots do not change either frozen executable experiment.

The initial confirmation is incomplete: eleven workers finished and five stopped
when the index-mean approximation assigned zero likelihood to an actual
observation. Its results are retained but excluded from supplemental effect
estimates. The supplemental experiment uses fresh namespace 4 worlds; it does not
replace or reinterpret namespace 3 results.

## Read the supplied data

Each `run_01/training/*.json.gz` contains the complete observed calibration data,
all candidate evaluations, all validation results, selected ordinary/fixed
policies and learned-controller weights. No training candidate is omitted.

Each `run_02/confirmation/*.json.gz` contains one fit/domain's complete world
tapes, all thirteen arm attempts, actual query/action/token/answer records and
timings. Mean support failures contain null performance and their exact failure
evidence. No epsilon, synthetic zero reward or successful-subset estimate is
substituted. `run_01/confirmation` contains the eleven original completed records.

Small owner checkpoints, logs, claims and process receipts are also preserved in
the two execution evidence archives. Their indexes list individual SHA-256
checksums. To restore these files into a fresh checkout:

```bash
tar -xzf tools/hcsn/addressed_decision_r15_20261101/run_01/EXECUTION_EVIDENCE.tar.gz -C tools/hcsn/addressed_decision_r15_20261101
tar -xzf tools/hcsn/addressed_decision_r15_20261101/run_02/EXECUTION_EVIDENCE.tar.gz -C tools/hcsn/addressed_decision_r15_20261101
```

Development records are separate in `DEVELOPMENT_EVIDENCE.tar.gz`. They are not
formal fitted replicates or confirmation observations. The extra trailing-LF
normalization of early dependency copies is documented separately, including the
pre-normalization source manifest; executable and JSON semantics did not change.

## Check frozen source and recompute the published statistics

This computation does not fit models or generate new worlds:

```bash
OPENBLAS_NUM_THREADS=1 python - <<'PY'
import json
from pathlib import Path
from tools.hcsn.addressed_decision_r15_20261101.campaign import read_json, check_source
from tools.hcsn.addressed_decision_r15_20261101.supplement import check_supplement
from tools.hcsn.addressed_decision_r15_20261101.supplement_statistics import summarize

b = Path('tools/hcsn/addressed_decision_r15_20261101')
print('core', check_source())
print('supplement', check_supplement())
training = [read_json(p) for p in sorted((b/'run_01/training').glob('*.json.gz'))]
confirmation = [read_json(p) for p in sorted((b/'run_02/confirmation').glob('*.json.gz'))]
supervisor = []
for folder, pattern in [(b/'run_01/supervisor', 'train_*.json'),
                        (b/'run_02/supervisor', 'confirm_*.json')]:
    for p in sorted(folder.glob(pattern)):
        item = read_json(p)
        if 'exit_code' in item:
            supervisor.append(item)
result = summarize(training, confirmation, supervisor)
assert result == read_json(b/'results/SUMMARY.json')
print(json.dumps(result['admission'], indent=2))
PY
```

The retained twelve arms have 128 episodes per fit/domain. Fit seed is the
independent unit, n=8. The same eight training seeds appear in both domains;
neither queries nor the supplemental run create additional fitted replicates.
Primary gain uses the registered D-minus-B contrasts with two-domain Holm
adjustment. A mean failure anywhere blocks all mean effect summaries in both
domains. The original confirmation must not be pooled into this calculation.

## Reconstruct the exact progress evidence without duplicate storage

The complete confirmation archives reconstruct all 2,048 JSONL rows, totaling
89,314,299 bytes, with exactly the original sixteen progress checksums. This was
independently verified in `results/INDEPENDENT_EXECUTION_AUDIT.json`.

```bash
OPENBLAS_NUM_THREADS=1 python - <<'PY'
import hashlib
from pathlib import Path
from tools.hcsn.addressed_decision_r15_20261101.campaign import read_json
from tools.hcsn.addressed_decision_r15_20261101.planner import canonical

b = Path('tools/hcsn/addressed_decision_r15_20261101')
out = b/'reconstructed_progress'
out.mkdir(exist_ok=True)
for p in sorted((b/'run_02/confirmation').glob('*.json.gz')):
    d = read_json(p)
    target = out/f"{d['seed']}_{d['domain']}.jsonl"
    h = hashlib.sha256()
    with target.open('xb') as stream:
        for i, tape in enumerate(d['world_tapes']):
            row = dict(index=i, world=tape,
                       arms={name: arm['episodes'][i] for name, arm in d['arms'].items()})
            raw = (canonical(row)+'\n').encode()
            h.update(raw)
            stream.write(raw)
    assert h.hexdigest() == d['progress_journal_sha256']
    print(target.name, h.hexdigest())
PY
```

## Optional deterministic scientific replay

Keep published run directories immutable. To rerun execution with the frozen
models and the same namespace 4 worlds, copy the supplemental freeze and its
publication receipt into a new directory, then launch the supplemental module:

```bash
mkdir tools/hcsn/addressed_decision_r15_20261101/replay
cp tools/hcsn/addressed_decision_r15_20261101/run_02/FREEZE.json tools/hcsn/addressed_decision_r15_20261101/replay/
cp tools/hcsn/addressed_decision_r15_20261101/run_02/SUPPLEMENT_PUBLICATION.json tools/hcsn/addressed_decision_r15_20261101/replay/
OPENBLAS_NUM_THREADS=1 python -m tools.hcsn.addressed_decision_r15_20261101.supplement launch --run tools/hcsn/addressed_decision_r15_20261101/replay --freeze-commit e4b51213bd19b6532553d252056573c17abc4814 --workers 4
```

This is a replay, not a new independent confirmation. CPU, wall time and time
stamps can change across hosts. Exact source/model identity, task results and
paired semantics are the scientific replay targets. The launcher explicitly
uses POSIX `wait4`; this measured workflow is Linux-specific.

## Replay the independent audits in a disposable checkout

The exact historical audit implementations are now retained in
[`audit_sources`](audit_sources/README.md). They are separate from the frozen
experiment and were archived without changing the original implementations. The
execution audit uses Linux/POSIX `fork` and `wait4`; the statistics audit uses
NumPy and SciPy, with no project statistics imports.

Use a **fresh disposable checkout**, extract both execution archives as above,
and keep its working directory at the repository root. Preserve the three
published outputs under a new backup directory before running the historical
scripts, which intentionally refuse to overwrite them:

```bash
python - <<'PY'
from pathlib import Path
b = Path('tools/hcsn/addressed_decision_r15_20261101')
expected = b/'audit_expected_outputs'
expected.mkdir(exist_ok=False)
for name in ['INDEPENDENT_EXECUTION_AUDIT.json',
             'INDEPENDENT_EXECUTION_AUDIT.md',
             'INDEPENDENT_STATISTICS_AUDIT.json']:
    (b/'results'/name).rename(expected/name)
assert not (b/'run_02/progress').exists()
PY
python -m tools.hcsn.addressed_decision_r15_20261101.audit_sources.reconstruct_progress
mv tools/hcsn/addressed_decision_r15_20261101/run_02/reconstructed_progress tools/hcsn/addressed_decision_r15_20261101/run_02/progress
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m tools.hcsn.addressed_decision_r15_20261101.audit_sources.independent_execution_audit
```

The statistics source preserves its historical absolute input path. The following
invocation adapts only that path **in memory** to the disposable checkout; it does
not edit the archived source or any frozen experiment file:

```bash
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 python - <<'PY'
from pathlib import Path
b = Path('tools/hcsn/addressed_decision_r15_20261101').resolve()
p = b/'audit_sources/independent_statistics_audit.py'
code = p.read_text()
old = "H=Path('/workspace/scratch/e0cf0c9f99f7/hepta-hcsn/tools/hcsn/addressed_decision_r15_20261101')"
assert code.count(old) == 1
code = code.replace(old, f'H=Path({str(b)!r})')
exec(compile(code, str(p), 'exec'), {'__name__': '__main__'})
PY
```

Compare the new JSON checks and conclusions with `audit_expected_outputs`.
Process timing, timestamps and later presentation metadata are expected to
differ. The execution script creates its JSON; the published Markdown and the
JSON's human-readable reconstruction command were separate presentation steps.
These replay instructions are optional: the recorded audit results and their
cost receipts remain the evidence of the original executions.

## Numerical checks and presentation

```bash
OPENBLAS_NUM_THREADS=1 python -m unittest tools.hcsn.addressed_decision_r15_20261101.test_audit -v
MPLCONFIGDIR=/tmp/hcsn-r15-mpl OPENBLAS_NUM_THREADS=1 python tools/hcsn/addressed_decision_r15_20261101/results/plot_results.py
```

The independent audit reports recomputed raw-world targets, emitted tokens,
actions, fees, state/checkpoint hashes and statistics without calling the project
summarizers or the original execution owners. Their scope and measured cost are
recorded in the reports. `RESEARCH_COST_LEDGER.json` separates nonoverlapping
measured research expense from the predeclared per-method deployment reuse
formula. It does not claim to meter all report generation, remote transfer,
hardware energy or production owner/network costs.
