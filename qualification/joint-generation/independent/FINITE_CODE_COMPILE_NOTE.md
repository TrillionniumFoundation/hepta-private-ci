# Candidate only: finite content feedback versus a compiled joint decoder

No new TRAIN probe, fit, model or formal evaluation is authorized or executed by
this note. Finish the current-weight H3 evidence first. Existing r2/CORE/D1/H2
failures remain unchanged. A different task/model with richer conditional
information would be an explicit new proposal, never a repair of old r2 results.

## Why a strong static comparator is necessary

The original [Adaptive Second-Order Solvers paper](https://arxiv.org/html/2610.03034v1)
constructs static schedules from adaptive trajectories. Its abstract reports
problem-dependent adaptivity: strong toy gains but marginal gains on image and
language tasks, with averaged schedules sometimes better. Its comparisons use
network-evaluation budgets and quality metrics, not this prototype's complete
training/search/critic/serialization CPU budget. This supports testing a learned
strong static alternative; it supplies no Hepta advantage or impossibility claim.

[Iterative Refinement Improves Compositional Image Generation](https://arxiv.org/html/2601.15286v1)
studies generator/critic/editor/verifier feedback and reports improvements over
parallel sampling. It motivates studying distinct legal content edits and their
conditional value. It does not establish complete lifecycle budget superiority
for this finite twelve-code prototype. A private ground-truth observer must not
become a free inference-time feedback feature.

## Distribution that must actually be scored

The current prototype samples independent heads: for a fixed input x, a draft
pair y=(i,j) has probability p_i(x)q_j(x), over 144 pairs. For a legal feedback
map or stochastic kernel T_x(z|y), the terminal **joint** law is

    pi_x(z) = sum_{i,j} T_x(z | i,j) p_i(x) q_j(x).

A deterministic code-pair edit is the special case T in {0,1}. Enumerating the
144 drafts and pushing their probabilities through the same map gives the same
terminal joint content law as sampling a draft and applying that map. Equality
of terminal laws implies equality of expected raw utility and fixed-rho
entropic content utility, under the same reward and observation semantics:

    E[R] = sum_z pi_x(z) R(z)
    U_rho = -log(sum_z pi_x(z) exp(-rho R(z))) / rho.

This mathematical content equality does not prove equal CPU cost or that a
compiled path is faster. It also does not turn an external decoder observation
into legal deployment feedback. Image code IDs are learned decoder inputs,
not independently verified pixel-semantic labels.

Feedback generally correlates the two codes. Multiplying terminal marginals
and applying the old independent-head utility formula would score a different
law. Likewise, applying an edit to the original separately greedy draft and
finding joint MAP of the pushed distribution are different decision rules.
Keep the original primary greedy definition and decoder/scorer meaning; any
joint-MAP statistic must be separately named, predeclared and report-only.

## Exact applicability and actual costs

A fixed table over 144 drafts applies only if feedback depends on that finite
state and a fixed, declared finite context (for example a particular legal
instruction). If it also uses input-conditioned probabilities, hidden states,
fresh model calls or continuous image features, compiling it may require
input-specific computation or a larger state; a global 144-entry map is not
automatically equivalent. New randomness or a sequence of actions needs its
full transition kernel and terminal law, with all intermediate information
sources declared. No external label or unavailable observation is permitted.

A future fixed TRAIN probe would compare the feedback implementation with its
exactly equivalent compiled terminal law, the original independent decoder and
an effective static NDU alternative. Charge table/kernel construction, any
context evaluation, decoder/observer/critic training and selection, storage,
normalization, sampling and actual output encoding to their real boundaries.
Give every comparator the same applicable optimization. Preserve byte/risk/law
checks and all seed/source outcomes. Then distinguish improved joint content
coupling from any additional value of sequential adaptive computation.

This remains a candidate. The concurrent content group's reported actual small
refiner had little action headroom and a negative comparison; a handmade example
cannot replace its real candidate evidence. Do not enlarge that refiner or
invent a favorable dataset to call the old task solved.
