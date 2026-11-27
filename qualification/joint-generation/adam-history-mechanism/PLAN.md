# Adam historical first-moment ablation — frozen before execution

Previous FIT raw-gradient H1/H2 failed; no gradient projection is justified.
Raw A/N increments were near aligned, but the prior diagnostic excluded saved
Adam moments. This distinct, post-outcome exploratory intervention tests whether
inherited first moment locally harms a different FIT source's text objective.
It neither rescues the failed old budget nor identifies the cause of old quality.

Restore all original 12 final states; no winner selection. Same fixed first FIT
source per digit 0..9, both variants, chosen before any restore. For update class
k use class (k+1) modulo 10 at the same noise variant as its distinct-source
sentinel. This arbitrary frozen cycle is not population inference. All sources
are FIT, not held-out validation. No DEV/TEST payload access.

Cache all20 original forwards/objectives, issued total gradients and separate
text gradients per model. Every one-step pair starts from the ORIGINAL saved
theta, m, v and sparse clocks, never the previous virtual update. Native arm
uses unchanged fixed_adam_step. Counterfactual removes only inherited beta1*m
from its numerator, retains identical updated v, sparse clocks, bias corrections
and epsilon, then globally rescales current-only displacement to the native
full-theta L2 norm. Reachability and all untouched parameters are preserved.
Verify symbolic native=current+history and symbolic/native engine agreement;
actual parameter displacement norms must agree rtol1e-10/atol1e-12.
No parameter checkpoint or optimizer state is saved from either arm. Original
parameters, moments, clocks, identity and sources must remain unchanged.

For each pair evaluate its fixed sentinel at native and counterfactual theta.
Report baseline/native/counterfactual text and total losses separately, finite
paired differences, and sentinel text-gradient dot/cosine with inherited history.
The positive cosine means inherited displacement is locally adverse to text;
it is not the dot product with a descent gradient. No new step-size choice.
Baseline/updated losses are compared only WITHIN the same cell and pair.

Primary H3: independently for C-N and E-N, BOTH seeds each must have:
1. >10/20 sentinel text losses counterfactual < native - 1e-10;
2. median(native text - counterfactual text) > 1e-10;
3. median cosine(sentinel text gradient, inherited history displacement) > 1e-12;
4. mean(counterfactual total - native total) <= 1e-10.
These are fixed descriptive gates, not statistical significance. All S/A cells
are controls reported fully; no pooling, model selection, relaxed gate or automatic
training follows. A pass supports a further hypothesis, not generation benefit.
Both arms worsening baseline must be disclosed even if paired comparison passes.

Zero current norm with nonzero native norm, undefined historical cosine, nonfinite
value, norm/engine mismatch or any assertion causes terminal failure with no
fallback or retry. Tiny nonzero dot signs are not counted without frozen tolerance.

One bounded child with original shared nonblocking EX lock inherited by worker,
CPU0 and six numerical thread variables1, observed one thread. Limits45CPU /
120wall /512MiB /4MiB per file. Whole lifetime wait4 includes literal helper tests,
imports/FIT validation/restores/numerics/output/exit. Expected counts: 12 restores,
720 forwards/objectives, 240 issued +240 text-component backwards, 240 native Adam
virtual transitions, 240 counterfactual generations. No sequential training or
persisted updates. Parent preparation/review/final tail remain unknown, not zero.
No retry, larger sample, source repair-and-rerun, reduced step or expanded limits.
