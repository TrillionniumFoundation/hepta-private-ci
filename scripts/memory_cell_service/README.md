# Local typed memory service

This executable research service connects current source facts, a durable
training queue, real LoRA optimization, pinned checkpoint publication, and
parameter reads. It extends the existing `SourceMemoryCell`, `ParametricOwner`,
and metadata catalog. It does not change a native production install gate or
claim that the finite trials prove general memory.

## Identity and authority

`MemoryService(root, scope, cell_id="memory", role="semantic")` binds one source
database to a stable `(scope, cell_id, role)`. The implemented
`MemoryCellRoleV1` roles are `semantic` and `procedural`. Reopening that database
with another role, cell, or scope fails. Roles currently select separately owned
training sources; both use the same completion-trained decoder backend. A role
name alone does not prove procedural generalization.

This service is the explicit **local research source authority**. An external
producer can use `source_id="ci/<evidence digest>"` to reference its retained
evidence manifest, but this module does not authenticate or reread that external
CI evidence. Production HNMF source admission requires a separate authentic
adapter. Give independent source services different scopes. Combining multiple
source authorities within one scope requires a separately designed union
frontier and must not merge unrelated epoch counters.

Every source revision digest binds scope, role, cell, source identity, revision,
typed key, and value. A correction withdraws the old revision. A source identity
cannot be silently resurrected after revocation. Source history remains on disk
for audit; revocation is use prevention, not physical erasure.

## Immediate and parameter reads

```python
import sys
sys.path.insert(0, "scripts/memory_cell_service")
from memory_service import MemoryService, read_local
from functools import partial

service = MemoryService("/tmp/my-memory", "research:example", role="semantic")
receipt = service.write("source:1", "Alice", "color", "red")
overlay = service.read("Alice", "color")
assert overlay.answer == "red"
assert overlay.origin == "source_overlay"

# This runs actual optimization over all live unconflicted source facts.
trained = service.work_once("/path/to/pinned-base", steps=128, rank=8)
generated = service.invoke_parameter(
    "Alice", "color", "What is the color for Alice?",
    partial(read_local, base_dir="/path/to/pinned-base"),
)
```

`write` is create-only by default. `correct(source_id, value,
expected_revision)` and `revoke(source_id, expected_revision)` require an exact
source revision CAS; initial revision is zero. Both update the immediate overlay
and invalidate the old parameter epoch in the same transaction that enqueues
training. `read` returns a frozen `ReadResult`:

| State | Overlay answer | Parameter callback |
| --- | --- | --- |
| Unknown key | `None`, `unknown` | Never called |
| Several live conflicting values | `None`, `conflict` | Never called |
| Only revoked sources remain | `None`, `revoked` | Never called |
| Supported key, no current trained version | Source value, `answered` | `unavailable` |
| Supported key and current version | Source value, `answered` | Raw decoder response, `generated` |
| Source or version changes during generation | Current overlay applies | `indeterminate`, response suppressed |

Multiple live sources that agree are supported; one deterministically selected
root is replayed while every source retains its own provenance. Conflicting keys
are omitted from training until resolved. Unknown/conflict/revocation handling
uses source admission, not a claim that the model learned to abstain.

`invoke_parameter(entity, relation, question, reader)` calls `reader(active,
question)` only after catalog and current source checks. The caller must supply
the correct typed key; the service does not parse arbitrary language into an
authenticated key. Entity identifiers use `[A-Za-z][A-Za-z0-9_-]*` with a 64
character limit, relations the same syntax with a 32 character limit.

Parameter responses always have `origin="parameters"` and
`correctness_verified=False`. The raw decoder response is preserved, including
incorrect text. Overlay answers never replace raw parameter output or count as
parameter accuracy. Adapter-disabled and shuffled-adapter controls remain
available through the existing raw research decoder/worker APIs; the service's
normal parameter path uses the admitted adapter.

## Background work and recovery

