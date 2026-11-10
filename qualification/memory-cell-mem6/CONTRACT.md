# MEM6 source-memory research contract

Status: **engineering component; scientific adoption HOLD**. These modules do
not modify `candidate_memory.py`, `candidate_selector.py`, the frozen actor,
the model weights, or the evaluator. A successful store or retrieval test is
not evidence of benefit on unseen actor tasks.

## Ownership and state layers

| Layer | Representation and owner | Lifetime |
| --- | --- | --- |
| Working state | `WorkingState`, owned by one task session | In memory only; `begin_session(new_id)` clears it |
| Episodic/source evidence | `EpisodicStore`, identified by authority and namespace | Explicit durable writes and revocations |
| Semantic/skill consolidation | A future separately evaluated candidate | Not implemented or automatically adopted here |

A fact slot is `(namespace, source_id, key)`. Each admitted write receives a
monotonic slot `version`, an authority `write_sequence`, and a content-bound
`record_id`. Provenance includes `source_uri`, `source_sha256`,
`source_version`, and `episode_id`. Source versions are caller-provided labels;
they are not an independently authenticated source chronology. The store does
not verify that a URI contains the claimed bytes. Callers must bind and retain
the original source separately. Evaluator labels are not a permitted source.

## Authority, snapshots, updates, and deletion

The SQLite database is the current authority. It serializes updates in a write
transaction. The JSON snapshot contains data, an authority identity, its read
generation, and a digest. Opening a snapshot always requires the current
authority and namespace. Only exact records still active in that authority are
returned; unknown, superseded, or revoked snapshot records are counted as
`snapshot_rejections`. A missing authority cannot be reconstructed from a
snapshot. A snapshot cannot replace the authority path through the export API.

An update advances the slot version and invalidates every active fact that
depends, directly or transitively, on the old record identity. New dependencies
must reference current facts in the same namespace. Updates that would depend
on their own invalidated descendants are rejected atomically.

`revoke(source_id, key)` removes the active payload, advances its frontier, and
removes dependent payloads. The frontier tombstone remains. A later explicit
write can admit new evidence at a newer version; it never reactivates the old
snapshot record. Deletion means removal from the live logical payload and
future reads, **not secure erasure of old snapshots, backups, storage media, or
model parameters**. An already completed read cannot be retroactively erased.

These are same-authority correctness checks. They do not authenticate a
malicious authority owner, detect rollback of the authority database itself,
establish independent trust-domain custody, or recover a real external effect.
Each read is coherent at its recorded authority generation; an action requiring
a current revocation barrier must recheck at its own commit boundary.

## Bounded storage and context

An authority admits at most `max_records` slots across its namespaces (default
256, hard maximum 4096). Tombstones consume slots and are never silently
evicted. Its logical canonical serialization is bounded by
`max_serialized_bytes` (default 1 MiB, hard maximum 16 MiB); an over-budget
mutation rolls back. These are logical limits, not measured RAM or physical
SQLite/journal size. Facts are at most 4096 UTF-8 bytes, identifiers at most 128
bytes, and dependency rosters at most 32 IDs.

Retrieval requires an explicit source allowlist of at most 32 IDs. Queries are
at most 2048 UTF-8 bytes, output rosters at most 128 entries, and assembled
context at most 65536 UTF-8 bytes (default 8192). Context admission skips whole
records that do not fit and reports their IDs; it never truncates a fact. This
research JSON context is not wired into the ordinary daemon prompt. Any such
integration needs the runtime's model-context contracts and token limits.

## Baselines and intervention semantics

| Strategy | Defined behavior |
| --- | --- |
| `exact_kv` | Case-sensitive key match within approved sources; deterministic ordering |
| `bm25` | Unicode word tokens, casefolding, `k1=1.2`, `b=0.75`, positive scores only; content-ID tie break |
| `uniform_replay` | Seeded uniform sampling without replacement from the current approved roster |
| `icl` | Bounded chronological assembly of current active source records; not a claim of full transcript ICL |

| Mode | Store read | Retrieval | Association | Actor delivery |
| --- | --- | --- | --- | --- |
| `on` | Yes | Yes | Callback if supplied | Yes, within byte budget |
| `off` | No; accepts `store=None` | No | No | Empty |
| `retrieval_off` | Yes | No | No | Empty |
| `delivery_off` | Yes | Yes | Callback if supplied | Empty |
| `association_off` | Yes | Yes | Disabled | Baseline retrieval order |

The optional association callback receives copied records and returns their
exact ID permutation. It cannot rewrite evidence or introduce new records.
Its caller-supplied identity is recorded but is not execution authentication.
No neural head is invented: without a callback `association_status` is
`unavailable`; with a callback skipped before retrieval it is `not_run`.
Testing `association_off` without a real head does not establish a scientific
association ablation.

`read_memory` returns `{records, context, receipt}`. `records` contains only
delivered evidence. The receipt records the session, mode, strategy, allowed
sources, current frontier/snapshot identities, retrieved/selected/delivered IDs,
provenance, byte drops, and local elapsed/CPU time. `verify_read_receipt` checks
internal content consistency, not honest execution. Receipts are evaluator
artifacts and must never become an alternate actor memory channel.

## Reviewable stages and validation

Stage 1 is `episodic_memory.py` with `test_episodic_memory.py`: storage,
working-state lifetime, update/revocation, and snapshot/frontier correctness.
Stage 2 is `episodic_retrieval.py` with `test_episodic_retrieval.py`: deterministic
baselines, intervention receipts, and new-process reads. Each module is below
500 lines. The components use only the Python standard library.

```sh
python -m unittest scripts.ndu_real_runtime.test_episodic_memory scripts.ndu_real_runtime.test_episodic_retrieval -v
python -m scripts.ndu_real_runtime.episodic_retrieval --mode off --namespace demo --session new-session --source source-a
```

The tests use synthetic engineering fixtures. A subprocess read establishes a
new-process storage path, not ordinary Hepta session integration or independent
owner cold recovery. Real task adoption still requires source-disjoint paired
on/off outcomes, the unchanged public selector, actual actor consumption,
cost accounting, and the gates in `PROTOCOL.md` / `ACCEPTANCE.json`.
