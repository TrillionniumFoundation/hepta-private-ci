# Physical-node Cell execution: complete results and owner handoff

## Decision

The actual two-host experiment demonstrates native parameter execution and a controlled original-owner stop/reload. It does **not** demonstrate a net benefit from distributed organization. The stronger, contemporaneous pure-local baseline is faster than every distributed-policy arm after connection, calibration and teardown are counted. The P3 net-benefit acceptance criterion remains unmet.

This publication adds the exact executed worker, three coordinator/probe sources, worker Cargo.lock, original raw trials and complete owner receipts. It is stacked on Cell implementation PR #4290, initial head `2021bd35616c1a8092238d5f408caee510c688ab`; that implementation exports the original `MemoryResidualCellV1` numerical path.

The scope is a replicated numerical Cell with placement policies. It does not implement an inter-Cell computation graph, distributed learning, a cluster-wide authority epoch, partition recovery, or a general agent. In particular, this controlled worker reload is separate from the P0 Agentd/thread/queue operation-resumption qualification.

## Workload, identities and resources

The physical hosts are `main` and `x230`. Each Runtime-owned worker uses the same original seed-731 residual model through `MemoryResidualCellV1::from_bytes` and `predict`; no table substitutes for the learned parameters. The fixture consists of eight already-encoded 384-dimensional input rows and expected typed outputs. Each trial cycles these same eight rows to execute 512 rows. These repeated rows are not independent language tasks.

| Artifact | Size | SHA-256 |
| --- | ---: | --- |
| Executed worker | 908,640 bytes | `91fda455c6db76e47cd7ca181f16a9317e3de5c400349257897c12ae2b9dceca` |
| Serialized model | 62,792 bytes | `35e0f96a2e7bf1a21a7e937ed009bbef9002c547781b8de12acbc5aae024e15e` |
| Parameter identity | 30,768 parameter bytes | `4cac583bd2967bb3ed828b31200b98b5e8c4e96a76d2eb2e07570acc1559b442` |
| Frozen input/expected values | 68,007 bytes | `a595ef46cc6fda670d451ae371bbe2bc90f6d3821aa599e5fcd8bbcc8a542637` |

Both actual cgroups were read back: `cpu.max = 100000 100000`, `memory.max = 268435456`. These verify a one-CPU/256-MiB cap on each worker job. They do not bound the coordinator, SSH services, encoder, LLM or other host processes. Worker process readiness RSS was about 2.8 MiB; the complete Runtime job cgroups were about 7.4 MB at the sampled instant. Neither number is the memory footprint of a complete agent.

Both machines were shared. A bounded preflight measured an unrelated compiler consuming about one CPU on each host (main has 48 CPUs; x230 has 4). Another qualification also ran from main. Those unrelated workloads were not stopped. Arm orders rotate across four repetitions and all arms are measured in the same run, but these are descriptive shared-host measurements, not dedicated-hardware statistical proof or equal consumed-energy comparisons.

## Stronger follow-up: 32 trials and 16,384 correct rows

`local_only` connects and warms only main. `pooled_centralized` connects both workers but sends task rows to main. `fixed_round_robin` splits requests across both workers. `adaptive` chooses from measured calibration latency multiplied by queued work. This fixed placement policy is distinct from the differentiable fixed graph studied in P2.

All 32 trial files exactly match their entries in the original RESULT, and every trial returns all 512 expected rows. Batch sizes are 1 and 32; each arm has four repetitions. Client concurrency is at most two, and each worker serves requests serially. Dedicated nonmultiplexed SSH clients retain normal host-key verification.

The task interval excludes setup. The measured-trial interval includes connection, identity checks, calibration, task execution and connection teardown. External deployment and recovery remain separate costs; the raw historical field `lifecycle_wall_seconds` is not a complete lifetime measurement.

| Batch rows | Policy | Task median, seconds | Measured-trial median, seconds | Task rows main / x230 across four trials |
| ---: | --- | ---: | ---: | ---: |
| 1 | local_only | 0.593026 | 0.598390 | 2048 / 0 |
| 1 | pooled_centralized | 0.620590 | 1.038081 | 2048 / 0 |
| 1 | fixed_round_robin | 1.737605 | 2.146619 | 1024 / 1024 |
| 1 | adaptive | 0.601095 | 1.026672 | 2048 / 0 |
| 32 | local_only | 0.362942 | 0.392822 | 2048 / 0 |
| 32 | pooled_centralized | 0.329634 | 0.800680 | 2048 / 0 |
| 32 | fixed_round_robin | 0.404592 | 0.867371 | 1024 / 1024 |
| 32 | adaptive | 0.368042 | 0.985813 | 2048 / 0 |

With batch 32, adaptive organization takes about 2.51 times the pure-local measured-trial median. Every adaptive task row runs on main; x230 serves calibration only. The pooled centralized task-only median is slightly lower than local-only in this small shared-host sample, but its measured-trial median is about twice as high. Neither observation establishes a distributed compute speedup.

The following totals cover all four batch-32 trials in an arm. Application bytes include loopback plus off-host traffic, so they are not exclusively wire bytes. Dedicated SSH wire counters are retained in every relevant raw trial. Tiny negative local-only SSH CPU sums (about 1e-16 seconds, floating subtraction noise) are displayed as zero here; original values remain unchanged in raw records.

