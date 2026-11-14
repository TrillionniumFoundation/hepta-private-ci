# Original finite Notes Organ component

Frozen8cdd135ac passed all original15 Agentd/Fleet/Notes tests in85.996s,
without retry. Scoped Agentd fix and explicit committed-range format/check
passed without changing source; no semantic test followed finish. The actual
retained test ELF is40aa80c7; its single-link read-only bytes were verified.

The repaired drain reads Fleet state outside the already held run mutex.
The original reconciler is restricted to its attached Notes destination;
original Device grants, dispatch and observation remain outside that scope.
The fixture retains original production30s defaults, bounded claim5000ms,
10s local waiter, real clocks and predecessor evidence checks. Three legal
independent HOS2 namespaces prevent unresolved D1 from authorizing D2.
Actual receipt state and issuer/device sequence are asserted before worker start.

The original deadlock and both14/15 intermediate failures are preserved,
alongside the complete15/15, source, ELF provenance, fix and format logs.
This is a component result under explicit Root/issuer/application fixtures.
The integrated physical material/capture/cold owner, actual Reserved Session,
native release size, whole final workspace and device G2 remain unqualified.
See [the source contract](../../README.md) and [original bytes](publication.json).
