# Lock ownership across failed construction

Applies to the existing causal ledger and sparse neuron journal. This is a
bounded recovery correctness fix within LRN-1/NEU-2, not a new service or authority.

An owner-level destructor is too late if construction returns an error before
that owner exists. A duplicated/inherited open description can then retain an
acquired file lock after the constructor's local File closes. Repeated recovery
can unexpectedly return Busy instead of the actual corruption or missing-history
error. The deterministic regressions retain one test-only duplicate and exercise
already-initialized creation and failed recovery before the store is constructed.

Each crate now uses a private LockedFile immediately after successful acquisition.
That guard owns explicit best-effort unlock on every normal return path, including
validation failure. A failed acquisition never constructs the guard and therefore
never releases another writer's lock. Successful construction moves the guard into
the existing owner. No public raw handle is exposed, no retry loop is added, and
no fault test is removed or serialized. Existing commit synchronization, poison
states, recovery anchors, file formats and byte-level golden vectors are unchanged.

The regression duplicates are not a supported production-sharing pattern. The
host still supplies separately opened, authorized files on a suitable filesystem.
Locks may be advisory or mandatory; this does not isolate a malicious writer.
Forced process termination still relies on OS descriptor closure and does not
execute Rust destructors. This fix is not a physical power-loss guarantee.

Review the two small guards, acquisition sites, then the three new Linux-specific
before/after regressions. The existing cross-platform test matrix remains intact.
All exact-candidate checks and independent durability review are still required.