| Policy | Coordinator CPU seconds | Local SSH-client CPU seconds | Application bytes |
| --- | ---: | ---: | ---: |
| local_only | 1.525420 | 0.000000 | 17,680,586 |
| pooled_centralized | 1.540164 | 0.675684 | 18,755,598 |
| fixed_round_robin | 1.617910 | 0.740713 | 18,755,595 |
| adaptive | 2.134186 | 0.719753 | 24,972,130 |

The original generation-1 run is also fully archived: 18 trials, 9,216 correct repeated rows, and three policies without the stronger local-only baseline. Its adaptive arm likewise sends all task rows to main. Both original g1 owners later terminated by timeout (exit 124); those are recorded as timeouts, not retroactively described as explicit cancellation.

## Original-owner stop and generation-3 reload

The complete qualification uses four recorded phases:

1. `before`: verify the original x230 generation-2 Runtime job is running, read the original model, and bind the same parameters and expected values.
2. `watch-stop`: keep a bounded live-read stream active, retain the successful prefix, cancel that exact original Runtime job, and preserve the interrupted request without retry (`automatic_retry_count = 0`). The final unresolved request is not labeled completed.
3. `stopped`: check the original authoritative terminal receipt (`state=cancelled`, `timed_out=false`, exit -15, complete capture), then verify the old endpoint is unavailable.
4. `after`: start a separate x230 generation-3 job with the same binary/model. Initial inference counters are zero. Send the original request identity using generation 2 against the new binding; it returns `binding_mismatch`, with rows/requests/compute_ns still zero. Then one generation-3 request executes exactly the eight original expected values.

All four phases passed. Measured phase intervals are 0.403221, 20.145230, 0.402951 and 0.514484 seconds. The watch interval includes deliberately waiting for an external owner-stop action and is not a service recovery-latency estimate. The x230 g3 start API took 2.681 seconds; the after probe does not include the operator gap between stop and restart.

| Worker | Original job | Outcome |
| --- | --- | --- |
| main g2 | `1a1883ad0f6-96a-3f55` | Explicitly cancelled after the experiment; authoritative terminal receipt verified |
| x230 g2 | `1a1883b068a-96a-3f56` | Explicitly cancelled during active reads; terminal receipt and old endpoint checked |
| x230 g3 | `1a1884f7f12-96a-3f75` | Same parameters reloaded; old generation rejected without numerical work; explicitly cancelled at closeout |

All test workers are confirmed terminal. No production service, unrelated compiler or unrelated Runtime job was stopped. The probe explicitly records `old_pending_agent_operation_resumed = false`: a new worker and same-parameter reload do not constitute resumption of a durable Agentd operation, exactly-once external effects, or cluster-wide generation fencing.

## Deployment and lifecycle costs

The actual first binary-plus-model transfer to x230 moved 971,432 file bytes and took 0.585378 seconds plus 0.168841 seconds of local transfer-client CPU. Generations 2 and 3 reuse those verified artifacts; there was no new model migration during the follow-up. A zero new-transfer count does not erase the initial deployment cost.

The x230 g2 start API took 3.706 seconds. The exact main g2 start API interval was not instrumented and is null, rather than inferred from unrelated timestamps. Numerical worker startup is separately recorded (about 1.5 ms on main g2, 1.2 ms on x230 g2/g3) and does not include Runtime/SSH/controller startup. Overlapping phase intervals must not be added as if they were sequential work.

Remote SSH-service CPU, full owner/controller CPU, resident-byte time integrals, hardware energy, raw-text encoding and model training are not completely measured. The same available hardware pool and verified worker caps therefore do not establish a strict equal-total-consumption budget. The measured distributed arms already lose before these remaining costs can support a full lifecycle claim.

## Complete, verifiable evidence

`evidence/network-final-20261029/ARCHIVE.json` lists nine base64 parts containing the exact gzip archive. It holds 123 source/evidence files with 6,319,613 bytes before tar framing; compressed size is 1,032,962 bytes. Archive SHA-256 is `74639a57a35344bcb4de57b72746a6f78a5703a436ca6afbb279bb2da050ea0d`. The inner manifest binds each exact byte stream. It includes original g1/g2 per-trial records, fixture and model, executed binary, Cargo.lock, source files, verified cgroups/shared activity, four lifecycle phases and original owner responses.

The archive was downloaded with one pinned file version and independently hashed chunks, then every manifest file was verified locally. The follow-up summary was recomputed from the 32 raw trial files, not copied from a prior prose summary. Sources and raw failures/timeouts are retained. Python syntax and published-byte integrity checks are recorded separately from actual execution evidence.

## Engineering consequence

Keep a local numerical Cell call as the baseline and default for this workload. Introduce remote placement only for a task whose useful parallel computation or required locality can repay the measured transport, calibration and lifecycle costs. Future positive claims need a fresh workload, a contemporaneous stronger local baseline, controlled shared-load handling, and complete relevant cost accounting. Replicating a small model across nodes and rejecting stale generations are necessary mechanisms; this experiment supplies no evidence that the resulting organization spontaneously forms general intelligence.
