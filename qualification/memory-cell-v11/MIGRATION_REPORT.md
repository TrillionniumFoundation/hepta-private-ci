# WP6: executed same-host checkpoint migration

## Result

The functional run completed all **15 checks** with two real child processes
representing `source` and `target`. Both processes loaded actual trained MLP
checkpoints. The target could serve only after a durable owner-generation
CAS, and its output matched the source output exactly. The source rejected
its old lease after the handoff. Computed outputs still waiting for their
final validity check were discarded when migration, correction, or revocation
made their authorization stale.

Implementation: [migration.py](migration.py).
Integration test: [test_migration.py](test_migration.py).
Retained evidence: [migration package](evidence/archives/migration-v11/README.md).
The original execution directory is
`/workspace/scratch/fa15dc544533/v11-migration-functional-01`; the separately
verified publication tree is
`/workspace/scratch/fa15dc544533/v11-migration-functional-01-sealed`.

This is a Linux, same-machine, cooperative-process research implementation.
Its controller is an explicit trusted SQLite authority. It does not replace
the Rust owner authority, authenticate hostile operating-system users, or
measure physical-host migration or network latency. The transferred object
is a serving checkpoint; optimizer state, process memory, and distributed
replay ownership are outside this profile. The evidence ledger remains
shared and central.

## Mechanism and authority boundary

`SQLiteReplayStore.commit_training` binds a real saved artifact to the
actual records in a current training batch. Separate location, preparation,
and migration-event tables live in that same SQLite database. Consequently,
source correction/revocation and migration's validity checks/CAS are
serialized through the same transaction mechanism. The controller can
publish a checkpoint only if that trusted training commit exists and the
actual artifact matches its digest and byte count.

Preparation copies the actual `weights.pt` and `manifest.json` into the
target node's registered directory. It checks the byte budget, checks a
soft wall deadline between operations, verifies both files against the
trusted digest, and calls `models.load` to validate the real model contract.
Files are flushed before the prepared directory is sealed. A prepared
receipt explicitly has `serving_authorized=false`.

The controller then rechecks the source checkpoint, current generation,
and target bytes before atomically changing the durable location and
incrementing its generation. Worker RPC exposes preparation and reads,
but no publish/activate operation. The fixture's actual checkpoint metadata
deliberately contains `claimed_owner=target` and `claimed_generation=999999`; these claims
grant no authority. A worker attempt to call `publish` is rejected.

Reads have two phases. `begin_read` checks the current node, generation,
checkpoint validity, and actual artifact bytes, then loads the model and
computes an output retained in bounded node memory. `finish_read` repeats
those authority and artifact checks before releasing the result. Tests
interleave the real CAS, source correction, or source revocation between
these two phases. The post-check is the read's authorization point; this
does not imply that a result already released can later be recalled.

The pending-read queue is bounded to eight entries, each batch to 32 rows,
and pending results expire after 30 seconds. Retained artifacts and evidence
history are separately accounted and are not a bounded retention system.

## Executed scenarios

The fixture trains a real `4 → 8 → 2` GELU MLP with 58 trainable parameters
on four explicit numeric records. The initial fit uses seed `51031`; after
a record is corrected, a fresh model uses seed `51032`. Each fit performs
80 minibatches of four presentations, using the current records actually
leased from the store. Both saved weights differ from their initial weights.
These authored numeric fixtures establish control-flow behavior, not a
new memory-quality benchmark.

| Scenario | Observed result |
|---|---|
| False owner/generation claims in metadata; worker attempts publish | Requests denied; trusted location remains authoritative |
| Byte budget of 2,997 for a 2,998-byte artifact | Rejected before copying; zero copied bytes and no handoff |
| Zero-second preparation wall budget | Rejected before copying; zero copied bytes and no handoff |
| Prepared target weights deliberately corrupted | Activation rejected by the actual artifact digest check |
| Successfully prepared target before CAS | Read denied |
| Successful owner CAS | Generation changes from 1/source to 2/target |
| Source old lease and duplicate activation | Both rejected |
| Source computes before CAS, finishes after CAS | Output discarded by post-check |
| Controller SQLite connection closed and reopened | Generation 2 persists; target output equals the source output exactly |
| Record correction after another copy is prepared | Prepared activation and current, prepared, and pending reads rejected |
| Fresh actual training on corrected current records | New checkpoint published at generation 3; target service recovers |
| Source revocation after a corrected copy is prepared | Prepared activation and current, prepared, and pending reads rejected |
| Original source artifacts | Remain retained after invalidation |

The connection-reopen check is not a controller process crash or node
restart experiment. This run does not test host failure, partitions,
distributed consensus, malicious file writers, or an operating-system
reboot. Source and target PIDs were `8` and `11` in the execution namespace;
both were children of the controller and both were waited for with exit
code zero. Full RPC receipts, failures, model outputs, and PID records are
retained in `OPERATIONS.json`, `PROCESSES.json`, and each node's `worker.jsonl`.

