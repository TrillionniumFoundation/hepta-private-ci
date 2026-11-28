# One mandatory receiver validation and transactional capacity

Base: `4686c861e54179690c4a668a356a4b0ce57639d5`. Register this scope and
`BASELINE.json` before freezing the implementation and invoking either phase.
This is a bounded engineering qualification, not a scientific training run.

## Implementation contract

The ledger remains responsible for complete packet validation before any
admission transaction. Its optional keyword `max_batches` defaults to None;
an explicit value must be a positive plain int, never bool. Inside the same
BEGIN IMMEDIATE, preserve the peer's refusal priority: already-over-limit
state, conflicting/exact existing batch, new-batch capacity, then head CAS.
An exact replay at the limit remains idempotent even with an obsolete head.
Ordinary uncapped ledger callers retain their existing behavior.

Peer dispatch passes its existing MAX_BATCHES to append. It no longer
validates the same new received packet twice or dereferences an unvalidated
packet body. Sender export and snapshot integrity validation are unchanged.
The existing crash-after-commit test hook forwards the new keyword unchanged;
its exit 71, lost-ACK classification, replay and numerical assertions stay.

The capacity guarantee covers capped append calls. A separate uncapped writer
can still exceed a cap; this optional parameter is not a persisted global
policy. The normal peer uses a serial TCPServer and a separate database per
owner. Do not claim its two queued requests alone expose the original race.

## Frozen controls

Use the existing synthetic TCP fixture (seed 48117, 5x2, lambda 0.2), with no
new data, tuning, original-cache access or changes to numerical thresholds.

1. On exact baseline source, send one actual TCP offer after fixture creation.
   Instrument the real receiver validate_packet and NumPy eigvalsh functions,
   forwarding all arguments/results. Expect two calls to each. Producer,
   sender-export and snapshot validation are outside this measurement.
2. Reproduce the old capacity failure using two actual spawned receiver
   processes, each running the original serial service against the same SQLite
   database, with a declared test capacity of one. Two concurrent client
   threads offer A and B; B supplies the independently computed post-A head.
   Timing-only barriers hold both real inventory reads at revision zero,
   then let A commit before B resumes. No query/validation result is forged.
   Retain the actual two admitted rows as a baseline capacity failure, including
   process IDs, overlapping timing, receipts and database state.
3. On candidate source, repeat the single new-offer count: one validation and
   one eigvalsh, with the complete same receipt and contribution identity.
4. Check malformed body and negative-PSD refusal over real TCP, strict explicit
   bound types, at-cap replay, conflict priority and new-batch rejection. The
   ledger must remain unchanged on each refusal; none becomes UNKNOWN.
5. Repeat the shared-database concurrent control on candidate source. Timing
   barriers hold both complete real validations before the transactions; A
   commits before B enters its transaction. B's predicted head must not bypass
   the capacity check. Require one accepted row and a bound refusal, with two
   distinct actual receiver processes and overlapping operations.
6. Execute the existing LedgerTests (4), PeerTests (4) and BinaryPeerTests (4)
   once against the changed source, including real lost-ACK/restart and numeric
   controls. The candidate suite has these twelve plus three new tests.

Baseline phase cap: 20 seconds. Candidate phase cap: 60 seconds. Whole scope
cap: 90 seconds, one BLAS thread. Stop on unexpected first failure; preserve
all observations, including the intentionally reproduced old capacity defect.
Any correction uses separately retained evidence without resetting spent time.
Freeze source before execution; format afterward, retain AST comparison and
do not repeat tests solely for formatting. No nine-parent replay is allowed.

Report measured call counts only. Halving one receiver validation path does
not establish total CPU, network, training or model-capability improvement.
