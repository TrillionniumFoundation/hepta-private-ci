# Fixed direct-versus-nested shared probe P1

Exactly one prospectively declared AB/BA probe ran in the selected Cloud: A1 direct, B1 nested, B2 nested, A2 direct. All four fresh processes completed with exit 0; all worker stdout/stderr and nested launcher receipts are retained. There was no repeat, warmup, outlier deletion or qualification/candidate/test invocation. T6–T8 failures remain valid.

| Sample | Launch | Shared process CPU (s) | Child CPU (s) | Shared total CPU (s) | Wall (s) | Cumulative worker CPU (s) |
|---|---|---:|---:|---:|---:|---:|
| A1 | direct | 1.991518883 | 0.609219000 | 2.600737883 | 2.607459176 | 3.323965812 |
| B1 | nested | 1.718029126 | 0.388147000 | 2.106176126 | 2.105662017 | 2.548231062 |
| B2 | nested | 2.065417881 | 0.403114000 | 2.468531881 | 2.473512622 | 2.841983648 |
| A2 | direct | 2.283216415 | 0.312013000 | 2.595229415 | 2.595160748 | 3.018131302 |

Nested minus direct shared CPU was **−0.494561757s** in pair 1 and **−0.126697534s** in pair 2. In this small bounded probe, nesting did not reproduce the T8 slowdown; both nested samples were faster. This is not a causal estimate or proof against every possible launch-related effect. Pair 1 differences were concentrated in compilation and training-data construction; in pair 2 direct compilation was faster while pretraining/calibration were slower. There is no uniform phase slowdown.

| Disjoint phase CPU (s) | A1 direct | B1 nested | B2 nested | A2 direct |
|---|---:|---:|---:|---:|
| dataset_train | 0.324928167 | 0.141331096 | 0.193803124 | 0.200688530 |
| dataset_validation | 0.064540657 | 0.050052835 | 0.058933363 | 0.078457664 |
| matching_manifest | 0.026169871 | 0.020258374 | 0.021189156 | 0.018289468 |
| compile | 0.612019936 | 0.390539955 | 0.404964994 | 0.314276761 |
| decoder | 0.225009910 | 0.214787034 | 0.298465165 | 0.317057018 |
| pretrain_loop | 1.002699471 | 0.989512063 | 1.149317996 | 1.197930886 |
| validation | 0.037313005 | 0.034454813 | 0.037520657 | 0.058152571 |
| calibration_measure | 0.240536582 | 0.205035616 | 0.237552773 | 0.324415359 |
| export | 0.015380035 | 0.013932131 | 0.015633632 | 0.016977973 |
| Explicit residual | 0.052140249 | 0.046272209 | 0.051151021 | 0.068983185 |

Each sample retained all 27 complete calibration measure calls and 1,944 real caption/PNG/JSON outputs with full cost/per-row receipts. Across the four samples this is 108 full measurements and 7,776 outputs. All twelve base files are byte-identical to T8; all four freshly compiled native libraries have its same SHA256. Each shared ledger recorded 3,611,371,737 units.

All captured start/end numerical runtime fields were identical: Python 3.12.14 at the same resolved executable; NumPy 2.3.5 and identical extension SHA256; OpenBLAS 0.3.30 pthreads/SkylakeX at the same library path and SHA256; identical CPU features/config, NumPy error handling, warnings, trace/profile and relevant environment. All 344 span-boundary snapshots showed one process task, BLAS pool size one and affinity [0,1,2,3,4]. No sampler thread was added. These are boundary observations, not a transient-thread peak claim.

Container throttling, memory.events and major-fault deltas were zero in all four samples. GC totals ranged from 4.315684ms to 5.662260ms. Container counters include other processes; none of these observations establishes a cause for historical variation.

Frozen-list source verification took A1/B1/B2/A2: 0.003131137/0.002139403/0.002289311/0.002734369s CPU; imports took 0.184656356/0.092039076/0.118015290/0.138544275s. This diagnostic verification is not the full qualification train/check_freeze boundary: qualification entrypoint and test-marker actions were never called. Its worker timing therefore must not be substituted for the T8 complete-build receipt.

All four observed shared phases used 9.770675305s CPU in total. The recorded cumulative worker CPU was 11.732311824s, plus separately timed nested-parent own CPU 0.001457611s. Parent waited-child CPU is not added again. These are external R&D costs with the exact administrative exclusions in summary.json; none is credited back to a qualification build.

**Mechanism conclusion:** the proposed nested-launch explanation is unsupported by this probe. T8’s child process itself previously used approximately 10.659s before compiler-child CPU, so an idle outer parent or cumulative-child accounting cannot explain that observation. The historical multi-second variation remains unexplained; these faster diagnostic samples neither fix T8 nor authorize another qualification run.

For the next independently authorized actual build, a minimal useful observation is one same-process snapshot inside charged common preparation: actual threadpool_info, resolved Python/NumPy/backend identities, affinity, task count and active trace/profile. Retain it with the unchanged CPU boundary; use boundary snapshots if needed, without adding sampler threads. No production source was edited for P1.

All original sample files are losslessly archived in raw-samples.tar.gz. raw-samples-files.json records each original file SHA256 and size; archive-verification.json confirms every archived regular file was checked against that original before raw payload removal. Small original RUNNING/WORKER_COMPLETE latches remain to prevent accidental repeated execution.
