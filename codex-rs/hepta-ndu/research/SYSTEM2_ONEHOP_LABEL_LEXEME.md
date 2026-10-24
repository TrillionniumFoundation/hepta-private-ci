# Neutral label-lexeme control for a frozen one-hop Reader

Research-only extension of draft PR #1546. This module is not a new model,
trained Cell, NDU/FBSDE method, or production serving change.

## Confirmed parent evidence

The completed label-field experiment, GitHub run 38273406637, evaluated
140/140 real responses on only 20 exposed synthetic device/token questions.
The source artifact was externally pinned by SHA256
a278014bae564336fc4d63335154cadbf14febc73620d958f45648b17ca0622a;
all 25 internal members and the raw seal
6f630a86d374658049377d4611f92fd6c0dd6626c267eef7c37d77f07f5aeaa2
were independently revalidated. Under a fixed answer-only prompt, labeled
single-fact / target-and-decoy / decoy-only inputs produced 12/20, 12/20,
10/20 label-list echoes respectively; unlabeled conditions each had zero.
All labeled/unlabeled conditions had ZERO exact answered tokens and ZERO exact
abstentions. Each labeled prompt had five more input tokens per evidence
item, so removal is NOT a pure zero-cost lexical intervention.

## Next isolated experiment

Keep the SAME frozen Reader, prompt, evidence, question, JSON label FIELD,
selection, source time/scope, greedy 64-token decoder and 1024-token ceiling.
Replace only label VALUES E1/E2 with R1/R2. The baseline E-labeled prompt is
compiled with the same tokenizer for every request. Input token parity or
difference is observed, not presumed. No output labels, pre-trained model,
answer annotations or parent Reader responses enter online source selection.

Use the original twenty already exposed questions, three conditions
(single fact; target plus one competing Token; irrelevant Token only).
Total: 20 x 3 = 60 new model attempts. The no-evidence condition has no label
to rename, and is not rerun. A complete raw-answers SHA256 seal precedes
any scoring of exact answer, target literal, label echo, correct refusal,
unsupported copying, or observed token costs. Failed attempts retain the
planned denominators and unknown work.

This is an explicitly non-qualifying mechanism control; if changing E to R
changes echo patterns, that is NOT proof of grounded Reader adequacy.
The earlier same-question labeled/unlabeled experiment also changed prompt
length and cannot establish a general causal label effect. A strong independent
Reader comparator and independently reviewed real evidence remain required
before any reasoning or NDU/FBSDE claim.

## Execution

The isolated GitHub Actions workflow verifies the already completed
cardinality parent (artifact 11756357532, SHA256
9f4a4ed9429212b98befffca27a297780d61317eaed8be519b1cb6880037f121),
runs the complete MemoryCell regression and Ruff F/E9 checks, verifies
the original historical Reader inventory, executes the 60 new calls,
and retains sealed raw answers, full attempted work, environment and SHA256
file manifest. There is no main merge, external owner mutation or production
activation.

production_accepted=false; reader_adequacy_established=false;
independent_natural_task_evidence=false.
