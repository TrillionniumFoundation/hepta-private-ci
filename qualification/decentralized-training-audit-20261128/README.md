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
