# MEM-3: strong retrieval wins this composition mechanism pilot

**Scientific qualification: HOLD. Product/model adoption: NoUpdate.**

The one preregistered campaign completed all **60 trials and 3,840 terminal
attempts**, after the real candidate-retention campaign had completed. Exact
retrieval plus relation composition and BM25 plus the same composition each
achieved **1,280/1,280 joint-correct outcomes**. The real Rust associative reader
plus that composer achieved **1,210/1,280 (94.53%)**. On tasks with an answer,
retrieval achieved **897/897**, and native association achieved **830/897
(92.53%)**. There is no unique neural benefit in this pilot; keep strong retrieval
in the product critical path.

The continuous cross-version question remains **open and blocked by the current
native interface**. All ten next-owner-cut predict/update requests were rejected
with `SnapshotMismatch`, and the independently witnessed checkpoints were
unchanged. The valid performance comparison below uses a separately paid
reset/rebuild at every owner cut. It does not establish continual memory or
unlearning.

## Registration, execution and evidence

The [protocol](PROTOCOL.md), [registration](registration.json), and exact
[fixture](fixture.json) were frozen before execution. There were five fixed
seeds (0 through 4), four ordered fact stages, and three readers; each trial had
the same 64 planned task IDs. No task, seed or failed observation was removed,
and no registered campaign was rerun or tuned after observing results.

- Campaign: `mem3-campaign-v1`, 2026-11-09 **12:43:10.956037 to
  12:43:19.016761 UTC**, exit 0, **60 completed / 0 failed / 0 not started**.
- Terminal roster: **3,840 completed / 0 failed / 0 unknown / 0 not started**.
  Abstention is an observed answer outcome, separate from an unknown execution
  outcome. There are two unknown-input tasks per trial, retained and scored.
- Measured campaign wall time: **8.060734 s**; Linux waited-child CPU usage:
  **6.891198 s**. Energy and provider charges were not measured and remain null.
- The prerequisite real candidate run was `run-002`, with **108/108 Completed**;
  its exact `RUN_RECEIPT.json` SHA-256 was
  `020ead824388c3ef994d72f65befd8479d8fe7369922171158e7aa7c514688c3`.
  Its separate preflight correction and earlier zero-actor failure are preserved
  in the candidate experiment's evidence, not counted as MEM-3 trials.
- Executed source was published at
  `1407c79571f0386304cc2718e0c3d26824672e1c`. The campaign manifest binds all five
  MEM-3 Python files and the reused MEM-1 native client/environment by actual
  file digest. Seven focused unit tests passed both normal Python and `-O`
  before final formatting. The format receipt verifies identical ASTs between
  tested and formatted code; the unit tests were not rerun after final format.
- The actual native ELF was the newly built MEM-2 source-projection binary,
  reused unchanged here: **23,616,504 bytes**, SHA-256
  `e8b95e5b88bfbbdd962812d800f2617daa924aa237dcdeba45b71697cad0713d`.
  Its source was pinned to `d13761500aba28634238ec23fb1d62eae5cf81ec` and built
  offline with Rust 1.96.0 in an isolated three-crate debug projection. This is
  not reuse of the historical MEM-1 binary and not a complete workspace build.
  [MEM-2 build/evidence](../memory-cell-mem2-coverage/RESULTS.md) supplies the
  source projection and dependency audit.
- Frozen fixture SHA-256:
  `36e8ec0047f3ec795a3d3828d9bdfa2d0f41063c4dbbccf3eeb9446e0c966a13`.
  The fixture bytes did not change during implementation, formatting or
  execution. Registration retains its original pre-format generator digest;
  executed-source digests are recorded separately.

[Machine-readable reconstruction](observations/reconstruction.json) and
[campaign receipt](observations/campaign-receipt.json) accompany the
[raw evidence archive](observations/raw-evidence.tar.xz). The
[archive manifest](observations/archive-manifest.json) records the exact archive
size, hash and member inventory. The archive includes every native command and
receipt, each raw task path, all planned rosters, initial native checkpoints,
transition diagnostics, tested and executed source snapshots, validation logs,
the frozen registration, and the first-candidate completion receipt. It excludes
the 23 MB ELF; its exact source/build identity is retained.

## What was compared

Each seed supplies sixteen primitive records: two functional relations A/B over
eight objects. The 16-dimensional fixed features and primitive labels come from
the existing MEM-1 `Owner(seed)`. All readers receive the same current records,
features, validity metadata and task programs. Composite terminal answers are
never training targets.

The exact comparator follows current primitive records and executes the full
relation program. The BM25 comparator ranks the complete small corpus, validates
the parsed node/relation key, and executes the same program. These are strong
retrieval-plus-composition baselines for this fixture; a terminal-answer-only
exact lookup would be a weaker and different comparator.

