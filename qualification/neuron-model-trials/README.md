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
dataset_sha256, host_profile_digest, parameter_cap, and max_len=512 for Laya.

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
 "source_sha":"<40-hex>","dataset_sha256":"<64-hex>",
 "host_profile_digest":"<64-hex>","parameter_cap":425000000,"max_len":512,
 "models":{
   "laya":{"model_id":"convaiinnovations/laya","revision":"<40-hex>",
     "weights_sha256":"<64-hex>","artifact_tree_sha256":"<64-hex>"},
   "typed":{"model_id":"convaiinnovations/laya-typed-decisions","revision":"<40-hex>",
     "weights_sha256":"<64-hex>","artifact_tree_sha256":"<64-hex>"}
 }}
~~~

## Run on the model host

Install the exact Laya SDK, torch and safetensors in an isolated environment.
Record the installed SDK's sha_tree(package_path, only_python=True) digest.
No automatic Hugging Face downloads are allowed.

~~~sh
python scripts/hepta_neuron_model_trials.py run --manifest decisions.json --dataset decisions.jsonl \
  --arm laya --artifact-dir /absolute/local/laya --sdk-sha256 EXACT_SDK_DIGEST \
  --device cpu --output /absolute/laya.json
python scripts/hepta_neuron_model_trials.py run --manifest heads.json --dataset heads.jsonl \
  --arm swiglu --device cpu --checkpoint-out /absolute/swiglu.safetensors \
  --output /absolute/swiglu.json
python scripts/hepta_neuron_model_trials.py compare --manifest decisions.json \
  --dataset decisions.jsonl --receipt laya=/absolute/laya.json \
  --receipt typed=/absolute/typed.json \
  --baseline-sha256 EARLIER_FROZEN_NO_CHANGE_SHA256 --output /absolute/report.json
~~~

Repeat for every arm/family. The earlier baseline SHA must be retained prior to
candidate inspection; this script checks byte equality but cannot authenticate
the issuer or time. Artifact hashes prove local bytes, not a caller-reported HF
revision. Keep training, model-load and target-host receipts for independent
verification. No user-provided model or dataset is currently bundled.

## Not production evidence

Every comparison explicitly returns production_evidence_verified=false,
ndu_selection_authorized=false and promotion_authorized=false. A different
independent evaluator must verify sealed holdout, labels, calibration/OOD and
future-window results, and NDU must weigh real task utility, negative transfer,
retention and resources. Then the named owner must pass shadow, restart,
CAS/route-generation fence, rollback and canary under a qualified target host.
No local JSON digest or green CI fixture replaces those approvals.
