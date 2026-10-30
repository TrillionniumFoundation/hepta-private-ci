# Regenerative value operators and sampled multilayer neurons

This continuation of `experiments/first_passage_cell` implements a value-learning
layer on the augmented active/refractory state, a sampled two-hidden-layer
spiking network, and a globally verified scalar natural-spike free boundary.
The original study is anchored at commit
`2abafe82a99d6def2132e605e57af183e3080194`.

## Review order

1. `operators.py`, `markov.py`, `free_boundary.py` and `NUMERICAL_CONTRACT.md`:
   regenerative propagation, positive transition bins and the scalar verifier.
2. `network.py`, `tasks.py`, `train_network.py`, `NETWORK_PROTOCOL.json`:
   exact segmented hard-spike forward propagation and disclosed surrogate training.
3. `value_learning.py`, `bellman.py`, `ndu_value.py`, `VALUE_PROTOCOL.json`:
   a trained transition/value operator, finite-horizon continuation and actual
   native utility receipts.
4. `SOURCE_FREEZE.json`, numerical receipts, training evidence and confirmation
   reports: immutable hypotheses, source/model identities, retained failures,
   independent references and actual task outcomes.

## State and operator

The state space contains active distance x>=0 and a separate refractory state
with remaining duration eta in (0,a]. A natural hit resets to distance r and
starts the full refractory duration a. A segment consumes any pending eta before
active evolution. Missing observation does not manufacture survival evidence;
the original known-state/observation contract remains in the preceding study.

The active generator is mu*d/dx + sigma^2/2*d^2/dx^2. Refractory evolution has
generator -d/deta. Terminal payoffs can distinguish the phases, so regularity
claims across the reset/release junction require explicit domain conditions.

The strong Markov identity at reset level gives the exact finite renewal term

    integral f_d(s) K_(t-s)(r,dy) ds
      = K_t(d+r,dy) - 1[y>r] K_t(d,d(y-r)).

Consequently terminal exponential moments and transition-bin probabilities use
finite analytic sums. Event counts and discounted occupation use F, H and its
discount derivative. Stable tilted-tail interval evaluation is required for
large refractory payoff decay; underflow terms are removed only under an
explicit representability bound. Earlier quadrature failures and failed
reference refinements are preserved in the evidence.

The neural value layer is linear in the supplied payoff coefficients. Its
transition head is positive and has unit mass. A one-step Bellman backup is
monotone and nonexpansive; multiplying continuation by exp(-q*dt) makes it a
contraction for q>0. The registered maintenance task uses q=0 and finite backward
induction. Learned transition error and the piecewise constant state projection
are measured separately from the exact continuous propagator.

## Natural firing boundary

`free_boundary.py` solves a declared scalar recurrent-spike objective: Brownian
voltage, spike reward voltage minus cost, reset r, mandatory refractory a and
positive discount q. For c>=r, the threshold b is the unique root

    lambda*(b-c) - 1 + exp(-q*a-lambda*(b-r)) = 0,
    lambda = (sqrt(mu^2+2*q*sigma^2)-mu)/sigma^2.

Value matching, smooth fit, the continuation generator equation, the stopping
inequality and discounted transversality verify global optimality for that
objective. Implicit derivatives and independent finite-difference policy
iteration are retained. This scalar result does not establish a global optimizer
for a coupled multilayer network or for arbitrary task rewards.

## Multilayer training and comparison

The network has two hidden spiking layers, three units per layer, one-segment
communication delay and an eight-segment input clock. Each segment has constant
drive. Within it, first passages, surviving endpoints, multiple resets and
remaining refractory time are sampled from the continuous law. Synaptic traces
carry emitted spike counts to the next layer; the readout receives the second
layer's trace.

Backward propagation uses explicitly biased straight-through derivatives of
conditional moments. Local moment derivative checks do not turn that surrogate
into an exact gradient of expected classification loss. Fixed diagnostics compare
it with finite perturbations of actual sampled loss and retain Monte Carlo
uncertainty.

The registered comparison uses three temporal tasks, three training seeds and
three architectures with55 active parameters each: the first-passage network,
a LIF surrogate network and a leaky tanh recurrent network. Train, development
and confirmation identities are separate. The delayed-query transmission repair
was made before confirmation; completed aborted fits and their compute remain
retained. Every planned result, including failed advantage gates, is reported.

## Value learning and NDU

A neural trunk learns20 active/refractory transition-bin probabilities together
with payoff and occupation moments. Three10,716-parameter fits use4096 training
contexts and512 development contexts. The terminal bin basis includes an
infinite tail. Deterministic holding, release and initial boundary atoms remain
explicit exact branches.

The control study compares learned-operator Bellman continuation, analytic-
operator Bellman continuation and the prior wait-after-current forecast across
three declared physical laws. All arms receive the same dynamics, state, price,
deadline, legal actions and actual cost ledger. These comparisons isolate
operator/planning approximation; they do not test identification of hidden laws.

`ndu_value.py` binds the new objective/plan envelope while invoking the original
native scalar additive signed-Q32 owner. It verifies every receipt and actual
return. The task still maximizes the same scalar net utility; the native Pareto
advisory is retained separately. Native authority remains DENY_ALL and the
receipts do not provide production safety certificates.

## Reproduction

Use Python3.12 and install `requirements.txt`. Restore the preceding study's
retained native executable following its README. From repository root:

```bash
python -m unittest discover -s experiments/first_passage_operator/tests -v
python -m experiments.first_passage_operator.validate_operators
python -m experiments.first_passage_operator.validate_operators_domain
python -m experiments.first_passage_operator.value_learning prepare
python -m experiments.first_passage_operator.value_learning train
python -m experiments.first_passage_operator.train_network develop
python -m experiments.first_passage_operator.train_network freeze
```

Confirmation requires the published source/model freeze. Existing confirmation
outputs must be retained; use a separate reviewed protocol for a new study.

```bash
python -m experiments.first_passage_operator.value_learning confirm --freeze experiments/first_passage_operator/SOURCE_FREEZE.json
python -m experiments.first_passage_operator.train_network confirm
python -m experiments.first_passage_operator.bellman --freeze experiments/first_passage_operator/SOURCE_FREEZE.json
```

## Sources and theoretical relation

- He and Xiong, *Rollover Risk and Credit Risk* (2012):
  https://www.princeton.edu/~wxiong/papers/rollover.pdf
- Qi, *Deep Q-Learning on Holder Spaces*, arXiv2606.16846v1:
  https://arxiv.org/html/2606.16846v1
- Neftci, Mostafa and Zenke, *Surrogate Gradient Learning in Spiking Neural
  Networks*, arXiv1901.09948: https://arxiv.org/abs/1901.09948

The transfer from He-Xiong is killed diffusion, Feynman-Kac valuation and
endogenous boundary verification. The connection to Qi is a positive Bellman
operator and function-to-value learning. Uniform ellipticity is absent during
refractory holding, and reset conditions are nonlocal; Qi's whole-domain Holder
regularity and practical sampled-learning convergence are not imported as an
unproved theorem for this hybrid system.
