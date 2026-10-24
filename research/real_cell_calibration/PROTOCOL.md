# Frozen development protocol and scope

This is a publication extract of the protocol committed before experiment runs
in 9a452e8254c7bcf7765b4ead33bb439999ab3a16. No method or threshold changed.
The 50% minimum coverage is a NEW DEVELOPMENT criterion frozen for this pilot,
not an original-system admission threshold. Historical rules remain unchanged,
including the separately replayed historical cosine confidence threshold .70.

One sequential model job; at most four CPU threads; RAM target 8 GiB; download
ceiling 2 GiB; no paid service. Paired linear/gated/rank-1/MLP each have 65 trained
parameters and 300 Adam steps, seed 20261023; equal FLOPs are not claimed.
Natural execution is blocked and no new independent validation is claimed.

## Intended natural task (not frozen data acceptance)

WIT English image/caption correspondence, not semantic class recognition. Text <!-- codespell:ignore wit -->
metadata is CC BY-SA 3.0; images require individual author/license/source-page
verification and local evidence. Reject unresolved rights, unavailable pixels,
missing captions, ambiguous source identity. Do not treat repository code license
as image license. Count every exclusion and retain its reason, before outcomes.
CLIP ViT-B/32 frozen image/text towers, official preprocessing, truncation at 77
tokens explicitly logged. Checkpoint SHA256 from author URL:
40d365715913c9da98579312b702a82c18be219cc2a73407c4526f58eba950af.
Natural extraction/audit adapter remains unimplemented and natural mode fails
closed. An exact natural manifest, extraction source hash and development-only
verification must be frozen in a new preregistration before natural holdout use.
Do not silently remove this lock or call this plan a completed natural freeze.

## Executable engineering protocol

`fixture` produces 600 synthetic source pairs (64-dimensional normalized features).
No images, natural captions or pretrained weights are implied. Shared projection
is fixed seed QR to 32 dimensions and normalized; cosine/cache/full-linear retain
full vectors. `freeze` hashes bank, manifest, code, config and exact example list.
`run` rejects drift before fitting. No threshold/model selection uses test results.

Union components by identical image bytes SHA256, source ID and page ID before
splitting. Sort by ID, seeded shuffle, block five components. Assign whole blocks
by SHA256 bucket: train 60%, temperature 10%, conformal calibration 15%, test 15%.
Negative donors stay in the same block/split, enabling disjoint block bootstrap.
For each anchor: one true pair, one highest-cosine other-component hard negative,
one distinct random other-component negative. Positives are minority 1/3.
For natural WIT these are weak correspondence labels: semantic false negatives <!-- codespell:ignore wit -->
remain possible. A blinded ambiguity audit would be required before claiming
semantic match performance. No old feature bank is an independent holdout.

Experiment 1: paired concat-linear (u.I+v.T+c), gated mixture
sigmoid(c*cos(I,T))*(u.I)+(1-g)*(v.T), rank-1 (u.I)*(v.T)+c,
and single-hidden-unit MLP c*tanh(w.[I,T]). All have 65 parameters.
This constrained gate/MLP lacks an output bias; rank-1 lacks additive terms.
These deliberate budget restrictions can hurt them and must not be hidden.
Train text-only/image-only linear ablations and full-dimensional linear.
Additional cosine logit=20*(full cosine-.25), fixed without development search.
Cache-inspired baseline uses normalized [I,T] train keys, correspondence +/-1
values, exp(-5*(1-affinity)) vote added to cosine logit. Alpha=1/beta=5 fixed.
It is NOT a Tip-Adapter reproduction or answer-position cache.

Experiment 2: reuse weights/calibration under within-block cyclic text shuffle,
missing text, missing image; retain original labels. Also constant gate state=1
and cyclically shuffled gate state. These are artificial stress diagnostics, NOT
natural-distribution measurements, and shuffle can retain identical donor text.
No dynamic routing/refinement or heldout oracle is implemented.

