# HCSN P0–P6: reproducible exploratory gate report (2026-10-31)

## Honest status

**No P0–P6 phase is fully scientifically closed. Production activation is disabled.**

P0: Implemented a **simplified HX-inspired one-shot** perpetual stopping kernel, stable near-boundary evaluation, algebraic value-matching and smooth-pasting checks, an independent finite-difference continuation-domain comparison, and a bounded admissible parameter domain.  This is **not** the original He–Xiong coupled rollover-risk solution, nor a regenerative multi-reset QVI, nor an FP32/all-domain certification. Therefore P0 remains OPEN.

P1: Five variants have been exercised (`call_only`, `put_only`, `margin_only`, `dual_call_put`, `ordinary_two_gate`) with matching 161 active trainable parameters, 512 synthetic training samples per seed, 90 Adam updates per seed, seeds 11/23/37, 300 ID and 300 OOD episodes per seed. These are exploratory, not independent preregistration; input transforms, local slopes, kernel FLOPs and calibration have NOT been matched. On the available study the ordinary two-gate baseline is stronger than the analytic dual. Therefore P1 remains OPEN.

P2: Synthetic Bayesian information-acquisition/physical-read task and deterministic replay checks only; no Selective Copy, MQAR, longer sequence benchmarks, irregular time, or complete regenerative reset implementation. OPEN.

P3: No verified comparison against real text/audio/image/video encoders, Transformer, Mamba, or SpikingSSM. OPEN.

P4: No multimodal alignment, retrieval or missing-modality heldout benchmarks. OPEN.

P5: CPU process-time observations exist for a tiny synthetic task. No GPU benchmarking, power measurement, fusion kernels, CDF approximation, peak RSS, throughput or p99 resource benchmark. OPEN.

P6: No medium-size encoder, distillation, continued pretraining or scaled context benchmark. OPEN.

## Exploratory mean across 3 seeds (lower regret better)

| Variant | ID exact regret | OOD exact regret | ID mean utility | OOD mean utility |
| --- | ---: | ---: | ---: | ---: |
| Call-only | .03682 | .04781 | .74249 | .74485 |
| Put-only | .00712 | .00997 | .76588 | .78581 |
| Margin-only | .00980 | .01728 | .77327 | .77699 |
| Dual Call/Put | .00564 | .00790 | .76997 | .78362 |
| Ordinary two-gate | **.00238** | **.00244** | **.77411** | **.79103** |

**Interpretation:** These runs do not establish any HCSN advantage. The conventional comparison wins on regret in both ID/OOD. Small synthetic episodes and the uncontrolled transforms prevent making a causal superiority claim.

## Run

From `/mnt/data` (Python and `torch` installed):

```sh
python -m unittest discover -s hcsn_p0_p6_20261031 -p 'test_*.py' -v
```

The 18 tests pass in the available CPU environment on 2026-10-31. Test success is not full model certification. See `math_kernel.py`, `test_math_kernel.py`, `boundary_content_bridge.py`, `train_study.py`, `study_results.json`, `panel_id.json` and `panel_ood.json`.

## Next execution priority

1. Implement coupled original HX Eq. (8)/(12)/(A7) with independent reference and adversarial parameter sweeps; add genuine regenerative QVI solver and reset event semantics.
2. Pre-register task splits and sloped/compute-matched controls; use independent heldout test and report confidence intervals, negative transfer and wall-clock/FLOPs.
3. Implement Selective Copy, MQAR, joint recall, irregular-time and multi-reset tests before claiming temporal-memory improvements.
4. Only advance to frozen real encoder comparisons, modality alignment, hardware and scaled training after P0/P1 evidence supports it.

## 2026-10-31 subsequent execution: finite-state regenerative QVI

Added `regenerative_qvi.py` and `test_regenerative_qvi.py`. The discrete
continuous-time Markov-chain generator on log(V) uses a monotone nonnegative
rate stencil with explicitly reflecting truncation endpoints. The intervention
operator resets to a fixed grid state at positive cost. Policy iteration checks
`max{(Q-rI)U+f, U(reset)-cost-U}=0` with independent ex-post residual.

Five extra unit tests verify generator conservativity/nonnegative jump rates,
Bellman complementarity, parameter rejection, repeated intervention semantics,
and a two-mesh convergence comparison. Total suite: **23 tests PASS** in
this session. This is a standalone **finite-grid impulse-control construction**, 
NOT a solution of the original He-Xiong rollover/debt-coupled model. Mesh
refinement 401->801 gives max interior value difference ~0.08936 in the
chosen parameters. In an earlier, stricter 201->401 comparison max interior
error was ~0.15546; it was not silently classified as closed. The
`reset_path` test feeds independently given state indices, not a simulated
full time-integrated path; no production reset event semantics are proven.

**P0 is still OPEN**: original HX coupled equations, independent reference,
true continuation process with recurrent path resets, smooth pasting for
continuous QVI, parameter sweeps and FP32/BF16 limits are incomplete. All
P1-P6 remain OPEN. Production activation is disabled.