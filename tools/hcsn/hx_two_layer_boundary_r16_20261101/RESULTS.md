# Results: two-layer continuous margin and time-conditioned boundary

The frozen experiment passed its local functional gates. It demonstrates an
actual changing downstream boundary and a nonzero financial conditioning path
through first-order BPTT. The ordinary drive path carries a much larger upstream
gradient in this fixture. These results do not establish useful spiking,
generalization, a multimodal architecture advantage, or a new financial PDE
solution.

## Execution identity and chronology

The eleven scientific files were frozen at 2026-11-01 18:35:36.337920 UTC.
The protocol SHA256 is
`da07c580e258f51517f124d6d7b902a8ae3c6700fb58cb96948c18447c740ad7`.
The remote checkpoint was commit
`76f6e91285ff25926eda2c7bf57f70e99431c6ec`, timestamp 18:37:20 UTC.
The first local audit process launched at 18:39:19.108027 UTC; its first
financial evaluation began at 18:39:20.134955 UTC. The checkpoint therefore
preceded the first new evaluation. All frozen source and input hashes matched
before and after execution.

Audit, twelve-update training, and the independent result checker each returned
actual exit code zero. Their complete logs and execution receipts are retained.
An independent review also recomposed the records without Torch or new financial
calls and passed 69 comparisons under the original tolerance. No model source,
fixture, or numerical gate was changed after opening the results. Future CI
execution on these cases is a regression, not a new holdout.

## Four gradient routes

All four graphs have identical forward states, readouts, represented assets,
financial parameters, and boundaries. Only their interlayer derivative edges
change. The terminal loss reads the second layer's physical z and adaptation.

| Gradient graph | First-layer raw gradient norm | Second-layer raw gradient norm | First upstream drive VJP norm |
|---|---:|---:|---:|
| Both routes active | 4.4444966042e-4 | 7.4499921761e-4 | 4.5943317663e-4 |
| Drive only | 4.4061238438e-4 | 7.4499921761e-4 | 4.5714131258e-4 |
| Financial conditioning only | 3.8373086937e-6 | 7.4499921761e-4 | 2.5118314186e-6 |
| Both routes detached | 0 | 7.4499921761e-4 | 0 |

The full first-layer gradient matches the sum of the two separate routes. The
downstream gradient is invariant across all four graphs. Upstream initial-state
and external-drive gradients vanish when both links are detached. The earliest
first-layer theta node still has terminal VJP norm 3.4826784370e-5 when only the
financial conditioning route is active, verifying real temporal connectivity.

The conditioning-only gradient norm is 0.8709035% of the drive-only gradient
norm, or 0.8633843% of the full gradient norm. These are vector norm ratios,
not causal fractions of training benefit. This fixture demonstrates a live
financial route while the ordinary drive route has the larger local gradient.

The direct b1 boundary contribution is separately recorded using
`-b1_theta/b1`, the parameter-map derivative, downstream financial derivative,
Euler step, and reverse adjoint. Its time-resolved [16,9] norm is
9.8696457644e-7; the net time-summed vector norm is 3.8363549214e-6. The remaining
conditioning state-history vector norm is 9.6905565573e-10. The required gate
was the time-resolved norm; the nonzero net sum here is an observation, not an
extra acceptance condition or evidence of task benefit.

All 28 named temporal comparisons passed. Their largest absolute discrepancy
was 2.1365152668e-9, with largest error divided by its frozen pointwise allowance
0.01330064. The independent checker also checked actual theta-node VJPs and
their raw-parameter credit. Every four-mode 18-entry raw gradient, every
per-time credit, local Jacobian, adjoint, and direct-boundary decomposition is
retained in the complete audit; the four 18-entry vectors also appear in
`RESULTS_SUMMARY.json`.

## Boundary movement and default saturation

The first boundary is constant during a rollout but changes between optimizer
updates. The second boundary varies during the actual sixteen used steps, not
only in the final logging call. Every one of the eight samples showed a nonzero
used-step boundary range.

| Quantity | Initial rollout | Final rollout |
|---|---:|---:|
| Constant b1 within rollout | 67.4415143018 | 66.4538184645 |
| Minimum b2 over all 17 logged states and 8 samples | 67.4034548473 | 68.3583957416 |
| Maximum b2 over all 17 logged states and 8 samples | 67.4906688551 | 68.4182233354 |
| Minimum per-sample b2 range over 16 used steps | 0.0030726736 | 0.0023992322 |
| Maximum per-sample b2 range over 16 used steps | 0.0210939927 | 0.0188187309 |
| Layer-1 default states, out of 136 logged states | 78 (57.35%) | 60 (44.12%) |
| Layer-2 default states, out of 136 logged states | 51 (37.50%) | 53 (38.97%) |
| Layer-1 sampled phase changes | 6 | 4 |
| Layer-2 sampled phase changes | 0 | 1 |

