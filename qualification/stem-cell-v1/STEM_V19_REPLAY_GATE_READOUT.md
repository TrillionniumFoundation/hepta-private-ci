# Hepta V19 — Frozen-original receipt versus bounded numeric replay

**2026-10-16 · Research-only · DRAFT / SHADOW_ONLY / DENY_ALL.**
This qualification is additive to Draft PR #2364. No Worker, model owner, NDU, CAS/CNS, FinalUse, selected model, protected main, or production Cell route is altered.

## Fixed historical inputs

- Original physical archived mmBERT-small features: GitHub Actions artifact 11890616195, ZIP SHA256 0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7.
- Original V18 retrospective aggregate SHA256 5c9cf67e1d91ca8ebc5adafd9963357a91ddb45361f43d0311c276150e29edb4.
- Original V18 absence-of-future HOLD SHA256 1cd975d0ab51fbe90ee161df1a30c8a7dc66b06bd39e46eb19229b699b544372.
- V18 original independent auditor code SHA256 9693d3a5be2dd4fb50b0e033d9798932237df0cabacd8d0b017d78ca1028d0f4.

Historical files must match those bytes exactly. The V19 reviewer does not accept arbitrary user-provided replay-model success flags. It invokes the original V18 auditor, which first revalidates real V15/V16/V17 saved tensors, source/feature identity and 32 authentic historical calibration records (three correlated seeds, not 96 new cases).

## Original independent local replay

The frozen V18 aggregate SHA differs from a fresh independent source-bound replay SHA b39cada32b071c323f6a03d77a283e191589594b0ada8e24d44a8e69382c30e9. The model files and source IDs still independently revalidate; maximum metric drift was 2.375078296534827e-08. Merely requiring every run to match the frozen *whole JSON* SHA is inappropriate for legitimate FP32 cross-run behavior, but the frozen original SHA must never be silently updated.

V19 compares the **complete JSON field tree**. All keys, arrays, source identities, case counts, seeded-run structure, original comparator and decisions are exact. Only finite floating numerical fields may differ by at most 5e-7 absolute. A new V17 full prediction JSON digest may differ only after the original 82-tensor/source-binding reviewer actually reruns. Malformed hashes, altered labels, new claims, new arms, changed and rehashed scores, forged future windows and wrong origin fail closed.

- 82/82 saved tensor files verified; 32 exposed calibration cases; 12 candidate arms.
- 186/186 combined V14–V19 local tests passed both normally and with Python -O, zero skips with the original archived material staged.
- Two independent local Linux child processes reproduced the same sanitized V19 result SHA b3c1d75e286c9d9cd41ade49f4719e4cf4434f51d7cbeccc22735f380bf02ed4.
- Linux whole-child wait4 peak RSS 105572 and 105624 KiB; user CPU 1.464663 s and 1.976076 s. These are standalone **read-only replay costs**, not full Encoder + training + inference, GPU, p99, production WAL, FinalUse or the user's target host.

The V19 decision is REPLAY_NUMERICALLY_EQUIVALENT_NO_FUTURE_ADMISSION. It reports zero signed future windows, zero independent future source roots, no source-host signature or independent evaluator, and both scientific/production permissions false.

## Mandatory remaining gates

Actual independent post-freeze source families, authentic separate publisher and evaluator custody, independent old-task retention and negative-transfer, frozen deployed no-change, complete physical costs including future p95/p99, 64/256/1024/4096 Cell target-host RSS/CPU/GPU/recovery, original owner signed CAS/CNS and independent FinalUse are **not** qualified.

**Retain no-change; do not split/promote Cells or merge research into main.** The exact-new-HEAD hosted source, base-merge and global CI checks must produce their own terminal receipts, not inherit earlier runs.