Fit one temperature per model on temperature split, grid {.5,1,2,4,8}; tie goes
smallest. Fit conformal quantile from calibration-block maximum true-label
nonconformity (1-p_y), ceil((B+1)*.9) order statistic; if beyond B use 1.
Report block/row coverage and set size, without promising formal validity under
natural distribution shift. Confidence acceptance >=.8 separately; target
coverage >=.5 and minority recall >=.7. No post-test recalibration for perturbations.
Report macro-F1, balanced accuracy, class recalls, NLL, Brier, 10-bin confidence
ECE, selective risk (null for no accepted rows), and individual probabilities,
labels, prediction sets, source indices, split/block and condition.

Three predeclared paired delta macro-F1 comparisons (gated/rank-1/MLP vs linear),
1000 block bootstrap replicates, Bonferroni 98.333% percentile intervals.
A future scientific claim additionally requires >=50 independent test blocks,
delta >=.02, corrected lower CI >0, above calibration/coverage criteria and
comparison against the strongest preselected development baseline. This pilot
only computes contrasts against projected linear and can never issue PASS.
Strong-baseline superiority and out-of-distribution generalization are unproven.

## Primary references and method limits

- GMU paper https://arxiv.org/abs/1702.01992 ; author code https://github.com/johnarevalo/gmu-mmimdb
- LMF paper https://aclanthology.org/P18-1209/ ; author code https://github.com/Justin1904/Low-rank-Multimodal-Fusion
- CLIP paper https://arxiv.org/abs/2103.00020 ; code/model license https://github.com/openai/CLIP
- Tip-Adapter paper https://arxiv.org/abs/2207.09519 ; author code https://github.com/gaopengcuhk/Tip-Adapter
- WIT paper https://arxiv.org/abs/2103.01913 ; official license https://github.com/google-research-datasets/wit/blob/main/LICENSE <!-- codespell:ignore wit -->
- WIT download documentation https://github.com/google-research-datasets/wit/blob/main/DATA.md <!-- codespell:ignore wit -->
- SelectiveNet https://proceedings.mlr.press/v97/geifman19a.html
- CALM https://arxiv.org/abs/2207.07061

GMU supports gated fusion; LMF supports factorized multiplicative fusion; neither
paper guarantees this severely constrained pilot will improve. Tip-Adapter uses
fixed-category few-shot classification, unlike caption correspondence. SelectiveNet
jointly optimizes selection/classification; CALM concerns language-model early exit.
Their guarantees do not transfer to this confidence threshold or frozen pair model.
Public author-code hashes and URLs are recorded in SOURCES.json. No third-party
implementation is included in this patch.

## Historical engineering supplement (added before either new run)

Explicitly authorized historical P39 input at exact source
05ff4eda77e5494d2dffb64cd906300fe6498df3, archive manifest SHA256
2a853d6c975b30d98a8c79348f01bb3f5b26f36793f2986826a5deed3ea4454e;
11 verified shards restore 91 hash-checked members. Features SHA256
1a4458c0d065d697ae491190ec00c0d30b29b8bc853cb96400d9ed1d432941ae.
Historical source manifest retains COCO/Flickr URLs, image hashes, CC BY 2.0 /
CC BY-SA 2.0 license IDs 4/5 and CC BY 4.0 annotation metadata. These are retained
provenance claims, not new publisher attestation or renewed per-author rights audit.
No photos/checkpoints redistributed or fetched. This authorized feature-only
reanalysis is not a substitute for the stricter fresh natural cohort audit.

Preserve original rows and train/dev/calibration/test names; dev supplies only the
fixed temperature choice. The old test stays **previously seen historical test**,
never independent validation. No new random negatives or split applied.
Use the same frozen head/projection/optimizer/settings above without tuning to
historical scores. Underlying encoder is embeddinggemma2_740m with 768-dimensional
vectors, revision 914f7f89142e33e77833254d9c9b90c3cef7303b;
image tower input contains a fixed neutral text prompt. Cosine is therefore
embeddinggemma cosine, NOT CLIP cosine. The balanced historical test has no
minority class: report minority_recall=null and positive/per-class recalls.
All bootstrap intervals on it are descriptive development statistics only.
No archived original Head replay (torch absent) is claimed.
