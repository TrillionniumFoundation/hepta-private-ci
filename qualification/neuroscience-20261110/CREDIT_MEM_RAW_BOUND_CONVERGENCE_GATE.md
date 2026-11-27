# Frozen credit raw-budget × causal MEM replay convergence — HOLD_NO_GO

Date: 2026-11-12 UTC. Scope: **shadow reference only**, `DENY_ALL`, `HOLD_NO_GO`.

## Exact sources and separate ownership

- First parent: [#6026](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6026), commit `a4abafbcb89053bda9a8300adab13ed8a91f9456`, tree `93e7305737d8372fb06958e494ed6972f5e338fb`. Preserves [#6024](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6024) frozen MEM prefix, [#5966](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5966) per-kind rotation, and prior time/clock fences.
- Second parent: [#6025](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6025), commit `9a5ef60be0076c5e9de97e3a396e94ebe39454da`, tree `bb08f1a5fea261d03cd55af6271d7ceadc6deed2`. Preserves raw 65,536 feedback scan bound and four original negative/positive tests.
- Independently maintained Q24 owner/Agentd stacks remain untouched. Neither parent grants production authority.
- New combined `study.py` is base #6026 + the exact #6025 resource refusal, with no changes to MEM selection semantics, as verified against the supplied source/test identities.

## Actual bounded execution on HeptaRuntime ai395

Working files came from original locally retained #6026 `study.py` Git blob `7def749e792bb98d25b88214b62da321eff476d5` and #6025's original `test_frozen_credit_raw_budget.py`. A separate isolated Python sandbox was used because a partial Git clone lacked unrelated blobs; it was not used to claim that a full repository merge or production build succeeded.

A new `test_credit_mem_budget_union.py` includes two cross-mechanism tests: (1) 65,537 future feedback records refuse before cutoff filtering while 65,536 remain causally withheld, and (2) frozen credit is invariant under post-cutoff feedback while frozen seeded MEM retrieval ignores a malformed future suffix and honors a visible logical deletion across 16 *declared* seeds.

- RED, unpatched #6026 reference: **86 tests / 3 intended failures**, including the original raw-cap regression. See `CREDIT_MEM_UNION_RED.log`.
- GREEN, combined reference: **86/86 passed**, `exit 0`, followed by `py_compile` success. See `CREDIT_MEM_UNION_GREEN.log`.
- Independently timed repeat: **86/86 passed**, wall **0.06 s**, user CPU **0.06 s**, system CPU **0.00 s**, max RSS **22,780 KiB**, command exit **0**. See `CREDIT_MEM_UNION_RESOURCE_EXECUTION.log`. This is a tiny Python contract-test process, **not** full model/Agentd/CI cost.
- Combined `study.py` SHA-256: `0f41e80914f41787083f84f23b4af5897ffcfb86564a6c0755d03afa2d81dd4d`.
- New cross-test SHA-256: `2d7731b43833921306dac8c2a6f31f42b2ee7e224922e1e703d200c83600c892`.
- Original raw-budget test SHA-256: `507b945e504937c2c297f6913145abc5e46df680017a506c271b12674e263a0c`.

## Qualification limits / remain HOLD

These are synthetic reference-level tests with self-declared sequences, source hashes and randomization seeds. They are not owner-attested data, real distributed memory deletion, learned-model effects, independent evaluator B, a successful Adopt/NoUpdate/rollback path, next-task C, cold restart, NDU 2×2 gain or production qualification. Full blocking CI, dependency and Blob policy gates must pass independently. The exact GitHub HEAD/tree and hosted CI outcome must be read back after publishing and cannot be inferred from these local tests.
