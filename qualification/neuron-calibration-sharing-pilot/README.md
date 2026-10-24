# Historical calibration mechanism: one shared temperature versus20 temperatures

This is an internal mechanism diagnosis in an already exposed historical training pool. It is **not a fresh acceptance set, deployment qualification, or replacement of earlier negative results**. Original1600-row holdout member/labels are not accessed. The previous512 internal evaluation rows are part of the historically used pool, not advertised as unseen data.

## New falsifiable question

Does calibrating each training draw separately improve probability estimates beyond one shared temperature, or primarily add degrees of freedom? This differs from the older single-head raw-versus-temperature/LAC experiment. There is one640-row head-training budget, no LAC/APS choice, no architecture selection and no best-seed selection.

Local protocol SHA25669f402d17d2f33e51a9d991a4fd2084575dfb5a6eeb630a47fbbb9963773eb0d was frozen at2026-10-24T10:34:50Z before new split selection/fitting. It is not externally preregistered. Fixed hash ranking partitions the2560 inherited training rows into1280 fit-pool,640 calibration and640 internal evaluation components. Twenty frozen seeds select640 fit-pool rows each. Current fit/calibration/evaluation are disjoint; all20 heads are saved before calibration and all temperatures before evaluation. All preprocessing remains fixed per-row native-L2 features, not learned full-pool normalization.

## Main result: individualized temperatures have no demonstrated added value here

Primary estimand is NLL(shared temperature) minus NLL(individual temperature), averaged over20 fixed correlated heads and640 evaluation sources:

**+0.00003005nats; conditional paired-source95% interval [-0.00001833,+0.00007611].**

The interval crosses zero. This does not prove equivalence or that per-head calibration is universally unnecessary. It shows no demonstrated incremental value under this fixed historical procedure. Source bootstrap preserves all20 heads jointly; the heads are not20 independent datasets and the interval omits training/calibration-population uncertainty.

Shared temperature minimizes equally weighted calibration NLL over20 heads on the SAME640 sources, not12800 independent examples. ItsT=0.53227; individualT ranges0.51639–0.54796. Every selected temperature is finite and interior. Both finite bounds and uniformT=infinity were candidates. No post-evaluation bound expansion occurred. Finite positive temperatures preserve every raw argmax label; uniform probabilities would create all-class ties and are explicitly handled separately.

## Better probability scores do not make a fixed0.7 acceptance rule safer

The new heads exhibit overall underconfidence on this internal population: calibration sharpens probabilities. Top1 accuracy remains89.5391% in all three head arms.

| Metric: mean over20heads | Raw | IndividualT | SharedT |
|---|---:|---:|---:|
|NLL|0.466652|0.350738|0.350768|
|Multiclass Brier sum|0.217716|0.168815|0.168837|
|ECE10|0.178308|0.026433|0.026620|
|Coverage atmaxp≥0.7|61.5703%|84.5078%|84.5625%|
|Wrong accepted / all640|2.1172%|4.7813%|4.7813%|
|Conditional accepted error, unweighted head mean|3.4374%|5.6576%|5.6536%|

The threshold is descriptive and was not retuned. Calibration increases coverage and also admits more errors; lowerNLL/ECE is not lower erroneous-admission risk at a fixed numerical threshold. Each raw head accepts381–408 rows and errs on12–16 of them. IndividualT accepts535–552 with27–33 errors; sharedT531–553 with27–35 errors. Full individual-head denominators and Wilson intervals are retained. No Wilson interval pools20 correlated heads into12800 independent observations.

The calibration-prior constant baseline hasNLL1.385916, Brier0.749820, accuracy22.8125%, but ECE only0.028086. This illustrates why lowECE alone does not establish useful task discrimination. Its coverage is0; conditional accepted error and its interval are **null**, not0% safe acceptance.

## Separating ranking instability from confidence bias

Raw argmax labels agree across all20 heads on567/640 rows and disagree on73. The predeclared descriptive subgroup analysis reports:
- Unanimous rows: NLL raw0.389972→individual0.260412/shared0.260438.
- Nonunanimous rows: NLL raw1.062231→individual1.052306/shared1.052366.

Probability improvement is concentrated in stable-label rows; temperature does not repair argmax disagreement. Mean per-row confidence variance across heads rises from0.001358 to about0.00198 after sharpening. These are explanatory descriptive observations, not additional significant causal contrasts or subgroup selection for qualification.

## Sample limits, cost and reproducibility

640 effective evaluation sources are modest. Selective-error uncertainty depends on each actual accepted denominator; cross-head averaging does not create new source observations. Only the primaryNLL contrast has a planned inferential interval. ECE10 and secondary scores remain descriptive. No training split, temperature bound, threshold, seed or budget was changed after evaluation.

Actual execution:20 fixed200-step logistic fits,5.45seconds, peakRSS299532KiB (~292.5MiB),2CPUthreads,zeroEncoder calls andno downloads. Existing20head parameter arrays and calibration/evaluation raw logits remain local for independent recomputation. This publication contains no raw news, label arrays, model weights, raw logits or original1600 holdout results.

Original executed drivers in observed/source retain sibling-workspace path dependencies and are evidence, not a self-contained retraining installer. replay.py checks the published640-source primary contrast, interval and aggregate arithmetic usingNumPy. It does not independently rerun inference. The original executed source has a logging-only all-uniform edge case (min/max of an empty finite-temperature list). It remains unchanged as historical evidence. run_reusable.py is separately labeled and fixes only that console summary via temperature_summary.py, with6 regression tests. Its numerical training/calibration/scoring procedure is unchanged; it has not been rerun as a new experiment. Both versions retain the original sibling-input layout, so the reusable version is not a portable data installer.

Independent numerical review passed: all calibration/evaluation logits, 21 optimal temperatures (independent convex inverse-temperature derivative solve), 60 per-head metric/interval records and the source bootstrap were independently reconstructed without retraining. The logging-only fix also passed independent numerical-AST comparison and all 6 regression tests. See observed/independent-verification.json and observed/summary-fix-review.json. The archived independent-verify.py retains original local workspace dependencies and is not directly runnable from the publication folder. No new workflow or remoteCI polling is requested. Old experiments and their limitations remain intact.
