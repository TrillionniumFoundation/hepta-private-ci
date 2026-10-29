# RR-SNN V4: identified delivery, fair controls, and native integration evidence

This package is a separate, frozen research experiment. It preserves the V2 and
V3 negative results. It does not change their task definitions or promote a
synthetic query into a real production future window.

## Why V4 exists

The V3 diagnostic reward could be maximized by avoiding ordinary pulses. V4
therefore gives utility only to identified information that is actually emitted,
delivered after a delay, and requested by an independent terminal query. The
task specification is in `TASK.md`; exact finite-task oracle and transition code
are in `task.py`.

The primary comparison is fixed in advance: `rr_full` versus
`ctrnn_state_cpu`. The secondary baseline is selected only by five-seed mean
validation NLL from a fixed list. Heldout utility does not choose the comparator,
checkpoint, architecture, training budget, or reporting subset.

## Model and analytical scope

The candidate uses a finite continuous-time Markov chain with 16 active states,
two Erlang refractory phases, a reflecting lower boundary, reset interpolation,
and actual marked threshold events. Its segment propagation is `p exp(Q dt)`.
Uniformization independently checks that finite-state propagator. Gillespie
sampling generates complete marked jump paths and censored holding intervals.
These statements are exact for the declared finite chain up to numerical
evaluation. They do not assert an exact continuous-diffusion or whole-network
solution.

The restricted scalar threshold primitive has

\[
\gamma=\frac{\sqrt{\mu^2+2\rho\sigma^2}-\mu}{\sigma^2},\qquad
h=c+\frac{1+W_0(-e^{-\rho r-1-\gamma c})}{\gamma}.
\]

The independent numerical control solves

\[
\gamma(h-c)-1+e^{-\rho r-\gamma h}=0
\]

inside the declared bracket. `numerical_control.py` uses identical frozen
weights, scenarios and initial random states for this comparison. Any subsequent
trajectory divergence is retained, including changes in random-number
consumption. Diagnostic instrumentation costs are not kernel throughput.

Resource and maturity pressure enter this scalar primitive through an explicitly
specified heuristic cost map. It is not the solution of the complete resource
and maturity optimal-control problem. Network controls are refreshed at public
observation events and held between them; actual internal pulses update the
trace in continuous time. The fully asynchronous V3 network is a distinct prior
experiment. This V4 model does not silently inherit a proof for arbitrary
asynchronous recurrent feedback.

## Fair comparison

All policies receive the same 22 raw features and the same 81-action feasibility
mask. Each has 977 registered trainable coefficients. Parameters with actual
nonzero gradient support are reported separately. The task ledger charges one
unit for a renewal and one for an identified communication output, uniformly
across architectures. Internal spikes and continuous-state updates have measured
computational costs; no artificial equivalence between their energy costs is
assumed.

| Family | Main readout | Numeric state per policy |
| --- | --- | ---: |
| RR and mechanism ablations | Actual pulse trace | 309 bytes |
| LIF | Actual pulse trace | 132 bytes |
| Continuous-threshold ALIF | Actual pulse trace | 164 bytes |
| Resource-LIF | Actual pulse trace | 164 bytes |
| One-mode CT-RNN | Continuous memory | 68 bytes |
| Eight-mode CT-RNN state control | Continuous memory | 292 bytes |
| Twenty-mode upper-state CT-RNN | Continuous memory | 676 bytes |

These byte counts describe allocated numeric state, including the declared
clocks, rather than Python process RSS. Shared weights, RNG object storage,
global constant buffers, task ledgers, queues and interpreter allocations are
separate. The upper-state comparator intentionally has a larger state budget.
Analog ALIF/CT-RNN readouts are explicit additional controls. CT-RNN is the
implemented continuous-time comparator; it is not advertised as the published
CfC architecture or an exact reproduction of all LSNN training procedures.

## Training and inference

Training is oracle optimal-action-set imitation on teacher-forced demonstration
states. The per-decision loss is the feasible-action log-sum-exp minus the
optimal-action log-sum-exp. Checkpoints minimize validation loss, including the
initial model. Heldout delivered utility is measured in a separate closed loop.

RR uses the direct loss derivative plus a complete-path score term. The path
score includes the initial discrete draw, every `N_ij log q_ij` term, censored
dwell-time exit penalties, and observation remaps. Causal return-to-go costs and
a leave-other-sequence-out baseline are used. Spiking baseline training uses
explicitly biased event-count surrogate gradients; event forward trajectories
are still real threshold events. No claim of an exact count derivative is made.

