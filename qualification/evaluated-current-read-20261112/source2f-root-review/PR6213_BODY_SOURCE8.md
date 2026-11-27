## Problem and current immutable source

The original evaluated read path repeats owner validation within one bounded observation. Its original source53 CI now identifies concrete failures: four command-fixture stack aborts, two stale CURRENT RPC expectations, an aggregate model regression timeout, owner-unavailable readbacks, and a Windows recovery-path assertion mismatch.

This draft contains source repairs and preserves the original failures. It remains **HOLD** pending original CI at the new immutable source.

- Head: `2f12492547c382156eb0dd15a4d3cf1018e37523`
- Tree: `9ebc2298ef710b1c090eed85eb402da7a9a61a11`
- Previous published source: `53b3227a8dff5af9e39ecef6356cfce702d80b1c`
- Merge parents: `82d36ec843a07936f03d69ec73e068e15e71212a` and `1cb195e590f7f5038a38625a943f259badea489a`
- Published with an expected-head lease at 2026-11-12 21:16:54 UTC; actual commit, tree and ref read back.
- Exact full changed-subtree comparison: **8 paths, 2 production and 6 test paths; 7 new Rust methods**. No other leaf changed relative to source53.
- No execution result is transferred from source53 to this head. New automatic CI is pending.

## Changes in this follow-up

1. **Batch cost validation.** The private nonempty merge path validates existing history once, then applies the original entry validation, replay/conflict checks, capacity checks and checked arithmetic in the original order. Empty input retains the old no-iteration behavior. Accepted-prefix semantics and journal durability/CAS boundaries remain unchanged. Four differential and real journal/cold-reopen tests are added; all 27 old methods remain unchanged. The static existing-history validation count decreases from 8,191,128 to 256,032 for the audited boundary sequence. This is a static work count, not measured elapsed-time improvement.

2. **Owned command test fixtures.** Existing large fixtures, commands and returned values are boxed, and consuming cleanup retains ownership and order. No additional thread, owner or reopen is introduced. All eight command test bodies remain byte-identical. This is a candidate repair for the observed stack aborts; its actual native result is pending.

3. **Exact CURRENT RPC expectation.** One shared Selection helper now expects the observed fourth original task CURRENT RPC before the original withdrawn T/B refusal. The subsequent local fenced read does not send a fifth RPC. The T/B counts, two S frames and refusal assertions remain unchanged.

4. **Independent model regression cases.** Four already independent fixture groups are now four methods: page/final-ACK faults, Missing/cold Missing, Pending/cold Pending, and renewal/expiry. All operations, assertions, owner reads and consuming cleanup remain. All four methods must pass to cover the old combined method. Each method receives the runner's existing limit; their aggregate wall-time allowance is therefore different from the old single-method allowance. No speedup or diagnosed internal timeout phase is claimed.

5. **Windows canonical recovery path.** The expected database path uses the same existing `AbsolutePathBuf` normalization as the actual runtime error. The strict path comparison, real corrupt database, error type and error propagation are preserved. No production filesystem or ACL behavior changes.

6. **Upstream caller inventory integration.** The upstream seven added callers and all 40 entries of that boundary were already byte-identical in ours. All seven actual product files and eight call sites were independently verified. The merge retains the prepared source tree and its one exact active CALLERS pin. No caller or source guard is removed.

## Original source53 validation — historical, not transferred

Original runs: [daemon native and caller](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43297579480), [shared Cell framework](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43297579399), [Windows private state](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43297579365), [blocking CI](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43297579660).

| Lane | Actual source53 result |
|---|---|
| Source closure | 506/506 passed |
| Learning-owner parser | 16/16 passed |
| Ordinary daemon native | 1,783 unique methods: 1,768 pass, 10 fail, 4 SIGABRT, 1 timeout; 100 filtered, 0 retries. Root/fix/format stages were not reached. |
| Shared Cell framework | 1,447 unique methods: 1,432 pass and the same 15 nonpassing identities. Original TRY 1/TRY 2 attempts are retained. Its overlapping methods are not added to the daemon denominator. |
| Windows private state | Whole job passed; exact selected LEARN collection 36/36, 597 filtered, zero retries and exact log/JUnit coverage. |
| Rustfmt / GNU Clippy | Both original jobs passed. The blocking synthetic checkout had source53's exact tree. |
| GNU / musl Bazel tests | Both failed. Printed cached/shard records are not a complete fresh method denominator. |
| Mac Intel | The original hepta-neuron target passed in 252.6 s before this cost candidate existed; other targets failed. Success method stdout was not printed. |
| Windows matrix | Separate actual TUI path mismatch and legacy isolation refusals remain recorded. |
| Full caller proof | Source53 remains under observation. The separate source84 full proof passed; its result is not transferred. |
| Branch fence | Observation-only audit; protection was unavailable. It is not enforced branch-protection PASS. |

Complete originals and source53 evidence were published to [evidence draft #6198](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6198) at `37ceb8104df4002e2fa582edef64207ed6f72db0`. Additional follow-up review and execution evidence will be reconciled there.

## Preserved read semantics and open blockers

Combined Selection/NextUse retains 6/9 semantic CURRENT slots with first and final physical reads, the same actual Cell/Task allocations, the fixed Purpose, actual Source publication pair, and independent tail checks. Public Individual paths retain physical reads. The original bounded Training proof and owner/lane guards remain.

The conditional production budget remains open: the same Version-held evaluator Arc in **Bound B** requires `3Q = 210 + 30R` original Trainer reads against its 128-request limit. `R` counts completed full six-cut Root readbacks. The stronger `244 + 36R` additionally requires Root and Version B to share the actual host. This static topology does not describe the default Individual/Fixture path.

The actual source53 cold Version failure separately printed `positive-generator completed=128` with two independent original peers. This follow-up does not claim that exhaustion is fixed. A narrower B Readback candidate is under independent review.

The Windows legacy admission function currently rejects before token, ACL or launch work. Changing TempDir ACLs cannot repair that contract mismatch. No sandbox bypass, capability substitution or skipped positive capability test is introduced here.

## Qualification status

All **12 complete scientific and authority gates remain OPEN**. `owner_decision = null`; `all_blockers_closed = false`. The PR remains Draft and unmerged. No manual Bazel execution, research actor redispatch, deployment or default adoption was performed.
