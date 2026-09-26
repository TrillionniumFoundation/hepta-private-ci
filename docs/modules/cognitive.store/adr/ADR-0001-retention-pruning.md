# ADR-0001: ancestry-safe retention and pruning

Status: accepted design; destructive compaction requires a separately qualified implementation.

The authoritative Memory/source/fact ledgers remain append-only.  Bounded paging limits materialization and does not authorize deletion.  A retention job may remove payload bytes only after a signed prune plan proves: every retained head has complete required ancestry; tombstones and revocation frontiers survive; citations and KG generation receipts remain interpretable; backup/WAL generations are covered; dependent artifacts have acknowledged revocation; and an independently retained current-cut witness advances after commit.

Pruning is a fenced generation transition.  It writes an immutable plan and predecessor digest, builds a private compacted generation, verifies semantic equivalence for retained live state and non-resurrection for deleted state, then atomically publishes.  Failure before publication leaves the predecessor active.  Uncertain publication is `Indeterminate`.  No in-place `DELETE` of ledger rows is allowed.

Minimum retention classes are: live payload, tombstone lineage, security/audit receipt, legal hold and prohibited payload.  A legal hold blocks physical deletion but not logical non-use.  A prohibited payload may be cryptographically shredded while retaining non-content lineage.  Model unlearning and derived-artifact deletion are separate owners and cannot be inferred from this store.