The frozen matrix has fourteen fixed-budget variants times five seeds, plus two
CPU-matched CT-RNN controls per seed: 80 fits. Each fixed fit uses 16 epochs and
128 updates. CPU controls stop at a complete epoch after reaching their paired
RR process-CPU budget and report overshoot. Initial construction/validation and
final serialization have explicit timer exclusions in each training receipt.

## Evidence order and reproducibility

1. `pre_data_freeze.json` binds source identities, generator seeds, task,
   training choices and statistics before production data generation.
2. `data/manifest.json` binds every generated split.
3. `experiment_protocol.json` additionally binds actual training/validation
   bytes and the full trainer identities before fitting.
4. `selection.json` is created only after all 80 fits and before heldout
   evaluation; it binds every checkpoint and training receipt.
5. The coordinator publishes the selection in an immutable Git commit and
   compares the exact remote bytes. `selection_publication.json` records that
   check; the local runner verifies the receipt against the local selection.
6. `execution_controls_freeze.json` binds the additional evaluation,
   numerical-control and policy-measurement scripts before heldout execution.

The executed Python environment is Python 3.12.14, NumPy 2.3.5, SciPy 1.17.0,
and PyTorch 2.7.1+cpu on a shared Linux CPU environment. It is not verified dot.
Repository entrypoints use `PYTHONPATH=research python -m rrsnn_v4.<module>`.
The raw evidence archive supplies generated data, fitted checkpoints and
unabridged run records separately from the Git-backed source.

For an exact evidence replay, restore the archived data and result paths beneath
`research/rrsnn_v4`, verify hashes, then run the selection and aggregation checks.
For an independent refit, use a clean separate checkout, restore only the frozen
data, and run `train_matrix --workers 2 --cpus 0,1`. Do not overwrite published
evidence. Equal-CPU controls can run different epoch counts on different
hardware; they are not a bitwise training-time reproducibility claim.

The first attempted launch stopped before any model update because free disk
fell below the 200 MiB guard. Its original execution receipt is retained in
`execution_attempts`. Only identified reproducible caches and fully summarized
temporary scale stores were reclaimed; the same frozen protocol was retried.

## Statistics and resource interpretation

The main statistic averages four latent paths within each seed/scenario, then
uses 10,000 paired crossed training-seed and scenario/group bootstrap draws.
All A0/A2/B0/B2 counterfactual conditions remain together. Negative-transfer
indicators are formed before path averaging. Four observer query draws are
nested and reported separately from expected utility. Intervals are pointwise,
conditional on the recorded paths/queries, and five seeds limit inference about
training variability. A realized query reward can exceed the expected oracle;
the expected oracle is not a pathwise upper bound on a realized outcome.

`policy_benchmark.py` executes 64/256/1024/4096 independent policy states sharing
weights in a batch, for all four declared policies and all five seeds. It
reports model-step and full task-loop timers separately. Each condition has two
warmups and five measured episodes; p95/p99 are descriptive empirical quantiles
and do not establish an SLA. These instances are not Cells.

The native owner experiments in `hepta/` execute official upstream runtime,
journal and witness components, with actual durable storage and crash recovery.
Their fixed-projection measurements are separate from the learned RR policy
measurements. The original first-publication recovery failure and the invalid
memory-pressure 4096 measurement are preserved. See that directory's README
and independent repair review for the conditional trust contract.

Real production owner lifecycle evidence, a protected current initialization
frontier, a real independent future query window, actual full Cell workloads,
and dot identity remain independent qualification requirements. Research
execution does not grant production authority or activate a deployment.

## Primary references

- Zhiguo He and Wei Xiong, *Rollover Risk and Credit Risk*, Journal of Finance
  67(2), 2012: https://www.princeton.edu/~wxiong/papers/rollover.pdf
- Guillaume Bellec et al., *Long short-term memory and learning-to-learn in
  networks of spiking neurons*, 2018: https://arxiv.org/abs/1803.09574
- Ramin Hasani et al., *Closed-form Continuous-time Neural Models*, 2022:
  https://arxiv.org/abs/2106.13898
- Angela J. Yu, *Optimal Change-Detection and Spiking Neurons*, NIPS 2006:
  https://proceedings.neurips.cc/paper/2006/hash/5f268dfb0fbef44de0f668a022707b86-Abstract.html
- Wilhelm Braun, Paul C. Matthews and Ruediger Thul, *First-passage times in
  integrate-and-fire neurons with stochastic thresholds*, Physical Review E,
  2015: https://doi.org/10.1103/PhysRevE.91.052701

The transferable financial idea is the interaction between maturity structure,
renewal costs and an endogenous stopping boundary. This package does not infer
biological validation or scientific novelty from a naming analogy.
Optimal stopping/change detection and first-passage constructions already have
substantial neural-model precedents. A novelty claim would have to identify and
validate the specific maturity/resource coupling beyond those precedents.
