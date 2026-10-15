# Original Reader zero-evidence abstention: 96-attempt independent audit

**2026-10-15 · SHADOW / DENY_ALL.** An additive research-only increment on #2085. It does not change source owners, the frozen original model, recorded answers, memory writer, FinalUse, `main`, or the original `blocking-ci` requirement.

## Original physical observations independently recounted

Original archived 30-layer 135M Reader experiments were executed on an isolated analysis host (not the user's dot host) before this increment. Three independently byte-SHA-pinned frozen journals were retained: 12 historical questions × four evidence regimes = 48 calls, eight deliberately gold-selected historical questions × four regimes = 32 calls, and the same eight with the witness/lesion arms at max 64 generated tokens = 16 calls. **96 previously recorded model calls are not 96 independent original QA questions**; some cases recur and only four historical source families are represented. The current increment performs **no additional Reader model forward**.

`amcn_original_reader_private_recount.py` independently reconstructs exact plans/starts/original Token IDs/statuses/response text/input-output token counts from three externally pinned original plans/seals and nine journal files, re-decodes original token IDs through the SHA-verified archive's ByteLevel tokenizer, and replays the exact 16 paired 24-to-64 greedy prefixes. Every original file is read-only, byte SHA pinned, duplicate-JSON-field checked and protected against incomplete JSONL lines. No publisher gold, question-answer target, or human-review material is read in this audit.

| Journal | Calls | Input tokens | Output tokens | Responses containing `[E#]` | Citation tags |
|---|---:|---:|---:|---:|---:|
| Annotation-only historical 12-case | 48 | 6,371 | 1,059 | 14 | 14 |
| Answer-selected historical eight-case | 32 | 4,285 | 681 | 6 | 6 |
| Eight-case 64-token follow-up | 16 | 2,691 | 629 | 7 | 10 |
| **Total** | **96** | **13,347** | **2,369** | **27** | **30** |

**Important failure:** Across both original 24-token experiments, **20/20 responses with NO supplied evidence contained no recognizable literal abstention** (`unknown`, `insufficient evidence`, `cannot answer`, etc.), despite an explicit prompt requirement to say `unknown` when evidence was absent. This is an observed abstention/prompt-following failure; the audit does **not** prove the factual hallucination rate. The 30 citation tags happened to reference evidence labels within the delivered source slots; syntactically in-range tags do **not** verify independent semantic entailment or source correctness. In particular, 69/96 original responses contained no citation marker.

## Research-only pre-dispatch remedy, not a model outcome

`amcn_research_empty_evidence_guard.py` implements a separate pure deterministic research preflight, without executing a generative model. If final evidence is empty, return `unknown` with **zero Reader invocations and zero model tokens**. If evidence is nonempty, check immutable source ID/root/scope/generation/revision, text SHA and supplied latest owner snapshot for withdrawal/drift; output only a candidate-to-dispatch instruction, **not** an owner-authenticated grant. This is a candidate for integration after independent Source Owner admission, not a trained Reader improvement or production Model Selection. It never edits the 20 archived non-abstaining original responses.

## Reproduction and genuine qualification limits

On a host that possesses the **private, SHA-verified original journals and Reader tokenizer**, run:

```bash
export PYTHONPATH=qualification/amcn-v1
export HEPTA_AMCN_ORIGINAL_RECOUNT_ROOT=/pinned/private-reader-96-journals
export HEPTA_AMCN_ORIGINAL_READER_ROOT=/pinned/original-reader
python3 -m unittest discover -s qualification/amcn-v1 \
  -p 'test_amcn_original_reader_private_recount.py' -v
python3 qualification/amcn-v1/amcn_original_reader_private_recount.py \
  --original-work "$HEPTA_AMCN_ORIGINAL_RECOUNT_ROOT" \
  --original-reader "$HEPTA_AMCN_ORIGINAL_READER_ROOT" \
  --output /create-only/original-96-private-recount.json
```

**Local execution:** 37/37 tests passed with the original logs/Tokenizer mounted. Source-only CI runs 30 standard-library test cases, including one skipped private-journal test class, plus an immutable sanitized-aggregate NO-GO gate. The source-only CI cannot and does not attest to executing the original archived model or independent publisher/source truth. The code includes explicit external SHA pins, and the sanitized aggregate has SHA-256 `13f6488f4d25bae2cbe61a08f4eba6cb23ab783f910416bace2f8bbb8e2875b6`.

Original model-host identity, official Hugging Face tokenizer/operator parity, independent factual entailment, a stronger reference Reader, 200+ truly independent source groups, true future calendar windows, matched total inference cost, MemoryCell parameter-learning task lift, Cell specialization, and learned graph efficacy **remain unqualified**. **NO-GO / DENY_ALL**: no automatic Cell fission/fusion, selected-model change, `FinalUse`, bypassing `blocking-ci`, or `main` merge.
