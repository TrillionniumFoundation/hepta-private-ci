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

**Full-model manifests must bind** `upstream_lock_sha256` and use the locked
common source revision and expected weight hash for each model. Pass
`--upstream-lock qualification/neuron-model-trials/upstream-weights.lock.json`
on `blind`, `run` and `compare`. The full-model CLI fails closed otherwise.
The `artifact_tree_sha256` field is still filled **after** actual staging and
must match the physically measured subtree; no synthetic placeholder qualifies.

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
