# Hepta Neuron external-model A/B trials (diagnostic only)

The executable comparison is intentionally **not** a Cell production activation, model
selector, an independent evaluator, or an NDU receipt. It never replaces a serving
model. Synthetic CI cases prove only protocol and negative-path behavior.

## Current production no-change and real Ledger data are independent prerequisites

`laya` is an upstream experimental arm, **not evidence of the currently deployed Hepta Cell**. Production no-change must be supplied by the real selected artifact/policy/route owner, including its current generation and checkpoint. An approved data owner must first use `LedgerWriter::freeze_dataset` and `read_dataset_records` to join active authenticated decisions and terminal outcomes with permitted model input; digests alone do not contain prompts, options or correct labels. Our signed structural preflight does not issue Hepta serving/selection authority. See [REAL_LEDGER_COHORT_PRECHECK.md](REAL_LEDGER_COHORT_PRECHECK.md). No actual private Hepta dataset is shipped here.

## Three frozen arms

- `decisions`: `laya` (frozen external A/B control, **not product no-change**) vs `typed`, actual ~421M family; require actual
  parameter counts within 1% and one common 512-token / 192-option-token cap.
- `multilingual`: `laya` (frozen external A/B control, **not product no-change**) vs `multilingual` (~322M); measure English,
  Chinese and cross-language cases in **each** holdout/future window. This is a
  *same-maximum-budget*, not an equal-parameter-count comparison.
- `heads`: `linear` (no-change) vs `mlp` vs `swiglu`, same frozen feature vectors,
  target vector, training seed, optimizer, epochs and batch size; all trainable
  tensor counts must be within 1% and **no greater** than the linear cap.

Full-model experiments are **inference-only**. They inherit incompatible upstream
pretraining/finetuning budgets. Never claim matched training compute or superior
Hepta performance from a vendor model card. Full-model typed probabilities are
rounded by Laya's SDK. The independent evaluator reports BOTH shipped/raw
probabilities and a post-hoc temperature-scaled view (fixed grid, categorical
NLL on **in-domain calibration only**, separate temperature per model). Neither
ECE10 nor fitted temperature is a permission, policy propensity or calibrated
production grant. No holdout/future labels may tune the calibrator. `is_ood` is
external ground truth; the 0.8 confidence rejection is a **proxy**, not an
independent OOD head. The head trial is Q24 regression, not a decision-policy test. A frozen head
produces **two distinct state-width Q24 vectors**, `drive_q24` and
`prediction_q24`, not a fused `prediction_q24` of twice that width. Report
Drive MSE and Prediction MSE separately, plus combined MSE/MAE. Head evaluation
must run after a physical safetensors save -> strict reload -> matched tensor
forward check; the saved weight SHA must still match after inference.

Full-model runner receipts must cover every *calibration*, holdout and future
case ID, without labels. The evaluator fits its temperature on sealed in-domain
`calibration` labels using the immutable grid `(0.5, 0.65, 0.8, 1.0, 1.25,
1.5, 2.0, 3.0)`, then reports raw and calibrated Brier/ECE by window. A single
calibration case is acceptable ONLY for diagnostic unit fixtures, never
qualified efficacy. Do not mislabel the serial per-request forward rate as
true backend-batch throughput; that field remains `null` until a real batch
execution path is independently measured.

## Pinned upstream family: metadata first, local bytes second

`upstream-weights.lock.json` freezes the single source repository
`convaiinnovations/laya` at revision
`7b928d828b7b0e022f929d9bd2e44165aa270148` and the three upstream
**publisher-advertised** safetensors SHA-256 pointers. It does **not** mean
any weight file was downloaded or any code executed. The historical variant IDs
remain logical experiment arm IDs; `typed` and `multilingual` are stored under
`typed-decisions/` and `multilingual/` inside that same upstream revision.

Validate the metadata-only lock offline (no model weights, no network):

```sh
python scripts/hepta_neuron_artifact_preflight.py catalog \
  --catalog qualification/neuron-model-trials/upstream-weights.lock.json \
  --output /absolute/new/catalog-diagnostic.json
```

A separately authorized operator must acquire each *complete* immutable source
subtree onto the named host, without symlinks or implicit downloads during a
trial. For illustration only, an authenticated HF CLI session could explicitly
fetch the fixed revision's `model.safetensors`, `rl_agent_config.json`,
`encoder/config.json`, and `tokenizer/{tokenizer.json,tokenizer_config.json}`
and stage each variant in its own offline bundle directory. Do not use `main`
for actual downloads and do not commit model weights or private data into Git.

Physically verify bytes **after** staging (requires `safetensors`):

```sh
python scripts/hepta_neuron_artifact_preflight.py local \
  --catalog qualification/neuron-model-trials/upstream-weights.lock.json \
  --arm typed --artifact-dir /absolute/staged/typed \
  --output /absolute/new/typed-local-preflight.json
```

