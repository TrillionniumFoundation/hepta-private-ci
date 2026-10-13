# Observe decoder dispatch, not the bypassed outer PEFT training hook

Date: 2026-10-13. Parent: `995e479f3091e5695958c2f0a94e98d6b9c09570`.
Continuation of PR #1697. This is a measured-work repair, not a new training
objective, model, dataset or qualification rule. Original test assertions stay.

## Actual completed predecessor execution

Native run **38387996492**, job **115264430514**, exact source
`e1ccb07f03da831dbd183759c1425a5e165d0180`, completed FAILURE during this turn.
Unlike the earlier Group failure, all **14 matrix + 54 contract + 29 native +
61 Group tests passed**. The newly reached response suite then ran **19 tests:
18 passed and one failed**. No tests were skipped within these suites. Model
artifact acquisition, pretrained response learning and original smoke remained
skipped because the combined test step correctly failed.

The failure is the UNCHANGED assertion in
`test_real_adapter_optimizer_mask_and_saved_reload`:

    self.assertEqual(receipt["training_forwards"], 4)
    AssertionError: 0 != 4

The tiny random Llama fixture actually optimized and saved/reloaded LoRA before
that assertion. The zero counter is not a failed optimizer or a pretrained
learning result. Its prior tensor checks do not prove natural-task ability.
The log also contains PEFT's existing peft_config/unload/reload warning. A warning
alone is not evidence of tensor mutation; original base and adapter equality
checks remain. This repair does not suppress the warning or delete metadata.

Retained artifact **11808574259**, GitHub-reported 78,241 bytes / 27 files,
SHA256 `ddf3942623ae41f58d5219b7b3ed1083461b16acc6610f6a276e81a86e831d31`.
It was not locally rehashed in this turn. The separate Group workflow
**38387996412** succeeded on the same source with the 158 tests listed above;
these two runs are not extra independent samples or current-patch validation.

## Cause and correction

Pinned PEFT 0.17.1 BaseTuner.forward calls `self.model.forward(...)` directly.
A forward-pre-hook on that outer causal LM therefore does not run in this
training path. The causal LM still invokes its decoder backbone through
Module.__call__. Hook `model.get_base_model().base_model` instead. Require a
real distinct decoder module; do not silently accept an unrecognized owner.

The receipt and training plan now record
`causal-decoder-backbone-forward-pre-hook-v1` and the actual owner class. Each
completed optimizer event records its observed decoder-forward delta. A Python
exception after dispatch records the observed count and elapsed time in an
optimizer_failed_or_unknown event and is re-raised, without retry or success
receipt. Host termination can still leave only a started event; that remains
unknown rather than free work.

The fixed existing training profile has no activation checkpointing or extra
forwards. Its measured total must equal completed optimizer steps, but the
counter is NOT assigned that step count. A mismatch fails. Training examples,
source-family split, initialization, dropout policy, loss masks, optimizer and
epoch count are unchanged. The generation counter in the composed Reader is
separate: generate invokes its causal model through a different dispatch path.

## Four additional regressions, all submitted

`test_five_reader_adapter_counters.py` uses the existing tiny random Llama and
actual PEFT library. It checks that the old outer hook sees zero while the
decoder sees one; two epochs produce eight observed forwards and eight per-step
counts; a failing decoder retains one attempted forward and removes its hook;
and unknown/self-referential owners are rejected. This filename is already
covered by the native workflow's adapter test glob. The original failing
response test and all preceding suites remain required and unmodified.

Local container/Python execution is still unavailable with infrastructure
ClientError. No new test pass, trained pretrained candidate, token-replay result
or independent five-experiment completion is claimed for this patch.

Primary pinned implementation sources:
- https://github.com/huggingface/peft/blob/v0.17.1/src/peft/tuners/tuners_utils.py
- https://github.com/huggingface/transformers/blob/v4.57.1/src/transformers/models/llama/modeling_llama.py
