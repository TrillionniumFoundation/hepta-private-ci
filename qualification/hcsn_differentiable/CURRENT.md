# HCSN research: current qualified scope

This page supersedes the *status claims* in the immutable first math-closure
snapshot; it does not alter that snapshot's source or execution records. The
current source includes the stable interval-probability repair. Its native
qualification passed **75 tests**, the **four original error-budget fixtures**,
and the separately declared **0.2-second frozen-physics localization profile**.
Six real model interfaces each completed three independently initialized runs:
**18 interface fits and 72 optimizer updates**. Formal comparative fits remain
**zero**. There is no model-superiority, full-domain, energy-efficiency, or
repository-wide CI-pass claim.

The source-bound receipts and failures are indexed in
[the new evidence record](evidence/localization-v2-20261108/README.md).
The historical [math-closure snapshot](evidence/math-closure-20261108/README.md)
retains its original 71-test result and blocked data attempt; those numbers are
historical and are not substituted for the new execution.

## Mathematical objects and fixed policy

`MODEL.md` distinguishes original financial equity `E`, killed single-cycle
value `C`, regenerative value `U`, first-hit probability `F`, discounted first-hit
mass `G`, instantaneous event-rate density `J`, and cumulative expected event
count `M`. The implemented Brownian policy uses a fixed trigger, a fixed absolute
reset, and a deterministic refractory delay. It does not solve an endogenous
optimal boundary or the original financial equity/rollover model.

For discount `q>0`, log drift `mu`, diffusion `sigma>0`, active margin `x>0`,
reset margin `xr>0`, and refractory delay `d>=0`, the first-hit Laplace transform is

```text
lambda = (mu + sqrt(mu**2 + 2*q*sigma**2)) / sigma**2
g(x) = exp(-lambda*x)
C^(a,h)(x) = a*(1-g(x))/q + h*g(x)
U(xr) = C^(a,h)(xr) / (1-exp(-q*d)*g(xr))
U(x) = C^(a,h)(x) + g(x)*exp(-q*d)*U(xr)
```

`C^(a,h)` here equals the perpetual killed running value plus `h*g(x)`, where
`h` is a scalar hit payoff. `MODEL.md` separately defines its killed `C_T` with
zero absorption payoff and a terminal survival payoff function; that function
is not this scalar `h`. The finite renewal implementation additionally requires
`d>0`. The implementation rationalizes cancellation-prone
roots and uses `expm1` for small denominators. Finite-horizon renewal sums and
the projected-chain linear/backward equations are separate implementations.
They pay a requested terminal reward once. The legacy `call`, now explicitly
aliased as `interval_value`, still includes its one-interval terminal feature;
adding it across intervals is not an implementation of `U`.

## Numerical repair and measured budgets

The first 0.2-second profile attempt failed on a refined active grid. Subtracting
two separately rounded killed survivor tails produced a negative cell mass of
`-1.1102230246251565e-16`, while an independent 80-digit computation gave the
positive probability `1.11885857336992304804e-16`. The repair computes reflected
Gaussian *interval* probabilities directly, chooses a CDF or survival-function
representation before differencing, and uses stable exponential differences.
It adds four targeted regression/gradient checks. It does not clip a negative
mass, renormalize a row, loosen a tolerance, or change the profile's physics,
window identities, quadrature, grid, or pass limits.

The locked 0.2-second model uses 128 active cells, one returning tail and 16
remaining-time cells. It freezes the actual instantiated FP64 physics and
source hashes. The maximum observed scaled sensitivities were:

| Quantity | Observed | Declared limit |
| --- | ---: | ---: |
| Common-prior perpetual value error | 0.208556% | 1% |
| Space refinement | 0.172347% | 0.5% |
| Remaining-time refinement | 0.002155% | 0.5% |
| Tail refinement | 0.023340% | 0.5% |
| Fixed-basis step-halving sensitivity | 0.228295% | 0.5% |
| Quadrature refinement | 2.47e-10 | 1e-5 |
| Rounded-residual error estimate | 6.59e-13 | 2e-10 |
| Interface probability-mass error | 5.55e-15 | 5e-11 |
| Locked unconditioned sequence continuation error | 0.087844% | 1% |
| Locked sequence mass drift | 6.22e-15 | 2e-6 |

