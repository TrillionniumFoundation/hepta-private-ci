# Private original-delivery preparation continuation

This component preserves the original signed ingress and the actual fresh
writer receipt inside the existing required owner. It adds no material reader,
FinalUse route, enrollment, training permission or production activation.

`VerifiedPairedTurn` retains the exact ingress already checked against Core,
AuthBus and the current Root human owner. Canonical AuthBus claims plus the
original signature must reproduce the requested delivery. The retained route,
principal and exact purpose must still match. This additional correlation is
not a replacement for signature verification or the current human lookup.

The actual `ProductionDurableWriter::prepare_operation` transaction can return
one fresh receipt for the original-delivery slot. Only that non-replayed,
non-inherited result can create `FreshJournalPreparation`. It retains the same
writer `Arc`; no path, JSON observation or later lookup reconstructs it. The
record must still be Queued at the private handoff. A retained or indeterminate
operation returns historical metadata without a continuation.

`OriginalPairedContinuation` borrows the original verified turn and owns this
fresh result. It has no Clone, serialization, receipt accessor or public
constructor. The existing preparation-only API consumes the private result,
checks its retained payload against the original source, and discards the
receipt before returning `FreshPrepared`. That public response remains
metadata. Dropping or losing the private result cannot undo its journal commit;
the same delivery remains read-only after cancellation or restart.

The new engineering controls use synthetic metadata with real temporary
SQLite journals. They exercise concurrent preparation, destruction of the
actual held writer, reopen, original owner cancellation and caller loss. They
do not construct a successful `VerifiedHumanTurn` or a production participant.
The original signed protocol control additionally rejects changed signature,
message identity and route. The existing source-bound architecture selector
runs the original eight preparation controls plus four new controls with a
minimum of twelve; the original ten turn/admission controls remain separate.
Source and formatted bytes alone do not establish native execution.

## Remaining material boundary

No installed host target or preparation observation proves paired material
custody. The Root service still unconditionally refuses the paired destination
on its generic FinalUse lane. Preparation configuration still rejects an
installed paired dispatcher. The legacy Python intake refusal is unchanged.

Actual material entry must add its own fixed native consumer, retained source
handles and independent consumer state/frontier. It must revalidate the
original ingress and exact issuer/writer/effect/enrollment records, require
both original held UI and logind owners with one absolute deadline, and perform
its first read synchronously inside the actual consumer entry. The full human
verifier cannot be called while holding the Registry/request locks it would
reacquire. No Registry mutex may cross an await. Returning a future is not a
material-read permission. These remaining interfaces are not implemented or
activated by this preparation component.