```sh
python -B scripts/memory_cell_service/training_worker.py \
  --root /tmp/my-memory --scope research:example --role semantic \
  --base /path/to/pinned-base --steps 128 --rank 8
```

`--once` handles one claimed job and exits; without it the worker polls for new
work. Source writes do not wait for training. The SQLite queue persists snapshots,
lease tokens, attempts, staged candidates, and completion states. New writes
supersede queued old work. Expired attempts can be reclaimed up to three times;
expired workers cannot stage or publish. A normal publication exception after a
candidate was durably staged requeues those same immutable bytes, with a fresh
lease token on the next claim, up to the same three-attempt limit. Budget
exhaustion becomes a visible terminal failure. Training failures without a
staged candidate also remain visible in the job's error field. A worker lease defaults to one hour; `--lease-seconds` can be
set up to one day for a known bounded training budget. The queue API also exposes
renewal for a supervised worker.

Training always starts from a fresh frozen base and replays **all currently
supported facts**. A configuration must complete at least one full pass through
the source/template pairs. The real measured receipt must bind the exact fact
digest and roots, with no inherited adapter roots. This is a clean replay policy,
not a statistical certification of forgetting. Checkpoint and catalog bytes are
SHA-pinned and revalidated by the existing owner and catalog.

Publication stages the candidate durably before owner activation. A short source
write transaction verifies the live epoch and training lease, activates the
parameter version through owner CAS, then commits its source-version binding.
No source transaction spans model training or inference. If a process dies after
the parameter owner commits but before the source binding commits, the staged
candidate is recovered after lease expiration. The worker validates those same
bytes and reconciles the binding without retraining or incrementing the active
generation again. Until then the service refuses parameter reads.

Publication rechecks its lease after checkpoint validation, before owner
activation, and again before committing the source binding. Expiration after an
owner commit leaves no usable service binding and follows the same staged-byte
recovery path. On POSIX the service flushes newly created parent directory
entries, source/parameter database directory entries, the training-attempt
directory entry, and the catalog directory entry. Existing checkpoint code
flushes tensor/config/manifest files and their directories. Windows reports
`directory_policy="unsupported_on_windows"`; it does not call an unsupported
directory API. Published receipts expose these storage capabilities and always
set `power_loss_recovery_verified=False`. These checks and process-interruption
tests do not claim that a physical power-loss experiment was performed.

`work_once` returns `published`, `superseded`, `empty`, or `idle`.
`published` includes the epoch, generation, checkpoint directory and SHA, catalog
path and SHA, and original measured training receipt. An empty supported snapshot
clears the service binding without loading a model. Each cell is bounded to 128
active sources and 4,096 retained source revisions; arbitrary growth is not
silently admitted.

## Network integration

`authority_view(scope=None)` returns only the current `Frontier(scope, epoch,
revoked)`, without source values. A network authority can inject this live
provider and call it before and after each operation; application code does not
need a manual frontier synchronization step after `correct` or `revoke`.
`parameter_binding()` returns current source epoch/digest/role plus `ActiveCell`
metadata and a pinned value-free catalog. Its checkpoint directory can be moved
using the network module's immutable-byte import/export protocol. The service's
outer epoch barrier and the worker's online authority barriers both apply when
the `reader` callback performs a network read.

## Behavioral verification

Run with the same pinned Python dependencies as `scripts/memory_cell`:

```sh
PYTHONPATH=scripts/memory_cell_service \
  python -B -m unittest discover -s scripts/memory_cell_service -p 'test_*.py' -v
```

The suite covers atomic source/outbox updates, conflicts, correction/revocation,
role binding, stale worker fencing, process restart, actual tiny-decoder training
and cold reads, independent worker-process publication, source changes during
training/inference, checkpoint tampering, and activation/binding crash recovery.
Tiny decoder tests establish behavior and byte lifecycle; pretrained capability
must be measured separately with retained raw control outputs.
