# Source-writing completion projection

This is an opt-in compute implementation for the existing source-only writer,
not a new memory objective, knowledge representation or acceptance path.
The default remains `full`. `--loss-backend supervised_positions` uses exactly
the positions whose next token is supervised, including the EOS target. The
entire input still traverses the decoder with its prompt gradients intact.

The full and selected implementations have the same single-example cross-entropy
objective in exact arithmetic. Different matrix shapes can produce floating-point
differences, so deterministic conformance is measured rather than assumed.
The bounded CPU path requires Qwen2's `logits_to_keep` interface; other models,
malformed/partial supervision and a model ignoring the selected shape reject.
No silent fallback, batch packing, new optimizer, gradient accumulation or
normalization change is introduced.

The source-only writer retains the current scope-round-robin schedule,
128-update / 65,536-input-token ceilings, target construction, AdamW settings,
clipping, original source dependencies, quarantine and immutable snapshot loading.
Read/generation/scoring implementations are unchanged. The pre-run write plan,
training record and actual progress identify the chosen backend and its projected
positions. Input-token costs always count the FULL input, not just its supervised
suffix. The backend is a compute implementation identity, not serving authority.

## Validation layers

1. `test_source_completion_loss.py` uses an authored causal network to verify
   loss, gradients, updates, prompt dependence and malformed-input rejection.
2. `test_source_completion_writer.py` extracts the actual writer method and uses
   explicit dependency fixtures to verify unchanged scheduling, accounting,
   frozen parameters, source roots and failure quarantine. This is not PEFT proof.
3. `check_source_completion_qwen.py` runs in a NEW process with actual pinned
   Transformers 4.57.1 and PEFT 0.17.1. Twelve paired random-Qwen2 updates cover
   float32/BF16, eager/SDPA, prompt gradients and exact frozen tensors. Missing
   libraries fail. These random small models do not establish pretrained speed.
4. `source_completion_probe.py` loads the original publisher-pinned Qwen-3B and
   performs only two paired updates from the beginning of the original source
   schedule. It uses independent optimizer states, alternates order, records
   full token costs and measured update durations, and restores the initial
   adapter. This is not a completed memory write, downstream task evaluation,
   warm-cache benchmark or proof across every input. Its numeric tolerances
   are written before execution and failures cannot be converted to passes.
5. A full source-only write, separate-process reload and original seven-arm task
   run remain necessary to establish the final learned artifact's behavior.
   No production activation follows from numeric conformance or faster writing.

```sh
PYTHONPATH=scripts/memory_cell python3 -m unittest discover \
  -s scripts/memory_cell -p 'test_source_completion*.py' -v
PYTHONPATH=scripts/memory_cell python3 scripts/memory_cell/check_source_completion_qwen.py OUT
PYTHONPATH=scripts/memory_cell python3 scripts/memory_cell/experience_write_trial.py \
  write SOURCES MODEL OUT --source-sha SHA --stage-sha SHA \
  --loss-backend supervised_positions
```

Use a new output directory. The full source workflow is not implicitly converted
by the new CLI option. The pinned-library and complete inherited regression
workflow retains repository formatting as a failure gate. Pretrained probing is
manually dispatched after its initial bounded execution, so formatting-only
pushes do not restart expensive model work. Any temporary formatting writer is
confined to a separate inspected branch and removed before integration.

No complete Qwen speedup, task advantage, semantic citation precision,
independent future window or production qualification is implied by this change.
Keep the negative historical learned-policy result and stronger deterministic
organizer as controls. Original source retention and maintenance costs do not
vanish when vocabulary projections are omitted.
