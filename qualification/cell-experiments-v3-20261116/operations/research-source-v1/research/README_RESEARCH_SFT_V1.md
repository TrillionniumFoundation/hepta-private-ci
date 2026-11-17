# Research SFT v1 implementation handoff

This package implements the separately approved post-failure authored-target
study. It leaves native qualification closed and contains no experimental
training result. The full rules are in RESEARCH_PROTOCOL_V1.md.

## What changed

Four new modules handle research admission, training, collection/evaluation and
coordination. They bind the complete real parent03 baseline with A=0, accept only
the six authorized authored A targets backed by original/control business checks,
and freeze four plans before any fit. A=0 retrieval is explicitly populated from
authored A. The new model schema is rejected by the unchanged native candidate
validator. All qualifications remain false and candidate_selected stays null.

The actual numeric loss, parameter hashing and round-robin fit loop are reused
from the frozen original. Training still has 64 steps per arm, 1536 sequence
positions and the original LoRA/optimizer/device policies. Reference calls now
save separate durable intent/receipt records so a later failure cannot erase
earlier measured work. The retained ledger preserves corrupt-byte identities,
known subtotals and unknown tails and never counts a batch summary twice.
After train returns, evaluation releases unused cached tensors before the
unchanged 4 GiB device check.

RESEARCH_VS_ORIGINAL_TRAIN.diff shows the source changes. NUMERICAL_KERNEL_DIFF.json
records exact AST equality of the numeric loop after making pad_token_id an
explicit argument. It is supplementary evidence, not a replacement for actual
tensor execution.

## Actual engineering verification

Exactly one behavioral suite and one CPU tensor suite ran with the existing
pinned HOME venv, -I -B, CUDA_VISIBLE_DEVICES="" and offline settings. Each child
had a 300-second limit.

- Behavioral: 12 tests passed, 0 failed/errors/skips; 0.974 seconds in unittest.
- Tensor: 1 test passed, 0 failed/errors/skips; 7.631 seconds in unittest.
- Both child exit codes and the owned controller PTY exit code were 0.
- No retries, no additional dependency installation and no original helper-test
  rerun occurred.

The actual parent03 read-only case verified all retained baseline/source fields,
A=0, nine A/B records, nine retrieval prompts and the pinned HOME runtime. It did
not execute a verifier or load a model.

The numeric case created a random tiny Qwen2 configuration and real PEFT LoRA
adapter on CPU. It ran the same production fit_steps for 64 updates, 98304 padded
positions, 414 input tokens and 128 supervised tokens. Real selected CE agreed
with dense CE. Parameters changed, AdamW state reached 64, the six group updates
were [11,11,11,11,10,10], and the new adapter loader restored exact logits from disk.
Only that fixture's base-loading boundary was synthetic. The native-generation
path and full pretrained CUDA fit were not exercised.

PEFT emitted its expected warning that the randomly created tiny fixture had no
pretrained config path when saving. The warning is preserved in actual stderr.
It did not skip or substitute the tensor checks.

These fixture steps are not real research fits, new user samples or task successes.
No real Qwen generation, pretrained-weight/tokenizer loading, GPU execution or
authored business verifier call occurred in engineering.

## Evidence and launch

CPU_ENGINEERING_01.zip is a separate complete evidence archive: 372 retained
regular files plus its full index, 373 ZIP members. It includes test sources,
raw fixtures, actual logs/exits, numeric adapter/optimizer bytes and results.
The deliberately created path-guard fixture symlink is recorded as metadata;
its real-source target was never traversed into the archive.

The archive SHA is:
78629fbaf830a733e09a77b733e33ec38546c57daa2f8899f5a8f28902794381

CPU_ENGINEERING_01_RECEIPT.json records the independent Mac archive verification.
CPU_ENGINEERING_TERMINAL_01.json preserves the actual tool-observed terminal
state, full available output, EXIT 0 and output_complete=true.
RESEARCH_ENGINEERING_SUMMARY_V1.json gives the key exact result hashes.

LAUNCH_INPUTS_V1.json contains exact argument arrays for root's optional read-only
preflight and separate real run. Preflight uses its own create-only output, so
it cannot consume the actual run directory. The real run is owned solely by root;
this handoff does not launch or authorize an additional run.

The diagnostic rule freeze is a separate reviewed package. Its exact file and
adjacent code hashes are pinned in the launch inputs before any fit.

## Limits

CPU engineering establishes numeric and artifact wiring, not CUDA capacity or
task improvement. A real 1.5B CUDA fit can still fail under the unchanged memory,
wall-time, sequence or output budgets; such failure must be retained without
retry or outcome-dependent adjustment.

These are already exposed development tasks. The study is explicitly designed
after observed baseline failures. Equal padded steps do not imply equal supervised
tokens or compute. Reused controlled feedback is not experience from an updated
student. Cold repeats add no independent sample. No generalization, multi-teacher
complementarity, source-growth scaling, Circuit, adoption, new C or PoUW conclusion
is supplied by this package.
