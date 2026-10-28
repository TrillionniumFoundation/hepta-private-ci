# First-passage cell and native NDU research package

This package implements a trainable, one-dimensional stochastic event cell,
explicit renewal resets, and value-informed maintenance decisions. It is a
research package beside the existing Hepta neuron work. It does not replace the
production neuron, Agentd state backend, or native NDU owner algorithms.

All five research work packages have implemented and checked deliverables. The
registered endogenous renewal controller passed **all three prespecified
confirmation comparisons** using executed actions and actual subsequent net
utility. Independent audits covered **32,768 complete episodes** across
confirmation and both prespecified model-mismatch tasks, in addition to the
52,224 development episodes and all 16 physical-model fits.

The comparison concerns voluntary repair/reset boundaries in the registered
synthetic maintenance task. The learned physical first-passage barrier is a
separate object. See [RESULTS.md](RESULTS.md) for the complete findings, costs,
computational measurements and limits, and the
[audited confirmation figure](evidence/confirmation_results.svg).

Start with [CONTRACT.md](CONTRACT.md), [PROTOCOL.json](PROTOCOL.json), and the
[pre-confirmation protocol amendment](PROTOCOL_AMENDMENT.md). The repository base
is `ed6f8c6645c927249cec0d3395f6bae21f278739`.

## Five work packages

| Work package | Implemented surface | Evidence and scope |
| --- | --- | --- |
| First passage and reset contract | `cell.py`, `task.py`, `filtering.py`, `CONTRACT.md` | Explicit event times, censoring, missing observations, reset distance, refractory carry, remaining time, and versioned checkpoints |
| Analytic propagation | `kernels.py`, `validate_kernels.py` | First-hit probabilities, density, discounted hit weight, killed transition kernel, log values, analytic gradients, and independent numerical references |
| Trainable cell | `training.py`, `validate_training.py` | Joint input-weight, drift, diffusion, physical-boundary and reset-distance likelihood training; every common coefficient participates |
| Cost and deadline feedback | `value.py`, `study.py` | Fixed, learned constant-threshold, first-event value, and full-renewal value policies under one realized cost ledger |
| Hepta value interface | `ndu.py`, `native_bridge.rs`, `build_native.py` | Actual existing native recursive utility and V2 candidate evaluation; forecast, continuation and realized-value receipts |

The physical absorbing boundary and the voluntary repair boundary are different
objects. This distinction is essential to interpreting the last two packages.

## Completed frozen confirmation

The published [source commit](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/507bfcc131f30c88c5931f6101c45afdd5c71887)
precedes evaluation. The [published freeze commit](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/8ada7c46a23063722ee9b7089be608d4ab1c2fed)
contains [FREEZE.json](FREEZE.json), whose SHA-256 is
`57858ef88f9a1ef03a9ade666a35fdbe7faafef651bdca8eee3514feb99b7fdd`.
The frozen source identity remains
`507bfcc131f30c88c5931f6101c45afdd5c71887` when later results and raw artifact
parts are published. The freeze's `confirmation_started: false` records its
pre-run creation state; completed run receipts and audits record subsequent
execution without rewriting the freeze.

| Prespecified endogenous-minus-baseline comparison | Mean net utility gain | Family-adjusted empirical interval | Registered gate |
| --- | ---: | ---: | --- |
| First-event value | +0.03748856 | [0.02596592, 0.05046213] | PASS |
| Fixed cross7 | +0.02209145 | [0.00977929, 0.03466599] | PASS |
| Learned threshold7 | +0.02214138 | [0.00937348, 0.03518791] | PASS |

Every comparison has eight positive model-seed means and an adjusted lower
bound above the frozen 0.005 gate. These use the registered two-stage bootstrap
and Bonferroni family correction, not a population guarantee. Endogenous mean
confirmation utility is 0.82583441 task units per episode. The two stress tasks
retain a higher endogenous mean than these three baselines without introducing
new significance gates. Full evidence is in the
[confirmation audit](evidence/CONFIRMATION_AUDIT.json),
[drift stress audit](evidence/STRESS_DRIFT_AUDIT.json), and
[diffusion stress audit](evidence/STRESS_DIFFUSION_AUDIT.json).

## State, first passage, and analytic operators

The observed physical level is `Y`, the physical lower boundary is `B`, and the
active-state distance is `x = Y - B > 0`. During one constant-input segment,

