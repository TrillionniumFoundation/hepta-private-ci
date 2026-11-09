# S0–S5 development progress, 2026-11-08

This series advances one source lineage from `81da60b349e32d89d0e4c4674a517a66af7e5eee`.
The review stages and the composed source are recorded in `PUBLICATION.json`.
**Every scientific stage remains HOLD.** Passing engineering regressions does not
establish adequate training, equal-budget real-task benefit, production owners,
physical migration benefit, or inherited multi-generation improvement.

Original executions, failures and source identities are preserved separately.
`ARCHIVES.json` identifies each compressed archive; `ARCHIVE_INDEX.jsonl` binds
its members by size and SHA-256. Tests repeated after a correction are not added
together as independent tests or scientific samples. Final formatting is a
separate source phase; its readback is recorded in `FORMATTING.json`.

## S0: protected checkpoint composition

`LearningIterationCheckpointOwnerV1::with_stage_owners` consumes the already
registered protected checkpoint capability and returns ordinary learning worker
ports. The separate stage-owner trait requires `validate_recovery` for every
restored snapshot. Its contract covers the original operation, proposal/anchor,
fresh trust and withdrawal checks, and empty, NoUpdate and completed snapshots.
It does not manufacture a stage signer, Root capability, proposal or fallback.

Synchronous persistence runs in one bounded blocking lane. Cancelling a waiter
does not release the lane while actual I/O continues. Unknown commit outcomes
remain unknown until the original store is read back. Stage-owner and protected
store errors are preserved.

The official scoped command was:

```sh
just test -p codex-hepta-agentd --locked --cargo-profile dev-small --lib \
  -E 'test(learning_iteration)' --retries 0
```

At clean commit `6462854e289a405b2981fa67b77b1cb51a155326`, tree
`d860ce8d7539d72ca75441f416332a8420f57564`, the desktop execution passed **21/21**
selected tests with zero retries; 760 other tests were outside the selected
scope. The three new tests exercise reopening each stage, error propagation,
lost-acknowledgement reconciliation and cancellation during actual fixture I/O.
This uses the existing file/fsync fixture, not independently qualified
production Root custody or actual training/evaluator owners.

The tested executable SHA-256 is
`c6bbe7ece3e3631aa1c19166c9d86269e3d43ff4ec272d7f94690a3e3db74a7d`.
The executable was copied into the configured host's separate evidence area
and its digest was verified. The source remained unchanged during execution.

All preceding failures remain visible:

| Attempt | Actual outcome |
| --- | --- |
| Local native 1 | Exit 101 before tests: missing CMake. |
| Local native 2 | Exit 101 before tests: missing Clang builtin `stddef.h`. |
| Local native 3 | Exit 101 before tests: shared-disk ENOSPC during archive/metadata creation. |
| Desktop native 1, `6900fdd5` | Exit 101 before tests: 16 E0659 errors from an ambiguous assertion macro in the new child test module. |
| Desktop native 2, `6462854e` | Explicit `pretty_assertions::assert_eq` import fixed the compilation issue; 21 selected tests passed. |

The separate, earlier contracts baseline executed 268 tests: 266 passed and two
failed at Unix socket bind with EPERM; ten were skipped. Its original retries,
log and JUnit are retained. It is not an agentd success result. A first caller
proof wrapper invocation was rejected before dispatch for an invalid source
identity; that rejection is retained as well.

The first Windows workflow on `6462854e` passed five test groups totaling 33
tests, then failed its Rust formatting step. All 18 formatting hunks were in
the newly added checkpoint-port test file. The same workflow passed this step
at `81da60b`; the compiler/workflow/formatter configuration was unchanged. This
is this series' formatting regression, not an inherited Windows assertion
failure. Subsequent acquisition checks were skipped. Its full original job log
and the baseline comparison are retained in `s0-windows-format-failure.tar.gz`.

The subsequent scoped `just fix -p codex-hepta-agentd --locked --profile
dev-small` passed at the same `6462854e` source. It took 312.642517 seconds and
produced a zero-byte patch. The only reported warnings were the two inherited
`third_party/i18n-config` lifetime warnings. Its original log, receipt and final
remote job states are retained in `s0-final-lint.tar.gz`.

The final formatter corrected the 18 new-test-file hunks and produced source
commit `dafa66841cbcda56dcbab7f1a737514ec7e7fe4f`. This is later than the native
test source; formatting is not represented as another native test execution.
The latest head-specific CI observation is retained separately below.

