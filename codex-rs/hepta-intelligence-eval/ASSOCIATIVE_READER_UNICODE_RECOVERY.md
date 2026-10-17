# Frozen Reader Unicode source recovery — privilege-isolated V2 diagnostic

**Research-only; production accepted: false.** This work repairs **a missing source
input condition**, not the MiniLM native tokenizer, pretrained weights, MemoryCell
parameters, inference selection or reference labels.

## Exact rationale

In the existing pinned 20-question Reader premise diagnostic, 19 questions have
all annotation-selected sources inside the v1 ASCII-only source view. The last,
`conv-49/q0014`, has four annotated original source IDs:
`D3:3`, `D5:5`, `D23:15`, and `D22:12`. The latter two contain an em dash and
right single quotation mark respectively. These source **messages exist in the
original SHA256-pinned LoCoMo corpus** but were excluded by the deliberately
restricted native MiniLM WordPiece ASCII input. V1 then marked the entire
question unavailable, rather than exposing only two incomplete facts.

V2 reconstructs the **original UTF-8 source text** for *that exact predeclared
question* in a separately marked privileged Reader test. It never feeds
non-ASCII bytes into `MiniLMOfflineEncoder` or alters the v1 corpus/predictions.
The same registered frozen SmolLM2 Reader can tokenize Unicode; its model
identity and prompt/decode budget remain fixed.

- Original LoCoMo: `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`.
- V1 Reader plan bytes: `404c0fa14adc96d1a20e8c8a894e5f9e6f77392da8cced05bdadc6248c0686eb`.
- Original public source bytes: `e3c9fe407afcc08a153eeb0122b107314443335cb8f153b6557693bdbf900455`.
- **Locally tested V2 plan:** `209f6849e7ec1bf4c87d7bfc3434bfe26884633dcfdbe06acee3c8b2ec949a2d`.
- Frozen Reader inventory identity: `afb110c28d68c8956d372e428277fa8f164a2304f0ef9d9064a084f3fab7d94c`.

## Trust and causal boundaries

1. The *trusted plan generator* sees the original corpus and the **already
   sealed V1 plan**; it checks source family, question, source IDs and original
   bytes. It uses annotation-selected evidence IDs only, **never gold answer
   values** when constructing the Reader input.
2. All 19 previously available questions retain their **byte-identical V1
   question/evidence views**. V2 changes exactly one predeclared question: it
   admits four original source messages, two of which had been excluded solely
   because of Unicode text.
3. The plan is written once (`plan.json`, `seal.json`) with strict SHA256
   contracts. Source records are bounded; absent roots, unknown identities,
   alternate source bytes, changed old evidence, extra files, and forged
   signatures fail closed. A duplicate plan or a modified input cannot silently
   replace the historical artifact.
4. The *Reader worker* downloads **only** the two sealed plan files and eight
   previously registered Reader model files. It never receives the raw LoCoMo
   corpus, hidden annotations or a gold answer file. It runs `annotated_all`
   and `annotated_minus_one`, with **the same** deterministic one-premise
   deletion and `max_new_tokens=48`. Unavailable/failed attempts remain in
   the 40-attempt denominator.
5. The independent post-run reviewer downloads raw references **after** all
   original model outputs are sealed, regenerates the exact V2 plan from
   originals, rejects any drift and reports diagnostic token F1 and explicit
   missing/failed/unscorable statuses.

The selected evidence IDs were chosen using the published reference annotation:
this is an **oracle diagnostic**, not RAG, an independent semantic entailment
judge, an externally verified sufficient-evidence oracle, or a MemoryCell
learning gain. Restoring raw source accessibility does not demonstrate
language comprehension or multiple independent samples. The full 20 questions
still represent ten correlated dialogue groups, not 200 independent families.

The existing V1 19/20 Reader experiment stays unmodified. Even if this V2
reader answers the newly admitted fourth-source question correctly, it cannot
be compared as an improvement in an eligible retrieval arm.

## Reproduction

```bash
export PYTHONPATH=scripts/memory_cell
export HEPTA_ASSOC_UNICODE_FIXTURE=/tmp/source-fixture
python3 -m unittest discover -s scripts/memory_cell \
  -p test_associative_reader_unicode_recovery.py -v
python3 scripts/memory_cell/associative_reader_unicode_recovery.py plan \
  /tmp/source-fixture/locomo.json /tmp/source-fixture/v1plan \
  /tmp/source-fixture/public.json /tmp/unused-new-v2-plan
```

Only the hosted workflow uses the registered frozen Reader. The separate
workflow `.github/workflows/hepta-associative-reader-unicode-recovery.yml`
records exact inputs, hashes, all reader outputs and post-seal review.
No existing `blocking-ci` or Architecture check is waived and no production
memory owner is changed.
