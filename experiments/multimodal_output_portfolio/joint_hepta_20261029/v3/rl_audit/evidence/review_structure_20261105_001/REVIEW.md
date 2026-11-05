# Independent raw arithmetic and checkpoint replay

Source publication: `062b6dd7c730c4795ae617f4c85278dd2ac821d7`.
Input: `../run_20261105_001/structure/run/`.
This reviewer did not import the experiment implementation or rerun training.
It independently evaluated the declared quality, Gaussian expectation, legal
actions, fees and saved neural/polynomial checkpoints from the retained arrays.

## Verification outcome

All **41,761 checks** passed, with no unexpected numerical or record anomaly:

- All 55 panel/seed shards and 660 unique arm records match the frozen roster.
- All 480 fitted checkpoints have the recorded byte digest and common-data digest.
- All **82,560 completed decisions** replay exactly from checkpoints/references.
- There are 645 completed records and 15 explicitly unidentified zero-noise Z records.
- All 150 positive-noise direct-gradient/Z pairs choose identical actions.
- The largest direct/Z gradient discrepancy is `6.23945339839338e-14`.
- The largest raw quality or expected-net arithmetic discrepancy is
  `2.220446049250313e-16`; fee and latency-percentile arithmetic agree exactly.
- Value/gradient calibration and finite-difference curl summaries are reproduced.

Timing summaries were recomputed from the recorded clocks. Their physical
measurement, training execution and administrative provenance were not independently
reestablished by this reviewer. Source publication binding is checked against the
retained registration; separate GitHub readback establishes remote publication.

## All panels: regret relative to the exact legal one-step policy

Each number is a descriptive mean across all five fitted seeds; smaller is better.
The comparison uses the mathematical task objective, without a CPU-to-utility tariff.
The quadratic value baseline is shown consistently across every panel. This
displayed baseline was selected for descriptive review; the original protocol
listed all model families without registering a primary learning-method contrast.

| Panel | Quadratic value | Linear direct gradient | Neural direct gradient | Neural value |
| --- | ---: | ---: | ---: | ---: |
| base | 0.000094109896 | 0.00017424271 | 0.00015188047 | 0.010866211 |
| noise_zero | 0.00013506163 | 0.00022869724 | 0.000056911928 | 0.0087163692 |
| noise_small | 0.00013506163 | 0.00022869724 | 0.000056911928 | 0.0087163692 |
| noise_large | 0.0018520618 | 0.00065165640 | 0.0012266655 | 0.015892749 |
| dimension_four | 0.00048007747 | 0.00018451973 | 0.00041815836 | 0.0052690302 |
| adjustment_high | 0.000047297378 | 0.000070049971 | 0.00010999367 | 0.0028625530 |
| complementarity_zero | 0.00011835407 | 0.000036755276 | 0.00019816763 | 0.017957675 |
| resource_residency | 0.000064666042 | 0.000016812489 | 0.000083690339 | 0.0012697502 |
| model_error | 0.016788798 | 0.017737872 | 0.017017987 | 0.039793600 |
| reset_always | 0.00017699915 | 0.00019395997 | 0.00019512996 | 0.011074968 |
| reset_never | 0.000094109896 | 0.00017424271 | 0.00014819221 | 0.010219975 |

### Implications within this experiment

The ordinary quadratic value critic is already close to the exact reference in
the base panel. A direct-gradient representation has no uniform advantage over
it: panel means and within-panel seed differences change sign. Even in the
large-noise panel, the neural direct-gradient mean is better but only two of five
seed differences are positive. The full paired differences are in `REVIEW.json`.

The fitted neural value critic is worse than the quadratic value critic in all
five seeds of every panel. This is a negative result for this registered training
configuration, not an impossibility result for better neural training.

The model-error intervention increases the three primary critics' regret from
approximately 0.00009–0.00017 to 0.0168–0.0177. Changing the critic representation
does not remove the common biased observation model. Gradient calibration is
also not sufficient for action quality: in the base panel the linear gradient
critic has lower gradient MSE than the quadratic value critic, but higher regret.

Positive-noise Z rescaling produces identical decisions throughout. Low noise
does not create a learned direct-gradient advantage in this equal-information
rescaling experiment. The singular zero-noise case stays unidentified; the
separate absolute-error sensitivity example is not a competing learning result.

## Cost interpretation

Base-panel mean recorded training CPU is 0.292 ms for quadratic value, 0.227 ms
for linear direct gradient, and 10.194 ms for neural direct gradient. The last
also has 62 fitted parameters versus six in each of the first two. Targets,
effective degrees of freedom and training work differ despite common observations.

Recorded neural inference can be faster in this implementation. The polynomial
feature routine also constructs an unused Jacobian during forward-only inference;
these measurements do not establish an optimized neural efficiency advantage.
All measurements describe this small NumPy probe. Complete physical net gain,
matched-compute efficacy, full RL/rsEAC comparisons and new-task or future-window
benefit remain unestablished.

## Reproduce this review

From the repository root:

```bash
python experiments/multimodal_output_portfolio/joint_hepta_20261029/v3/rl_audit/evidence/review_structure_20261105_001/audit_structure.py experiments/multimodal_output_portfolio/joint_hepta_20261029/v3/rl_audit/evidence/run_20261105_001/structure/run NEW_REVIEW.json --source-commit 062b6dd7c730c4795ae617f4c85278dd2ac821d7
```

The output path must not exist. This command reads retained records and performs
checkpoint inference; it neither modifies the source/evidence nor retrains models.
