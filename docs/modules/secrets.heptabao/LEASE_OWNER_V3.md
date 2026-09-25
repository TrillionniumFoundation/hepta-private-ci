# Secret lease owner and registered consumption V3

This is the current implementation contract for PR #998 on
`codex/secrets-heptabao-convergence`. It complements `TECHNICAL.md` and does not
activate a daemon, certify an external provider, or grant release authority.

## Owners and executable entrypoints

`DurableLeaseRegistryV1` remains the single metadata writer. The historical type
name is retained for source compatibility; its persistent document is schema 3.
It owns lease records, lease operation history and secret-consumption operation
history. It never contains a provider token or secret value.

`BaoFinalUseHost::consume_kv_v2_with_authbus` is the registered, operation-aware
source integration. It combines independent approval, a signed revocation feed,
AuthBus policy/reservation/dispatch/settlement and this durable writer. The
low-level `BaoClient` API remains an explicitly trusted source adapter, not an
automatic production admission endpoint. A normal Agentd/App Server bootstrap
must select the protected configuration and real registered consumer; such
process activation is not established by these APIs or their fixtures.

`RegisteredBaoConsumer::for_operations` binds a consumer ID, nonzero immutable
implementation/configuration digest, operation-aware callback and observer.
The callback receives the original operation ID and complete semantic digest.
The optional `BaoReadRequest.consumer_configuration_sha256` is part of the
independently signed request digest. The product ingress requires it to match the
registered profile; changing only host configuration cannot silently reuse an
old approved binding. Omitting the field preserves legacy KV binding bytes but
cannot enter this operation-aware product ingress.
Its observer must query the original effect, never re-execute it. A legacy
closure-only registration cannot enter the durable product path. Independent
issuer, approver, revocation-distributor, time and settlement keys remain outside
the adapter. Test keys exist only inside synthetic fixtures.

## Persistent identity and history

The document contains `schema_version`, monotonically incremented `revision`,
`time_frontier_unix_ms`, `operations`, `leases`, and `consumptions` maps.

Each new lease operation binds operation ID, kind, nonzero semantic digest,
provider lease ID when known, expected generation for mutations, observation
time and resulting generation when applied. A terminal result also stores its
immutable `result_lease` snapshot and exact `result_observation`.

`operation_result` returns that original snapshot, not the current mutable lease.
An identical terminal observation is idempotent without incrementing revision.
A changed observation conflicts. An identical issue request remains idempotent
after its resulting lease ID has been assigned. `lease(id)` is instead a current
metadata projection; neither result is an authorization for new secret use.

## Lease transitions

| Input | Preconditions | Persisted result |
|---|---|---|
| `prepare_issue` | New operation identity, nonzero digest, reserved capacity | Prepared issue with no invented provider lease |
| Issue observation | Matching pending issue, unique valid active generation-1 lease | Applied operation, associated lease and immutable result |
| `prepare_renew` | Active renewable lease, no pending mutation | Prepared mutation bound to current generation |
| Unknown renewal | Original pending operation and valid fence | Unknown operation and RenewUnknown lease |
| Renewal observation | Same lease/generation, ordered observation, no pending revocation | Next generation and immutable operation result |
| `prepare_revoke` | Nonterminal lease, no existing pending revocation | Revocation takes priority over an in-flight renewal |
| Unknown revocation | Original pending operation | RevokeUnknown without fabricating successful revocation |
| Revocation observation | Matching lease/generation and ordered observation | Revoked, nonrenewable next generation |
| `expire_at` | Monotonic trusted owner time | Expired, nonrenewable next generation; pending work cannot resurrect it |
| Denied/NotApplied | Matching pending operation | Denied operation; restore only compatible nonterminal projection |

Renewal may shorten remaining TTL. What must be monotonic is the trusted
observation order and local generation, not the provider-selected expiry.
Expiry must still be after the observation time. A stale observation cannot
replace a newer generation or a terminal lease. The time frontier persists even
when an expiry scan changes no lease, so a later scan cannot roll back time.

The local observation API is a trusted owner interface, not a signed provider
wire protocol. Caller-supplied observations must not be exposed as unauthenticated
network mutation authority. Provider-native dynamic endpoints remain gated.

## Migration and missing historical facts

Schema 1 and 2 are read deterministically and upgraded in memory to schema 3;
the next successful write publishes schema 3. A previous snapshot never proves
the original operation result. No singleton issue/lease association is inferred.
Old terminal results and old mutations without a provable generation are marked
`legacy_binding_incomplete`. Their historical result query returns
`LegacyRequalificationRequired`. Records remain visible for controlled external
reconciliation. This is an explicit migration boundary, not silent data loss,
not an invented success and not permission to reissue an unknown lease.

## Single-writer and storage protocol

The Unix profile requires an owner-owned 0700 parent and owner-owned, single-link
0600 regular state/lock files. Symlink final components and unsafe metadata are
rejected; files are opened with `NOFOLLOW`. Non-Unix profiles fail closed until an
equivalent owner/ACL and locking implementation is qualified.

The lock file is held for the entire owner lifetime. Its device/inode is checked
before writes, so unlinking/replacing the lock fences the original writer.
Multiple objects and processes cannot both be accepted writers. The lock file
also contains a synchronized initialization marker: a missing previously
initialized state file is an error, not a fresh empty registry.

Commit sequence:

1. Validate cross-record state and the full encoded byte budget.
2. Create an owner-private unique replacement file and write all encoded bytes.
3. Synchronize the replacement file.
4. Rename it over the original file.
5. Synchronize the parent directory before reporting success.

