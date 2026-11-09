# MEM integrated qualification, 2026-11-09

**Three experiment paths are implemented and executed. Scientific acceptance is
HOLD; production adoption is NoUpdate.** Same-image retention improves observed
candidate availability without improving task completion. Source-matched replay
does not establish a consistent structured-order advantage. Strong relational
retrieval outperforms the actual Rust associative reader on the fixed composition
fixture. No new top-level Cell category is introduced.

## Decision and evidence map

| Experiment | Complete execution | Main observation | Decision |
| --- | --- | --- | --- |
| [Frozen real-actor candidate retention](../memory-candidate-retention-20261109/RESULTS.md) | 54 case pairs; 108/108 episodes completed | In the same 34 WRITE pairs, correct-candidate availability rises 14 to 23, correct selections remain 2, and candidate-mediated successes remain 1. Overall success is 11/54 in both arms. | Retention has an availability effect; no observed terminal benefit. |
| [MEM-2 replay exposure controls](../memory-cell-mem2-coverage/RESULTS.md) | 80/80 native windows; 20/20 exactly matched pairs | Structured minus uniform stable-A accuracy is +2.5 pp in dynamic and -15 pp in stationary at the B window. | Keep uniform as the default; do not promote structured replay. |
| [MEM-3 versioned relations and new combinations](../memory-cell-mem3-composition/RESULTS.md) | 60/60 trials; 3,840/3,840 terminal tasks | Exact and BM25 each achieve 1,280/1,280 joint correct; native association achieves 1,210/1,280. | Keep strong retrieval on the product critical path. |

These are different execution units and are not pooled into a synthetic total
of independent trials. All denominators, failed preparations, source bindings
and actual native work are retained in the linked reports and evidence.

## Three layers within MEM

| Layer | Implemented or evaluated responsibility | Current boundary |
| --- | --- | --- |
| Evidence and episodes | Exact/BM25 readers over facts with explicit provenance, versions, revocation, dependency and expiry metadata; independent terminal truth evaluation | Synthetic relational qualification; no new semantic index or production authority is claimed. |
| Working candidates | The bounded pool is connected to the real actor/host with identical current-only admission controls and source-bound O/C/S/D audit events | At most 128 candidates and 524,288 serialized bytes, scoped to the same immutable original image and task identity. |
| Learnable associations | The real Rust normalized-delta matrix is exercised for replay and primitive relation readout; checkpoints, update requests and kernel work are retained | No adapter or new actor training. Each MEM-3 owner cut pays for a reset/rebuild; continuous state transition is unavailable. |

Cross-screenshot, cross-document and cross-task persistence are not implemented
by reusing this bounded pool. Evidence/source validity remains an explicit owner
contract rather than an inferred property of a neural score.
The replay controls rehearse fact/primitive records. They do not qualify
skill-policy replay, procedural consolidation or a learned composition operator.

## Candidate retention: availability and completion are separate

The frozen comparison changes only candidate retention between observations.
Encoder, OCR, actor parameters, controller/action definitions, original image
and admission caps remain matched. The panel uses fourteen source groups and one
existing checkpoint: zero new actor fits and zero independent training repeats.

| Metric in the same 34 pairs with an actual WRITE decision | current_only | bounded |
| --- | ---: | ---: |
| Correct candidate offered, C | 14/34 (41.18%) | 23/34 (67.65%) |
| Correct selection among C-positive decisions | 2/14 (14.29%) | 2/23 (8.70%) |
| Correct candidate-mediated delivery among observed correct selections | 1/2 | 1/2 |
| Candidate-mediated correct deliveries | 1/34 | 1/34 |

All nine newly available correct candidates remain unselected. The conditional
selection fractions use different supports; their difference is not evidence
that the selector was made worse. Eleven cases per arm have no correct candidate
observed at the processed anchor, and one per arm selects/writes correct text but
fails the complete final delivery rubric.