This computes a real full-file SHA-256, reads tensor shapes without model
execution, checks model config, tokenizer/encoder metadata, symlink absence, and
full local artifact-tree SHA. `local_weight_bytes_verified=true` only proves
that those physical local bytes match the public metadata lock; neither that
lock nor its receipt is independently authenticated production evidence.

### Operator-controlled weight acquisition and evaluator-owned dataset freeze

The artifact materializer is **offline-cache-only by default**. It copies the
five preregistered files into a **new** model directory on the actual target
host, checks the complete weight-file SHA-256 during copying, runs the tensor
inventory and encoder/tokenizer preflight, fsyncs each file and emits a
create-only diagnostic receipt. A failed acquisition leaves its partial
output directory in place for operator quarantine; never treat that directory
as a runnable model.

```sh
# Use this by default after approved weights have already entered the HF cache.
python scripts/hepta_neuron_materialize_weights.py \
  --catalog qualification/neuron-model-trials/upstream-weights.lock.json \
  --arm typed --destination /absolute/new/model-typed \
  --output /absolute/new/typed-acquisition.json

# Only on an explicitly authorized network-enabled target host:
# add --allow-network and optionally --cache-dir /absolute/trusted/hf-cache
```

**No network download was executed in CI**. The local model path is never
included in Git, and checksum validation against upstream metadata does not
establish independent publisher/host attestation. Use a distinct fresh
output directory for each arm and compare the observed `artifact_tree_sha256`
to the independently frozen experiment manifest before running.

The evaluator can seal already-collected local Hepta data (with approved data
rights and chronological source grouping) without exporting labels to the
inference worker. The original sealed file is **never copied** to the model
runner directory:

```sh
python scripts/hepta_neuron_freeze_dataset.py \
  --manifest-template /evaluator/controlled/manifest-input.json \
  --sealed-dataset /evaluator/controlled/sealed.jsonl \
  --output-dir /evaluator/controlled/new-frozen-bundle
# Share ONLY new-frozen-bundle/manifest.json and blinded.jsonl with the runner.
# Retain sealed.jsonl under the independent evaluator, then use compare with
# actual inference receipts and the original sealed file.
```

`freeze-diagnostic.json` records row counts and byte commitments, not
real-data provenance or elapsed future-window certification. All producer,
source, consent, license, principal, evaluator-independence, and NDU-causality
gates remain external and fail closed.

**Full-model manifests must bind** `upstream_lock_sha256` and use the locked
common source revision and expected weight hash for each model. Pass
`--upstream-lock qualification/neuron-model-trials/upstream-weights.lock.json`
on `blind`, `run` and `compare`. The full-model CLI fails closed otherwise.
The `artifact_tree_sha256` field is still filled **after** actual staging and
must match the physically measured subtree; no synthetic placeholder qualifies.

## Local inputs (no bundled labels or weights)

Create separate manifests and JSONL data for each family, with immutable sealed and blinded input
SHA-256, exact Git `source_sha`, nonzero `host_profile_digest`, parameter cap,
chronological disjoint `train`, `calibration`, `holdout`, `future_1`, `future_2`
windows and `source_group` identifiers. The `observed_at_ms` intervals must not
overlap. Keep heldout/future source groups out of training.

For choice tasks provide `id`, `split`, `source_group`, `observed_at_ms`,
`state`, `question` (`type=choice`, `instructions`, ordered `criteria` map),
`gold`, `is_ood`, `language`, `domain`, and **`option_order`** (an explicit,
complete, unique list of option IDs; never infer indices from JSON map order).
`multilingual` requires `en`, `zh`,
`cross` in each evaluation window. For heads provide `features_q24` and
`target_q24` arrays (lengths d and 2w, each signed [-8,8] Q24). No real data
is shipped in this repository.

Three deliberately invalid templates requiring actual signed pins are included
in `qualification/neuron-model-trials/examples`. They must never be used as
CI model evidence until each placeholder is replaced and independently checked.

Manifest example fields:

```json
{"schema":"hepta.neuron.model-trial.v1","family":"decisions",
 "source_sha":"<exact 40-hex commit>","dataset_sha256":"<sealed 64-hex>",
 "blind_dataset_sha256":"<blinded 64-hex>",
 "host_profile_digest":"<64-hex>","parameter_cap":425000000,"max_len":512,
 "sdk_tree_sha256":"<verified 64-hex SDK tree>",
 "models":{"laya":{"model_id":"convaiinnovations/laya",
   "revision":"<exact 40-hex HF commit>","weights_sha256":"<64-hex>",
   "artifact_tree_sha256":"<64-hex>"},"typed":{"model_id":"convaiinnovations/laya-typed-decisions",
   "revision":"<exact 40-hex HF commit>","weights_sha256":"<64-hex>",
   "artifact_tree_sha256":"<64-hex>"}}}
```

