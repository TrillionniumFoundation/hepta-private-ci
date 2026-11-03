# NEU-1: local model bakeoff — source-only research harness

This is a **fail-closed evidence verifier and optional offline driver**, not a production model backend. The canonical plan remains `docs/learning/NEURAL_BIOMIMICRY_SPEC.md` and the source integration remains `codex-rs/hepta-neuron` / `codex-rs/hepta-infer-worker-host`. No test in this folder can grant action authority, modify selected weights, promote a checkpoint, change a Cell owner or close a product qualification gate.

## Six phases and acceptance boundary

| Phase | Evidence required | Failure action |
| --- | --- | --- |
| 1 Baseline | Fixed English and Typed Laya checkpoint revisions; real local weight/tokenizer/runtime hashes; group-disjoint train/calibration/test/future dataset | Missing checksum, case or split -> BLOCKED |
| 2 Replacement | Same-case Laya Multilingual predictions, languages, p50/p95/p99, actual host RSS and explicit unknown GPU measurement | No real runtime receipt -> BLOCKED |
| 3 Encoder | Arctic 305M and Harrier 270M, frozen local encoders, trained *independent* option-scoring heads with equal optimizer/steps/batch/samples/seed/projection width | Unequal head budgets or dataset provenance -> BLOCKED |
| 4 Safety | Test and future group-heldout accuracy/coverage, 15-bin ECE, multiclass Brier, OOD false-acceptance, language/family negative transfer, paired *group*-bootstrap 95% CI | Incomplete pairs / invalid probabilities -> BLOCKED |
| 5 Resources | **Each** arm at 64 / 256 / 1024 / 4096 logical Cells; observed simultaneously active count, host, loaded model, p95/p99, throughput, load duration and RSS | Any absent arm/scale/host measurement -> BLOCKED |
| 6 Lifecycle | Actual independent owner receipts for Artifact CAS, signed load, Supervisor cutover, stale-generation rejection, crash reopen and rollback, plus independently pinned Ed25519 auditor public key | Invalid signature, missing owner, invalid order, missing/modified receipt -> BLOCKED |

Run contract tests with `python3 -m unittest discover -s qualification/neuron-model-bakeoff -p 'test_*.py' -v`. They deliberately construct synthetic observations and a temporary signing key to verify **rejection logic**. A successful test is never evidence that real checkpoints ran.

## Real model collection

The runner does not download models: pre-stage weights in an exact pinned local checkpoint directory after reviewing licenses, device/runtime and tokenizer/preprocessing dependencies. Store weights and private datasets **outside** the Git repository. Record the full model revision and SHA256 for weight file(s), tokenizer and runtime.

For a Laya checkpoint (`english`, `typed-decisions` or `multilingual`), provision `laya`, `torch` and `psutil` on the target host. An example with deliberately non-executable placeholders:

```sh
python3 qualification/neuron-model-bakeoff/run_laya.py \
  --dataset /approved/cases.jsonl \
  --checkpoint-dir /approved/checkpoints/laya-english \
  --weights-file /approved/checkpoints/laya-english/model.safetensors \
  --weights-sha256 "$ACTUAL_SHA256" --host-id "$ACTUAL_HOST_ID" \
  --device cuda --confidence-min "$FROZEN_CALIBRATION_THRESHOLD" \
  --max-len 512 --head-max-len 256 \
  --output /evidence/laya-english.predictions.jsonl
```

This runner sends `state` and `question`/option criteria to the model but **never** the truth label, OOD flag, group or split. It records measured local latency and RSS; `gpu_peak_bytes=null` because PyTorch allocator peak is not total device-resident GPU usage. Observe GPU usage separately on the target host. Laya `choice` probabilities must be checked for label completeness. Output is not signed and does not certify independent observations by itself. SDK reproducibility: https://nandhakishorm.github.io/laya/reference/agent/ ; the existing reference source pin is in the canonical spec.

