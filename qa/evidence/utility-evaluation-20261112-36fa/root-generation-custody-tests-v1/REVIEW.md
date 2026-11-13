# Root-local initial custody: mechanism test candidate v1

This is an uncompiled, unexecuted test candidate for the separately frozen production packet `3ffcac56096eb06214963ab1fdc5898e2b7eebb2`. It adds two test modules and appends one module declaration to the original `circuit_q24_task_test_support.rs` (`661ec1c609ba0af1188dad00dd2910c7de4d2020`). Every byte of that parent's original body is retained. The four production postimages, the four-source fix101 repair, the actual witness postimage, the physical native repository, and all refs remain untouched.

## What the candidate exercises

The CURRENT actually supplied to the coordinator is constructed by the original public `prepare_agentd_generation_initial_v1` over a real `RootAuthorityDirectory`. The ignored tests require real and effective UID 0. They create their own mode-0700 directory beneath `/root`, then use the unchanged original directory validation, protected preparation, publication CAS and readback. There is no UID exemption, alternate test store, `from_parts` construction, file ownership transfer or caller-selected Current callback in this path.

The existing `VersionFixture` supplies its actual Artifact owner, selection, target journal/witness files, FinalUse owner, clock and explicit engineering issuer. That fixture also creates its historical test CURRENT, but the new tests never pass that owner to preparation, publication, recovery, task installation or drain. Its existence must not be described as production Root custody. AuthBus likewise retains the existing engineering issuer. These fixtures do not provide real deployment authority, independent evaluation or a useful user task.

The task path consumes the same Ready value that the new coordinator obtained from original publication. `OriginalRootCircuitTaskInputsV1` has no caller-supplied PublishedTask. The coordinator supplies that original task to `with_q24_circuit_task_profile` and retains the factory's actual Cell and Source. The test fixture starts the original bootstrap, dispatches the signed ObjectiveStart through the existing state ingress, and obtains completion only through `custody.drain_completed_task`. It does not pre-open a parallel Cell, construct a Source publication, call the inference model directly, or substitute a cached completion. The original retirement implementation checks task/Cell Arc identity and performs its original Source/Cell/journal/current sequence.

## Five prepared cases

| Case | Actual mechanism used | Required observation in the test code |
|---|---|---|
| Different operation | Real Root preparation, same protected store | The named different operation is rejected; protected Current and target bytes remain equal; no nonce is consumed. |
| Failed publication | Damaged signature from the existing issuer, original publish and original recovery | The Prepared value remains consumed. A second publish is refused. Same-operation readback remains Prepared and original recovery refuses pending history without redispatch. |
| Normal original task | Real protected publication, original task factory, original signed ingress, same-task drain | Before RunStart, drain fails. After the actual Circuit succeeds, drain yields the opaque original completion. Its complete shared Cell input projection, run, objective, bundle and nonempty result are checked. The publication remains the same and exactly one nonce has been consumed. |
| Installation failure | Published Ready followed by the original factory's zero-capacity rejection | The error retains the same original publication readback and does not create a new operation or return a reusable Prepared/Ready. The test does not claim that Source/Cell files were never touched. |
| Original withdrawal | Existing Artifact owner's real withdrawal before installation | Installation is fenced while the protected historical Published fact remains readable. A historical fact is not accepted as live task authority. |

The Cell input comparison uses an explicit `CellStepInputV1` projection rather than the invalid cross-type equality found in the separate fix101 repair. It preserves the original opaque publication's operation ID and compares the eight shared source fields. It does not assert that this equality independently verifies a lease or derives the operation ID; those remain the original Source/dispatch checks.

## Cleanup and timing

The normal case stores its body result, then always awaits `RootSession::finish` on the Result path before returning that result. All test conditions use fallible `anyhow::ensure!` or `bail!`; no new panic assertion can bypass that explicit join. The fixture cancels and awaits the actual worker under the original five-second bound. Its Drop only requests cancellation, matching the existing fixture boundary. This is not evidence that interruption of the entire async test has already joined the worker, nor a claim that an original operation with an uncertain acknowledgement was rolled back.

The original queue capacity 4, inference control capacity 4, maximum Cell records 16, Source witness bound 64, work amounts, 60-second task bound and original clocks are retained. The zero-capacity case changes only its requested test input to provoke the unchanged factory rejection. No test execution budget or native phase has been enlarged.

## Exact source and module checks

`REMOTE_SOURCE_REFERENCES.json` records complete Git GET byte identities for the protected directory, original runtime/test module chain, original initial fixture and durable RunStart types. The pure freeze script checks these identities against the complete 0c59 file graph and verifies all four frozen production postimages. It also proves that removing the exact 95-byte appended mount restores the entire original parent.

The verified module chain is `runtime::tests::circuit_task_ingress::q24_tests::support::root_initial_custody::tests`. `TEST_INVENTORY.json` lists all five complete names. The existing ingress module is Linux-only; these cases remain ignored unless explicitly selected in the existing Root test phase. This package does not modify that phase, its budgets, workflow, CALLERS or protection/QA files. Root must review and register the new cases and the production call edges before any final source freeze. Merely compiling ignored tests would not demonstrate that they passed.

## Remaining boundaries

This v1 package does not inject a real lost acknowledgement after the protected Current CAS. The protected directory's internal contracts test hook is not a public downstream interface; this package does not substitute the fixture FileCas hook and call that a Root-store failure.

The production v1 only constructs custody from a live original Prepared value. Its recovery method is warm recovery on that retained custody. It cannot by itself recreate custody after the Root process loses that value. Root has requested a separate v2 cold-entry using the actual reopened concrete Current, original authorities, selection, original target files and fixed recovery identity, directly through `recover_agentd_generation_initial_v1`. That future entry and its tests are not included here. Reopening an owner in one mechanism test must also remain distinct from a demonstrated process restart.

There is no remote Current service, cross-UID task proxy, full three-UID provider execution, independent B evaluation, model usefulness result or actual new C/daemon/Root closed loop in this package. The real task-chain count stays zero. No formatter, compiler, Rust test, source gate, QA, H action, physical source mutation or ref update was performed for this candidate.
