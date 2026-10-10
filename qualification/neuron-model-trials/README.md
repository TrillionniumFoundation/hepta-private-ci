# Hepta Neuron external-model A/B trials (diagnostic only)

These experiments never select a production artifact, install a live model or
mint an NDU receipt. Synthetic CI cases test only protocol and negative paths.

## Frozen comparisons

- decisions: Laya (no-change) versus Laya Typed Decisions (~421M each).
  Verify actual parameters within 1%, same 512-token context and 192-token
  choice-option budget.
- multilingual: Laya versus Laya Multilingual (~322M candidate). Require
  English, Chinese and cross-language test cases in each evaluation window.
  This is the same parameter *ceiling*, not an exact same-parameter experiment.
- heads: Linear (no-change) versus MLP versus SwiGLU. Same frozen input
  features, Q24 regression targets, training schedule, optimizer, batch size,
  seed and no more than 1% parameter-count gap.

Full-model comparisons are inference-only; upstream pretraining and fine-tuning
compute are not equal. Laya probabilities are rounded to four decimal places.
ECE10 is diagnostic, not a calibration certification. The 0.8 confidence OOD
false-accept gate is only a proxy and is not an independent OOD detector.

## Input files (keep all data and model bytes outside the repository)

Use a separate JSON manifest and JSONL dataset for each family. The required
manifest fields are schema, family, exact source_sha (40-hex commit),
dataset_sha256, blind_dataset_sha256, host_profile_digest, parameter_cap,
and max_len=512 for Laya.

For each Laya arm, models[arm] requires model_id, revision (40-hex HF commit),
weights_sha256 and artifact_tree_sha256. The latter is the sha_tree() digest
over a complete offline model directory (all files, symlinks forbidden).
Record actual upstream pretraining and any license/SBOM decisions independently.
For heads, head requires encoder_digest, input_dimension, state_width,
seed, epochs, batch_size and learning_rate. The 512-in, 256-width example has a baseline cap of 262656
trainable parameters; both alternative heads remain within 1%.

Every sample must contain id, split, source_group, observed_at_ms. The splits
must be chronological and source-group-disjoint: train, calibration, holdout,
future_1, future_2. Never use sealed or future data to choose an artifact.
Decision rows contain state, a type=choice question with instructions and
ordered criteria, gold, is_ood, language and domain. Multilingual evaluation
requires en, zh and cross in each holdout/future window. Head rows contain
features_q24 of length input_dimension and target_q24 of length 2*state_width.

Minimal decision-family manifest skeleton (replace every placeholder with
the actual pinned digest before running):

~~~json
{"schema":"hepta.neuron.model-trial.v1","family":"decisions",
 "source_sha":"<40-hex>","dataset_sha256":"<sealed 64-hex>",
 "blind_dataset_sha256":"<redacted 64-hex>",
 "host_profile_digest":"<64-hex>","parameter_cap":425000000,"max_len":512,
 "models":{
   "laya":{"model_id":"convaiinnovations/laya","revision":"<40-hex>",
     "weights_sha256":"<64-hex>","artifact_tree_sha256":"<64-hex>"},
   "typed":{"model_id":"convaiinnovations/laya-typed-decisions","revision":"<40-hex>",
     "weights_sha256":"<64-hex>","artifact_tree_sha256":"<64-hex>"}
 }}
~~~

## Sealed evaluator data and blinded runner input

Do not send gold labels, OOD status or future Q24 regression targets to the
model runner. The independent Evaluator holds the full, labeled JSONL. The
model runner uses a derived redacted JSONL: remove gold/is_ood from all
decision rows, and retain target_q24 only on head training rows. The evaluator
verifies that blind_dataset_sha256 is the deterministic canonical SHA-256 of the
redaction of the sealed dataset_sha256 input.

Before freezing both digests, compute them in the evaluator-only environment:

~~~python
import hashlib, json, sys
from pathlib import Path
sys.path.insert(0, "scripts")
from hepta_neuron_model_trials import blind_rows, canonical_jsonl, sha_file
sealed = Path("/secure-evaluator/decisions.jsonl")
rows = [json.loads(line) for line in sealed.read_text().splitlines() if line.strip()]
print("dataset_sha256", sha_file(sealed))
print("blind_dataset_sha256", hashlib.sha256(canonical_jsonl(blind_rows(rows, "decisions"))).hexdigest())
~~~

