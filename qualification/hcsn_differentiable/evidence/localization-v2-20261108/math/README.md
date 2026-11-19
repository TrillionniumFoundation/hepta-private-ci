# Localization v2: independent frozen-physics numerical admission

This proposal changes the deterministic refractory duration from 0.1 s to
0.2 s. That is a different physical model. It preserves the original event
clock and the already selected A01/D01 windows; it does not inherit the older
0.1 s candidate's qualification.

## Exact proposed profile

- `active_cells=128`, `endpoint=2.4`, `phase_cells=16`, `refractory=0.2`,
  `tail_rate=1`, `quadrature_order=32`, `initial_log_std=0.08`: 145 states.
- The original `TrainablePhysics` is instantiated with its defaults:
  `mu=-0.12`, `sigma=0.35`, `log_boundary=0`, `log_absolute_reset=0.32`,
  `discount=0.15`, and then frozen. The receipt records the actual resulting
  FP64 tensor values as hexadecimal floats, including transform rounding.
- The absolute initial value is `exp(0.55)`; the original conditioned Gaussian
  law and its represented-basis counterpart are reported separately.
- Each elapsed time is **integer tick difference divided by 10,000,000**.
  There is no clipping, subdivision, resampling, changed time scale, or removal
  of a long-gap example. A simultaneous event has zero elapsed time.

## Gates locked before CPU execution

| Measurement | Limit |
| --- | --- |
| Common-prior perpetual U error, scaled by max(1,abs(reference)) | 0.01 |
| Space, phase, tail, and time refinement delta | 0.005 each |
| Quadrature refinement delta | 0.00001 |
| Rounded linear-solve residual error estimate | 2e-10 |
| One-step row mass error | 5e-11 |
| Unconditioned sequence mass drift | 2e-6 |

All exact gap values in A01's first 128 and D01's first 64 events are included.
All 325 distinct gap values in the pinned full archive receive a positivity
and mass interface audit. Only gap metadata are used from other sequences;
there is no fitting, label scoring, or holdout model evaluation.

The refinement anchors are fixed order statistics, selected before observing
any numerical result: the positive locked-gap minimum, middle, and maximum,
and the full archive's 95th, 99th, and 100th percentile gaps. Duplicate anchors
are evaluated once. Refinement differences are sensitivity measurements, not
independent error contributions or certified error bounds.

Four original 32-event training schedules, the complete 128-event A01 prefix,
and the 64-event D01 prefix receive an unconditioned continuation check:

`accumulated running/event reward + exp(-rho*T) * p_T @ continuum_basis_U`

is compared with the same initial law's analytic perpetual value. The terminal
continuation is included once. No observation filtering or neural content
writing is applied during these numerical checks.

## What a passing receipt admits

A passing `hcsn-localization-v2-budget-result-v1` receipt must have status
`passed_locked_frozen_profile`, every gate true, and unchanged source hashes.
It supports a bounded interface experiment with this exact frozen physical
profile, grid, and fixed A01/D01 selection. It does not establish a learned
physical parameter domain, full-dataset numerical fidelity, six-model causal
superiority, or a universal long-sequence error guarantee.

Observation likelihoods and neural content updates can amplify transport
errors. The model's likelihood also depends on the transported physical
channels; bounding its output range does not bound the complete feedback
map's sensitivity after training. A per-interval QPR budget therefore cannot
be multiplied or summed into a claimed end-to-end filtered error guarantee.
Training other physical parameters or extending the input/sequence scope
requires another declared numerical qualification.

The CPU probe uses one thread, a 300-second wall budget, a 2-GiB RSS budget,
and no CUDA. It starts no training fits and reports no model effect, speed,
GPU, or energy qualification. Failed or incomplete attempts remain retained;
limits are not widened after the result.
