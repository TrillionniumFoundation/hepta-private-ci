# Matched-information E1 candidate

The completed 128-update / 96-call result is in [RESULTS.md](RESULTS.md), with
machine-readable raw-receipt validation in [READOUT.json](READOUT.json). All four
arms fail all six upstream tasks; the research selection remains NoUpdate.

The historical answer-only and trajectory fits used different visible training
histories. This candidate isolates a narrower causal question: with the same
complete A trajectory information and model computation, does supervising every
assistant action improve downstream behavior over supervising only its final
answer?

Both fits start from the same pinned Qwen2.5-Coder-1.5B-Instruct base, fresh rank-4
LoRA initialized with seed 1729, AdamW settings and 64-update schedule. Every
original trajectory turn is tokenized with the existing native chat encoder.
Both objectives execute every identical padded input, selected language-model
head position and backward graph. In the final-only arm, losses on preceding
actions receive weight zero. Its final target still sees the same prior history.
The all-actions arm supervises all declared assistant actions. Observation tokens
remain masked. Consequently this final-only arm is an information control and
must not be conflated with the earlier short-context answer SFT.

An independent dense cross-entropy calculation verifies each objective's actual
parameter gradient. The test also observes identical forward arguments, head
positions and backward counts, and confirms the input groups are unchanged.
The actual run must additionally match initialization hashes, complete encoded
groups and all 64 per-update work shapes before any candidate evaluation.
Physical wall time and energy are measured where available; equal tensor shapes
do not assert equal physical cost.

Only the original six authorized A references may train. They remain authored
references and are not promoted to additional external teachers. Each reference
is executed again before fitting. Six external-source tasks from Requests,
Werkzeug and Click remain forbidden to training. Their source, records and
comparison protocol are frozen before new candidate weights are generated.

Evaluation uses four fixed arms: frozen base, frozen base with deterministic
A-only trajectory retrieval, final-only supervision, and all-actions supervision.
Each arm executes two actual model calls and two original business verifications
per task, for six A-retention and six upstream tasks: 96 planned model calls.
The first, last, selected, recovered and regressed outcomes are all retained.
Retrieval searches all six A records using input-only token overlap, takes one
complete reference trajectory and charges the resulting input tokens. Neither
reference answers from the upstream panel nor its observed model results enter
training or model selection.

Original requests, raw model outputs, verifier receipts, training steps, adapter
manifests and failures are retained. This is a research candidate: source groups
are not independent users, pretraining overlap is unknown, energy may be unknown,
and no journal state grants native owner adoption, FinalUse or settlement.
