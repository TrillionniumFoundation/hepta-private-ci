# V14 Reader sufficiency: four evidence conditions x two frozen Readers

**DRAFT / RESEARCH / SHADOW_ONLY / DENY_ALL / NO MAIN MERGE / NO FINALUSE.**

## Why
V9 actual pretrained MiniLM Head retrieval lost to untrained BM25. V13 selected
phrase+character lexical arm had a retrospective weak publisher Hit@3 delta
(+11/829, four old source roots, one regressed), but an original Reader
16-question disagreement-conditioned diagnostic found zero added publisher
witness hits and no independent semantic correctness. More Cell training,
SYSTEM2, or model selection is NOT justified by those results.

This V14 addition solves one narrower *measurement* problem: do not blame a
Retriever or optimize an Encoder if the frozen original Reader cannot answer
even when given independently verified sufficient evidence. It does not assert
that a complete original V14 evaluation has occurred.

## External immutable three-stage execution
1. **Freeze source-only plan** before model calls or adjudication labels. For
   every source-independent case, specify the same question and four *actual*
   distinct request SHA256s: no evidence, ordinary retrieval, independently
   curated sufficient evidence, and lesion with a proper subset of the
   sufficient evidence IDs. Re-running with an unchanged model input under a
   renamed arm is rejected. Bind exact candidate and stronger reference
   weights, tokenizer and runtime SHA, fixed task objective, output-token
   budget and source family/time-window identities.
2. **Execute original Reader separately** for both fixed models and all four
   arms, retaining original private answers, input material, source evidence,
   model-owner execution receipts and resource counters securely outside
   the public repository. Supply the complete source-bound answer SHA and
   cited source ID census. The V14 script DOES NOT perform these original
   calls, verify their provenance, or assert equivalent physical inference
   budgets. The plan fields and result file can be forged without an
   independently authenticated model host.
3. **Adjudicate after a sealed model-output file** with an independent
   source-level reviewer. Link every correctness and semantic entailment
   decision to the exact original answer SHA. The reviewer must separately
   verify actual sufficiency, lesion necessity and supported citations;
   stable hashes do not prove correctness or reviewer independence.

The scorer consumes three **external** JSON files:
    python qualification/stem-cell-v1/v14_reader_sufficiency_gate.py \
      --plan PRIVATE/source-first-plan.json \
      --predictions PRIVATE/original-reader-predictions.json \
      --adjudication PRIVATE/external-semantic-judgment.json

Input files must match the strict schemas implemented in
v14_reader_sufficiency_gate.py and the constructed negative fixtures
test_v14_reader_sufficiency_gate.py. Neither original input texts nor answer
texts are committed by this patch.

## Interpretation with the exact same candidate Reader
- Sufficient evidence wrong; stronger reference right: **Reader capacity or
  representation bottleneck**, not a MemoryCell retrieval win.
- Sufficient evidence right; ordinary retrieval wrong: retrieval/index/selection
  is a candidate cause. Must independently adjudicate evidence coverage.
- Sufficient evidence right; lesion wrong: lesion sensitivity is a diagnostic,
  not by itself causal grounding or semantic citation correctness.
- Both Readers wrong with sufficient evidence: audit the task, prompt,
  evidence sufficiency and both Reader capacities before any claimed gain.
- Only changing to the stronger reference improves scores: label this as
  reference Reader capacity, never learned Cell benefit.

For a valid causal claim, use registered interventions, identical resource
budgets or full matched-cost comparisons, and independent source-level outcome
adjudication. Count family and time-window clustering; question rows sharing
one source root are NOT independent trials.

## Adversarial source-only tests
The negative tests exercise injected answer labels, duplicate plans/answers,
missing arm results, fake model identity, changed prompt SHA, fabricated
citations, evidence deletion failures, false authority flags, forged evaluator
independence, incorrect answer bindings, NaN, duplicate JSON properties,
integer/bool confusion, budget overrun and result-order invariance.

Local isolated analysis run (not dot, not GitHub CI) executed **28/28 tests**
under ordinary Python and **28/28 under python -O**. These tests use synthetic
SHA-derived answers and human-result fixtures and are **not** a pretrained
Reader run, human evaluation, or a physical claim about the current model.

## Explicit hard blockers
There is no physical original V14 source-first trial, pinned independent
human source/evaluator attestation, genuine future source-disjoint task
windows, independent original source identity, authentic candidate-vs-reference
model call evidence, model-host admission, full lifecycle compute, ongoing
retention repair or signed FinalUse. The script unconditionally reports
HOLD_NO_GO, stem_winner_verified=false, system2_verified=false,
production_authorized=false, and independent_human_attestation_verified=false.

Do not infer production selection, new model quality, multimodal competence,
Cell split permission, NDU/SYSTEM2 efficacy, or main merge from the tests.