$$
 dX_t=\mu\,dt+\sigma\,dW_t,\qquad
 \mu=\mu_0+w_1u_1+w_2u_2,\qquad \sigma>0.
$$

Inputs affect the drift. The current implementation does not add an unmodelled
instantaneous input jump. Let
$\tau=\inf\{t\geq0:X_t\leq0\}$, and let $\Phi$ be the standard normal CDF.
For $x,t>0$,

$$
 F(t;x,\mu,\sigma)=P_x(\tau\leq t)
 =\Phi\!\left(-\frac{x+\mu t}{\sigma\sqrt t}\right)
 +e^{-2\mu x/\sigma^2}
  \Phi\!\left(\frac{-x+\mu t}{\sigma\sqrt t}\right),
 \qquad S=1-F,
$$

$$
 f(t;x,\mu,\sigma)
 =\frac{x}{\sigma\sqrt{2\pi t^3}}
   \exp\!\left[-\frac{(x+\mu t)^2}{2\sigma^2t}\right].
$$

A terminal observation `X[t] <= 0` is not interchangeable with `tau <= t`:
an unconstrained path can cross the boundary and return before the deadline.
The event likelihood uses the first-passage law.

For discount $q\geq0$, set $\zeta=\sqrt{\mu^2+2q\sigma^2}$. The discounted
first-hit operator is

$$
\begin{aligned}
 H_q(t;x)&=E_x[e^{-q\tau}\mathbf1_{\{\tau\leq t\}}]\\
 &=e^{-(\mu+\zeta)x/\sigma^2}
   \Phi\!\left(\frac{\zeta t-x}{\sigma\sqrt t}\right)
 +e^{-(\mu-\zeta)x/\sigma^2}
   \Phi\!\left(-\frac{x+\zeta t}{\sigma\sqrt t}\right).
\end{aligned}
$$

Thus `H` at `discount = 0` equals `F`, and $e^{-qt}F\leq H_q\leq F$. For positive `q`, `H` is a
discounted event weight, not a probability or a confidence score. The maintenance
study uses the registered undiscounted native profile; the general `H_q` kernel
is independently validated but does not silently change that objective.

For $x,y,t>0$, the killed transition density can be written without subtracting
two ordinary Gaussian densities:

$$
 k_t(x,y)=\frac{e^{-(y-x-\mu t)^2/(2\sigma^2t)}}{\sigma\sqrt{2\pi t}}
          \left(1-e^{-2xy/(\sigma^2t)}\right),\qquad
 K_tg(x)=\int_0^\infty k_t(x,y)g(y)\,dy.
$$

Its mass is $K_t1=S(t;x)$, and for fixed coefficients
$K_sK_t=K_{s+t}$. A surviving terminal state has density `k_t / S`.

### Numerical and boundary contract

`first_passage(x, mu, sigma, horizon, discount=0)` returns `F`, `S`, `f`, `H`
and their `log_` counterparts. `first_passage_gradients` provides analytic
interior derivatives with respect to distance, drift, diffusion, horizon and
discount. `killed_density`, `killed_log_density`, `killed_gradients`, and
`killed_cdf` provide the transition interfaces.

At `x = 0`, the event is an atom at time zero: `F = H = 1`, `S = 0`. At `t = 0`
with positive `x`, `F = H = f = 0` and `S = 1`. An atom is not represented by an
ordinary finite density derivative. The zero-time transition is a Dirac mass;
the density interface requires positive time. Logs of mathematical zero are
negative infinity, while validation JSON is finite and standards-compliant.

The implementation uses stable log normal CDFs, complementary probabilities,
Mills ratios, a near-boundary survival expansion, and a log-domain killed gap.
It preserves representable gradients even when an ordinary probability or
kernel density underflows. Nonfinite inputs and unrepresentable intermediate
or derivative domains are rejected. The killed CDF has an explicitly documented
adaptive-integration fallback when Gaussian interval subtraction is ill
conditioned. Numerical verification covers declared finite test sets; it is
not a universal floating-point accuracy theorem.

## Observation, reset, and replay semantics

`filtering.py` propagates a positive finite-grid approximation with the killed
kernel. A confirmed survival observation normalizes its surviving mass. An
available Gaussian live-state sensor likelihood can then update that belief.
The grid projection and its tail collapse are disclosed; it is not an exact
Gaussian posterior or an exact continuous semigroup.

