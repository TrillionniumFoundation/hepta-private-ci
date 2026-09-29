# platform.types

Start with [CURRENT_IMPLEMENTATION.md](CURRENT_IMPLEMENTATION.md) for current
source and claim boundaries. The [technical guide](TECHNICAL.md) retains the
architecture, ownership and work-package history. Read the
[protocol contract](PROTOCOL_AND_QUALIFICATION_V1.md) for versioned identities,
transport and owner-pinned verification, and the
[2026-09-29 closure](OPTIMIZATION_CLOSURE_20260929.md) for Prompt capacity,
streaming/capacity optimizations, tests, performance methodology and acceptance.

Native Rust contracts and the compiled catalog govern protocol semantics.
Generated inventories are navigation; successful candidate receipts and eligible
independent review are separate evidence. Source existence is not activation.

The supported foundation remains authority-free and stateless. Prompt V1 bytes
remain frozen. Prompt V2 now admits only values within its frozen HPTC array
capacity; larger V1 observations are retained as V1, never silently truncated.

The [qualification integrity continuation](QUALIFICATION_INTEGRITY_20260929.md)
defines resource-attempt publication, stale-report rejection, independently
recomputed consumer test counts, and the existing-lane guard regressions.
