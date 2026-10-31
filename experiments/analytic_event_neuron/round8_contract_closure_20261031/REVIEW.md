# Independent experiment review

## Assessment before fresh confirmation

The calibration and control experiments now distinguish controller fitting from
cell transitions within a bounded, fully enumerated task. They do not establish
an intrinsic content-processing advantage of the analytic cell. The public task
state already includes the exact Bayesian posterior and the readout receives
all public features directly. That structural limit is stronger than a small
observed difference between cell families.

Reviewed modules: `protocol.py`, `control_exchange.py`, `gaussian_policy.py`,
`confirmation.py`, `heldout_exact.py`, and `analysis.py`. The calibrator and its
saved results also received the independent replay checks described below. This
review did not read new heldout results or select any candidate from them.

## Findings and dispositions

| Issue | Assessment and disposition |
| --- | --- |
| Public information and timing | All policies receive the same public `State`. Private truth and unread votes remain in `Episode`, which is passed only to the environment. STOP uses the pre-action posterior. The independent oracle enumerates legal successors; it does not hand future observations to the policy. |
| Shared encoder/readout exchange | Each exchange copies one anchor and changes only its stated transition contract. Brownian comparisons jointly set leak to zero across all three contracts. Comparisons are valid within that anchor/process; a Brownian versus R7 difference also changes the process and must not be called a pure event-mechanism effect. |
| Calibration target consistency | The readout encoder and the transition encoder are separate. Saved core, drive and kernel encoder are identical through both stages; all restored transition matrices are unchanged. Targets therefore remain the deployed fixed-cell Q*, rather than stale values from an earlier encoder. |
| Hard versus mean | Hard deployment propagates the realized internal state, samples its successor, observes that successor and chooses a greedy action. Mean deployment propagates the full law and maximizes expected readout values. These are distinct policies. The finite hard-policy exact DP is not an oracle for the mean policy. |
| Genuine unbounded endpoint control | `UnboundedGaussianPolicy` carries a scalar Gaussian mean/variance without clipping or tail folding. Hard deployment propagates its actual continuous sample. Mean propagation is exact for the stated constant-drift Brownian law; only the nonlinear readout expectation uses Gauss–Hermite quadrature. |
| Gaussian/probit degrees of freedom | Both implementations use the same law, weights, latent uniforms and action logic. Endpoint channel probabilities are diagnostic only. They are paired identity checks, not independent architectures or extra sample size. |
| Latent randomness | Keyed uniforms are common across paired arms and keyed by world/fit/regime and decision counter. This is a valid common-random-number coupling. It does not imply that clocked and first-passage trajectories share an explicitly reconstructed continuous Brownian path. |
| Heldout isolation | The calibrator imports only the original eight training configurations. New configurations and new world seeds are fixed by the protocol. No training or checkpoint selection uses their values. Old R7 confirmation informed this design and is correctly treated as development evidence. |
| Multiplicity | Initially, three contrasts were described across two regimes with a three-test correction. Before confirmation, this was corrected to six tests with 99.166667% intervals. All five fit-level differences must remain visible. |
| Sampling unit | `analysis.py` resamples the five complete paired fit/world blocks, enumerating all `5^5` bootstrap index tuples. Trajectories, internal states, stages and equivalent Gaussian/probit arms are not counted as independent fits. Five previously trained fits give limited inferential resolution; interval labels do not establish reliable finite-sample coverage or broad-task superiority. |
| Wire costs | Initially, the unbounded policy reported only action bytes while the finite policy included a state packet. Before confirmation, the unbounded packet was aligned to the same `<I5d` plus action format. Proxy event fees, measured process CPU and actual transport/IO costs must remain separate. |
| Frozen execution | Initial-only manifest verification could miss concurrent changes during a run. Confirmation and heldout exact evaluation were amended to verify the same manifest again at completion. Imported R7 dependencies and all candidate checkpoints must be included in the frozen dependency inventory. |

No remaining issue above prevents the declared bounded confirmation. The
following limits must accompany its results:

- The Gaussian control transfers a readout trained on finite cell states into an
  unbounded voltage domain. It is a useful fixed-readout intervention, not a
  separately optimized Gaussian architecture benchmark.
- `heldout_exact.py` evaluates hard deployment only. Mean-policy returns come
  from paired execution and retain their distinct decision rule.
