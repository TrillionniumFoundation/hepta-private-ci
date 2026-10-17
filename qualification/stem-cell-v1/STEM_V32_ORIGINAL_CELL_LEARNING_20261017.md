# V32 — Original frozen mmBERT feature reuse and Cell0→Cell1 adaptation

2026-10-17 · Strict **DRAFT / SHADOW_ONLY / DENY_ALL**; only an additive child
of [V31 NO_GO](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2692)
exact head `e02cdbd580267b74e0b02dfffaeeffb1be1e04c4`.
No change to `main`, selected Encoder, Cell/Supervisor lifecycle, Worker, Control,
CNS, NDU/selector/evaluator, Artifact CAS, learning journal or signed FinalUse.

## Why this is NOT a repetition of the same-source ScienceQA CPU/accuracy gate

The previous [V31 original-source research](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2692)
relates **ScienceQA** original historical 64-case evaluation (text 17/64,
conditional 17/64; 5 rescues/5 harms) and independent physical Granite+DINO
feature CPU costs (average ~28.16% selective feature-only CPU reduction).
It has **no proof of improved task utility**. **This new study is a DIFFERENT
publisher, AG News, and MUST NOT combine its task results with ScienceQA as
paired cases or claim that one explains the other.** AG News source membership
itself assigns two `cell` identities; no invented task names or routing are used.

Frozen original source evidence is existing publicly completed model run
[38546717991](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38546717991),
original artifact `11890616195`, full ZIP SHA256
`0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7`.
It contains original **128×384 float32 mmBERT pretrained features**; original
`features.safetensors` SHA256
`e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490`,
original publisher raw dataset SHA256
`50335a2214756c7a9e09fee9ac9ed27ab855ea98635bb0fab0998144165ffb2c`,
and original archived owner commit `4133d6ac5bd3f8d4200c56fffb09e6aba004a084`.
This is the **identical original material** used by existing research
[V18](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2481)
/ [V19](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2530),
not a newly executed Encoder. V14 control manifest SHA256
`d029f906565946216126db39e4ca3f4f14d7ab5a3c297ec2a62639ccdfbf604a`
is independently reconstructed exactly before the sample reduction.

## Strong material and source-target isolation

The model-visible immutable material is only the **original 64 TRAIN cases**:
32 original Cell0 + 32 original Cell1 and original frozen 384D vectors.
The stager sees publisher archive labels, but writes **neither 32 CAL nor
32 BLIND labels, texts nor features** into the learner workspace. The uploaded
archive is removed before optimizer execution. Source and output directories
are create-only; source bytes are SHA-fenced exactly:

- staged original 64×384 FP32 feature bytes
  `2530b62d48b593cebeeb783c3ee754f8229b924558340dd09fb7160c6d1e3cc3`
- original TRAIN-only source meta bytes
  `69bdb09bb235c9cf490da400e239c5d9fabe8e13327cb255721090ea47d2e096`

Only the **64 original TRAIN features** are used for TRAIN-only mean/std
normalization, precisely the V19 reference rule. No loaded 421M or duplicated
mmBERT per-Cell weights, no retrieval from TEST/BLIND, no new Encoder forwards.
An identical hash still is **not** a signed model issuer, independent label
custodian or future-source evaluator.

## Equal-update stage study and variants

Original `cell=0` is an artificial **old stage**, `cell=1` an artificial
**new stage**. This is a retrospective staging order over a public static
publisher corpus, **NOT** an observed chronological task transition.

Four deterministic SOURCE-ID folds each hold out 8 Cell0 + 8 Cell1 examples.
The learner has 24 Cell0 + 24 Cell1 fit examples per fold and **never fits on
the fold-held 16 labels**. The publisher source controls this immutable
`cell` label, not a supervised outcome classifier. Seeds 41/47/53.

Every fold/seed physically fits (1) an old zero-initialized 1,540-parameter
linear Head for **40 AdamW steps**, then (2) a normal unsplit continuation
for **40** on new-only, and (3) a same-parameter rehearsal candidate for **40**
on 8 old + 8 new examples per batch. Each Head update consumes 16 examples;
all paid training is accounted: **3 seeds × 4 folds × (40+40+40) = 1,440
physical Head optimizer steps**. The separate split Cell0 is an immutable
copy of the Stage-1 old Head and split Cell1 **reuses the exact actual
continued Head state**. No wasteful duplicate 40-step new-cell retraining.

Compare five source-bound OOF arms:

