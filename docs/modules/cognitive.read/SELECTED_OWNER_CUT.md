# Selected-ID durable owner cuts

Status: revised source candidate. Exact source/merge qualification, target-host
acceptance and independent review remain separate. The current source identity is
bound by `IMPLEMENTATION_MAP.json`; older supplement hashes are historical only.

This extends `FINAL_USE_CLOSURE.md` with bounded owner materialization. All SQL,
witness maintenance and migrations belong to the existing `CognitiveStore` owner.
The stateless read port owns no database, cache, background worker or authority.

## One existing durable owner

`CognitiveStore::lane_c_snapshot_ids` authorizes the principal and scope before
accepting at most 512 unique IDs. Its ordinary selected path materializes only
requested ancestry and citations inside one SQLite read transaction. It validates
contiguous ancestry, terminal tombstones, current head pointers, citations,
verification and validity before returning immutable values.

Selected histories retain the 16,384-revision and 65,536-citation ceilings.
Oversized selected history fails the whole request. There is no silent missing
ancestry prefix; `read_ids_v1` also reports absent requested IDs explicitly.
The legacy whole-scope and page APIs keep their own documented semantics and
resource limits.

## Currentness beyond selected records

The same physical owner transaction reads `lane_c_scope_witness`, maintained by
source/revision/citation/fact/head mutation triggers. Its state revision and
frontier counts detect mutations outside the selected set. Indexed
`lane_c_head_validity` queries obtain validity regime boundaries, so an unselected
verified head entering or leaving eligibility also invalidates a prior cut.

The exact-cut digest uses `hepta.sqlite.lane-c.exact-cut.v1` and binds the selected
snapshot, owner witness and sorted requested ID set, including missing IDs.
Revalidation rejects clock regression, reacquires the same requested set and
compares the complete cut. A selected subcut cannot add an ID absent from its
original acquisition. A historical receipt is an observation, not a mutation
lease or a cached authorization decision.

## Schema, recovery and derived-state admission

The owner authenticates the definitions of witness tables, indexes, views and
triggers using its canonical schema oracle. Startup/recovery additionally compares
witness counters and head validity with the authoritative rows through independent
audit views. This full recomputation belongs to startup, not each exact-ID read.

Migration 0018 rejects witness identity changes, non-increasing revisions and
replacement of an existing witness identity. Maintenance uses update-then-conditional-
insert in the same SQLite statement transaction, preserving normal increments
without admitting `INSERT OR REPLACE` through SQLite's default non-recursive
trigger behavior. Head and validity-row memory identities are immutable as well, preventing a same-revision identity update from bypassing witness maintenance. Historical migrations remain unchanged.

Migration 0020 rejects replacement of existing canonical source, memory, citation and KG identities, including projection/meta identities. The owner preserves legitimate source replay, meta reopen and KG initialization through atomic insert-if-absent. Recovery capture authenticates schema and independently audits witness contents inside its same transaction, including cold read-only recovery.

Recovery anchors bind the schema oracle. An anchor from an older oracle is
rejected; this revision does not silently rebind an old anchor to a newly opened
cut. Re-establishing a current independent recovery witness belongs to the owner
recovery process. Exact schema/content validation is not a proof against arbitrary
offline database forgery or a substitute for independently retained rollback
witnesses.

## Ordinary product composition

The existing Agentd handler:

1. observes bounded retrieval candidates and acquires their exact-ID cut;
2. admits exact revision/digest matches using `OwnerCutReadView`;
3. preserves HNMF observations, optional ranking and the complete JSON budget;
4. derives the final selected subcut and binds the publication plan;
5. records preparation through the existing learning owner, when configured;
6. rechecks dependencies and the memory owner after awaited work before publication;
7. reacquires selected IDs, dependencies and a fresh plan at worker final use,
   immediately before physical `TurnStart`.

The HNMF adapter borrows the inner structural snapshot. Final-use binding includes
the outer owner witness. The native worker's unknown-send reconciliation remains
separate from preparation and does not infer safe replay.

## Capacity and remaining cost

The selected hot path avoids whole-scope ancestry materialization and repeated
whole-scope counts/head streaming. It still validates all selected ancestry and
citations, and the read port validates the complete structural input it receives.
The legacy full-scope/page paths retain their broader construction cost.

The exact scope witness is derived state, not a second authority. Its write guards
perform canonical counter audits, and startup performs a full content audit.
Migration 0019 adds exact-scope expression indexes and replaces the unexpected-scope audit branch with indexed existence probes, preserving the canonical counter audit. Cross-scope history no longer dominates this branch; same-scope counts still scale with that scope. These costs must be included in owner workload measurements. Indexed reads do not
establish constant-time total acquisition, constant-time writes or production p99.

## Regression evidence

Owner tests cover missing IDs, subset/reacquisition parity, malformed and unauthorized
requests, validity transitions, source changes, clock regression, correction,
tombstone and head-pointer rollback. The large-history fixture puts 17,000 revisions
on an unselected record: selecting a small unrelated record remains bounded, while
requesting the oversized ancestry itself fails the declared ceiling.

Witness integration tests separately cover migration from a populated older store,
pre-existing drift, reopen schema weakening/removal, content drift with restored
schema, recovery-anchor capture and unselected-head mutation followed by attempted
frontier reset or replacement. Test presence is not a pass receipt; the audit
records executed checks and current qualification limitations.