Head manifest uses `family=heads` and `head={input_dimension:512,
state_width:256,seed:17,epochs:10,batch_size:16,learning_rate:0.0003}`;
`parameter_cap=262656` for this shape. Use actual dataset SHA-256; the angle
bracket values above are **not** valid evidence. Compute the tree SHA using
`sha_tree()` from the trial script over a complete, local, symlink-free snapshot.

## Sealed labels and blinded model-runner inputs

Keep two separate datasets under separate access controls: the independent
Evaluator holds the sealed JSONL with `gold`, `is_ood`, and future `target_q24`;
the model runner receives a blinded JSONL with those labels removed (Head train
rows alone retain targets). Both SHA-256 values MUST be frozen in the manifest. The JSON parser rejects duplicate keys and nonfinite literals, including nested objects.
The evaluator recomputes the deterministic blinded export from the sealed source
and checks its digest before comparing model predictions. The model runner cannot
accept the sealed dataset as its inference input.

Generate the expected blind hash in the evaluator environment before freeze:

```python
import hashlib, json, sys
from pathlib import Path
sys.path.insert(0, "scripts")
from hepta_neuron_model_trials import blind_rows, canonical_jsonl, sha_file
sealed = Path("/secure-evaluator/decisions.jsonl")
rows = [json.loads(s) for s in sealed.read_text().splitlines() if s.strip()]
print("dataset_sha256:", sha_file(sealed))
print("blind_dataset_sha256:", hashlib.sha256(canonical_jsonl(blind_rows(rows, "decisions"))).hexdigest())
```

Once pinned, the evaluator creates a **new** blinded output; never overwrite an
existing dataset:

```sh
python scripts/hepta_neuron_model_trials.py blind --manifest decisions.json \
  --dataset /secure-evaluator/decisions.jsonl --output /model-runner/decisions-blind.jsonl
```

## Running an experiment

Requires an isolated Python runtime and, for actual inference, PyTorch,
`safetensors`, and the pinned Laya SDK. Never permit implicit HF downloads.

```sh
python scripts/hepta_neuron_model_trials.py run --manifest decisions.json --dataset /model-runner/decisions-blind.jsonl \
  --arm laya --artifact-dir /absolute/local/laya --weights-file model.safetensors \
  --sdk-sha256 EXACT_INSTALLED_LAYA_TREE_SHA256 --upstream-lock qualification/neuron-model-trials/upstream-weights.lock.json --device cpu --output /absolute/laya.json
python scripts/hepta_neuron_model_trials.py run --manifest heads.json --dataset /model-runner/heads-blind.jsonl \
  --arm swiglu --device cpu --checkpoint-out /absolute/swiglu.safetensors \
  --output /absolute/swiglu.json
python scripts/hepta_neuron_model_trials.py compare --manifest decisions.json \
  --dataset /secure-evaluator/decisions.jsonl --receipt laya=/absolute/laya.json \
  --receipt typed=/absolute/typed.json \
  --baseline-sha256 EXACT_EARLIER_FROZEN_LAYA_RECEIPT_SHA256 --upstream-lock qualification/neuron-model-trials/upstream-weights.lock.json --output /absolute/compare.json
```

Repeat per remaining arm/family. The evaluator interprets each probability by `option_order`, not JSON object
iteration order. The `input_tokens` count is checked against the same 512-token
maximum for each full-model experiment. Peak CPU RSS is recorded through Linux
`VmHWM`; CUDA runs additionally report PyTorch peak allocated/reserved bytes
rather than treating these as complete device-memory telemetry.

Baseline hash must originate from the retained
no-change measurement before inspecting candidate results. The script checks
this hash, but cannot authenticate its timestamp or independent issuer.
Model and SDK tree digests authenticate local bytes but **do not prove** a
self-reported upstream model revision; external artifact-owner verification
is required. Chronological bins also do not prove truly prospective future
windows without independent observation timestamps. Archive signed artifact manifests separately.

## Externally signed claims: verification only

`hepta_neuron_trial_evidence_gate.py` checks four independently pinned Ed25519
role keys and distinct principals: `shadow`, `evaluator`, `ndu`, and `recovery`.
The operator, **not the trainer**, provisions the trust JSON and records its
SHA-256 out of band. Every signed envelope uses the schema
`hepta.neuron.trial-external-evidence.v1`, the role, role-bound key ID, an
exactly bound evidence body and `signature_ed25519_hex` over canonical JSON.

- Shadow: per-arm receipt hashes, zero effects, shadow-only and signed trace.
- Evaluator: sealed labels and separate scoring over holdout and both future windows.
- NDU: no-change baseline, real utility/resources/retention/negative-transfer,
  with signed net gains over both windows for every candidate.
