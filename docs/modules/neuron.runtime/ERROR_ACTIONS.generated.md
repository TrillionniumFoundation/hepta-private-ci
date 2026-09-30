# neuron.runtime generated error actions

Generated from `docs/modules/neuron.runtime/MODULE_SPEC.json`. Stable codes remain low-cardinality; retained evidence must carry the internal stage and correlation identity.

| Stable code | Required operator action |
|---|---|
| `owner_busy` | retry with bounded backoff; inspect owner lock wait/hold evidence |
| `owner_poisoned` | stop serving; recover owner from durable state |
| `controller_busy` | retry control operation; inspect drain and lifecycle contention |
| `controller_poisoned` | stop lifecycle mutation and reconstruct controller |
| `not_serving` | do not dispatch; inspect lifecycle state |
| `invalid_lifecycle_transition` | reject caller intent and use documented transition order |
| `generation_conflict` | reject stale generation and reload current descriptor |
| `pending_recovery` | run exact-operation recovery; never redispatch blindly |
| `unknown_generation` | fail closed and inspect durable generation topology |
