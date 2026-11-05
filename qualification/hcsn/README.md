# HX kernels and HCSN research qualification

This package connects the He–Xiong stationary rollover model to two separately reported neural architectures: **A, a value-feature recurrent encoder**, and **B, a resetting population-flux encoder**. It provides reproducible checks and synthetic experiments. It does not establish task superiority, a dynamical phase transition, or global network/NDU optimality.

## Evidence and current status

| Evidence | What it supports | Current scope |
| --- | --- | --- |
| [Kernel receipt](evidence/kernel_reference.json) | FP64 value matching, smooth pasting, debt/equity residuals, limits, homogeneity and independent derivative checks | Passed for the recorded cases; formal inadmissible roots are explicitly labeled |
| [Mechanism receipt](evidence/mechanisms.json) | Rest, repeated pulses, recovery, refractory timing, sustained input, tested coupling, mass accounting and joint refinement | Numerical probes passed; stronger tested coupling exhibits synchronized population-rate bursts |
| [Local test receipt](evidence/local_tests.json) | Exact counts of passed, failed and skipped tests, with source hashes | NumPy checks have run locally; inspect skips instead of counting them as tensor passes |
| PyTorch checks and training receipts | Tensor values/gradients, A/B forward/backward, smoke training and measured performance | Pending measured CI evidence at the time this README was written |

Receipts bind results to their recorded source hashes and software versions. The local environment used for the bundled NumPy evidence has no PyTorch. The [research workflow](../../.github/workflows/hepta-hcsn-research.yml) requires PyTorch and retains JSON artifacts for its exact commit; a queued or running job provides no pass result. No full CUDA comparison or measured energy result is currently claimed. Mathematical details and feasibility distinctions are in [MATH.md](MATH.md).

## Install and reproduce

Run commands from the repository root. The focused CPU workflow uses the pinned dependencies and official PyTorch 2.8.0 CPU wheel:

```bash
python -m venv /tmp/hcsn-venv
source /tmp/hcsn-venv/bin/activate
python -m pip install -r qualification/hcsn/requirements.txt
python -m pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu
```

The requirements include the maintainer's `ncps==1.0.1` release. Full CUDA experiments need a compatible, explicitly pinned CUDA PyTorch/Mamba installation from the official projects; record that environment with the results. The CPU wheel cannot execute the official Mamba-2 benchmark. Missing optional implementations are reported as `unavailable` and never replaced by another model.

```bash
# Local checks may run without torch; their receipt records the skipped tests.
python -m qualification.hcsn.checks --output /tmp/hcsn-local-tests.json
# Required CI gate: missing torch or any skipped test gives a nonzero exit.
python -m qualification.hcsn.checks --require-torch --output /tmp/hcsn-tensor-tests.json
python -m qualification.hcsn.validate --output /tmp/hcsn-kernel-reference.json
python -m qualification.hcsn.mechanisms --output /tmp/hcsn-mechanisms.json
python -m qualification.hcsn.benchmark \
  --config qualification/hcsn/configs/smoke.json --output /tmp/hcsn-smoke.json
# On the configured CUDA device, with the official optional dependencies:
python -m qualification.hcsn.benchmark \
  --config qualification/hcsn/configs/full.json --output /tmp/hcsn-full.json
```

`checks --require-torch` is mandatory for a tensor qualification claim. The benchmark exits 1 for an execution failure and 2 when no run completes; optional unavailability can coexist with exit 0, so read `status`, per-run reasons and summary counts. CUDA requests do not silently fall back to CPU. Preserve fresh receipts rather than overwriting historical evidence for a different source revision.

## Kernel API, units and domain

The main map is `(V, theta, T) -> {b, E_HX, F, G, f}` with an explicit `first_passage_atom`. Low-level hitting/equity functions take **`x = log(V/b)`**, not `V`. Here `F` is first-hit probability, `G` its discounted counterpart at `q = r + ell`, and `f` the regular first-hit density.

```python
import torch
from qualification.hcsn import tensor as hx

params = hx.HXParams(r=torch.tensor(0.05, dtype=torch.float64, requires_grad=True))
value = torch.tensor([140.0, 180.0], dtype=torch.float64, requires_grad=True)
result = hx.evaluate(value, params, horizon=0.5)
result["E_HX"].sum().backward()
```

