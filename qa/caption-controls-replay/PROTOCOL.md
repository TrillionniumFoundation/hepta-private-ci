# Post-hoc strong controls, frozen before new test-score calculation

Exploratory analysis of immutable source 539d1d5e73f7c26ec170165e610b8570858b1e59, artifact 12579262528. Not preregistered acceptance, not an independent replication, no change to original plan/threshold/splits/DENY_ALL. Existing headline test results were already known when this protocol was designed.

Use retained 384 x 768 text/image float32 vectors only; verify bank SHA256 and row-to-image identity, normalize each vector in float64. No encoder/model/data network accesses. Image vector includes original fixed neutral text prompt.

Controls fixed before calculating scores:
1. Zero-shot cosine: score dot product of normalized image/text vectors; threshold 0 only as explicitly arbitrary untuned binary diagnostic, with primary threshold-free AUROC. Do not describe cosine as calibrated probability.
2. Zero-shot retrieval: rank original source image among the two images in its existing block, and separately all images in its held-out split. Report text-to-image and image-to-text top-1/top-5/mean reciprocal rank, ties fractional by average rank. Retrieval uses a candidate set unavailable to independent binary classification; not a directly identical decision task.
3. Scalar cosine logistic baseline: standardize cosine using TRAIN mean/std only; fit intercept and slope on TRAIN binary cross-entropy, slope L2 penalty grid [0, 0.0001, 0.001, 0.01, 0.1, 1]. Deterministic Newton iterations (maximum 100, damped line search), choose smallest DEV NLL, grid order breaks ties. Select temperature from original grid [0.25,0.5,0.75,1,1.5,2,3,4,8] by CALIBRATION NLL only. Binary threshold 0.5, confidence threshold 0.7 fixed. No refit on test.

Freeze fit JSON before opening test JSONL. Then report binary balanced accuracy/positive recall/NLL/coverage/selective risk; bootstrap difference in accuracy versus original gated/linear predictions by original pair block (2000 replicates, seed 20261022), descriptive only, no qualification flag. Preserve every original artifact byte; hash all consumed inputs and outputs. Do not claim private Head learning advantage or semantic contradiction from source pairing. This cohort's pretraining contamination is not excluded.

Checks: finite/nonzero vectors; feature hash; unique bank IDs; unique row IDs; split/source-image nonoverlap; all row image/source IDs in bank; binary label equals source pairing; each block has 4 rows/2 images; normalized score correctness; test data cannot enter fitting API. Existing published test awareness means post-hoc selection bias remains despite computational fitting isolation.
