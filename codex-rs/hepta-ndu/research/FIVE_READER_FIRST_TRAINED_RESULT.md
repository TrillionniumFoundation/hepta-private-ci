# First completed pretrained response-learning and composition result

Date: 2026-10-13. PR #1697. Exact executed source:
`a87e56e6cfe6d2286cb8a59cd201e735576427fe`.
Run **38421445932**, job **115379521883**. The whole workflow FAILED at its
final legacy Encoder/Head smoke; completed earlier phases remain individually
identified, not relabelled as a successful workflow or independent experiment.

## Actual source and pretrained execution

All **219 tests passed**, zero skipped: 14 matrix, 54 contracts, 29 native,
61 Group, 28 response and 33 adapter/counter/replay tests. Python compilation
and exact original model/data artifact SHA verification passed. Official HF/PEFT
response learning and post-save NativeSession replay both completed SUCCESS.
These results are from the decoded hosted job log, not local execution.

Response study: **4 historical questions from 2 held-out source families**,
`locomo:conv-43` and `locomo:conv-47`, each under four input conditions and four
arms. All **64 planned rows** executed successfully: **48 actual model calls**
(frozen/aligned/shuffled) and **16 nonlearned always-refuse outputs**. There were
no unavailable oracle controls or execution errors. Only **3 of the 4 questions**
had an available benchmark answer target. The four conditions and repeated arms
are NOT new independent questions. All material remains previously exposed
public development; annotations are not human-reviewed semantic sufficiency.

## Outcome: unconditional refusal, not conditional reading improvement

For EACH condition (no evidence, lexical retrieval, annotated support plus
distractors, support removed), each arm had four rows. Frozen Reader produced
**0/4 prescribed refusals**. Aligned LoRA, shuffled-positive LoRA and the
always-refuse control each produced **4/4 prescribed refusals**. Thus both
learned arms refused **16/16** inputs, including those with annotated support.
Every arm had zero benchmark exact-body matches and zero syntactically valid
citations on these rows. Exact-body scoring is not semantic grading, and a
missing reference answer is not a judged error.

The negative control matters: correct target pairing did NOT produce a better
observed result than incorrect target pairing or unconditional refusal. The
empty-input instruction contract improved, but this sample supplies no evidence
of evidence-conditional answering, new reasoning or qualified Reader adequacy.
Do not adopt either candidate or pass a gate on refusal rate alone. This is a
bounded observed collapse, not a theorem that LoRA or shared encoders cannot
learn these tasks. The data are too small and previously used to support a
universal negative conclusion.

Keep this result frozen. Any training-objective change belongs to a separately
registered development experiment, with no checkpoint/threshold/hyperparameter
selection on these four evaluation outcomes. Examine training-only conditional
losses and a distinct validation split before future confirmation.

## Actual training, cost and identity

Each learned arm used 28 admitted training examples and **56 optimizer updates
with 56 observed decoder forwards**. Each processed **9,426 input tokens and
1,122 supervised tokens**, with **230,400 trainable parameters / 921,600 FP32
parameter bytes / 1,843,680 optimizer tensor bytes**. Two arms therefore performed
112 actual updates; they are not independent data replicates. Same token/step
counts do not establish matched total compute or energy.

Both started from adapter tensor SHA
`66331d48169f0843740cc1b16db0f13b903c98a4a5c3d453cdd4d58202f9a844`.
The original base tensor SHA
`30aeed70fe072d8e93242d177384cbfa758d6d84ae0b2228314e1b72663e6915`
remained unchanged; both saved adapters reloaded exactly. The aligned final
adapter SHA was
`dc965c1618f812c53bef5de94b7af0c53a2c7e28cd9481630b656a2d4493fd87`;
the shuffled final adapter SHA was
`75dd15dbbf2ab6d7229f921eb7e709ee2e6083faf818e6d68a60fb2f5b3ba8be`.

Observed training wall times were 48.884208281 seconds aligned and
49.250291942 seconds shuffled. These are that host/run's training region,
not a future duration estimate or whole-operation TCO. Energy/FLOPs/peak RSS
remain unknown; starting/ending RSS is not peak memory. Fixed arm order and
separate staging/loads remain charged limitations.

The response study recorded **843 inference decoder forwards**, separate from
112 training forwards, 32 replay forwards, prior fixture tests and the final
legacy smoke. Do not report 843 as the total cost of this workflow.

## Saved-composition replay

Four extra calls (one fixed historical question, two evidence conditions,
two saved adapters) all succeeded. All four had exact original answer,
input-token hash and output-token hash equality. **32 extra decoder forwards**
were observed. This proves that these particular saved candidates reproduce
the prior outputs through the native composition owner. Those outputs were
refusals; faithful replay is not reasoning improvement. Each arm retained one
model object; different adapters did not share a mutable PEFT base.

The loaded composed model had 134,745,408 parameters including 230,400 LoRA
parameters. It is the archived small Reader, NOT a 421M Laya comparison.

## Seals and retained evidence

Response plan SHA:
`c6a32fa6e823327f057b87da376b25d32b976e399a9e82eb0fba8854ed1771ad`.
Response raw SHA:
`23b18d34b7f9d56110ba0a6757caf89cf6d3d8fb52b336b7dd8c0c19ee34fc8e`.
Replay raw SHA:
`62cc5a696f5442935c9467ab56193785718f26c8bf1c534c1f0fe7e8ec4621b4`.

Hosted artifact **11825939763**, reported by GitHub as **1,911,695 bytes / 79
files**, ZIP SHA256
`5d474d84e8aa29b9cc6a4ea6d163cb1218e4f3f210c71af5df916f2fb41962cf`.
Source/runtime, raw answers, journals, checkpoints and failure output are
retained in that artifact; original pretrained weights are excluded. Local
rehashing was not possible because container/Python probes returned ClientError.

## Remaining concrete failure and next execution

The final legacy smoke reached Encoder construction in train_heads and failed
at `LocalEncoder` tensor inventory equality. Do not remove that check or assume
a new checkpoint. A focused pinned-material audit now reports actual saved
keys, loaded state keys, buffers, shapes and exact equality, then attempts the
unchanged strict loader. It uses the original archive and fails unless strict
verification passes. This is diagnostic execution only, not training or review.
No source namespace remapping or ignored tensor exemption is inferred without
actual material evidence. The five independent causal experiments, human-reviewed
Reader sufficiency and deployment admission remain uncompleted.
