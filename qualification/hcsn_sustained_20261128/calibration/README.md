# Post-hoc calibration of six-layer CREMA-D edits

The previously reported aggregate outcomes motivated this analysis. All 27 frozen candidate-weight hashes came from the original seal. We replayed each candidate on the same 1,147 development clips, verified its original uncalibrated loss, and fitted a nonnegative scalar multiplying its logits in [0,4] by convex NLL minimization. Each method and seed selected its prefix by calibrated development NLL. We wrote and hashed this selection before reading the chosen candidate’s stored logits for the 1,311 cold clips. The second analysis repeats this procedure after adding the same fixed log training-class frequencies to every candidate. All 72 classes occurred in training. The two analyses use the same previously observed cohort and constitute mechanism diagnostics.

The table averages three paired training seeds. The 4.1 column counts seeds whose selected model reached at most 4.1 NLL on both development and cold clips. Charged seconds include the original complete costs for each inspected prefix, plus development replay, scalar calibration, common reanalysis preparation and selected cold scoring. These are measured costs on this CPU and dataset.

| Calibration | Method | Dev NLL | Cold NLL | Dev top-1 | Cold top-1 | Seeds ≤4.1 | Charged s |
|---|---|---:|---:|---:|---:|---:|---:|
| Temperature | forward | 4.08993 | 4.10470 | 6.28% | 6.53% | 1/3 | 8.33 |
| Temperature | shuffled | 4.10936 | 4.14975 | 6.10% | 5.36% | 0/3 | 8.43 |
| Temperature | head | 4.15788 | 4.16360 | 5.70% | 5.21% | 0/3 | 7.11 |
| Temperature | same_site_bp | 4.11988 | 4.12665 | 3.72% | 3.48% | 1/3 | 11.82 |
| Temperature | keep | 4.26308 | 4.26252 | 2.85% | 2.82% | 0/3 | 4.12 |
| Temperature + train prior | forward | 4.07147 | 4.09528 | 6.25% | 5.49% | 1/3 | 8.33 |
| Temperature + train prior | shuffled | 4.08719 | 4.12146 | 6.07% | 5.77% | 1/3 | 8.43 |
| Temperature + train prior | head | 4.15804 | 4.15891 | 6.39% | 6.05% | 0/3 | 7.11 |
| Temperature + train prior | same_site_bp | 4.03810 | 4.04662 | 6.80% | 6.18% | 2/3 | 11.82 |
| Temperature + train prior | keep | 4.20560 | 4.20563 | 3.66% | 3.66% | 0/3 | 4.11 |

Simple temperature scaling gave direct-minus-same-site-BP cold NLL −0.02195 (95% actor-cluster bootstrap −0.05570 to +0.01312). Adding the identical training log prior changed the difference to +0.04866 (+0.02114 to +0.07696). Positive means lower loss for BP. Both intervals resample the same 16 actors with 4,000 paired draws after averaging matched seeds, weighting by clip count. The training prior by itself scored 4.20560 development NLL and 4.20563 cold NLL, with 3.66% top-1 on both. A positive per-model scalar preserves rankings; any change in top-1 relative to the previous report may arise from selecting a different prefix (or a zero scalar with tied scores). Adding a class-dependent prior can change rankings.

The average direct point estimate on the temperature-plus-prior arm clears 4.1 on development and cold data. One of its three seeds individually clears both gates. Two BP seeds clear both, and its mean loss is lower. Across these two valid post-hoc choices, the sign of the direct/BP comparison changes. Neither provides a fresh benchmark or a general editing-speed result. All original uncalibrated gates and evidence remain separately available.

Run `python calibrate.py BASE SOURCE_ROOT EMPTY_OUTPUT_DIR` on the environment containing the original prepared data, sealed models and scores. The run validates their hashes and keeps the original result files untouched. Place its two JSON outputs beside `verify_calibration.py` and run `python verify_calibration.py` to reproduce the development choices, charged costs, per-arm summaries and actor-bootstrap intervals from the retained statistics.
