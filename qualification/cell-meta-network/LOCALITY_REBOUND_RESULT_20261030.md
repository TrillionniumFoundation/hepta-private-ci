# Matched parallel source-locality control: no stable distribution benefit established

The coordinator Runtime job was `1a18d13f897-96a-4880`, with output under
`/tmp/hepta-cell-locality-parallel-rebound-20261030-01`. Its external
`CONTROL_EXECUTION.json` records exit code 0, 1.769906 s wall and 0.375487 s
waited-child CPU. This enclosing window must not be added to the helper's
nested 1.631113 s observation or its CPU/SSH counters below.

The separate rebound control completed all sixteen fixed trials, with two
concurrent workers in each arm and all source summaries identical to the
original frozen inputs. This removes the first experiment's one-local-worker
versus two-distributed-worker confound. It does not establish a reliable latency
advantage from moving the second worker to x230 for this workload.

The predeclared task median was 44.735129 ms for two main workers and 46.177961 ms
for main+x230. The distributed median was 1.442832 ms higher, or 3.2253%. The
paired distributed-minus-local median was +1.527128 ms. Results varied: the
distributed arm was faster in three pairs and slower in five, while its mean
was lower because the first two local measurements were relatively slow. Keep
all trials. Neither a stable distribution advantage nor universal local
superiority follows from eight correlated pairs on two particular hosts.

## Fixed comparison and complete outcomes

| Metric | Two main workers | Main+x230 |
|---|---:|---:|
| Measured trials | 8 | 8 |
| Concurrent worker requests per trial | 2 | 2 |
| Task median | 44.735129 ms | 46.177961 ms |
| Task mean | 51.189359 ms | 48.800379 ms |
| Task range | 38.161848–71.687319 ms | 38.564943–73.191817 ms |
| Median including before/after stats | 46.649500 ms | 52.053762 ms |
| Coordinator CPU within instrumented trials, total | 0.023089 s | 0.022013 s |
| Task-only application bytes sent / received, total | 4,670 / 7,350 B | 4,614 / 7,294 B |

The byte difference reflects distinct worker instance/request labels, not
different file data or omitted work. Each trial audits the same two shards.
Instrumentation RPCs are measured separately from the task-only window.

| Adjacent trial pair | Order | Distributed minus local task time |
|---|---|---:|
| 0, 1 | Local then distributed | −23.316491 ms |
| 2, 3 | Distributed then local | −22.178931 ms |
| 4, 5 | Distributed then local | +13.321970 ms |
| 6, 7 | Local then distributed | +0.952804 ms |
| 8, 9 | Local then distributed | +8.820051 ms |
| 10, 11 | Distributed then local | +6.412595 ms |
| 12, 13 | Distributed then local | +2.101452 ms |
| 14, 15 | Local then distributed | −5.225288 ms |

The paired mean is −2.388980 ms, opposite in sign to the paired median. These
are different predefined descriptive summaries; the mean is not discarded to
make the conclusion look negative, and the two slow early local trials are not
discarded to make a cleaner local result. OS page caches and background host
contention were uncontrolled. One recorded warmup per worker does not prove
identical cache, CPU-frequency or scheduling conditions.

## Actual useful work and input identities

| Shard | Files | Bytes | Source identity |
|---|---:|---:|---|
| Main source snapshot | 225 | 2,606,999 | Git commit `ca77c10b25cf6eb1de91537c938a2beba597c886` |
| Existing x230 source snapshot | 223 | 4,286,560 | Tree digest `bad32903929dcf6538bc6a7ea896a62ef9eecc78e55d12cb0a1d7e8e35474519`; no source commit |

The distinct input is 448 files and 6,893,559 bytes; repeated benchmark trials
do not create more distinct source data. The x230 files came from that node's
preexisting source archive. Their original centralized copy was reused without
another source transfer. Every audit verifies the original file list, byte
count, content digests and aggregate summary. Stale generation probes were
rejected without audit work before measurement.

This action performs real bounded file-integrity work. `AuditShard` does not
invoke the memory model loaded by the native worker, so its timings are not
memory-cell inference, model-training or complete agent-throughput measurements.
It supplies evidence about execution placement and data locality only.

For the same x230 shard, native read/hash medians were 43.236000 ms in the main
central copy and 40.596672 ms on x230. Corresponding RPC medians were 43.509936 ms
and 42.995091 ms. The median of per-call RPC-minus-native time was 0.237878 ms
locally and 2.552680 ms remotely. This directly exposes communication and client
overhead; it does not isolate their cause from all host/cache differences or
predict the performance of a larger task.

## Measured coordinator and setup windows

The helper's complete observed window was 1.631113 s, with 0.077688 s coordinator
CPU and 0.193343 s owned SSH-client CPU. The external Runtime launch/window is a
different scope. Trial and warmup costs are already inside this helper window;
do not add them again when reporting the helper total.

The dedicated SSH connection took 0.308220 s to establish, while the two local
connections took 0.001750 s and 0.000283 s. The SSH client reported 10,504 B sent
and 20,984 B received across the whole connection. These include protocol and
instrumentation traffic; they are not the source archive size. The three warmup
RPCs took 0.076742 s, 0.104505 s and 0.123097 s, respectively, and are retained
separately from the sixteen measured tasks.

