# ACT-1: tool and action Cell qualification

## Status and source identity

This package implements bounded, goal-checked action skills on the existing
`automation.taskflow` authorized-effect path. Controlled native conformance
passed on final **green-r4: 150 tests passed, zero failed**. The fixture uses
the existing SQLite shim and genuinely read-only observer/oracle connections.
Final scoped Clippy and repository formatting also passed, with no Clippy warnings.

| Identity or gate | Recorded value |
| --- | --- |
| Starting candidate | `6ddfca2406e4d01416cd2f7ab1655a0dc16f8da5` |
| Starting candidate tree | `491eace326f335498334fb051c9e8f298ca7a04c` |
| Source branch | `fix/codex-v13-same-model-next-task-20261106` |
| Separately observed main snapshot | `732e934ba496d90fbe042b8d41d479ef901643e5` |
| Prior green-r3 executed tree | `334ccb7bb726033e898a3d698dfe616ae627e75c` |
| Post-correction test gate | 150 passed, 0 failed; [green-r4 receipt](native/green-r4/receipt.json) |
| Post-correction maintenance | Clippy and fmt exit 0; no warnings; [receipt](native/maintenance-r2/receipt.json) |
| Final executed source identity | `aa2afbb8eaa8b0c4d9e5c3c93abf03fa7cba4951` |
| Final matrix evidence | 30 unique rows, unchanged counts; [raw rows](native/metrics-green-r4.json), [summary](native/summary.json) |

Production activation, learned-hierarchy benefit and universal exactly-once
qualification remain **false**. A candidate branch is not the default branch.
Each native receipt describes its own staged execution tree; later documentation,
formatting or fixture edits must not be attributed to an earlier run.

## Implementation map

Paths below are relative to `codex-rs/hepta-automation/`.

| File | Responsibility |
| --- | --- |
| `src/action_skill.rs` | Versioned contract/envelope/binding, budgets, execution/goal/cancellation facts and observer interface. |
| `src/action_skill_driver.rs` | Authorized-driver decorator; initiation/goal checks, bounded calls and original-byte recovery. |
| `src/authorized_effect.rs` | Existing FinalUse/durable-attempt execution seam; fixes ordinary `NotFound` to remain `Unresolved`. |
| `src/lib.rs` | Explicit public exports for the contract and driver. |
| `src/action_skill_tests.rs` | Decorator-level identity, evidence, cancellation, rejection and recovery probes. |
| `tests/action_skill_act1.rs` | Native fault matrix, real input/SIGKILL processes, recovery, drift and positive-failure tests. |
| `tests/action_skill_support/destination.rs` | Durable SQLite target, business effects, fault barriers, contacts, dedupe and rejection tombstone. |
| `tests/action_skill_support/observer.rs` | Independent target predicates and retained evidence on a separate observation connection. |
| `tests/action_skill_support/harness.rs` | Real fleet/AutomationStore, prepared/claimed step, signed FinalUse grant, dispatch and recovery. |
| `tests/action_skill_support/baselines.rs` | Three control organizations, separate business oracle and per-run metrics. |
| `tests/action_skill_support/mod.rs` | Fixture modules and child-process environment names. |
| `tests/authorized_effect.rs` | Regression: empty provider lookup must not grant retry rights. |
| `tests/action_skill_support/README.md` | Fixture protocol, scenarios and scope. |
| `BUILD.bazel` | Additional integration-test support sources; not evidence of a Bazel test run. |

The post-r3 fixture correction reuses `codex-state::SqliteConfig` without new
dependencies. The target uses its durable evidence pool; observer and scorer use
existing-database, read-only observation pools. The final native gate validates this correction.

## Contract, authority and terminal semantics

A skill binds initiation, internal-policy identity, termination, target
postcondition, version, call budgets and recovery. Policy/predicate digests pin
implementations; this change does not add an interpreter or learn predicates.
The envelope embeds contract and destination in the exact wire bytes covered
by the provider payload digest and signed FinalUse binding.

