# control.runtime API contracts

## Production entry points

### `ControlRuntimeOwnerV1::open_fenced`

Starts the unique production owner and enforces the persistent generation fence. Initialization and same-generation restart require a zero predecessor anchor. A strict `N → N+1` transition requires the externally retained anchor for `N` and a new non-zero anchor for `N+1`.

### `ControlRuntimeOwnerV1::admit_owner_port`

Accepts a canonical producer envelope only after owner, generation, policy epoch, policy digest, payload identity, evidence, and freshness checks. The verifier result must bind the exact envelope digest. Freshness is checked both before and after verification.

### `commit_decision`

Consumes an authenticated owner port once and durably appends the exact canonical decision envelope before later authority or dispatch transitions.

### `record_authority_request` and `consume_independent_authorization`

Persist the request and independent authorization as separate exact-attempt records. Authorization is validated against operation, candidate, plan, payload, snapshot, revocation frontier, and expiry.

### `mark_dispatched`

Re-samples owner-controlled time and rechecks current snapshot, revocation frontier, final payload, and grant expiry immediately before the durable dispatch transition.

### `record_terminal` and `reconcile_indeterminate`

Bind terminal evidence to the exact attempt. `Indeterminate` remains non-success and may only move to `Reconciled` through explicit observed evidence. It is never an instruction to resend.

### `admit_runtime_module_promotion_v1` and `promote_bound_runtime_module_v1`

Create and consume an opaque transition token bound to the complete candidate and topology tuple. Final use rechecks both trusted time and the current registry.

### `ProductionOrganHostV1::admit`

Validates the graph before indexing routes, rejects unsupported feedback or buffered profiles, and enforces fan-out and output budgets.

## Reference-only surfaces

The following remain public for compatibility, testing, protocol tooling, or migration and are not the production composition root:

- `PlannerStoreV1::append` and `compact`;
- `ControlRuntimeExecutionConsumerV1`;
- raw `OrganHostV1`;
- raw `RuntimeModuleRegistryV1::promote_after_handoff`;
- caller-supplied-time planning helpers.

Production callers must enter through `ControlRuntimeOwnerV1`, the bound module-admission API, and `ProductionOrganHostV1`.
