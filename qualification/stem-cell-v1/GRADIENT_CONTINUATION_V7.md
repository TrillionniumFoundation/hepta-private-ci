# V7 shared-Stem Bridge continuation: gradient-conflict mechanism

**Status:** research / SHADOW_ONLY / DENY_ALL / no Stem or Cell promotion.

**Parent:** `research/cross-fact-bridge-v6-20261015` at pinned commit
`54a3d90e98f6b6d7585e1705690510476d01f54a` (#2338). V6's synthetic paired-world
warmup fitted in all three seeds but the contrastive old-task TRAIN retention
failed in seed 41; independent future transfer was not demonstrated. This is a
candidate-only experiment on existing frozen checkpoints. All original V6 runtime
source bytes and read-only original results remain intact.

## What has been implemented

* `bridge_gradient_guard.py` executes a real train-only two-stream backward pass.
  The natural/old-task gradient and binding/new-task gradient are computed from
  separate original minibatches on the SAME current Reader state. The
  `joint` and `protect_old` arms pay exactly **two Reader forwards, two complete
  backward calls, and one Adam optimizer update** per logical training step;
  both use identical initial model, data schedule, learning rates, parameter
  inventory, gradient clipping and number of optimizer steps.
* `joint` sums both gradients; `protect_old` removes the new gradient's
  component that directly opposes the old gradient. This guarantees only a
  first-order *pre-Adam* alignment for a finite well-formed gradient; nonlinear
  loss, optimizer preconditioning, gradient clipping, later drift and task
  generalization are NOT proved by the algebra. The guarded step consumes
  additional dot products and projection arithmetic, so full FLOPs are **not**
  equal even when forwards, backwards and updates match.
* `bridge_gradient_campaign.py` loads genuine, SHA-bound V6 Granite token bank
  and original train-only data, reopens V6 frozen warmup weights, rejects altered
  original V6 source, reruns the identical 500-step per-seed old/new batch plan,
  trains both arms (3 seeds × 2), and saves candidate weights and complete
  raw cost/gradient receipts into **new output directories only**. It applies
  existing V6 binding retention gates and reports natural *internal tune*
  descriptively. Any failed attempt leaves a terminal failure receipt.
* Neither arm opens official validation or independent future-task labels.
  Neither may replace the original V6 experiment or bypass original selection.

## Local tests executed before push

`python -m unittest -v test_bridge_gradient_guard.py` executes actual CPU Torch
forward/backward/Adam calls and adversarial numerical controls. This suite uses
small artificial tensors and a scoped stub for the *test-only* binding loss owner,
**not** original Granite weights or human-task efficacy. It verifies projection
numerics, no-conflict equivalence, empty/nonfinite/wrong-shape rejection, two
physical forward/backward calls, matching optimizer steps and frozen-parent
isolation. A successful local test suite is not a genuine six-arm campaign.

## Actual original-model invocation

From the repository root in an environment containing the exact V6 dependencies:

```bash
python qualification/stem-cell-v1/bridge_gradient_campaign.py \
  --source /approved/multirc-source \
  --snapshot /approved/pinned-granite97 \
  --prepared /sealed/prepared-token-bank \
  --previous-main /sealed/original-v4 \
  --previous-native /sealed/original-v5-native \
  --previous-v5 /sealed/original-binding-v5 \
  --previous-v6 /sealed/original-bridge-v6 \
  --output /sealed/new-gradient-v7
```

No paths above are assumed to exist on the authoring host; they are placeholders
for the *previously qualified original V6 inputs*. Refuse to fake those material
owners or infer pretrained evidence from a mock. The original model/data archives
and valid original source tree must be supplied; this command does not download
third-party model weights itself. Keep trained candidates out of the production
model registry until separately admitted.

## Next evidence required

1. Execute all six original-pretrained campaigns with the exact frozen model
   and source bytes. Require 500/500 actual paired train updates per arm/seed,
   independent verification of saved weights, and full old/new/optimizer costs.
2. Check old TRAIN retention for all three seeds, then obtain a *separately
   selected* new-source future panel. No posthoc choice of winning seeds/arms.
3. Compare a strong single unsplit Reader and equal total parameter budget,
   paired old/new future quality and true whole-lifecycle compute. Record
   negative transfer and failure cases, especially the old seed-41 result.
4. Only after genuine generalization and cost-adjusted NDU improvement should
   Cell split/fusion, multimodal specialization or model promotion be proposed.

**Research-only code.** No native NDU authority, FBSDE theorem, 10T/100T
teacher-equivalence, real multimodal generation, production Stem selection or
real-world reasoning emergence is asserted by this work.