**Remaining S0 evidence:** a default/ordinary task entry using concrete original
owners, a loadable learned model, complete costs, and actual successor use.

## S1: distinguish perception, selection and stopping failures

The original retention inputs required text, with image weight zero. The missing
rendered images were therefore not the reason for their zero text scores. The
original 160-result projection contains 47 immediate stops and 113 text writes,
all with zero text score and no ROI read. A sampled original date observation
contained no candidate accepted by the unchanged date normalizer. No label,
action-mask or evaluator-interface bug was established.

The new development-only diagnostic binds the registered inventory, original
requests, attempts, result hashes, record chains, trajectories, public packets
and final deliveries. It accepts only train/development roles and retains
failed, unresolved and unstarted attempts in the denominator. It distinguishes
missing correct candidates, incorrect selection within the candidates, writes
outside the candidates, stopping and acquisition outcomes. Reconstructed action
text is separate from independently hash-bound final delivery text.

One bounded read-only job on the original host analyzed all **20 original
training attempts and 50 rows**, preserving 126 input bindings. No new actor,
OCR, training or evaluator process was launched.

| Original training observation | Count |
| --- | ---: |
| Correct candidate present / absent | 21 / 29 rows |
| Correct WRITE_TEXT / incorrect candidate selection / missing correct candidate | 2 / 2 / 4 writes |
| ROI coverage gained / lost / retained / still missing | 2 / 2 / 1 / 2 reads |
| Hash-bound final text correct / incorrect | 10 / 10 attempts |
| Final text judgments agreeing with the original evaluator | 20 / 20 |

Eight of the ten correct final texts were already present in public handoffs and
had no WRITE_TEXT. They do not establish newly learned delivery. One of the two
ROI coverage gains also came from an already completed handoff. ROI coverage is
an observed availability change, not a counterfactual benefit estimate.

The original content-training receipt contains only two source groups, 14
unique content states, two epochs and four optimizer updates for the inspected
fit. Text cross-entropy fell from 1.2891023064 to 1.2314098132. Rows without a
correct candidate contribute no exact text-selection cross-entropy under the
unchanged training semantics. These counts do not establish training adequacy
or forgetting from an independently measured initial incumbent.

Sixteen new diagnostic tests and five existing recursive-contract tests passed
in the final scoped command, with zero skips. Two earlier expanded commands
failed because of package-path/mock namespace and sparse-checkout input issues;
the original failures and one existing no-Torch skip remain in the archive.
No old test source or skip rule was changed to manufacture a pass.

The original action spans sum to 11.546084601 seconds and are already included
in the 53.750481397-second sum of original attempt wall envelopes. Concurrent
phase elapsed times are a different, overlapping measure. The new diagnostic
wrapper measured 0.154168170 wall seconds and 0.104213647 process CPU seconds;
transport, supervisor, energy and monetary costs are not established. ROI
action spans alone may omit OCR performed during the following decision.

Raw retention documents, OCR and complete original results are not included in
the published archives. Aggregate findings, original paths and hashes are
preserved; original raw evidence remains on its configured host.

### Bounded candidate memory

A separate development adapter now retains actor-visible candidates across
observations of the same original image. Its scope binds the original operation,
case, immutable image SHA-256, width and height; changing any field clears the
pool before validating the new observation. Inputs contain only public text,
original-image coordinates, origin and 126 finite features. Unknown metadata or
label fields are rejected. The scope identity is caller-supplied, not independent
image authentication.

Selection is fixed: current candidates first, then the most recently observed
distinct historical candidates, with stable ties. Records are deduplicated by
text, box and origin, capped at 128 and at an explicit canonical JSON byte
budget, and returned as immutable copies. Original observation steps and source
bindings are retained. Successful and rejected calls record process CPU and wall
time; serialized resident bytes are not process RAM or complete physical costs.

The adapter's **five tests passed in its first and only execution**, in 0.019
seconds. This is separate from the diagnostic command's 21 passing tests. The
pre-test source snapshot, log and receipt are retained in
`s1-candidate-memory.tar.gz`; `S1_MEMORY_VALIDATION.json` is a readable copy of
the original pre-format receipt. Both files preserve their tested Python ASTs
after final formatting. There were zero fits, optimizer updates, dataset
replays or confirmation runs. The frozen actor/evaluator was not modified and
the adapter was not integrated into an original task run, so no terminal-quality
or old-capability-retention improvement is established.

## S2: preparation and action choices before evaluator access