`MISSING` keeps both live mass and the absorbing event atom. It never fabricates
survival evidence. `OBSERVED_EVENT` means that the current absorbing cycle has
already ended by observation time, including any prior event atom. It is not
an exactly timed new crossing in the latest interval. A communication message
and the absence of a communication message are separate observation facts.

After every physical event, the cell records its actual event time, resets to
`B + reset_gap`, holds that level for the deterministic refractory period, and
continues for all remaining physical time. Repeated events within a control
interval are allowed. The positive refractory period provides a finite event
bound; unsupported segment/bound combinations are rejected before mutation.

The event sampler uses the defective inverse-Gaussian law, with an atom at
infinity for positive drift, and a stable rationalized sampling formula near
zero drift. Surviving endpoints use Brownian-bridge rejection or inversion of
the killed CDF. These implement the local diffusion law without an Euler time
step; special-function evaluation and numerical inversion still have finite
precision.

Cell and task checkpoints include model identity, physical state, time,
refractory remainder, event count and random-stream counters. Restoration
requires the externally selected model identity and cross-checks the random
stream seed against the scenario's declared noise seed, as well as task state,
event timing and the accumulated cost ledger. Repair, propagation and accounting
form one transaction. A failed
step cannot leave an uncharged repair behind. Exact replay means the same
checkpoint and future request sequence reproduce the same events, states and
rewards; it does not mean different time partitions use the same sampled path.

## Jointly trained parameters

The six common fitted coefficients are
`mu0`, `w1`, `w2`, `log_sigma`, `B`, and `log_reset_gap`. Positive diffusion and
reset distance use exponential parameterizations. The refractory duration is a
fixed registered task parameter, not a seventh learned physical coefficient.

Every trajectory starts at a measured absolute level. The initial distance is
`initial_level - B`; after a reset it is the fitted `reset_gap`. This physical
anchor separates the boundary from the reset parameter. For observed event
indicator $\delta_i$, the trajectory log likelihood contributes

$$
 \sum_i\{\delta_i\log f(t_i;x_i,\mu_i,\sigma)
       +(1-\delta_i)\log S(t_i;x_i,\mu_i,\sigma)\}.
$$

The objective is normalized by trajectory count. Repeated within-trajectory
intervals are not counted as independent experimental seeds. Analytic
chain-rule derivatives update all common coefficients with bounded L-BFGS-B.
Initial/final losses, gradients, parameter changes and optimization costs are
retained. The seven-parameter physical reference adds an active `u1*u2` drift
coefficient. Training is event-time likelihood training, not a claim of
pathwise backpropagation through hard spike times or a trained multilayer SNN.

## Renewal values, costs, and two different boundaries

Write reset distance as `d` and refractory duration as `a > 0`. While inputs and
coefficients remain fixed, the nth physical event time satisfies the law

$$
 T_n\overset{d}=\tau_{x+(n-1)d}+(n-1)a.
$$

First-passage times add over distance for the same drift and diffusion. Hence,
for a positive remaining horizon `T`,

$$
 E[N_T]=\sum_{n\geq1}
 F\bigl(T-(n-1)a;\,x+(n-1)d\bigr),
$$

where terms with negative available time vanish. Only finitely many terms can
contribute because `a > 0`. If $u_n=T-(n-1)a>0$ and $d_n=x+(n-1)d$, expected
active time is

$$
 E[A_T]=T-\sum_{n:u_n>0}
        \int_{\max(0,u_n-a)}^{u_n}F(s;d_n)\,ds.
$$

The integral is expected time lost to each post-event refractory interval.
`value.py` evaluates it by fixed Gaussian quadrature and checks it against an
independent inverse-Gaussian/Levy CDF plus adaptive quadrature. Omitted tiny
refractory contributions have a separately reported bound.

Under the registered task, the wait-plan utility is
`0.6 * expected_active_time - 0.5 * expected_failure_count`. `REPAIR` pays the
public repair fee once, spends its refractory time, and starts from the reset
distance. `WAIT` first spends any observed refractory remainder. `STOP` has
zero future utility and zero further elapsed time. The resource axis records
the fee without subtracting it a second time from utility.

The physical threshold `B` triggers a stochastic event and is jointly fitted
from event histories. The voluntary repair boundary chooses whether to reset
proactively given state, public price and remaining time. The endogenous arm
uses full-renewal action values plus one development-selected action-gap bias.
That bias changes selection only; it never changes task reward or NDU utility.

