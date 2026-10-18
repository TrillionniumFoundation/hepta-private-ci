# Cell split and differentiation lineage (shadow-only)

This qualification contract turns Cell splitting into an immutable lineage decision. A parent artifact is bound to its Stem, adapter/head, capability manifest, snapshot, generation, modalities, and artifact digest. A split proposes at least two new child identities. Each child must have a matching evaluation ledger with the same benchmark, task-quality lower bound, regression, calibration, OOD, latency, memory, safety, and rollback evidence.

The decision accepts only children that pass every hard gate. It is deterministic and keeps `authority=DENY_ALL` and `effect_admitted=false`. Revocation produces a typed digest-bound receipt; it does not call a worker or alter owner state. A production registrar must separately materialize child artifacts, route them through calibrated gates, and retain parent rollback.
