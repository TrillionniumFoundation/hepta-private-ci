# Cross-Fact Granite97 Reader: executable next campaign (2026-10-15)

**Status: DRAFT / RESEARCH_ONLY / DENY_ALL / no model winner.**

This child of the actual V5 Reader stack reuses the original immutable Granite97 token feature bank and V5 source, weight, cache, and training-case identities. No backbone or selected production inference model is updated.

## What runs

- `cross_fact_granite_campaign.py`: new full-budget real-token campaign. Requires the already staged original V4/V5 source data, pinned model snapshot, cached train features, prior V4 design/native freeze and V5 design, all outside the checkout. The source can load the frozen Encoder through the existing exact-identity TokenBank; it is **not** a replacement Encoder implementation.
- Two equally parameterized H=32 Reader arms: masked **cross-fact** attention residual versus equally sized **fact-local** MLP; each adds exactly **4,096 trainable parameters** on top of the original Reader, with identical initial weight bytes and six-input inference API.
- Three seeds **41, 47, 53**, 8,000 max Adam updates per arm, 16 training cases per step, complete four-row paired worlds, three recurrent hops, learning rate .001, pair weight .5 and diagnostic interval 250. Both arms inherit the original train-only stop gate: all 128 candidates correct, both evidence worlds correct and logit CE <= .10.
- `cross_fact_granite_review.py`: separate stdlib-only reviewer. Recomputes TRAIN symbolic truth and saved probability success, rehashes training/model files and source, checks matched initialization, parameter count, optimizer exposures, schedule identity, and rejects incomplete cohorts or unexpected fresh evaluation after a failed train gate. It cannot independently attest clock accuracy or physical Encoder execution.
- The campaign **cannot encode fresh test-role cases until all six fitted arms pass the frozen full-fit gate AND per-seed actual training updates, exposures, optimizer-state bytes, model parameter counts and original schedule SHA match between arms**. Unequal arithmetic/FLOPs remain explicitly unproven. The original V5 protocol factory constructs candidate definitions earlier; only TRAIN cases are used in optimization.
- If any fit fails, retain six training receipts with `train_gate_failed_no_fresh_scoring`. If all fits pass but work investment differs, reject with `unequal_actual_budgets_no_fresh_scoring`. Only when both hold, freeze every artifact and **seal twelve complete inference prediction panels without computing labels or writing scores**. In a separate Python process, `cross_fact_granite_score.py` checks all twelve seals and frozen Head digests before importing fresh-domain scoring labels, then writes 12 write-once scores plus one completion manifest. Source/label OS isolation and independent host attestation are NOT claimed.

## Run against actual pinned V5 inputs

Use the identical environment, licensed inputs and immutable archive paths described in `BINDING_V5_PROTOCOL.md` and `READER_MULTIRC_V3_RUNBOOK_20261015.md`. Paths below are placeholders for **already staged, verified inputs**; the command does not download or invent them. Keep output outside the Git checkout.

```bash
cd /path/to/hepta-private-ci
export PYTHONPATH=qualification/stem-cell-v1
python qualification/stem-cell-v1/cross_fact_granite_campaign.py \
  --source /verified/MultiRC/source \
  --snapshot /verified/Granite97/snapshot \
  --prepared /verified/V4/prepared \
  --previous-main /verified/V4/main \
  --previous-native /verified/V4/native \
  --output-v5 /verified/V5/design-and-previous-observations \
  --output /independent-storage/cross-fact-granite-v1 \
  --seed all --steps 8000

# First inspect training gates and twelve sealed prediction panels:
python -S qualification/stem-cell-v1/cross_fact_granite_review.py \
  /independent-storage/cross-fact-granite-v1

# ONLY when all six fits, actual budget comparisons and twelve seals pass:
python qualification/stem-cell-v1/cross_fact_granite_score.py \
  /independent-storage/cross-fact-granite-v1

# Independently replay original scoring and proof-file identities:
python -S qualification/stem-cell-v1/cross_fact_granite_review.py \
  /independent-storage/cross-fact-granite-v1
```

**Note:** `python -S` is appropriate for the pure-stdlib reviewer only if the original project libraries and their imports are locally available. It must not be used for the PyTorch campaign. Output directories cannot preexist, avoiding accidental overwrite of evidence.

## Executed checks in this authoring environment

The newly extended source plus the five focused suites were exercised against the exact inherited original TokenReader: **42/42 focused local tests in ordinary Python and 42/42 under `python -O`**, including sealed-to-score end-to-end fixtures, no-label-before-gate, full prelabel source roster checks, synthetic autograd and budget parity/adversarial file tests. The pinned original Encoder was NOT run by these suites. Remote exact-head CI has not completed, and a source hash alone is not independent execution proof. The Granite campaign itself **has not loaded real weights or run six pretrained fits** here: only a synthetic earlier paired-world prototype completed. Neither natural-task ability, equal-FLOP advantage, fresh generalization, NDU efficiency, a 4096 Cell physical runtime nor production readiness is asserted.

## Selection gates

Do not interpret a gate PASS, trained Head or fast batch as authority to load or serve a model. Keep the original negative V5 results and previous static/Split/NDU results. Require source-disjoint external tasks, exact-head native qualification, independent original-label scoring, old-task retention, full Encoder+training+online cost and target-host p99 before considering a model change. Sampled rows per logical group are not independent fresh worlds, and equal parameter count does not imply equal arithmetic.

