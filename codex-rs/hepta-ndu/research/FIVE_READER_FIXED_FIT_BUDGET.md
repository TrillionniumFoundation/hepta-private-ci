# Fixed optimization-dose experiment and response-target audit

Date: 2026-10-14. PR #1697. Parent: 5fdb607484785e8ce78781808dda18866ef35709.
At publication this implementation and its 25 regression definitions are
submitted, not yet tested on the target runner. Current local container and
Python probes returned ClientError; no local test/model result is claimed.
Existing result records and source-time experiment remain unchanged.

## Question, not a broad architecture matrix

The previous paired result did not satisfy the target preference even on its
14 training pairs after 28 optimizer updates. That does not distinguish an
optimization-dose shortfall, a response/citation scoring mismatch, weak input
annotations, or model/adapter expressivity. In particular a normalized score
for an answer PLUS long source identifiers is not interchangeable with the
probability of beginning that answer under greedy generation.

This study fixes five arms before new results: frozen Reader; aligned 2 epochs;
shuffled 8 epochs; shuffled 2 epochs; aligned 8 epochs. The two-by-two trained
contrast separates increased optimization from correct target pairing. Both
8-epoch arms receive the same larger dose. The frozen arm measures the initial
answer behavior. There is no adaptive stopping, threshold/seed/checkpoint search,
intermediate SELECT-based choice or automatic candidate selection.

All arms use the SAME source-session-date projection, already implemented and
unit-tested in the parent, after the same document selection. This does not
condition the experiment on the still-pending date-study outcome. The source-time
lane remains the separate comparison of input representations. Old content-only
and first refusal-collapse results are not rewritten or reclassified.

## Unchanged model and trainer

The new driver calls existing fit_response_adapter with epochs=2 or epochs=8,
within its existing 1..8 bound, and the existing paired-evidence-margin-v1 loss.
Base, q_proj/v_proj LoRA rank4/alpha8, learning rate, seed, masks, decoder and
save/reload verification are unchanged. No larger model, new vocabulary,
additional optimizer, serving owner or hidden reference-answer input is added.

For the retained 14 training pairs, planned updates are 28 versus112 per arm;
actual counts are checked against the admitted cohort and reported, not assumed.
There are four scored forwards per paired update under the inherited objective.
The initial adapter tensors must match. After completion, actual optimizer
journals must establish that the short arm's example schedule is the prefix of
the corresponding long arm's schedule. This does not claim that unrecorded
intermediate parameter tensors were independently checked.

This is an optimization-dose comparison, deliberately NOT equal compute. Longer
training, both shuffled controls, staging, independent model loads, free
predictions and post-generation scoring all cost resources. Unknown energy,
FLOPs and peaks remain unknown. Same-composition serving reuse is unchanged;
these offline arm backends are separate model objects.

## No new test leakage or evidence laundering

Use the original source-family TRAIN/SELECT choices, identity-selected before
label eligibility, with the same no-replacement admission census. Original
TEST families are excluded. SELECT is already exposed development validation,
not newly acquired or untouched evidence. Source-date text is not an inferred
event/ask date. Nonempty distractor input is not declared semantically insufficient.
The existing exact-body/citation-format readout remains unchanged.

For each arm, all free generations are sealed before teacher forcing or scoring.
The ordinary model generation request contains no target. Failed, unavailable
and timeout rows remain in the fixed census. All successful candidates remain
unadopted regardless of outcome; independent semantic Reader qualification is
still mandatory for downstream efficacy claims.

## Six scored sequences per eligible pair, not six new tasks

reader_fit_audit uses the exact original four compiled sequences and additionally
scores the benchmark answer with ONLY the specifically appended delivered-source
citation suffix removed, under support and empty context. Prefix token IDs must
remain equal. Bracketed content inside the benchmark answer, including negations
or dates, is never stripped. No arbitrary regex normalization is performed.
Missing/noncanonical suffixes fail rather than guessing an easier target.

These two uncited targets are TEACHER-FORCING ABLATIONS ONLY. Training, generated
answers and final quality scoring still require the original answer/quotation
behavior. Removing a suffix changes EOS position and token boundaries; the
uncited score difference is therefore explicitly NOT an additive attribution of
loss to citations. It supplies a separately named diagnostic comparison, not a
higher-quality score substituted into the original result.

Every response token records its causal one-shift log score and top1 ID. The
first answer/refusal divergence compares the two candidate-token logits from
ONE forward at a genuinely common prefix, also recording whether a third token
wins and whether greedy decoding would reach that prefix. A positive pairwise
logit alone does not imply the answer token is the actual next generated token.
Teacher-forced exact-path matches are distinguished from actual free output.

The four original mean scores are checked against the existing HF scoring path
in a tiny real-model regression. All audit calls require frozen eval weights;
weights are rehashed afterwards. Each pair gets a durable start/result record,
actual observed forward counts, measurements and failure status. Failure rows
remain in counts; reported means are explicitly conditional on successful scoring.
Failed setup or integrity checks make the study nonzero, never a green verdict.

## Execution and evidence

The dedicated read-only workflow requires the inherited source/Reader/Group/
legacy-buffer/source-date suites plus the 25 new tests, then runs this study.
It does not retrain obsolete experiments merely because new files were added.
It retains generating source, all outputs, audit records, optimizer journals,
adapters and failure logs while excluding the original model/data directory.
The whole job has a bounded execution deadline; individual slow calls retain an
observed timeout result but are not claimed to have a per-call OS watchdog.

python scripts/memory_cell/reader_fit_budget_trial.py ORIGINAL.zip \
  --work NEW_MATERIAL_DIR --output NEW_RESULT_DIR

Primary loss definition checked for the causal shift and prompt masking:
https://raw.githubusercontent.com/huggingface/transformers/v4.57.1/src/transformers/loss/loss_utils.py

## Interpreting the eventual result

Training gain without SELECT gain is not generalization. Mean full-target gain
without body-only or actual branch/answer improvement suggests a readout issue,
not task success. Aligned-versus-shuffled comparisons at both doses are essential;
more frequent answering alone can be an always-answer shortcut. Even a successful
8-epoch fit remains a historical small-Reader development result, not a421M Laya
comparison, independent semantic grounding or closed Group/NDU/multimodal result.
The five independent causal experiments and production adoption remain open.
