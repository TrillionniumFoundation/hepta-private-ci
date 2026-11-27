# E26 — pre-outcome exact six-passage admission test, bounded power and true E24 control

**2026-10-15. DRAFT / SHADOW / DENY_ALL.** Additive research child of E25 #2333, original immutable HEAD `5aa65b120df705d2c96adde9a093b4627958a64f`. No change to main, original Reader/Neuron, model selector, NDU, FinalUse, Q24/Q32, Evidence WAL, CAS, `blocking-ci` or predecessor E25 source. E25's actual six-passage pretrained forward / independent-human scorer was **queued and unobserved** when these rules were frozen. This manuscript and the literal `E26_FROZEN_HYPOTHESIS_20261015.json` freeze the research decision before the NEW SIX E25 labels are scored. The E24 tau `.01` was nevertheless selected **after seeing previous four passage outcomes**; do not mistake this for fully prospective preregistration.

## Statistical power cannot be ignored

E25 has exactly **six held passages**, each with two original questions and each question with 2–8 genuine candidates. Candidates are not independent tasks. For a paired source-cluster difference

`delta_g = complete_questions_E24_tau001(g) - complete_questions_E16_Brier(g)`

where `delta_g` is one of `-2,-1,0,1,2`, the exact, **two-sided** six-cluster sign-flip p-value is

`p = # {s in {-1,+1}^6 : |sum_g s_g delta_g| >= |sum_g delta_g|} / 64`.

When all six passage effects are nonzero and favor the same arm, the smallest possible two-sided p-value is **2/64 = 1/32 (0.03125)**. With even one tied passage, the minimum rises to **4/64 = 1/16 (0.0625)**. Under a **two-primary-hypothesis Holm adjustment**, even the best possible two-sided single-test p-value yields **adjusted 1/16 > .05**. Therefore E26 declares ONE research primary comparison only:

**E24 `question_softworst_tau_001` vs E16 `e16_scaled_brier_5`.**

The four original frozen Readers, candidate accuracy, other tau profiles and Brier are *descriptive*; they are not extra independently searched primary hypotheses. No posthoc relaxation after E25 scores arrive.

A research follow-up signal requires **all**:
1. Original E25 source-head/synthetic-merge human score and original source/model seals validated **outside** this model-free E26 helper, and E26 structure re-audit passes.
2. The exact two-sided source-cluster p-value <= 1/20 (0.05), computed on 6 source clusters, not 12 questions/variable candidates.
3. At least one additional whole question completed overall and **no per-passage whole-question regression**.
4. New actual-human average two-class Brier for tau .01 no more than **0.02 absolute worse** than E16 control (FP64 tolerance 1e-12 only for the comparison boundary).

These thresholds define an *exploratory follow-up signal*, NEVER a deployable/authorized winner. The .02 Brier tolerance is an engineering choice frozen here before NEW E25 outcomes, not a confirmatory independently justified clinical or statistical margin. Six related public dataset passages are underpowered and not a new time period, original signer or new data family. A significant sign flip also requires exchangeable passage-effect signs under the null; passage source dependence is unverified.

## What was actually independently executed now

- Source-bound **actual original human E24 independent-summary bytes** SHA-256 `b88af557b4fd2aa50a26f523aee452fb7a08bbe659b3f0fc4c0aaf325f8c9b59` (6,036 bytes), derived from the already completed original E24 human-label research process. On the old 4 passages, E24 tau .01 has 2 complete questions and E16 Brier 0; passage-level deltas **[+1,0,0,+1]**, exact two-sided `p=1/2` — NOT a demonstrated source-generalized learning gain.
- **Two algorithmically independent exact tests:** exhaustive signed enumeration and a dynamic-programming signed subset-sum count. Controls prove six-group floor `1/32` and two-primary Holm floor `1/16`.
- Full E25 expected original HUMAN scorer schema is validated for six passage totals, per-passage question/candidate sums, byte-hash-shaped original blind seal, exact genuine old source SHA, no production authority and exact independently rechecked E25 retrospective comparison fields. Missing/source-forged data reject. Test fixtures for hypothetical six-group outcomes are explicitly SYNTHETIC, not E25 model results.
- Exact SHA checked old E24 original file and literal new pre-registration. Create-only output, ordinary Python and `python -O` independent tests. E25's separate 31 full contract tests also rerun on its byte-pinned original pretrained archive.

## Reproduce

```sh
R=qualification/shared-stem-system2-architecture
export PYTHONPATH="$R"
python -m unittest discover -s "$R" -p 'test_e26_*.py' -v
python -O -m unittest discover -s "$R" -p 'test_e26_*.py' -v
python "$R/e26_frozen_admission.py" precheck --output /tmp/e26-pre-outcome.json
```

Only **after** original E25 hosted independent human score exists, has separately passed the original source-level checks, and its full SHA-256 is available:

```sh
python "$R/e26_frozen_admission.py" score \
  --e25-original-human-score /path/to/final-e25-score.json \
  --e25-score-sha256 ORIGINAL_E25_SCORE_SHA256 \
  --output /tmp/e26-descriptive-admission.json
```

The hypothetical synthetic E25 receipts used in `test_e26_frozen_admission.py` can only test rejection and arithmetic; they cannot authenticate a physical model or source signature.

## Hard nonclaims

`new_six_passage_model_outcome_observed=false`, `model_selected=false`, `production_accepted=false`. No new model weights/forwards, original six-source human label score, full hardware/service costs, new unrelated data family or time window, independent original label provider, NDU-FBSDE task gain, production Worker, FinalUse or trained Cell promotion. Never merge/activate from E26 local or hosted research CI; the E25 physical workflow, architectural gates, `blocking-ci` and independently verified future tasks remain prerequisites.