## Reviewer semantics
- The stdlib-only reviewer accepts **three** sealed states: no fresh files after failed fitting, all prelabel predictions sealed and **not yet scored**, or all twelve scored files with a matching write-once scoring-completion manifest.
- Any partial scoring, modified seal, duplicate JSON key, symlinked evidence, wrong model digest, missing batch identity or tampered training budget fails closed.
- The original `full_fit_gate` and `matching_training_budgets` are separate facts; only their conjunction opens the fresh seal phase. This is matched *observed update/exposure/optimizer storage*, **not** equal GPU/CPU floating-point operations.

## Strict prelabel roster identity

The training entrypoint now freezes a SHA256 of each of the two original V5 fresh-domain case-ID rosters in `plan.json`, with **no labels** included. In the separate score process, `check_prelabel_seals` first checks complete fitted-model and resource budgets, all 12 sealed prediction files, 128 unique IDs per role, exact original roster digests, ordered physical batch receipts and frozen Head material. Only *after* that full check does it import the fresh-domain scoring protocol. The independent stdlib reviewer reconstructs the rosters again and rejects any changed source membership.

This is deterministic process-stage separation, **not** independently signed label custody, a trusted execution environment, or an empirical claim of source-disjoint natural-task superiority. Any prior failed fit or mismatched optimizer storage must keep outcome scoring unopened.

## Strict full-receipt replay before fresh-label scoring

The separate scorer now invokes the independent `review(root)` **after**
validating all twelve prelabel seals but **before** using their new-domain
labels. Coordinator-written training PASS flags, model digests, and cumulative
update counts cannot grant access to scoring by themselves.

New `cross_fact_granite_receipt_oracle.py` rebuilds the original four-case
paired worlds and all 8,000 planned deterministic RNG sampler updates using
only stdlib. It compares the training schedule SHA against the source, checks
every actually completed optimizer step's exact original case IDs, order,
sampling digest, exposure, depth, training-only pair weight, finite-gradient
status, and nonzero CPU/wall cost. It reconstructs per-case exposure counts
and refuses a lifecycle timing report smaller than the sum of its nested
observed updates. The reviewer additionally cross-checks optimizer tensor
bytes and reported CPU/wall time with the actual trainer receipt, and binds
old-task internal tune diagnostics to each frozen model digest.

Regression tests include a **full non-mocked reviewer → scorer → reviewer
replay**, using six deliberately fake (invalid model) byte artifacts and twelve
synthetic prediction panels. These validate the integrity boundary only:
modifying a single purported weight file, training receipt, old-task receipt,
sample order, optimizer record, or cumulative work denies scoring. Other tests
exercise real Torch tensor gradients but do not claim a real Granite97 forward.

Exact tests executed in this working CPU container:
```sh
PYTHONPATH=qualification/stem-cell-v1 python -m unittest discover \
  -s qualification/stem-cell-v1 -p 'test_cross_fact*.py' -q
PYTHONPATH=qualification/stem-cell-v1 python -O -m unittest discover \
  -s qualification/stem-cell-v1 -p 'test_cross_fact*.py' -q
```

Observed results: **48/48 passed per mode in the current branch**, no skips. This is only a
focused local suite; the hosted exact-source `hepta-neuron-next-round-matrix`
CI and the complete Cargo/Bazel workspace qualification are separate.
This reviewer still cannot prove physical execution of original pretrained
weights, accurate hardware clocks, independent signer identity, or the truth
of external observations. No synthetic fixture score may be promoted.

## Synchronized Head training and physical input reuse

The original V5 `binding_training.py` remains byte-identical so its historical
source/CAS design identity and negative observations are not reinterpreted.
This child adds `cross_fact_joint_fit.py`, a separate actual trainable
two-Head executor bound to the same V5 TokenBank and original four-row TRAIN
groups. Cross-Fact and Local start with exactly equal initial parameter bytes
and parameter count. Every physical optimizer update consumes the **same
preconstructed detached TokenBatch** in both models (one `data.take` per
paired update rather than one per Head); both Heads pay their own backward and
optimizer compute. The research receipts distinguish the two Head costs from
the **one** complete joint owner CPU/wall lifecycle, so shared work is not
counted twice.

At each registered training-only 250-update diagnostic, the two Heads are
measured separately with original candidate labels. The whole *pair* stops
early only when **both** have all-original-128 candidate accuracy 1.0,
paired-world success 1.0 and train logit CE <= .10 at that same checkpoint.
If only one passes, **both continue on the next identical TRAIN minibatch**
until the budget (up to 8,000 steps) expires. No synthetic, official validation,
fresh vocabulary, natural internal tune or external test data participates in
the synchronized stopping rule. Stop-on-TRAIN is a biased estimator of
generalization and never itself warrants a model winner.

`joint-training.json` retains exact paired stop reason, all initial/effective
model identities, one shared batch materialization per completed step,
the shared deterministic sample schedule, partial/failed second-arm effects,
and one complete process CPU/wall receipt. The independent stdlib reviewer
requires that file and each arm's original-compatible physical optimizer
receipt to bind the same completed step, initial state, exact minibatches,
parameter and optimizer storage, frozen artifact, and nonadditive cost.
A second-arm failure cannot return a selected model.

**Actual executed local CPU checks:** normal Python **48/48 tests passed**;
`python -O` **48/48 passed**, without skips. Includes five new real
autograd/paired-optimizer/synchronous-termination tests, including measurement
of actual `data.take` invocation count: 4 synchronized optimization steps
cause exactly 4 TRAIN materializations, not 8. These tests use controlled
synthetic token tensors with the real inherited TokenReader code. No new
Granite97 Encoder weights were downloaded or executed in this local container.

The number of physical Encoder forward calls, fused GPU kernel throughput,
actual V5 pretrained six-arm learning and total lifetime p99 remain unknown
until their exact pinned native observations finish. Keep DRAFT/DENY_ALL.
