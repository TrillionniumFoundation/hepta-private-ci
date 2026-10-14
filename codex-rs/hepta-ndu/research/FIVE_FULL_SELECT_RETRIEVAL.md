# Full SELECT retrieval census on the shared frozen Encoder

Date: 2026-10-14. Additive development experiment on the fixed research branch.
No Reader qualification, production routing, model replacement, target repair,
new donor selection, TEST access, or answer-level semantic claim is created.

## Why this experiment follows the three-pair result

The completed crossed audit showed that direct cosine on frozen Encoder vectors
preserved both question and evidence rankings on all three scoreable paired
SELECT rectangles, while every saved from-zero small Head preserved neither
joint ranking. Three pairs are too small to decide whether that relation signal
is broad or accidental. This experiment expands the same readout to the entire
fixed SELECT inventory before investing in more Stem or Head capacity.

The exact authenticated inventory artifact has SHA256
`aeb4113b6d2baace0a042f960876861c78b5449b6d9dac404dee2e5c041e46fa`.
A local no-model preflight rehashed that ZIP and projected:

- 296 SELECT questions;
- two existing source families (184 and 112 questions);
- 249 distinct evidence candidates after deduplication **within the original
  source-family scope**;
- 545 unique question/evidence feature inputs.

There are 211 evidence candidates used by one question, 29 by two questions and
nine by three questions. Shared evidence is retained explicitly; a tied source
is not silently counted as a unique top-1 success.

## Inputs and target exclusion

Each pool row already contains a public question and its annotated source
material. The feature projection contains only:

```
{"question": ..., "options": ...}
{"evidence": ...}
```

The inventory's `answer_body` is hashed to bind the source artifact but never
enters feature text, lexical scoring, neural scoring, candidate selection or the
readout. Tests change every answer body and require feature, unit and candidate
bytes to remain identical. Thus this study evaluates retrieval of the registered
source, not generation of the registered answer.

The original source text, source-session metadata, order, local citation IDs and
family scope remain unchanged. Exact duplicate evidence bytes are deduplicated
only inside the same source-family scope; identical text in another family is a
separate candidate. No question or source is replaced because it is difficult.

## Fixed methods

All methods score every encodable SELECT question against every encodable scoped
evidence candidate:

1. `cosine`: deterministic FP64 cosine on the shared frozen vectors; no fitted
   parameter.
2. `lexical_jaccard`: case-folded alphanumeric token-set Jaccard over public
   values only; no corpus statistics or fitted parameter.
3. all 15 saved Head/seed objects from the completed shared-Encoder study:
   frozen gate, evidence-only, affine aligned, gated aligned and gated reversed,
   at the three fixed seeds. They are reloaded read-only; no best seed is chosen.

Raw score scales are never subtracted across methods. Comparisons use paired
ranks and top-k outcomes on the same question/candidate denominator.

## Frozen feature ownership and actual extra work

The crossed-evidence artifact supplies an authenticated cache and exact tensor
census. Every matching feature key is reused. Only missing public SELECT feature
keys may invoke the same strict archived 22.7M-parameter Encoder. Before loading
the Encoder, the tokenizer checks the fixed 512-token capacity without silent
truncation. An over-cap feature is retained as unavailable; its question and
candidate stay in the planned denominator and cannot become a zero score.

The output records:

- old and combined tensor digests;
- new feature count and unavailable feature count;
- actual Encoder load and forward count;
- normalized feature bytes;
- every saved Head checkpoint identity and replay of its old registered logits;
- actual Head forward calls;
- cosine and lexical computation counts;
- process timings with unknown energy/FLOPs left null.

No Reader, causal decoder, pretrained optimizer or Head optimizer is used.
Upstream Encoder construction and prior Head training remain paid historical
work; cache reuse does not erase them.

## Readout

For each question, report global and within-family retrieval separately:

- deterministic rank with a fixed evidence-key tie break;
- optimistic and pessimistic tie ranks;
- unique top-1 and tie-aware top-1;
- strict top-5;
- lower/upper reciprocal rank;
- mean pessimistic rank;
- per-family and family-macro summaries.

The own evidence key can support several questions. Such multiplicity is
reported per item. Missing or over-cap inputs are not imputed. The saved score
matrices are sealed in safetensors before summaries are written.

Retrieving the annotated source is not proof that the source is sufficient,
that the answer is correct, or that a Reader call can be skipped. The inventory
is previously exposed development material, not an untouched confirmation set.

## Local preflight status at publication

Twenty-five new synthetic contract/readout/entrypoint tests pass locally. Python
compilation and workflow YAML parsing pass. On the authenticated 296-question
inventory, the no-model lexical preflight completed 73,704 comparisons:

| Readout | unique top-1 | strict top-5 | lower-bound MRR |
| --- | ---: | ---: | ---: |
| global | 83/296 | 151/296 | 0.4012933227 |
| within family | 84/296 | 158/296 | 0.4087039336 |

These numbers are a lexical development baseline, not semantic accuracy and not
neural execution. The cloud workflow must independently validate all result
origins, encode missing features and replay saved Heads before a neural comparison
is reported.

Files:

- `full_select_retrieval.py`;
- `full_select_retrieval_trial.py`;
- `test_full_select_retrieval.py`;
- `.github/workflows/hepta-full-select-retrieval.yml`.

`reader_adequacy_established=false`, `production_accepted=false`, and
`five_experiments_completed=false` remain.
