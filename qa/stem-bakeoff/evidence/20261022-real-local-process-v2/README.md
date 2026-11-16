# Bounded local-process replay, V2

## Result

This rerun closes the pool-lifetime resource gap found during review of V1.
All **90 prediction and route batches remain exactly equal to V1**: 18
in-process references plus 72 spawned-process outputs. Three seeds, the parent
and split snapshots, one or two workers, input source files, repetitions and
scientific configuration are unchanged. The complete V1 evidence remains in
`../20261022-real-local-process`; its changed source files are retained here in
`history/` with original and compressed byte hashes.

Every worker now admits at most **1,024 total load and inference messages**.
The constructor permits a smaller limit, including a load-only limit of one.
Before executing the Router, the owner checks that every worker has capacity
for every Cell batch that could be selected. This conservative rule can close
a pool with spare messages. It guarantees the entire dispatch fits before any
model runs. Sequence counters and stored event receipts therefore have a hard
lifetime bound; the total event cap is 2,048 for the maximum two workers.

The new actual-artifact cap trial rejected the first inference after a
load-only allowance: **zero owner Router forwards and zero Head calls**.
The pool closed permanently. A 14-test behavior suite also exercised the
boundary after successful inference with one and two real workers, verified
unchanged independent counters and transport receipts, and rejected attempts
to raise the limit or reuse the closed pool. All tests passed in 30.033 seconds.

## Measurements

The real V2 replay took 58.767 seconds. Each column covers six valid pools.

| Observation | One worker | Two workers |
|---|---:|---:|
| Valid inference Head example calls | 3,264 | 3,264 |
| Actual worker Head module forwards | 72 | 72 |
| Actual owner Router forwards | 36 | 36 |
| Actual worker Router forwards | 0 | 0 |
| Median request latency | 419.22 ms | 338.10 ms |
| Observed request latency range | 348.35–641.16 ms | 254.21–469.74 ms |
| Median startup | 1,238.02 ms | 1,345.92 ms |
| IPC payload plus POSIX frame bytes | 7,327,773 | 7,347,199 |
| Joined worker OS CPU | 21.482 s | 30.745 s |
| Snapshot tensors in owner plus workers | 172,736 bytes | 259,104 bytes |

Timing, CPU, PIDs and request UUIDs vary on this shared host. The comparison
excludes timing and transport metadata while requiring identical probabilities,
acceptance decisions, row routes, source pins and actual call fields. Worker
startup and all actual message receipts remain in the unabridged raw payload.

As in V1, all twelve pre-dispatch ancestor withdrawals produced zero additional
Head calls. Mid-request withdrawal and generation changes discarded 128 actual
Head results each. Real process termination and SIGSTOP timeout failed closed.

## Scope and evidence

This remains same-host multiprocessing under a trusted controller. It provides
no cross-physical-node, remote authentication, hostile-worker, real-time or
production qualification. Every worker loads a full snapshot; higher worker
count increases total tensor residency. The measurements exclude process
bootstrap wire bytes, kernel copies, allocator memory and the shared Encoder.
No Encoder inference, training, model acquisition, labels or new test data were
used. Authority stays `DENY_ALL` / `SHADOW_ONLY`.

`inventory.json` lists all stored run and historical-source files. The plan was
written before inference, binds the exact eleven-module dependency closure and
all 44 original E2 input files, and records the V1 plan it supersedes.
`comparison.json` records the independent V1/V2 check; the only changed local
runtime dependencies are the owner and probe. The report and prediction ledger
are losslessly gzip-compressed. No original run payload was omitted.

- V2 plan: `580667a6e172abdd3bb667a22214525619bd6afc4c2f35979e03c62a22ec7dd7`
- V2 ledger: `3aa29390e1ac1eae1f8d8b886ac649209f1c6899fb47bca097591e59527385ab`
- Frozen owner: `61a1686eb44fc83e445c008e64d424912ffbf5e225944174cffa76f29549126d`
- Frozen probe: `e85ee59f9abc35e732db82c7d92bf3ec03dfdb51ee800935bf01577a2f5c1242`

Replay with the same command documented in V1, using a new output directory.
V1 source can be restored from `history/` for a historical replay. Each run
must use its own recorded source hashes; current code is not attributed to V1.
