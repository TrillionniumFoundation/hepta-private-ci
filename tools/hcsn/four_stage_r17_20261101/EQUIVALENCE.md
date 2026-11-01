# What the finite HX comparison can establish

This note concerns the forty-state, four-content law in R15/R16. It does not
claim an equivalence for every continuous He–Xiong model, learning algorithm,
network architecture or physical implementation. The controlling inherited
source is R16 commit `0fd894118c47f38c2acf2532b8242fd16df76c47`, extending R15
`74144a3f5d5c77c953ecdc4708d3d90b56b67d3c`.

## Proposition: ordinary finite HMM realization

Fix a finite row generator Q, initial conditional probabilities, emissions E
for each available observation quality, public WRITE maps, reward vectors,
action durations and prices. Fix the controller horizon, projection schedule
and deterministic tie rule. Consider an HX-labeled implementation and an
ordinary continuous-time finite HMM with these same quantities.

For every public history with positive likelihood in the shared model, their
filters agree. If both use the common finite action-tree controller, their
action values, chosen actions and submitted answers agree. On a shared owner
world and keyed observation tape, the complete executed action/observation
trace, reward, fees and utility agree.

This is an exact-arithmetic claim. Distinct numerical algorithms require
separate checks, particularly at ties; the proposition is not a license to
change the frozen tie rule or to treat differing discrete actions as equal
within a numerical tolerance.

### Proof for full state

The transition kernel is P(t) = exp(t Q) in both models. A row probability p
therefore advances to p P(t). On observation y of quality e, with likelihood
L = p P(t) E_e(:, y) > 0, both produce

\[
\mathcal B_{t,e,y}(p)
= \frac{(pP(t))\odot E_e(:,y)}{L}.
\]

The initial conditional probability and each deterministic public WRITE map
are shared. Induction over the public event/observation sequence establishes
filter equality. A zero-likelihood hypothetical branch contributes zero to
the Bellman expectation; it does not supply a legitimate executed posterior.
The implementation's shared fallback on such a hypothetical branch does not
alter this expectation.

For h remaining slots, STOP has value

\[
V_{\rm STOP}(p,h)=\max_c p P(h\Delta t)r_c.
\]

WAIT uses the same one-slot transition, continuation value and time charge.
READ and REFRESH use the same propagation, emission likelihoods, conditional
posteriors, remaining slots and charges. Induction from h = 0 therefore gives
the same value for every admissible action. Shared action and answer tie rules
select the same maximizers. This proves controller equality for the declared
three-slot current-query horizon, without assuming it is globally optimal over
all six queries.

Couple executions to the same owner world. Equal previous actions consume the
same duration and reveal the same keyed token. The next filters and actions
remain equal by the preceding induction. At the shared deadline, equal
answers receive the same target reward and have paid the same fees. Repeating
this argument across all queries proves trace and utility equality.

In the current task, REFRESH purchases a higher-quality observation and two
slots; it does not reset the hidden owner path. Its name does not introduce an
additional model-specific physical intervention.

### Event-anchored representation

For the anchored filter the effective state contains the eight masses z_k,
their per-address anchor times a_k, and the common clock t. Materialization is

\[
p_k(t)=z_k R\exp((t-a_k)Q).
\]

On an actual observation or public WRITE, both apply the same update and
collect with C; on unobserved time advance both change only t. Thus the same
induction applies to this age-dependent state, provided the ordinary reference
uses the same C, R and update schedule. This does not make R exp(tQ) C an
eight-state semigroup. Full and anchored representations are different
estimators and are not claimed equivalent to one another.

## Consequences for the existing comparisons

R15 `calibration.py` constructs `hmm_same_matrix` by deep-copying the fitted HX
payload. R16 `study.py` restores that payload through the same `BlockLaw` API
and uses the same controller. The reported complete-trace equality for this
reference is therefore the behavior predicted by the proposition. Additional
worlds cannot establish an HX-exclusive filtering or decision advantage over
this same-matrix implementation.

The validation-selected ordinary model is selected between `hmm_same_matrix`
and a separately fitted free-rate model by validation likelihood. When that
rule selects the different free-rate generator, D minus B need not be zero.
The proposition does not prohibit a benefit against this specified fitted
model or selection rule. Such a benefit must be measured and interpreted as a
property of fitting, structural priors, model selection or misspecification;
it is not evidence that ordinary finite HMMs cannot represent the deployed HX
filter.

Likewise, an exact computational factorization can save time without changing
the filter. If it depends only on matrix symmetry it is available to the
same-matrix ordinary model as well. Its benefit is a finite implementation
optimization, not an exclusive HX capability. Numeric state-array savings,
whole-process memory, CPU, GPU and measured energy remain separate quantities.

## A differentiating claim that remains testable

A valid next hypothesis is that the financial parameterization is a useful
structural prior for learning dynamics from limited observations, or that a
continuous representation achieves a better measured approximation/cost tradeoff
than strong ordinary implementations. These are distinct hypotheses.

For a learning-prior claim, freeze disjoint generators, fitting budgets,
selection rules and data splits before opening outcomes. Give ordinary models
the same observations and structural information available to the candidate;
include free-rate and same-matrix deployment references. Preserve the original
D minus B gate: both domains mean gain at least .01, positive Student-t95 lower
bound and Holm-adjusted paired sign-flip p below .05. Report all fits and failed
candidates. Learning and policy-control effects should remain separated by the
full two-by-two comparison.

For a continuous approximation claim, specify the continuous target and its
error contract first, independently verify values, distributional successors
and derivatives, and then compare implementations at the same accepted error
and output quality. The finite same-Q equivalence does not settle this claim.
Neither claim supplies unmeasured GPU/energy results, open-domain cross-modal
binding or production ownership qualification.

This note closes the interpretation of one finite equivalence. Core utility,
cost and full-model adoption gates retain their existing empirical status.