After freezing the manifest, the evaluator produces an exclusive-write blind
input under separate permissions. This is not an in-process data-access
control; enforce filesystem and principal isolation externally:

~~~sh
python scripts/hepta_neuron_model_trials.py blind --manifest decisions.json \
  --dataset /secure-evaluator/decisions.jsonl --output /model-runner/decisions-blind.jsonl
~~~

## Run on the model host

Install the exact Laya SDK, torch and safetensors in an isolated environment.
Record the installed SDK's sha_tree(package_path, only_python=True) digest.
No automatic Hugging Face downloads are allowed.

~~~sh
python scripts/hepta_neuron_model_trials.py run --manifest decisions.json --dataset /model-runner/decisions-blind.jsonl \
  --arm laya --artifact-dir /absolute/local/laya --sdk-sha256 EXACT_SDK_DIGEST \
  --device cpu --output /absolute/laya.json
python scripts/hepta_neuron_model_trials.py run --manifest heads.json --dataset /model-runner/heads-blind.jsonl \
  --arm swiglu --device cpu --checkpoint-out /absolute/swiglu.safetensors \
  --output /absolute/swiglu.json
python scripts/hepta_neuron_model_trials.py compare --manifest decisions.json \
  --dataset /secure-evaluator/decisions.jsonl --receipt laya=/absolute/laya.json \
  --receipt typed=/absolute/typed.json \
  --baseline-sha256 EARLIER_FROZEN_NO_CHANGE_SHA256 --output /absolute/report.json
~~~

Repeat for every arm/family. The earlier baseline SHA must be retained prior to
candidate inspection; this script checks byte equality but cannot authenticate
the issuer or time. Artifact hashes prove local bytes, not a caller-reported HF
revision. Keep training, model-load and target-host receipts for independent
verification. Chronological labels alone do not prove truly prospective windows. No user-provided model or dataset is currently bundled.

## Signed external role evidence (non-authorizing check)

A distinct verifier, scripts/hepta_neuron_trial_evidence_gate.py, validates
Ed25519-signed claims from four separately pinned principals and keys:
shadow, evaluator, ndu and recovery. An operator must provision the trust
registry and record its SHA-256 out of band. The trainer must not own any of
these signing keys.

The shadow receipt must bind complete per-arm runner receipt hashes and
claim zero effects. The evaluator must bind sealed labels and scoring over
holdout and both future windows. NDU must bind the earlier no-change baseline,
utility gains for every candidate in both windows, resource cost, negative
transfer and retention. Recovery must bind journal CAS, old-route rejection,
generation fences, rollback and no-resurrection. Every signed body must bind
the frozen trial manifest, comparison, source, host and sealed data digests.

~~~sh
python scripts/hepta_neuron_trial_evidence_gate.py \
  --manifest decisions.json --comparison /absolute/report.json \
  --trust /operator/trust.json --trust-sha256 PINNED_BY_OPERATOR_SHA256 \
  --shadow /signed/shadow.json --evaluator /signed/evaluator.json \
  --ndu /signed/ndu.json --recovery /signed/recovery.json \
  --output /absolute/signed-check.json
~~~

Signature verification authenticates only the signed assertion bytes, not
the physical truth of CAS/host/recovery or true evaluator independence.
The verifier NEVER selects a model and always keeps
production_evidence_verified=false, ndu_selection_authorized=false and
promotion_authorized=false, even if every signature verifies.

## Not production evidence

Every comparison explicitly returns production_evidence_verified=false,
ndu_selection_authorized=false and promotion_authorized=false. A different
independent evaluator must verify sealed holdout, labels, calibration/OOD and
future-window results, and NDU must weigh real task utility, negative transfer,
retention and resources. Then the named owner must pass shadow, restart,
CAS/route-generation fence, rollback and canary under a qualified target host.
No local JSON digest or green CI fixture replaces those approvals.
