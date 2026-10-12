# Frozen source-support fallback and held-out policy risk selection

Continuation of #1550 at e1f2af3c8f1ee553d29b45751926ab14975b35ea. The original
banking cohort, all historical controls, measured 100 ms view ceiling, owner
boundaries and acceptance reviewer remain unchanged. No new admission service.

## Newly observed parent physical result

Parent run 38161695542 completed the real mmBERT joint_backoff_cv_v2 acquisition
job. Artifact 11711952374, SHA256
78275a957179c755c05b8b69344c50605939052004850ef4b4a436c76bd6fe45,
was downloaded and audited against original labels and all 6,677 requested views.
On 240 banking test texts NDU, myopic, compiled, risk and full-symbol all give
230 correct answers, 240 accepted, score .8766666667 and 480 test forwards each.
No extra NDU outcome value is demonstrated. The supported mmBERT run's maximum
view CPU was 88.737 ms, but one successful run does not prove budget reliability.

The uniform mmBERT job failed with 223.639 ms total / 223.368 ms Encoder phase;
the uniform hashing job failed with 106.190 ms total / 105.835 ms Head phase.
Original artifacts 11711758620 and 11711737420 are retained. Phase attribution
does NOT identify OS contention, GC, thread scheduling or another root cause.
No fresh unchanged retry or budget waiver is introduced in this increment.

## Frozen new task and controls

travel_guard_v1 uses eight intents not in the earlier banking/composition tasks:
book_flight, book_hotel, car_rental, flight_status, lost_luggage, carry_on,
plug_type, international_visa. The schema and hyperparameters were fixed before
executing or inspecting this cohort's labels/results in this continuation.
This is a new task family within the SAME public CLINC release, not external
preregistration, author independence, contamination exclusion or future data.

Per class: train[0:40] fits the Head, train[40:70] fits the joint law, val[0:10]
selects the original simple controllers; train[70:100]+val[10:20] calibrate the
frozen policy family, and test[0:30] is evaluated only afterward. Counts are
320/240/80/320/240. Original text overlap rejects. The validation-named directory
has the explicit role policy_risk_calibration ONLY in this new cohort; the old
banking validation meaning is unchanged. All model coefficients and the four
candidate policies are fixed before calibration predictions or labels are used.

Two raw-support guards use minima 5 and 20. At a low-support history, read the
full view if absent; otherwise use its actual Head symbol, bypassing an unreliable
joint posterior remapping. At supported histories keep the original neutral
BSDE action. Count matching original kernel rows, never smoothed pseudo-counts.
The complete candidate family is full_symbol, ndu_bsde, ndu_backoff_5,
ndu_backoff_20. All use the same legal view port and pay for their real reads.
No calibrated per-case risk is inferred from a support count.

## The conditional risk statement

For each frozen complete policy on n independent calibration sources, let A_i
indicate acceptance and E_i indicate wrong AND accepted. Set a=mean A_i,
e=mean E_i. The target is R=mean E[E_i] / mean E[A_i], with the same balanced
class mixture as the fixed-size calibration strata. Independence of sources,
within-class stability and absence of model/calibration leakage are assumptions,
not facts established by a unique text hash.

For independent Bernoulli variables, concavity of log(1-p+p*exp(t)) bounds the
product MGF by that at their average mean. Chernoff optimization therefore gives
exp(-n*KL(empirical || population_mean)) for the appropriate one-sided tail,
even when the individual class-conditional means differ. Invert it to obtain a
lower bound L_A and upper bound U_E. Apply delta=.05/(2*4) to the two directions
and four predeclared policies. With probability at least .95, all candidates
simultaneously satisfy R <= min(1,U_E/L_A) when L_A>0. Therefore data-dependent
choice INSIDE this fixed family does not evade the simultaneous bound.

The frozen research requirements are >=200 actual source rows, coverage lower
bound >=.5, and accepted-error upper bound <=.10. Choose maximal empirical
coverage, then the unchanged external utility, then fixed candidate order.
If none passes, risk_selected abstains. Zero accepted observations have no
zero-risk interpretation. Float bisection is not an outward-rounded certificate.
Public data assumptions remain unauthenticated; this is not production approval
or a guarantee under arbitrary drift. All uncertified controls are still measured.

## Recording and verification

Calibration runs complete and journals sync before risk-calibration.json is
sealed and the test loop starts. Source, prediction and model/kernel/objective
identities bind the choice. Calibration cannot use the selected arm recursively;
there is no validation-risk_selected output. The auditor independently rebuilds
original counts, risk bounds, candidate choice, raw support and allowed actions.
It rejects an edited winner, forged zero risk, stale objectives and missing data.
Calibration/compilation CPU is charged; budgets and model ownership are unchanged.

Use the existing entrypoint, with explicit backend (no automatic substitute):

```sh
PYTHONPATH=qualification/neuron-stem python qualification/neuron-stem/fbsde_study.py \
  --profile semantic_acquisition_v1 --backend hashing_reference_v1 \
  --kernel-profile joint_backoff_cv_v2 --cohort travel_guard_v1 \
  --publisher-root /original/publisher --output /new/travel-guard
```

The same workflow adds separate travel jobs for hashing and physical mmBERT.
Source/merge and all historical jobs remain. Fresh-head CI, real model execution,
new-data risk/utility, full lifecycle cost and native final-use/recovery are
separate requirements. Keep Draft; no main merge or activation.
