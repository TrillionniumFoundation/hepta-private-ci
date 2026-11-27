# ACT3 stage 3: real private-state cold recovery

**64/64 paired recoveries passed; no learned policy promotion.**

The actual campaign uses eight saved ACT2 GRU checkpoints, four reused original
tasks and two real SIGKILL boundaries. There are 32 uninterrupted references,
64 killed workers and 64 fresh restoring workers: 160 distinct subprocesses,
all under the same UID. New independent tasks = 0.

The crash points are after the post-inference pending checkpoint but before the
first apply, and after the actual SQLite effect commit but before the source
continuation acknowledges it. The latter is durable acknowledgement loss after a
real effect, not a claimed physical network packet-loss experiment.

Every restored run preserves its reference hidden bytes, decision sequence,
goal state, original effect identities and success claim. No double hidden-state
advance or duplicate effect was observed. Three already inferior reference runs
remain incomplete after recovery: seed 704 normal length 3 and length 4, and seed
707 normal length 4. Correctly restoring a failed policy is a recovery pass, not
a task-success or learning-gain pass.

| Seed 700 / normal length 3 | Primitive attempts | Metered total | Budget |
|---|---:|---:|---:|
| Uninterrupted | 11 | 14 | 24 |
| Restore before effect | 11 | 17 | 24 |
| Restore after commit | 11 | 18 | 24 |

The metered total adds owner reconciliation and restoration metadata reads.
Checkpoint commits and surviving-process scorer queries are reported separately.
Killed-process internal scoring/setup and all SQL/checkpoint I/O are not a
complete lifetime cost ledger: `full_operations_cost_qualified=false`.

## Reproduction

```sh
python3 scripts/act2_learning/qualify_continuation.py \
  --models qualification/act2-learning-20261110/run2 \
  --include-long-task --output /new/empty/path/continuation
```

The default three-task panel contains 48 pairs. `--include-long-task` adds the
original length-4 normal task to include seed 707's known failure stratum.
Source and model bytes are hashed before and after execution. Missing pairs,
unexpected exit codes, mismatched continuation or changed source cannot pass.

`RESULT.json` is the bounded summary. `run1.tar.xz` retains every original output,
full result, per-case stdout/stderr, identities, checkpoints and physical SQLite
databases. `ARCHIVE_INDEX.json` records each original size and SHA256; all archive
members were re-read and matched. Compression preserves the complete bytes while
respecting the unchanged 512,000-byte repository blob gate.

## Limits

This closes the measured single-writer, same-UID SQLite research continuation
scope. Production CellStateOwnerV1/FinalUse callers, independent trust domains,
concurrent writers, host power loss, other families' neural cold restoration,
full costs and independent domain benefit remain open. The fixed skill library
is retained; the result is HOLD / NoUpdate for learned-policy adoption.