The native reader trains the unchanged Rust normalized-delta matrix for eight
shuffled passes over currently eligible primitives. Each next source comes from
that reader's own preceding prediction. Neither a retrieval result nor evaluator
truth can replace a native value. A common owner gate sees provenance/version,
revocation, dependency, expiry and constraint metadata without primitive values.
It can reject a path but cannot correct a label.

All three readers receive the explicit symbolic composition rule. This tests
whether associative primitive readout helps downstream new combinations. It does
not demonstrate that a neural system learned a relational operator. The corpus
is synthetic and small, with known source identities; this is not a semantic
search, LLM-RAG, adapter-learning or real user-task benchmark.
Perfect retrieval creates a ceiling in this fixture. The pilot can expose
associative-readout losses, but it cannot estimate a benefit under noisy queries,
ambiguous entity matching, incomplete relational indexing or larger workloads.

## Terminal outcomes and error decomposition

`joint correct` includes both a correct terminal label and a correct abstention
when current truth/constraints require abstention. The answerable-only column
prevents many correct refusals from hiding errors on tasks with an answer.

| Reader plus common composer | Joint correct / all tasks | Correct / answerable | Wrong assertions | Truth-ineligible terminal assertions |
| --- | ---: | ---: | ---: | ---: |
| Exact current-record retrieval | 1,280/1,280 (100%) | 897/897 (100%) | 0 | 0 |
| BM25 current-record retrieval | 1,280/1,280 (100%) | 897/897 (100%) | 0 | 0 |
| Native associative readout | 1,210/1,280 (94.53%) | 830/897 (92.53%) | 67 | 3 |

The native arm was **5.47 percentage points lower in joint correctness** and
**7.47 points lower on answerable tasks** than either strong retrieval arm.
Its 70 incorrect terminal outcomes comprise **64 incorrect labels on answerable
tasks, three false abstentions on answerable tasks, and three assertions on
tasks for which the independently reconstructed truth requires abstention**.
The three truth-ineligible assertions are a subset of the 67 wrong assertions.

Each arm made 897 terminal assertions, 343 gate/constraint abstentions, and 40
unknown-input abstentions. Those equal aggregate totals do not mean the same
tasks were answered: the native arm's three false abstentions and three invalid
assertions offset in the totals. Retrieval correctly abstained on all 383
unanswerable tasks; native readout did so on 380/383.

| Primitive/path metric | Exact | BM25 | Native |
| --- | ---: | ---: | ---: |
| Raw primitive predictions / retrieved values | 2,426 | 2,426 | 2,426 |
| Raw label errors, including later-blocked sources | 0 | 0 | 247 |
| Eligible raw-source predictions | 2,219 | 2,219 | 2,218 |
| Label errors on eligible raw sources | 0 | 0 | 78/2,218 (3.52%) |
| Actually used invalid sources | 0/2,219 | 0/2,219 | 0/2,218 |
| Actually used revoked sources | 0/2,219 | 0/2,219 | 0/2,218 |

The zero invalid/revoked-source-use counts are consequences of the shared
explicit gate. They are not learned neural authority and do not imply correct
terminal facts. For example, `seed-4-version-native/task-54` permits endpoints
0 through 3. Native readout correctly follows `A:6 → 0`, then predicts `B:0 → 3`
although the frozen current record says `B:0 → 7`. Both sources are current,
live and eligible, so the value-blind gate passes. The returned 3 satisfies the
predicted-path endpoint check, while full truth requires abstention. This case
and the other two invalid assertions remain in the raw evidence and primary
denominator.

## Stage, family and seed results

These stages are rebuilt states, not a continuously carried neural memory.

| Fact stage | Native joint correct | Native correct / answerable | Native eligible raw errors | Truth-ineligible assertions |
| --- | ---: | ---: | ---: | ---: |
| Base | 300/320 (93.75%) | 256/276 | 21/650 | 0 |
| Version replacement | 277/320 (86.56%) | 225/266 | 50/630 | 2 |
| Revocation + dependency invalidation | 313/320 (97.81%) | 188/194 | 7/499 | 1 |
| Expiry | 320/320 (100%) | 161/161 | 0/439 | 0 |

Both retrieval readers were jointly correct on 320/320 tasks at every stage and
correct on every answerable task. The expiry result uses a fresh rebuild with
fewer eligible primitives; it is not evidence of learned forgetting or recovery
of a previously carried state.

