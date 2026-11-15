# V11 research: isolated postseal scoring without training dependencies

**DRAFT / SHADOW_ONLY / DENY_ALL. NO MAIN MERGE, model promotion, or new true Granite efficacy evidence.**

## Frozen parent and noninterference

This is a small additive child of V10 PR #2384 at exact source `0d09048cc3180a502dec6808297937aa78e22853`. It deliberately does **not** advance the V10 parent branch, because its exact-HEAD [real Granite nine-arm Actions run #38820394598](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38820394598) is already queued. Replacing the V10 parent HEAD would cause the registered cancel-in-progress workflow to supersede that work. Previous V7/V8/V9 control and V10 training/encoder files remain byte-identical.

## Fixed, audited boundary

The original independent reviewer imported `v10_granite_reader` merely to obtain the arms/seeds and `sha_file`. That transitively imported `torch`, `safetensors`, the training models and the optimizer environment. Scientific scoring must not depend on the trainer's source implementation or its heavyweight packages.

V11 independently registers exactly three original arms and seeds, and computes model/receipt file SHA using stdlib `hashlib.sha256`. It preserves the original complete nine-checkpoint, model SHA, feature receipt, training-source SHA, complete 256-step optimizer schedule, source-group pairing, world/proof and final-label security checks. No thresholds/metrics/labels are changed. The source-only test uses a separate Python `-S` process and fails if it pulls in `torch`, `safetensors`, `transformers` or `v10_granite_reader`. Physical evaluator now runs `python -S` and omits redundant Torch/NumPy/Transformers package installs from the **postseal scoring job only**; real-encoder and nine-model TRAIN steps retain their original pinned packages.

## Actually executed vs not executed

- **65/65 focused tests** passed in an ordinary Python process; **65/65** separately passed with `python -O`, no skips. The 63 inherited cases include original V9 provenance, the V10 globally conflicting evidence cases, and three-seed model SGD source-trace records; two new cases exercise independent stdlib reviewer import and byte-sensitive digest.
- A real `python -S` import of the updated scoring module completed without importing model/training packages.
- Original V10 Python error evidence is historical; this V11 child is not a retrospective fix for successful Granite scientific model runs. **No new true Granite forward, natural human cohort, nine-fit completion or independently observed heldout scores is claimed.**
- Separate child branch prevents cancellation of the original physical queued run; the V11 exact-head source/architecture checks must still execute before any proposed integration.

## Next decision

Keep original V10 physical run and its exact-source artifacts unaltered; after it finishes, verify the model source/weights and original heldout raw predictions with this separately implemented stdlib scorer. If source, original model acquisition, SGD, or label-owner checks fail, repair that actual failure without waiver. If heldout model efficacy stays near chance, report the negative and prioritize grounded entity/variable representation and naturally sourced evaluations before expensive NDU/FBSDE recursion.

Always: `production_accepted=false`, `model_selected=false`, `authority=DENY_ALL`.
