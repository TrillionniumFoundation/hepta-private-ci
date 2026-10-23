# Hepta NDU-OOP v4: dynamic four-output allocation (finite mechanism)

**Status: DRAFT / RESEARCH_ONLY / DENY_ALL / HOLD_NO_GO.**
Parent: [v3 feedback generation](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3370).
This additive experiment changes **none** of v1/v1.1/v2/v3 source or sealed confirmation results.

## Precisely what is implemented

A budgeted finite **output portfolio** chooses a different information/refinement
action after receiving real (synthetic) feedback. Its actions are:
\`text\`, \`audio\`, \`image\`, \`video\`, \`witness\` and \`emit\`.
The first four are **symbolic feedback probes**, not natural-media decoders.
The witness observes a latent common-corruption indicator with a declared error
channel, rather than consulting hidden truth. All four final symbolic outputs
must be emitted, with four units reserved before every optional action.

- Input is four public binary reports.
- The hidden evaluation state contains four ground-truth bits and one common
  corruption switch (32 possible states). Per-channel observation errors depend
  on this shared switch, so posteriors are **not** the product of marginals.
- Every action has an explicit discrete cost and two possible observations.
  Once selected, its result changes the public state and the next portfolio
  action; repeated probes and an impossible terminal budget fail closed.
- The controller maximizes a time-consistent finite entropic certainty
  equivalent of external four-channel loss minus declared symbolic resource
  charges. An exact finite Bellman search is valid **only for this finite
  declared action/signal model**. A hard planning-state cap rejects rather
  than silently substituting a fabricated optimum.
- The strong static comparator selects the best fixed sequence using the
  same reports, full joint model, risk profile, and budget, with terminal
  outputs allowed to respond to observed information. A myopic comparator
  re-optimizes only a single action lookahead.
- The evaluator independently enumerates truth, common corruption, all public
  reports, stochastic intermediate signals, actual emitted symbols and charged
  costs; truth never enters the runtime policy.
- \`factorial.py\` separately validates four **executed** paired
  training × inference arms and re-scores raw outputs using independent truth,
  rejecting changed labels, missing arms, duplicate worlds, proxy-cost units
  or fabricated metrics. No neural training is run by this module.

It is **not** an implementation of continuous Merton feedback or a general
controlled FBSDE. The optimization is over discrete information/refinement
actions and the four symbolic terminal output bits, not neural decoder logits
or weights.

## Executed local evidence (2026-10-23, Python standard library)

\`\`\`bash
python -m unittest discover -s experiments/multimodal_output_portfolio/v4 -p 'test_*.py' -v
python experiments/multimodal_output_portfolio/v4/run_experiment.py
\`\`\`

12 unit/adversarial tests passed locally. The saved
\`evidence-development.json\` contains complete exact enumeration, not a
randomized holdout or physical resource measurement.

| Fixed model, budget 6 | Mean external loss ↓ | CVaR90 external loss ↓ | Mean declared symbolic cost |
|---|---:|---:|---:|
| Nominal / dynamic | 0.141326 | 0.612170 | 6 |
| Nominal / optimized static | 0.155631 | **0.606282** | 6 |
| Nominal / myopic | 0.194000 | 0.696816 | 6 |
| Common-corruption shift / dynamic | 0.169709 | 0.655022 | 6 |
| Common-corruption shift / static | 0.177511 | **0.639185** | 6 |
| Common-corruption shift / myopic | 0.194000 | 0.696816 | 6 |

**Interpretation:** under this declared small model, dynamic allocation improves
mean error over strong fixed sequencing, but **worsens CVaR90 relative to static**
at both tested regimes. This is a genuine tradeoff, not a risk-frontier claim.
The confirmation gates for P2–P5 are therefore **not passed**.

The budget-6 dynamic planner visits 560 states over all 16 root public reports.
For root reports (0,0,0,0), it first probes video; feedback 0 leads to
\`image\` and feedback 1 to \`text\`. This verifies actual feedback-dependent
portfolio reallocation at the **symbolic mechanism** level.

## Scientific gates and strict nonclaims

1. **Utility identifiability.** The true terminal loss is a fixed four-channel
   Hamming metric. A forged internal score is rejected when externally checked.
   No real preference data or utility-scale identification is implied.
2. **Correlated errors.** The full common-cause posterior is used, a factorized
   comparison is adversarially tested, and a predeclared changed common-cause
   law is independently evaluated. Robustness outside the model is absent.
3. **Dynamic control.** The policy really switches next modality based on
   observed feedback. This does not establish improvements to real
   text/audio/image/video generation or a general deep continuation benefit.
4. **Solver cost.** Exact enumeration is feasible on the finite model; the
   state cap prevents unbounded planning. This is not high-dimensional MPC,
   learned Riccati or native inference latency qualification.
5. **Credit allocation.** A strict 2×2 paired outcome auditing contract exists,
   but no true baseline/NDU generator fine-tuning comparison has run here.
   A descriptive difference-in-differences is not a causal identification
   theorem without a frozen design and source-independent outcomes.

For real P2–P5 closure, bind this action/receipt protocol to a legitimately
loaded pretrained four-output generator, make the **actual generated outputs**
and physical costs independently measurable, run 2×2 learned-training ×
learned-inference controls with new untouched source-group heldout and paired
randomness, and validate real audio/video continuity, calibration, robustness,
and production runtime authority. Do not rewrite the earlier negative pilots.

## Safety / ownership

No repository main-branch updates, selected artifacts, production dispatch
changes, model promotions, new grants or external effects are authorized.
The code does not consume model checkpoints or emit natural media.
\`BLOCKER_LEDGER.json\` names what is complete and what remains open.
