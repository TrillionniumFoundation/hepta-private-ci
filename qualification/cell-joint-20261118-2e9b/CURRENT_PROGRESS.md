# E1–E6 continuation: completed executions and open qualification

Observed 2026-11-18T12:54:32.000-05:00 (America/New_York).

The prospective `SOURCE_FREEZE.json` remains unchanged. The original joint
engineering execution is still `e52c4f67cb58a65409256f7be263cfb49ac22557`:
216 CPU tests and 221 source/fixture byte checks. Later experiments retain their
own source, weights, runtime, protocol and costs. They are not combined into
a claim that one complete numerical/native candidate has passed.

[CURRENT_PROGRESS.json](CURRENT_PROGRESS.json) records exact identities,
original hashes, budgets, failures and qualification flags. This update is
evidence only; it changes no production implementation or historical score.

## Results now available

| Experiment | Actual execution | Result and limit |
| --- | --- | --- |
| E1 trajectory value | 96 model calls; frozen, retrieval, answer SFT, trajectory SFT | All four arms score 0/6 on external B. Trajectory SFT selects 5/6 on A but finishes 2/6 and regresses all three initial successes. Generalizable improvement is not established. |
| E2 current student, principal run | Two actual 64-update fits and 108 model/verifier calls on A, old B and B2 | Credit improves A last-answer retention to 5/6, but the original advancement criterion remains false. Research **NoUpdate** is retained. |
| E2 common historical prefix | 33 new calls, three frozen models, identical six failure and five success prefixes | Parent/all/credit recover 2/6, 5/6, 5/6 and preserve 2/5, 2/5, 5/5. The successful updated answers are identical across the five recoverable failures; credit also repeats the same answer across each task's two histories. This is evidence of retaining seen A answers, not general feedback understanding. |
| E3 genuinely different teacher | 12 calls from the original authorized local teacher with byte-pinned model/runtime | Teacher 2 selects 1/6, teacher 1 selects 0/6; union equals the stronger teacher. No mutual complementarity is established. Physical compute is not matched. |
| E4 earlier interaction | 120 main calls plus four calibration calls | All main single/full-circuit arms score 0/6. Only the no-answer ablation scores 1/6. No Circuit necessity is established. |
| E4 parent/credit interaction | 108 main calls, four calibration calls, 118 total verifier calls, all nine arms | PP, CC, PC and CP each select 5/6. Collaboration does not exceed either strong two-call control or attain the separate-arm 6/6 oracle union. Three retrieval arms each score 0/6. |
| E5 real source materials | Four upstream repair lineages, eight before/after test children, 228 original test cases | Before: 99/114 pass and 15 fail. After: 114/114 pass. This establishes four reproducible repair materials, **zero authenticated users**, zero new training updates and no measured growth curve. |
| E6 native owner | Actual v11 and v13 complete NoUpdate attempts; original failures retained | v11's dedicated response capacity passes nine related native regressions. v13 admits a 19,118-byte Task reply, then refuses shared-lane request 65 at maximum 64. Complete native NoUpdate and adoption remain unqualified. |

## E2: retain both the negative decision and the mechanism evidence

[Principal E2 originals and policy receipts](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/2bc71d97995229122769d3ccee66e342e2edd100/qualification/cell-current-policy-credit-20261118)
retain the actual parent, all-observed and verified-credit adapters. Every fit
uses 64 updates, 103,815 input tokens, 393,216 padded tokens, 16,094 materialized
head positions and 192 forward/backward passes. Supervised positions differ:
16,094 versus 9,780; the zero-masked positions still incur computation.

| Panel and model | First | Last | Selected | Recovery | Regression |
| --- | ---: | ---: | ---: | ---: | ---: |
| A parent | 3/6 | 2/6 | 5/6 | 2 | 3 |
| A all observed | 3/6 | 2/6 | 5/6 | 2 | 3 |
| A credit | 4/6 | 5/6 | 5/6 | 1 | 0 |
| B2 parent | 4/6 | 2/6 | 5/6 | 1 | 3 |
| B2 all observed | 3/6 | 3/6 | 4/6 | 1 | 1 |
| B2 credit | 4/6 | 3/6 | 5/6 | 1 | 2 |

