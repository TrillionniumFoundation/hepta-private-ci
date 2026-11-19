# One shared-preparation profile; not qualification

The protocol-first diagnostic executed exactly one additional shared TRAIN and
validation preparation after t7, exited 0, and did not run candidate selection,
the qualification evaluator or any test construction. `RUNNING.json` is its
retained exclusive execution latch; `profile.json` is the completed outcome.

Shared reported CPU was 4.001949343 seconds; outer process CPU was 3.640419533
seconds, child CPU 0.375792 seconds, and wall 4.016026641 seconds. The three base
files are byte-identical to t7. Its 9.077-second slowdown did not reproduce and
its cause remains unknown; this diagnostic does not replace t7's exit 1.

The profile contains 27 actual calibration calls and 1,944 service requests,
with 3,611,371,737 declared units. Complete compilation, shared metadata,
preparation samples, GC/resource data and pstats are retained. cProfile uses an
elapsed timer, cumulative rows overlap, and profiler/wrapper overhead is real;
its rows do not identify exclusive CPU cost or establish an uninstrumented pass.

The cumulative profile identifies bookkeeping as useful optimization work:
4,470 `charge_kernel` calls account for about 0.906 seconds inclusive, overlapping
the 1.521-second pretraining-step total. Any proposed incremental ledger must
preserve exact snapshots, counters, admissions, prices, and rejection behavior,
and prove a saving on bounded hand-built input before another frozen build.
Neither this observation nor a faster diagnostic establishes the historical
slowdown's cause or a content/control benefit.