A pre-replacement failure retains the predecessor. Rename errors and failed
post-rename synchronization produce `CommitIndeterminate` and fence the owner.
No repeated request or result query through that owner can turn uncertainty into
a confirmed success. Reopen validates the durable image under a newly acquired
exclusive lock. Temporary files are never treated as committed observations.

The marker detects missing initialized state, not restoration of both state and
marker from an old backup. Protection against that attack still requires an
external monotonic trust/epoch frontier and an operator recovery procedure.

## Capacity and complexity

Maximum encoded store size is 8 MiB. Individual lease metadata is at most 16 KiB;
operation/lease/consumption maps each retain a 65,536-record hard ceiling. Issue
and renewal admission retain control headroom; pending lease and consumption
results reserve future encoding space on every commit. Exceeding the limit
rejects before replacement and preserves the previously reopenable image.

The owner deliberately remains a bounded JSON-snapshot pilot. It copies and
validates history and rewrites the file for each commit. No unbounded-history,
constant-cost append, automatic retention, safe archival or high-throughput
claim is made. Archival must preserve operation deduplication, immutable results
and revocation history before increasing the pilot ceiling. Deleting records to
make room is not an acceptable recovery method.

## Registered consumption and recovery

The complete consumption digest binds the exact AuthBus effect/request, operation
ID, policy revision, quota key/revision/amount, deadline, signed grant, signed
approval and registered consumer configuration digest.

| Durable state | Meaning and allowed recovery |
|---|---|
| DispatchAttempted | Original identity durably reserved; no automatic redispatch, even if provider entry is not known |
| DeliveryPrepared | Validated response receipt committed before the final live authority check; this is NOT evidence that the consumer ran |
| ConsumerSucceeded | Registered consumer returned success and that observation is durable; quota settlement may still be pending |
| Indeterminate | Callback failed after entry, or its terminal outcome is uncertain; query the original registered observer |
| Succeeded | Original consumer result and AuthBus settlement are both recorded; retries return historical metadata only |

The provider receipt is committed before the final live-authority recheck. Thus
filesystem waiting cannot create an authorization gap between an earlier check
and effect entry. Revocation-feed freshness is checked again before invoking the
registered callback. Callback execution itself does not hold the authority mutex.

A successful retry does not fetch the secret, spend quota again or re-enter the
consumer. Unknown or incomplete operations never become a new attempt. Recovery
uses `reconcile_consumption`, which intentionally takes no `BaoClient`: it queries
the enrolled original observer and settles the original reservation. It verifies
reservation operation ID, effect digest, amount and already-settled terminal
receipt digest. A mismatched consumer configuration rejects recovery.

An observer's Unknown or NotApplied observation currently remains pending rather
than being converted to a refund or invented success. Likewise, a failure before
a reservation/response is durably associated needs owner reconciliation. These
conservative stop states are visible through `consumption_result`; automatic
compensation and provider-side operation lookup are not yet implemented.

## Verification and nonclaims

Original lifecycle cases remain. Additional tests cover multi-object and
cross-process writer exclusion, immutable result recovery, idempotent completion,
ordered shorter-TTL renewals, revocation/expiry non-resurrection, migration with
missing facts, capacity failure, missing files, private permissions/hardlinks,
lock replacement and uncertain-commit retry.

Native registered-host tests use real loopback TLS, real AuthBus stores and the
same durable owner. They exercise one-effect success/retry, settlement outage,
consumer acknowledgement loss with an independently queried durable outcome, and
revocation after durable preparation. They are synthetic source integration
fixtures, not a selected production daemon or external dynamic lease acceptance.

`qa/qualify.py` runs formatting, all-target tests and strict Clippy independently,
records every exit status/log digest, checks exact HEAD/tree and clean tracked
source, and fails if any gate fails. Lane A includes independent source-head and
deterministic-merge native jobs; a document failure cannot suppress these jobs,
and native success cannot override an existing document failure.

`qa/probe_dynamic_lease_contract.py` starts only a new synthetic TLS instance at
the fixed external source pin. An unsupported endpoint exits 2 and records a
provider blocker. Healthy KV reads do not count as dynamic lease E2E. Source
presence, local receipts and this document do not authorize merge, production
activation, independent acceptance, promotion or release.

## Fixed provider observation, 2026-09-25

The pinned `HeptaBao@eac9c608bfda77a8972e1e8a1343dfc21985d62b` was built on
Linux with its locked dependencies. A fresh synthetic TLS service returned 200
for KV write/read, 501 for a database mount, and 404 for database credentials and
lease lookup/renew/revoke endpoints. The probe exited 2. The source-bound result
is `codex-rs/hepta-bao-adapter/qa/evidence/dynamic-contract-probe-20260925.json`.
This is a verified provider-contract blocker, not dynamic lease qualification.

The AuthBus dependency now obtains WAL/FULL authority pools and a single-connection
transient schema oracle through the existing state owner's lightweight `codex-state-sqlite` subpackage. Its
five-connection, foreign-key and busy-timeout behavior is retained. Connection
ownership is centralized without moving AuthBus's migrations or authority facts.

The connection primitives live under `codex-rs/state/sqlite`, with no domain state
or migrations. The existing state runtime delegates to the same factory; AuthBus
does not acquire a dependency on the full Codex protocol/history/runtime stack.

## Typed source inputs and native test denominator

`BaoApprovedReadV1` groups admission, grant, independent approval and exact
request for the registered host. `BaoAuthorizedReadV1` groups the corresponding
low-level authority tuple; it is not a minted authorization. The grouped APIs
replace long positional argument lists without dropping any signed fields.

Native feedback executes adapter and lightweight SQLite-owner tests, their
strict all-target Clippy, formatting and the AuthBus live-schema regressions.
The Python qualification tests prove exit propagation and receipt binding only;
they must not be counted as Rust/provider execution.