All 325 distinct data gaps passed the interface checks. The fixed windows and
the predetermined refinement anchors passed their declared gates. These
refinement differences are empirical sensitivities, not additive certified
error bounds. The residual estimate is not a certified bound either. Step
halving compares fixed-basis resolvents; the actual data gaps were not
subdivided. A retained row-wise diagnostic reached **1.6974%**, with denominator
`max(1, ||continuum basis U||_inf)`, not each row's own value. The common prior's
passing result does not qualify every basis row or arbitrary initial state.
Observation-conditioned neural posteriors, long contexts, a trainable
physics domain and alternative reset laws still need their own qualification.

## What the real-data runs established

The official UCI localization data retain the original integer timestamps,
subject identifiers and source rows. A fixed whole-file integer clock model
exactly explains all 164,860 displayed dates. It corrects the original guard's
use of a per-record quantization tolerance for an adjacent difference. It does
not establish that the data authors used SQL or .NET. The original rejected
attempt remains in the first evidence snapshot.

The 18 runs used the same frozen 25-dimensional frontend, unchanged A01 first
128 training events, D01 first 64 development events, and four 32-event training
episodes. Each run started with fresh model and optimizer state. Official CfC
received real elapsed times. Official recurrent PLIF and S4D-Lin used their
declared event-indexed dynamics plus the common elapsed-time feature. S4D is
the SSM arm; it is not named Mamba. Attention was causal. HCSN physics stayed
frozen and matched the new numerical receipt.

An independent audit checked all 90 checkpoints, the 18 logits/result records,
the actual changed tensors at 72 optimizer updates, independent initialization
identities, source rows, frontend features, loaded dependency hashes, and frozen
HCSN physics. All **528 checks passed**. A separate final read verified all
36 live source files against the source archive. Metrics were recomputed from
saved logits without further training or model forwards.

The run also exposed concrete reasons it cannot support comparative effects:

| Interface | Trainable parameter count |
| --- | ---: |
| GRU | 427 |
| Official CfC | 807 |
| Official recurrent PLIF | 176 |
| Official S4D-Lin | 335 |
| Causal Transformer | 1,179 |
| HCSN | 9,804 |

The training window contains 122 walking and six sitting-down events. All 64
development events are walking. Eight of the PLIF's 12 training windows have
zero spikes. Four updates, these unequal capacities, and a single-class
development window cannot establish adequate SNN training or a model ranking.
The three independent initializations are real; they do not remove those
limitations. Episodes are not additional independent fits.

The E subject's raw records were read for schema, clock and global-gap metadata,
but never used for model training, tuning or scoring. The 0.2-second delay was
chosen after that global metadata audit. A subsequent ABC-only audit finds the
same maximum gap, 0.162175 seconds, in C02; this does not rewrite the selection
history as ABC-only. The prospective formal protocol must preserve that
disclosure when interpreting E as a held-out scoring subject.

## Costs, CI, and remaining work

The actual interface driver took 175.057531 seconds; suite and worker times have
separate scopes in the evidence. These include imports, construction and
checkpoint I/O and are not steady inference throughput or p99 measurements.
Peak worker RSS was 625,102,848--782,454,784 bytes. Persistent state bytes,
steady throughput, p99, peak VRAM and complete system energy remain `null` with
reasons. A CPU execution does not count as a measured zero GPU-memory peak.
Setup failures, numerical qualification and evidence transport have separate
receipts and are not hidden inside the training total.

The [formal protocol](../../proposals/localization-v2/formal_protocol.json)
specifies full subject-separated data, capacity matching, equal tuning
opportunities, adequate training, independent confirmation seeds, calibration,
requested ablations and an all-attempt resource ledger. The accompanying
[implementation boundary](../../proposals/localization-v2/PROTOCOL.md) explicitly
lists the missing constructors, dynamics, numerical domains and formal runner.
It is a specification, not a completed study. In particular, a matched ordinary
dual gate and a true physical-readout removal must expose a content-only or
ordinary-gating explanation rather than assume that either explanation is false.

The pinned hosted science workflow discovers the current tests and enforces the
four original budget fixtures. Native 0.2-second/data-interface evidence is
separately identified; that profile is not silently credited to the hosted lane.
Hosted source head, tested tree and actual job outcomes must be read at their
exact run. Historical repository-wide required checks remain HOLD until actual
fresh checks establish otherwise. No merge or main modification is included.

The separate Colab attempt never bound a runtime or executed qualification;
its cleanup is unconfirmed after the recorded account-manager state error.
No old S81 or 170-run campaign receives completion credit. FP32, mixed precision,
GPU kernel work, long-gap strategies and HCSN-plus-attention pretraining remain
gated on a fair real-task benefit; this interface exercise supplies no such
benefit claim.
