# Hepta Neuron external-model A/B trials (diagnostic only)

The executable comparison is intentionally **not** a Cell production activation, model
selector, an independent evaluator, or an NDU receipt. It never replaces a serving
model. Synthetic CI cases prove only protocol and negative-path behavior.

## Three frozen arms

- `decisions`: `laya` (no-change) vs `typed`, actual ~421M family; require actual
  parameter counts within 1% and one common 512-token / 192-option-token cap.
- `multilingual`: `laya` (no-change) vs `multilingual` (~322M); measure English,
  Chinese and cross-language cases in **each** holdout/future window. This is a
  *same-maximum-budget*, not an equal-parameter-count comparison.
- `heads`: `linear` (no-change) vs `mlp` vs `swiglu`, same frozen feature vectors,
  target vector, training seed, optimizer, epochs and batch size; all trainable
  tensor counts must be within 1% and **no greater** than the linear cap.

Full-model experiments are **inference-only**. They inherit incompatible upstream
pretraining/finetuning budgets. Never claim matched training compute or superior
Hepta performance from a vendor model card. Full-model typed probabilities are
rounded by Laya's SDK; ECE10 is diagnostic, not a calibrated grant. `is_ood` is
external ground truth; the 0.8 confidence rejection is a **proxy**, not an
independent OOD head. The head trial is Q24 regression, not a decision-policy test.

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
  --sdk-sha256 EXACT_INSTALLED_LAYA_TREE_SHA256 --device cpu --output /absolute/laya.json
python scripts/hepta_neuron_model_trials.py run --manifest heads.json --dataset /model-runner/heads-blind.jsonl \
  --arm swiglu --device cpu --checkpoint-out /absolute/swiglu.safetensors \
  --output /absolute/swiglu.json
python scripts/hepta_neuron_model_trials.py compare --manifest decisions.json \
  --dataset /secure-evaluator/decisions.jsonl --receipt laya=/absolute/laya.json \
  --receipt typed=/absolute/typed.json \
  --baseline-sha256 EXACT_EARLIER_FROZEN_LAYA_RECEIPT_SHA256 --output /absolute/compare.json
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

## Nonnegotiable promotion boundaries

A report always writes `production_evidence_verified=false`,
`ndu_selection_authorized=false`, `promotion_authorized=false`. A separate
independent evaluator must authenticate model/host measurements, labels,
calibration and OOD, then issue a signed sealed-holdout result. NDU must compare
real task utility, negative transfer, retention and total resources over at
least two future windows against frozen no-change, and owner-governed shadow,
recovery, rollback, fence and canary must pass before any production selection.
No CI fixture, local digest or JSON report can satisfy these gates.
