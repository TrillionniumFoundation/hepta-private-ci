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


## V14.1 grounded-capacity and family-paired correction

An externally asserted \`correct=true\` is **not** evidence that a Reader
used the delivered source. The scorer now computes \`grounded_correct\`
only when correctness and semantic citation entailment are both asserted,
a cited source actually appeared in the corresponding delivered evidence,
and the Reader did not abstain. An adjudicator cannot mark
\`citations_entailed=true\` for a source-free, citation-free, or abstaining answer.

The three proposed bottleneck diagnoses (candidate Reader vs reference,
retrieval vs sufficient evidence, and sufficient vs source-lesioned evidence)
now operate on **grounded** rather than raw correctness. They remain
*unverified diagnostics*: the static scorer cannot prove the reviewer has
independently seen original source bytes or that any original pretrained
inference actually ran. It cannot distinguish model memorization from
source-supported inference without real task interventions and source-level
review.

The report preserves original per-answer correctness and separately adds
per-claimed-family paired sufficient-minus-retrieved and
sufficient-minus-lesion grounded contrasts. The family identifiers and
their independence are **not authenticated**, and no bogus case-wise
confidence interval or causal Cell benefit is calculated. The study
still unconditionally returns \`HOLD_NO_GO\` and leaves production,
Stem selection, Cell split, SYSTEM2, and FinalUse forbidden.


## V14.2 original source-to-model-input materialization

The read-only source builder
`v14_reader_original_request_builder.py` now provides a physically usable
entry point for original Reader execution: it deterministically derives all
four request **bytes** from the same registered question and original source
snippets. It forbids unknown fields, answers/gold in its declared schema,
foreign/duplicate evidence references, duplicate input bytes despite different
arm names, unsupported model identities and missing source text.

Source input has exactly these top-level keys:

- `schema` = `hepta.stem.v14.reader-sufficiency.v1.original-source-first.v1`
- `source_only=true`, `gold_available_before_predictions=false`,
  `production_authorized=false`
- `objective_sha256`, `max_output_tokens`,
  `models` (same pinned two-Reader manifest as V14)
- `cases`: bounded question text, owner family/window, original
  source ID/text census, four ordered evidence-ID assignments.

No answer text, publisher labels, model checkpoint tensor or private prompt is
committed to this public repository. The CLI writes two create-only files with
0600 permissions: a source-free V14 plan and a separate **private** packet
containing the actual rendered question/evidence prompts and original snippets.

Example execution from the repository root:

```sh
python qualification/stem-cell-v1/v14_reader_original_request_builder.py \
  --source PRIVATE/source-only-cases.json \
  --plan PRIVATE/original-four-arm-plan.json \
  --private-requests PRIVATE/original-reader-prompts.json
```

The model host must consume only those pinned private prompt bytes, record
exact original model/tokenizer/runtime material, full output bytes and measured
CPU/token usage, then seal its outputs before an independent source reviewer
accesses heldout truth. The scorer refuses plan or answer identity drift, but
a matching SHA is **not** proof of genuine model execution or evidence
sufficiency. The chosen "sufficient" evidence still requires independent
human/source-level attestation, and the lesion still requires proof that its
removed premise was necessary. Source-only builder replay is **not** an
independent reviewer.

Nineteen new synthetic and adversarial unit cases exercise byte-level arm
materialization, label smuggling, private file creation, duplicate/foreign
evidence, source mutation, prompt substitution, model identity and input
reconstruction. CI runs both normal and optimized Python test modes on exact
PR HEAD. **No original V14 Reader calls, prospective family-level gains,
model promotion, FinalUse or production authorization have occurred here.**


## V14.3 separately implemented prompt replay

`v14_reader_original_request_review.py` is an isolated source-first
prompt verifier. It intentionally does **not** import the prompt builder. It
recomputes every question SHA, source ID and source text, exact ordered
evidence membership, actual per-arm model prompt bytes and SHA, frozen
Reader/model-budget identity, private packet binding and completeness.

The review's source input and private prompt packet are supplied from the
original research material held outside Git. It does not accept the producer's
claim that material was generated correctly without checking its exact bytes.
Its report exposes only case counts, material digests, four-arm request count
and explicit false claims for original model execution, independent source
owner, sufficiency, promotion and FinalUse. It NEVER emits private raw
questions or evidence text.

This independent implementation closes **a software-level cross-file
consistency gap**, not the source-identity or scientific validity problem:
a dishonest actor controlling original source bytes, both model outputs and
the evaluator can still forge the entire packet. Source-owner authentication,
actual pinned pretrained model invocation, paired answer/citation outcomes,
future independent families, total lifecycle cost and external semantic
review are still required. The shadow study remains `HOLD_NO_GO`.

To reread a privately staged physical input packet:

```sh
python qualification/stem-cell-v1/v14_reader_original_request_review.py \
  --source PRIVATE/source-only-cases.json \
  --plan PRIVATE/original-four-arm-plan.json \
  --private-requests PRIVATE/original-reader-prompts.json
