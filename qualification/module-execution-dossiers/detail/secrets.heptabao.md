# secrets.heptabao: implementation design

Parent: `docs/modules/secrets.heptabao/TECHNICAL.md`. Lane:
`LANE-A-FOUNDATION`.

Status: exact-version KV v2 consumption and repository-owned SecretLease
issue/renew/revoke lifecycle source are implemented. Provider readback for a
lost dynamic-lease issuance response, product composition, distributed
authority state and independent acceptance remain external/open gates.

## 1. Source and work envelope

Roots: `external/HeptaBao`, `codex-rs/hepta-bao-adapter`.
Package: `HEPTABAO-1-SECRET-BOUNDARY`.

The adapter reuses the existing enrolled `BaoClient` transport and
`kernel.authority::FinalUseAuthority`; it does not introduce another trust or
network spine.

## 2. Public operations

Implemented native operations:

- `consume_kv_v2(authority, grant, request, consumer) -> BaoSecretReceipt`;
- `request_secret_lease(registry, authority, grant, request, now, consumer)
  -> SecretLeaseIssueOutcome`;
- `renew_secret_lease(registry, authority, grant, request, now)
  -> SecretLeaseMutationReceipt`;
- `revoke_secret_lease(registry, authority, grant, request, now)
  -> SecretLeaseMutationReceipt`;
- `reconciliation_binding(...)` produces the exact independently signed
  observer proposal;
- `reconcile_issue_observation`, `reconcile_renew_observation`, and
  `reconcile_revoke_observation` consume a fresh observer grant and move only
  a matching `Unknown` operation forward without replaying the provider effect.

Ordinary receipts contain lease/reference metadata and digests, never raw
secret values. Dynamic secret values exist only in bounded zeroizing response
objects passed synchronously to the trusted consumer.

## 3. State records and transaction design

`LeaseRegistry` is the local authoritative metadata owner and uses SQLite/WAL
with full synchronous durability. It stores no provider secret values.

Lease state:
`Issuing | Active | Renewing | RevokePending | Revoked | Expired | Unknown`.

Operation state:
`Prepared | InFlight | Applied | Rejected | Unknown`.

Every effect persists `operation_id + operation kind + lease identity when
known + semantic_sha256` before dispatch. Exact retries return the existing
operation; changed semantics conflict. Renew/revoke persist the operation intent
and transitional lease state in one transaction.

## 4. Effect ordering and recovery

1. Validate bounded request and derive exact final-use binding.
2. Persist local operation intent.
3. For renew/revoke, atomically fence the lease into its transitional state.
4. Immediately before provider dispatch, claim the independently signed
   final-use grant and durably burn the nonce.
5. Enter exactly one provider effect.
6. Deterministic pre/at-boundary denial may become `Rejected`.
7. Any outcome that might have entered the provider but is not proven becomes
   `Unknown`. No blind repeat is issued.
8. A terminal provider observation reconciles Unknown forward through a separately
authorized observer ceremony. Registry effect-transition methods are
crate-private, so ordinary external callers cannot bypass that ceremony.

A dynamic-secret GET is treated as `LEASE_ISSUING_READ`, not a pure read.

Current HeptaBao source requires unknown external-effect reconciliation but its
operation ledger has no direct HTTP outcome endpoint. Consequently a lost
issuance response cannot yet be automatically mapped back to a provider
lease-id by this adapter. `reconcile_issue_observation` therefore requires an
authenticated observation supplied by the product/provider reconciliation
owner. This limitation is explicit and fail-closed. The observer grant authenticates
which host principal may assert the observation; it is not a substitute for a
provider-owned outcome/readback endpoint or other qualified terminal evidence.

## 5. Final-use replay storage

The final-use authority keeps `authority.json` as a compact trust/revocation
checkpoint and appends fixed-size `(authority_epoch, nonce)` records to
`claims.log`. Claim admission fsyncs one journal record rather than rewriting
the complete JSON set. The journal is the complete replay truth and restart
replays it; revocation/head persistence keeps the nonce set out of JSON and may
rewrite the journal only as an O(N) checkpoint/compaction. Legacy JSON snapshots
are migrated into the journal before compact publication.

The former 16,384 nonce-claim ceiling is removed. The 16,384 bound applies only
to the revocation-ID set. The local authority is still single-active per state
directory by OS lock. Active-active requires a separate strongly consistent or
sharded authority topology and is not claimed here.

## 6. Capacity and performance

- provider response bound: 1 MiB;
- dynamic secret fields: at most 64 string fields, each at most 64 KiB;
- lease duration/increment: at most 31 days in the current adapter profile;
- operation identity and metadata are bounded;
- claim hot path: one fixed-size append + fsync plus in-memory replay lookup;
- revocation/head checkpoint/journal compaction remains O(N) in retained nonce
  count but is not the per-claim hot path;
- replay memory and journal bytes grow with unique claims in a long-lived epoch,
  so epoch rotation and target-host capacity remain explicit operational gates.

Target-host latency, journal replay scale and disk-full behavior require
candidate measurements before production activation.

## 7. Security and privacy invariants

- no raw secret in ordinary return receipts, durable lease registry, logs or
  learning/export records;
- trusted callback selection is a host privilege, not established by a
  caller-controlled closure or by `consumer_id` alone;
- ordinary receipts omit secret-bearing response and delivered-value digests;
  expected KV digests stay inside the signed request and are checked before use;
  any owner-only secret-dependent diagnostic digest remains sensitive metadata;
- zeroization covers owned application buffers only and is not a whole-RAM
  secrecy claim;
- restoring/deleting authority state is an authority reset unless independently
  fenced by newer trust/epoch.

## 8. Current native implementation and remaining gates

Implemented source:

- `codex-rs/hepta-bao-adapter/src/https_consumer.rs`;
- `codex-rs/hepta-bao-adapter/src/lease_client.rs`;
- `codex-rs/hepta-bao-adapter/src/lease_registry.rs`;
- `codex-rs/hepta-contracts/src/final_use.rs`;
- `codex-rs/hepta-contracts/src/final_use_store.rs`.

Focused tests:

- `codex-rs/hepta-bao-adapter/src/https_consumer_tests.rs`;
- `codex-rs/hepta-bao-adapter/src/lease_registry_tests.rs`;
- `codex-rs/hepta-contracts/src/final_use_tests.rs`;
- real-service fixture under `codex-rs/hepta-bao-adapter/qa`.

Still open and not self-certifiable by this source:

- HeptaBao runtime operation-outcome/readback endpoint for automatic lost-
  issuance reconciliation;
- a named production caller and authenticated provider observation source;
- active-active/distributed final-use replay/revocation state;
- retained exact-head/synthetic-merge execution receipts for this candidate
  must be green; the Lane-A workflow generates SHA-named machine receipts;
- target-host capacity/fault qualification;
- independent semantic/operator acceptance, canary, promotion and release.