[`reference.py`](reference.py) is the independent FP64 implementation: `hx_equity` uses numerical killed-resolvent quadrature as an oracle, while `hx_equity_closed` evaluates the A7-equivalent expression. Both backends' `evaluate` interfaces return the equity key `E_HX`. [`tensor.py`](tensor.py) supplies differentiable FP32/FP64 expressions and stable boundary/tail branches. Quadrature is not presented as a production tensor fast path. Tensor tests must establish agreement and gradients before training results are interpreted.

| Quantity | Units or convention |
| --- | --- |
| `V`, `b`, `E`, `principal = P` | Money in one consistent normalization |
| `coupon = C` | Aggregate coupon flow, money/time |
| `maturity = m`, `horizon = T`, neural `dt` | One consistent model-time unit |
| `r`, `delta`, `ell = xi*k` | Inverse time; learn `ell` directly |
| `sigma` | Inverse square root of time |
| `tax`, `recovery = alpha`, `x`, `F`, `G` | Dimensionless |
| `f`, population firing rate | Inverse time; different state/process interpretations |

`hx_debt` returns debt value **per unit of the stationary maturity ladder**, with `p=P/m` and `c=C/m`; it is not aggregate debt. All tensor arguments must share a device and use FP32 or FP64. FP16/BF16/autocast qualification is outside this implementation. Reported wall-clock seconds are separate from the model-time unit.

Primitive conditions are `r, delta, sigma, m, P > 0`, `coupon, ell >= 0`, `0 <= tax < 1`, `0 <= recovery <= 1`, and `x,T >= 0`. Exact zero volatility/rate/payout is not introduced through epsilon substitutions. `ell=0` is supported and **still contains rollover**. At `x=0`, `F=G=1` for `T>=0`; `f` excludes the atom at time zero. At `x>0,T=0`, `F=G=f=0`. A first-event density alone is not the firing rate of a population with repeated resets.

### Formal roots and economic feasibility

Positive primitive parameters and a smooth-pasting root do not guarantee a valid equity value. With

```text
g0 = delta*b - (1-tax)*coupon + recovery*b/maturity - principal/maturity,
E_xx(0+) = -2*g0/sigma**2,
```

`g0<=0` is a **local necessary screen**. `reference.parameter_feasibility(params)` separately reports `local_admissible`, `sufficient_monotone_subdomain` and `uncapped_recovery_exceeds_face`. The stronger condition `R<=min(p,c/q)`, where `R=alpha*b/m`, provides a sufficient monotone-cashflow subdomain; passing only the local screen is not a global nonnegativity or optimal-stopping proof. The numerical stress scan intentionally includes negative-equity formal solutions and labels them.

The paper's recovery payoff is uncapped. `alpha*b>P` is a separate diagnostic, not a universally established exclusion in the original model. Capping recovery would change the equations and requires a new derivation. Neither equity nor recovery is silently clipped. Tensor `validate=True` rejects locally inadmissible boundaries and negative requested continuation values; `validate=False` is used for explicit formal-equation tests and already-screened inner calls, not to certify economics. See [MATH.md](MATH.md) for the derivation and counterexample.

## Version A: value-driven continuous memory

[`ValueKernelCell`](cells.py) uses `E_HX/V` and `F(x,maturity)` as gate/candidate features, a vector memory `h`, and a recovery state. Its “call” channel is normalized HX equity. Each step freezes its rate and target and applies

```text
h_next = h + (1 - exp(-rate*dt)) * (target - h).
```

The rate is bounded and positive, the target is `tanh`, and recovery follows another exponential update. Starting from zero, memory stays in `[-1,1]` and recovery in `[0,1]` for nonnegative scalar `dt`. This is an exact frozen-coefficient update; it does not exactly solve the continuously changing nonlinear vector field or implement threshold/reset spikes.

