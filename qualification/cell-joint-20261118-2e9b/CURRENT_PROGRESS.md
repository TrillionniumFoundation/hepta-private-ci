# E1–E6 continuation: actual results and remaining gates

Observation: 18 November 2026, America/New_York. The original prospective
`SOURCE_FREEZE.json` remains unchanged. The 216-test joint engineering source is
`e52c4f67cb58a65409256f7be263cfb49ac22557`. Each follow-up retains its actual
source, model and protocol; the complete identities and original-file SHA256
checks are in [CURRENT_PROGRESS.json](CURRENT_PROGRESS.json).

## Completed experiments

| Experiment | Actual result | Interpretation |
| --- | --- | --- |
| E1, 96 calls | All four arms score 0/6 on external B. On A, final-only selects 3/6 and trajectory SFT selects 5/6, but both finish at 2/6. Trajectory SFT recovers two initial failures and regresses all three initial successes. | Research **NoUpdate**; retained or generalizable improvement is not established. |
| E3, 12 new calls | Byte-pinned second teacher selects 1/6, retained first teacher 0/6. Union is 1/6, equal to the stronger teacher. | Genuine different-model execution, without demonstrated mutual complementarity. Physical compute is not matched. |
| E4, 120 primary calls | FF, TT and full TF each score 0/6. Only the separate `TF_no_answer` ablation scores 1/6; all other arms score 0/6. | No Circuit necessity or aggregate same-budget advantage is established. |
| E5 | Zero authenticated new users and zero new deduplicated real training sources. | Neither growth curve is measured. External evaluation repositories are not user growth. |

[E1 originals](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/462c651d349663d86f6ec88ed5d9eed453f218c0/qualification/cell-matched-info-20261118)
retain both 64-step trainings, matched input/computation shapes, all four
evaluation arms, failed formats, business verification and regressions. Candidate
identities were fixed before external B evaluation. B is evaluation-only.
Reusing it in E4 is exposed development, not fresh confirmation.

[E3 originals](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/5e027a1d0c49a2b1408e90491b4cc0bc1660725f/qualification/cell-e3-localteacher-20261118)
retain the complete 98,403,356,224-byte GGUF hash, actual service sampling,
superseded zero-call failures and old-baseline rechecks. The upstream community
license/local Apache label conflict is explicit. Only the authorized internal
research scope is asserted. Logical information and call caps match; service
compute, physical cost equality and external commercial rights do not.

[E4 originals](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/7e0687b916dfbc8b87f1e3d3709856ed44dafbc2/qualification/cell-upstream-circuit-20261118)
include 1,332 indexed files. Including four A calibration calls and six reference
verifications gives **124 model calls, 130 verifier calls, 68,033 input tokens and
11,321 output tokens**. The actual owner ran for 1,034.621 seconds without an
automatic retry. Loading and child costs are retained; nested windows are not
added. Full physical cost equality remains unestablished.

The one TF answer-edge ablation recovers a failure after removing the earlier
wrong answer and preserving actual failure feedback. This is one exposed
negative-transfer case, not a population effect. Separately, 22 of 24 retrieval
outputs copy an unrelated A reference AST; two do not parse. Better formatting
did not create verified upstream task success.

## E2: both actual updates frozen, then B2 released

The next E2 candidate uses the current student's actual A actions, their real
verification feedback and verified correction targets. The two arms start from
the same actual parent parameters. Each completed 64 updates, 103,815 input
tokens, 393,216 padded positions, 16,094 head positions, 192 forwards and 192
backwards. Positive supervision covers 16,094 versus 9,780 positions. Internal
training wall times were 297.715 and 299.090 seconds; physical cost equality is
not claimed.

[Both actual weight manifests](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/1a75a7ccbc404b3d6f7baf2d9d7400b3c03a2b1d/qualification/cell-current-policy-credit-20261118/training-evidence)
were frozen before B2 was released. The constructor had already committed six
tasks from three new repositories and three maintainer groups, including six
passing reference checks and six rejected tautology controls. It independently
checked both manifests and the original weight-freeze file before
[releasing B2](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/1134793c60c1b9908eaf6e388f753860ee8917c4/qualification/cell-blind-panel-b2-20261118).

This is operational blinding between agents in a shared workspace. It does not
establish authenticated independent evaluator custody, absence of pretraining
overlap or real-user adoption. B2 is prohibited for training and candidate
selection.