At the end, the durable location still names generation 3, but both recorded
checkpoints are invalid. Service fails closed through the checkpoint
validity check. A location entry or retained prepared file alone therefore
cannot reactivate revoked content. Old records and weights remain in the
archive; **mathematical erasure of learned information is not demonstrated**.

## Actual costs and budget scope

| Item | Observed value |
|---|---:|
| One serialized mutable-weight file | 2,461 bytes |
| One manifest | 537 bytes |
| One complete copied serving checkpoint | 2,998 bytes |
| Retained checkpoint directories, including failed/stale copies | 6 copies; 17,988 bytes |
| Successful handoff's preparation stage | 0.0045575 seconds |
| Successful CAS operation | 0.0010084 seconds |
| Initial fit, including first-use optimizer/runtime overhead inside fit | 4.17999 seconds |
| Corrected fit in the already warm controller | 0.07731 seconds |
| Complete functional run, including child startup and checks | 14.53889 seconds |
| Final checkpointed main SQLite database | 167,936 bytes |
| Ledger database plus live sidecars immediately before final close | 902,096 bytes |
| Complete sealed evidence tree | 826,269 bytes across 38 files |

The normal preparation budget is 2,998 copied artifact bytes and ten
seconds. The wall limit is a **soft preparation-stage limit**, checked
between I/O, model loading, and validation operations. It cannot interrupt
a single filesystem or tensor operation. Controller CAS, process startup,
training, RPC framing, and evidence writing are reported separately or
included in the complete-run duration; they are not falsely charged as
zero or claimed to fit that preparation-stage limit. These timings are
one functional observation of a very small checkpoint, not an efficiency
comparison or evidence about network transfer performance.

No pretrained base was copied or newly downloaded. Existing Python/Torch
runtime installation bytes are not included in the checkpoint/evidence
counts. Adam state was used for the two fits but is not serialized or
transferred by this serving profile. No total-storage or compression
advantage is claimed.

## Evidence identities and final sealing

`PLAN.json` and `EXECUTED_SOURCE/` were written before fixture preparation
and training. The run checked that those source files were unchanged at
completion. The existing frozen `models.py` and `maintenance.py` were not
edited; neither were the evolution or structure experiments.

| File | SHA-256 |
|---|---|
| `migration.py` | `2ac75d99227169a2f3a39eaeeb23f5c5dc63ce53481d04249ae5513c1c35bcab` |
| `test_migration.py` | `f352ef7dcb09d55b5b124ad80f14068db2e06e6e4e281b7cf5447f578f29e945` |
| Unchanged `models.py` | `5cced6633c73ff4a0b32a3817b43116c37f2f65f9d1ad2fddc7d8f917a9ca802` |
| Unchanged `maintenance.py` | `fcbcb13f2e8f66de71e7b2c6dd64eab6c37ff1120edb02f668b86770d2c76c32` |
| Executed `PLAN.json` | `bff0a83cf0c1d9edbd32a9812c12c19311b264b37ac978aee11a023ba2e069bd` |
| Executed `RESULTS.json` | `92874df0331177087b9875ab5f7f0269f545ad5aad0d1dd9ca13890e1972de9b` |
| Final main database | `a3a9da570ea961adea5e2fdd1b0d1a187f699db130e7d2e38d91afb1726cd5af` |
| Sealed tree inventory | `06f6168afb62b327f69c0457022c23c0a236eb706dee720037e0f581e7baee02` |

There was an observed sealing anomaly: later filesystem views showed extra
WAL/SHM paths absent from the run's final inventory. Their modification
times preceded the final database, and they appeared again after a rename.
The cause remains unestablished. A `/proc` file-descriptor check found no
open matching descriptors and no uninspectable processes. The main
database's hash continued to match the executed inventory exactly.
An immutable read of that main file passed SQLite integrity checking and
contained the complete final state: five records, nineteen migration events,
generation 3, and both invalid checkpoints.

For publication, a new directory was assembled solely from the verified
final inventory. Both extra sidecars' exact bytes are retained under inert
names in `SEALING_SIDECARS/`; active WAL/SHM aliases are excluded so restoring
the package cannot replay them over the verified main database. All original
results, plan, source snapshots, and inventory are preserved byte-for-byte.
`SEALING.json`, `SEALED_COPY.json`, and `SEALED_INVENTORY.json` document this
additional step. A subsequent full member/hash check found the sealed tree
stable. The report is post-run interpretation, not part of the frozen plan.

## Reproduction

From the repository root, in the existing prepared environment:

```bash
OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 \
/workspace/scratch/fa15dc544533/memory-v11-venv/bin/python \
  -m unittest discover \
  -s qualification/memory-cell-v11 -p test_migration.py -v

OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 \
/workspace/scratch/fa15dc544533/memory-v11-venv/bin/python \
  qualification/memory-cell-v11/migration.py run \
  --output /workspace/scratch/fa15dc544533/v11-migration-functional-rerun
```

The integration test passed before the retained functional run. The runner
refuses an existing output directory and saves the rejection receipts and outcomes.
For exact-source reproduction after later repository edits, use all four
files in `EXECUTED_SOURCE/` in a separate directory. The sealed evidence can
be restored without retraining using the commands in the package README.
