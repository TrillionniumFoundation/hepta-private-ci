# AuthBus durable operation composition

## Normative owner

`codex-hepta-operations::DurableOperationStore` is the sole production owner of
operation identity. AuthBus and Bao do not mint an operation identifier and do
not accept a caller assertion as evidence that an identifier is durable.

The product entry sequence is:

1. atomically prepare `DurableOperationIntentV1` and its source outbox;
2. claim that exact `(scope_id, operation_id)` under the current owner
   generation, lease and writer fence;
3. verify the expected destination and exact request payload digest;
4. consume the operation owner's independently signed final-use grant;
5. synchronously persist the operation as `Indeterminate` before asynchronous
   AuthBus/provider work begins;
6. pass only `EnteredAuthBusOperationHandle` into the Bao/AuthBus composition;
7. converge the operation only from independently supplied terminal evidence.

The entered handle privately binds:

- scope and operation identity;
- destination and request payload digest;
- operation semantic digest;
- owner generation;
- durable revision and writer fence.

A changed generation, revision or fence invalidates the handle before AuthBus
reservation or provider I/O. A crash after handoff cannot return the operation
to `Prepared`, and a later process must recover or adopt the same operation
identity. `MutationOutcomeUnknown` and provider ambiguity therefore never
justify constructing a new identifier or blindly retrying.

## Bao binding

`BaoClient::durable_operation_payload_digest(request)` is the payload digest
that must be stored in the durable intent. The destination must be exactly
`provider:heptabao`. `consume_kv_v2_with_durable_authbus_operation` derives the
AuthBus reservation operation ID from the sealed handle and returns one
correlation receipt containing the operation semantic digest, AuthBus effect
digest and provider receipt.

Provider success is not terminal operation authority. The return value keeps
`reconciliation_required = true`; a destination-owned observer must provide a
`ReconciliationReceiptV1` to
`DurableOperationStore::reconcile_entered_authbus_operation`.

## Non-claims

This source composition does not prove that a target deployment has selected,
provisioned and backed up the durable operation database. Target-host evidence
must bind the operation store path, filesystem/device identity, owner
generation, backup set and the AuthBus candidate SHA. Until that evidence is
terminal-success, production qualification and activation remain false.
