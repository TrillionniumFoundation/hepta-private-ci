# V21: source-first blinded evidence sufficiency — original ten-root LoCoMo

**Research only / DRAFT / SHADOW_ONLY / HOLD_NO_GO / DENY_ALL / no main merge.**

## Exact lineage and scientific question

This is an additive child of V20 PR #2540, exact SHA `d787dd40c4ea161917539b33cb89b69605371919`, preserving the unchanged Qwen/native 135M executors, tokenizer control, source owner, NDU/Neuron/CNS/CAS/FinalUse, and global `blocking-ci`.

V17–V20 diagnosed the original 135M reader with a weak publisher-answer substring proxy. Of 30 SHA-first original questions, eight publisher answer fields were missing. Only eight of the 22 labeled cases had the publisher's literal answer inside the corresponding truncated annotated passage. A publisher-annotated source is **not** necessarily sufficient evidence. Nothing justifies declaring the other fourteen cases Reader errors, or treating model-generated citation syntax as entailment.

This V21 addition creates an **independent evidential sufficiency intake** for future human adjudicators *before* any conclusion about Reader capacity, Cell differentiation, System 2, or NDU.

## What is actually physically executed

The private source-owner program reopens **real, SHA-locked** original LoCoMo prepared public question/utterance source and the exact V17/V19 source-first plan. The native reference-plan validator reproduces the inherited 120 requests, original citation addresses and source content. Exactly 96 unique Qwen message-byte identities remain after canonical alias deduplication. A secret 256-bit random blinding key maps each unique source message to an independent reviewer ticket, shuffled by randomized ticket identifier. Twenty-four duplicate logical arms map back to their same unique ticket; their review is counted once, not twice.

Each **private** ticket contains a question and up to three verbatim original evidence snippets, with speaker and citation ID. It contains no Reader answer, original publisher target answer, policy arm name, or model identity. The review mapping and blinding key live in a separate `0600` create-only file. No full dialogue corpus, source questions, excerpts, private tokens, model weights, raw model answers, publisher gold or secret blinding key enter the public Git tree or GitHub Actions artifacts.

The actual local original-source observation was **10 source families, 30 original questions, 120 logical evidence requests, 96 distinct evidence tickets, 24 reused aliases**. A separately executed read-only source custody test verified that the complete blinded-ID roster and exact mapping matched the published digest-only observation. There are **zero Qwen or 135M forwards** from this V21 creation, and **zero genuine human adjudications**.

## Review protocol and acceptance conditions

1. A source owner freezes source, model plan, schema, ticket digests, private alias mapping and source evidence selection before any review response. A blinded reviewer sees the question and exact evidence only, not the original gold answer, model response or intervention arm.
2. A second genuinely independent reviewer evaluates the same frozen tickets, using separate assigned review access. Verdicts are `sufficient`, `insufficient`, or `indeterminate`, bound to each ticket's actual question/evidence digest. Review ID strings by themselves **do not establish reviewer independence**. A disagreement remains unresolved and cannot be reassigned to the winning model.
3. Both independently governed review identities and trust/signing provenance must be authenticated **outside** this source-only tool. This V21 code intentionally cannot certify that step. Its unsigned reconciliation is a local mechanics test and always reports `independent_reviewer_identity_cryptographically_verified=false` and `evidence_sufficiency_certified=false`, even if all fixture judgments agree.
4. Only after sufficient evidence, and the complete original 135M and pinned Qwen3 genuine model attempts, are independently sealed should a separately authenticated reviewer evaluate semantic final answers, abstentions and whether cited evidence actually entails the answer. Source sufficiency and answer correctness remain different variables; syntactically well-formed citations do not imply entailment.
5. Scores must separate labeled versus missing publisher answers, literal-answer-in-evidence versus semantic-only candidate sources, and independent root groups rather than treating 120 arms or 96 aliases as independent human tasks. Full model inference/training/selection costs count uniquely; no Qwen benefit is retroactively credited to MemoryCell, Stem or NDU.

The source-only two-reviewer reconciliation never grants semantic qualification, model selection, automatic Cell Split, stochastic FBSDE, FinalUse or production authority. A fabricated “verified true” field, changed question/evidence bytes, foreign citation, lost alias, re-signed prompt, injected gold, duplicate ticket, or altered private custody fails closed.

## Reproduction

Source-only exact-HEAD checks:

```bash
export PYTHONPATH=research/hepta_v17_reader:research/hepta_v19_reader:research/hepta_v21_reader
python -S -m unittest discover -s research/hepta_v21_reader -p 'test_blinded_sufficiency.py' -v
python -O -S -m unittest discover -s research/hepta_v21_reader -p 'test_blinded_sufficiency.py' -v
python -S research/hepta_v21_reader/blinded_sufficiency.py verify-public \
  --receipt research/hepta_v21_reader/V21_ORIGINAL_BLINDED_EVIDENCE_OBSERVATION_20261016.json
```

On an isolated admitted **private source** operator, first remove the publisher `hidden.json` and all model-output files from the input directory. Prepare `public.json`, `owner.json`, `plan.json`, `annotation.json`, `requests.json`, `qwen-plan.json` using the exact existing V17/V19 owner commands. Then:

```bash
python -S research/hepta_v21_reader/blinded_sufficiency.py prepare \
  --public "$SOURCE/public.json" --owner "$SOURCE/owner.json" \
  --v17-plan "$SOURCE/plan.json" --annotation "$SOURCE/annotation.json" \
  --v17-requests "$SOURCE/requests.json" --reference-plan "$SOURCE/qwen-plan.json" \
  --private-folder "$PRIVATE/blind-evidence-v21"
```

Never upload `$PRIVATE` or `$SOURCE` to GitHub. The source-code CI checks **only sanitized digest/count evidence and unit fixtures**, never raw sensitive dialogue or human ratings. The future real-human task and Qwen physical run must complete separately with their own exact candidate receipts and independent approval. A queued or cancelled workflow is not a pass.

## Current NO-GO

No actual reviewed source sufficiency, independently signed reviewer identity, same-question real Qwen result, semantic correctness or grounded citation, actual matching full lifecycle cost, future disjoint source windows, V6 seed41 retention repair, qualified NDU FBSDE, learned Stem/Cell split or model promotion. All runtime and product authority flags stay false.
