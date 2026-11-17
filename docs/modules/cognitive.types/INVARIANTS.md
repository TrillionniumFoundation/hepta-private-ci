# cognitive.types invariants

This document distinguishes established Wire V1 validation, the additional canonical receipt, and explicitly selected strict policy. Sections 4–8 describe `ValidateStrictV1`; those rules do not silently replace existing Wire V1 acceptance. Changes that reject formerly legitimate V1 states require a version or migration decision.

## 1. Universal invariants

Every canonical contract must:

- have an exact registered schema ID, schema version and contract ID;
- reject unknown fields;
- be bounded by encoded bytes and collection counts;
- use integer-only numeric wire fields;
- reject noncanonical bytes even when they decode to equivalent JSON;
- validate before canonical encoding, digesting or registered consumption;
- preserve Unicode code points exactly; no implicit NFC/NFD normalization;
- carry no authority merely because it is structurally valid.

## 2. Record and snapshot invariants

- content, predecessor and citation digests are nonzero where present;
- revision 1 has no predecessor;
- revision greater than 1 has a predecessor;
- record identity plus revision is unique in one snapshot;
- snapshot digest is computed over deterministic record ordering;
- snapshot authority is `DENY_ALL`;
- continuity, same-record ancestry, head selection and fork rejection require the durable owner or a transition validator with predecessor state.

## 3. Memory-write receipt invariants

The canonical receipt:

- recomputes the intent digest from intent ID, candidate, authorization, writer-fence and expected-snapshot digests;
- has a nonzero issue time and named writer;
- models `committed` and `rejected` as disjoint tagged outcomes;
- never includes record fields in a rejected outcome;
- requires inserted commits to advance the memory frontier exactly once;
- requires unchanged commits to preserve frontier and snapshot digest;
- validates its own domain-bound receipt digest;
- can be decoded through the closed registry; consumer code must choose the appropriate entry point and independently authenticate external context.

The digest checks do not prove that writer metadata is authentic or that a snapshot digest has a claimed full preimage. The in-memory store adapter rejects its new invalid metadata before writing and checks its comparison ID, consumer and both operands against the actual receipts.

## 4. Federation invariants

- `complete` requires all peers completed, no failures, no truncation and at least one item;
- `partial` requires items and an explicit missing/truncated/failure explanation;
- `empty` requires no items, no failure and complete peer accounting;
- `indeterminate` requires no items, indeterminate validity and an unresolved peer state;
- one result cannot expose multiple current revisions of the same `(source owner, record ID)`.

## 5. Synapse and plasticity invariants

- synapse weight is nonzero;
- inhibitory/negative relations require negative weight;
- nonnegative relations require positive weight;
- fixed synapses require zero eligibility;
- eligibility-gated synapses may begin with zero eligibility;
- plasticity may create a relation from zero old weight, but the new weight is nonzero and relation-sign consistent;
- a plasticity batch is not empty;
- proposal collections are explicitly capped;
- current-snapshot immutability and activation denial remain enforced by the base contract.

## 6. Replay invariants

- bucket-count collections are capped;
- selected count zero cannot coexist with selected IDs or source buckets;
- base validation binds selected IDs and aggregate counts;
- semantic duplicate selection IDs are rejected by the base contract.

## 7. Topology invariants

- operation and node delta agree;
- add/retire edge deltas agree with the typed edge set;
- rewire carries no nodes, has at least one edge and has zero net edge delta;
- resident-byte delta has the same direction as net object growth/removal;
- overflow is a hard failure;
- operation-batch conflict detection and graph referential integrity remain the topology owner’s responsibility unless the full predecessor graph is supplied.

## 8. Forgetting invariants

- propagation is not empty;
- retired node and synapse collections are capped;
- retired self-loop synapses are rejected;
- base validation binds generation advancement and retirement identity;
- durable deletion, index invalidation, artifact revocation and backup nonresurrection remain owner responsibilities.

## 9. Selector invariants

- byte/time/frame/region ranges are checked against the asset manifest;
- JSON Pointer syntax follows RFC 6901 escape rules;
- AST path, GUI node and JSON Pointer membership is checked in caller-supplied sets; the owner must verify that those sets belong to the supplied index digest and asset;
- selector index collections are capped;
- selector resolution never grants access to the underlying asset.

## 10. Consumer invariants

- all named consumer bindings must reference a closed-registry schema;
- schema flow (`input` or `output`) is enforced;
- mismatch metrics and cutover gates are unique;
- shadow state is derived from the two digests, not caller-selected;
- `cutover_eligible()` reports internal matched-state consistency; actual cutover additionally requires the owner’s acceptance and authenticated context;
- missing canonical or legacy output is not equality;
- rollback strategy and owner are mandatory.

## 11. Diagnostic values

`ContractFieldPathV1::new` and `ContractViolationV1::new` bound newly constructed diagnostics. Their serde representations and public diagnostic fields are not registered wire contracts and do not establish a permanent type invariant. Callers must validate or bound diagnostics received from elsewhere before storing or displaying them.