1. `nochange`: Stage-1 frozen old Head across Cell0/Cell1;
2. `continued`: one ordinary 1,540-parameter Head updated new-only;
3. `rehearsal`: same-sized single Head, 40 updates with paid 8-old/8-new replay;
4. `split`: *two* physical 1,540-parameter Heads, route by original source
   Cell0/Cell1; retains exactly old Head for Cell0 and new continuation for Cell1;
5. `source_blind_ensemble`: average logits from the **exact same two Heads
   as split** without privileged source-cell routing. No new weights or updates.

The **split-vs-source-blind ensemble** is exactly parameter/memory/optimizer
matched: two Heads, **3,080 total FP32 weights = 12,320 weight bytes**;
both use the same actual trained states. However, mean ensemble scores two
Heads per input while split scores one, so **active serving FLOPs are not
matched**. `continued` and `rehearsal` have 1,540 weights (6,160 B), so
neither is total-parameter-matched to split. Rehearsal also retains explicit
old feature examples; those bytes must count in any real lifecycle study.

## Actually executed local ORIGINAL source results (NOT future/production)

All scores are 64/seed on **fourfold TRAIN-only out-of-fold** cases (32 Cell0
and 32 Cell1); no CAL or BLIND score is opened by this pipeline.

| Variant | Seed 41 Cell0/Cell1 | Seed 47 Cell0/Cell1 | Seed 53 Cell0/Cell1 |
| --- | --- | --- | --- |
| Frozen stage1 nochange | 19 / 18 | 20 / 18 | 19 / 18 |
| Single-Head continued | 20 / 21 | 19 / 22 | 23 / 21 |
| Single-Head rehearsal | 22 / 19 | 21 / 18 | 25 / 22 |
| Split Cell0 old / Cell1 trained | 19 / 21 | 20 / 22 | 19 / 21 |
| Two-Head source-blind mean | **21 / 22** | **20 / 23** | **24 / 22** |

At equal stored weights, source-blind ensemble scored 43/43/46 cases versus
split's 40/42/40 in seeds 41/47/53. **Specialization is NOT qualified as
better** on this original TRAIN panel. Split preserves old-stage Cell0 logits
by construction, not by learning an independently demonstrated retention rule.
These are exploratory comparisons on already-seen publisher family and
original TRAIN source groups, and analysis selected after studying other
experimental branches. Do **not** infer prospective efficacy, unbiased
selection confidence, lifelong learning or self-evolving intelligence.

## Independent physical evidence vs full authorization

`v32_original_cell_learning.py` actually executes PyTorch CPU SGD/AdamW
updates and saves complete PRIVATE Head tensors and held-OOF logits locally.
`v32_independent_numpy_review.py` **does not import Torch or producer**;
reconstructs all 48 original Head state/weight digests and 60 model-output
digests using only original frozen feature and labels, with FP32 tolerance
`<1e-4`, recomputes Brier and correct for each original Cell and fold,
checks source/missing-label custody, physical optimizer meter and strict
cost/split-state reuse. It does **not** independently replay optimizer
gradients, validate an independently signed model manifest, measure full
CPU/GPU serving, old publisher temporal history, or recover kernel Cell Split.

Two local, separately executed source-preserving Python processes (ordinary and
`-O`) reproducibly generated all 12 fold-specific model identities and
identical independent NumPy readouts. Adversarial tests cover feature forgery,
wrong Head logits, source misrouting, CAL/BLIND/authority injection, unpaid
updates and missing original evidence. The checked-in JSON is only the
**sanitized** actual original train-only NumPy report (no raw source text,
case IDs, labels, model weights, logits or run credentials).

A **new exact-SHA hosted GitHub Actions push** must re-acquire the original
artifact with credential-free signed URL handling, enforce exact source
hashes, run physical learning twice, inspect independent review, and match
this historic development OOF result; PR source checks cannot claim physical
success. Global `blocking-ci`, Rust model lifecycle, independent NDU evaluation,
new source families, chronological future windows, true old-task retention,
calibration, negative-transfer, p95/p99, 64–4,096 active Cells and signed
FinalUse ALL remain **OPEN**.

**Release posture:** `HOLD_ORIGINAL_TRAIN_OOF_NO_PROSPECTIVE_SELECTION`;
`DRAFT / SHADOW_ONLY / DENY_ALL / NO_STEM_OR_CELL_PROMOTION / NO_MAIN_MERGE`.
