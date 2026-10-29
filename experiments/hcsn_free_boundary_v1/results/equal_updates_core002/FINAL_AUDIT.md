# Final audit of the separate fixed-update diagnostic

The authoritative completed quality report is [analysis002/REPORT.md](analysis002/REPORT.md); numeric tables and paired three-seed differences are in [analysis002/ANALYSIS.json](analysis002/ANALYSIS.json). This addendum binds the final reports, accounts for both audit attempts, and distinguishes the storage anomaly from training execution.

## Completed evidence

All **18 new searches / 36 LR candidates** completed, each with exactly128 optimizer updates, for4608 new optimizer updates. There were **zero worker failures and zero retries**. All126 reused baseline searches have both exact128 LR snapshots and pre-existing validation-only selected predictions. The resulting panel covers all six tasks, eight models and three seeds; the original secondary remains **202 evaluated /42 incomplete /0 added training**.

The final audit verified all36 initial weights byte-for-byte, every first128 minibatch and running prefix for all36 new and252 reused candidates, and all11 old free128 snapshots that were available for exact byte replay. All252 baseline logs were available and reread live. No original study001 log/NPZ or conditional/jobs file was deleted during the space incident. REFERENCE_PREFIX_AUDIT.json is a preventive, independently hashed copy of evidence that remained available, not a reconstruction after missing original evidence. All36 new candidates passed each of the five parameter-group audits, with finite/nonzero observed gradients and actual numeric changes; all six separately named scalar-parameter tensors changed in each candidate. Prediction row coordinates, labels, argmaxes, accuracy and cross entropy were independently checked for all ID and available OOD archives.

## Two audit attempts, one unchanged training experiment

The first audit rejected14 search directories because33 intermediate NPZ files existed even though pruning receipts marked them removed. Its source, outputs and cost receipt remain unchanged; analysis001/INDEX.json locates and hashes the original artifacts. The source snapshot hash matches its original ANALYSIS.json. The second analysis records all33 extras, totalling1,579,368 bytes, with their actual and expected SHA. All hashes match, all required initial/128/selected files are present, and no unknown extra is accepted. None is eligible in the terminal128-only selection. The extra files themselves remain preserved. Their continued presence has no established cause.

The revised storage gate accepts this precisely identified retention anomaly while keeping initialization, minibatch sequence, original128 replay, selection, finite gradients, actual parameter changes and prediction-integrity gates strict. Five synthetic tests check exact retention, accepted matching extras, unknown extras, mismatched extras and missing required checkpoints. The first report's audit-invalid CPU category is not evidence of worker failure; the final report separates those scopes. No protocol, training source, selected weights, training run or heldout predictions were changed after this anomaly.

## Factual clarifications to report shorthand

**The irregular OOD intervention combines two shifts:** sequence length increases from32 to64 and the time-interval distribution is multiplied by3. It is not solely a sampling-rate or pure time-interval shift. The shorter heading “Irregular3×time” and accompanying OOD sentence in the already-bound analysis002 report omit the sequence-length change; the numerical arrays, predictions and accuracy are unchanged.

**Storage did not produce an IO failure in this diagnostic.** Available-to-user space was reported as `f_bavail=0`, while total free blocks remained approximately1.3–1.6GB (`f_bfree`). All18 training workers and both audit processes completed writes without an observed IO exception. No original study001 log/NPZ or conditional/jobs file was deleted. The earlier generated report's language about “filesystem filled” and possible reclamation should be read with these actual observations: reclamation of those original study files was considered but did not occur. All252 original baseline logs were reread live in the final audit. The preventive prefix copy is additional evidence, not a substitute forced by lost originals.

## Complete measured cost scopes

| Scope | CPU seconds | Treatment |
| --- | ---: | --- |
| New18 complete search workers | 809.269501 | Includes imports, both LR fits, validation, checkpoint/hash operations and heldout evaluation |
| New coordinator self CPU | 0.103281 | Disjoint from waited workers |
| First complete audit process | 2.210424 | Preserved failed storage-gate audit |
| Second complete audit process | 2.480189 | Completed quality and storage-anomaly audit |
| Sum of the above disjoint measured scopes | **814.063395** | Excludes unmetered interactive inspection/report writing and preflight imports |
| Training-update CPU inside the search workers | 691.719672 | Nested component; do not add again |
| Reused reference training/inference added here | 0 | Existing126 baseline searches and predictions are reused |

New training wall time with three workers was270.910254 seconds. Sum of per-child wait4 CPU is809.269501 seconds; the aggregate RUSAGE_CHILDREN route is809.269520 seconds, a19 microsecond difference consistent with independently quantized accounting. Both values are retained. Historical baseline full searches cost5520.721426 CPU seconds and are disclosed in the quality report; these were already paid in the primary study and are not billed again. CPU is not an energy measurement.

## Interpretation

At exactly128 updates, free_dual has descriptively higher mean ID accuracy than two_gates in five of six tasks, and than legacy_hcsn in five of six. It remains below the best tested baseline on every ID task: free-minus-best gaps are−10.69,−60.37,−0.65,−10.42,−1.11 and−4.49 percentage points in Copy/MQAR/Irregular/MNIST/FSDD/Multimodal order. The complete ID and OOD tables retain all models, seed SDs and paired differences. There are no new hypothesis tests or acceptance gates, and no selected claim of statistical superiority.

This diagnostic changes both the update target and the eligible checkpoint set: both LR candidates are compared only at terminal128, whereas the original primary experiment selected among its CPU-gate-eligible checkpoints. A changed score therefore cannot be attributed solely to extra or fewer training updates. Fixed-update and equal-CPU results answer different questions. New free two-LR training-prefix CPU has median38.397 seconds, compared with historical fixed128 prefixes of5.002 seconds for two_gates and2.333 seconds for Transformer; these observations are not isolated throughput benchmarks.

The diagnostic was registered before its new training but after the same test data had already been observed. It is a disclosed post-primary diagnostic, not a fresh-test confirmation. Three seeds support descriptive uncertainty only; all primary Holm/content results remain unchanged. Speech accuracy is still low, and these small tasks do not establish foundation-model or architecture-family superiority. The wrapper's before/after full-manifest checks passed, but it lacks the original run_search's additional dataset rehash specifically between selection lock and heldout loading; that check-location difference remains disclosed.
