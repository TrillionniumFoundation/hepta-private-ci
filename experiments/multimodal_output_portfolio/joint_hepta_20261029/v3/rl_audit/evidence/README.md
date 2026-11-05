# Frozen full-run evidence

Read [the Chinese results report](../RESULTS.zh-CN.md) and [SUMMARY.json](SUMMARY.json)
for the scientific outcome. All registered phases completed; superiority, a novel
algorithm, real LLM efficacy and complete-cost amortization remain unestablished.
The execution source is `062b6dd7c730c4795ae617f4c85278dd2ac821d7`.

## Raw run and integrity

`formal_001_archive/` retains all 76 original files, including registration,
completion, GitHub source readback, phase start/results, empty-or-complete process
logs, whole-process receipts, every model/observation shard and all service/failure
records. The 13,240,578 raw bytes are stored as nine bounded binary parts totaling
3,915,296 bytes. The part order, sizes, SHA-256 hashes, Git blob identities and all
member hashes are in [PARTS.json](formal_001_archive/PARTS.json).

From a repository checkout containing this evidence, restore to a **new** directory:

```bash
audit_dir=experiments/multimodal_output_portfolio/joint_hepta_20261029/v3/rl_audit
python "$audit_dir/evidence/formal_001_archive/restore.py" --output /tmp/ndu-restored-001
```

The restored root contains `run_20261105_001/`. The helper validates every part,
the complete archive and the exact member roster before creating the output.
It does not overwrite existing output or accept unregistered archive members.
[PACKAGING_CHECK.json](formal_001_archive/PACKAGING_CHECK.json) records actual full
restoration and deliberate one-byte-corruption rejection. This integrity check
is additional publication work, not an original experiment or training expense.

## Independent calculation paths

| Directory | Reanalysis | Limits |
| --- | --- | --- |
| `review_semantics/` | Explicit closed-form values/gradients, counterexamples, source/readback and six-panel roster | Implementer reanalysis, no independent institution |
| `review_structure_20261105_001/` | 41,761 checks, all 480 checkpoint identities, all 82,560 decisions | No retraining or independent clock provenance |
| `review_tools/` | 5,126 checks, all 108 services, final code outputs, models, effects and cost scopes | No repeated training/service, known templates, implementer reanalysis |

These review files are outside the raw archive so their scripts and reports can
be reviewed directly. They do not change original source or original run files.
The structure report's quadratic-value baseline is a consistent post-hoc
descriptive display, not a preregistered primary comparison.

To use the original review scripts, place the restored `run_20261105_001/` beside
these review directories in an independent checkout. The structural reviewer
accepts explicit input and new output paths as documented in its REVIEW.md.
The semantic and tool reviewers use their sibling raw-run path and exclusively
create `REVIEW.json`; preserve their published REVIEW.json under another name
before replaying in that independent checkout. They intentionally refuse to
overwrite published output. Remote-readback receipts are retained source
provenance, not authenticated network operations repeated by offline reviewers.

## New experiments

The source manifest is unchanged in the evidence publication. Run the frozen
scientific source separately, with a fresh output directory:

```bash
python -B -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.rl_audit.run --source-commit 062b6dd7c730c4795ae617f4c85278dd2ac821d7 --output /tmp/ndu-new-run
```

Python 3.12.14 and NumPy 2.3.5 were used; Linux wait4 measures child costs. The
launcher fixes numerical-library thread counts to one, isolates imports, validates
the full case roster and checks source bytes before/after. Wall/CPU timings will
vary. A new run is additional evidence; it must not replace this original run.
The source SHA is bound to its remote tree by the archived GitHub readback receipt;
the authoring subset's local git HEAD is never used as that remote identity.