The predeclared **108-call actual evaluation is running** on desktop job
`1a1ef401640-ffbe-455`: unchanged parent plus both updated students, two attempts
each on A, exposed B and B2. The original source is
`048014f8634059b65b24f49da7f00d5b1bb85737`; training retains source
`6a7696b0c0c5a0a2ba0fb52160aabb191850b2d3`. Selection uses the registered A-only
recovery/regression/final-success rule. No learning benefit is claimed before
the real executions and original readback finish.

## E6: namespace regression passes; original complete NoUpdate still fails

[The original native owner's Draft #6700](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6700)
has published its exact v8 history and originals. That lineage differs from the
joint research source; its results are not relabelled as joint-source execution.

Native-v8 source `f7e58512021c7481fa51809bb349f63d93bb1d6c` fixes a concrete
namespace error: a 169-byte CompletedLearning owner key exceeded the unchanged
128-byte limit. The scoped Initial-identity digest preserves full identities in
the record and changed-target refusal. The
[actual Root namespace regression](native-v8/root-completed-refusal-namespace.xml)
passes. The [whole cold NoUpdate test](native-v8/ordinary-whole-cold-no-update.xml)
still fails after 60.689 seconds at `cli.serve`. The
[complete v8 run record](native-v8/RESULT.json) retains preparation, commands,
binary provenance, source checks and successful cleanup.

Native-v9 source `ad21d6401fa307831b629b3e71ea1b9c3a350f83` adds static
error-only diagnostics with no gate, control-flow or deadline change. Its
[original NoUpdate attempt](native-v9/ordinary-whole-cold-no-update.xml) still
fails, now locating the earlier error at `historical.observe_complete_task`,
then `historical.worker` and `cli.serve`. The publication client sees
`POLLIN|POLLHUP` after that historical-operation error. This does not justify
weakening the poll guard. The [complete v9 record](native-v9/RESULT.json) retains
the failed attempt and exact source identity.

Complete native NoUpdate and Adopt remain unqualified. The existing cold case
authenticates retained C, not fresh D. D requires an actual newly admitted task
and its own original journals after recovery. Independent controller
authentication, FinalUse, settlement and full cost remain open.

## Chain: the stronger original business gate is still open

[Draft #958](https://github.com/TrillionniumFoundation/Trillionnium-Chain/pull/958)
retains the original 4-second/16-worker/0.25-CPU successes: x64 3.415648125 seconds,
ARM64 2.400575524 seconds, each with 7/7 accepted submissions and independent
replays. The stronger original F0 remains a separate workload: 30-second window
1/6 and 4-second window 0/6.

[The subsequent metadata optimization](https://github.com/TrillionniumFoundation/Trillionnium-Chain/actions/runs/44328450170)
also fails both original windows, 0/6 each. Its 42 planned packet exposures are
9 timely acknowledgements, 1 attempted without timely acknowledgement and 32 not
attempted. ACK is not final confirmation. All services are confirmed reaped.
[The complete original archive and independent reader](https://github.com/TrillionniumFoundation/Trillionnium-Chain/tree/e6af21fd47347ba900ef87842447ed6fe227a6f0/docs/development/evidence/chain-host-stat-20261118-2e9b)
verify all 443 original files and retain the exact native exit and business
failures. A small syscall saving cannot stand in for service liveness.

The next [actual native-delta candidate, Draft #960](https://github.com/TrillionniumFoundation/Trillionnium-Chain/pull/960),
retains full normalized before/after readback, cancellation rollback, identity
and permission checks, and the original task-output fallback. Its original
[F0 run](https://github.com/TrillionniumFoundation/Trillionnium-Chain/actions/runs/44335832525)
is pending. Unit/adversarial controls and strict Clippy do not replace that run.
Energy, provider, network, storage-time and other unmeasured costs remain unknown.

## Platform gates and continued execution

[Draft #6708](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6708)
fixes seven Mac fixture failures by using canonical ordinary temporary roots,
including the Circuit database reopen. Original store readback, no-contact
assertions, alias negative controls and production path custody are unchanged.
The pinned repository formatter passed; actual Mac CI validation is pending.
Windows' original positive business case and dependency advisory gates remain
failed. No assertion, denial rule or sandbox boundary was weakened.

The shared scratch executor became unavailable while the actual desktop
evaluation continued. This checkpoint was reconstructed from hash-matched
published originals and original remote native records; experiments were not
repeated because of that outage. Continue the same experiment IDs and original
business gates. Every unknown and valid research NoUpdate remains explicit.
