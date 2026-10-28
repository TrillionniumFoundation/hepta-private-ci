# Independent review of native whole-trajectory gradients

The corrected `native-joint-gradient-002` diagnostic passed this review under
profile `20adfb58197901642bf7281e9ff8a27426480588d34b70a48af7f377f99c4727`.
The authoritative output is
[NATIVE_JOINT_GRADIENT_INDEPENDENT_REVIEW.json](results/NATIVE_JOINT_GRADIENT_INDEPENDENT_REVIEW.json);
the reproducible reviewer is [native_joint_review.py](native_joint_review.py).

This is an implementation and accounting check. The native controller, readout,
calibration, and authority remain fixed. Eight updates on original training
sources and four original-development deployments do not establish improved
quality, optimal allocation, generalization, observer adequacy, or a tail bound.

## What was checked

| Check | Result |
| --- | --- |
| Original training trajectories reconstructed | 16 |
| Their actual sampled four-modality emissions reconstructed | 20 |
| Updates with exact original preclip gradient records | 8 of 8 |
| Modules with nonzero gradients at every update | 13 of 13 |
| Raw module-gradient records reproduced, including SHA-256 | 104 of 104 |
| Final development deployment receipts independently checked | 4 |
| Original trajectory log-density replay discrepancy | 0 |
| Maximum independent normalized-density gradient relative L2 discrepancy | `1.6611886505115983e-7` |
| Maximum independent gradient element discrepancy | `2.002716064453125e-5` |
| Maximum independent normalized joint log-density discrepancy | `0.015625` |
| Neural forward replays performed by this review | 40 |
| Additional native executions, media deliveries, private reward calls, or updates | 0 |

The independent normalized density has a different float32 reduction order;
its small absolute log-density discrepancy is reported explicitly. This does
not replace the exact sampled-action hashes and byte-for-byte original gradient
comparison. The reviewer requires every parameter to agree within declared
float32 tolerances and total relative gradient error below `2e-6`.

## Method

1. Verify the frozen protocol/profile/source chain and each current parameter
   snapshot. Bind vocabulary, policy, native host receipt, and final deployment
   tensors to their declared hashes. Reopened file hashes must match the actual
   episode receipts. Archive paths are resolved relative to each original
   episode scope, allowing the archived run to move without rewriting receipts.
2. Check that each trajectory contains one initial sample and exactly the
   actually executed retry, if admitted. Retry RNG state must advance from the
   first draw; the sampled tensor hash must differ. Stopped or refused retries
   cannot contribute an unexecuted score. Private scoring must occur after the
   original owner closes.
3. Reconstruct the original sampled tensors from the frozen public arrays,
   snapshot, and recorded seed. Require exact sampled bytes, RNG states,
   emission/trajectory log densities, and the original preclip gradient records.
   These replays reproduce old random realizations; they add no statistical
   observations or qualification sources.
4. Hold those actions fixed and independently use normalized
   `torch.distributions.Normal` and `Categorical` densities. Differentiate their
   full trajectory sum through every current neural parameter and compare with
   the original gradient tensors. The native controller itself is not trained.

For the two-trajectory batch, the differentiated loss is

```text
(mean_k expm1(-gamma * R_k) / gamma - previous_batch_baseline)
    * sum_k sum_actually_executed_emissions log p_theta(action | history)
```

Parameters remain fixed until both trajectories have ended. The prior-batch
baseline is independent of current action draws. Keeping the joint score retains
cross terms if observed costs couple trajectories; the mean already divides by
the batch size. Fresh retry sampling is essential: replaying the same latent
and counting its density twice would give an incorrect gradient.

## Complete deployment charges and the retired attempt

All 20 original training/development episodes are checked for unique cost IDs
and exactly one charge for each of per-episode public-input/policy preparation,
current-snapshot binding/verification, and post-stop readback/private scoring.
Native kernel, generation, delivery, refused proposal, CPU, and wall charges are
recomputed from their recorded physical counters and frozen tariffs. Failed
outputs retain their original sampled-action scores, zero declared gross utility,
and all incurred charges.

The corrected run records `16.383601427` CPU-seconds in its episode returns,
including `0.348375` CPU-seconds of per-episode preparation. Its one-time loading,
training/backward, checkpoint writing, and diagnostic reporting are separately
recorded outside deployment returns. The earlier `001` attempt omitted the
per-episode preparation charge and is retired. Its mathematical replay pass is
preserved and does not constitute complete-billing acceptance.

CPU realizations are treated as conditionally exogenous in this likelihood-ratio
model. Direct parameter derivatives of platform runtime are not estimated.
Variable CPU also has no declared finite future support, so this diagnostic
issues no distribution-free tail certificate. Natural semantic qualifications
and their earlier failed gates remain unchanged.

## Reproduce

Use the frozen source bundle and recorded CPU Torch environment. With the
original source arrays and an extracted completed `002` run:

```bash
python -B -m experiments.multimodal_output_portfolio.unified_20261028.native_joint_review \
  --run /path/to/native-joint-gradient-002 \
  --assets /path/to/natural_assets \
  --output /path/to/new-independent-review.json
```

The reviewer refuses to overwrite an existing result and rejects source,
snapshot, public-array, billing, or density mismatches. No original owner process
is started, and no checkpoint, historical profile, or qualification result is
modified.