- Numerical accuracy of a fixed finite matrix and its gradient is not continuous
  OU first-passage accuracy. R7's upwind numerical diffusion remains present in
  the R7 calibration/native family; the new Brownian kernel has a different,
  explicitly declared process and tick-level recovery contract.
- Recovery claims must name the tested implementation. The initial unbounded
  Python control provides a snapshot but does not itself define a restore API;
  native finite-cell recovery does not automatically certify it.
- The final 400-update checkpoint is retained even when a preceding stage or
  another fit has better return. No adverse seed is dropped or replaced.

## Calibration results available before new confirmation

The table reports the exact mean optimality gap over the original eight
configurations and all five registered fit seeds. Smaller is better. These are
development diagnostics under sampled internal state followed by greedy action.

| Family | R7 baseline gap | Readout-only gap | Content/readout gap |
| --- | ---: | ---: | ---: |
| Direct Q | 0.020285938 | 0.014598548 | 0.006234354 |
| Projected continuous | 0.023230705 | 0.014515503 | 0.009959484 |
| Clocked | 0.020557347 | 0.013580810 | 0.010236012 |
| First passage, R7 CTMC | 0.023629072 | 0.014726687 | 0.007926949 |

The direct controller improves substantially under the same repair. The gains
therefore cannot be credited exclusively to the analytic event cell. In this
development table, its final gap is smaller than every event-cell family's.
The content/readout stage changes the representation used by the Q head while
holding physical state dynamics fixed; it does not demonstrate improved content
addressing or successful joint learning of new cell dynamics.

Value regression and action quality are not equivalent. For direct seed 11,
readout-only weighted RMSE improves from 0.15731 to 0.07281 while its exact greedy
gap worsens from 0.02109 to 0.02490. Clocked seed 11's final gap, 0.02295, also
exceeds its baseline 0.02137. These adverse outcomes are preserved. The primary
diagnostic is the exact four-action optimality gap, which is independently
equal to the deployed-occupancy-weighted sum of optimal action regrets.

Uniform RMSE covers every legal action in all public/latent cells, including
states the deployed policy does not visit. The training-weighted RMSE uses the
fixed 45% baseline occupancy, 45% optimal occupancy and 10% uniform mixture.
The deployed-occupancy RMSE changes its weights with the policy. A lower value
under one measure need not improve the others or repair the action boundary.
All three measures are retained in each stage audit.

Configuration 4's incorrect initial WAIT is fully repaired for all five direct
controllers only after content/readout training. It is not uniformly repaired
across all other families. Configuration 7's mean gap decreases for every
family but remains positive. The experiment does not claim these failures have
been completely eliminated.

## Verification receipts

- All 20 fits completed the frozen 400/400 updates; total measured calibration
  process CPU was 100.015746 seconds. This includes per-fit setup and audits;
  stage-level training-only CPU is also retained.
- Four focused tests passed: frozen transition input despite readout encoder
  changes, zero-event-fee identity across every law, legal-action loss masking,
  and exact saved two-encoder execution round-trip.
- A subsequent saved-byte replay covered all 60 stage checkpoints and all 20
  static target archives. It rederived Q* from the original source model,
  verified original and candidate hashes, checked stage-specific frozen
  parameters, and reproduced the stage metrics. All checks passed; replay wall
  time was 5.353106 seconds.
- At zero event price, the independent scalar public DP and every joint
  public/latent optimum agree to floating-point roundoff. With positive price
  0.0002 and at most one event per tick, any cell's optimum differs from the
  no-event public optimum by at most 0.0012 for these horizons.
- The unbounded mean-policy quadrature check used 48 versus 96 Hermite points,
  five anchors, and 32 fresh development worlds per anchor. Across 693 shared
  prefixes, maximum Q difference was `4.440892098500626e-16`; all 160 action
  sequences were unchanged. These worlds use seeds
  `86000000 + fit_seed * 1000 + index`, not confirmation or heldout seeds.
  This is evidence for the evaluated readouts and states, not a universal
  quadrature error guarantee.

Relevant machine-readable receipts are `evidence/calibration_summary.json`,
`evidence/calibration_replay_audit.json`, the 20 per-fit calibration records and
target archives, and `evidence/calibration_gaussian_quadrature.json`.