Old B remains zero for every arm. The A MSE case changes from fail→pass to
pass→pass, so failure opportunities decrease from three to two. Raw recovery
counts alone do not measure a decline in recovery ability. Neither this
interpretation nor the later diagnostic changes the original NoUpdate rule.

[The completed common-prefix run](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/2b9cd0fa5383aa4657521a1c623e6b67e9b83bfa/qualification/cell-e2-fixed-prefix-20261118)
holds each request identical across all three models. Root independently
recounted all 33 records and verified the request pairing. It uses 17,484 input
and 2,941 output tokens, 26 business executions, seven format rejections and
117 observed subject calls. The three disjoint model stages total
317.708056750 seconds wall and 318.477409 seconds child CPU; nested verifier or
generation timings are not added again. All 201 originals plus the index are
retained. This exposed-A mechanism run has no new training or independent
confirmation.

## E4: the matched parent/credit comparison is complete

[All nine arms, raw interactions, two adapters and original policy checks](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/8f1f6f1930ef4ed60dd95d6fd3fe2be7502ad23f/qualification/cell-parent-credit-circuit-20261118)
remain bound to execution source `18de34630fe4b81efaf875c073272b062aeea211`.

| Arm | First | Last | Selected | Recovery | Regression |
| --- | ---: | ---: | ---: | ---: | ---: |
| PP | 4/6 | 2/6 | 5/6 | 1 | 3 |
| CC | 4/6 | 3/6 | 5/6 | 1 | 2 |
| PC | 4/6 | 3/6 | 5/6 | 1 | 2 |
| CP | 4/6 | 3/6 | 5/6 | 1 | 2 |
| PC without answer | 4/6 | 4/6 | 4/6 | 0 | 0 |
| PC without feedback | 4/6 | 3/6 | 5/6 | 1 | 2 |
| PP with retrieval | 0/6 | 0/6 | 0/6 | 0 | 0 |
| CC with retrieval | 0/6 | 0/6 | 0/6 | 0 | 0 |
| PC with retrieval | 0/6 | 0/6 | 0/6 | 0 | 0 |

Main execution uses 59,186 input/5,181 output tokens, 87 business executions,
21 format rejections and 233 subject calls. Calibration adds four model calls,
1,128 input/164 output tokens and four verifier calls; six A-reference checks
bring the total to **112 model calls and 118 verifier calls**. The owner reports
541.191474373 seconds wall. Pool initialization and the per-call generation and
verifier windows are nested within that owner.

An independent per-call audit binds the original request, answer, token IDs,
loaded parameters, native observations, relay messages, order and costs.
Calibration and main execution deliberately retain their different predeclared
verifier source hashes. Root separately verified the published readout bytes
and recomputed the nine-arm totals. The first zero-call deployment refusal and
both failed audit attempts remain in the archive; no model or verifier was
rerun to repair bookkeeping.

The complete archive contains 1,956 originals plus its index, is 5,582,960 bytes,
and has SHA256
`0cda7c982d5fc1e19526bf755d92bedc8fa07ec1bf6a7c51a4bf097234034d41`.
B2 is already exposed development material. No adaptive route was selected from
its task outcomes, no new arm was added after the results, and the original
E2 decision is unchanged.

## E5: four reproducible upstream repair materials

[Source, license, native replay, material records and growth protocol](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/b20ece30e1e8884c6b892ba9d0ad06d012ea2f6e/qualification/cell-upstream-training-sources-20261118)
retain 83 distinct original Git blobs and four MIT notices.

| Upstream repair | Original test cases per revision | Before | After |
| --- | ---: | --- | --- |
| python-attrs/attrs #1593 | 5 | 4 pass, 1 fail | 5 pass |
| Textualize/rich #4006 | 24 | 14 pass, 10 fail | 24 pass |
| tox-dev/platformdirs #721 | 29 | 28 pass, 1 fail | 29 pass |
| python-humanize/humanize #479 | 56 | 53 pass, 3 fail | 56 pass |

