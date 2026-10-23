# Original owner physical barrier and pre-effect Current

Frozen2ff0a02710 passed74/74 original-owner tests without retry. The original67
required cases all ran and passed in this same run, including9 real SIGKILL
scenarios in23.521s under their original60s watchdog. Scoped Memory/State fix
completed without source changes and the explicit committed-range formatter
check passed. Original test ELF3b74c3f8, actual source path and retained read-only
single-link binary were verified separately. No semantic test followed finish.

The former read-only BEGIN IMMEDIATE exclusion claim was disproved by actual
competing commits and remains withdrawn. The repaired owner uses the original
SQLite database's private physical writer-lock-only connection: real BEGIN,
query_only after acquisition, permanent deny-COMMIT and close-on-drop. Ordinary
observation remains physically read-only and does not mark Current dirty.
Tests directly observe SQLite BUSY while the lock is held, reject writes even
after query_only is disabled, and preserve the original permanent commit gate.

Before original synchronous Notes/HOS2 entry, the same owner retains its exact
Entered facts and obtains a bound whole-owner Current acknowledgement before
FinalUse claim/enter and the original channel call. The physical barrier spans
that synchronous boundary. Lost ACK, cancellation, revocation, missing barrier
or expired original claim refuses dispatch and fences the owner. Known FinalUse
rejection releases the physical lock before original durable settlement; a
rejected stale checkout cannot turn into a newly authorized writer.

The actual negative made1 channel entry when0 was required. Original compile
failure,66/67 missing-fence failure,73/74 stale-checkout fixture failure and final
74/74 are all preserved. The old read-only barrier red logs are also retained
in the separate retirement-counterexample publication; passing short pending
observations never replace an actual exclusion proof.

These are original SQLite/owner and explicit issuer/checkpoint/channel fixture
results. They do not qualify installed Root, physical image publication, real
devices, whole-process cold recovery or adapters that defer their effect until
an arbitrary returned Future is polled. Cancellation coverage is a pending
acquisition test, not every possible initialization instruction. The new Root
material/capture composition requires its own same-source qualification.
No large executable, private database, key or compiler target is published.

See [the full original-byte manifest](publication.json),
[the counterexample](../2026-10-23-retirement-counterexample/README.md), and
[the effect-entry contract](../../OWNER_PUBLICATION_BARRIER.md).
