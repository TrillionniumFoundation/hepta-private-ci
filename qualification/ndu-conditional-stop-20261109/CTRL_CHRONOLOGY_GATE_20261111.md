# CTRL chronology and isolated-launch reconciliation — 2026-11-11

**Decision:** DRAFT / HOLD_NO_GO / NoUpdate. Research-only consistency checks; no policy, actor, model, evaluator, private historical source, output score, or Owner authority is changed.

Parent: [#5958](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5958) at exact `4a930a5af12ce7c2a20d868c11f05cc8e9a851f9` (itself stacked on #5943/#5614). The separate receipt-checker branch #5956 is **not** part of this base.

## Defects reproduced in the exact parent Python source

- `content_identity_report` paired actor steps with positional delivery snapshots without independently verifying observation order. When writes carried identical text/bytes, reversing two trajectory rows, inserting an extra actor observation, or moving actor-ready behind observations still yielded positive complete receipts.
- Historical `content_audit` considered `exit_code=0` and `enforced_before_actor_exec=true` sufficient to mark the launch completed, even when `callback_error`, `protocol_error`, or `limit_reason` was non-null. The native report already failed closed on those flags.

Six **manufactured adversarial** checks were red before the code fix (17 unittest methods run, six failed cases); the other tests passed. These are checker counterexamples, **not** evidence that the six original `WRITE_TEXT` scores resulted from these bugs.

## Patch

- Require exact actor-observation emission order, contiguous zero-based step IDs, same-case identity, and one readiness message only before observations; forbid extra/missing actor observations.
- Reuse a single strict completed-and-isolated launch predicate in the historical audit for both row-level `selected_used` evidence and episode-level `launch_completed`.
- Add regression tests for six counterexamples; retain original score values, scoring semantics and snapshot ordinal scoring repair in #5958.

## Local red/green verification (HeptaRuntime ai395)

- An isolated local scripts-copy fixture was prepared from an existing test source; **the four modified/source-under-test files were overlaid from GitHub at the pinned parent**. This is a scoped Python test, not an attestation of a complete repository checkout.
- Red: 17 tests, six expected failing adversarial cases (original source + extended tests).
- Green: `python3 -m compileall` for the two modules and `PYTHONPATH=scripts python3 -m unittest ndu_real_runtime.test_content_identity ndu_real_runtime.test_content_audit -v`; **17/17 tests passed** with zero errors/skips on ai395.
- Retained durable process IDs: red `1a1ca163503-2564-475`, green `1a1ca190432-2564-48b`. The intermediate broader local command named an unavailable native test module and does not constitute a native integration result.

| Pinned tested file | SHA256 |
| --- | --- |
| `content_identity.py` | `40f4898adf6222330fbff1da9466b12709ed93e70662ed27ecca0ff249e2a1a1` |
| `test_content_identity.py` | `89fe106052e23b049d464d4eb84f661f4f062600ea49793834247b1dfbb07436` |
| `content_audit.py` | `3202b61885e9a77327db759407b31371d91b18c9123caead247b607314096437` |
| `test_content_audit.py` | `23ed7949604f10d23d1721818439aba5f43d033c18d8d3f29aecb284bf94d8c1` |

## Remaining gates

Independent GitHub exact-head CI and full original-owner native integration must be evaluated separately. The 6/6 historical zero-score root cause remains **UNKNOWN** without actual source-owner selection→wire→delivery→evaluator receipts for each original episode. No independent prospective B, real outcome/implementation-probability calibration, matched light baseline, total cost gain or production admission is established.

## Historical original-owner boundary update (source already reviewed separately)

An **earlier** read-only analysis on #5610 recovered the original frozen #5450 native artifacts: [readback report](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/fa40154c1de35af750910f117ad6a0c7aceda1be/qualification/ctrl-metacontrol-20261109/ORIGINAL_NATIVE_READBACK_20261110.md) and [digest-only six-case data](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/fa40154c1de35af750910f117ad6a0c7aceda1be/qualification/ctrl-metacontrol-20261109/ORIGINAL_NATIVE_READBACK_20261110.json). This is **not** new work in this PR, nor an independent operator-key attestation.

Across six original diagnostic WRITE_TEXT runs, a correct reference-matching candidate was present (6/6), but the ACTUAL actor-emitted candidate was a nonmatching alternative (6/6). The actor wire, post-action delivery and scorer receipts were mutually consistent (6/6). Thus the **first observable semantic mismatch was the emitted actor payload**, not the delivery or canonical scoring. Historical internal selected-index receipts were absent (0/6), and the model-ranking/selection cause remains **UNKNOWN**. The original READ-only trajectories stopped without an answer suffix and cannot support a READ value gain.

The synthetic chronology counterexamples fixed here are distinct from, and do **not** retroactively explain, these six historical zero scores. This qualification still remains HOLD_NO_GO.