The real path is durable TaskFlow prepare/claim, FinalUse claim, durable
dispatch-attempt record, fenced final-use verification and goal-checked dispatch,
destination effect, independent observation, durable receipt and owner settlement.
The decorator does not grant capabilities, replace the executor or bypass fencing.
Its binding includes provider key/payload, effect-intent digest, contract and
destination. The effect digest binds attempt, policy generation, subject and scope;
historical evidence is not current execution authority.

| Settlement | Required evidence |
| --- | --- |
| `Succeeded` | Provider success plus exact-bound independent evidence: goal satisfied, termination met and execution terminal. |
| `Failed` | Provider failure plus retained no-effect/no-late-commit evidence, goal unsatisfied and termination established. |
| `Indeterminate` / UNKNOWN | Ambiguous contact, partial effects, unavailable/mismatched evidence, or conflicting provider/goal observations. |

Exit zero, `completed`, a cancellation ACK and an empty lookup are insufficient
alone. Before contact, rejected initiation may return a pre-contact error.
After dispatch may have occurred, errors/timeouts become `Indeterminate`; they
must never manufacture `NotDispatched` or `ProvenAbsent`. Ordinary `NotFound`
now remains `Unresolved` in the underlying driver too. Key/status capability
alone cannot exclude an in-flight request committing later.

Recovery reuses original identity and envelope, without replaying the action or
adopting a changed contract. `observe_pending` reads waiting, partial-effect and
cancellation facts without settling or redispatching. Cancellation and partial
effects remain separate from goal satisfaction. Host-provisioned observers are
trusted; matching a name or digest is not authentication or formal verification.
Observers retain detailed evidence indexed by the full binding. TaskFlow stores
a bound digest, not every subeffect or input-reader detail.

The positive failure fixture seals a rejection tombstone under the destination
writer transaction after checking zero business events. Its observer can then
attest no effect and no possible later commit for the exact key/payload.
The test obtains `Failed` settlement and checks that reopen, a late target worker
and owner replay preserve the tombstone and zero effects. This is a limited
destination contract, not a generic distributed absence proof.

## Controlled matrix: final green-r4 evidence

The baselines are a deterministic persistent workflow, a parsed hand-authored
DSL macro and a flat primitive verification loop. They share target, request,
observer, authority, fence, fault schedule and budget. Equivalent behavior is
expected: these are **single-effect conformance baselines**, not a performance
ranking or a learned-skill generalization experiment.

The target commits real SQLite business events separately from execution facts
and contacts. The oracle queries business rows through its own connection; it
does not score fault labels, provider ACKs, exit codes or observer judgments.
Waiting uses a real stdin child. Restart uses SIGKILL after destination commit
and before the dispatch result, then reopens and queries the original key.

Every scenario contributes **three rows**, one per baseline; columns aggregate
those three rows. “Actual” means the complete business goal, excluding partial
subeffects. Every row has exactly one physical dispatch.

| Scenario | Rows | Actual full goal | Reported success | UNKNOWN | Recovery queries |
| --- | ---: | ---: | ---: | ---: | ---: |
| No fault | 3 | 3 | 3 | 0 | 0 |
| Committed effect, ACK lost | 3 | 3 | 3 | 0 | 3 |
| Waiting for input | 3 | 0 | 0 | 3 | 6 |
| Partial success | 3 | 0 | 0 | 3 | 6 |
| Rejected after partial effect | 3 | 0 | 0 | 3 | 6 |
| Cancel before commit | 3 | 0 | 0 | 3 | 6 |
| Commit before cancel | 3 | 3 | 3 | 0 | 0 |
| Exit zero without effect | 3 | 0 | 0 | 3 | 6 |
| Lookup unavailable after commit | 3 | 3 | 0 | 3 | 6 |
| SIGKILL after commit | 3 | 3 | 3 | 0 | 3 |
| **Total** | **30** | **15** | **12** | **18** | **42** |