This is a value-informed repair/reset boundary prototype. It does not solve an
endogenous absorbing boundary from value matching and smooth pasting, and it
does not identify the fitted physical `B` with the voluntary repair gate.

All candidate forecasts assume `WAIT_AFTER_CURRENT`. Deployment is
`MPC_REPLAN_EACH_HALF`: it selects again every 0.5 time units. Planned values
are therefore not exact Bellman values of the deployed adaptive policy. The
study retains both the planned value and the actual subsequent net return.

## Eight registered arms and fair comparisons

Every arm receives the same public observation: current level, inputs, price,
remaining time, refractory remainder and legal actions. The simulator's true
coefficients and hidden stress regime are not policy inputs.

| Arm | Fitted model / policy capacity | Decision rule and interpretation |
| --- | --- | --- |
| `fixed_shared6` | Shared six-parameter model; fixed repair threshold | Distance threshold 0.35, with the common negative-value STOP guard; structural reference with fewer policy degrees of freedom |
| `fixed_cross7` | Seven-parameter physical model; fixed repair threshold | Extra predictive drift interaction matches total count, but changes capacity allocation; not a pure boundary-only ablation |
| `learned_threshold7` | Shared six-parameter model + one learned distance threshold | 17 thresholds from 0.05 to 0.85, with the same STOP guard; a concrete ordinary learned-boundary family |
| `ordinary_first_event` | Shared six-parameter model + one gap bias | Cost/deadline-aware first-event value approximation; a stronger renewal ablation, not an arbitrary ordinary threshold |
| `endogenous_renewal` | Shared six-parameter model + one gap bias | Accounts for repeated events, resets and refractory time in candidate plan values |
| `always_wait` | Fixed-action control | Always waits; not a learned-policy parameter-budget comparator |
| `always_repair` | Fixed-action control | Repairs whenever legal and otherwise waits |
| `stop` | Fixed-action control | Stops immediately, with exactly zero future task return |

The constant-threshold arm receives price and deadline but its repair gate
does not explicitly adapt to them; that is its structural restriction. Both
value-boundary arms use the same 17-point bias grid from -0.08 to 0.08. All
three calibrated families use the same 128 policy-development scenarios per
seed, the same realized utility objective, and first-grid-index tie breaking.
The selected score is the original native Q32 realized return; unquantized
actual returns are retained separately.

The task ledger charges actual activity, failures and executed repair exactly
once for every arm. This common task-cost convention does not establish equal
computational budgets. The runner separately records wall time, Python-process
CPU time, native calls, forecast requests and cache hits. Python process CPU
excludes child native-process CPU. Shared forecast caching and subprocess
costs must be considered before making speed claims. Development caches are
isolated by scenario and arm and reused only within that arm's 17-point grid.
Confirmation and stress use a new cache for each arm and episode. These measured
regimes differ; their raw timings are not interchangeable cold-inference costs.

Arms share each public scenario and named counter-based random stream. Different
actions change resets, refractory periods and subsequent draw counts. This
pairing is not a claim that every arm follows one identical continuous Brownian
sample path. Statistical pairing is by complete scenario/episode within each
model seed.

## Native NDU contract

The adapter calls the unchanged owner functions
`codex_hepta_ndu::evaluate_recursive_utility` and
`codex_hepta_ndu::evaluate_candidates_with_policy`. Its registered profile is
`hepta.ndu.recursive-utility.scalar.q32.v1`, with signed Q32, nearest/ties-even
rounding, and finite-horizon scalar recursion

$$
 U_k=\operatorname{clip}\bigl(r_k+\gamma_k U_{k+1},L,U\bigr).
$$

This study uses `gamma = 1`, zero terminal value, and bounds of +/-1,000,000
task-return units. The adapter rejects projected utilities and unknown
profiles. It does not substitute an entropic utility or a general FBSDE solver.
For this additive profile, expected plan increments can be evaluated by the
same native recursion. A separate native realized path uses actual executed
transitions and their costs.

Native V2 requires `abstain`; task `STOP` explicitly maps to that zero-effect
candidate. Native feasibility, ties and candidate identities are retained.
Output authority remains `DENY_ALL` with `safety_certificate=false`. A forecast
receipt is evidence of computation and lineage, not execution authority or a
proof that a predicted outcome occurred.

