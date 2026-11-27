# Parameter-matched HX feature study: fixed updates

The frozen 160-update batch completed 26/30 fits in 1800.052 seconds. One bounded recovery of the four incomplete identities completed the matrix. The original batch remains partial; its two interruptions, unknown interrupted update counts and all costs remain in the archive.

All arms use the existing delayed-recall/adding tasks, data seed 271828, seeds 101/211/307, width 8, length 16, batch 32, FP32 and one CPU thread. HX dual and matched_gate each have 257 trainable parameters including the common readout; GRU has 297. HX physical parameters are trained. The retained HX memory/recovery payload is 64 bytes per example (GRU: 32), separate from parameter, optimizer and process memory.

| Task | Model | Fits | Test MSE mean ± sample SD | All-attempt process seconds |
| --- | --- | ---: | ---: | ---: |
| delayed_recall | hx_dual | 3/3 | 0.174965 ± 0.132240 | 370.417 |
| delayed_recall | matched_gate | 3/3 | 0.200564 ± 0.126215 | 18.748 |
| delayed_recall | hx_call | 3/3 | 0.174757 ± 0.132297 | 361.382 |
| delayed_recall | hx_risk | 3/3 | 0.193602 ± 0.141760 | 21.433 |
| delayed_recall | gru | 3/3 | 0.344451 ± 0.002014 | 9.698 |
| adding | hx_dual | 3/3 | 0.170420 ± 0.005067 | 629.783 |
| adding | matched_gate | 3/3 | 0.170647 ± 0.005690 | 65.199 |
| adding | hx_call | 3/3 | 0.170423 ± 0.005065 | 411.646 |
| adding | hx_risk | 3/3 | 0.169947 ± 0.004412 | 98.330 |
| adding | gru | 3/3 | 0.171024 ± 0.002941 | 36.127 |

These are fixed-update synthetic-task outcomes. The three-seed variation is substantial; the timing environment was shared. Validation wall-prefix curves do not give fast models extra updates to fill the same wall budget. A separately frozen wall-filled comparison follows. Original170, localization/original42, and Cell E07 retain their original definitions and status.

`FIXED_UPDATES.json` includes actual parameter and HX base-boundary changes. `fixed-updates-originals.tar.gz` contains the complete original batch, one recovery, checkpoints, immutable attempts, source bytes, controller and all test logs. Its internal MANIFEST binds every file. Initial missing-ncps and namespace/mock test failures are retained alongside 23/23 targeted and 112/112 canonical passes. This is a value-feature cell study, not the reset/refractory-flow model.