There are zero false-success records and zero duplicate effects in this matrix.
Each baseline has 10 rows, 5 actual full goals, 4 reported successes, 6 UNKNOWN,
10 dispatches and 14 queries. Raw `(baseline, scenario)` pairs are all unique.
These are controlled cases, not 30 statistically independent task samples.
Passing all scenario assertions is not 30/30 business task success.

Of 18 UNKNOWN rows, 3 have a complete goal, 6 partial effects and 9 zero events.
Thus `unknown_with_any_effect=9`; the original `metrics.json` field
`unknown_but_effect_committed=3` counts complete goals under UNKNOWN, not all
committed subeffects. Keep the raw artifact unchanged;
[summary.json](native/summary.json) names these distinctions. Final green-r4 raw
rows are identical to green-r3 when keyed by baseline and scenario.
The 42 queries equal provider lookup contacts. They exclude other observer reads,
startup, wall time, compute and tokens; they are not complete recovery cost.

## Test counts and evidence integrity

[green-r4 receipt](native/green-r4/receipt.json), [log](native/green-r4/tests.log)
and [JUnit](native/green-r4/tests.xml) agree: **150 tests run, 150 passed, 2 skipped**.
JUnit has 150 unique cases and no failure/error. Nine ACT-1 integration entry
points and three action-skill unit entry points are included in that total.
The 30 matrix records come from two integration entries, not 30 extra tests.
The positive tombstone/`Failed` test is outside the 30-row denominator; additional
input-resume, partial-repair, drift, unsupported-target and recovery checks are
also separate. Do not mix their contacts into matrix totals.

The ignored entries are `action_skill_input_worker` and `action_skill_crash_worker`.
Parent tests launch them with `--ignored --exact`; the crash helper is deliberately
killed. They are excluded from the normal 150-case run and JUnit, explaining
JUnit's empty skipped list versus nextest's two skipped entries. Do not count
them as two extra passes or two untested product failures.

The final log SHA-256 is
`ee3fad77f0c0b5d24a1f217eeab9946d28e5fe7cc23855e160a26826cef7d249`;
JUnit SHA-256 is `3ac8e1599e37182708e51314c2b4024370aeb399af775448f653c822ab7cc43a`.
The nextest run ID is `a3b6510a-a9e0-402a-86ad-d77a19d13e26`.
Before/after execution trees match; raw metrics reproduce the log exactly.
The native gate uses Rust 1.96.0 and nextest 0.9.103 on x86_64 Linux:
`just test --locked -p codex-hepta-automation --lib --tests --test-threads 2 --success-output immediate`.
This is a scoped crate gate, not a whole-workspace or remote-CI result.

After tests, only `destination.rs` layout changed during formatting; the exact
[patch](native/post-green-r4-formatting.patch) is retained. The formatted source
tree is `74fad34ae160c07c5844450ac2dbe9c23a1214c3`, distinct from the executed tree.
Qualification documents/records are added afterwards. No behavior-changing
post-test edits are attributed to the successful run. Per repository guidance,
no routine test rerun followed the final fix/format commands.

The independent [final source review](native/final-source-review.txt) confirms
the post-r4 patch is whitespace-only and verifies the exact SQLite read-only
implementation. The [earlier metric review](native/metrics-review-green-r3.txt)
checks all green-r3 rows; final green-r4 rows were independently matched against
that retained set. Reviews do not add test cases or extend qualification scope.

## Retained failure and correction history

All gate attempts and the initial staging failure remain under `native/`; later
passes do not erase failed attempts.

