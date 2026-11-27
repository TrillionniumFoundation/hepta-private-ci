# Cost v2: frozen local result

The bounded warm probe executed once under protocol002 after the guard and native lanes released their processes. Both arms returned the expected operation on 2 warmups plus 18 measured queries. There were 20 actual decoder entries and 20 verified source calls, zero training updates, zero new semantic task gates and zero retries.

The task remains one exposed historical incident with three query forms; repetitions do not create independent tasks. This measures bare parameter reads, including parameter integrity checks, and exact typed source retrieval. It does not measure live source-owner enrollment, revocation, Objective/NDU checks or end-to-end native service latency.

| Measure | Parameter memory | Source retrieval |
| --- | ---: | ---: |
| Measured correct operations | 18/18 | 18/18 |
| p50 query wall | 1.543282 s | 57.966 us |
| p95 query wall | 1.606733 s | 89.493 us |
| Measured interval | 25.605116 s | 0.001317 s |
| Observed correct queries/s | 0.702985 | 13670.726873 |
| Whole child CPU | 37.179130 s | 0.031895 s |
| Whole child wall | 37.201404 s | 0.043051 s |
| Child peak RSS | 1108628 KiB | 26468 KiB |

Both p50 and p95 use nearest rank: the 9th and 18th ordered values among 18 measured queries. The p50 is not an average of the middle pair. The p95 equals the largest sample; this is a short descriptive probe. Source per-phase CPU counters read zero, below available resolution; the nonzero whole-child CPU is charged. The source comparator is strong for this closed typed two-rule operation contract and is not a general RAG or repair agent. The source path is faster and has fewer retained dependencies here.

Memory used 1608 input and 178 generated tokens across all 20 calls: warmups 156/16, measured 1452/162. The real generation wrapper enforced 20 calls, complete prompts <= 192, max_new_tokens = 16 and returned outputs <= 16; all observed outputs obeyed the frozen limits.

Memory startup inside its worker took 8.258067 s wall / 8.246100 s CPU. Two warmups totalled 2.583602 s query wall and 18 measured queries totalled 25.602828 s; interpreter setup, journal overhead and teardown remain in whole-child costs. The controller consumed 5.132540 s self CPU and 44.638723 s complete execute wall, including both full input hash checks and result serialization. Controller plus children CPU was 42.343565 s. The covering outer process meter observed 42.393865 s CPU / 44.690792 s wall; it includes CLI/receipt overhead and must not be added again.

Storage distinguishes repeated paths/hard links from equal bytes on different inodes. The latest declared inventory is 1,234,846,118 B across 19,282 regular files; allocated st_blocks is 1,282,613,248 B, not unique device extent. Equal-content different-inode payload is 7,594,379 B; no content deduplication was performed. Current model package footprint includes later relay additions.

Standalone declared operational storage is 84,359,967 B for source retrieval versus 1,229,874,530 B for one memory cell. Three cells sharing one host project to 1,233,655,276 B; three independently copied hosts to 3,689,623,540 B. Only real dependencies are shared: retrieval does not pay for a model base or model packages it does not use. These are artifact deployment projections, not multi-host measurements.

Whole OS, dynamic dependency closure, whole-host CPU, energy, billing and continuous/transient byte-time remain unknown. Future independent task count is 0, so compression gain is null. The old 76-test result is historical evidence; no new semantic task was run for this cost probe.

Final 17 pure accounting/guard tests and lint passed before this run. Original protocol001 remains intact as zero-call superseded evidence. Source bytes for actual execution are in executed-sources-plan003; publication formatting needs an explicit identity bridge. Root owns final formatting and remote writes. No further models or tests are scheduled by this lane.

A separate read-only peer audit by ndu_current_proof independently checked all 40 raw samples, phase/index identities, expected answers, nearest-rank quantiles and CPU totals. It found no discrepancy and executed no further models or tests.