- Recovery: journal CAS, generation fence, old route rejection, governed rollback,
  and tombstone no-resurrection; source/host/manifest/receipt bindings remain fixed.

```sh
python scripts/hepta_neuron_trial_evidence_gate.py \
  --manifest decisions.json --comparison /absolute/compare.json \
  --trust /operator-only/trust.json --trust-sha256 OPERATOR_PINNED_SHA256 \
  --shadow /signed/shadow.json --evaluator /signed/evaluator.json \
  --ndu /signed/ndu.json --recovery /signed/recovery.json \
  --output /absolute/attestation-check.json
```

The completed signature packet permits only **manual inspection**, not an
"eligible for production" verdict. Valid signatures authenticate *claims*
and their bytes, not physical truth.
Even if positive signed NDU gains are present, this validator explicitly keeps
`production_evidence_verified=false`, `ndu_selection_authorized=false` and
`promotion_authorized=false`. A real evaluator and host must separately replay
and attest effects, seals, recovery and NDU utility before operator review.


### Optional public-weight physical smoke (still NO Hepta evidence)

A separate manual/label-triggered GitHub Actions workflow
`.github/workflows/hepta-neuron-physical-smoke.yml` tests the **three locked Laya variants in order on the same GitHub CPU runner**,
using one exact SDK Git SHA, CPU-only dependencies, explicit Hugging Face
downloads from the pinned revision, complete safetensors digests, and the same
no-label synthetic question for each variant. It uploads ONLY non-sensitive JSON diagnostics,
never weights, prompts or private data. It has zero authority to promote a Cell.

For a draft PR, an authorized repository maintainer may add the label
`hepta-neuron-physical-smoke` to trigger this workflow once; ordinary PR
synchronizations do not trigger downloads. A `workflow_dispatch` button only
becomes available when its workflow is installed on the repository default
branch; its boolean acknowledgement is required there. Neither successful CI
nor a synthetic forward is a real Hepta decision benchmark or attested host.

On a separately authorized network-enabled target host, the same operation
can be run after `hepta_neuron_materialize_weights.py` stages real bytes:

```sh
python scripts/hepta_neuron_physical_smoke.py \
  --catalog qualification/neuron-model-trials/upstream-weights.lock.json \
  --arm laya --artifact-dir /absolute/pinned/laya \
  --sdk-python-sha256 EXACT_SOURCE_PIN_OF_INSTALLED_LAYA_PYTHON \
  --device cpu --output /absolute/fresh/laya-physical-smoke.json
```

The default trial protocol CI continues to use only synthetic tests, not HF
network calls, and never implies that a real weight forward succeeded.

## Retained baseline physical diagnostic (source observation only)

GitHub Actions [run 38095294436](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38095294436)
completed successfully for the original Laya checkpoint under experimental
commit `bfbe962f41db74ef55edb5d883d7bc156ab7c2e9`. The retained original
materialization and forward JSON (with SHA-256 digests) are copied without
alteration into `physical-smoke-receipts/`; the `README.json` binds their
source artifact. Full weight SHA-256 was
`891102d372688fc2a094dac56a384bc537b87c63f21f9f3dac0be2b7cbc8d86c`,
actual parameter count was 421293827 and one 39-token CPU synthetic forward
took 340.916554 ms. These are SINGLE-RUN diagnostic observations, not p99,
true throughput, accuracy, a target-host independent attestation, an evaluator
qualification, or a production Cell run. Baseline and any later variant runs
must be identified by their own exact commit/runner and observation window.

### Three-variant physical check (one synthetic question, not model selection)

GitHub Actions [run 38095795540](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38095795540)
completed successfully on one Ubuntu CPU Runner for the original, Typed
Decisions and Multilingual models, with the fixed upstream revision and full
local weight hashes. The six original JSON receipts and the archive-level
SHA-256 manifest are preserved in
`physical-smoke-receipts/run-38095795540/`. Exact parameter counts are
421293827 / 421293827 / 321908995, respectively. One 39/39/38-token
synthetic question took 244.415929 / 250.623740 / 80.782443 ms, respectively.
These single-run timings cannot establish p50/p95/p99, production hardware
throughput, a causal speed advantage, calibrated probabilities or real task
accuracy. No real Hepta data, NDU utility gain or effect authority was used.

## Nonnegotiable promotion boundaries

A report always writes `production_evidence_verified=false`,
`ndu_selection_authorized=false`, `promotion_authorized=false`. A separate
independent evaluator must authenticate model/host measurements, labels,
calibration and OOD, then issue a signed sealed-holdout result. NDU must compare
real task utility, negative transfer, retention and total resources over at
least two future windows against frozen no-change, and owner-governed shadow,
recovery, rollback, fence and canary must pass before any production selection.
No CI fixture, local digest or JSON report can satisfy these gates.
