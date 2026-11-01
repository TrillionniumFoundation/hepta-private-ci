# Independent R15 campaign review before formal execution

This is a source review of the proposed training/freeze/confirmation pipeline.
It does not certify unobserved remote publications, fabricate experiment
outcomes, or treat a development smoke as formal confirmation. The reviewer
read campaign, protocol, documentation, the statistical gate implementation and
the complete-worker launcher without editing those files.

## Snapshot reviewed

At the read containing publication guards, `campaign.py` SHA-256 was
`bf746200ef335157f4242b7f799e9405c690330644b61415c986406020084fd7`.
The corresponding `PROTOCOL.json` SHA-256 was
`64db3d30361d933694d2b9b0f399d141010e9b037ce7bf546cf7a2aeb6051eaa`.
The source manifest listed 17 files, including the imported R11 financial kernel
and R12 cell/protocol. Forty-character commit validation concerns commit SHA
syntax; it is not a claim that the manifest has forty source files.
Any later code change needs its own frozen identity and focused delta review.

## Data separation and model choice

The actual dataflow respects the intended separation. Calibration uses public
raw sequence streams at 11m/21m plus the fit seed. Policy learning, task
selection and confirmation use separate phase namespaces at 1/2/3 times 10^12,
with disjoint fit and domain offsets. In the registered eight-fit/128-episode
design these namespaces do not overlap.

Ordinary selection executes the common value planner on IID task-validation
worlds for the free-rate and same-HX-matrix HMM models. It selects actual net
utility, not the calibration likelihood diagnostic. Both candidates remain in
confirmation. The fixed-pattern selection uses pooled HX and selected-ordinary
validation utility and freezes one identical program for A and C. Learned
feature-policy regression uses the independent policy-training worlds. No
confirmation world or result is used in these selections.

Selection and policy training share the declared synthetic task family and
public information, but they do not establish generalization to natural language,
new dynamics families or learned address routing. Eight seeds are separate
calibrations, not eight independently chosen task definitions.

## Freeze and publication enforcement

Exclusive claim and result creation prevents an accidental second invocation
from overwriting the first attempt. Formal training now requires a 40-hex source
commit and a source-publication receipt matching the source manifest. Formal
confirmation requires a 40-hex freeze commit and a freeze-publication receipt
matching exact FREEZE bytes. Confirmation also checks the source manifest,
protocol hash and the selected training archive hash before opening its claim.
The complete fitted candidates and selected policy fields are inside the hashed
training archive; a later model or selection edit is consequently detected.

The actual connector readback is the evidence for those publication receipts.
A local `remote_readback_verified` boolean alone is not an independent remote
proof. The final report must retain the remote commit/readback identities and
their temporal relation to confirmation opening. Development bypasses the
publication prerequisite only when explicitly flagged and stored separately.

Two inexpensive preservation improvements were requested during review: check
the same source manifest again at successful train/confirm completion, and save
the completed calibration stage before later selection work can fail. Without
the latter, a task-selection exception can leave detailed calibration records
only in worker memory, although the supervisor still retains process cost and
failure logs. These are execution-evidence improvements, not changes selected
from scientific confirmation outcomes.

## Paired execution and hidden-world ownership

For each confirmation index the pipeline constructs one Episode and passes that
same owner object through all arms. It archives all hidden paths only in the
scorer-owned result. The policies themselves receive beliefs, current public
prices and deadlines through the already-reviewed execution layer; the archive
is never supplied to the actor. Arm order rotates deterministically, avoiding a
fixed first-arm timing order.

Same-matrix equivalence compares complete `queries` records from independently
executed D and HMM arms, including actions, completion times, tokens, answer,
target, fees and checkpoint digest. It is stronger than comparing mean utility
alone. Per-arm laws are separately restored and their declared duration caches
prepared before the episode loop. This keeps a reuse benefit from being
silently borrowed only by a later alias arm.

The source contains no observed task-semantic failure in deadline choice,
all-address time advancement, overwrite ordering or target leakage. This is a
bounded code review finding; independent numerical tests and actual pipeline
execution remain separate evidence.

## Costs and infrastructure

Training function CPU contains common generation, both candidate fits, all
ordinary/fixed validation trajectories and controller learning. Confirmation
records separate per-arm preparation, episode CPU and one belief-checkpoint
disk round trip. World generation is separately retained as experimental
infrastructure. These nested measurements must not be added twice to enclosing
worker totals.