The new development planner compares horizons 1, 3 and 6 over the same four
actions. It takes only explicit actor-visible inputs, reserves the registered
full tool support plus preparation and declared decision work/time, and stops
before model inference when no option fits. Every comparison choice is frozen
before the evaluator is read. Prefix, decision, preparation and tool costs are
accounted once; host CPU/wall and simulator units remain distinct.

Two new development GRUs used seeds 9011 and 9017: 1,016 parameters, 128 training
samples, 12 epochs and 48 optimizer updates each. The v2 time-accounting replay
reused these exact checkpoints and original development samples; it performed
zero new fits and zero confirmation runs. Version 1 and its evidence are retained.

| Expanded development panel | Adaptive | Fixed 1 | Fixed 3 | Fixed 6 |
| --- | ---: | ---: | ---: | ---: |
| Seed 9011 expected net utility | 0.201100 | 0.201100 | 0.199673 | 0.188201 |
| Seed 9017 expected net utility | 0.183208 | 0.184575 | 0.188486 | 0.177247 |

Each seed stops in 86/129 episodes on this expanded resource panel. On the
original generator resource panel, full-support reservation makes every one of
129 episodes stop before inference. Neither result establishes a useful policy
advantage. The fixed arms share the same twelve forecasts and charges; this
isolates choice rules but does not establish fairness against the cheapest
fixed-policy implementation. Adaptive ties Fixed 1 at seed 9011 and is lower by
0.001366392262152322 at seed 9017; it is also lower than Fixed 3 at seed 9017.
On the original resource panel every arm has expected net utility
-0.03237209302325582 because incurred prefix costs still count despite zero
prediction calls. Declared decision delay affects feasibility and reported
utility, but does not advance the simulator's latent state.

The full PRED-1 package passed **42 tests**, including eleven new preparation
tests. This is a finite simulator development result, not real media/action
feedback or latency/failure robustness qualification.

## S3: real gradient and spike observability

The PLIF adapter now records per-neuron spike counts, fractions, silent units
and actual batch/time opportunities. Training logs read gradients after backward
and before clipping/AdamW, separating missing, finite zero, finite active and
nonfinite gradients. Complex values count real and imaginary scalars separately.
Weight decay is not classified as gradient credit.

Five real Torch/SpikingJelly tests passed on CPU. They compare legacy and
instrumented logits, gradients, RNG and two AdamW updates with `rtol=atol=0`,
check real PLIF hooks and reset, and exercise the actual trainer's diagnostic
and main update records. The selected environment was Python 3.12.14, Torch
2.8.0+cpu, NumPy 2.3.5 and SpikingJelly 0.0.0.0.14. It differs from older CUDA
evidence. Optional distribution dependencies and GPU execution are unqualified.

The new CI workflow executes these behavioral tests on an exact clean source,
checks a non-skipped minimum, and retains original failure logs. This instrument
does not establish sufficiently trained standard baselines, convergence,
scientific benefit, or a GPU cost advantage. The gradient helper currently
targets the registered dense-gradient models.

## S4: trained parameter and optimizer state continuity

The development adapter captures named CPU tensors, persistent buffers, AdamW
moments/steps and parameter-group settings. Existing ORG-1 transitions repartition
whole tensor records; materialization maps optimizer IDs by stable parameter
name, including when target parameter and group order are reversed. Orphaned
optimizer state is rejected instead of being silently lost.

Five real GRU/AdamW tests passed before and after the orphan-state correction.
These are the same five tests, not ten independent observations. Across split,
merge, rewire and no-change paths, logits, gradients, parameters and the next
AdamW update are bit-exact. Interrupted transfers retain partial observations,
unique record ownership and incurred costs while leaving the source unchanged.
Two suites executed 18 unit optimizer updates; they are not scientific fits.

Tensor payload, Torch archive and in-memory JSON bytes are separate counters.
No physical/network traffic is inferred. The 64 MiB limit is checked per encoded
object, not as a process or aggregate memory bound; retained snapshots grow with
the number of moves. This is fresh-episode CPU state; RNG, schedulers and online
hidden states are outside the transfer contract. It does not change neuron count
or distribute subsequent execution.

The original three reference archives were independently hash-checked and their
raw traces recounted:

| Operation | Pairs | Fixed / dynamic score | Fixed / dynamic messages |
| --- | ---: | ---: | ---: |
| Split | 33 | 33 / 33 | 36 / 36 |
| Merge | 33 | 33 / 33 | 36 / 36 |
| Rewire | 33 | 33 / 33 | 36 / 69 |

