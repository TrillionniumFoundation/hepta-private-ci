# AMCN original Head specialization disagreement: 14 real Reader tasks (SHADOW / DENY_ALL)

**October 15, 2026.** This is an explicitly **selection-biased mechanism diagnosis** over
historical LoCoMo, not independent production qualification, not strong-RAG
superiority, not prospective evidence, and not a valid equal-total-compute
inference. MemoryCell production execution still belongs on the user's dot host;
these exploratory local CPU runs were in an **isolated analysis container, not
on dot**. No change to selected models, source owner, revocation owner, memory
writer, `main`, `blocking-ci`, or FinalUse.

## Why these cases

Earlier naturally equal-input-token 24 questions had zero true typed-vs-untyped
Top-3 evidence differences: even 72 physical Reader calls could not identify
type differentiation. The complete *previously frozen*, original 400-question
retrospective heldout Head rank packet contains exactly **14 questions** for
which typed and untyped Top-3 order differs: **10 actually replace a source;
4 only permute the same sources**. This study takes **all 14**, by an exact
predeclared rule, without reading publisher gold. Six questions are from
`conv-49`, eight from `conv-50`. **None** has equal natural prompt-token
counts across all three arms; replacing/truncating original source content to
force equality is forbidden. The study can diagnose mechanisms but is neither
representative nor equal-compute causal evidence.

## Exact original material and private interfaces

- Original public-only family/question source file (10 families, 1,986 questions):
  SHA-256 `ac5f95085e5b223f81e888236e2c162f1ef45a3d1f52ad3e903fde48a629a633`.
- Original 1,986-question MiniLM/BM25 frozen rank JSON:
  `25bd9754e1da4ee5ddf620e7f3c734f06650568278c6aab51916d55046baef99`;
  scientifically stable ranking digest `bd63d0555a8e5b0cde444023d40da4570987226451fb97a2284d0bd285614a66`.
  A **new runtime's measured Encoder wall seconds can change its raw file SHA**;
  the archived manifest/Head bank must match its actual source/rank bytes.
- Original TRAIN-only three physical two-Head banks, six safetensors manifest:
  `88dbb2c9feffea97058c455f9a1292d21601a39449b6fee47169b540d6759fb6`.
- Original all-829 heldout/SELECT Head selections:
  `a937d4fd91e0c75cf4ddd265760c0b6c4cf1ed0947ad0c5be323686aca7391a3`.
  Before building the Reader plan, this run **physically reloaded all six Heads
  and independently reproduced 3,316 original Head forward results** using
  `verify_original_predictions` from the existing training owner.
- Reader original 30-layer BF16 weights:
  `5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c`;
  exact archived tokenizer: `9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c`.
- **Frozen full original Reader request plan** SHA-256:
  `e92c469bb8f03ae5b5c3382301244043eb4d3a4ecfbc64d4835b46f4185198c7`.
  Full prompts and original dialogue bytes remain in an access-restricted private
  work directory, not in the Git tree or public Actions artifacts.
- All 42 original Reader dispatches were durably recorded before inference,
  then original raw token IDs/text/status were fsynced. `starts.jsonl` SHA:
  `e07ee2cd360ef3addaf789c3d114130acc3836cd8e021a3dae149807ae4de442`;
  raw answer journal SHA:
  `cae73ed3d1474517df276b55a19dd985a86d70fc808b479a67b74ba1d43b8c04`;
  completed create-only answer seal SHA:
  `8631fcef11838e9e3b1ed74c0d00e9aa3209d65a9450e806631434ef045b16f9`.
- Publisher support was separately opened **only after the 42-answer seal**,
  locked by `758d951c2fb296c3ba23ef539e3f243fb8464d52ed0d42c8d0981943ac907a06`;
  original LoCoMo `locomo.json` by
  `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`.
  Ordinary `answer` and separate `adversarial_answer` were counted by distinct
  fields, without mistaking the latter for independent human truth.
- **Public sanitized result JSON** `ORIGINAL_TYPE14_READER_20261015.json` SHA:
  `3e03f0f4f7e6135e4ce2372df4c107a683e3f300cb3af998f943120f040fef5b`.

## Observed original CPU model outcomes

