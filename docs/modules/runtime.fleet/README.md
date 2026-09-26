# runtime.fleet documentation index

Read these documents in this order:

1. [`DURABLE_OWNER.md`](DURABLE_OWNER.md) — current source implementation, durable datasets, transaction model, resource semantics, supervisor composition and remaining product boundary.
2. [`OPERATIONS.md`](OPERATIONS.md) — metrics, alert thresholds, recovery commands, forbidden operations and physical qualification matrix.
3. [`IMPLEMENTATION_MAP.json`](IMPLEMENTATION_MAP.json) — machine-readable operation-to-source/test mapping and conservative claim boundary.
4. [`TECHNICAL.md`](TECHNICAL.md) — stable module contract, ownership and long-lived architectural requirements.
5. [`runtime.fleet-durable-owner.md`](../../../qualification/module-execution-dossiers/detail/runtime.fleet-durable-owner.md) — current execution/qualification dossier for the durable-owner candidate.

Where historical text in `TECHNICAL.md` describes the lease ledger as only an in-memory component, `DURABLE_OWNER.md` is the current implementation statement for this candidate. This precedence applies only to source implementation facts; it does not override the stable authority, activation, acceptance or release boundaries.

Current truth summary:

- the existing `hepta-supervisord` process is the only fleet owner;
- durable owner generations, canonical resources, trusted Linux capacity observation, authority-bound issue, revocation snapshot restore and final-use verification APIs are source implemented;
- the supervisor maintenance caller is source composed;
- a concrete Agent/worker physical-use caller is not yet composed;
- selected-host qualification, independent acceptance, activation and release remain false until exact-candidate evidence exists.
