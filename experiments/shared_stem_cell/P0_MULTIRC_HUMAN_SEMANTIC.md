# P0: original-human MultiRC semantic Reader, lexical hard negative, four Stem branches

**Status: RESEARCH / SHADOW / DENY_ALL.** This is one prospective, source-pinned,
small English *cross-sectional* qualification proposal, stacked **additively** on
P0 question-only SQuAD v2 retrieval repair PR #2109. Its existing sources,
original prediction receipts, queued CI and model/Control owners remain untouched.
A passing synthetic test, SHA, Actions job, observed accuracy or local `laya`
call does not grant model selection, final-use, a release, native effects or any
production capability.

## Precise scientific question

A SQuAD answer-span *deletion* changes whether an answer string appears. Literal
substring matching can therefore attain perfect accuracy without understanding
facts. MultiRC offers authentic human binary candidate-answer annotations for
an unchanged original passage/question. **An original false candidate can be
lexically present in the evidence.** Test whether the model can discriminate
true from false under the same original question when **both candidate strings
occur** in the paragraph; also report a preregistered `>=0.75` token-presence
control. This is a *naturally annotated semantic contrast*, **not** a generated
minimal-pair relation flip. If too few matched questions exist, report no hard
conclusion and retain the entire unselected population.

Additional optional audit: identical normalized answer text occurring with
opposite original human labels in different passages/questions. This is
reported only as cohort coverage; cross-source pairing is **not** causal
because other facts may also differ. A no-evidence view for every question and
candidate preserves task identity but has **unknown truth**; report only the
change in probability, not invented counterfactual accuracy/Brier.

## Pinned original inputs and reader tasks

Source `aps/super_glue@4e14482c58d790d467ecfb29b6790e1917bf8756`:
`multirc/train-00000-of-00001.parquet` and
`multirc/validation-00000-of-00001.parquet`. GitHub Actions obtains the exact
revision, checks publisher LFS SHA when present, stores original full SHA-256
in a read-only source receipt, and the independent scorer re-downloads and
rechecks the complete original parquet bytes. No network-acquired pickle,
model-supplied labels or arbitrary dataset code.

Eligibility and ranking **never inspect labels**: a bounded distinct passage
with >=2 authentic questions and >=2 answer alternatives each, two lowest
eligible question IDs, at most four lowest answer IDs each, and a SHA-ordered
source passage selection. First **12** train source passages; disjoint **4**
validation passages for temperature calibration; disjoint **8** validation
passages for held evaluation. All original answer alternatives are preserved
within those fixed limits; no label-driven negative selection or re-ranking.
The 8 held passage groups, **not** each candidate row, are the relevant
independence unit. Source list, answers, question IDs, full evidence, text,
selection rule, fit/blind hashes and exactly two views per candidate are fixed
before expensive model weights load.

## Physical four-model design

- Granite R2 97M, `835ad14087e140460703cf0fae09f97d469d65c2`;
- mmBERT-small, `0eb3d056ec1d6333cf4e19b0966dfde342a41a3a`;
- EmbeddingGemma2 text, `914f7f89142e33e77833254d9c9b90c3cef7303b`;
- Laya421 `convaiinnovations/laya@c5d78730f3493e4fe16d61507ef4b78eef7318cf` native frozen `noul` policy.

The first three reuse the original fully vetted E1 `encode_pretrained`
physical CPU path. Each uses frozen Q24 features, an actual same-initialized
frozen-vs-40-SGD-step linear Head, width 384/384/256 and **770/770/514**
Head parameters, train-only human original labels, calibration-only
predeclared temperature choice and no future labels. Source/model alias and
complete mmBERT safetensors requirements fail closed. Laya uses the original
`do_laya` and is **not** pretended to be an equal-parameter Head or training
budget matched. Any one model failing results in four-arm evaluation being
unavailable, not cherry-picked three-arm success. No fabricated weights or
random model substitution.

## Independently reproducible outcomes

The model job has access only to `fit.json` and `blind.json`. Separate material
owner `owner-only-human-labels.json` never enters its workspace. Only the
independent scorer can access held labels **and** exact raw source files. It
regenerates every original row and label from the source, including original
question/answer/passage identities; validates every source SHA, complete
per-arm prediction, compiled task identity and typed non-authorization flag;
then recomputes full original accuracy/Brier, conditional hard lexical exact
presence/75%-overlap coverage, within-question true-vs-false ranking,
original-to-no-evidence sensitivity, literal string-presence baseline and
per-arm separately reported resource cost. No custom per-case threshold search;
underpowered strata cannot establish superiority. Exact-source attestation is
not an externally signed issuer and does not establish dataset licensing,
pretraining noncontamination or independent human review beyond original labels.

**Critical design boundary:** the original MultiRC binary label answers the
question for the original source, not for a transformed passage; even if the
same strings remain after an artificial edit, no fabricated human label is
allowed. Generated relation flips would need genuinely independent human
re-adjudication in a subsequent experiment. This is not an official SuperGLUE
MultiRC score because the slice is tiny, preselected and observational.

## Reproduce offline tests and actual physical research

```sh
PYTHONPATH=experiments/shared_stem_cell python -m unittest discover \
  -s experiments/shared_stem_cell -p test_p0_multirc_semantic.py -v
PYTHONPATH=experiments/shared_stem_cell python -O -m unittest discover \
  -s experiments/shared_stem_cell -p test_p0_multirc_semantic.py -v
```

The read-only Actions workflow `hepta-p0-multirc-semantic-four.yml` attempts
actual source acquisition, actual pinned frozen weights and Head training,
then independent original labels verification. Source-only synthetic tests
**do not** execute public pretrained Encoder weights or report real natural
language scores. GitHub results must be judged at the **exact commit and
prospective merge**, alongside original `blocking-ci`, native owners and
security review. No new production implementation or Model/FinalUse grant
exists in these Python research files.

## Mandatory next claim gates

Real independent 4-model hosted success; all raw original source/model/feature/
Head/prediction receipts independently rechecked; enough human-labeled hard
contrasts; source-family stratified uncertainty; actual end-to-end model load,
Encoder, Head, Reader, CPU/GPU RSS, energy and p95/p99 on target host; three
chronologically independent future windows; bilingual/code families; Reader
sufficient-evidence semantics and original independent model no-change;
longitudinal retention, NDU and signed original Worker/CAS/Evidence WAL/FinalUse
qualification. No policy, graph, selected Stem, CUDA/native Computer Use,
`main` or release settings are modified here.
