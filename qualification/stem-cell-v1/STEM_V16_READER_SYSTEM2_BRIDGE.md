# V16 — Frozen Reader sufficiency → cost-bound System2 / Split robustness bridge

**Research only. DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO. Never merge to `main` or enable FinalUse from these results.**

## Motivation and exact predecessor

V14 (#2400) defines four real evidence conditions (no evidence, ordinary retrieval,
independently curated sufficient evidence, deleted critical premise) for the same
candidate Reader and a separately frozen stronger reference Reader. V15 (#2404)
defines a distinct four-arm finite-tree *additive-cost* System2 controller and a
non-authorizing Cell Split evaluator. Neither source-only contract has physically
run the whole required original Reader/evaluator trial. Earlier #2283 found an
online native NDU arm with **no prediction changes** but higher measured CPU.

A source-hash or successful unit test is not a model outcome. V16 connects the
**exact V14 sufficient-evidence candidate request** to V15's initial STOP
baseline. This makes the most basic comparison identifiable: if the original
Reader cannot use sufficient evidence to answer, deeper NDU computation should
not be credited for restoring a fundamentally missing Reader capacity. It also
prevents a System2 run being silently reinterpreted as the V14 retrieval/no
-evidence/lesion input, changing model version, substituting a new answer at
identical request SHA, or switching the adjudicated correctness/citation judgment.

## Source-only phase (before any original answers)

```
python3 qualification/stem-cell-v1/v16_reader_system2_bridge.py plan \
  --v14-plan PRIVATE/v14-frozen-source-only-plan.json \
  --v15-study PRIVATE/v15-source-only-study.json \
  > PRIVATE/v16-create-once-prelabel-seal.json
```

The complete canonical V14 and V15 validators must pass. Require:

* identical immutable objective SHA, same V14 **candidate** Reader weights,
  tokenizer and runtime SHA as V15; the reference Reader stays a *different*
  model for capacity diagnosis, not a creditable Stem/Cell gain;
* exact complete case roster, case/source-family/time-window identity;
* each V15 root input/request SHA exactly equal to the *V14 sufficient* prompt
  SHA. V14's question SHA remains separate from its full model-request SHA;
* precommitted root stop-success probability and graph/price/budget with no
  labels, answers, post-seal metrics or forged promotion fields;
* `model_host_authenticated=false`, `independent_evaluator_authenticated=false`
  and `production_authorized=false` unconditionally.

Save the source-first seal before dispatching the Reader; SHA-256 alone cannot
attest that the bytes were sealed before labels were available. An external
trusted owner must independently timestamp/sign source and outcome phases.

## Original execution and external independent outcome phase

V16 intentionally **does not download models, generate any Reader answer or
synthesize human judgments**. Prepare authentic SHA-pinned original V14 2-Reader
× 4-evidence answers and V15 same-Reader four-policy executions from the
separately authorized model host, along with original metered CPU/tokens and a
post-seal independent evaluator. Keep all raw questions, evidence, answers,
model weights, labels, private trace contents and receipts outside the public
Git tree. Run:

```
python3 qualification/stem-cell-v1/v16_reader_system2_bridge.py review \
  --v14-plan PRIVATE/v14-frozen-source-only-plan.json \
  --v14-predictions PRIVATE/v14-original-answers.json \
  --v14-adjudication PRIVATE/v14-independent-adjudication.json \
  --v15-study PRIVATE/v15-source-only-study.json \
  --v15-policy PRIVATE/v15-prelabel-policy-seal.json \
  --v15-execution PRIVATE/v15-original-model-execution.json \
  --v15-adjudication PRIVATE/v15-independent-adjudication.json \
  --prelabel-seal PRIVATE/v16-create-once-prelabel-seal.json
```

Both canonical V14 and V15 post-seal validators run again; V15 separately
recomputes its full finite-tree policy and execution trace. For **each case**,
V14 candidate + sufficient original `answer_sha256`, terminal request SHA,
correctness and semantic citation-entailment must be identical to V15 STOP.
This strict physical replay pilot assumes frozen deterministic generation; a
non-reproducible decoder must be studied as a new registered profile, never
silently accepted as the same original answer. No reuse/cache/FLOP saving is
deduced from matching answer or model hashes.

## Numerical diagnostics (strictly descriptive)

1. Count V14 candidate sufficient/retrieved/lesioned/absent answer correctness,
   reference sufficient correctness, abstention, and citation entailment. Do not
   convert a strong-reference success into a Stem/Cell learning effect.
2. Verify root STOP precommitted forecast calibration using exact integer Brier
   sums on externally adjudicated V14 candidate-sufficient results. Include a
   constant 0.5 untrained comparison and four fixed forecast quartiles. This is
   **in-sample descriptive calibration**, not prospectively validated fitness.
3. Compare V15 NDU shadow to STOP, fixed-one and greedy-one using **paired,
   casewise** external correctness and observed full-arm CPU/token totals with
   one registered additive cost profile. The micro-utility delta sums are exactly
   reconciled to the original V15 reviewer; forecast incremental action costs
   never replace measured actual end-to-end work.
4. Resample entire **claimed source-family clusters**, not individual questions
   or random seeds, with 1,024 deterministic bootstrap replicates seeded only
   from frozen source-first bridge SHA plus comparator name. Report case-weighted
   percentile intervals and worst leave-one-family-out net benefit. Family IDs
   are untrusted until a separate source owner authenticates deduplication.
5. Independently of Reader/System2, `split` reviews a complete V15 paired
   parent/split result and exposes **per future-window signed correctness delta**
   and old-task source-family regressions, preventing a net positive aggregate
   from hiding a failing future window. Synthetic positive gates stay non-authorizing.

Separate actual physical inference, forecast fitting/calibration, training,
model load, cache, migration, evaluation, rollback and energy costs must later
be measured on identical admitted source groups and a target host. This script
cannot authenticate a self-reported CPU counter, a SHA, issuer identity,
reviewer independence, a prospective source family or the production owner.
Without verified task outcomes, source independence, cost comparability and
actual physical model execution, every positive numeric result is still a NO-GO.

### Additional split sensitivity

```
python3 qualification/stem-cell-v1/v16_reader_system2_bridge.py split \
  --study PRIVATE/v15-split-source-first.json \
  --predictions PRIVATE/v15-paired-original-split-results.json \
  --adjudication PRIVATE/v15-sealed-split-judgments.json
```

The output never authorizes a Cell split. It does not reuse V14 source/Reader
qualification for unbound split data and does not assert that a historical
"future-1" string is an independently witnessed future time window.

## Actual unit verification scope

```
export PYTHONPATH=qualification/stem-cell-v1
python3 -m py_compile qualification/stem-cell-v1/v16_reader_system2_bridge.py \
  qualification/stem-cell-v1/test_v16_reader_system2_bridge.py
python3 -m unittest discover -s qualification/stem-cell-v1 -p 'test_v14_reader_sufficiency_gate.py' -v
python3 -m unittest discover -s qualification/stem-cell-v1 -p 'test_v15_system2_split_shadow.py' -v
python3 -m unittest discover -s qualification/stem-cell-v1 -p 'test_v16_reader_system2_bridge.py' -v
# Repeat all three under `python3 -O` (no assertions used as a validation gate).
```

The V16 unit fixtures are **entirely fabricated** and adversarial. The original
candidate/reference model weights, original evidence and independent human
reviewer are NOT available in the source-only workflow. An isolated local
analysis execution may use a V14 development-compatibility module; only
exact-HEAD GitHub CI loads the true inherited V14 module from the repository.
No new pretrained Reader call, stochastic/general FBSDE solution, calibrated
real forecast, autonomous Cell Split, multimodal generation or 10T/100T model
"equivalence" is implied.

## Go/no-go authority firewall

Every `v16` output hardcodes `HOLD_NO_GO` and `production_authorized=false`.
Model/Reader attestation, independent evaluation, three genuine future windows,
negative-transfer/old-task retention, complete matched physical lifecycle,
exact-HEAD CI and independently signed FinalUse remain separate hard gates.
Existing Hepta ownership, durable intent/outbox, revocation, WAL and CNS/Control
remain unchanged. No production module, worker, model, scope or artifact is
selected or modified by this change.
