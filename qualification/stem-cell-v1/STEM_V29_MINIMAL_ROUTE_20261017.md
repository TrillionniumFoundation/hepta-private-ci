# V29 — Source-only minimal policy route for real lazy DINO vision

2026-10-17 · Research-only / **DRAFT / SHADOW_ONLY / DENY_ALL**.

## Scientific problem

The original V28 physical proof consumes a frozen V27 route file that contains
`text_class`, `image_class`, and `selected_class`. No TEST labels or authority
are there, and the route is properly frozen from original historical outputs;
however, a genuinely on-demand vision run should **not have access to cached
predictions from the image Encoder**. That is a distinguishable information
exposure from the earlier ground-truth TEST-label isolation. A study measuring
physical batch savings should use only source IDs and the frozen *text-only*
trigger. The V25/V27 historic result remains negative (17/64 for both text
and conditional selection, 5 rescues and 5 harms, nominal McNemar p=1).

## Source-first construction and exact identities

V29 inherits immutable V28 `b0ea6b2e218ac4f1d85a5dde22a1e2d0d1a638f1` and
its original pinned E3 source controls, with no separate model/owner/issuer.

1. Verify original E3 ZIP `11945106672`, full SHA-256
   `7807b82d6c747b0b13666b330145e3801a8c8a0aadeee3f2ff7ab5f5c8c00a30`.
   Seal V27's source- and label-blind full historical plan and require exact
   SHA-256 `c8f3f3d03ef9bdc9722d1197aaa807d901a4d5cda2e6c40d20f8ddcf7d2b8ad2`.
2. **Before any original DINO model acquisition**, project the full plan to only
   (`id`, `group`, `trigger_vision`) for all 64 original cases; the trigger is
   solely based on the frozen text-only Top-1/Top-2 margin `<0.005`.
   V29 refuses nested class, scores, source body, image SHA, target or
   instruction fields. It stores no labels, cached image responses, or output
   privileges. Its exact full 11,404-byte canonical document digest is
   `d8a555bef8f95680cd35a16cf3dbe7f8e9ab717fe626e4dc82e6fd61538773a6`.
3. Delete the complete V27 plan and original ZIP before the research
   pretrained model stage. The physical model script admits **only** the exact
   canonical V29 digest; it has no fallback to a full V27 plan. Missing or
   changed identity, extra field, wrong source/route or missing 21 triggers
   fail closed. The data-source staging remains source-only, and its publisher
   cache is removed before model execution. This does not certify forensic
   deletion of past files, but prevents exposure through the declared inputs.
4. Reuse one real pinned DINOv2-small checkpoint, source-bound 64 genuine
   ScienceQA images, TRAIN-only warmup and ABBA order full64/conditional21/
   conditional21/full64. The runner checks 8/3/3/8 **actual** backend batch
   increments, CPU + wall, input byte count, same-image 384D parity, and
   process high-water RSS. There is no new textual model or TRAIN update.
5. Publish **only** sanitized aggregate. Original image files, per-case
   features, route IDs, train labels, TEST labels, checkpoint weights and raw
   model output remain inside the job. This file defines research execution,
   not a production route/capability protocol.

## Test and acceptance boundaries

`test_v29_route_only.py` provides pure source/adversarial tests for source
compatibility, strict SHA/canonicalization, duplicate identities, unknown
columns, label/visual-output exclusion, and true run-scheduling/custody checks.
Tests execute no real pretrained model. A separate physical push workflow must
produce a terminal successful original-source/model-owner receipt before reporting
any physical savings. Code/CI success cannot claim full system p95/p99, energy,
GPU residency, causal need for images, improved accuracy, future-time utility,
retention, NDU selection, or 4,096 production Cell capacity. Existing negative
V25/V27 same-source utility remains binding. Do not merge to `main`, grant
FinalUse, select Stem or enable automatic Cell split/fusion.
