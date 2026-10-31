# Round 10: new CREMA-D offline recurrent experiments

30/30 newly executed jobs; 240 raw condition/logit reconstructions; all backbone and readout parameter blocks updated.

Three paired initialization seeds and eight historical heldout actors. The test cohort is reused; it is not a fresh independent confirmation cohort.

## Mean outcomes

| Budget | Model | Parameters | Full | No audio | No video | Shift4 | Recall32 | Recall96 | Complete CPU s |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| fixed | ordinary | 6654 | 0.2708 | 0.1632 | 0.3090 | 0.2535 | 0.1424 | 0.1441 | 1.736 |
| fixed | matched_c1 | 6654 | 0.2760 | 0.1979 | 0.3090 | 0.2778 | 0.1441 | 0.1441 | 1.912 |
| fixed | analytic | 6654 | 0.2899 | 0.1944 | 0.2986 | 0.2691 | 0.1528 | 0.1528 | 2.447 |
| fixed | cfc_matched | 6474 | 0.2014 | 0.1667 | 0.1701 | 0.1892 | 0.1788 | 0.1788 | 1.723 |
| fixed | cfc_same_width | 13230 | 0.1944 | 0.1840 | 0.1701 | 0.1840 | 0.1528 | 0.1528 | 2.290 |
| cpu | ordinary | 6654 | 0.2778 | 0.2135 | 0.3490 | 0.2691 | 0.1788 | 0.1788 | 12.539 |
| cpu | matched_c1 | 6654 | 0.2951 | 0.2274 | 0.3559 | 0.2691 | 0.1667 | 0.1493 | 12.608 |
| cpu | analytic | 6654 | 0.2535 | 0.2101 | 0.3160 | 0.2552 | 0.1632 | 0.1510 | 12.631 |
| cpu | cfc_matched | 6474 | 0.1823 | 0.1771 | 0.1545 | 0.1684 | 0.1528 | 0.1528 | 12.575 |
| cpu | cfc_same_width | 13230 | 0.2101 | 0.1736 | 0.1701 | 0.2031 | 0.1406 | 0.1406 | 12.701 |

## Preregistered equal-training-CPU contrasts

| Endpoint | Control | Analytic gain | 95% crossed-bootstrap CI | Bonferroni lower | Pass |
|---|---|---:|---|---:|---|
| full | ordinary | -0.0243 | [-0.0938, +0.0330] | -0.1163 | False |
| full | matched_c1 | -0.0417 | [-0.0903, +0.0069] | -0.1068 | False |
| full | cfc_matched | +0.0712 | [-0.0017, +0.1441] | -0.0191 | False |
| full | cfc_same_width | +0.0434 | [-0.0139, +0.0990] | -0.0312 | False |
| missing_mean | ordinary | -0.0182 | [-0.0573, +0.0234] | -0.0677 | False |
| missing_mean | matched_c1 | -0.0286 | [-0.0677, +0.0078] | -0.0823 | False |
| missing_mean | cfc_matched | +0.0972 | [+0.0382, +0.1562] | +0.0252 | True |
| missing_mean | cfc_same_width | +0.0911 | [+0.0460, +0.1354] | +0.0312 | True |

Passed 2/8 contrasts. Neither a partial pass nor an infrastructure pass establishes overall superiority.

## Interpretation and limits

- The analytic gate is zero-drift finite-window first passage with a freshly parameterized gap per step. It is not the complete coupled He--Xiong operator, a probability-conserving renewal cell, or an optimal task-value policy.
- Ordinary and matched-C1 use the identical candidate recurrence and exact parameter count. The matched arm agrees in gate value and slope at z=0 for every elapsed time. This tests local slope matching, not full curvature or arithmetic-cost equivalence.
- CfC reproduces the official default equations with no backbone. H=6 matches parameters within3%; H=12 is the same-width control. Hand-written gradients passed32 central-direction checks, and CfC forward matches a separate literal equation implementation. Official Torch runtime equivalence has not executed here.
- CfC uses the common zero-bias initialization of this experiment; upstream Torch Linear initializes biases randomly. This is an equation-level architecture control, not a reproduction of the original paper's complete training configuration; CFC_PROVENANCE records the exact distinction.
- Both low-level modality frontends are fixed. All small recurrent/backbone/output weights train through complete BPTT. This is not raw-media encoder pretraining or a multimodal foundation model.
- Resampling uses full-clip duration. Inputs are offline sequences, not causally decoded media. Recall32/96 append other real-clip distractors under an artificial first-clip-recall contract; no natural long-video claim is made.
- The target-phase bit explicitly identifies the original clip versus irrelevant distractors. Delay donors cross test actors, so delay observations are coupled and receive descriptive means only; the registered bootstrap endpoints use gap0 and do not consume donors. Within-actor mispairing means a different recording, not an enforced different-emotion intervention.
- Validation chooses between midpoint/final checkpoints; learning rate0.003 is fixed equally without an extensive tuning study. Robustness and negative outcomes remain in raw outputs.
- Full child CPU includes interpreter startup, restore reads, initialization, training, validation, test, and result/checkpoint writes. Training CPU is nested and is not added again. Connector transfer and shared cache restore are separate. No GPU or energy comparison exists.
- Historical raw affine-FLOP estimates are preserved. SUMMARY contains corrected operation counts for the actual hidden-only BPTT; special functions, readout, Adam and memory traffic are excluded.

## Reproduce

Run restore.py on the pinned textual parts, then check_gradients.py, study.py launch with three jobs, and summarize.py. Keep OPENBLAS_NUM_THREADS=1, OMP_NUM_THREADS=1 and MKL_NUM_THREADS=1. Existing output directories are immutable: use a fresh checkout/output root for another attempt.