Learned base parameters are bounded to `r∈(.02,.10)`, `delta∈(.01,.05)`, `sigma∈(.15,.45)`, `coupon∈(.02,.08)`, `maturity∈(.5,2)` and `ell∈(0,.03)`, with `P=1`, `tax=.25`, `alpha=.60`. The corner/random tests screen this box; finite sampling is not a theorem about every possible parameter/input. The boundary receives its runtime local-feasibility check once per sequence.

Input conditioning scales coupon and principal together, giving `b=b0(theta)*exp(shift)` with `|shift|<=.25`. The independent asset map is `V=P*(2.4+2*sigmoid(input_map+0.2*h))`; it is anchored to face value, not to `b0`. Thus `x=log(V/b0)-shift` retains financial-boundary sensitivity, including the risk channel's gradient to `ell`. The HX and constant-carry boxes are checked against the asset lower bound, and an explicit runtime domain check rejects `x<0` without clipping equity or mapping a defaulted state back into continuation. A sequence of such stationary features is **not a first-passage law for an arbitrary moving boundary**. `hx_fixed` removes input conditioning while retaining learned global financial parameters.

In exact arithmetic, `g0<=0` and this parameter box imply `b0/P<=(1+.75*.08*2)/(.6+.01*2)=1.806452`; the asset floor and maximum shift therefore give `x>=.034104`. Accounting for the FP32 guard tolerance still leaves a conservative margin above `.034`. The constant-carry boundary's maximum is `1.683595*P`, giving margin above `.1045`. These domain bounds are separate from the stronger question of global financial admissibility. Risk-only regression tests check nonzero liquidity and boundary gradients at an interior parameter point; far-tail FP32 underflow can legitimately eliminate gradients elsewhere.

All encoder factory outputs have shape `[batch,time,hidden]`. A minimal trainable sequence regressor is:

```python
import torch
from qualification.hcsn.baselines import make_encoder

torch.manual_seed(0)
x = torch.randn(4, 8, 2)
target = x[:, 0, :1].clone()
encoder = make_encoder("hx_dual", 2, 8, device="cpu", dt=0.1)
readout = torch.nn.Linear(8, 1)
optimizer = torch.optim.Adam([*encoder.parameters(), *readout.parameters()], lr=1e-3)
optimizer.zero_grad(set_to_none=True)
prediction = readout(encoder(x, dt=0.1)[:, -1])
loss = (prediction - target).square().mean()
loss.backward()
optimizer.step()
```

Choose `population_flux` for B through the same factory. For streaming A, retain the `(memory,recovery)` tuple returned by `ValueKernelCell.step`; `forward` initializes a fresh state for each sequence. The snippet demonstrates API use, not a completed training experiment.

## Version B: probability transport, reset and refractory state

[`Population`](population.py) and [`TorchPopulation`](population_torch.py) maintain active density mass, a refractory queue, recovery and an upper-grid escape account. The output is **absorbed mass / dt**, followed by a readout filter in `PopulationFluxEncoder`. Positive drive moves log margin toward the fixed absorbing boundary `x=0`. B currently studies this reset/first-passage mechanism with fixed physical parameters; it does not learn the HX financial free boundary or the full rollover coupling.

```python
import torch
from qualification.hcsn.population import PopulationConfig
from qualification.hcsn.population_torch import TorchPopulation

cfg = PopulationConfig(bins=32, dt=0.1)
population = TorchPopulation(cfg, dtype=torch.float32)
state = population.initial_state(shape=(4, 8))
step = population(state, drive=torch.full((4, 8), 4.5))
state, rate = step.state, step.rate
mass = state.total_mass()  # active + refractory + escaped
```

The killed Brownian transition is integrated over destination bins with drift frozen at each source centre. Density projection, nonlinear drift freezing and step-end reset remain discretization errors. Queue length is fixed, not differentiable; gradients flow through drive, coupling and tensor state without surrogate spike derivatives. There is no same-step refiring. Escape mass is retained instead of renormalized or reinjected; monitor it when choosing the domain.

