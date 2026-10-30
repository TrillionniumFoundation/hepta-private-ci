# Post-seal finite diagnostics — new registration, 2026-10-30

This directory is a **new implementation and registration** for
`execution04_durable_20261030`. It is not the lost 2026-10-29 supplement, does not
claim that implementation's original hash, and does not recreate its missing
execution receipts. The original scientific protocol and all primary training,
scoring, inference, and acceptance rules remain unchanged.

Preparation uses source text, source identities, and small invented fixtures only.
It opens no scientific RAW, checkpoints, qualification/final endpoint arrays, or
real bank values. What happened after the last observation of the inaccessible
execution03 remains a separate continuity incident; this registration does not
assert that no earlier endpoint producer ever ran.

## Fixed scope

The supplement produces four descriptive checks, without fitting or choosing a
new tolerance:

1. **A equal-first-dynamics checks.** For all 48 registered parents in each of
   seeds 17, 29, and 43, group the four actions by the original
   `branches[action].first.dynamics`. Within each group compare first component
   identities, terminal dynamics, action values, stored semantic output-hash
   vectors, and source/condition row identities. Also check branch-value,
   baseline-advantage, and retained reward-mean arithmetic. Container NPZ hashes
   bind input bytes; different container hashes are not different model outputs.
2. **A recorded successor differences.** Retain all per-parent/action records and
   summarize their parameter, momentum, gradient, and buffer `l2` and `max_abs`,
   both across all actions and nonbaseline actions. Preserve representation
   differences, including zero numerical momentum difference with a different
   optimizer component hash. These are the original recorded norms; the
   supplement never restores a checkpoint or recomputes a model transition.
3. **A deployed gated calibration decisions.** Execute only the exact, pinned
   `predict` and `choose` function ASTs from the original `heads.py`. Evaluate the
   12 calibration parent slots per model under field12, full-current-state, and
   history6: **36 registered parent slots and 108 head-mode rows**. Report gated
   regret, rowwise ungated regret, optimal-set accuracy, chosen advantage, ties,
   fallbacks, overrides, and outside-fit-norm counts. Keep the original batched
   ungated diagnostics separate. These dependent parents already selected tau;
   they are **zero new independent samples**, and yield no uniform certificate.
4. **W shared-action diagnostics.** For exactly the three registered
   schedule-6000/baseline/clock-48 pairs, report the intersection of the two best
   action sets and, with `r_s(a) = max_b V_s(b) - V_s(a)`, report
   `min_a max(r_original(a), r_reflected(a))` and
   `min_a (r_original(a) + r_reflected(a))/2`. The former restricts both states to
   the same deterministic action; randomized minimax can differ. The latter is
   a 50:50 mixture over the two constructed states. Near H12 is not identical
   input, and these numbers are not a lower bound for all field policies or an
   estimate of reachable-state prevalence.

The C macro16/horizon96 contract is carried as unchanged context. No C calibration
diagnostic or new C hypothesis is added. First divergence remains observable at
the original transaction boundaries, not at an invented precise internal step.
This supplement does not replace the original A inactivity decision, primary
statistical analyses, cost interpretation, or architecture simple-effect review.

## Access gate and public pipeline interface

Only Python's standard library is imported before the complete metadata gate.
The caller supplies separate external SHA256 identities for the plan, pipeline
COMPLETE, VERIFIED, MANIFEST, and finalizer source freeze. No "latest" discovery
or unbound input search is performed.

The public pipeline completion interface is exactly:

```json
{
  "schema": "hepta.fullstudy.pipeline-completion.4",
  "complete": true,
  "execution_episode": "execution04_durable_20261030",
  "artifacts": {
    "verified": {"path": "absolute path", "bytes": 1, "sha256": "actual SHA256"},
    "manifest": {"path": "absolute path", "bytes": 1, "sha256": "actual SHA256"},
    "aggregate_results": {"path": "absolute path", "bytes": 1, "sha256": "actual SHA256"},
    "finalizer_freeze": {"path": "absolute path", "bytes": 1, "sha256": "actual SHA256"}
  }
}
```

The numbers and hashes in this schema example are placeholders, not receipts.
The four descriptors must match the actual externally bound files. The program
never searches arbitrary notes or nested objects for a conveniently matching
descriptor. This COMPLETE covers the primary 14 jobs, aggregate, and literal
verification; it does not certify this supplement or scientific benefit.

The independent gate then verifies:

- The actual finalizer freeze, its bound aggregate freeze, original protocol
  identity, and consistent operational amendment identity.
