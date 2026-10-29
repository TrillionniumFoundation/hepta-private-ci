# Finite CTMC gradients and censored complete paths

Run `node research/rr_snn_v3/validate_ctmc_gradients.cjs`.
The gradient protocol was committed before data generation at
7ff84ab65c524fdb78f4d7cd5297e038ab8af903. The validator emits the full report.
This module implements finite-state transition and continuation derivatives,
plus the score of a fully observed marked path. It does not differentiate a
general moving boundary or a discrete deadline argmax.

## Transition and continuation tangent

For a nominal generator Q and a signed row-zero direction dQ, the uniformization
rate nu is frozen at its nominal value. With R=I+Q/nu and dR=dQ/nu, powers obey
P[k+1]=P[k]R and D[k+1]=D[k]R+P[k]dR. The same Poisson weights yield the transition
and directional derivative; differentiated interval composition handles splitting.
The derivative series has an explicit truncation bound. Floating-point rounding
and generator validation tolerances remain separate sources of error.

continueValue differentiates the terminal value and discount rate as well as
the generator. The API rejects nonfinite results, invalid tangents and aggregate
exposure overflow. Fixed support is required; a zero rate cannot acquire a
positive realized-event log derivative through this interface.

A state generator alone does not retain self-spike semantics. For one evidence
state, Q=[0] has zero state-transition derivative, while a self-spike process has
expected count lambda*T. Budget and commitments must be part of the joint state,
or pulses must be represented with marked counting/reward operators. Deterministic
refractory periods require the hybrid event or age state. The event runtime uses
those explicit semantics; the complete network is not asserted to be a single
finite homogeneous matrix exponential.

## Complete-path score

For fully observed marks, log likelihood is the sum of log rates at all events
minus the integrated eligible hazard over the entire observation window.
Ordinary jumps, physical stochastic pulses and self-marks contribute their own
rates. The final no-event interval is included. Deterministic deadline emission
does not add a stochastic event log rate. A separately trained stochastic action
policy would require its own action likelihood.

The fixed experiment uses 512 training paths and 2048 separate heldout paths,
heterogeneous horizons and initial states, rates [1.2,0.65], fixed initialization
[0.35,2.2], and 400 gradient steps at learning rate 0.1 in log-rate parameters.
There is no holdout selection or architecture comparison.

## Executed reference results

Thirteen grouped checks pass, including nine rejected invalid/numerical inputs.
The maximum two-state analytic error is 3.963496197911809e-14 across 48 cases;
the noncommuting three-state finite-difference error is 1.2695025586317854e-11.
The joint continuation/terminal/discount derivative error is
4.252811644511745e-11. Five reciprocal rate/time scales spanning 1e-100 to 1e100
agree within 3.3306690738754696e-16.

Learned rates are [1.215819105861122,0.6557116693442029].
Independent count/exposure MLE is [1.2158191058612997,0.6557116693347288];
their maximum relative difference is 1.4448558144848914e-11.

| Evaluation | Fitted | Generating rates | Wrongly omitted final censor |
| --- | ---: | ---: | ---: |
| Heldout NLL per path | 1.4237367549400424 | 1.4235450224690538 | 1.7854174285229694 |
| First-event Brier | 0.16930673571597873 | 0.16918890536686934 | 0.20403244872768955 |

The deliberately wrong estimator is a regression counterexample, not a strong
architecture baseline. These results establish parameter recovery for the
declared synthetic complete-path experiment.

## Equal-summary maturity counterfactual

The independent mathematical fixture compares [0.2,0.4,1.6,1.8] with
[0.2,1,1,1.8]. Count, mean, min, max and total due fees are identical.
A first pulse before T=2 pays reward 5 and cancels unpaid obligations; each due
pending obligation costs 1. The only controls are constant intensity 0.5 or 2.
The fast control has declared additional cost 3.221761971732996, deliberately
chosen for a contrasting two-policy fixture, not estimated from a benchmark.

J(lambda;D)=5*(1-exp(-2*lambda))-sum(exp(-lambda*d))-controlCost(lambda).

Spread values are 0.5811359991710261 (slow), 0.49892489724481326 (fast).
Clustered values are 0.6361343969409625 (slow), 0.7183454988671754 (fast).
A summary-only policy cannot distinguish them; balanced best average regret
is 0.04110555096310642. All strong baselines must receive the same complete
maturity sequence, mask, budget and evidence. This proves decision relevance
of the schedule in this constructed model, not exclusive RR architecture value.
