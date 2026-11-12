# Frozen base-only output semantics diagnostic

This is a newly precommitted diagnostic on the same 24 public operator-written
OOD tasks. It is not the original nine-condition / 216-generation experiment:
only the frozen base is loaded; no LoRA is downloaded, recreated or substituted.
Independent future confirmation, retention and adoption remain HOLD.

## Why run this stage

The old scorer compares only the next-token logits for `" yes"` and `" no"`.
Their conditional probability does not describe their combined mass in the
full vocabulary, nor the validity of an unconstrained generated answer.
This diagnostic records those missing quantities and compares them with the
unchanged eight-token greedy output, counting invalid output as incorrect.

## Frozen identities and execution

[BASE_OUTPUT_PLAN.json](BASE_OUTPUT_PLAN.json) freezes the official
HuggingFaceTB/SmolLM2-135M-Instruct repository at
`12fd25f77366fa6b3b4b768ec3050bf629380bac`, three original base artifact SHA-256
identities, all downloaded auxiliary files, runtime, public task hashes,
outcomes and an aggregate 1 GiB download limit. The official revision was read
from the [model API](https://huggingface.co/api/models/HuggingFaceTB/SmolLM2-135M-Instruct)
before this plan was published. Every download must match the frozen original
weight/config/tokenizer digests before model inference.

The model's auxiliary tokenizer and generation files are newly fixed by this
official revision and the PREEXECUTION manifest. The older experiment did not
retain all their identities. Equality of three original digests must therefore
not be described as complete equality of the original loading environment.

Python 3.12.3, Torch 2.9.1+cpu, Transformers 4.57.3, CPU float32/eager, four CPU
threads; no chat-template or question changes. An inherited non-neutral greedy
configuration fails preflight instead of being silently cleared. The new
runtime contract validates the effective config before the first forward.

The source-head workflow triggers once on push to this isolated research
branch, with a 20-minute timeout. It first runs frozen-input/result tests,
then downloads and validates the model, records PREEXECUTION, and performs
24 scoring calls and 24 generation attempts. It keeps raw rows, per-attempt
start/completion records and output tokens, plus full stdout and process cost.
Partial output never counts as a completed 24-task result. It does not launch
the inaccessible original eight adapters.

## Interpreting results

- Primary denominators are all 24 unique public tasks; independently held
  future tasks are zero. Invalid free-generation answers remain incorrect.
- Report conditional two-choice scores, full-vocabulary label mass (also log
  mass), label ranks, top token, generated text and every seed-free base row.
- Probability drift from the historical base is descriptive; auxiliary files,
  host and transitive runtime dependencies were not originally fully pinned.
- The two inference procedures have different work counts. Report each cost;
  their elapsed-time difference is not a scheduling-efficiency gain.
- External `time -v` covers the Python process, while dependency installation,
  CI queue, energy and owner costs remain separate.
- No threshold, label, prompt or parser is chosen from these outcomes. No
  claim about eight-adapter benefit, independent future B, old capability
  retention, human/owner approval or production suitability follows.

Current state at source publication: **NOT_STARTED / HOLD_NO_GO**.
Actual results must be read from this source's job and retained original data.
