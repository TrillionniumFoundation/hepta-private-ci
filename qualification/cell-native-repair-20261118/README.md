# Native-turn recovery and matched retrieval controls

The retained 60-call diagnostic run produced 33 format rejections. Its second
Cell receives the previous action inside a tool JSON object. Native trajectory
training instead represents that action as an assistant turn followed by a tool
observation. This experiment changes that explicit communication representation
and measures the resulting execution, recovery and regression rates.

The existing `bundled_v4` default remains byte compatible. An explicit
`native_turn_v1` option shares the original task history, the preceding Cell's
unaltered assistant action, and the same stable measured verifier feedback.
Removing the answer edge removes that assistant action. Removing feedback keeps
only a task-continuation instruction, with no outcome counts or success flag.
The receiver is always given the original task input and the same paid verifier
opportunity. No answer is repaired or extracted after model generation.

## Frozen comparison

The common source parent is `4d9fc82c1efff45f964d4efdc6155b350e01fd23`.
The three original Run02 adapters F, T and C, model tensor checks, provider,
verifier, four diagnostic tasks and output-selection rule remain in use.
Every arm receives two model-call opportunities and pays for both. Caps are
4,096 input tokens, 384 output tokens and 2,048 relayed content bytes per call.

| Arms | Message representation | Reference access |
| --- | --- | --- |
| bundled FF, TF | Original tool JSON | None |
| native FF, TT, CC | Assistant action then tool feedback | None |
| native TF, CF | Same native turns between two adapters | None |
| native TF without answer, without feedback | Individual actual message removal | None |
| native FF retrieval, native TF retrieval | Same native turns | Same single A reference |

Eleven arms over four tasks require **88 actual generation calls**. All arms
are reported; no winner is selected to change the models or route. The original
earliest-business-success output rule is retained, with first/last success,
0-to-1 recovery and 1-to-0 regression reported separately.

Retrieval ranks only visible input terms against the six original authorized A
training tasks. Integer Jaccard overlap is maximized, with the complete training
record digest breaking ties. One retrieved task and its verified answer are
shared identically by both retrieval arms. Evaluation targets, trajectories,
verifier parameters and other evaluation records are excluded. The six A
answers are freshly verified before generation; those six verifier calls and
reference-preparation costs are retained separately. Retrieval adds input work,
so common caps do not imply equal measured costs.

These four same-project diagnostics have already been exposed. They measure a
communication mechanism and strong single-model controls; they add no new
independent user, teacher or future-task evidence. E5 authenticated user growth
and independent E4 confirmation retain their existing open status.

## Run

Use the existing `diagnostic_run_v4.py` provider arguments with the new
`--study repair_retrieval` option and a fresh output directory. The runner
retains the training-reference verifications and selections in `RETRIEVAL.json`,
the complete source/model/arm freeze in `FREEZE.json`, every original request,
model output and real verification, and the owned provider's terminal receipt.
The result adds the six reference verifier calls to its explicit extra-cost
scope. Raw wall-time scopes overlap and must not be summed as a total.

## Engineering validation

Before formatting, 14 tests passed across the existing Circuit runtime,
native-turn actual repository execution, retrieval controls, and provider
stdio lifecycle. The native-turn test verifies that both edges are needed for
a scripted recovery, removes each from the actual receiving request, and checks
that the evaluation answer never reaches the provider. These scripted controls
are separate from the real model run. `just fmt` completed successfully.
