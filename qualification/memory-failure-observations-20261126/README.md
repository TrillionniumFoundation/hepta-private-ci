# Observe existing memory test failures

This candidate is reconstructed on `752eae654d24345b0999a5b151250a2a60dbcd8e`
after the scratch reset. It is a new source cut; the previous unpublished
`fcbb6194` patch and review files were not recovered.

The original Intel peer-truncation test received zero completed peers instead
of sixteen. Its unchanged assertions now include the existing coverage object,
whose fields are fixed numeric counts. It contains no peer text or paths. The
original two-second federation budget and all expected counts remain unchanged.

The original duplicate-start test retained an active lease but observed zero
event rows. An active handle is also retained on admission or replay failure;
it is not evidence that an event was admitted. Test builds now remember the
last actual start outcome using a fixed enum, populated from the existing
acquire, replay and admission results while the original state guard is held.
The duplicate-start count assertions include that enum and the three existing
row counts. No payload, lease ID, database path or raw error text is printed.

The existing two starts, two stops, 250-ms I/O limits, original result handling,
authority checks, waits, locks and count assertions remain. No new I/O, retry,
clock or background task is added. Normal dependency builds contain no enum
or observation field. A later acquire attempt can overwrite the earlier start
observation; this is not a complete attempt history. An earlier active-handle
expectation failure still precedes the count diagnostic. Other lifecycle tests
and all production admission decisions remain unchanged.

The two old failures remain failures. These observations do not fix a timeout,
establish its cause, or qualify the new source. Original normal CI behavior is
still required; no new Rust or native execution was performed for this cut.
