# E27: original pretrained shared Encoder + answer-sensitive token Cell Head

**Date:** 2026-10-16. **Status:** research candidate / `DRAFT` / `SHADOW_ONLY` / `DENY_ALL`. This is a source-only candidate until its exact GitHub hosted source-HEAD and synthetic-merge original-model jobs actually finish. No native Hepta Neuron or NDU owner is modified; no source data, model weights, private training logs or original questions are committed. No baseline PR is rewritten.

## Motivation: respond to a measured Reader bottleneck, not a new FBSDE identity

- E12 numerical FBSDE local/global solve and E12 neural warm-start established a bounded **finite-discrete** mathematical mechanism only, at higher complete compute cost than cheap direct controls.
- The original real pretrained MultiRC conditioned Reader archived in GitHub artifact `11946621518` scored 16/33 genuine candidate answers, with 8/8 original questions having candidate-score spans <= 0.001. E14/E15/E25 and AG News E9/E10 had no qualified NDU cost advantage. A new FBSDE on the old nearly answer-blind Head cannot manufacture unavailable task information.
- E27 tests a **different representation**: for each original evidence paragraph one shared frozen public `answerdotai/ModernBERT-base` token Encoder produces evidence tokens once; it separately embeds each original question and each complete genuine answer. A small trained Head performs task-conditioned, answer-conditioned token attention. The matched control **masks candidate-answer embedding inside an identical-size Head**. It is not a copy of 421M parameters, nor does immutable weight sharing imply that the physical embedding work is free.

## Actual tensor model and controlled differentiation

With frozen evidence tokens `E_i` and pooled question/answer vectors `q,a` from the **same immutable shared model**:

```
q_r=W_q q, a_r=W_a a, e_ri=W_e E_i        (rank 16)
alpha_i=softmax_i(<e_ri,q_r+a_r>/sqrt(16))
c=sum_i alpha_i e_ri
p(y=1)=sigmoid(MLP_32([q_r,a_r,c,a_r*c]))
```

Training has two separate, identically initialized 64-step AdamW jobs with the same original training examples, source-question batch order, rank, parameter count, output heads and losses. The matched `answer_muted` arm sets `a_r=0` **inside the Head only**, keeping the tokenizer/model invocation inventory identical. Distinct optimizer trajectories and computed tensor work still differ; record both physical CPU times instead of claiming exact equal FLOPs. The paired loss on genuine original TRAIN native alternatives is candidate BCE plus optional within-question positive/negative softplus ranking if those classes are present. The encoder is frozen throughout, and both Head weights are separate candidate copies.

Exact immutable upstream model: `answerdotai/ModernBERT-base@8949b909ec900327062f0ebf497f51aef5e6f0c8`. All five original model config/safetensors/tokenizer SHA-256 are checked before loading; no `trust_remote_code`, mutable tag or randomly initialized substitute. Model input max 256 tokens; **every truncated sequence is counted** (truncation may remove relevant premises and therefore denies sufficiency). CPU shared base is instantiated once per experiment. The pretrained **model forward count**, token count, model CPU/wall, feature generation, separate per-Head fitting and inference work are recorded. These are host-self-reported costs, not independent power/GPU/total-service accounting.

## Exact dataset and source-owner separation

- Authentic publisher dataset: `aps/super_glue`, immutable revision `4e14482c58d790d467ecfb29b6790e1917bf8756`, source train SHA-256 `ced6d731a335a0e4fbd29f6f382f291518952c0f449448361d294000c39e6728`, validation SHA-256 `5eb64893afc5af7828b2f3b41d6a4574eb7a82cbb17c86c75842f5f95f679ada`.
- For bounded resource budget: **48 complete training paragraphs** and **8 complete validation paragraphs** ordered by a public, deterministic SHA of paragraph ID and actual evidence bytes. Full native question/candidate identity and unfiltered candidate alternatives are bound before reading outcomes. Input-size exclusion removes **the entire paragraph**, never just a negative or hard candidate. The train-side original 0/1 labels are available only in the train material; held input excludes all labels. All previous original source papers/experiments are retained; these eight passages may overlap previous validation studies, so they are **not prospective new observation-time or independent dataset-family evidence**.
- Material-owner GH job downloads train and validation original parquet, validates byte SHA, publishes `train-only.json` (with TRAIN truth), `held-BLIND.json` (NO held truth), and a **separate** original gold artifact. Trainer GH job downloads only public training/held artifacts and the pinned pretrained model. An independent scorer job fetches publisher validation parquet a second time and checks every identity/paragraph/question/answer byte against blind inputs and every label against separately held original gold, then evaluates the **presealed predictions**. GitHub Actions job isolation is process control, not cryptographic proof that public human labels were secret.

## Original scoring and adversarial controls

Primary factual metric: number of complete original MultiRC questions for which **every native answer candidate** is classified correctly. Secondary: candidate accuracy, candidate Brier, within-question candidate probability span, count of mixed-label questions, per-source whole-question deltas, and a bounded two-sided exact source-cluster sign-flip reference. Eight passages are eight source clusters, not 100+ independent answer rows. Mean span > 0 does not imply correct semantic evidence use.

The frozen evaluation algorithm rejects candidate/source reordering, duplicate/ghost answers, missing original questions, mismatched source text SHA, invalid labels, an extra held label in a public message, wrong model bytes, incorrect Encoder/optimizer counters, token/cost zeroes, absent original paired controls and attempted capability promotion. It **does not** independently reforward the pretrained model or re-execute Torch SGD; a malicious producer may still forge self-reported logits/timing. The result explicitly says those independent audits are **false**, and does not authorize production.