The primary unconditional outcome remains **11/54 (20.37%) in each arm**: zero
wins, zero losses and 54 ties. Ten of those eleven successes were already correct
at handoff and used no WRITE action. Initially incorrect cases succeed in only
**1/44 per arm**. The observed availability gain therefore does not justify a
claim of improved task completion.

Twenty episodes per arm have no processed candidate roster at the final
attribution anchor. Their C/S events remain unknown even though all 108 evidence
rows are VERIFIED. Consequently the all-planned P(C), P(S|C) and P(D|S) point
values remain null/UNKNOWN, with explicit missing-outcome bounds. The 34-pair
table is a descriptive execution subset, not a replacement for the full planned
denominator or a complete population estimate. Bounds are not confidence
intervals.

The original run failed before PLAN construction or actor dispatch because a
valid quarantine ID was absent from the released catalog. A targeted correction
preserved the entire exclusion set and original request/receipt, then executed
the same frozen design as a recorded preflight correction. It is not another
independent experiment. No post-result tuning or repeat was performed.

## Replay: equal exposure does not rescue a general structured advantage

Both matched arms start from identical native checkpoints and replay the exact
same complete record/source/version multiset. Each uses 64 updates per window,
equal serialized replay payload and actual update-request bytes, and zero
teacher work. The priority rule changes order only among remaining quotas.

| B-window stable-A accuracy, five seeds / 40 probes per cell | Matched uniform | Matched structured | Structured minus uniform |
| --- | ---: | ---: | ---: |
| Dynamic | 34/40 (85.0%) | 35/40 (87.5%) | +2.5 pp |
| Stationary | 36/40 (90.0%) | 30/40 (75.0%) | -15.0 pp |

This controls exposure more strictly than matching the count of sources. It
identifies an ordering comparison conditional on a common state and exposure
multiset. It does not identify the cause of the original MEM-1 coverage gap or
replace the historical full-trajectory results. The initial/final software
verification runs use the same seeds and are not pooled as additional evidence.
Selector CPU, RSS, energy and monetary cost are not fully matched.

## Composition: valid sources do not guarantee correct values

The fixed pilot includes version replacement, revocation, dependency invalidation,
expiry, constraints, unknown inputs, and two/three-hop combinations of known
primitives. Every reader receives the same explicit composition operator. The
native reader follows its own predicted next hop; retrieval or truth never fills
its values. A common value-blind metadata gate can reject a source but cannot
correct a primitive label.

| Reader plus common composer | Joint correct | Correct on answerable tasks | Wrong assertions | Assertions when truth requires abstention |
| --- | ---: | ---: | ---: | ---: |
| Exact current-record retrieval | 1,280/1,280 (100%) | 897/897 (100%) | 0 | 0 |
| BM25 current-record retrieval | 1,280/1,280 (100%) | 897/897 (100%) | 0 | 0 |
| Rust native association | 1,210/1,280 (94.53%) | 830/897 (92.53%) | 67 | 3 |

The native arm's 70 errors are 64 wrong answerable labels, three false abstentions,
and three assertions when full truth requires abstention. The last three are
included in the 67 wrong assertions, not additional errors. Actual invalid or
revoked source use is zero in every arm because of the shared explicit gate.
That fact does not establish correct values, learned authority or unlearning.

On the 960 new-combination tasks per arm, exact/BM25 achieve 960/960 joint correct
and 814/814 answerable correct. Native achieves 900/960 and 754/814 respectively.
The small synthetic corpus and perfect retrieval ceiling expose associative
readout losses; they do not estimate performance under noisy queries, ambiguous
entities, incomplete indexing or larger real-task workloads. The operator is
provided, not learned.

### Continuous version memory remains blocked

All ten diagnostic requests against a new owner cut return SnapshotMismatch,
with byte-identical before/after checkpoints. Current predict/update/restore
bind the exact snapshot; reset discards numerical state. Rebuilt version stages
are not a continuous interference or forgetting experiment.

A later continuous-memory qualification needs an owner-authenticated transition
that preserves auditable state continuity while enforcing encoder/scope
invariants and current support eligibility. Revocation also needs an explicit
policy for residual numerical influence. Reusing an old generation or relabeling
Python metadata would evade the existing contract and is not an acceptable test.

