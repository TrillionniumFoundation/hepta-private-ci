# Reproduce and audit the HCSN study

## Published identities and ordering

| Stage | Git commit |
|---|---|
| Prior experimental baseline | `74cf5f30a4e87a2666c57b3f8fba38f8d09fdfd3` |
| Primary source and protocol, including candidate binding | `103be7196bf5d88a5662e57084d5b8761d9a71a3` |
| Secondary LIF/Transformer source and protocol | `cb3a8e1e3422e7477adb41d9e7bff8d20a9810b7` |
| All 54 primary models and six controllers | `2cb71c47503821373bd31790d37febf7af22c84e` |
| All 54 secondary models | `e3571ef540244aee85ff4d0e5575233ab3b869e0` |
| Actual-policy continuation audit and model analysis | `231e02a3badfacf2ad031d09ca9fc79cdd46119a` |
| Policy summary registration | `307ee6264045a26702073cca5afb297db5959393` |

Both full candidate sets, both analysis scripts, and the extra Q-pi audit were
published before any heldout **test** evaluation. Development-set evaluation
preceded candidate freezing and selected the lightweight controller as registered.
The freeze manifests use heldout to mean the final test split. Each checkpoint blob was checked against
an independently computed local Git blob identity. Candidate manifests were fetched
at their pinned commits and compared byte-for-byte with the local manifests before
testing. The source, candidate, and execution receipts retain the timestamps.

The query-binding diagnostic was motivated by the observed recall results. It is
explicitly **post hoc**: it changes no model, optimizer, checkpoint, test selection,
or registered headline comparison. Its evidence is separate from the registered
content matrix.

## Environment

The actual run used Python 3.12.14, NumPy 2.3.5, SciPy 1.17.0, and scikit-learn
1.8.0 on a shared AMD EPYC 9V74 CPU runtime. `ENVIRONMENT.json` records the exact
platform and constraints. For each formal process, all three settings below were
checked before starting the child process:

```bash
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
```

No Torch, JAX, CUDA, Rust application build, or neuromorphic hardware was used.
The Python study is additive; it does not qualify a native production owner.
The root repository's `just fmt` could not run in the API-backed partial worktree:
`just`, Cargo, and the Rust source checkout were unavailable. No Rust file changed.
Python syntax, numerical identities, complete parameter gradients where applicable,
causal execution, frozen artifact identity, and independent expectation sums were
checked directly.

## Restore all raw evidence

The Git tree contains source, contracts, reports, figures, and all 108 final
checkpoints plus six controller payloads directly. To avoid thousands of small
Git publication operations, the entire `evidence/` tree is also preserved in the
deterministic archive parts indexed by `archives/evidence_v1/MANIFEST.json`.

From this experiment directory:

```bash
python archive_evidence.py restore --manifest archives/evidence_v1/MANIFEST.json
```

The restorer checks part, aggregate, and member hashes, accepts only safe evidence
paths, skips an existing identical file, and rejects an existing different file.
It does not overwrite the published original evidence. See `ARCHIVE_EVIDENCE.md`
for the exact archive format and scope.

In a normal Git checkout, verify the originally published candidates with:

```python
import run_study
import secondary_study

source = run_study.verify_freeze()
run_study.verify_candidate(
    "2cb71c47503821373bd31790d37febf7af22c84e", source
)
secondary_study.verify("e3571ef540244aee85ff4d0e5575233ab3b869e0")
```

The verifier compares the candidate manifest against `git show COMMIT:PATH`.
The original API-backed execution instead retained an actual pinned GitHub
readback receipt. A syntactically valid 40-character commit string is insufficient.

## Repeat computation into new directories

Do not overwrite original evidence. For a new replication using the same frozen
source and fixed training protocol:

```bash
python content_audit.py train --out evidence/reproduction/content
python comparison_run.py train --out evidence/reproduction/comparison
python content_audit.py evaluate --out evidence/reproduction/content --split dev
python comparison_run.py evaluate --out evidence/reproduction/comparison --split dev
```

Save the new candidate identities before a new evaluation. For a verification
replication of this already published experiment, compare the new numeric model
arrays with the original candidates, then use:

```bash
python content_audit.py evaluate --out evidence/reproduction/content --split test
python comparison_run.py evaluate --out evidence/reproduction/comparison --split test
python renewal_audit.py --stage formal --out evidence/reproduction/renewal \
  --frozen-commit 103be7196bf5d88a5662e57084d5b8761d9a71a3
```

Floating-point and linear-algebra versions can affect bit identity. Compare those
differences explicitly rather than replacing the original checkpoint hashes.
Wall times, CPU times, and completion timestamps will naturally differ. The
synthetic data seeds, raw batch hashes, pixel split IDs, and dataset hash are fixed.

For re-evaluation of an original frozen model **and original controller**, use
`policy_run.py evaluate` with a new `--output` directory and its original verified
candidate identity. A new `fit` is a new candidate: compare its controller bytes
and content checkpoint against the original manifest. Only byte-identical artifacts
can reuse the old binding. Otherwise record a new complete candidate manifest and
freeze its identity before evaluation; do not label a different refit as the old
published candidate. The top-level wrappers enforce the original manifest binding;
the lower-level `policy_run.py` alone is not proof of remote publication. All six
family–seed combinations (2 families × 3 seeds) and all four test configs remain in the comparison.
`POLICY_CONTRACT.md` gives the full interface.

## Recompute summaries without rerunning training

```bash
python aggregate_results.py --out analysis_recomputed
```

This checks all 108 runs and 324 condition rows, exact train/test batch identities,
saved labels, checkpoint/log hashes, and independently recomputes accuracy and NLL
from the saved logits. It retains all 81 primary paired comparisons and all 54
frozen-model memory diagnostics. Its charts show observed ranges across three
seeds; they are not confidence intervals or optimized Pareto frontiers.

`summarize_policy.py` validates all six policy evaluations, all 24 configuration
graphs, the complete actual-policy continuation audit, and the actual execution
trace ledgers. It refuses to overwrite its existing output. Run it in a separate
copy with a new output location if reproducing the report itself.

The most complete cost receipts are `evidence/execution/*.json`: they include
process startup and final I/O. Per-model training receipts stop before final
checkpoint/optimizer serialization. Repeated forward timings exclude input
construction and serialization. Do not combine overlapping timing scopes, and do
not convert abstract action tariffs to joules or money.
