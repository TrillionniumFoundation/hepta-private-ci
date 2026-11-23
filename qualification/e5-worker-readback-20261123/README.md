# E5 source allocation and measured worker controls

This research record covers two published synthetic fixtures, with one intentionally shared future input. Both the plain Cell and fitted Circuit retain a parent success on `keep` and their candidate succeeds on `later`. The present measurements use a single CPU host. User count, training throughput and production adoption are separate outcomes.

The [hosted fit-and-cold replication](HOSTED_READOUT_ZH.md) now includes all retained original model weights and job receipts. The registered historical identities passed 4/8 on the first hosted CPU and 8/8 on the second. On the latter, two concurrent workers completed 535.79 fitted and cold-verified model pairs/hour against 317.97 with one worker. The former local recovery's terminal outcome remains unknown.

## Worker measurements

| Balanced block | One worker (s) | Two workers (s) | Time with two admitted jobs (s) | Serial/parallel elapsed |
| --- | ---: | ---: | ---: | ---: |
| 1, serial first | 33.308 | 18.156 | 12.384 | 1.835× |
| 2, parallel first | 31.658 | 16.424 | 11.495 | 1.928× |

The clock includes queueing, child creation, cold model loading, inference, receipt readback and worker drain. Each batch offered the same two distinct registered model-pair requests with 12 primitive model calls across both arms. All eight attempts in the corrected sweep passed. The median offered-work completion rates were 221.80 and 417.48 pairs/hour, a 1.882× ratio. Two repetitions on a shared host do not estimate a population speed distribution. Admitted job overlap includes model loading and waiting.

The first cold sweep's Python reader rejected canonical-equivalent tuples and arrays in the semantic verifier's output. Eight native processes completed. Its registered measurement was unsuccessful. After correcting the reader, a second complete balanced sweep generated the table above. The first fit-and-cold sweep completed all eight native fixtures but generated different registered material on the newer library versions. The historical dependency replay regenerated three exact plain and two exact Circuit request digests. Only one of eight complete jobs qualified (plain). Seven fixture return codes were `-9`. Kernel OOM attribution was unavailable. The fit-and-cold speedup remains unidentified. A separately registered, bounded trainer-release recovery was initiated. Its completion could not be observed after the shared execution environment disconnected. No human enrollment or adoption was recorded.

## Human scale experiment

Both regimes cross 1/4/16/64 enrolled people with an independent worker setting of 1/2. The fixed total is 64 updates, allocating 64/16/4/1 per person. The fixed-person budget is 32 each, giving 32/128/512/2048 updates total. The earlier 32-total plan remains identifiable in the source revision. Fresh real cross-user consent and task arrivals, bound numeric compute/verification limits and equivalent per-worker offerings must precede either live curve. The numerator counts distinct frozen candidate weight identities passing retention and future transfer and adopted on subsequent independent work. Repeated use or payment do not add identities. All elapsed batch time and failed attempts enter the denominator. No observed time window with authenticated downstream adoption exists here, so the observed human rate remains null.

## Evidence and replay

[RESULTS.json](RESULTS.json) contains all completed sweep counts, complete corrected cold batch clocks and the exit codes of the historical fit-and-cold sweep as read from the local batch outputs. The raw-run directories were unavailable for export after loss of the execution environment. Independent readers can rerun the checked-in harness against the public immutable source commits in [PROTOCOL.json](PROTOCOL.json). The raw outputs of a new run must live in a new directory. To re-run, use the current repository checkout and place the original plain fixture material and extracted Circuit fixture material in PLAIN and CIRCUIT. Set `PYTHONPATH=scripts` and invoke `python -m cell_experiments.e5_worker_control PLAIN CIRCUIT NEW_DIRECTORY`. Use `--train` for full refits, or `--train --release-trainer` for the separately budgeted process-lifetime control. Historical dependency versions and original PEFT relative path are documented in [TRAINING_REPLAY_ENV.json](TRAINING_REPLAY_ENV.json).
