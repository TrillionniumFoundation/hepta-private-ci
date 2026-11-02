# Fresh-process action-boundary replay

This is a separate engineering stage stacked on the published continuous task
adapter qualification. It reads the archived 80 episodes / 40 worlds and all
505 action-boundary checkpoints. No new task worlds, training, or scientific
confirmation samples are generated. Frozen adapter, renewal source, artifacts
and task files are not modified.

For each boundary the runner invokes a new Python interpreter using
`subprocess.run`. A worker receives only the checkpoint, public-file/world
location, explicit opt-in artifact, and controller identity. The expected suffix
and evaluator outcome remain with the parent comparator. The new process loads
its own NumPy/SciPy modules, frozen head and verified FullHX ContentAdapter,
restores Owner state/receipts plus continuous voltage/mode/residual refractory
and PCG64 state, then actually executes the remaining actions and due packet
reads. Even terminal-boundary workers build their own model and content owner.

The declared execution uses four concurrent workers, one BLAS/OpenMP thread per
worker, and a 45-second timeout per worker. Every request/result, stderr,
returncode, timeout, error, fresh content setup and subprocess wall measurement
is retained. Exact equality is required for all suffix decision and final
checkpoint fields except measured timings. A worker error or mismatch blocks
the stage; no boundary is dropped or replaced. Source, model, raw-input and
world hashes are checked before and after execution.

The parent separately measures wall/process CPU. Per-worker entry-to-result
CPU includes module imports and execution, while Linux `RUSAGE_CHILDREN`
user-plus-system CPU measures all child-process CPU, including interpreter
startup and serialization. Those are different cost boundaries and are both
retained. Neither measures energy or establishes a speed advantage.

The new source, protocol and `SOURCE_FREEZE.json` must be published before any
workers execute. The first version retained 16 strict mismatches caused by
absolute versus archived relative missing-file error paths. Version 2 preserves
the original relative Owner folder spelling and repeats all 505 boundaries
without relaxing the comparator.

For a new checkout, extract the archived adapter qualification into its expected
namespace before preparing a fresh cold-run destination:

```bash
mkdir -p tools/hcsn/digital_read_followup_20261101/evidence/continuous_task_prepared_final2/qualification
tar -xzf tools/hcsn/digital_read_followup_20261101/evidence/continuous_task_qualification.tar.gz \
  -C tools/hcsn/digital_read_followup_20261101/evidence/continuous_task_prepared_final2/qualification
```

From the repository root:

```bash
python3 -m tools.hcsn.digital_read_followup_20261101.continuous_cold_replay_v2 prepare \
  --out tools/hcsn/digital_read_followup_20261101/evidence/continuous_cold_v2_prepared
# Publish that source/freeze, then run with its full commit SHA.
python3 -m tools.hcsn.digital_read_followup_20261101.continuous_cold_replay_v2 run \
  --out tools/hcsn/digital_read_followup_20261101/evidence/continuous_cold_v2_prepared \
  --published-source-commit FULL_40_HEX_COMMIT
```

Every invocation writes exclusively. Reproduction must use a fresh prepared
output directory; existing evidence is never overwritten.

This qualifies fresh-process restoration at completed action boundaries on the
same Linux host, with intact declared snapshot and packet files. Operating-system
file caches remain available; they are not flushed by spawning a fresh Python
process. It does not
simulate an interrupted in-flight action, power loss, torn checkpoint write,
exactly-once external effects, malicious checkpoint tampering or Rust ACK
recovery. It does not establish task benefit, gradient validity or production
readiness. Existing world reuse here is an engineering replay, not an additional
independent model fit or confirmation cohort.
