# Hepta: a four-stage marked-flow experiment

**Completed results:** [Chinese execution report](REPORT.md),
[main statistical summary](results/campaign002_analysis001/SUMMARY.md),
[long-distance and query-swap summary](results/EXTENDED_SUMMARY.md).
All 75 training/evaluation fits and 225 extension conditions completed. The
operator audit passes in its stated domain; this candidate did not establish
reliable content binding or a quality/cost advantage. Full raw evidence and
checkpoints are published in [verified archive parts](artifacts/README.md).

This additive research experiment starts from public baseline
`1dc975504276d9f7af3b28f0f7b1c2a79ef66d8d`. It does not modify the inherited
`hcsn_distributional_v2` implementation or import uncommitted results from other
concurrent research work. The first operator freeze was committed as
`1349bb1bfec5c9fe5f165e1efcf2be4b479c945e` before the formal numerical run.

The research question is whether a consistent threshold, first-event, survival,
reset and content propagation model contributes useful neural computation.
Correct numerical operators, learning capability and deployment advantage are
separate claims. This directory reports each separately.

## Mathematical object

The inherited model is a finite continuous-time Markov chain (CTMC) with a
reflecting lower edge, an upper firing boundary and an Erlang refractory chain.
It is a declared finite approximation, not the exact He-Xiong financial model.

With row probabilities `p`, let `Q` be its conservative generator and `R` its
event-mark matrix. `R` includes a firing event that resets to the very same state,
even though that event cancels from the net movement generator. Then:

\[
Q_0=Q-R,\quad P_t=e^{Qt},\quad K_t=e^{Q_0t},\quad \lambda=R\mathbf1.
\]

- Current physical state is `p P_t`, with total probability one.
- No-next-event probability is `p K_t 1`, including recovery when the initial
  state is refractory. It is not current active occupancy.
- Probability of at least one event is `1-p K_t 1`.
- Expected repeated-event count is
  `p integral_0^t exp(Qs) lambda ds`; it can exceed one.
- Local discounted event value is `(rho I-Q)^-1 g`, and the discounted next-event
  transform is `(rho I-Q0)^-1 lambda`. These are fixed-policy local quantities,
  not trained task-optimal Bellman values.

For content `h`, retain the state-conditioned first moment
`M_i = E[h 1{X=i}]`. Multiplying content by `eta` at each firing and applying
continuous decay `gamma` gives

\[
A_\eta=Q-(1-\eta)R-\gamma I,
\qquad M(t)=e^{A_\eta^\top t}M(0).
\]

The corresponding kernel is the marked event-count probability generating
function. At `eta=0` it reduces to the killed kernel; at `eta=1` and `gamma=0`
it reduces to full propagation. Its derivative at `eta=1`, applied to the
ones vector, gives expected event count. This is a genuine same-process
connection between the event mechanism and the content memory.

The neural memory is a probability vector plus content first moments. It is
not the complete joint distribution of physical state and arbitrary content.
Nonlinear encoding and reading define a new neural architecture, rather than
an exact nonlinear Bayesian filter.

## Observation and time semantics

Each supplied `dt` elapses before its observation. The model:

1. Propagates using the generator chosen at the last observed input.
2. Reads existing memory with the current input/query.
3. If observed, changes its bounded threshold, applies physical remapping and
   the matching event-weighted content remap, then writes the new content.
4. If missing, preserves the prior policy and performs no observation write.

Splitting an interval inserts a propagation-only step; it does not duplicate
an observation. A real zero observation is distinct from no observation.
Transformer placeholders are masked as attention keys/values and do not
increment observation position. Its two causal attention layers permit the
two-hop mapping in the bridge-binding task.

The flow candidate uses 4 active cells plus 1 refractory phase and 24 content
features per state. It learns bounded input-dependent threshold and drift,
plus global noise, refractory mean and event retention parameters. The two
same-process value features enter the readout. They have not been separately
validated as restoring and regenerative force channels, and the threshold is
not a proved smooth-pasting optimum of the He-Xiong stopping problem.

## Four stages

| Stage | Evidence | Scope |
|---|---|---|
| Operators | Independent SciPy exponentials, quadrature, solves and Frechet derivatives; marked count law; limits and remaps | Finite CTMC and its declared refractory law |
| Continuous dynamics | Partial observations of a controlled relaxation process; irregular clocks, split intervals, missing observations, post-jump recovery | Small supervised dynamics task |
| Content | All four queries in MQAR, selective overwrite, episode-specific A/B bridge binding; silent delay and missing-target strata | Symbolic memory, not language modeling |
| AV/text | Actor-disjoint CREMA-D audio/video plus actual transcript tokens, weighted sentence consistency, missing-modality sensitivities | Two-sentence fixed-frontend experiment, not a foundation model |

All five arms receive the same model-visible inputs and the same per-step
training episodes. The arms are marked flow, diagonal-decay content memory,
time-aware GRU, surrogate-gradient LIF and a two-layer causal SDPA Transformer.
They have different parameter counts and state costs; these are measured and
reported. Equal training steps do not imply equal compute or equal optimal
tuning effort.

The two-sentence AV/text design has exact weighted Bayes ceilings of 1/2 for
any single modality, 5/6 for any two, and 1 for all three. Accuracy above chance
alone cannot establish tri-modal binding. The acted data and tiny vocabulary
also cannot support open-domain multimodal scaling claims.

## Evidence discipline

- Source hashes and fixed training specifications are recorded before formal
  fits. Checkpoints are frozen before confirmation evaluation.
- Every fit uses the final fixed-budget checkpoint. No early stopping, seed
  selection or test-based hyperparameter selection is used.
- Evaluation retains per-episode logits, targets, weights and actor clusters.
  The availability of a deleted target is evaluation metadata only.
- Numerical development runs, superseded specifications, failed attempts and
  formal runs remain distinguishable in the evidence.
- Feature preparation, training, evaluation and shared-host CPU timing have
  separate receipts. Internal timing and enclosing process receipts must not
  be added together.
- No GPU, energy or foundation-model result is inferred from CPU seconds.
  Dense matrix exponentials are a differentiable reference implementation;
  their performance is not the performance of a future optimized kernel.

## Files

`marked_flow.py` defines the operators; `operator_audit.py` checks them;
`models.py` connects them to trainable content; `model_checks.py` checks causal
time semantics; `synthetic_data.py` and `dynamic_data.py` define the synthetic
tasks; `av_data.py` and `AV_PROTOCOL.md` define the real-data input contract;
`runner.py` controls the frozen training/evaluation study. The final report
and machine-readable summary are generated from retained raw outputs.