Default classification uses the actual represented asset and raw boundary,
`V <= b`. Default states retain Q=0 and R=1. Downstream saturation remains and
increases slightly after training. More or fewer sampled phase changes do not
prove regenerative spiking; these are discrete samples of input-driven Euler
trajectories. No exact crossing times, autonomous cycles, or convergence in
step size were measured.

## Training and cost observations

The only trainable values were raw_theta1[9] and raw_theta2[9]. All eighteen
entries changed. Their total update norms were 0.7170200152 and 0.7166894219.
Initial states, rest references, gains, inputs, and targets remained fixed.
There was no trainable head and no direct margin or boundary term in the loss.

The same eight synthetic training sequences produced loss
0.017321569845080376 before training and 0.016821451485157013 afterward, a
2.8872577047% decrease. All twelve intermediate losses, parameters, gradients,
effective per-time financial parameters, and represented trajectories are
retained. The loss reduction was not a pass condition. There is no validation
set or comparison establishing that the financial mechanism caused useful
learning. This broader initial-state family and two-layer dynamics differ from
the earlier nearly flat single-layer experiments; their loss scales and
saturation findings must not be compared as a controlled improvement.

| Local CPU operation | Internal wall time | Full process wall time | Financial calls / attempted rows |
|---|---:|---:|---:|
| Four-mode audit and wrapper contracts | 0.4629 s | 2.2839 s | 171 / 1359 |
| Twelve updates plus final rollout | 0.6432 s | 4.1323 s | 442 / 3536 |
| Independent record checker | not separately timed | 0.2615 s | 0 / 0 |

The audit row counter includes a deliberate five-row invalid-maturity contract
batch; 1359 is not a count of successful financial rows. The numerical core is
the frozen FP64 C++ financial implementation with FP32 neural inputs and state.
These timings are descriptive local CPU measurements, not speed comparisons,
GPU measurements, or energy evidence.

The record checker independently composes the four audit chains from archived
financial values/Jacobians. It verifies all twelve parameter-update links and
finite training gradients, and binds the first training gradient to the audit.
It does not independently replay the other eleven gradients or Adam. The
financial values/Jacobians are from the same frozen kernel, not a second
financial oracle. The final checker source also passed 23 non-financial
synthetic controls; its earlier 19-control runs and distinct source identities
are retained in the independent checker evidence.

## Complete archive and reproduction

The original audit is 639,504 gzip bytes, SHA256
`8ff233b9045b96ff846d146acc94e9daa6e066f7a9137204bcbc6cb89e8be7c3`.
It is published as two exact contiguous byte parts (320,000 and 319,504 bytes)
to respect the single-blob size limit. No arrays were deleted, reformatted, or
recompressed. `AUDIT_ARCHIVE.json` binds the parts and original byte identity.
The reconstructed artifact was checked byte-for-byte against the original.

```sh
python -B materialize_audit.py --root CANDIDATE_DIRECTORY --output NEW_DIRECTORY/TWO_LAYER_AUDIT_V1.json.gz
python -B check_two_layer_results.py --root CANDIDATE_DIRECTORY --protocol-sha256 da07c580e258f51517f124d6d7b902a8ae3c6700fb58cb96948c18447c740ad7 --audit NEW_DIRECTORY/TWO_LAYER_AUDIT_V1.json.gz --training CANDIDATE_DIRECTORY/TWO_LAYER_TRAINING_V1.json.gz --financial-root FINANCIAL_CAPSULE_DIRECTORY --output NEW_DIRECTORY/CHECK.json
```

The training artifact is 453,637 bytes, SHA256
`33049a15099c3e8634b0a5575f63040ead4031d90c5e0a6f4697600b5cf794a9`.
The independent result check is SHA256
`926f4f595b8bcd5b336c19575f903294b3cae0ce0f1bd69011f5d88db03e9dfb`.
The create-only materializer verifies every part and the complete output before
writing. The README gives the three fresh-run entries and their exit semantics.
`summarize_results.py` derives the descriptive JSON from these complete records
without evaluating a new model or financial point.