| Measure (all 14 original questions) | BM25 | Unsplit two-Head bank | Typed two-Head bank |
|---|---:|---:|---:|
| Original successful Reader calls | 14 | 14 | 14 |
| Any publisher-weak source at final Top-3 | 5 | **7** | **7** |
| All publisher-weak sources at final Top-3 | 5 | **7** | **7** |
| Strict casefolded whole-answer string equality | 0 | 0 | 0 |
| True original Reader input tokens | **3,464** | **3,424** | **3,341** |
| Actual original Reader output tokens | 340 | 281 | 321 |
| Output generated to max-32 ceiling | 6 | 4 | 4 |

**All 42 physical generations completed**, zero failed/incomplete starts. 12
ordinary and 2 adversarial questions per arm; none achieved strict whole-string
equality. Typed-vs-untyped original raw Reader strings differed in **11/14**
questions, but weak Hit@3 and exact-string counts were tied. Each Head arm
picked up 2 BM25 misses and lost 0 BM25 hits in this **cherry-pickable by
design disagreement-only** subset; the registered whole 400 question weak
Top-3 scores are STILL BM25 182, untyped 192, typed 192. There are ONLY TWO
independent source family groups, zero true future time windows, no blind
independent semantic adjudication, and no official Hugging Face model parity.
Both Head arms share the same original Encoder and final 3 evidence slots,
but measured input/output tokens differ; their training/retrieval work also
exceeds BM25. **There is no equal-total-compute full-task claim.**

## Reproduce read-only in a locally approved research environment

Preposition the exact **private original** source/rank/Head/Reader files from
its SHA-pinned artifact. No manually recreated model, missing tensor, label
backfill or pseudo-original empty source is accepted. Use the original source
file layout from #2085's `amcn_original_trained_rank_heads.py`.

```sh
export PYTHONPATH=qualification/amcn-v1
python3 qualification/amcn-v1/amcn_original_type_divergence_reader.py plan \
 --public /private/public-sources-only.json \
 --rank /private/ten-family-real-original-minilm-rank.json \
 --predictions /private/sealed_heldout_predictions_recounted.json \
 --bank-directory /private/physical_banks \
 --reader-directory /private/original/reader \
 --output /private/create-only/type14-original-plan.json
# Verify EXACT external request file SHA before running any model.
sha256sum /private/create-only/type14-original-plan.json
python3 qualification/amcn-v1/amcn_original_type_divergence_reader.py generate \
 --plan /private/create-only/type14-original-plan.json \
 --plan-sha256 e92c469bb8f03ae5b5c3382301244043eb4d3a4ecfbc64d4835b46f4185198c7 \
 --reader-directory /private/original/reader \
 --output /private/create-only/original-reader-42
# Resume only if interrupted: same generate command, SAME immutable output
# folder; it preserves the unsuccessful prior start before any retry.
# Check the file SHA BEFORE opening publisher weak gold and original answers.
sha256sum /private/create-only/original-reader-42/seal.json
python3 qualification/amcn-v1/amcn_original_type_divergence_reader.py score \
 --plan /private/create-only/type14-original-plan.json \
 --plan-sha256 e92c469bb8f03ae5b5c3382301244043eb4d3a4ecfbc64d4835b46f4185198c7 \
 --reader-directory /private/original/reader \
 --original-run /private/create-only/original-reader-42 \
 --seal-sha256 8631fcef11838e9e3b1ed74c0d00e9aa3209d65a9450e806631434ef045b16f9 \
 --publisher-weak-gold /private/withheld-publisher-weak-labels.json \
 --raw-original-locomo /private/original/locomo.json \
 --output /private/create-only/type14-postseal.json
```

The 14 original-source/head/model audit tests require the physical original
plan, journal and Reader tokenizer under `HEPTA_AMCN_TYPE14_ORIGINAL_ROOT`
and `HEPTA_AMCN_TYPE14_READER_DIR`; their **actual local run passed 14/14**.
A separate pure-stdlib fast negative-authority suite **14/14 passed** against
this exact sanitized aggregate. Its GitHub Actions job is deliberately
source-only, never simulates the 42 physical Reader calls, never opens raw
source or publisher labels, and **cannot qualify the model**. There is no
production promotion, Cell self-division, automatic merge/fission or FinalUse.

**Research verdict:** E1 full-task improvement **not established**; E2 typed
vs equal-budget unsplit **NO-GO** despite changed answers; E3 learned graph
full-task effect **not measured**. The nine-arm strong hybrid RAG causal study
and independent prospective window requirements remain blockers.
