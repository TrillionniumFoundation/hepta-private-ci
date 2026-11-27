# Incremental content002 evidence archives

`content_checkpoint_archives.py` is a separate standard-library helper. It
does not import Torch, read array contents, change registered training sources,
or write inside any worker directory. It is explicitly a native Linux helper:
`flock` prevents simultaneous watchers, and `os.wait4` records complete archive
child CPU and peak RSS. Run it from the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m experiments.hcsn_distributional_v2.content_checkpoint_archives --batch-size 32 --poll-seconds 15
```

The default process runs at an additional nice level of 5. `--once` drains all
currently available full batches and exits. A batch smaller than 32 is eligible
only after `content002/COMPLETE.json` and a successful matching
`SCHEDULER_EXECUTION.json` certify all registered searches.

## What gets sealed

Each run must have a successful progress entry that exactly matches its worker
`EXECUTION.json`, including the `os.wait4` measurement. Its completed identity
must match the registered job, source map, dataset hash, and protocol hash. Its
process log must match the receipt hash. A bundle contains the complete run
directory, its process log, and an immutable selection manifest. This includes
every candidate checkpoint and every update JSONL file. Active directories and
the mutable study progress file are excluded.

Selection follows protocol job order among the completed, unsealed runs at the
time of observation. The selection manifest records that observation's progress
hash, the exact run IDs, full worker receipts, and a file inventory. Every input
is hashed in bounded 1 MiB blocks. No NPZ is opened as an array.

## Publication and failure behavior

Each batch is passed to a fresh process using byte-identical
`evidence_bundle.py` and the frozen v1 `archive.py`. Hard links form a temporary
package tree under `results/content_checkpoint_archives/work/<bundle>/`.
The existing tar.xz packer and restore verifier operate as streams. Only one
archive child runs at a time.

After child completion, the helper verifies the restore seal, all parts, the
exact selected member list, and unchanged original files. It publishes parts
and the seal first, and the manifest last. All links and immutable metadata
use exclusive creation. Existing artifacts are never overwritten.

Successful bundles are discoverable as `artifacts/content002_runs_NNN.json`.
Their `_EXECUTION.json` seal and `.tar.xz.partNNNN` files are siblings.
The exact source selection, full outer child receipt, and publication record
are respectively under `selections/`, `receipts/`, and `committed/` in the helper
results directory. Stage trees and failure receipts are outside `artifacts/`.
An archive failure stops that watcher; the failed attempt remains, and a later
invocation reserves a new name. Never upload a staging tree as a successful
bundle or recursively include the helper `work/` directory in metadata bundles.

Existing successful manifests determine coverage. Duplicate run coverage,
partial run directories, mismatched logs, or mismatched selection identities
are rejected. Final coverage is reverified against exactly all registered job
IDs. A study `ABORTED.json` produces an explicit failed state with a copy and
hash of the abort evidence; previously completed bundles remain valid, but no
full-study completion is claimed.

## Cost scope

For each archive process, use
`receipts/<bundle>.json.cpu_seconds_including_children`. This is the complete
isolated child measured by Linux `wait4`. The bundle seal's process, body, pack,
and restore clocks are nested inside that measurement and are not additive.
Failed child receipts use the same accounting.

For each watcher invocation, use the final
`instances/<instance>_EXECUTION.json.own_cpu_seconds` once. It measures only the
watcher's process CPU through the final receipt, excludes archive children,
and explicitly leaves the small final serialization and exit remainder
unmeasured. The mutable `STATUS.json` contains cumulative heartbeats and must
never be summed. Fixture test outer receipts include their own archive child
processes; fixture child timers must not be added again.

Study metadata, protocol/source snapshots, final analyses, and the archive
helper's own receipts are separate publication units. The incremental worker
bundles alone do not claim to contain those later products.
