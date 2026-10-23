# Real local-process snapshot replay

## Result and claim boundary

Three seeds (7, 17, 29), two real E2 snapshots per seed (parent and split),
and one or two spawned workers produced **bitwise identical probabilities and
identical route ledgers** to the frozen in-process implementation. There were
18 reference batches and 72 process batches, covering both repetitions of all
three previously evaluated historical cohorts. No labels, training, model
download or Encoder forward occurred in this replay.

This is same-host multiprocessing under a trusted Python controller. It does
not establish separate physical nodes, remote authentication, Byzantine worker
safety, cross-network confidentiality, new memory-task utility or production
activation. All outputs remain `DENY_ALL` / `SHADOW_ONLY`.

## What executed

Each worker independently loaded the real immutable E1 snapshot, Head NPZs and
Router NPZ. The owner alone executed the frozen Router. It finalized every
selection before sending only selected Head sub-batches. One- and two-worker
configurations preserved each Head's sub-batch shape and arithmetic order.

Requests/results use bounded typed JSON over `send_bytes` / `recv_bytes`, with
1 MiB maximum messages and 128-row pooled float32 inputs. The owner retains the
exact snapshot, artifact, feature, generation, scope, purpose and source-frontier
pins. Workers cannot replace those expectations with their own digest reports.
Request IDs and per-worker sequence numbers fence stale or reordered responses.
No request/result pickle or external listening service is used.

Host-created shared counters observe actual Head forward hooks independently
of result payloads. Those counters assume trusted host/worker code; they are not
tamper-proof remote attestations. Final publication repeats the current-owner
and withdrawal checks while holding the owner commit lock. A failed pool is
permanently closed and cannot fall back to a previous generation.

## Actual costs

The entire experiment took 60.552 seconds. Values below include all six pools
for a worker configuration (three seeds times two snapshots).

| Observation | One worker | Two workers |
|---|---:|---:|
| Valid inference Head example calls | 3,264 | 3,264 |
| Actual worker Head module forwards | 72 | 72 |
| Actual owner Router forwards | 36 | 36 |
| Actual worker Router forwards | 0 | 0 |
| Median request latency | 457.25 ms | 331.52 ms |
| Observed request latency range | 347.35–789.67 ms | 257.58–455.54 ms |
| Median pool startup | 1,309.07 ms | 1,459.27 ms |
| IPC payload plus POSIX frame bytes | 7,327,782 | 7,347,202 |
| Joined worker OS user + system CPU | 21.143 s | 29.375 s |
| Snapshot tensors in owner + workers | 172,736 bytes | 259,104 bytes |

IPC lengths are measured on actual encoded messages, including snapshot loading
messages. Four-byte CPython POSIX connection headers are counted separately;
process spawning bootstrap, kernel copies and allocator overhead are excluded.
The OS CPU deltas include joined worker startup, imports, loading and shutdown.
Per-request owner/worker CPU, every message's bytes, IDs, feature pins, selected
rows and actual per-Cell calls remain in the raw report and ledger.

Every process loads a full snapshot. Two workers therefore have higher total
snapshot residency and CPU here. The shared-host timing sample is descriptive,
not a throughput or hardware qualification; it does not imply equal total costs.
The original shared Encoder is absent from these inference processes.

## Real failure checks

All 12 pools rejected an actual ancestor Router calibration-group withdrawal
before another Head executed: **zero additional calls**. Four additional real
NPZ worker trials checked final-use failure handling:

| Failure | Actual Head rows before discard | Observed result |
|---|---:|---|
| Ancestor withdrawn after worker execution | 128 | Entire result rejected |
| Owner committed split generation after parent execution | 128 | Old result rejected; owner remains generation 2 |
| Worker process terminated | 0 | Rejected |
| Worker paused with SIGSTOP | 0 | Deadline rejection; worker killed and joined |

The stopped-worker case completed rejection/cleanup in 467 ms with a 100 ms
transport deadline. Each failed pool also rejected a subsequent reuse attempt.
Dedicated behavior tests additionally exercise wire corruption, response replay,
foreign worker pins, feature/scope mutation, withdrawal-frontier rollback,
artifact tampering, no legal budget candidate and exact reload semantics.

## Evidence and reproducibility

`inventory.json` binds every original and stored byte stream. The complete
prediction ledger and report are deterministically gzip-compressed; the plan
and stdout remain directly readable. No raw run payload was dropped.

The immutable plan was written before any replay inference. Its 11-file AST
dependency closure records exactly the local Python modules used by this probe,
so unrelated additions do not change its code identity. All 44 input files were
checked against the retained E2 inventory before and after execution. E2's
existing evidence contains those features, snapshots and model artifacts; they
are referenced instead of duplicating them here.

- E2 inventory: `55883610c693991ba68951a0380e8c19dcdfe70d048527c8fa34ac9c386a7a8a`
- This plan: `ff4d575b9c3eec8bea3f719785ae89d9bd1fb6916ba8b6f99df5d9fce996650d`
- Original report: `dd2102b1bdccf7dc8b17ce889d17da14b6d61ceda95e566a298842c7e869b6b7`
- Original prediction ledger: `1efc9b798d51a7424243c0d01abff160e1889d5064c9870dd79cecd0b6c5e02a`

After restoring E2's original paths according to its inventory, run:

```sh
python qa/stem-bakeoff/real_process_probe.py \
  --source-root /tmp/hepta-memory-evolution-run-v3 \
  --inventory qa/stem-bakeoff/evidence/20261022-real-cell-evolution/inventory.json \
  --output /tmp/hepta-memory-process-replay
```

The output directory must not exist. Timing and PIDs naturally vary; source
pins, prediction parity, per-Cell execution counts and fail-closed results are
the replay requirements. The retained historical windows are not new blind tests.
