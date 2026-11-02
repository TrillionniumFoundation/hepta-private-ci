# Reproduction and frozen evidence

Run from the full repository root with Python 3.10+, NumPy and SciPy (this run used Python 3.12). PyTorch is not needed for the new candidates. The inherited v8 PyTorch scripts remain unchanged and require their original environment.

First restore the original compressed trace bytes:

```bash
python -m experiments.hcsn_v9_followup_20261101.publication.restore
```

The restore command verifies sizes, SHA256 and Git blob identities of all three ordered parts and the complete original. Existing divergent evidence is rejected. `publication/VALIDATION.json` records six recovery/corruption/path checks. `SOURCE_RECOVERY_CHECK.json` records 78 byte-exact baseline files. The complete remote base tree is preserved; the local editing environment reconstructed only the files needed for this work.

Read existing results before generating new runs:

- `frontend/OBSERVED_RESULT.json`: actual missing-source FAIL; synthetic admission fixtures do not qualify real assets.
- `persistent_core/results/development001/{PLAN,FIT,FROZEN_MODELS,SUMMARY}.json` and `AUDIT.json`.
- `refit_ablation/results/development001/` and `development002/`: distinct plans, exact source snapshots and all failed/successful optimizer candidates. Current campaign source corresponds to round 002.
- `risk/results/development001/{PLAN,SUMMARY,SENSITIVITY,JSON_AUDIT}.json` and `runs.jsonl`.
- `economics/SUMMARY.json`, `AUDIT002.json` and all eleven original receipts/samples.
- `review/`: independent cross-module reconstruction, including the initial source-identity refusal and its snapshot-based resolution.

Behavioral checks (run before the final formatting attempt under AGENTS.md):

```bash
python -m unittest discover -s experiments/hcsn_v9_followup_20261101/frontend -p test_admission.py -v
python -m unittest experiments.hcsn_v9_followup_20261101.persistent_core.test_models experiments.hcsn_v9_followup_20261101.refit_ablation.test_refit experiments.hcsn_v9_followup_20261101.risk.test_study -v
```

New output paths are required; keep original frozen results intact. Example persistent experiment:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m experiments.hcsn_v9_followup_20261101.persistent_core.campaign prepare --output /tmp/hcsn-persistent-new
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m experiments.hcsn_v9_followup_20261101.persistent_core.campaign run --output /tmp/hcsn-persistent-new
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m experiments.hcsn_v9_followup_20261101.persistent_core.audit /tmp/hcsn-persistent-new
```

For fresh refitting, use `refit_ablation.campaign prepare` and `execute --output /tmp/hcsn-refit-new`; the directory README gives exact commands. For risk, use `risk.study prepare` and `execute --output /tmp/hcsn-risk-new`, followed by `risk.validate_results` and `risk.sensitivity` with that directory as the positional argument.

Wrap a fresh research command to collect its own disjoint task CPU and sampled family memory:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python experiments/hcsn_v9_followup_20261101/economics/family_cost.py --out /tmp/hcsn-new-cost --interval 0.05 --timeout 900 -- python -m experiments.hcsn_v9_followup_20261101.persistent_core.campaign run --output /tmp/hcsn-persistent-new
```

The wrapper's scope excludes its own imports/capability probes and final receipt serialization. A receipt containing `sampled_partial` does not establish complete memory; device energy and missing preparation costs stay unknown. Costs from component timers are nested and must not be added to enclosing task CPU again. Shared-host wall time is not an isolated deployment latency claim.

Reproductions may differ in timestamps, CPU/wall measurements and gzip metadata. Model/world content is tied to the declared frozen source and seeds. No real AV qualification, architectural adoption, full Rust CI or production activation is asserted.
