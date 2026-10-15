# Post-hoc rank fusion on the completed full SELECT retrieval census

Date: 2026-10-15. This is deliberately labelled **post-hoc exposed-development
analysis**. The completed SELECT outcomes were inspected before these fusion
methods were implemented. It is not preregistration, independent confirmation,
model selection authority, semantic accuracy or a production routing rule.

## Fixed input

The analysis consumes only the completed, authenticated full-SELECT result:

- source `8e213b7585221ddf9fd279037caa4dc6f972af6c`;
- run `38540293994`;
- artifact `11885366683`;
- artifact ZIP SHA256
  `6534177c6974ee0e9fe0a331891ec5cb0b2443481198ece36cfcaf754003d436`.

Before creating any fused score, the worker verifies the exact archive manifest,
source commit, successful disposition, 296-question/248-available-candidate
matrix geometry, prediction seals and both saved cosine and lexical summaries.
It then reads only the already sealed `cosine` and `lexical_jaccard` matrices.
No Encoder, Head or Reader is loaded, and no optimizer runs.

## Target-free score construction

For each available question, each base score row is converted to a deterministic
1-based candidate rank by descending score with evidence key as the fixed tie
break. The own evidence key is not consulted while constructing scores. The six
fixed diagnostics are:

1. `equal_reciprocal_rank`: `1/r_cosine + 1/r_lexical`;
2. `rrf_k60`: conventional equal-weight reciprocal-rank fusion with offset 60;
3. `mean_rank`: negative arithmetic mean of the two ranks;
4. `rank_product`: reciprocal product of the two ranks;
5. `anti_cosine_control`: lexical rank combined with reversed cosine rank;
6. `cyclic_cosine_control`: lexical rank combined with the cosine ranks from the
   next available question in the fixed score-index order.

The last two controls preserve important marginal structure while destroying or
reversing the intended cosine relation. All methods retain the one unavailable
question. The same fused score matrix is read out globally and after restricting
to the registered source family; no family-specific fit occurs.

## Exact local replay before publication

Eight synthetic contract tests pass, including target-independence, immutable
inputs, unavailable-row preservation, fixed tie breaking, control behavior and
foreign-directory CLI execution. The complete authenticated artifact also
replayed locally. These observed numbers are descriptive, not confirmatory:

| Method | Global unique top-1 | Global strict top-5 | Global MRR lower | Within-family unique top-1 | Within-family strict top-5 | Within-family MRR lower |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| lexical baseline | 83/295 | 151/295 | 0.402532 | 84/295 | 158/295 | 0.409927 |
| equal reciprocal rank | 83/295 | 158/295 | 0.398736 | 85/295 | 164/295 | 0.411808 |
| RRF, `k=60` | 66/295 | 138/295 | 0.345910 | 68/295 | 142/295 | 0.354813 |
| mean rank | 64/295 | 134/295 | 0.331927 | 65/295 | 137/295 | 0.338869 |
| rank product | 74/295 | 154/295 | 0.378359 | 76/295 | 159/295 | 0.386603 |
| anti-cosine control | 9/295 | 129/295 | 0.223299 | 51/295 | 142/295 | 0.327851 |
| cyclic-cosine control | 47/295 | 135/295 | 0.296527 | 66/295 | 143/295 | 0.352057 |

Equal reciprocal rank improves strict top-5 by 7 questions globally and 6
within-family, and improves within-family unique top-1 by one. It does not improve
global unique top-1 and slightly lowers global MRR. This is compatible with
limited complementary cosine information, but it is not evidence that a fusion
rule generalizes to new tasks. The negative controls' weaker results are useful
mechanism checks, not a significance test.

A valid next confirmation must freeze a fusion rule using TRAIN or a separate
validation cohort and evaluate it on new task families without selecting weights,
methods or cutoffs from this exposed SELECT census. Answer sufficiency and Reader
quality must still be measured separately.

`select_fit=false`, `new_optimizer_updates=0`, `new_reader_calls=0`,
`reader_call_skipping_authorized=false`, `semantic_accuracy=null`,
`production_accepted=false`, `five_experiments_completed=false`.
