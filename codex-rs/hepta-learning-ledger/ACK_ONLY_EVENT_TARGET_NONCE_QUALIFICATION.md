# ACK-only event target and nonce qualification

This Unix-only qualification is disabled by default. It does not authorize
product execution, create Ledger records, or replace the required independent
RecoveryGrant and Witness checks.

Before an existing ACK may be reconciled, the reservation owner durably records
the immutable original event and then the grant nonce. The event key binds the
original Ledger identity, record, and Witness transition, not the grant's nonce
or issuance window. Files are created relative to the pinned directory, are
private to its owner, and are never removed automatically after partial writes.
The success receipt covers both persisted records.

The earlier nonce-only format does not identify which event a prior reservation
occupied. Such reservations remain untouched and require reconciliation; the
new format never silently accepts them as an empty journal. Stop older writers
before moving an existing directory to the new format: they do not participate
in the event reservation protocol. Directories without earlier reservations can
start using the event-aware format without changing their configured location.

The tests exercise a signed synthetic grant for an already reserved event,
nonce reuse after reopening, a process that exits without advancing the
Witness, and preservation of old-format bytes. They do not claim qualification
against physical power loss or independent production signing.
