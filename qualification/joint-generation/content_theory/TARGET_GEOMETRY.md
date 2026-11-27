# Fixed native12 target geometry: an intrinsic difference, not a model win

Original sources: `content_joint/objectives.py` and `utility.py`. Constants stay
alpha=.2, rho=1.5. For native semantic code c, r_yc=R_y(c,c), with the original
learned decoder and actual decoded reward. The original two-modality average CE
equals −log s_y because both marginals are s. It is never doubled or divided
again. All old failures/10-second costs remain unchanged.

This analysis uses hand categorical laws and three saved decoder reward tables.
There is no neural/decoder forward, trained weight read, request, optimizer step,
sampler or image. Twelve geometry/source-equivalence tests passed, followed by
complete support checks. Research CPU before the main receipt was.572315 seconds;
the separate fixed-head upper-bound calculation used.057198 seconds. These are
independent research receipts, not added to or removed from old method budgets.

## One known label: same best output, different geometry

Write s=softmax(z), p=s_y, k_c=exp(−rho*r_yc), Z=sum_c s_c k_c,
t_c=s_c k_c/Z and rbar=sum_c s_c r_yc. Minimized per-example losses are

    L_A = −alpha log p − rbar
    L_N = −alpha log p + log Z/rho.

Their **logit** gradients, before division by batch size, are

    g_A,c = alpha(s_c−1[c=y]) − s_c(r_yc−rbar)
    g_N,c = alpha(s_c−1[c=y]) + (t_c−s_c)/rho.

The ambient **probability** derivatives are

    dL_A/ds_c = −alpha*1[c=y]/p − r_yc
    dL_N/ds_c = −alpha*1[c=y]/p + k_c/(rho*Z).

Moving mass from any wrong j to y gives respectively
−alpha/p−(r_yy−r_yj) and −alpha/p+(k_y−k_j)/(rho*Z). Both are strictly negative
when the decoded correct reward is highest. Thus both free-distribution optima
are the SAME delta_y. A finite softmax only approaches that boundary. No claim
that the original task's N optimum should be a wrong code follows.

The saved reward gaps r_yy−r_yj are.907929–.948633; wrong-code reward spread is
at most.040381, below alpha=.2. Consequently, for **every** interior s on this
support, both total logit gradients have a negative correct component and
positive wrong components. For a wrong j,

    g_A,j/s_j >= alpha−wrong_spread >0
    g_N,j/s_j >= alpha−(1−exp(−rho*wrong_spread))/rho >0.

All108 fixed hand target states (three probabilities ×12 labels ×three saved
supports) were also checked for A and N. This is a global sign certificate for
the given reward support, not an assertion about shared-encoder parameter signs
or generalization across different requests.

## N is not a uniform gradient multiplier

If every wrong reward is b and the correct reward is b+Delta, put
D=1−exp(−rho*Delta). Along the correct logit, keeping wrong-relative logits fixed:

    g_A,y = −(1−p)[alpha+Delta*p]
    g_N,y = −(1−p)[alpha+D*p/(rho*(1−D*p))].

For that equal-wrong case, per-example directions coincide but their scale is
confidence dependent. The utility-only N/A ratio is

    D / [rho*Delta*(1−D*p)].

For the fixed hand Delta=.9 it grows from.548711 at p→0 to2.116612 at p→1,
crossing one at p=.609225. With the CE anchor, both total correct-logit gradients
approach−alpha for p→0: N does not eliminate the corrective CE force. Across a
batch, state-dependent reweighting changes the summed parameter direction even
when each example's logit direction agrees. A single LR multiplier cannot in
general undo this mechanism. No LR/anchor/regularizer scan is suggested here.

## Curvature depends on coordinates

For a known label, probability Hessians are

    H_A,s = alpha*e_y e_y^T/p^2
    H_N,s = H_A,s − k k^T/(rho*Z^2).

So A is convex in free probabilities; N adds negative curvature, including along
wrong-only redistributions if their reward differs. But the actual optimizer
uses parameters/logits. Let S(v)=diag(v)−vv^T and a=s*(r_y−rbar). Then

    H_A,z = alpha*S(s) − diag(a) + a s^T + s a^T
    H_N,z = (alpha−1/rho)*S(s) + S(t)/rho.