## Work and provenance

| Campaign | Observed wall time | Recorded work |
| --- | ---: | --- |
| Corrected candidate campaign | 93.791119 s | 108 episodes; 171.762103 s CPU; at most two workers; zero new actor fitting/updates |
| Final MEM-2 replay campaign | 15.92 s | 5,120 fork updates; 1,600 evaluation queries; 80 windows |
| MEM-3 composition campaign | 8.060734 s | 2,360 primitive updates; 2,426 predictions; 4,846 protocol requests; 6.891198 s waited-child CPU |

The candidate actor is frozen; that does not mean the MEM-2/MEM-3 experimental
matrix performs no updates. MEM-3 records 498,304 replay payload bytes, 697,646
native request bytes and 1,292,288 kernel multiplications. Teacher work is zero.
Timing includes orchestration/instrumentation and does not establish a production
latency ranking. Nested timing envelopes are not added. Full RSS, energy and
provider pricing remain unmeasured.

The Rust binary was newly built from an exact 66-file, three-crate projection of
base `d13761500aba28634238ec23fb1d62eae5cf81ec`, with 24 lock-matched dependency
identities. Its SHA-256 is
`e8b95e5b88bfbbdd962812d800f2617daa924aa237dcdeba45b71697cad0713d`.
No Rust logic changes or full-workspace qualification are implied.

Candidate execution uses source `a4068996433f87f756455e97fe06ca1992aa63fb`;
MEM-3 execution uses `1407c79571f0386304cc2718e0c3d26824672e1c`.
MEM-2 manifests and archives bind its executed overlay bytes separately from
the common repository base. Original negative results and failed preparations
are preserved. The source stack consists of reviewable draft PRs, not merged
mainline code or product adoption.

The [publication binding](observations/source-binding-before-results.json)
compares local Git blob identities with the corrected published source and
checks the candidate and composition execution manifests. It records byte
consistency, not another experiment or authenticated execution authority.

### Reviewable PR stack

The stack starts from the existing integrated base in
[PR #5440](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5440).
Each following stage targets its predecessor. Handwritten logic and findings
are separated from mechanically preserved raw evidence.

| Area | Draft review stages |
| --- | --- |
| Candidate pool and admission | [#5481](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5481), [#5515](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5515) |
| Real actor/host and independent attribution | [#5516](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5516), [#5517](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5517), [#5518](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5518) |
| Frozen campaign and contracts | [#5521](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5521), [#5522](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5522) |
| Source-matched replay | [#5519](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5519), [#5520](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5520), [#5524](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5524) |
| Composition, accounting and registration | [#5530](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5530), [#5531](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5531), [#5532](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5532) |
| Original preflight failure and correction | [#5534](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5534) |
| Composition evidence | [#5538](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5538) |
| CI discovery correction | [#5540](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5540) |
| Candidate execution and validation evidence | [#5551](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5551) |
| Final reports and publication binding | This final synthesis stage |

## Validation and retained limits

Focused candidate, replay and composition regressions passed in their recorded
local environments. Final formatting receipts retain tested-source equivalence;
formatting was not followed by optional test reruns. The first exact-source
workflow passed 17 candidate contracts but used the wrong replay import root.
[PR #5540](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5540)
corrects that invocation without changing experimental code. The preserved
[source CI snapshot](observations/ci-source-snapshot.json) records the corrected
job still queued at 13:07:48 UTC; no tested-source checkout or passed-test count
was then observable. Its eventual result and subsequent final-head checks must
be assessed separately. Local tests, successful experiments and archived hashes
do not imply all repository checks passed.

The next evidence requirement is selection on a fixed candidate support plus
independent real-task confirmation. Continuous owner-version transitions and
cross-document/task memory require their own implementation and qualification.
This tranche establishes the instrumentation, actual actor integration and
measured negative comparisons needed to make those choices without promoting
an unsupported mechanism.
