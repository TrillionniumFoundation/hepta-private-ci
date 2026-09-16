# Self-iteration runtime ledger

`IterationLedgerV1` is the bounded bookkeeping slice for governed self-iteration. It
stores one validated `IterationEnvelopeV1`, at most the envelope candidate budget,
and an append-only sequence of externally produced evidence receipts.

The ledger accepts candidates only in `Drafted` state. Every subsequent state
transition must provide the matching evidence kind (`Sandbox`, `Evaluation`,
`Selection`, and so on). Evaluation, review, selection, promotion, release and
terminal decisions must use an actor distinct from the candidate generator. A
candidate cannot bypass a state, reuse an evidence identity, or exceed the fixed
384-event ceiling.

`IterationLedgerV1` does not execute sandboxes or evaluators and does not grant
selection, merge, promotion or release authority. Callers must authenticate
receipts and enforce the external authority boundary before appending them.
Snapshots are reconstructed by replaying the event sequence; a supplied current
state without matching events is rejected.