Both can be nonconvex in logits: the hand known-label Delta=.9, p=.1 case has
negative correct-logit curvature for A AND N. It would be wrong to conclude
"A training is convex, only N is hard." The nonlinear shared encoder adds further
parameter geometry. A larger N norm alone does not identify optimization failure.

## Uncertain labels: genuinely different target distributions

Let eta_y be a specified conditional label law at one input. **No real eta(x)
has been estimated here.** It must not be replaced by the model's own confidence.
The original training source averages the per-label losses:

    L_A(s;eta)=−alpha*sum eta_y log s_y − v^T s, v_c=sum eta_y r_yc
    L_N(s;eta)=−alpha*sum eta_y log s_y + sum eta_y log Z_y/rho.

The label average stays OUTSIDE log. Pooling label/outcome risks inside one log
would define a different objective and erase the example below; it is not a
correction applied to the source or evaluator.

For strictly positive eta, A is strictly convex in probabilities. Its unique
optimum is

    s_c = alpha*eta_c/(lambda−v_c),
    sum alpha*eta_c/(lambda−v_c)=1, lambda>max v_c.

This equation, solved by a bounded scalar bisection, passes KKT checks. For N,

    g_N,z = alpha(s−eta) + (sum eta_y*t_y−s)/rho
    H_N,z = (alpha−1/rho)S(s) + sum eta_y*S(t_y)/rho
    H_N,s = alpha*diag(eta/s^2) − sum eta_y*k_y*k_y^T/(rho*Z_y^2).

An interior stationary distribution satisfies

    alpha*eta_c/s_c = alpha−1/rho + sum eta_y*k_yc/(rho*Z_y).

There is no general uniqueness claim. A sufficient logit-convexity condition is
alpha>=1/rho; the fixed alpha=.2 does not satisfy it. This is a mathematical
condition, **not** a proposal to change the anchor.

### An exact opposite-direction example

Use two equally probable true labels, correct reward1, wrong.1, and an output
law(p,1−p). Every p has expected joint success.5 and expected raw reward.55.
Put kappa=exp(−rho*Delta), w=p(1−p). Up to constants:

    L_A = −alpha*log(w)/2
    L_N = −alpha*log(w)/2 + log(kappa+(1−kappa)^2*w)/(2*rho).

A has the unique optimum p=.5. N's center curvature is

    L_N''(.5)=4[alpha−tanh(rho*Delta/2)^2/rho].

For alpha=.2, rho1.5, Delta=.9 it is−.122797 (A's is+.8). N instead has two
global minima **.281997 and.718003**. Their product is

    w* = alpha*rho*kappa / [(1−alpha*rho)*(1−kappa)^2].

At the SAME p=.51, A descent moves toward.5 while N descent moves away from.5.
This proves a target-level difference, not merely a bigger step. N reduces
within-generator reward randomness conditional on each true label while paying
more label CE; it need not improve semantic joint correctness. Treating its
output policy as a calibrated label posterior would be inappropriate here.

### Check against all retained decoder supports

For each seed11/23/47 and every unordered pair of12 labels, set the HAND
posterior eta=(.5,.5) on that pair. The equal mixture of those two outputs
strictly dominates every outside code in both row reward and negative-exponential
normalizer, and improves both target CE terms. Thus any outside mass can be
removed, so the global optimum is on the two-code face of the full12-code law.

All198 faces have two local N minima and a middle maximum; N's global optimum
differs from A's in every face. Every face gives opposite A/N directions at.51.
A optima stay between.499795 and.500204. N center curvatures range from−.197479
to−.135243. All roots/values and the dominance certificates are retained;
none was picked as a favorable subset. Fixed pair0/1, seed11, has N minima near
.234100/.765898 versus A≈.499999. Tiny decoder-reward asymmetries choose the
global branch differently across saved seeds in this constructed ambiguous case.

This does **not** prove real requests have this posterior, that the observed
N−A failure was caused by ambiguity, or that a different optimizer would help.
Known-label target optima are identical; finite optimization, shared-feature
approximation, sampling/generalization and the scoring objective's own policy
preference must remain separate explanations. All earlier TRAIN/formal failures
and unproven two-modality gains remain unchanged.

Evidence: [verification and every face](../runs/content-native-objective-theory-v1-20261023/verification.json),
[source-equivalence/finite-difference tests](test_geometry.py), and
[next-candidate limits](NEXT_CANDIDATE.md).