- The exact 14 controller jobs, their successful result/exit-code bindings, all
  scientific operation receipts, and the exact 26 primary/controller plus four
  aggregate completion seals. Failure markers override a completed interpretation.
- Literal restore coverage of **every logical manifest entry**, not a subset:
  ordered path list, file count, byte count, and completed temporary-copy cleanup.
- Matching hashes for the original A/C phase source freezes and their union of
  unchanged source files, together with the additional fixed reporting and
  diagnostic source pins. Source files are hashed as bytes and never imported.
- The explicit episode RAW/source/operations roots and a new, nonoverlapping
  output directory outside RAW, CAS, source, and input registration directories.

Only after all these checks does the program import NumPy and decode the fixed A
bank and W diagnostic records. It does not decode B/C endpoint arrays or aggregate
effect values. SHA verification alone never creates a new scientific completion
claim. These checks verify the registered local evidence chain; they do not claim
permanent external storage or recover missing old execution evidence.

## Invocation after actual completion

Publish/register `PRE_ENDPOINT_PLAN.json` and the exact implementation before the
execution04 endpoints. Supply real descriptors only after the primary pipeline
has completed. The following is a template, not an instruction to execute during
preparation:

```bash
env PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -B /workspace/scratch/178ced6a501f/fullstudy_git/supplements/parameter_field_fullstudy_20261030/postseal_supplement.py \
  --raw-root /workspace/scratch/178ced6a501f/fullstudy_execution04_durable_raw \
  --source-root /workspace/scratch/178ced6a501f/fullstudy_git \
  --plan /workspace/scratch/178ced6a501f/fullstudy_git/supplements/parameter_field_fullstudy_20261030/PRE_ENDPOINT_PLAN.json \
  --expected-plan-sha256 'ACTUAL_PLAN_SHA256' \
  --pipeline-complete '/absolute/path/to/primary_pipeline/COMPLETE.json' \
  --expected-pipeline-sha256 'ACTUAL_PIPELINE_SHA256' \
  --verified '/absolute/path/to/VERIFIED.json' --expected-verified-sha256 'ACTUAL_VERIFIED_SHA256' \
  --manifest '/absolute/path/to/MANIFEST.json' --expected-manifest-sha256 'ACTUAL_MANIFEST_SHA256' \
  --finalizer-freeze '/absolute/path/to/FINALIZER_SOURCE_FREEZE.json' \
  --expected-finalizer-sha256 'ACTUAL_FINALIZER_SHA256' \
  --output /workspace/scratch/178ced6a501f/fullstudy_execution04_supplement_results \
  --execute-post-seal
```

No output directory is created until the complete metadata gate has passed.
Before-gate rejection emits a structured failure to stderr; capture it in the
external execution log. After-gate failure preserves partial supplemental outputs
and attempts an exclusive `FAILED.json`. Existing outputs are never overwritten.

## Outputs and interpretation

- `GATE.json` and `INPUTS.json`: actual input identities, access boundary, and
  before/after metadata consistency.
- `BANK_SUMMARY.json`, `EQUAL_DYNAMICS_GROUPS.jsonl`, and
  `SUCCESSOR_DIFFERENCES.jsonl`: fixed-population transition/label diagnostics.
- `GATED_CALIBRATION.json` and `GATED_CALIBRATION_ROWS.jsonl`: 108 declared
  diagnostic rows, not 108 independent samples.
- `W_SHARED_ACTION_REGRET.json`: the three constructed-pair comparisons.
- `INTEGRITY_ISSUES.json`: every detected consistency problem; none is silently
  removed or used to choose a favorable subset.
- `COMPLETE.json`: output hashes, separate wall/CPU/peak-memory cost, runtime
  identity, and zero new gradient/scoring/fitting/sample counts.

Exit **0** means the descriptive supplement completed without detected issues.
Exit **3** means it completed with listed integrity issues and cannot support
unqualified interpretation. Exit **2** means blocked/failed analysis. No exit code
establishes scientific benefit, resolves historical failures, or authorizes
deployment. Supplemental cost is separate; do not add it twice to an inclusive
wrapper measurement. It excludes writing its own final receipt, and historical
unknown costs remain unknown.

## Small synthetic checks

`test_semantics.py` uses tiny invented metadata and numerical vectors. It tests
the full public gate with scientific imports forbidden, rejection of missing
jobs/literal paths and wrong external bindings, explicit pre-gate read denial,
semantic output equivalence, common-optimum/minimax cases, and the exact original
gated choice AST. The synthetic metadata fixture mocks only original-source
inventory verification; actual original source identities are independently
checked from source files during preparation and again by the production gate.
No test calls a scientific runner or loads real data.
