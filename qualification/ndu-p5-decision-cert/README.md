# P5: globally bound-aware adaptive computation for a registered discrete FBSDE

**Research / shadow only; DENY_ALL.** Stacked on #2003 (exact candidate source
`7cb31733a39a143bf74b9045ab5acb905651c941`). This is a new *solver
stopping policy* over the EXISTING bounded FBSDE owner and independent Newton
reference, not a new stochastic NDU owner, neural model, multimodal Encoder,
or general continuous-time FBSDE theorem. Neither #2003 nor queued P0 #1923
is changed by this experiment.

## Frozen public control problem and mathematical bound

Same terminal objective `G(X_T)=tanh(X_T)`, event law and cost conventions across
three legal actions; only the controlled coupling coefficient `a` and the
registered action price change. Fixed nonanticipative binary chance tree,
`steps=4`, horizon `T=0.8`. For each globally admitted action `a_j`, the
existing full-tree Picard map is `F_j(y)` with the *declared sufficient*
contraction upper bound `q_j=a_j*T*(1+beta*T)<0.95`. Its root utility includes
one time-counted action cost. For a contraction on its complete registered
domain, a candidate field `y` has the *nominal* root-value error bound:

    epsilon_j = ||y - F_j(y)||_infinity / (1-q_j)
    L_j = y_root - cost_j - epsilon_j
    U_j = y_root - cost_j + epsilon_j

An extra explicit no-op action has exact value zero. Only if some action's
`L_j > max_{k != j} U_k` does the planner stop with a **nominal** discrete
best-action certificate. Otherwise it refines the still-competitive largest
uncertainty interval, charges one actual whole-tree map call, and rechecks.
At its frozen `max_calls=90`, ambiguity/budget exhaustion returns **no
certified action**. A wrong interior terminal reset is never an admissible
continuation field. The action-gap result is conditional on the contraction
bound, the whole-tree state law and ideal real arithmetic: Python FP64 intervals
are NOT outward-rounded, and there is no certified continuous FBSDE limit.

## Independently executed paired evaluation

Two seed-frozen source-disjoint generated cohorts (`cohort_a`, `cohort_b`),
96 tasks each. Preregister the entire action/state law and frozen code seeds
BEFORE predictions; `study.py predict` sees no independent reference optimum.
Create-only sealed predictions are passed to another process importing an
independent prefix-indexed `direct_map`, and independently rerunning all
reported per-action iterative work. It checks the claimed `Z`-compatible global
operator bounds by the same whole-tree law; compares actions to *new* full
Picard solutions and **24** independently computed Newton action spot checks.
All raw outputs and failed requests remain retained for post-run audit.

Three cheap controls are never silently discarded: exact non-coupled `a=0`
BSDE (one operator call), one forward-map approximation for all candidates,
and fixed-four-steps-per-action. The no-op value is present in every arm.
The scorer checks cheap controls independently and charges actual map calls.

| Cohort (96 tasks) | Nominal gap-certified | Adaptive calls | Uniform Picard calls | Fixed-4 calls | One-map wrong | Fixed-4 wrong |
|---|---:|---:|---:|---:|---:|---:|
| A | 96 | 758 | 3036 | 1152 | 49 | 0 |
| B | 96 | 753 | 3083 | 1152 | 44 | 2 |
| **Total** | **192** | **1511** | **6119** | **2304** | **93** | **2** |

Independent reference found zero mismatches for the 192 nominally certified
choices. Whole-tree operator calls fall 75.3% vs uniform full-precision Picard,
34.4% vs fixed four steps; baseline single-map/uncoupled choices lose on 93
synthetic tasks. This does NOT mean learned intelligence or natural-language
reasoning emerged. The adaptive action index uses only registered public
coefficients, not any observed future label. Cumulative Python CPU time is
measured on the local host and varies with scheduling; comparisons of **exact
operator calls** are the stable primary metric, and scoring, reference/Newton,
failed attempts, source creation and audit are reported separately from
individual policy runtime. No dummy workload is inserted for cheaper arms.

## Exact reproducibility

The SHA256 of the canonical preregistered source object is
`e420444337d163508cd7ba8122894ffd334566b52d57073e67b94203e301eac2`.
The LF-terminated `plan.json` file digest is
`92c568e9694c259b64ac1f8bb1f6db9d9214dd14ca13c81ff7d1f75bbea7a607`.
`test_decision.py` independently requires all 192 slots, preserves ties and
budget exhaustion as uncertified, and mutation-tests wrong source identities,
caller authority, incomplete/forged resources, results, controls and option
bounds, both with ordinary Python and with `python -O` (no assert-only gates).

```bash
python3 -m unittest discover -s qualification/ndu-p5-decision-cert -p 'test_*.py' -v
python3 -O -m unittest discover -s qualification/ndu-p5-decision-cert -p 'test_*.py' -v
python3 qualification/ndu-p5-decision-cert/study.py plan --output /tmp/p5-plan.json
SOURCE=$(sha256sum /tmp/p5-plan.json | cut -d' ' -f1)
python3 qualification/ndu-p5-decision-cert/study.py predict \
  --source /tmp/p5-plan.json --source-sha256 "$SOURCE" --output /tmp/p5-predictions.json
SEAL=$(sha256sum /tmp/p5-predictions.json | cut -d' ' -f1)
python3 qualification/ndu-p5-decision-cert/independent_score.py \
  --source /tmp/p5-plan.json --source-sha256 "$SOURCE" \
  --sealed /tmp/p5-predictions.json --sealed-sha256 "$SEAL" \
  --output /tmp/p5-independent.json
```

## Hard nonclaims / next acceptance

- Two source-disjoint **synthetic** cohorts are NOT two future observation-time
  windows, true external utility, pretrained-multimodal learning or natural
  semantics; the entire binary law is known, not learned from the environment.
- Global *discrete* contraction is an admitted assumption from the existing P5
  reference. No outward interval FP64, model misspecification robustness,
  continuous-space decoupling regularity or statistical significance claim.
- The synthetic action set consists of frozen all-horizon controls. There is no
  optimizer over all adapted policies and no universal System 2 optimality.
- Work/cpu receipts are only local observations, not independent host-attested
  CPU/GPU energy or production batch/queue/Power telemetry.
- Production native NDU coefficients, historical Laya/Stem comparisons,
  independent evaluator, artifact selection, FinalUse and blocking-ci remain
  unchanged and mandatory. Always `p5_accepted=false`, `DENY_ALL`.

Scientific next step: test whether the same bound-aware stopping *actually*
beats strong Bellman/critic controls at matched quality and full physical cost
on independently observed real decision tasks. Do not infer this from toy costs.