The independent Python integer recurrence checks native values and recursive
evidence hashes. Compact episode receipts retain source/binary identities,
request and evaluation digests, candidate/action mappings and recursive values.
The original candidate order, public inputs, model identity and contexts allow
reconstruction after canonical JSON compression. Full receipts are additionally
retained for the first scenario of every arm and model seed. See
[NATIVE_REPRODUCE.md](NATIVE_REPRODUCE.md) for original-source provenance,
locked dependency restoration, build/test gates and rounding details.

## Evidence currently available

| Evidence | What it establishes |
| --- | --- |
| [KERNEL_VALIDATION.json](evidence/KERNEL_VALIDATION.json) | 294 passing checks, including a summarized 720-tuple discount-bound grid; independent integrals, gradients, killed mass/composition, tails and observation semantics |
| [TRAINING_VALIDATION.json](evidence/TRAINING_VALIDATION.json) | Six- and seven-parameter fits for all eight seeds: 16 retained fits, active parameter changes and independent distribution-based likelihood checks |
| [PYTHON_VALIDATION.json](evidence/PYTHON_VALIDATION.json) | Final integrated research-package suite: 65 tests passed, zero failures, zero errors and zero skips; actual retained native executable used |
| [POLICY_DEVELOPMENT_AUDIT.json](evidence/POLICY_DEVELOPMENT_AUDIT.json) | All 52,224 development episodes passed independent ledger, native-path and selection checks; all eight seeds retained |
| [CONFIRMATION_AUDIT.json](evidence/CONFIRMATION_AUDIT.json) | All 16,384 confirmation episodes audited; all three registered paired-gain gates passed |
| [STRESS_DRIFT_AUDIT.json](evidence/STRESS_DRIFT_AUDIT.json) and [STRESS_DIFFUSION_AUDIT.json](evidence/STRESS_DIFFUSION_AUDIT.json) | Two additional 8,192-episode cohorts audited without refitting or changing policy parameters; descriptive model-mismatch evidence |
| [NDU_VALIDATION.json](evidence/NDU_VALIDATION.json) | Six Rust tests and eleven Python native/value tests already included in the 65-test suite above; exact finite-tree arithmetic, 64 fixed diagnostic observations and 10,000 independently sampled renewal paths |
| [test_audit.py](tests/test_audit.py) | Hand-computed event/refractory/cost ledgers, deliberate score and event-time forgeries, paired-cohort completeness and statistical decision gates |
| [test_study.py](tests/test_study.py) | Preparation/selection identity, atomic evidence and study lifecycle checks |

The diagnostic cohort and sampling checks do not establish policy superiority.
The final integrated receipt records a successful original `just fmt` invocation
and preservation of the native adapter digest. The NDU receipt also retains
historical formatting attempts, including the earlier generated-symlink rejection;
those historical entries have not been overwritten. This is scoped package
validation, not a claim that the full repository CI suite passed.

### Retained interruption and repair history

The first policy-development attempt encountered `ENOSPC` before confirmation.
Its original incomplete gzip bytes and failure receipt remain in
[evidence/aborted_policy_preparation_01](evidence/aborted_policy_preparation_01).
The storage writer now reserves a bounded 32 MiB before generating an episode,
rejects capacity overflow, and removes the reserved zero tail when closing.

Independent review also found a task-checkpoint restoration consistency gap:
a rehashed checkpoint could claim a scenario seed different from its stored RNG
seed. The repair adds that cross-check. [SOURCE_REPAIR.json](evidence/SOURCE_REPAIR.json)
records the exact two-line guard and proves that removing it recovers the earlier
training-time `task.py` byte hash. Physical data generation and likelihood fitting
do not call that restoration method, so their original provenance and all 16
fits are retained unchanged.

The complete development cohort was then rerun with exactly the same seeds,
scenarios, grids and costs. Its independent audit confirms all 52,224 episodes
and 623,801 retained native recursive paths. All 10,902 complete episode records
recoverable from the interrupted prefixes match the rerun after excluding only
runtime timing fields. No aborted prefix is counted as a second independent
cohort. No favorable development outcome may justify selecting, deleting or
replacing a confirmation seed. Development is used only for the registered
per-seed policy parameter selection.

## Registered cohort and statistical interpretation

