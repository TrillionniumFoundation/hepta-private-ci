# Selected-ID durable owner cuts

Status: authored implementation and regression candidate. Normal-path integration
is materialized by the exact source-preparation commit; that resulting source
and its deterministic merge still require qualification. No activation,
independent acceptance, target-host performance or complete consumer migration
is claimed by this supplement.

This extends the correctness work in `FINAL_USE_CLOSURE.md` with a bounded owner
materialization path. It does not add a store, schema migration, background
worker, authorization cache, mutable read index or durable read-owned facts.

## One existing owner and one ancestry implementation

`CognitiveStore::lane_c_snapshot_ids` accepts at most 512 unique IDs, authorizes
the principal/scope, and delegates to the existing page transaction and
ancestry/citation reconstruction in `lane_c_snapshot.rs`. The same code checks
contiguous ancestry, terminal tombstones, current head pointers, citations,
verification and validity. The whole-scope historical count is a frontier,
not a reason to materialize every historical record.

Selected histories still have a 16,384-revision ceiling and 65,536-citation
ceiling. An oversized selected history fails the entire request. The result
never silently drops requested IDs or returns an incomplete ancestry prefix.
Missing IDs remain explicitly detectable through `read_ids_v1`.

The legacy whole-scope snapshot and public page APIs remain available; their
limits and canonical page digest are not silently redefined. The private page
implementation additionally accepts a bounded exact-ID set for the normal
Agentd consumer. There is no alternate test-only reader.

## Currentness beyond the selected record

`DurableCognitiveSelectionSnapshot` carries the bounded record view, sorted
requested IDs (including missing IDs), global existing owner frontiers and a
supplementary ordered head-state digest observed in the same transaction.
The supplementary digest includes head ID/revision/content digest,
verification/lifecycle, validity interval and eligibility at observation time.
Thus an unselected head's validity transition, a source/tombstone frontier
change, correction or head-pointer change still invalidates the selected cut.

The exact-cut digest uses `hepta.sqlite.lane-c.exact-cut.v1` and binds the
underlying selected snapshot, supplementary owner witness and requested ID set.
The owner revalidation method rejects clock regression and reacquires the same
requested set. It compares the complete cut and structural snapshot. Historical
read receipts are not leases and do not suppress a current owner check.

The transaction still relies on the existing physical owner's immutable-ledger
and recovery invariants. This change is not a substitute for descriptor-safe
recovery admission or a proof against arbitrary offline database forgery.

## Ordinary product composition

The reviewed integration updates the existing Agentd handler in place:

1. observe the owner's bounded retrieval candidates;
2. acquire their exact-ID owner cut;
3. perform exact revision/digest admission using `OwnerCutReadView`;
4. retain existing HNMF observation, optional ranking and complete JSON budget;
5. derive an immutable selected-ID subcut for the final bounded item set;
6. bind that subcut and the publication plan, then revalidate with the owner;
7. on the existing worker final-use request, reacquire the exact selected IDs,
   verify the entire binding, recheck dependent owners and evaluate a fresh plan.

The HNMF adapter borrows the inner structural snapshot only; the final-use read
binding includes the outer selection witness. A subset cannot add an ID absent
from the original acquired request. The worker need not retain the discarded
retrieval candidates to reacquire the final item set. The existing native
worker and uncertain-send reconciliation path are unchanged.

## Capacity and remaining cost

This removes whole-scope history materialization from the selected product path,
not all size-dependent work. Every acquisition still counts owner ledgers and
streams the complete head metadata in bounded batches to construct the witness.
The legacy page caller still repeats its global metadata work on each page.
No constant-time lookup, O(selected IDs) total complexity, production p99 or
cross-request witness cache is claimed. Replacing that pass requires an
owner-maintained, transactionally verified root/checkpoint with explicit
migration and recovery qualification; it must not become a second authority.

## Regression cases

The real SQLite-owner tests cover exact missing IDs, subset/reacquisition
parity, duplicate/oversize/wrong-principal rejection, unselected-head expiry,
source frontier drift, clock regression, correction, tombstone and head-pointer
rollback. The large-history fixture creates 17,000 valid contiguous revisions
for an unselected record in the same physical schema, verifies the legacy full
snapshot refuses its global ceiling, and verifies the exact small selection can
be read and revalidated. Requesting the 17,000-deep record itself must still
fail the bounded selected-ancestry gate.

That fixture is an owner-capacity regression, not an independent deployment or
all-consumer migration receipt. Existing Agentd and physical native worker cases
must execute against the materialized ordinary integration on both exact source
and deterministic merge candidates. Acceptance flags remain false.
