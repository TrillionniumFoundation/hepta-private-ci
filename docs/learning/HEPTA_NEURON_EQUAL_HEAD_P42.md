# P42 — five-arm original Encoder / equal-budget Head research

**DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO.** Child of P41
[#3445](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3445),
frozen parent 4b672808ceaa13597d7792201e06a82e0819b750.
Do not merge or replace an already selected Neuron Cell without independent
real-model, owner, final-use and target-host qualification.

## Scope: eliminate a misleading comparison, not a production blocker

P39 measured **complete pretrained** Laya English, Typed and Multilingual
decision policies, but trained identical 200-step task Heads only for Arctic
and Harrier. These are useful baseline observations, **not** five equal-
specialization-budget model evaluations. The original P39 full-policy run,
scores, counters, weight pins and immutable P40/P41 provenance remain intact.

The P42 experiment adds a **separate** parity result for each of the five
original SHA256-pinned model weight sets. In this parity arm only:

1. Use the same original historical 2014 news rows and the same plain-text
   input (no prompt-specific model-generated features). Limit all original
   frozen encodings to 192 tokens, require finite nonzero vector outputs.
2. For the three Laya variants, call their original **frozen encoder**
   directly *after* the full typed-decision policy forward. These are
   additional real forwards and do not count as full-policy inferences.
   For Arctic and Harrier, reuse their already measured real original
   Encoder features. CLS is used for bidirectional Encoders; the last
   nonpadding token is used for Harrier's decoder-style embedding.
3. Apply an **untrained, deterministic Gaussian projection** with seed 2307
   and normalized 256-dimensional output. Each input width has a distinct
   projected matrix and SHA256; there is no supervised projector fitting.
   This is an experimental 512-feature-contract-compatible representation,
   not a qualified Hepta runtime projection or a model-equivalence claim.
4. Train the **same 1,028 trainable scalar** linear 256-to-4 Head on *train*
   data only: exact P39 train_task_head with AdamW, 200 full-batch steps,
   seed 7, LR 0.05. Select temperature only from the *calibration* cohort.
   Preserve the original future_1, future_2 and publisher-OOD rows as
   separately scored historical holdouts. A trained Laya parity Head does
   **not** erase or overwrite its original full policy.
5. Serialize each genuine trained Head as F32 safetensors, hash original
   bytes and **load fresh tensors**. Require exact matching logits on all
   splits before publishing the corresponding Head artifact.
6. In a separate no-Torch audit job, parse bounded safetensors headers and
   actual F32 values, reject nonfinite/malformed, verify exact byte SHA,
   verify 1,028 parameter inventory and training metadata, recompute
   accuracy/ECE/Brier/abstention from raw parity predictions, and compare
   every row identity/label to the retained original policy report.

Five-arm physical workflow now retains per candidate:
physical-output.json (original policy or original Encoder+Head),
equal-head-output.json (new parity experiment),
equal-head.safetensors (real, reloaded Head),
and its original pinned model and publisher metadata. The aggregate job
retains five-arm-equal-head-audit.json with clear REVIEW_REQUIRED or
BLOCKED and no authority. Missing artifacts fail closed.

The preflight workflow was corrected to check **exact PR head SHA** rather
than checking out GitHub's synthetic merge ref, and the no-Torch contract
step no longer accidentally imports Torch-only physical tests. Torch-based
contract tests run in the existing pinned CPU virtual environment instead.

## Verification

Focused, non-pretrained local unit tests:
python3 -m unittest discover -s qa/stem-bakeoff -p
'test_replacement_head_parity*.py' -v.
The P42 authoring environment verified 10 focused fixture/adversarial tests
under normal and optimized Python, with PyTorch 2.10.0 CPU. These tests
only validate shape, freezing, replay, unsafe artifact and forged-receipt
rejection. They are not five original-model forward evidence.

Exact P42 head and all parent+merge CI must produce terminal logs before
claims of source qualification. Source-only success is not host/operator
acceptance.

## Explicit remaining external blockers

- Full five pinned checkpoints really load and execute on a named target
  cloud host, with actual raw outputs and device-specific receipts.
- Larger, independently preregistered multilingual and retrieval cohorts,
  provenance custody, and heldout/negative-transfer decision results.
- Equal-budget **full-policy** adaptation, if that stronger comparison is
  later required; shared-head parity does not establish this.
- Real 64/256/1024/4096 logical and simultaneously active Cell resource
  tests: host/generation, CPU/RSS/GPU/energy/load, actual p95/p99 and
  instrumented state isolation plus backpressure.
- Separately verified original Artifact CAS, checkpoint migration, CNS
  route cutover, Supervisor Generation Fence, crash/restart/rollback,
  and rejected old-generation independently signed Final-use receipts.
- Independent observer, security/statistics review and operator approval.
  No fake source fixture, metadata hash, queued CI or self-reported
  signature is permitted to close these external acceptance gates.