The benchmark uses **32 bins, `dt=.1`, requested refractory `.24`, effective refractory `.3`** after rounding up to three steps. The mechanism receipt instead uses 64 bins and `dt=.02`, where effective refractory is `.24`. Its successful probes and joint grid/time refinement cannot automatically qualify a trained B at the benchmark settings. Jointly refine spatial and temporal resolution, inspect escape and mass conservation, and report sensitivity. Dense transitions cost quadratically in the number of bins. B's fixed boundary also does not implement arbitrary moving-boundary first passage.

Report A and B separately: comparing them changes state capacity, numerical approximation and architecture as well as the output mechanism.

### Observed coupling: synchronized bursts

The [`coupling_scan` receipt](evidence/mechanisms.json) uses seed **20261105**, two heterogeneous units, strengths **0, .08, .3, .8**, and the same seeded drive perturbations across strengths. Units differ in noise, rest/reset margin and tonic drive; coupling adds the other unit's preceding-step rate to the drive. The observation lasts 16 model-time units at `dt=.02`; the reported tail is **(8,16]**, comprising 400 interval-average rates.

| Coupling | Tail zero-lag correlation | Tail mean rates, units 0 / 1 | Tail peak rates, units 0 / 1 |
| --- | ---: | ---: | ---: |
| 0 | -0.26794 | 1.66559 / 1.59829 | 2.18449 / 1.96142 |
| .08 | 0.60120 | 1.69418 / 1.63901 | 3.54662 / 3.30942 |
| .3 | **0.98449** | 1.82089 / 1.83445 | **21.04717 / 23.08186** |
| .8 | **0.99788** | 1.75000 / 1.75000 | **34.81471 / 36.79544** |

Rates have inverse-model-time units; the peaks are interval averages, not infinitesimal-time measurements. The stronger couplings show pronounced synchronized population-rate bursts even though mean rates remain about 1.75–1.83. Every scanned run is numerically finite and mass-conserving, which **does not rule out harmful synchronization**. The time grid itself caps the reported rate at `1/dt=50` through its one-event-per-step convention.

These correlations describe population-rate cofluctuation; microscopic spike coincidence was not measured. The receipt also reports lag scans, whose maxima can select periodic aliases and do not identify a causal conduction delay. Synchrony is an observed outcome rather than a pass/fail gate. This finite scan does not establish global stability, a critical coupling, a phase transition or a bifurcation.

## Experiment matrix and budgets

The exact mapping is implemented in [`baselines.py`](baselines.py):

| Config name | Model or ablation |
| --- | --- |
| `hx_dual` | A: full HX rollover, both channels, conditioned boundary and recovery |
| `hx_fixed` | A with input-independent boundary; global financial parameters remain learnable |
| `hx_call`, `hx_risk` | A with only `E_HX/V`, or only `F`; the unused channel is not evaluated |
| `no_rollover` | Separate constant-carry equity `simple_equity_ratio`; not the `ell=0` HX limit |
| `softplus` | Bounded softplus/sigmoid feature control with frozen financial parameters |
| `no_recovery` | A with recovery feedback removed |
| `hx_attention` | A followed by two causal SDPA attention blocks |
| `population_flux` | B with true population absorption, reset, refractory state and recovery |
| `population_flux_no_recovery` | B with recovery strength zero; reset/refractory remain (full config) |
| `gru` | Native `torch.nn.GRU` |
| `lif`, `adaptive_lif` | Leaky integration, discrete threshold checks and hard forward reset; logistic surrogate gradient; latter adds threshold adaptation |
| `pif` | Conservative upwind perfect-integrate-and-fire population with reset and CFL-controlled substeps; no leak or refractory period |
| `transformer` | Two causal pre-norm blocks using native PyTorch SDPA dispatch |
| `cfc` | Official `ncps.torch.CfC`, with per-step timespans |
| `mamba2` | Official `mamba_ssm.Mamba2`; CUDA required by this wrapper |

The call/risk/dual, fixed/conditioned boundary, full/absent rollover, financial/ordinary features, recovery and attention comparisons address different hypotheses. PIF and population flux are density models; LIF event times are checked on the time grid. Missing CfC/Mamba installations remain explicit unavailable entries.

