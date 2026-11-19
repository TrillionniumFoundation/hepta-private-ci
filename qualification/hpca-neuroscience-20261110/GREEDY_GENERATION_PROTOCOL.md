# HPCA V2: frozen greedy free-generation contrast (research-only)

**Protocol frozen before executing inference.** Source parent: PR #5997 HEAD
`65ae9883e1a1dc1618f27f519fdb7672f4b51189`. This new protocol is a
descriptive diagnostic on the SAME public operator-created 24 OOD tasks,
not independently held future B, not product C, not Owner-attested action/effect
or a production-ready result. Never use this evidence to Adopt.

## Ex ante population and controls

Use EXACT OOD plan from #5960 (24 tasks, four families, balanced yes/no),
original actual V2 training result SHA256
`9512849b90964c35951bb8bb2226b3f2f6d3ec0da1e9a3b98467c8970afbe39c`,
and actual binary-score OOD result SHA256
`3002553ec485b19247f510863e9c78d2cce7747434ad7737f68b7dd3f9a74a2a`.
Model is the same 134.5M SmolLM2 base and eight immutable V2 LoRA adapters;
training is not repeated. Four seed pairs: 11,17,23,29.

For all nine model conditions, prompt is the original question stripped at
both ends followed by newline + `Answer:`; do not prepend a new instruction.
Free decode WITHOUT restriction to yes/no tokens: greedy `do_sample=False`,
`num_beams=1`, `max_new_tokens=8`, EOS stopping, tokenizer native special
tokens, CPU float32, four PyTorch CPU threads, zero GPU. Prompt/label identity
must match the original frozen two-choice data; checkpoint hashes must match
the original training report. Same model conditions and tasks as the binary
scorer; compare **different inference procedures**, not equal resource cost.

Primary readouts (all preselected): number/percentage of 24 answers whose
generated text STARTS (after optional whitespace) with standalone yes or no;
accuracy on all 24 counting invalid responses as wrong; agreement with original
two-choice predictions, tokens emitted and process wall/CPU/RSS/I/O costs.
A buried yes/no or prose without a leading label is INVALID, not remapped
using answer key or a posthoc parser. Report every seed and both cadence arms,
including negative outcomes. No model or arm will be chosen from these scores.

## Acceptance boundaries

One observed real decode does not validate external evaluator, source ownership,
actual ACT/CTRL effects, memory deletion/recovery, multi-seed training superiority,
NoUpdate/Adopt, persistent production owner or Core x NDU 2x2. All remain HOLD.
Source/script/result/logs should be committed with exact file hashes. Re-run
the precommitted parser tests and audit all 216 output rows before interpreting.