```

A separate nineteen-case negative/source-only suite checks the source
reconstruction, outsider prompts, altered model/budget/source IDs,
faked original execution or gold exposure, reordering and missing routes.
Both standalone suites run normal and optimized mode in the read-only
exact-head GitHub Action. They do **not** attest any real original V14
Reader forwards or semantic answer improvements.


## V14.4 joined source-to-outcome read-only contract

A separate `v14_original_reader_reconcile.py` now joins all five original
material records *in one exact software-level consistency evaluation*:

1. Original source-only question/evidence material.
2. Frozen four-arm / two-Reader request plan.
3. Private original model prompt bytes from source-first builder.
4. Complete original-model-output-shaped candidate/reference answer
   inventory with actual prompt/model/answer digests and recorded costs.
5. Post-seal independent-evaluator-shaped judgments tied to answer SHA.

The reconciler requires the independent actual-prompt reviewer and the
Reader's source-bound, per-family grounded outcome/citation diagnostic to
agree on the exact plan SHA, complete per-arm case census and original
prompt identities. The output contains source/plan/prompt/model-output/
adjudication SHA references and per-reader bounded token/CPU/wall
**reported** counters. It never copies original private text into the
public aggregate.

To run with separately pinned *real* externally generated materials:

```sh
python qualification/stem-cell-v1/v14_original_reader_reconcile.py \
  --source PRIVATE/source-only-cases.json \
  --plan PRIVATE/original-four-arm-plan.json \
  --private-requests PRIVATE/original-reader-prompts.json \
  --predictions PRIVATE/original-reader-predictions.json \
  --adjudication PRIVATE/external-semantic-judgment.json
```

A twelve-case adversarial synthetic test suite checks cross-file mutation,
foreign model weights, missing physical attempts, review forgery, citation
membership, paired resource conservation and no leakage of source text.
This is an **auditable executable input/output protocol**, not an
observed original model experiment. Original model host attestation, an
external trusted source owner, actual post-seal human evaluation, future
source families and full cost comparisons remain missing. The reconciler
always returns `HOLD_NO_GO` and false flags for model promotion,
SYSTEM2 and production authorization.


## V14.5 original pinned candidate Reader physical CPU execution

`v14_original_reader_candidate_cpu.py` is now a callable *physical* research
candidate-model executor, not a model mock or an asserted model output. It
reuses the existing frozen V12 135M BF16 archive and **actual manual FP32 CPU
PyTorch** Reader implementation, with original checkpoint hashes:

- Model `5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c`.
- Tokenizer `9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c`.
- Config `8eb740e8bbe4cff95ea7b4588d17a2432deb16e8075bc5828ff7ba9be94d982a`.
- Runtime is the SHA256 of the exact source bytes in `v12_reader_runtime.py`.

It uses strict independent original question/evidence prompt replay **before**
loading model weights, hashes the entire local checkpoint **before and after**
inference, validates actual input BPE length without clipping, and executes
each candidate model request (at most 64 cases × four arms) using the original
greedy model runtime. The two-stage private journal uses exclusive file
creation (0600), records the exact input-token SHA and fsyncs the attempt
identity before each physical call. The create-only output retains actual
generated token IDs, raw answer bytes, answer SHA256, physical CPU/wall and
forward counts, source/model/runtime identities and unregistered citations.
No model responses, original input text or checkpoint weights enter the
public repository artifacts.

To run **only on a host with the genuine pinned V12 archive**:

```sh
python qualification/stem-cell-v1/v14_original_reader_candidate_cpu.py \
  --source PRIVATE/source-only-cases.json \
  --plan PRIVATE/original-four-arm-plan.json \
  --private-requests PRIVATE/original-reader-prompts.json \
  --original-reader-root PRIVATE/original-135m-reader/ \
  --private-output PRIVATE/v14-candidate-original-answers.json
```

This runtime is neither an official Hugging Face parity implementation nor an
independently authenticated model-host run; only the candidate Reader is
implemented, and the stronger reference Reader remains a separate external
source. It cannot produce complete eight-arm V14 task results by itself.
The complete source→prompt→dual Reader→post-seal review reconciler still
requires both exact model identities, independent review and real outcomes.
The runner never issues FinalUse or production authority.

**Honesty gate:** Source-only CI tests 14 failure and preflight contracts,
including missing authentic weights and wrong model/runtime/source material.
Those tests NEVER execute the real pretrained model. **No V14 physical model
run has been executed or attested by the current exact-head CI** merely because
this code is present. V14 remains `HOLD_NO_GO`, `SHADOW_ONLY`,
`DENY_ALL`, and `production_authorized=false`.