For the two embedding models, `run_heads.py` supports `train`, `calibrate`, and `eval` with pre-staged locally audited SentenceTransformer checkpoints. **Both** use the same 256-dimensional fixed random projection and the same 257-parameter linear option-scoring head, batch size, step count, seed and optimizer schedule. Training uses **only** the train split, temperature and abstention fit **only** calibration, evaluation **only** test/future. The experimental Head is not Laya-compatible at the tensor level, and is not connected to production inference. `--reviewed-local-code` permits local third-party Python only after an external audit; it is disabled by default. The train stage writes a safe tensor `.npz`, calibration writes a separate immutable JSON file, and eval writes candidate prediction JSONL. Keep these separated for reproducibility. This is one *candidate experimental protocol*, not a claim of Pareto improvement.

The JSONL dataset requires `case_id`, `group_id`, `split`, `state`, `question`, `labels` (ordered strings), `label`, `language`, `task_family`, `ood` (boolean), and optionally `criteria` (label-to-description map). Every split is mandatory; group IDs must not appear in multiple splits. The stage-3 head training manifest requires `steps`, `batch_size`, `examples_seen`, `seed`, `target_dim=256`, `optimizer_sha256`, and `training_dataset_sha256` computed over canonical sorted train rows. The Head *must not* read gold labels during eval.

## Independent verifier / evidence format

`bakeoff.py` uses only the Python standard library and an external system `openssl` binary for Ed25519 verification:

```sh
python3 qualification/neuron-model-bakeoff/bakeoff.py \
  --root /offline/immutable-evidence --manifest /offline/immutable-evidence/manifest.json \
  --trusted-lifecycle-key /independent-auditor/pubkey.pem \
  --output /offline/evaluation-report.json
```

The manifest has `schema=hepta.neuron-model-bakeoff.v1`, `source_commit` (full Git SHA), `dataset` (path + SHA256), `models` (five entries with `arm`, `revision`, `license`, and SHA-bound `weights`, `tokenizer`, `runtime`, `predictions`), `workload` (SHA-bound JSONL) and `lifecycle` (SHA-bound JSON). Candidate `head_training` must have identical values for both embedding arms and exact training-split digest. All artifact paths must resolve under `--root`; absolute paths and `..` are prohibited. Evidence containing private task content must stay on authorized storage.

Workload JSONL must contain 20 rows: for every arm and each logical cell count `64`, `256`, `1024`, `4096`, provide `active_cells`, `requests`, `throughput_per_sec`, `p95_ms`, `p99_ms`, `load_ms`, `peak_rss_bytes`, `host_id`, and `execution_kind="observed-real-model"`. The host-side collector must come from a real admitted Hepta worker. A fabricated `execution_kind` string or sample measurements do **not** prove genuine execution; the observer must verify target-host runtime provenance separately.

Lifecycle JSON uses `schema=hepta.neuron-bakeoff.lifecycle.v1` and exactly six ordered `events`: `artifact_cas`, `signed_load`, `generation_cutover`, `stale_generation_reject`, `fault_reopen`, `rollback`. Each includes `owner`, `operation_id`, `generation`, `status="observed_success"`, `receipt_path` and `receipt_sha256`; the verifier checks the existing referenced receipt bytes. The independent auditor signs the canonical compact UTF-8 JSON (excluding `signature_base64`) using an Ed25519 key. The public key is supplied by a separately provisioned trust owner, **not** by the model trainer or the manifest. Receipt fields and signature are necessary but not sufficient: a separate owner must establish that the bytes came from the actual product execution path.

**Output deliberately says** `evaluation_evidence_only_not_release_or_promotion`, never `all_blockers_closed`. A real bakeoff requires approved data, pinned usable model bytes, live target host/driver, training resources, verified independent observer and externally selected deployment/rollback. Until those exist, all six empirical acceptance gates remain **OPEN**.
