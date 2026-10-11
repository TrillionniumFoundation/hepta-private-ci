# Four-gate learning and reasoning acceptance

This extension lives in the existing Neuron Stem qualification directory. It
preserves the existing prequential runner, its original prediction journal, the
three-way reviewer, resource probes, model registry and all production owners.
Integration base: `6f7e3e1040fd26ddef6600d6440572c58de1de6e` (PR #1499 lineage).
The implementation is a research evaluator and a CPU capture adapter, **not a
trained System 2, a stochastic NDU solver, or a production promotion service**.

## One result per question

| Gate | Required comparison | Result must not be explained by |
| --- | --- | --- |
| Shared compute | Original no-change; shared-weight joint batching; shared-feature Heads | Merely loading fewer weight copies or dropping failures |
| Cell learning | Original no-change; same-initialization frozen Head; prequential trained Head | A better Stem, future-label leakage, or changing the frozen control |
| Group reasoning | Single step; preregistered fixed depth; equal-compute alternative | Extra inference/training/search compute, parallel width, familiar structures |
| NDU | Fixed budget; confidence escalation; deterministic NDU; stochastic candidate | Self-reported utility, a changed objective, or uncharged training/search |

Results are `blocked_missing_evidence`, `blocked_missing_runtime`,
`invalid_evidence`, `not_passed`, or `diagnostic_pass`. All four diagnostics must
pass for `all_offline_diagnostics_passed=true`. Even then, independent signatures,
real-world efficacy, NDU selection and production promotion remain **false**.
These fields describe what this reviewer actually verifies, not a ban on later
independent owner qualification. No fixture signature or CLI switch enables it.

## Gate 1: count actual work

`four_gate_compute.py` requires all 36 combinations of 64/256/1024/4096 Cells,
5%/25%/100% active Cells and 0%/50%/90% repeated scoped inputs, each with three
arms (108 arm workloads). Each exact request schedule is hash-bound in the plan.
Rounding of the requested repeat ratio is explicit: unique states are
`max(1, round(requests * (1 - repeat_bps / 10000)))`. Every active Cell must tick.

Count Encoder forward calls, rows within batches, actual tokens, unique admitted
inputs, reused request dependencies, resident Stem copies, all-outcome p99 and
successful throughput separately. A request references a real forward event and
batch slot; only the feature-reuse arm may reuse that slot. Keys bind principal,
scope, purpose, generation, authority epoch, pipeline and the **complete**
admitted input. Joint and state-only representations are not assumed equivalent.
The original model weights are pinned per arm. The same candidate Encoder weights
must be used in joint-batch and feature-reuse arms.

`four_gate_capture.capture_cpu` hooks an **already loaded frozen Torch Encoder**
with actual pre/post forward hooks. It performs bounded batching/reuse and runs
isolated Cell Heads. Supply approved `prepare_batch(rows, arm)` and `pool(output)`
adapters and run each arm in a fresh process. It never downloads a checkpoint or
executes external model code. Its RSS samples are **not** a continuous peak RSS
measurement. Add an independently measured peak and separately measured lifecycle
phases before submitting Gate 1 evidence. Exceptions abort rather than emitting a
complete successful capture. GPU/NPU/native Worker telemetry requires its real
backend; zero CPU-path GPU work is not a GPU benchmark. Energy remains null when
unmeasured. The toy CPU checks do not implement an original Laya no-change arm.

## Gate 2: replay original evidence, not a PASS flag

The bridge imports the existing `prequential_threeway_review` verifier and reads
five original SHA-pinned inputs: dataset, trial, pre-label journal, no-change
predictions and three-arm calibration/OOD receipts. It rechecks Head lineage,
first-prediction equivalence, frozen identities, updates and historical retention.
No alternate Cell journal or weight format is introduced.

Recompute accuracy and Brier comparisons against both controls in each future
window. OOD false-acceptance thresholds come only from historical calibration.
Require source-group confidence bounds for both OOD comparisons as well as the
future predictive gains. Missing OOD data cannot be replaced by future ECE.
Observed profiles require at least 200 source clusters per comparison; that floor
is not a power analysis or proof that the declared clusters are independent.

## Gate 3: measure actual sequential depth and novel tasks

Paired evidence must cover both future windows and all five strata:
`new_relations`, `temporal_order`, `missing_evidence`,
`wrong_initial_hypothesis`, `counterfactual`. Bind training source, input and
structure inventories. Reject training overlap and duplicate inputs masquerading
as independent sources/windows. No stratum can disappear inside a pooled score.

The trace is an observed causal DAG: each node has an ID, kind, parents, actual
start/end, available input references and output digest. Count Cell depth and
learned group depth separately. A parallel fork uses maximum parent depth; waits,
guards and transport retries do not add learned depth. A retry must retain the
original output. Reject cycles, undeclared input edges and terminal-outcome input.
This validates provenance structure; it cannot prove semantic novelty from hashes
or determine gradient reach from a serialized execution trace.

The selected fixed depth is 2/4/8/16. Compare against single-step and a preregistered
equal-compute alternative using the same Stem, tokenizer, training data, host and
environment. Match both per-episode and **whole lifecycle** measured cost axes
within at most 5%, while also enforcing absolute budgets and parameter/RSS limits.
No generality claim follows from longer execution alone.

## Gate 4: external objective and full lifecycle cost

The implemented review profile is explicitly
`registered_linear_external_score_minus_lifecycle_cost`. Its digest binds the
fixed external objective and measured additive cost coefficients. It does not
pretend that a discounted baseline solves an arbitrary recursive utility/FBSDE.
A nonlinear profile needs its own conforming evaluator before acceptance.

For each window, compare deterministic NDU against fixed-budget and confidence
controls; compare stochastic NDU against both controls and deterministic NDU.
A candidate needs either better quality without higher declared cost, or lower
cost with quality noninferiority, **and** positive cost-adjusted external benefit.
Each task stratum must retain quality. Negative stochastic incremental value is
reported rather than hidden by a deterministic gain; inspect individual results
when the simpler model is the defensible choice.

All seven phases are explicit: load, warmup, inference, training, search,
evaluation, migration. Physical job IDs cannot be charged twice. Reconcile
additive per-episode inference charges with the physical inference phase.
Amortize non-inference cost over the actual evaluated episode count, not imaginary
future volume. Wall latency is budgeted but is not summed as parallel CPU work.
Unmeasured required GPU/energy is missing evidence, not zero. Inherited pretraining
is held fixed by the shared Stem comparison; new pretraining must be accounted
for under a separate experiment rather than silently changing the Stem.

Scores come from external outcome records under the frozen objective. A producer
cannot name itself as its observer. This identity check is not authentication.
Unresolved censoring blocks review without a registered censoring estimator;
failed/cancelled/indeterminate episodes remain in coverage and cannot claim success.
General off-policy causality, correlated multi-agent assignment and stochastic
solver conformance are not established by these paired shadow/replay comparisons.

## Original-byte input protocol and invocation

Prepare the design plan **before** selecting policies and observing held-out data.
Keep its independent preregistration receipt. Prepare a separate post-observation
bundle; never rewrite the plan to insert new outcome-file hashes. A bundle is:

```json
{
  "schema": "hepta.four-gate.evidence-bundle.v1",
  "plan_sha256": "CANONICAL_JSON_PLAN_SHA256",
  "evidence": {
    "compute": {"path": "compute.json", "sha256": "ORIGINAL_FILE_SHA256"},
    "learning": {
      "dataset": {"path": "dataset.jsonl", "sha256": "ORIGINAL_FILE_SHA256"},
      "trial": {"path": "trial.json", "sha256": "ORIGINAL_FILE_SHA256"},
      "prelabel_journal": {"path": "prelabel.jsonl", "sha256": "ORIGINAL_FILE_SHA256"},
      "no_change": {"path": "no-change.jsonl", "sha256": "ORIGINAL_FILE_SHA256"},
      "ood_receipts": {"path": "ood.jsonl", "sha256": "ORIGINAL_FILE_SHA256"}
    },
    "reasoning": {"path": "reasoning.json", "sha256": "ORIGINAL_FILE_SHA256"},
    "ndu": {"path": "ndu.json", "sha256": "ORIGINAL_FILE_SHA256"}
  }
}
```

Use null for an unavailable gate. The symbolic hashes above are intentionally
invalid examples, not evidence. `test_four_gate_fixtures.py` supplies complete
**synthetic-only** schema examples, never a substitute for target-host budgets,
real model pins, authorized data, or future observations. Plan validation lives
in `four_gate_review.validate_plan`; each reviewer checks its raw trace shape.
Independent host/evaluator/observer attestations still need the existing owners.

```sh
python3 qualification/neuron-stem/four_gate_review.py \
  --root /approved/evidence \
  --plan frozen-plan.json --plan-sha256 "$PLAN_FILE_SHA256" \
  --bundle observed-bundle.json --bundle-sha256 "$BUNDLE_FILE_SHA256" \
  --output /approved/results/four-gate-review.json
```

The plan's canonical digest and its original file byte digest are distinct and
both are retained. JSON rejects duplicate fields, nonfinite/overflowed numbers,
blank JSONL rows, symlinks, escaping paths, oversize input and mismatched bytes.
Use a trusted private evidence root: this is not a hostile-directory sandbox.
Outputs are exclusive-create and file-synced; POSIX also syncs the parent. No
Windows parent-directory durability or multi-file transaction is claimed.
Exit 0 means four offline diagnostics passed; exit 2 means not passed/incomplete.

## Reproduction and missing scientific evidence

```sh
PYTHONPATH=qualification/neuron-stem python3 -m unittest discover \
  -s qualification/neuron-stem -p 'test_*.py' -v
PYTHONPATH=qualification/neuron-stem python3 -m unittest capture_cpu_checks -v
```

The second command requires Torch and psutil and has no skipped fallback. Its
small numerical Encoder/Heads and toy learning labels are expressly synthetic.
The dedicated workflow tests exact source head and merge source separately and
runs the real CPU checks. Its source archive binds reproduction to the checkout.
No test or CI job here executes real mmBERT/Jina/Laya/LFM weights, creates genuine
future observations, supplies independent NDU signatures, or qualifies native
4096-Cell peak RSS/p99, GPU/NPU, unclean recovery, Artifact CAS/final-use or release.
The four empirical questions remain open until their real evidence is supplied.
