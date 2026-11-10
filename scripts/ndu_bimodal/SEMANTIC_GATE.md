# P0/P1: frozen colour-card text/image delivery gate

**Status: bounded engineering guard only. Scientific acceptance HOLD_NO_GO; production no-update.**

This independent standard-library checker targets the numeric v4 bimodal prototype.
It neither teaches the generator semantic outputs nor demonstrates controller benefit.

## Actual checks

The input is an externally pre-registered evaluation manifest and its expected
SHA-256, supplied by the evaluator owner *before* the candidate output is seen.
The evaluator opens the original generated.txt, generated.ppm and delivery.json
from one native SUBMIT directory and rejects substitution, symlinks and mismatches.

The manifest binds public input, model checkpoint and native binary SHA-256;
the task identifier; independent acceptable normalized text; expected 16x16
colour-card RGB; image tolerances; maximum native calls, summed child wall
time and child CPU time. The manifest SHA is explicitly supplied rather than
self-authenticated from its own contents.

A positive result requires matching delivery/manifest identities, byte-for-byte
owner text and image commitments, an exact accepted phrase, valid canonical
16x16 P6 RGB data meeting both image tolerances, completed paid native calls and
costs within the frozen cap. All required checks must pass concurrently.

The decision BOUNDED_TASK_PASS is **limited to this registered colour-card task**.
The result always retains independent_evaluator_execution_verified=false,
whole_resource_budget_verified=false, open_world_semantics_verified=false,
production_adoption=false and scientific_acceptance=HOLD_NO_GO. No real-world
task-level NDU net benefit is inferred.

## Run

From repository root, with an evaluator-authorized frozen manifest and its
independently retained full 64-hex digest, execute:

    python3 -m scripts.ndu_bimodal.semantic_gate \
      --manifest /path/to/frozen.json \
      --trusted-manifest-sha256 FULL_64_HEX \
      --delivery-dir /path/to/native/infer \
      --report /new/path/report.json

Exit code zero means bounded pass, one means bounded failure; malformed or
unauthorized input fails closed. Report output is create-only. This checker
cannot verify *who* chose the task labels or whether they were held out; those
obligations require an independently signed/evaluated experiment.

Manifest contract (illustrative IDs, NOT an evaluated or frozen case):

    {
      "schema": "hepta-bimodal-colour-card-semantic-v1",
      "task_id": "independently-registered-01",
      "bindings": {
        "public_sha256": "1111111111111111111111111111111111111111111111111111111111111111",
        "checkpoint_sha256": "2222222222222222222222222222222222222222222222222222222222222222",
        "binary_sha256": "3333333333333333333333333333333333333333333333333333333333333333"
      },
      "target": {
        "accepted_text": ["red", "a red card"],
        "rgb": [255, 0, 0],
        "max_channel_error": 10,
        "max_mean_absolute_error": 4,
        "min_pixel_fraction": 0.95
      },
      "limits": {
        "max_calls": 4,
        "max_native_wall_seconds": 2.0,
        "max_native_cpu_seconds": 2.0
      }
    }

## Known inherited limitations

The predecessor #5451 native example emits repetitive ueeeee... text, even
though UTF-8 and Torch/Rust numerical parity succeeded; semantic_quality=null.
Its original training receipt changes core, encoders and adapter groups, and
therefore does NOT satisfy frozen shared backbone / private adapter training.
Its requested dynamic native policy falls back to static-quota, while finite
dynamic utility 0.398750 trails the light control result 0.471250.

P0 full source/tree, model, data, codec, utility, budget and cold-recovery binding
is still open. P1 independently qualified semantics remain open. P2/P3 actual
risk distributions, matched physical budgets and global NDU learning attribution
are open. P4 ordinary StageOwnerPorts, CURRENT, distinct NextUse and cold owner
restart are open. P5 audio/video streaming and synchronization are open.

## Scoped reproduction

    python3 -m unittest scripts.ndu_bimodal.test_semantic_gate -v

All 17 contract unit tests passed on an authorized Mac operator host after
one corrected test expectation. They test positive semantics as well as wrong
image colour, single-pixel violation, repetitive text, retargeted frozen
labels, identity mismatch, altered bytes, missing image, bad codec, cost cap,
failed call, unapproved adoption, unknown/duplicate fields and NaN. These
tests do NOT constitute a complete live native/Torch/owner or cloud CI result.