All eight model seeds are fixed in `PROTOCOL.json`: 1103, 1151, 1201, 1213,
1223, 1231, 1237 and 1249. Per seed there are 512 training trajectories,
128 likelihood-development trajectories and 128 policy-development scenarios.
Across the three 17-point policy grids, preparation retains 52,224 development
episodes. Plan storage for their complete compressed evidence before starting.

Confirmation has 256 paired whole episodes per model seed and arm: 16,384
episodes across eight arms. Each registered stress phase has 128 per seed and
arm. The drift-shift and diffusion-multiplier stresses are prespecified model
mismatches, not certificates of population robustness.

The three primary comparisons are endogenous renewal minus first-event value,
minus `fixed_cross7`, and minus `learned_threshold7`. The independent audit uses
4,000 bootstrap replicates, resampling model seeds and paired whole episodes.
Two-sided Bonferroni tails are `0.05 / (2 * 3)`. Each individual comparison passes its
registered gain gate only if its empirical adjusted lower bound exceeds 0.005
and every model-seed mean gain is positive. These are empirical intervals from
eight seeds, not finite-sample coverage guarantees. Failure of a gain gate is a
result to retain, not a reason to retrain on confirmation or change the cohort.

## Reproduce from the repository root

The recorded numerical environment is Python 3.12, NumPy 2.3.5 and SciPy 1.17.0.
The retained native executable is Linux x86_64. Other platforms or a different
native build require a new recorded build identity and matching study freeze;
see `NATIVE_REPRODUCE.md`.

### 1. Materialize archived evidence, restore the native executable, and run tests

A cold checkout first reconstructs the retained original evidence files. The
archive manifest `EVIDENCE_ARCHIVE.json` identifies bounded binary parts under
`evidence/data_parts/<original-sha256>/<index>.bin`. Their representation changes
only transport and storage: the restore helper verifies each part and the
reassembled original byte count, SHA-256 and Git blob SHA. It generates no new
trajectories, loads no pickle, and refuses to overwrite a differing existing
file. Run restoration before native verification, freeze checks or replay:

```bash
python -m experiments.first_passage_cell.evidence.audit_helpers.restore_archives
python -m experiments.first_passage_cell.restore_native
python -m experiments.first_passage_cell.evidence.audit_helpers.restore_archives --verify-only

HEPTA_FIRST_PASSAGE_NATIVE="$PWD/experiments/first_passage_cell/NATIVE_BUILD.json" \
  python -m unittest \
  experiments.first_passage_cell.tests.test_kernels \
  experiments.first_passage_cell.tests.test_cell \
  experiments.first_passage_cell.tests.test_ndu \
  experiments.first_passage_cell.tests.test_audit \
  experiments.first_passage_cell.tests.test_study -v
```

Restoration verifies the compressed executable against the retained binary
SHA-256 and refuses to replace a different existing binary. The explicit
manifest environment variable makes the native test dependency unambiguous.
The original repository formatting gate remains `just fmt`; it is not a
comprehensive Python lint result. The
[archive restoration helper](evidence/audit_helpers/restore_archives.py) fails
on missing or corrupt parts. A layout manifest or a recorded hash alone is not
a claim that all required bytes have already been remotely published. The final
[publication receipt](evidence/ARCHIVE_PUBLICATION.json) verifies all 319 stored
data objects for 52 original artifacts (145,319,237 bytes); the final manifest
restoration check passed for every original. See [RESULTS.md](RESULTS.md) for the
registered outcomes and their scientific scope.

For the retained study, use the package's `prepared/` and [FREEZE.json](FREEZE.json)
after restoration. Audits can be repeated into new receipt paths without
rerunning the physics fit or policy selection. The next section instead
prepares a new run, which requires a new matching published freeze.

### 2. Prepare all physics and policy artifacts

Set the following paths to writable locations. Use a fresh preparation/output
directory for a new run; existing artifacts are deliberately not overwritten.
The freeze path must name the published manifest for those exact artifacts,
not a fabricated source commit or an old run's unrelated preparation.