For the 960 new-composition tasks per arm, retrieval achieved **960/960 joint
correct and 814/814 answerable correct**; native achieved **900/960 joint correct
(93.75%) and 754/814 answerable correct**. The complete family breakdown,
including all constraint, version, revocation, dependency, expiry and unknown
tasks, is retained in the reconstruction JSON. All three invalid native terminal
assertions belong to the constraint family.

| Fixed seed | Native joint correct / 256 | Native correct / answerable | Native truth-ineligible assertions |
| --- | ---: | ---: | ---: |
| 0 | 217 (84.77%) | 147/184 | 2 |
| 1 | 248 (96.88%) | 182/190 | 0 |
| 2 | 245 (95.70%) | 156/167 | 0 |
| 3 | 252 (98.44%) | 183/187 | 0 |
| 4 | 248 (96.88%) | 162/169 | 1 |

Both retrieval arms achieved 256/256 joint correctness for every seed. These
five synthetic streams are not five independent pretrained-model training
runs. Their repeated primitives, tasks and stages are dependent; no significance
or broad generalization claim is made from the pooled task denominator.

## Work, bytes and timing

The following are totals over twenty state instances per arm (five seeds times
four cuts). Serialized storage totals add those instances; they are not peak
RSS, GPU memory or a continuously resident twenty-state store.

| Measured/recorded quantity | Exact | BM25 | Native |
| --- | ---: | ---: | ---: |
| Provided serialized information bytes | 66,557 | 66,557 | 66,557 |
| Shared value-blind metadata bytes | 33,130 | 33,130 | 33,130 |
| Stored reader payload/state bytes | 9,620 | 52,030 | 56,492 |
| Primitive retrieval calls | 2,426 | 2,426 | 0 |
| Retrieval candidates scored | 0 | 38,816 | 0 |
| Retrieved value/version payload bytes | 55,798 | 55,798 | 0 |
| Native training updates | 0 | 0 | 2,360 |
| Native predictions | 0 | 0 | 2,426 |
| Native replay payload bytes | 0 | 0 | 498,304 |
| Native protocol request bytes | 0 | 0 | 697,646 |
| Native kernel scalar multiplications | 0 | 0 | 1,292,288 |
| Teacher calls / bytes / multiplications | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |
| Observed trial wall time sum, seconds | 1.5951 | 1.8587 | 4.3250 |

Per-state stored payloads were 481 bytes for exact, 2,601–2,602 for BM25, and
2,818–2,836 for native state plus features/version sidecars. Shared metadata is
listed separately. The native arm's 4,846 protocol requests include creation,
checkpoints, training, prediction and the ten rejected transition diagnostics;
the implicit worker `quit` is outside the metered command protocol. Native IPC
wall time was 2.3020 s, included within native trial wall time, not an additional
cost to add to it. Likewise, arm trial times sit inside whole-campaign wall time.

Counts, serialized bytes, training support/target/order, kernel-reported work,
actual native scores and checkpoint digests were independently reconstructed
from fixture and raw evidence. Timing is observed client instrumentation and was
checked for validity, not recomputed from per-request timestamps. Arm order was
fixed and wall times include evidence logging/roster writes; these timings do not
establish a production latency ranking. They also omit full-process RSS, energy
and provider pricing. Retrieval was not given pointless rehearsal to equalize
its work with the neural arm. No full-cost benefit for native association was
established.

## Continuous-memory blocker and necessary next interface

All five base native states received a next-cut `predict` and `update`, yielding
**10/10 `SnapshotMismatch` rejections**. The before/after checkpoint bytes and
digests were identical. The independent reconstructor verifies the entire
command chronology and ties every diagnostic receipt to the actual failed
request; an empty diagnostic list or a different error cannot pass.

The existing Rust `predict` requires exact current-snapshot equality; `update`
first calls that check. `restore` binds checkpoint bytes to that snapshot, and
`reset` carries only predecessor identity while discarding numerical state.
There is no legal weight-preserving transition to a new owner cut. Reusing the
old generation number or changing only Python metadata would evade the owner
contract and is not a continuous-memory experiment.

The next continuous-memory experiment needs an owner-authenticated transition
contract with explicit model/encoder/scope invariants, current support-set
eligibility and invalidation handling, and auditable state continuity. Revocation
also needs a defined treatment of numerical influence: merely rejecting use of
a revoked source does not erase its learned contribution. That interface and
any unlearning claim remain unimplemented and unqualified here.

The current fixed MEM-1 reference driver still uses its original descriptor
tags and grants no fact/adoption authority. External binding of actual MEM-3
feature and program bytes does not qualify a new production encoder or owner.
The correct outcome of this pilot is to preserve strong retrieval, retain the
negative neural comparison, and keep continuous-version memory and independent
real-task confirmation as explicit unfinished work.
