# HPCA V2 process-independent CPU forward reexecution — HOLD_NO_GO

This is a **new process-level reexecution on the same ai395 host**, not a new
training run, independent holdout or evaluator, separate hardware validation,
or model-selection/adoption evidence. It uses the **same original committed
inference program**, the same public operator-written 24 OOD tasks, the same
base model, and eight original LoRA adapters. **DENY_ALL.**

## Exact source and input pins

- Original precommitted task plan: PR #5960 head
  `a54c1d72ee2d82d3bae5c5fdda94d5d3333046b2`.
  Plan SHA256 `acb16047e5942d317262ddb8273a2d62e9131e758d6627dcf1c2f42081d98043`.
- Original inference program: PR #5995 head
  `aaa01ecc3b4e157dcf4927ac42301daaf2df7b4c`.
  SHA256 `b9f61e8133f67af2d126c3730588c1386efcfb2788259f618e092081c2454af8`.
- Original V2 training/result archive SHA256
  `9512849b90964c35951bb8bb2226b3f2f6d3ec0da1e9a3b98467c8970afbe39c`.
- Prior 216-row OOD forward archive SHA256
  `3002553ec485b19247f510863e9c78d2cce7747434ad7737f68b7dd3f9a74a2a`.
- Verified base-model file SHA256 `5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c`,
  config `8eb740e8bbe4cff95ea7b4588d17a2432deb16e8075bc5828ff7ba9be94d982a`,
  tokenizer `9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c`.
  Eight LoRA adapters are each SHA+size checked against the original training archive
  before model execution; no adapter was trained or modified.
- Frozen seeds 11, 17, 23, 29; each has interleaved/bursty; plus one base.
  Environment: ai395 CPU-only Torch 2.9.1+cpu, transformers 4.57.3,
  PEFT 0.18.0; four inference CPU threads.

## New actual model execution

HeptaRuntime durable native job **`1a1cbccc45f-2564-cbd`**, exit 0;
model base and all eight original LoRA adapters were freshly loaded and
executed over all 24 prompts. The untouched fresh result file is
`HPCA_V2_PROCESS_REPLAY_RESULT.json`, SHA256
`a5e40b990dc2b02b7c689c3ed5332a0c10348d04f0ee8e6bcc8d49b3b58dcc4b`.
The full process stdout/stderr are retained in this directory.

An independent stdlib comparator checks the original published record against
the fresh result: **9/9 model conditions**, **216/216 task predictions** and
**648/648 recorded probability, Brier, and log-loss fields are bit-exactly
equal** (no changed scores). The four paired bursty/interleaved *binary
accuracy* contrasts are still **0,0,0,0** on these 24 public tasks.

Measured new full-process cost: **9.599138684 s wall**,
**32.938411662 s CPU**, **1,248,592 KiB max RSS**, 14,557,184 block-read
bytes from the process IO counter. Original first execution was 9.919519 s
wall / 33.539318 s CPU / 1,229,628 KiB peak RSS. These are *process-scoped*
costs, not all-in training, evaluator, acquisition, energy, or deployment cost.
The repeat ran with a 400% CPU quota and 4 GiB process-memory ceiling; these
are new bounds, not evidence that original training had the same envelope.

The archived JSON comparison is `HPCA_V2_PROCESS_REPLAY_AUDIT.json`.
`verify_hpca_process_replay.py` and its six synthetic tamper/consistency
tests can be rerun via the path-scoped Actions workflow. Passing CI **only
verifies the recorded pair**; it does not replay native model inference on
GitHub-hosted machines.

## Remaining scientific and production gates

This strengthens the **reproducibility of an existing negative operator-task
result**, not its scientific generalizability. It has no independently held
future B, independently controlled evaluator, prospective sparse/dense ACT/CTRL
effects, NDU factorial attribution, native Owner authority, true
Adopt/NoUpdate, distinct next C, or whole Agentd/Root cold recovery.
All remain **HOLD_NO_GO / DENY_ALL**. Do not auto-merge or deploy.
