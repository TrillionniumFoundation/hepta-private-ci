# PRED crossed train/development diagnostic 003

## Scope fixed before execution

This is a new development diagnostic, not a third confirmation campaign.
Both previously used confirmation sets remain sealed. The historical 16-seed
result and its original utility/p-value requirements remain HOLD. No result of
this diagnostic can change that decision or select a new confirmation winner.

The integrated base is `885dae0f3285267e9e9c49d8b43b0d009779f9e8`.
Its static training diagnostic is preserved. The preparation planner missing
from that integrated tree was imported with its exact #5412 blob identities
before the new Fixed1 changes. The execution source is
`d5f30f0a15af065281f80a10e4cbc210af07b8fb` (#5480), with the complete imported
source closure separately hashed in `FREEZE.json`.

## Design and denominators

Three data seeds, three initialization seeds and three permutation seeds form
a complete 3 × 3 × 3 grid. Seeds are derived from the declared SHA256 namespace
without observing outcomes and exclude both used confirmation campaigns,
their selection seeds and previously exposed preparation pilots.

Seven variants are fixed: single-step MLP, GRU, simple diagonal SSM,
dual-timescale recurrence, GRU reset, GRU without action, and GRU without
explicit clock/lag features. This is 189 separately executed fitting operations, but
not 189 or 27 independent confirmation units: factor levels are reused.

The original optimization settings are retained: 4096 training and 512
development episodes per data seed, 16 history rows, 30 epochs, batch 128,
approximately 3000 parameters, learning rate 0.003. Each fit consumes the
whole budget; minimum development observed-label NLL selects its checkpoint.
The selected epoch does not replace consumed training cost.

- Unique generated training episodes: 12,288 across three data realizations.
- Unique generated development episodes: 1,536 across three data realizations.
- Planned fit-step calls: 181,440 across 189 fits.
- Planned training example presentations: 23,224,320.
- New confirmation episodes generated or read: zero.

Initialization and permutation streams have separate seed inputs. Every fit
records initial parameters, the complete batch-order digest, selected numerical
parameters and full optimizer state. Checkpoint bytes are saved and read back.
Raw curves, actual counters, resource panels, failures and model identities are
retained. A failure cannot trigger a replacement seed or be dropped from the
denominator. Only a complete unchanged-source grid gets a factor decomposition.

## Fixed analyses

For each model, decompose development NLL, legacy fixed-horizon utility,
expanded-resource Fixed1 utility and legacy adaptive-panel utility into the
three main effects and all four interactions. Use finite-grid squared
variation, marginal means and paired GRU differences. Do not report the cells
as independent replicates, attach sign-flip p-values, infer population variance
components, or declare promotion. If interactions dominate, do not label one
main factor as a sufficient explanation for instability.

Action ablation removes both historical actions and candidate identity.
Clock/lag ablation removes explicit elapsed/index columns and pools the four
delay-specific sensor slots; sequence order and missingness remain observable.
Reset removes both prior simulator history and its accumulated recurrent
state. The separate receipt encoder supports a distinct latest-event/history
ablation, but these fits still use the original 16-dimensional simulator.

## Costs and the resource intervention

The default full-support planner cannot take an action under the original
resource generator when prediction has positive cost: budget/deadline never
exceed 8, the registered terminal maximum. Preserve that all-STOP result.
An additional development panel fixes remaining budget to 16 and deadline to
20 on the same outcomes. This is a declared resource intervention, not a new
independent task or a change to any old confirmation dataset.

Fixed1 encodes the observed prefix once and evaluates only legal horizon-1
heads. Shared-panel comparators retain all 12 forecasts and their repeated
history work. All choices freeze before evaluator access. The six simulated
rates are explicit in the configuration; rates for a model state step/head
are not equal FLOPs across architectures. Report actual operation counts and
measured CPU/wall time separately. Validation, admission, transport, training,
energy and currency are not fully monetized. `physical_cost_complete=false`.
Declared prediction delay does not advance the hidden environment state.

The old full-history Bayes posterior is a common diagnostic reference, not an
information-matched oracle for ablated inputs. This experiment evaluates
direct preparation-option forecasts, not autoregressive latent rollouts.

## Execution and cloud readiness

Configured Colab/Kaggle CPU evaluation was requested through HeptaRuntime
first. The original stable request did not return a durable job ID, and a
same-key reconciliation timed out. A later read-only search was refused for
SSH admission capacity; its no-child result applies only to that search.
Account readiness therefore remains UNKNOWN, not unavailable or allocated.
No cloud training/allocation was requested. This small NumPy diagnostic is
executed on the current CPU with its actual environment and outer exit/time
receipt. Do not substitute a cloud or GPU execution claim.

The outer receipt records process exit, source/config identities, log hashes,
elapsed time and child resource use. A RUNNING attempt without terminal
RESULT is not a completed campaign. All artifacts are create-only.

## Next evidence required for promotion

Real owner action histories must be collected and joined to frozen earlier
inputs; this structural adapter does not authenticate their origin. New
independent tasks, strong cost-matched baselines, complete physical costs,
readback-driven replanning and a separately frozen confirmation design are
still required. A prediction-loss improvement alone is not decision benefit.
Longer planning requires measured task value and calibration, not low latent
ensemble disagreement alone.

Research anchors: [DreamerV3](https://www.nature.com/articles/s41586-025-08744-2)
and [Biased Dreams](https://rlj.cs.umass.edu/2026/papers/Paper13.html).
