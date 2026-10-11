# Four-gate learning, reasoning and resource acceptance

**Scope:** additive research implementation. No production model selection, route,
parameter generation, runtime authority, native wire version, or existing owner changes.

**Inspected parent:** `6f7e3e1040fd26ddef6600d6440572c58de1de6e`,
`experiment/neuron-stem-jina-v5-qualification-v2` (PR #1499).
This pin identifies the inspected source, not an assertion that it is the latest branch head.

## 1. What this addition implements

`qualification/neuron-stem/four_gate_core.py` contains bounded JSON/evidence parsing,
pre-label local journals, actual causal-depth accounting, transitive source clustering,
paired cluster bootstrap, physical-work deduplication, and a finite-scenario recursive
risk profile with an independently implemented equivalent generic recursion.

`four_gate_review.py` separately reviews compute, Cell-learning, reasoning, and NDU
artifacts. It does not collapse them into a single utility score or issue adoption authority.
The Cell path calls the **existing** `prequential_threeway_review.review`; it does not
replace that evaluator. Six inputs are required: dataset, trial, sealed journal,
no-change predictions, resource reports and OOD receipts, each bound by its SHA-256.

`four_gate_compute_probe.py` executes actual CPU tensors in isolated Linux child processes.
It compares serial joint encoding, batched joint encoding and shared-state encoding with
question-conditioned Heads. Its tiny random Encoder is a measurement mechanism, not
Laya, mmBERT, Jina, LFM or a pretrained language model.

`four_gate_learning_probe.py` trains actual heads and recurrent/flat networks on generated
vector and directed-graph tasks. It compares chronological local adaptation, retention,
OOD confidence, held-out graph compositions, and five compute policies. Generated
oracle results are not independent production-owner observations.

`four_gate_base_check.py` verifies inspected parent blob identities and optionally the
inherited review signature. Byte/API compatibility is not an end-to-end integration test.

The new Actions workflow is read-only and separately runs standard-library tests and real
CPU tensor tests. Installing numerical libraries is not downloading pretrained weights.
No existing workflow, production owner or security gate is weakened.

## 2. Frozen experiment matrix and comparators

The default plan has 64, 256, 1,024 and 4,096 logical Cells; active fractions 0.05, 0.25,
1.0; requested input-repeat fractions 0, 0.5, 0.9; three task-similarity strata; three
repetitions; and three compute arms. This is **324 paired cohorts / 972 physical
arm executions**. Requested repeat rates are rounded to a realizable distinct-input
count; measured reuse is reported separately. All declared active Cells must actually tick.

The existing `resource_gate.py` intentionally compares distinct Stems and returns a
maximum over stage p99 values. Do not reinterpret it as a same-Stem dispatch comparison.
The new compute gate allows the same weights and calculates quantiles from all actual
request observations. A cohort is a burst: all its requests arrive at cohort start.
Latency includes local queueing, scoped-key lookup, encoding and Head work. Fixture
materialization, admission digest preparation, model load, network, production WAL,
final-use and external effects are outside this clock. Model-load time is disclosed
separately; this is not a complete native end-to-end latency measurement.

Weight sharing, batching, feature reuse and sparse Head activation are distinct. Count
actual Encoder forward calls, items and tokens, not logical cell references. A reduced
call count alone is not a resource victory. GPU busy time and energy are unmeasured,
represented as null, and never inferred to be zero. Isolated process peak RSS includes
runtime allocation and is not a sum of independently attributable tensor memory.

Joint state+question encoding and state-only encoding plus a conditioned Head are different
architectures. Their predictions are NOT assumed equivalent. Real-task quality and resource
measurements must jointly qualify any architecture replacement.

## 3. Gate 2: genuine Cell learning

Reuse the inherited three-way evaluator. Preserve no-change, same-initialization frozen,
and learned predictions; actual initial/final Head identities; chronological pre-label
seals; local update lineage; two real future windows; held-out old-task retention and OOD.
A local fsync or hash is not an independent clock or a model-execution witness.

The controlled probe uses 8/32/128 historical examples per Cell, 12 Cells per trial and
128 later events per Cell. Each trial therefore executes 1,536 test-then-learn updates.
Few-shot trials use separately registered seeds; do not call them a nested same-data
learning curve. The no-change arm is a trained pooled synthetic-task reference, **not**
a Laya teacher. All three arm predictions are sealed before the generated label is
used by the optimizer. The frozen Stem and frozen control Head remain unchanged.

Only 12 local task groups occur in each controlled trial; 1,536 sequential events do
not constitute 1,536 independent learning observations. Confidence-based OOD tests
can fail even when future prediction improves. Do not waive that failure.

## 4. Gate 3: actual sequential reasoning

The evidence reviewer requires single-step, fixed-depth and matched-budget feedforward
controls, five task families and two declared future windows. It joins independent-shaped
outcome records to prediction requests, retains failed attempts, rejects missing/censored
results rather than assigning zero, rejects train/test source leakage, and calculates
actual Cell depth from a causal DAG. Parallel siblings contribute maximum depth, not sum;
waits and transport retries do not add learned depth. No autograd depth is inferred.

The controlled graph experiment uses a shared learned message-passing Cell. Training
paths have length 1–4; held-out paths have length 5–12. The five families cover new
composition, reversed temporal precedence, incomplete evidence, incorrect hints and
edge interventions. Each family contains both outcomes. BFS labels are generated by
separate deterministic code in the same process. This is a useful algorithmic test,
not independent physical observation or open-domain reasoning.

The flat comparator receives the same graph/step supervision and optimizer-step schedule.
Its parameter count and actual runtime differ. Equal optimizer steps and a common depth
ceiling do NOT establish equal total training/inference resource use. The native evidence
review supports frozen phase budgets, but no controlled-graph result establishes a
Hepta-wide equal-total-cost superiority claim.

## 5. Gate 4: NDU and the value of additional computation

Five arms are mandatory: fixed budget, confidence escalation, deterministic NDU,
finite-scenario recursive-risk NDU and an algebraically equivalent generic nested-risk
control. The selected external objective is immutable across arms. Internal estimated
utility, confidence or a small solver residual is not the task outcome.

The implemented risk model is finite-scenario entropic recursive valuation. It includes
explicit action duration, continuation law and one charge per action. At zero risk it
reduces to the declared expectation profile. It is NOT a general stochastic FBSDE solver;
there is no learned diffusion, martingale covariance model or qualified Z-gradient path.
Dynamic risk here is a registered bounded function of computation depth, not a claim
that arbitrary preference dynamics have been learned.

The controlled controller estimates current and continuation correctness using a separate
calibration set. Test labels are evaluated only after the policy chooses its final depth.
The original implementation repeatedly solved the same small tree. The optimized version
compiles immutable stopping tables keyed by the complete supported state and bound to
model, critic/profile, objective, scope, risk settings and maximal depth. Richer state
requires a richer cache key. This is not a general-purpose utility caching theorem.

Calibration and table construction are charged once, never once per Cell, but they are
not free. An inference-only saving can be smaller than this extra preparation cost.
The probe's registered 0.008-per-step price is an abstract objective coefficient, not
measured CPU time or energy. Actual wall/CPU costs are reported separately. No unique
mathematical advantage over the equivalent generic nested-risk formulation is asserted.

## 6. Statistical and evidence boundaries

The plan freezes 64 planned comparisons, 40,000 bootstrap draws and at least 30 root-source
components for a positive paired diagnostic. Overlapping roots are joined transitively.
The estimator is an equal-root-component-weighted paired mean, not an IID bootstrap of
correlated Cell calls. Report finite-bootstrap tail resolution and support failures.
These are research statistical settings, not replacements for the existing HNMF/native
independence, safety, retention, authority and future-window acceptance requirements.

Hashes authenticate neither execution nor truth. A different observer ID is a structural
check, not verification of an independent trusted observer. Native signatures, current
final-use, Artifact CAS, generation fence, durable state migration and recovery remain
with their existing owners. All outputs from this addition deny production promotion.

The compute probe uses Linux `fork` for bounded research child processes. Python 3.13's
multi-threaded-fork warning is retained when emitted; children are timeout-bound and reaped.
Do not embed this harness in a production multi-threaded serving process or infer portable
process-safety qualification. Native deployment requires its own approved process backend.

## 7. Reproduction

Run from a full checkout at the inspected parent plus this additive patch:

```sh
python3 qualification/neuron-stem/four_gate_base_check.py --repository . --check-api
export PYTHONPATH=qualification/neuron-stem
python3 -m unittest discover -s qualification/neuron-stem -p 'test_four_gate_*.py' -v
python3 -m unittest four_gate_tensor_tests -v
python3 qualification/neuron-stem/four_gate_review.py plan --output frozen-four-gate-plan.json
python3 qualification/neuron-stem/four_gate_compute_probe.py --output controlled-compute
python3 qualification/neuron-stem/four_gate_learning_probe.py --output controlled-learning
```

Torch and NumPy must be physically installed; missing dependencies fail the tensor job.
The measured environment used Torch 2.10.0+cpu and NumPy 2.3.5. The new workflow uses an
explicit CPU wheel and logs its full dependency environment. A workflow file is not a
successful GitHub Actions execution receipt.

Use `--smoke` for limited numerical checks. A smoke compute run contains only two of the
324 paired cohorts and must return `matrix_complete=false`. It is not matrix acceptance.
All output paths are create-only. Preserve interrupted artifacts; do not overwrite failed
runs or relabel a resumed append-only census as an uninterrupted production execution.

The aggregate native-shaped review takes a manifest whose gate files contain relative
paths and SHA-256 digests:

```sh
python3 qualification/neuron-stem/four_gate_review.py review \
  --plan frozen-four-gate-plan.json --manifest actual-evidence/manifest.json \
  --output four-gate-review.json
```

Missing gates produce an incomplete report and exit status 2. Generated probe artifacts
must not be relabeled to satisfy genuine-model/future-window requirements. No generic
adapter in this patch manufactures Laya no-change predictions or signs native receipts.

## 8. Current delivery boundary

This package was developed without a locally mounted full parent repository or a native
Rust toolchain. Parent source/API was inspected through GitHub reads. The inherited
reviewer's full execution, same-SHA whole-repository CI, actual pretrained Stem weights,
real Hepta task data, two independently observed future calendar windows, signed owners,
and target-hardware CPU/GPU/recovery acceptance remain unverified.

The available GitHub connector exposed reads only, and direct Git DNS resolution failed.
Therefore the package contains an offline additive patch, not a claimed remote commit or
PR. Apply/review on the pinned parent, retain the existing gates, and require successful
remote receipts before reporting any repository integration or production qualification.