**Candidate hypothesis, fixed before this new physical attempt:** the answer-aware Head must improve whole-question correctness over the matched answer-masked Head, survive an exact source-cluster permutation contrast and show robust answer-span while accounting for all extra physical work. These existing validation passages are historically public/explored; even a positive observed score is exploratory and cannot qualify scientific independent prospective efficacy, learned NDU utility or any production selection. A strict consumer must use an independently identified new source/time panel and full-service cost before making that claim. Zero/negative improvement = explicit NO-GO. Evidence insufficiency, unreproduced logits, missing original files or truncation = HOLD.

## Commands on registered original dependencies

```
ROOT=qualification/stem-cell-v1
PYTHONPATH="$ROOT" python -W error::ResourceWarning -m unittest discover -s "$ROOT" -p 'test_e27_*.py' -v
PYTHONPATH="$ROOT" python -O -W error::ResourceWarning -m unittest discover -s "$ROOT" -p 'test_e27_*.py' -v
# Production-shaped three stages are in .github/workflows/hepta-e27-original-answer-token-cell.yml.
```

## Test evidence and strict nonclaims

Authoring host ran 24 Python Torch/stdlib **synthetic-input mechanism tests** normally and 24 with `python -O`, both with zero skips/failures, plus source compilation and CI YAML/static shell checks. These are genuine small tensor-gradient executions, NOT actual 149M checkpoint loading nor original human-label result. The real pinned pretrained Encoder and original publisher source are required, without fallback, on exact GitHub Actions jobs. Fresh source/merge architecture and blocking CI also remain mandatory. `model_selected=false`, `production_accepted=false`, `independent_publisher_signature_verified=false`, `natural_task_generalization_established=false`, `full_fbsde_neural_reasoning_gain=false`, `automatic_cell_split=false`, `FinalUse=false`, **`authority=DENY_ALL`**.

## P3: exact source closure and Torch-free material owner repair (2026-10-16)

The research stack inherited #2531 and contains **only E27** source files beneath
`qualification/stem-cell-v1`. Its original hosted workflow erroneously tried to
import `multirc_materials` and invoke `public_encoder_probe.py` as though that
module tree existed in the checked-out branch. The original material-owner job
also imported Torch implicitly via the E27 Head, despite not installing Torch.
Both are runnable-source blockers, NOT observed neural/task-quality failures.

The repaired workflow checks out a **separate read-only original Reader donor**
`TrillionniumFoundation/hepta-private-ci@50f9a77cecb1ddc18b4d674db15a22a873726663`
into `e27-donor/` in each source/merge matrix job, checks its exact Git HEAD,
then admits original pinned `multirc_materials.py` and
`public_encoder_probe.py` from that immutable checkout only. It never replaces
E27 code, rewrites prior PRs, merges main or treats a donor as production.

`e27_material_contract.py` now owns the unchanged versioned E27 data schema,
SHA function and source restrictions as pure standard-library operations.
Importing `e27_reader_owner` no longer imports Torch; only the blind training
function loads `e27_token_interaction` and its optimizer. A dedicated no-site-
packages subprocess test proves that 48 TRAIN and 8 HELD fixture paragraphs can
be admitted without Torch or Transformers. All prior neural tensor tests remain.

The source closure is a **necessary engineering repair, not new original-model
success**. Source/synthetic-merge CI must actually execute the exact source;
individual admitted original weights, publisher labels, whole-question results,
performance, independent physical attestation and production remain unqualified.
`DRAFT / SHADOW_ONLY / DENY_ALL / NO_MAIN_MERGE / NO_FINALUSE` is unchanged.

## P4: actual hosted E27 source/material error (2026-10-16)

Workflow 38930365910 at exact #2548 head `c227de511654675f351c12e6515658d22ea0f5b5` completed **failure**. Exact source-head and merge source-contract jobs failed because `test_e27_material_contract` read the workflow from the module directory rather than repository `.github/workflows`. Both material-owner jobs acquired the exact pinned publisher Parquet and then failed `insufficient/oversized original source support`: the old combined error masked whether SHA-sorted 48 original TRAIN paragraphs exceeded the registered aggregate bounds (`n_questions <= 288`, `n_cases <= 1200`) or lacked required within-question mixed-label support. That exception grouped those independent predicates, so the exact offending aggregate was not previously logged. Neither original pretrained Reader training nor human evaluation ran.

The repair keeps the original 48 TRAIN/8 HELD paragraph caps, source IDs, full admitted questions/answers, label-free held values and exact 288/1200 hard capacity. For TRAIN only it selects full original public paragraphs by predeclared encoder-work cost (1 + question count + native candidate count), ties by immutable source hash, **before examining any label values**; never cuts a question/answer slate or uses utility to select cases. HELD source still uses the prior SHA order, so original independent reviewer semantics are unchanged. If 48 whole TRAIN paragraphs cannot be supported within hard capacity or mixed-label support is insufficient, fail closed with the distinct existing training contract; no budget, outcome or authority bypass. This cost-targeted training sample is NOT random/representative of the original MultiRC distribution and requires independent prospectively sampled groups before any efficacy claim. The affected tests now locate the workflow in its real repository path.

Historical global `blocking-ci` also failed unrelated cargo-deny advisories, Windows Bazel and formatting. They remain open independent blockers, not permission to skip them. `DRAFT / SHADOW_ONLY / DENY_ALL / NO_FINALUSE / NO_MAIN_MERGE`.