The original centralized transfer receipt records a 1,311,026 B archive for
4,286,560 B of source, 0.584053 s receiving time and 0.709659 s including extraction.
Its coordinator/SSH-client CPU were 0.139678 s and 0.191350 s. That transfer
occurred once in the original experiment; the rebound control references it and
does not charge it as a new transfer. It remains part of overall deployment
history and any future fully specified cold comparison.

Rebound preparation retained a real failed regression run because the v1 helper
dependency had not yet been deployed: 0.132060 s observed wall and 0.003247 s
preparation-process CPU, with regression exit code 1. Installing that unchanged
dependency and passing eight regressions then took 0.210678 s observed wall.
These are separate setup attempts, not a silent successful first launch.
Proof capture recorded 0.001085 s local wall and 0.001079 s local CPU. Remote
proof-read/transfer costs remain null where not observed; null is not zero.

Wrapper-entry-to-ready observations for the three fresh workers were 38.597710 ms
on main, 34.066819 ms on x230 and 35.959975 ms on main-second. They exclude earlier
Runtime scheduling and are not complete deployment startup costs. The immutable
ready snapshots are preserved independently of the later terminal receipts.

## Full new worker lifecycles, including idle holding time

All three original new Runtime jobs later reached `timed_out`, exit code 124,
with complete output. Their wrappers independently reached terminal with actual
direct-child reap and `wait4` resource usage:

| Worker | Runtime job | Lifecycle wall | Child CPU | Wrapper CPU | Wait4 peak RSS | Ready process RSS |
|---|---|---:|---:|---:|---:|---:|
| main | `1a18d138619-96a-487a` | 239.959181 s | 0.579247 s | 1.270221 s | 19,264 KiB | 3,004 KiB |
| x230 | `1a18d1395c4-96a-487b` | 239.976825 s | 0.425052 s | 1.946023 s | 18,944 KiB | 2,904 KiB |
| main-second | `1a18d13a73a-96a-487c` | 239.957058 s | 0.464033 s | 1.224523 s | 19,264 KiB | 3,044 KiB |

These roughly 240-second lifecycles include idle holding and coordination time;
they are not 240 seconds of source-audit work. The complete observed new child
CPU totals 1.468332 s and wrapper CPU totals 4.440767 s across all three workers.
Three workers stayed resident, but only two did audit work in a measured trial.
These are actual costs of this qualification deployment, not an inferred
two-worker production memory requirement.

Runtime `timed_out` is the whole-job outcome. Wrapper `classification: cancelled`
records the external stop signal; `complete: true` and `child_reaped: true` prove
the direct child was reaped. These facts coexist and must not be relabelled
normal worker completion. They do not independently prove arbitrary descendant
or cgroup cleanup. Keep the external Runtime/unit evidence separately.

`wait4` peak RSS and the ready `/proc` sample have different scopes. Do not sum
peak maxima or infer a measured simultaneous footprint from them. Do not add
the worker's `RUSAGE_CHILDREN` CPU delta again to its `wait4` CPU. The old two
900-second worker lifecycles remain separate original costs, not erased by this
new deployment and not repeatedly charged to each warm trial.

## Artifact identities and decision

The preserved rebound `RESULT.json` is 118,444 bytes with SHA256:

```text
959ba76fc85592de2bf2decf3b302df45216d20a9c3618ff5b5b0771f8b91804
```

The common executable SHA256 remains
`2d11c2263a020f8244737aa6c0f7088316fdc2d78bce98f699ff9b4b2083baf8`, and the loaded
model artifact remains
`35e0f96a2e7bf1a21a7e937ed009bbef9002c547781b8de12acbc5aae024e15e`.

| Preserved final lifecycle receipt | SHA256 |
|---|---|
| main | `4f7e076e47f7305eb9b497fab9dfebef97bff90488d4adc2503e8fd2a7df7f3d` |
| x230 | `71c51c851fd47bfd5595b2e370b5716644d412bac909ea7aabddbb6a0b2dba4d` |
| main-second | `da4621b7308a0f21f49e55992797d6e1c1dba3bbba37a81e7e13c0ba4ea8c040` |

Their immutable main copies are under
`/tmp/hepta-cell-locality-rebind-proof-20261030-01/final-workers`. Exact external
Runtime terminal receipts accompany them. Original A/B evidence, original
transfer, frozen new protocol and every new trial remain unchanged.

Keep `cold_cost_comparison=null` and `full_cost_exact=false`. Uncontrolled cache
and host contention, remote SSH-service CPU, full resident-byte integrals,
hardware energy and unmeasured outer setup remain material boundaries. The
opposing mean/median signs and incomplete full-cost scope do not support a
reliable break-even repetition count.

The implementation can dispatch and validate real work across nodes, but this
particular workload does not justify automatic physical distribution. Future
placement decisions need a measured benefit from task size, resource pressure
or data locality under a fair local parallel comparison. No automatic routing,
split, prune or effect authority was enabled by this result.