```bash
FP_PREPARED=/absolute/path/to/first-passage-prepared
FP_OUTPUT=/absolute/path/to/first-passage-output
FP_NATIVE="$PWD/experiments/first_passage_cell/NATIVE_BUILD.json"
FP_FREEZE=/absolute/path/to/published-first-passage-freeze.json

python -m experiments.first_passage_cell.study prepare \
  --stage physics --prepared "$FP_PREPARED"

python -m experiments.first_passage_cell.validate_training "$FP_PREPARED" \
  --output "$FP_OUTPUT/training_validation.json"

python -m experiments.first_passage_cell.validate_kernels \
  --output "$FP_OUTPUT/kernel_validation.json"

python -m experiments.first_passage_cell.study prepare \
  --stage policy --prepared "$FP_PREPARED" --native-manifest "$FP_NATIVE" \
  --seed 1103 --seed 1151 --seed 1201 --seed 1213 \
  --seed 1223 --seed 1231 --seed 1237 --seed 1249

python -m experiments.first_passage_cell.study prepare \
  --stage finalize --prepared "$FP_PREPARED" --native-manifest "$FP_NATIVE"
```

Explicit `--seed` preparation can be split across workers with distinct seeds;
a subset does not finalize the study. The last command checks all registered
seeds and creates `prepared_manifest.json`. It rejects missing, inconsistent
or interrupted preparation. A policy preparation call without explicit seeds
processes all seeds and finalizes automatically; do not then try to overwrite
its completed manifest with another finalize call.

### 3. Publish the matching freeze before confirmation

The study owner publishes the exact source commit and a freeze manifest that
binds protocol, complete prepared artifacts, runtime sources, native source and
binary, and build manifest. `verify_freeze` checks those file contents, and
`validate_preparation` checks seed/model/data/grid/selection consistency before
any confirmation scenario generation. Runtime code must remain fixed through
evaluation. The exact published freeze identifier belongs with the run evidence. A local
40-character commit-shaped string is not remote publication evidence: the study
owner must verify that the named commit contains the recorded source bytes.

### 4. Run, audit, and replay the frozen study

```bash
python -m experiments.first_passage_cell.study run \
  --prepared "$FP_PREPARED" --output "$FP_OUTPUT" \
  --native-manifest "$FP_NATIVE" --freeze "$FP_FREEZE" --phase confirmation

python -m experiments.first_passage_cell.audit "$FP_OUTPUT" \
  --phase confirmation --output "$FP_OUTPUT/confirmation_audit.json"

python -m experiments.first_passage_cell.study replay \
  --native-manifest "$FP_NATIVE" \
  --episode-file "$FP_OUTPUT/confirmation/1103.jsonl.gz" --line-index 0
```

Run the two registered stress phases with the same frozen artifacts and
`--phase stress_drift` and `--phase stress_diffusion`. Audit each with the same
phase name and its own new output JSON. They do not permit a new fit or policy
selection. The run command always uses the complete registered seed set;
`--seed` is a preparation option, not a confirmation subset selector.

Each phase writes per-seed compressed episode ledgers and a phase run receipt.
The writer reserves 32 MiB per active ledger before its first episode; make room
for this working allocation in addition to completed data. An active incomplete
file can therefore appear larger than its written payload. Completed files are
truncated to the exact gzip bytes. Interrupted `.incomplete` files do not pass
as complete ledgers. The independent
audit reconstructs active time from event/refractory timing, recomputes all
costs and returns, and rejects missing or duplicate paired outcomes. Replay
reconstructs native forecast and realized receipts; it is distinct from the
independent arithmetic audit and from cell/task checkpoint continuation.

## What these results cannot establish

This is one scalar stochastic cell and a controlled maintenance task. It is not
a trained general SNN architecture, a biological-neuron model, a whole-system
Hepta improvement, or evidence of superiority over arbitrary learned boundary
classes. There is no claim that every admissible floating-point input is exact,
that a finite grid posterior is closed under exact filtering, or that a
wait-after-current forecast is an optimal adaptive value function.

The financial inspiration is analytic barrier/default propagation and
value-dependent intervention, as discussed in
[He and Xiong, Rollover Risk and Credit Risk](https://www.princeton.edu/~wxiong/papers/rollover.pdf).
This package uses a declared physical data-generating measure, not an implicit
risk-neutral pricing measure. It does not reproduce that paper's complete
credit-market equilibrium or free-boundary solution.

[Deep Q-Learning on Holder Spaces](https://arxiv.org/abs/2606.16846) is a related
function-space learning direction. Its results do not automatically transfer to
this cell merely because an analytic operator is used. A transfer would need
explicit state/function spaces, regularity and conditioning bounds, an
appropriate Bellman operator, and the relevant approximation and learning
assumptions. This package supplies testable finite-model components and honest
value interfaces; it does not claim such a theorem or a new general convergence
result.