| Budget | [Smoke](configs/smoke.json) | [Full research](configs/full.json) |
| --- | --- | --- |
| Tasks | Delayed recall | Delayed recall and adding |
| Models × seeds × tasks | 16 × 3 × 1 = **48 requested runs** | 17 × 5 × 2 = **170 requested runs** |
| Train / validation / test examples | 128 / 32 / 64 | 4096 / 512 / 1024 |
| Sequence length / hidden width | 8 / 8 | 64 / 64 |
| Batch size / optimizer steps | 16 / **8** | 64 / 400 |
| Device / inference repeats | CPU / 7 | CUDA / 100 |

Smoke's three seeds and eight optimizer steps check the training path and reporting. They do not establish convergence or superiority over Transformer, Mamba-2 or any other baseline. Full is a research configuration awaiting execution, not a completed result. Both tasks are synthetic: delayed recall predicts the first scalar after distractors; adding sums two marked entries, one from each half of the sequence.

Every model receives the same split arrays and hashes, minibatch draws per seed, step count and token budget. Splits are independent; checkpoint selection uses validation only and the held-out test is evaluated once after selection. Validation/test are evaluated in batches. Hidden width is shared, **parameter count is not matched**; actual total/trainable counts are reported. The setup uses eager FP32 training and the selected implementations, without claiming equal hyperparameter tuning or a large-language-model scaling comparison. Requested deterministic algorithms use `warn_only=True`, so bitwise identity across devices is not guaranteed.

## Reading performance and failure reports

- **Quality:** per-run test MSE, validation selection, a training-mean constant predictor, and mean/seed standard deviation over completed runs. Always report completed, failed and unavailable counts beside those means.
- **Throughput:** training examples/second includes validation and checkpoint-copy time; construction and initial data transfer precede that timer. Inference throughput is batch forward throughput, with two warmups and CUDA synchronization after each timed call.
- **Latency:** p50/p95 are batch-forward wall times on the recorded hardware, not individual-event latency or an end-to-end service measurement.
- **GPU memory:** `max_memory_allocated` is reset after model/data construction and read after training/validation, before test/latency measurement. It includes resident model/data plus training, optimizer and saved-checkpoint tensors; it is neither allocator-reserved memory nor total device usage. CPU runs have `null` with a reason.
- **Failures:** training failure rate uses runs that reached training; execution failure rate also covers construction/evaluation failures. Missing dependencies are counted separately from failed training. A numerically finite run that has not converged or has not beaten the constant predictor can still be `completed`; this failure rate does not measure learning success.
- **Energy:** joules are read from accessible RAPL package/NVML GPU counters over the training wall interval, including validation. Sampling handles counter wrap, and GPU UUIDs avoid logical-device remapping mistakes. Counters cover the device/package and other activity, not process attribution or necessarily the whole machine. No accessible counter means **`null` plus a reason**, never an inferred TDP/runtime estimate or zero. These are energy measurements; no average-power result is asserted.

The JSON also records configuration, command, seeds, source hash, package versions, hardware, parameter counts and population discretization. Subsequent research needs completed tensor CI, full multi-seed experiments, population convergence/escape audits at trained settings, and matched-capacity/tuning studies before stronger conclusions. Finite transient tests are separate from a phase-transition/bifurcation analysis. A financial boundary's local optimality does not imply an optimal network task objective or global NDU optimum.

## Primary sources

- He, Z. and Xiong, W. (2012), *Rollover Risk and Credit Risk*, Journal of Finance 67(2), equations (8), (9), (12), (A5), (A7): [author-hosted published paper](https://zhiguohe.net/wp-content/uploads/2023/12/The-Journal-of-Finance-2012-HE-Rollover-Risk-and-Credit-Risk.pdf), [DOI](https://doi.org/10.1111/j.1540-6261.2012.01721.x).
- Official CfC implementation: [ncps repository](https://github.com/mlech26l/ncps), [maintainer release 1.0.1](https://pypi.org/project/ncps/1.0.1/).
- Official Mamba-2 implementation and installation requirements: [state-spaces/mamba](https://github.com/state-spaces/mamba).
- PyTorch 2.8 API and backend dispatch: [scaled_dot_product_attention](https://docs.pytorch.org/docs/2.8/generated/torch.nn.functional.scaled_dot_product_attention.html).