The launcher uses isolated worker processes, single-thread library environment
settings and POSIX `wait4` user+system CPU. Its receipt includes interpreter
startup, imports, final gzip/JSON writing and fsync, which are outside an inner
function timer. These are research-CPU accounts; action tariff, physical time,
CPU and hardware energy retain different meanings. No production network,
GPU, Rust deployment or complete crash recovery follows from this accounting.

The statistics code conservatively charges the same complete candidate-search
cost to each alternative B/D deployment. Calibration-only standalone and
equal-calibration numbers are separately identified. They are components and
alternative accounts, not independent savings that can be added together.

## Statistical and documentation consistency

The controlling protocol now states four one-sided 98.75% Student-t lower
bounds: utility and correctness, each in IID and OOD, family alpha .05 via
Bonferroni, with all lower bounds strictly above -.01. `_lower_bound` implements
`t.ppf(1 - .05/4, n - 1)` and uses the fit mean differences. This agrees with the
requested n=8/df=7 rule. The primary gain comparison separately uses exhaustive
paired sign-flip tests and two-domain Holm adjustment; secondary mechanism
contrasts are descriptive rather than alternative rescue endpoints.

The source review also requested that statistical design completeness verify
the exact registered seed set and non-development flags, not only eight rows
and 128 episodes. Upstream formal freeze already restricts the seeds, but the
independent summary should not accidentally promote an arbitrary development
bundle. The cost gate in code requires both online D/B <= .90 and the full-search
1000-use D/B <= .90; the controlling protocol should state both conditions and
the primary amortization point explicitly.

README, MODEL_SPEC and protocol agree on supplied typed routing, current-query
optimality rather than six-query global optimality, and the finite-model scope.
Protocol and source review explicitly limit checkpoint evidence to local belief
state fsync/read/restore. MODEL_SPEC now distinguishes the calibration likelihood
diagnostic from task-validation primary selection and repeats the four-bound
noninferiority convention. None of these documents should label an unpassed
scientific effect or missing production qualification as closed.

## Focused delta review before source publication

The reviewer read the final changes described below directly in the source.
This section supersedes the pending-review language above for these specific
items. The reviewed SHA-256 identities are:

| File | SHA-256 |
| --- | --- |
| `campaign.py` | `02997ee4d91ffd07b782b20ece2fe8089b44124f1a740fcac580601e22aa117a` |
| `PROTOCOL.json` | `dbd4e096c3a4fdf814a48eeb41d712a040e09f3be861f6700fe4fabf0c6c5461` |
| `statistics.py` | `8cfa4d07ab5953e22275bb16d03453dcf98f6b0d915db358cf3f0e6fe777efcc` |

Training calls `check_source()` again after controller learning and before
creating its successful result; confirmation does the same after all paired
episodes and before creating its successful result. Both compare the returned
manifest digest to the opening/frozen digest. Because `check_source()` first
hashes every listed file, these checks detect both a changed listed source and
a changed manifest at these checkpoints. They are execution checks, not a
continuous filesystem monitor.

Immediately after `fit()` returns, training now saves the complete calibration
result to `calibration/{seed}.json.gz` before candidate validity checks and task
selection. The shared writer uses exclusive creation, deterministic gzip,
flush and file fsync. A later selection or controller-learning failure therefore
leaves the completed calibration sequences, search evaluations, candidate
payloads and cost records available. This does not promise recovery of a fit
interrupted before it returns or full-machine crash durability.

The statistical admission calculation now requires the exact eight registered
fit seeds, an explicitly Boolean-false `development` field in every training
and confirmation record, and 128 confirmation episodes per fit and domain.
Those conditions feed the scientific gain, noninferiority and guarded-cost
admission flags. An arbitrary eight-row bundle or development smoke cannot
qualify merely by matching its dimensions.

The protocol now explicitly requires all four simultaneous noninferiority
lower bounds above -.01 and, in both domains, both online CPU D/B <= .90 and
whole-search CPU D/B <= .90 at 1000 complete-episode reuses. This agrees with
the two cost tests in `statistics.py`; other reuse counts remain reported
sensitivity points and cannot replace the registered primary count.

The current manifest has 18 files because `decision_probe.py` was added after
the earlier 17-file snapshot. This review records that inclusion without
claiming an independent audit of all decision-probe logic. No formal training
or confirmation result is inferred from these source changes. The requested
preservation, admission and protocol-clarity corrections are resolved in the
three source versions identified above.