These are 99 pairs / 198 arm-task executions, with zero training updates and
zero scheduler-search candidates. The shared dictionary router's identity does
not establish a strong tuned fixed scheduler. Complete net benefit remains
unknown and the previous HOLD result is unchanged.

## S5: original-run independence in inherited-improver evidence

The validator now deduplicates original runs across lineage blocks under both
producer and evaluator ownership, and original attempt/operation IDs under
producer ownership. Registered missing results also reserve their identities.
Renaming a lineage cannot turn one execution into independent repeated evidence.
Shared pair IDs and holdout data remain allowed; independent owners may reuse
their own local IDs. Owner declarations alone do not authenticate independence.

The three existing suites passed **45 tests**, including four new test methods.
CI's evolve suite minimum rises from 13 to 17. Read-only recomputation of both
retained campaigns is identical to the unmodified `81da60b` code. The final
campaign also exactly matches its stored report. The earlier development report
predates fields already present at that base, so its pre-existing stored-report
mismatch remains documented instead of being overwritten.

The original three lineages, twelve runs and 72 attempts remain HOLD. This
integrity repair creates no new improver generations and establishes no sustained
advantage for a successor improver from common starting points.

## Composed source and review stages

The final code source is `62a8c50ec81a0027621d75156a9b56b23edd977c`, tree
`7f2acc200e960278dbf135e90bd24416f8d35c7e`. It composes 27 changed source/workflow
files onto `81da60b`; the evidence-only commit containing this report inherits
that exact code. `PUBLICATION.json` binds each review stage, parent, tree and
changed file. These are nine successive review PRs, not nine alternative source
implementations.

| Review PR | Scope | Added + removed text lines |
| --- | --- | ---: |
| [5409](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5409) | S0 checkpoint composition | 478 |
| [5411](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5411) | S5 original execution independence | 122 |
| [5412](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5412) | S2 preparation choices | 549 |
| [5413](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5413) | S3 gradient/spike observation | 470 |
| [5414](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5414) | S4 named trained-state transfer | 604 |
| [5415](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5415) | S1 observation diagnosis | 560 |
| [5416](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5416) | S1 original-attempt binding | 522 |
| [5417](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5417) | S1 bounded candidate memory | 414 |
| [5418](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5418) | Inherited MEM-1 mechanical formatting | 496 |

S1 diagnostic code is split into observation and file-binding review stages.
The fourteen core test methods and core function ASTs exactly match their subset
in the final tested module; the final stage adds the two file-binding tests.
This subset comparison is a source readback, not a new behavioral execution.

Final formatting used pinned Ruff 0.15.13 and the repository's `just fmt` recipe.
All eighteen Python file ASTs remained identical. Rust formatting changed only
the new test file's layout. `git diff --check` and selected fatal Python lint
checks passed. Native tests preceded scoped `just fix`; all local behavioral
tests preceded final formatting. No local behavioral tests were rerun after
that formatting phase. Automatically triggered PR CI is recorded separately
with its own source identity and observation time.

No qualification policy, Cargo dependency/lockfile, frozen evaluator, protected
main branch or running production deployment was changed. The publication is a development
source-and-evidence series; S0, S1, S2, S3, S4 and S5 all remain HOLD.

### Final source verification and observed CI

At clean source `62a8c50ec81a0027621d75156a9b56b23edd977c`, the original
`hepta_ci_exec.py` source-head wrapper dispatched
`verify_hepta_callers.py verify`. It exited zero after 305.954632 seconds,
scanned 6,115 Rust files and returned `PASS_HEPTA_CALLER_CLOSED_SET`. Before and
after commit, tree and clean status were identical. This verifies the declared
source call-site set; it is not an actual task, training, production-owner or
scientific qualification receipt. The earlier rejected wrapper invocation is
still retained.

The final recorded CI observation is explicitly time-bound:
**2026-11-09 04:11:31–04:11:32 UTC**. The S0 formatted head `dafa6684` Windows
[run 42559471008](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42559471008)
was in progress, with the first three native groups successful, Agentd integration
running, and its Rust formatting step still pending. No final success is inferred.
At S1 memory head `30fbc990`,
[training development 42559907452](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42559907452)
and [EVOLVE-1 42559907449](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42559907449)
were queued. These head identities were independently read from each run.
No new terminal failure was observed at that time; the whole series is not
claimed CI-green. Raw observations are in `final-ci-observation.tar.gz`.