| Attempt | Observed outcome and consequence |
| --- | --- |
| Initial staging | Expected before-file hash disagreed because of a copied trailing newline; stopped before mutation. This is a setup failure, not a test result; see `native/staging-preflight.json`. |
| `red-not-found` | Deliberate red test: 1 failure, exit 100, exposing the old `NotFound` to `ProvenAbsent` conversion. |
| `green-r1` | Compile failure E0618, exit 101: local `facts` shadowed the fixture function; renamed the binding. |
| `green-r2` | 149 tests: 148 passed, 1 failed, 2 skipped. Reopen retained the old FinalUse owner (`StateLocked`); both automatic attempts failed. Fixed fixture lifetime. |
| `green-r3` | 150 passed, 2 helper entries skipped, exit 0; includes the added positive-failure test. Historical pre-shim/read-only-correction gate. |
| `maintenance-r1` | `just fix ... -D warnings` exited 0 but emitted one disallowed direct SQLite-pool warning. `just fmt` exited 1 because `dotslash` was missing. Not a clean lint/format gate. |
| `format-r2` | Reused the existing recorded `dotslash`; `just fmt` exited 0. Fixed formatter availability, not the remaining SQLite lint. |
| Fixture correction | Reuse SQLite shim and actual read-only observer/oracle pools, with no new dependencies. Requires a new test gate. |
| `green-r4` | 150 passed, 2 helper entries skipped, exit 0; final shim/read-only-pool candidate, exact log/JUnit identities retained. |
| `maintenance-r2` | Scoped fix and fmt both exit 0; diagnostic log has no warnings. Only recorded formatting changes followed tests. |

## Qualification boundaries and next evidence

- The local controlled SQLite target is not a deployed HTTP service or external account.
- This seam does not activate a production Cell, ordinary product entry, remote
  `runtime.codex` adapter or published runtime/source version contract.
- Fixture call bounds are 16 KiB wire bytes, 30-second provider and 5-second
  observer timeouts; the harness allows one dispatch and two lookups per row.
  Cross-call/restart budgets remain owner obligations, not a new global scheduler.
- Cancellation is a destination-domain request, not TaskFlow run `Cancel`.
  There is no implicit rollback, compensation or erasure of committed effects.
- SIGKILL recovery reuses the same TaskFlow fence. Existing fencing suites are
  separate evidence; this fixture is not a new-epoch/competing-writer proof.
- Input state comes from the controlled destination and a real stdin process.
  Arbitrary syscall-wait detection, prompt/reader epochs and stale-input ordering are unqualified.
- Subprocess tests are Unix-only. Cargo/nextest success and Buildifier formatting
  do not establish Bazel execution or Windows support; Bazel tests have not run here.
- No universal exactly-once or formal protocol proof is claimed. Trusted observer
  evidence, target dedupe and a specific tombstone are explicit assumptions.
- Learned hierarchy, proximal neural prediction, residual adaptation and held-out
  composition generalization remain unmeasured. Freeze model/data/policy, tuning
  opportunities, independent evaluation and complete budgets before comparison.

## Research basis, verified 2026-11-08

- Perks et al., [Connectome analysis of a cerebellum-like circuit for sensory prediction](https://www.nature.com/articles/s41586-026-10690-6), Nature, **2026-09-02**:
  connectomics, recordings and constrained models motivate a proximal-feedback/residual
  adaptation hypothesis; transfer to software remains unproved.
- Harvey et al., [Unsupervised Hierarchical Skill Discovery, v2](https://arxiv.org/html/2601.23156v2), **2026-05-28**:
  observational structure discovery still requires action-grounded executable
  policies and initiation/termination mechanisms.
- Physical Intelligence et al., [pi0.5](https://arxiv.org/abs/2504.16054), **2025-04-22**:
  semantic subtasks and low-level robotics motivate hierarchy comparisons, not
  software recovery or exactly-once guarantees.
- Yang et al., [RECEIPT, v1](https://arxiv.org/html/2611.01930v1), **2026-11-01**:
  distinguishes return, input wait and actual effect and checks a bounded protocol;
  its finite-model assumptions do not qualify this implementation.
