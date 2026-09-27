# Bounded Laya retrieval driver — experimental source, not a product organ

This directory belongs to the existing inference.worker implementation. It adds no server, executor, learning store, authority issuer or top-level module. `laya_retrieval.py` is a callable CPU predictor and a one-shot qualification entry. **It is not yet wired through the production App Server/inference owner and has not been run with real weights by this change.** Its fake-predictor tests establish only input/output contracts, not accuracy, calibration, device attestation, isolation or longitudinal learning.

## Reviewed backend and artifact preparation

The implementation was checked against `NandhaKishorM/laya` commit `4066d5d5fbf08b66c6757ddeedbd797bd7655bc0`, `laya/agent.py` and `laya/common.py`, API version 0.3.20. In particular, option descriptions are capped at 48 tokens; aggregate options can shrink again, instructions can truncate and the remaining state budget can silently truncate. The driver preflights those sites with the actual tokenizer and rejects instead of silently removing support. A model upgrade requires rechecking this contract.

A host-prepared canonical, isolated, immutable checkpoint directory is required. Supply a JSON pins object with exactly `repository` (`convaiinnovations/laya`), a 40-character checkpoint `revision`, `files` (the complete relative-file to SHA-256 inventory, including weights, encoder, tokenizer and calibration/config files), `runtime_versions` (exact installed versions for laya, torch, transformers, tokenizers and safetensors) and `format` (`hepta.laya.retrieval.v1`). No mutable `main` model selection or implicit network download is admitted. This format binds identity but is not proof of authorized selection or signed build provenance. Runtime version labels are not binary/device attestation; the existing trusted host must supply those remaining guarantees.

Materialize Hub cache symlinks before admission under the artifact owner's controlled preparation. Tokenizer files needing Laya's load-time repair must be prepared as a separately identified artifact, not silently rewritten. Before/after file hashing detects ordinary drift but is not a race-proof sandbox. The directory and code must be protected from concurrent untrusted writers. Use one driver per selected resident model; logical Cells share it, not independently loaded copies.

The one-shot entry is usable with an already prepared checkpoint and pins:

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python3 \
  codex-rs/hepta-infer-worker-host/python/laya_retrieval.py \
  --checkpoint /absolute/owner/prepared/checkpoint \
  --pins /absolute/owner/prepared/pins.json < request.json
```

Dependencies must be supplied by a reviewed environment; this directory does not install or change them. No checkpoint pins or successful real-model receipt are fabricated here. The CLI's 30-second post-load budget is qualification-only and does not enforce an end-to-end process deadline or measure model load cost.

## Input and output

`request.json` contains exactly format, operation_id, scope, objective_digest, snapshot_digest, query and candidates. Each candidate contains id, source_digest and a host-selected bounded excerpt. The complete 1–8 candidate list is bound in order; the driver adds an explicit abstain choice. Digest strings do not authorize reading the source. The memory owner must check privacy, current source revision, deletion and access before constructing input and again before publication/use.

The driver returns predictions and its explicit deterministic argmax policy with tie-breaking in admitted order. Prediction probabilities are not behavior propensities: the selected deterministic action has propensity one. Output binds the operation, scope, objective, snapshot, complete candidate identities, model identity and input digest. It omits raw excerpts and ignores `act_probability`, raw confidence and self-reported success. `authority=false`, `calibration_verified=false` and `task_success=null` stay explicit. A receipt digest is not a signature, durable commit or external outcome observation.

`Rejected` before entry means no model call occurred. An exception after entry becomes `EnteredFailure`, including late responses and invalid distributions; the owner must retain consumed work and unknown status rather than inventing unused capacity. The process-local lock is bounded admission, not cross-process resource ownership. Hard cancellation needs the existing worker supervisor; a Python deadline check cannot interrupt a running native tensor operation.

## Product composition still required

The existing inference owner must admit a verified operation, reserve durable resources, pin the model, enforce process/network isolation, enter this driver, persist the result and reconcile uncertainty. Agentd/Neuron/TaskFlow then consume the exact result through their existing owner ports. Do not directly wire this CLI into a tool/effect path or let it write a second operation journal. Independent calibration, trusted device/memory accounting, revocation during use and long-lived worker recovery remain required before activation.

## Learning and computer-control boundaries

This patch implements no local model training or organ credit estimator. Evaluate future candidates against deterministic and simple-model baselines with equal total inference, training, evaluation, loading and migration budgets. Retain no-change, missing-data/no-update, future-time holdouts and old-task retention. The deterministic pilot does not supply off-policy support for actions it never takes. An independently observed result, not this predictor, supplies success labels.

No computer actions are executed. Typed predictions are proposals for existing Intuition, authority and effect owners; observation freshness, target replacement, revocation and unknown effect reconciliation cannot be replaced with model scores. Structural split/merge/retirement still uses existing TaskFlow, Supervisor, artifacts and topology handoff protocols.

## Tests

```sh
python3 -m unittest discover -v \
  -s codex-rs/hepta-infer-worker-host/python -p 'test_*.py'
```

Eleven fake-predictor contract tests cover identity binding, complete candidates, duplicate JSON, truncation, expiry/capacity before entry, invalid/late output after entry, deterministic ties, checkpoint drift, symlinks and offline admission. They deliberately do not import a model or claim that held-out retrieval quality improved. Native Neuron/inference tests and whole-product qualification remain separate.
