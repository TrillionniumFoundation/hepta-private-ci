# WISDM external cohort replication

Source files come from UCI WISDM, DOI 10.24432/C5HK59, via the Git snapshot in SOURCE.json. Each precomputed phone accelerometer time window has a measured activity label. The free decision uses only the x-axis mean and standard deviation. The paid decision accesses the full same-window accelerometer feature set. Both tariffs are simulated. A different cohort, device source, 18 activity labels, and the same frozen gates extend UCI HAR.

Fetch with `python wisdm/get_data.py wisdm-data`. Run `python wisdm/run.py train wisdm-data wisdm-run`, followed by the separately sealed `test` phase on the same paths; use `python time_arms.py wisdm wisdm-data wisdm-run` for cold-process replays. Expected upstream PYTHONPATH and runtime match the parent study.

50 archived ARFF filenames exist; 1614 is missing. Six are exact copies of 1610 including its internal subject code; all six aliases were excluded by immutable blob and internal identity before fitting. They remain in SOURCE.json for independent provenance checks. 44 unique internally matching people remained. The 11/6/6/21 allocation was frozen before either training or confirmation. The initial attempt stopped on a source-identity assertion before fitting. Treat every timing as conditional on this CPU, source and policy family.

## Frozen confirmation

The fitting, adaptation, development and confirmation samples consisted of 6,603, 2,051, 2,910 and 9,086 labeled windows respectively. All 18 labels appeared on confirmation. All data partitions had distinct participant IDs.

| Arm | New utility | Gain vs KEEP | Paired 95% person bootstrap | Worst old-person change | Mean purchase fraction |
|---|---:|---:|---:|---:|---:|
| KEEP | .110619 | 0 | [0, 0] | 0 | .003544 |
| Exact physical edit | .110823 | +.000204 | [−.000514, +.000860] | 0 | 0 |
| Same scalar BP | .110823 | +.000204 | [−.000514, +.000860] | 0 | 0 |
| Wider drive BP | .110823 | +.000204 | [−.000514, +.000860] | 0 | 0 |
| Ridge candidates, KEEP selected | .110619 | 0 | [0, 0] | 0 | .003544 |

The three physical edits eliminate the same 43 purchases across seven people. Their decisions coincide on all 9,086 windows. Average old utility rises by .001445 for each, and the worst old-person change is zero. All four candidate arms fail the registered adoption criterion. The free expert achieves .110823 accuracy, and the fully informed expert .222622. Always buying yields .122622 utility at the new tariff; a correctness-aware oracle yields .266197. The fixed pre-trained experts and one-step gating make this a low-accuracy activity policy. Changes in encoder training time, energy, multimodal transfer and useful general-purpose model editing remain unmeasured.

Fifteen fresh single-CPU process launches exactly reproduced the five selected policies on each of three rotated-order rounds. The medians from launch through import, data verification and parsing, expert and incumbent fit, candidate training and dev selection, and seal equivalence were 1.478 s for KEEP, 1.514 s for inverse, 2.606 s for same BP, 2.844 s for wider BP and 1.301 s for ridge. All arms shared a separate held-out scoring run of 0.559 s after imports. The inverse and same BP both deployed an always-free decision despite their runtime difference. These 15 measurements describe cached local data and this shared CPU; hardware acquisition, network download and procedure design are outside those clocks. All per-launch measurements are in evidence/cold.json.

A CPU-independent re-score is available from the parent study directory using `python verify_har.py wisdm/evidence`. It checks both parameter/prediction seals, the per-participant rows, uncertainty, and the complete cold-timing table. The action arrays preserve the true labels and correctness of both action alternatives. Frozen algorithm and protocol hashes accompany the candidate seal in evidence/train.json.
