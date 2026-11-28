# Opaque correction batch and context audit

## Pinned scope

Baseline: `ab63fa79e11ce295a5bfbbe3f56120b62d4fcbbe` (PR #7256).
This qualification covers the Python opaque-observation consumer and native-chat
encoder. It is not evidence of real-user consent, signed native labels, native
owner ingestion, a model fit, cross-user benefit, adoption, or FinalUse.

## Reproduced failures

`OPAQUE_V1_BASELINE_REPLAY.json` records execution of the original production and
fixture code extracted from that exact baseline. Source originals remained byte
identical. The independent fixture records reproduced four failures:

1. An opaque example and an ordinary example each encoded individually, but their
   legitimate mixed batch was refused with `schema mismatch`.
2. Adding unbound `task.messages` put the corrected answer into the context while
   source verification and encoding still succeeded.
3. A training prefix ending with the student's failed assistant answer encoded
   successfully although the same inference prefix was refused for lacking a
   subsequent user or tool observation.
4. Appending an unbound environment observation containing the corrected answer
   made that answer available in the trajectory training prefix.

## Changes

Batch dispatch retains ordinary records' collective admission, bounds, input
order, duplicate-ID rejection, split checks, authorization checks, and masks.
Opaque observations can now participate in legitimate final-answer batches.

The opaque source profile binds one prompt and one observed answer, not a complete
history. It therefore refuses `task.messages` and supports `final_answer` training
only. Original failure/correction records remain retained as evidence; their
unbound event history is not converted into training context. Restoring opaque
trajectory training requires a separately specified and verified source profile
that binds the actual recovery observations and ordering.

Every supervised native-chat prefix now passes the same `render_prompt` boundary
used for inference. Ordinary records with actual fixture feedback remain supported;
the guard against assistant-only recovery prefixes remains enforced.

## Execution evidence

`ENCODER_RESULT.json` and `ENCODER_TESTS.log` retain an intermediate 33-test pass.
That run preceded discovery of the additional environment-observation injection;
it does not establish closure of that later finding.

`ENCODER_FINAL_RESULT.json` and `ENCODER_FINAL_TESTS.log` record the final 41-test
run, including the opaque source validator's existing controls and both context
injection regressions. Result: 41 passed, zero failures/errors/skips, 0.157 seconds
reported by unittest and 0.372602885 seconds measured around the subprocess, with
a 30-second timeout. All Python sources were hashed before and after execution
and remained unchanged during the run. `just fmt` completed successfully before
this final execution. The result file binds exact tested source hashes and the
raw log hash; a later publication commit is not represented as an execution host.

Reproduce from the repository root:

```sh
PYTHONPATH=scripts python -m unittest \
  cell_experiments.test_opaque_batches \
  cell_experiments.test_opaque_context \
  cell_experiments.test_paired_opaque_teacher \
  cell_experiments.test_opaque_teacher_data \
  cell_experiments.test_chat_protocol \
  cell_experiments.test_data \
  cell_experiments.test_paired_source -v
```

## Remaining boundary

This patch closes specific data-admission and encoding failures. The native
paired owner still has its own schema, signed-label, permission, evaluator, and
learning gates. A synthetic encoding control must not be promoted into evidence
that those gates accepted a live external teacher or that a new user benefited.

## Complete Python discovery and CI dependency repair

The original hosted engineering job discovered 339 tests and ended with one
import error: `test_sdk_capture` could not import the repository's Python SDK.
The workflow now includes `sdk/python/src` in `PYTHONPATH` and pins Pydantic
2.13.4 from that SDK's checked-in lock. SDK source and dependency changes also
trigger this integration job. No test was removed or skipped to repair the gate.

The original discovery command then ran at local source commit
`06b1889ae08978a905f1dc31373099013ef7647b`: **350 passed, zero failures, errors or
skips**, 378.629 seconds reported by unittest and 383.859732497 seconds measured
around the subprocess. The original failed import counted as one discovery item;
the repaired SDK module contains twelve real test methods. This explains the
339-to-350 inventory change without deleting or adding application tests.

`FULL_PYTHON_RESULT.json` and `FULL_PYTHON_ARCHIVE.json` bind the result and archive.
The archive retains complete source hashes, raw output, dependency versions, the
original hosted failure, and the earlier local 47-control run that lacked Torch
(one error and two skips). The final run used the existing pinned CPU profile,
including actual local tensor updates, cold loads and two-Cell relay controls.
It remains an engineering fixture execution, not scientific or production
learning qualification. The updated hosted job must report its own outcome.
