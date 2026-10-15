# AMCN question-level weak-support recall: source-first research diagnostic

**Authority:** SHADOW / DENY_ALL / not eligible for production.

`amcn_typed_query_eval.py` evaluates whole **original questions** using a
precommitted, label-blind, exact-source Top-K plan plus the complete original
five-arm physical Head probability predictions. Labels are opened only after
the exact plan and predictions are pinned. It computes Hit@1, Hit@K, MRR@K,
zero-shortlist-support counts, per-functional-type counts, and paired
source-family win/loss/tie. Zero-support and missed-support queries stay in
every original-question denominator. The lexical Top-1 control uses the
original source-first rank, **not** a reselected publisher-gold source.

**Inputs:** `plan`, `predictions`, and `publisher_support` are three
independently bounded structures. The caller must supply external exact
SHA-256 values for all three. Each query binds scope, generation, family,
type, candidate source ID/revision/content SHA and original model input
SHA. The scorer rejects wrong class arms, duplicates, missing candidates,
changed source input, changed published labels, mixed scope/epoch, and missing
FUTURE_A or FUTURE_B diagnostic partitions. Matching self-reported hashes
do not establish independent issuer signatures or model forward authenticity.

## Existing archived LoCoMo diagnostic — descriptive, NO-GO

Using the prior immutable source archive originally published in GitHub
Actions artifact `11586991191` (outer ZIP SHA-256
`07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af`),
the local existing hashed-lexical-feature Head trial was independently
rescored across all **44 heldout questions / 704 original Top-16 rows**.
No new pretrained Encoder/Reader forward was executed by this scoring step.

- Original LoCoMo JSON SHA-256:
  `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`.
- Original public source-first feature packet raw SHA-256:
  `bc93802d1d28275a4dd51bfbe7a7dfdbb0a8c86f21920cb2c5d5b7ddeb9e42fc`.
- Previously sealed source-first plan digest:
  `ec478977b3f1e5b5b1e654a946df7acb405239745be6f4b4e84a82a6dc848f46`.
- Preserved physical model prediction seal raw SHA-256:
  `537b2489836a20cfefa43fa4d3941b33a61f03e7543d044a7716e458479fbc87`.
- Original predictions canonical digest:
  `4f87d0901ba3ad1ac4016c8e09644a8c9ea9da951d386b231aee0350f919770b`.
- Converted question-level candidate-plan digest:
  `528d63c6ef26dbd1b6c158dc23be38533ca2b33f38ce292a30bb74900c3d325c`.
  Conversion assigns the original ranked candidate source IDs and input digests;
  publisher-weak support for the shortlist is read from the withheld annotation
  file; it never manufactures support for missed source-first candidates.

| Retrospective split | Questions | Lexical Hit@1 | Unsplit Hit@1 | Typed Hit@1 |
| --- | ---: | ---: | ---: | ---: |
| SELECT | 16 | 4 | 4 | 3 |
| FUTURE_A | 8 | 2 | 2 | 2 |
| FUTURE_B | 8 | 3 | 2 | 3 |
| RETENTION | 12 | 5 | 3 | 4 |

Of 44 heldout questions, 15 have no publisher-labeled support among the
source-first final Top-16. They remain in the denominator. FUTURE_A/B consist
of just two retrospective conversation families (one family each), **not**
future calendar windows and not 200 independent sampling units. Even the one
FUTURE_B typed gain relative to unsplit is **not** a gain relative to lexical
Top-1 or strong hybrid RAG. Do not interpret row-level accuracy as real
question success, or publisher annotations as independent semantic entailment.

The original physical bank's readback was tested by the training research,
but **this stand-alone scorer does not reexecute the physical Head tensors**;
a caller must present independent physical-readback receipts for that claim.
No new Reader answers, citation adjudication, strong hybrid RAG comparator,
source-issuer trust, total maintenance bill, selective parametric unlearning,
independent NDU acceptance or production FinalUse has been established.

Run hermetic scoring contract regressions:

```bash
PYTHONPATH=.:qualification/amcn-v1 python -m unittest discover \
  -s qualification/amcn-v1 -p 'test_amcn_typed_query_eval.py' -v
```