Eight Rich cases hit the same original three-second per-case timeout before
the repair; none does afterward. There is no outer child timeout or collection
error. Selected original parameterized functions run unchanged on both
revisions. Disabled repository-wide plugins and generated version-module stubs
are explicitly documented; no behavior function is replaced.

These are four repair lineages, not 114 independent tasks and not four users.
Historical maintainer fixes are not original agent trajectories. Statistical
source independence and pretraining overlap remain unestablished.

The existing E5 ordering is retained: the one-source point is Rich by lexical
source ID order. Planned 1/4-source update counts are 32/32 at fixed total
budget and 32/128 at fixed per-source budget. Actual updates remain zero.
The 16- and 64-source points still lack 12 and 60 sources. Prepared numeric
features, class labels and coding growth results are not invented from source
identities.

## Next actual student and teacher collection

[Draft #6717](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6717) published complete source/protocol
`dfc4e24ba68fa983f4dbdaca1de6c2d54a4df950` before inference. Desktop job
`1a1efba0ff6-ffbe-5bf` was launched for eight parent and eight credit calls under
the original worker lock, with at most eight additional calls from the separately
verified existing local teacher. The student owner has reported completion;
its final original readout is being retained separately in #6717 and is not
incorporated into this snapshot's results. There are **zero new training updates**.

The restricted JSON patch format binds the original paths and bytes. Actual
candidate code runs in a network-isolated bwrap process; tests and dependencies
are read-only and a host canary is inaccessible. The same sandbox has already
reproduced all 228 original before/after test cases. Initial student prompt
lengths are 473, 1,303, 1,770 and 1,757 tokens; complete reference patches require
113, 1,194, 374 and 99 tokens.

The new policy therefore freezes a uniform 8,192-token input limit and
2,048-token output limit, checked before each call against the student's actual
32,768-token context. It does not masquerade as the earlier 384-token policy.
Complete second-round history must fit without truncation. The teacher's first
service preflight refusal remains recorded; its later natural return was
verified without restarting or reconfiguring it. Its 131,072-token slot context
has passed the native template/codec preflight. The prospective teacher freeze
was published at `9cfa4995c5d08aa0af00cdda6ef1fa67e49b6d1e` before the first
four teacher generations in job `1a1efc81fab-ffbe-5e5`. That freeze contains
zero new model calls and does not establish matched physical computation.

The first and second answers, real sandbox feedback, failures and all costs
must be retained. This is new A material collection; independent confirmation,
a new learning gain, and native adoption are not claimed.

## E6: exact native failures, with an observed request-budget cause

[The original owner history](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/3299c1d3318ff157f4948dee89b7939ef67b515c/docs/cell-experiments/e6-native-owner-20261118)
preserves v8–v13 and their distinct source commits.

- v11 derives a **Task-specific 28,933-byte bound** from the unchanged
  12,288-byte ledger component, 16,384-byte publication component and a
  261-byte canonical envelope. Other operations remain at 16,384 bytes;
  authority bootstrap remains 65,536 bytes and the lane maximum remains 64.
  Nine related native framing/identity controls pass. Its complete NoUpdate
  still fails after a real 19,114-byte Task response.
- v12's additional diagnostics fail helper compilation with an actual
  Read/Write `by_ref` ambiguity. No business test or old executable is
  substituted for that missing build.
- v13 fixes the diagnostic trait scope and executes the original complete
  NoUpdate. The original XML records a **19,118-byte Task response** under
  28,933, followed by **request_id=65, maximum=64** at
  `historical_client.read_limit`, before the next Task action. The case fails
  after 68.181 seconds; 15,558 source files remain identical and cleanup passes.
  This directly confirms the shared-lane limit failure that was only a
  hypothesis after v11.

[The read-budget review](NATIVE_READ_BUDGET_REVIEW.md) identifies two narrow
existing synchronous scopes for possible reuse. It also identifies a real
witness initialization write between checks, which prevents blindly combining
all validations. This is static review, not an executed repair or proof that
64 total requests suffice.

The original executor retains its active source, target and owner lock.
Its next work reconciles exact static caller/QA markers; no subsequent business
success is claimed here. Complete native NoUpdate, actual adoption, new C,
a fresh D after cold recovery, FinalUse, independent-controller authentication
and settlement remain open. Recovering the old retained C is not a new D.
The coordinator's default independent `BLOCKED` remains an honest result.

## Chain: the original stronger window still fails

[Draft #961's complete prior F0 evidence](https://github.com/TrillionniumFoundation/Trillionnium-Chain/tree/cb04bbd5d29f839980f5c90bfcda621f9a6a490c/docs/development/evidence/chain-executed-deltas-20261118-2e9b)
records run 44335832525 on source `e6af21fd47347ba900ef87842447ed6fe227a6f0`:

- Original 30-second business phases: **2/6**, comprising baseline 2/3 and
  ROOT 0/3. Original four-second SLO: **0/6**.
- All 42 planned packet exposures are retained: 28 timely ACKs and 14 not
  attempted. ACK is not business confirmation. All original services are
  observed empty.
- All 443 manifest files, 12 independent readers and six resource boundaries
  were verified. The native process exits with the original business failure.
- Provider timing reports zero in its billable field and 2,164,000 ms run
  duration. Neither is a physical-cost measurement; the run duration includes
  queueing and is not CPU time.

[The next candidate, Draft #962](https://github.com/TrillionniumFoundation/Trillionnium-Chain/pull/962),
is frozen at `1380eaae3c902b3e17d5e5a7d73bf242b0366562`. It can reuse a complete
parent account graph only around its own proved passive metadata INSERT.
The old scope is never re-enabled. Extra attempted writes, different owners,
schema changes, triggers, and extra metadata indexes retain the original
reader/error paths. The actual parsed metadata index is checked as the original
primary-key BINARY/rowid index; ordinary, expression, partial and NOCASE extra
indexes all take the full-reader path.

Its 179 component tests, two existing ignores, strict Clippy and all 2,617
original source pins are retained. They do not prove the pressure window.
The unique original [F0 run 44356270247](https://github.com/TrillionniumFoundation/Trillionnium-Chain/actions/runs/44356270247)
completed on runner 1000189688 / job 134985105101 with all seven preparation
controls passing and native exit 101. The original 30-second business gate
scores **1/6** (baseline 1/3, ROOT 0/3); the original four-second gate remains
**0/6**. The first confirmation arrives 24.507888471 seconds from its planned
start. All 42 packet exposures remain in the denominator and owned services
are observed empty. [The exact independent readback](chain-graph-f0/preliminary-independent-readback.json)
retains all six planned rounds and the original two gate failures.

The baseline performs eight History imports, 82,046 Host checkpoints,
4.543810044 seconds nested Host CPU and 5.425864517 seconds caller CPU. The
ROOT phase performs zero History calls/imports while its whole public phase
still consumes 8.691669137 CPU seconds. Its zero import CPU is not evidence
of cheap service. Controller cgroup CPU deltas and lifetime memory peaks
remain separate from public-process and nested Host costs. Different runners
and completed work prevent attributing the changed timing to this patch.
The original archive is 17,509,272 bytes, SHA256
`ba7317fdbc7da70965c277323ca0a4321ab5692945322bc906c086b92d6bc872`.
Full physical costs and the original service target remain open.

The older 974 x64/ARM successes remain attached to their original executions.
A [separate published same-Rust follow-up](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/cf53f57d12af8fe4dc4d0273cfac630e999155a2/docs/development/evidence/chain-exact-body-delay-20261118/ci-e305-followup/README.md)
also prevents claiming robust closure of the smaller window: E305's original
same-packet head scores 0/1 while its same-tree prospective merge scores 1/1;
both fresh-challenge cells score 0/1. All four mixed-service cells fail the
original two-second maximum-gap predicate with the complete quiet tail retained,
despite all scheduled honest probes and mutations succeeding. These remain
separate experimental scopes; neither identical Rust nor identical trees
transfers a pass between executions. No failure probability or unique timing
cause is inferred from one execution per cell.

## CI and the joint engineering candidate

[Draft #6713](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6713) changes only the blob-policy Fence pin to the
official v0.13.1 commit. The actual hosted job 134942886696 passes setup,
all seven original policy tests, the real changed-blob check, clean-worktree
check and post-Fence health evidence. Audit mode, permissions and the global
512,000-byte limit are unchanged. This closes that specific startup failure,
not all required CI.

The E2, new E4 and E5 archives now have exact SHA256-plus-path entries under the
repository's existing asset policy. Each has seven original policy tests and
its actual base-to-candidate changed-blob check passing. Archives remain whole;
changed bytes lose the exception. Original execution refs and research results
are unchanged.

[Draft #6719](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6719) freezes the combined dependency/runtime source
at `2b3642214ba5ff4aaac27de13322a354a69507e7`; evidence head is
`7fc46c193a9ff8726e43fca2982d9b8f455e3dac`.
It combines the exact RMCP/SQLite proposals, the two Mac fixtures and the
verified Fence pin, with 75 input hashes checked in an independent clean
worktree. The actual canonical Bazel lock update/check and locked full Cargo
metadata all pass on one graph: RMCP 3.9.0, rusqlite 0.43.0, one bundled
libsqlite3-sys 0.40.0 link, no sqlcipher, and bindgen's syn edge at 2.0.119.

Original `just fmt` and the authored Rust diff checks pass. The full baseline
diff check's three original upstream documentation trailing-space warnings
remain recorded with exit 2 and exact upstream bytes. Chrono 0.4.45 still
appears in the 1,523-package graph: 121 roots reach it, including 28 direct and
93 indirect-only roots. Required-zero still exits 2. New exact-head consumer
qualification has started; prior proposal tests are not borrowed.

Mac preparation now verifies all 11,217 materialized files against frozen
`9aaac03f...`. The first original 11-case test command executes **zero cases**
because the offline index lacks sqlx-sqlite 0.9.0. Source bytes remain identical.
Locked dependency acquisition has now completed in 681.282 seconds with the
same lock/source. The second owner then spent 308.221291292 seconds in the
original test command but executed **zero cases**: compilation could not read
the original tracked `docs/modules/MODULES.json` outside the previously
materialized source subset. The original 11,217-file inventory is unchanged;
it did not cover this external compile input. [The second original result](mac-native-second/RESULT.json)
and [exact diagnostic](mac-native-second/original-macos-fixtures.stderr) are
retained. The owning agent is restoring that fixed-source Git blob and
recording the expanded input inventory before resuming the same eleven cases.
A separate clean joint checkout is prepared. All original timeout/cache/source
failures remain retained. Actual Mac regression success is still pending. Windows's
original positive business requirement and dependency-policy qualification
remain open; no assertion, guard or security mode was changed to manufacture
a pass.

## Prospective cost instrumentation and qualification

[The original capability observation](cost-counter-capability/RESULT.json)
records that existing authorized read-only sudo can read both CPU package
energy counters. NVML's cumulative GPU energy operation returns
`Not Supported`. The new student run samples the CPU counters every 20 seconds.
Those are whole-host CPU windows, including concurrent activity; they are not
per-model net energy. No past energy is backfilled, power limits are not
measurements, and GPU/network/storage/provider/monetary gaps are not zero.

All whole-joint numerical/native, independent-learning-gain, Circuit-necessity,
native-adoption, complete-NoUpdate, fresh-C/cold-fresh-D, FinalUse, settlement,
production and complete-system-cost flags remain false. False means
**not established by this evidence**, not impossibility. Continue the actual
running jobs, preserve their original results and costs, and repair the next
specific failed boundary without changing the original business target.
