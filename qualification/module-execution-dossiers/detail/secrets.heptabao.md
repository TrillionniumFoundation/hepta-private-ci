# secrets.heptabao: implementation design

Parent: `docs/modules/secrets.heptabao/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: exact-version KV-v2 consumption and the module-owned provider-native
SecretLease lifecycle are source-implemented. Product activation, exact-provider
dynamic-engine qualification and independent acceptance remain separate gates.
Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`.

## 1. Source and work envelope

Roots: `external/HeptaBao`, `codex-rs/hepta-bao-adapter`.
Package: `HEPTABAO-1-SECRET-BOUNDARY`.

This module owns secret-lease metadata and its operation ledger. It does not own
kernel final-use replay/revocation truth, provider credential values, operator
approval keys or product-process activation.

## 2. Public operations and contract details

Implemented source operations:

- `consume_kv_v2` — exact-version KV-v2 string-field consumption;
- `request_secret_lease` — provider-native dynamic-secret issuance;
- `renew_secret_lease` — provider lease renewal;
- `revoke_secret_lease` — synchronous provider lease revocation;
- `reconcile_secret_lease` — provider lookup reconciliation for an
  indeterminate renew/revoke;
- `SecretLeaseStore::reconcile_issue_observation` — trusted external
  observation path for an issuance ambiguity when no lease ID reached the
  caller.

All provider operations require the registered `BaoFinalUseHost` composition
for product use. The host binds a signed final-use grant, independent approval,
signed revocation feed and closed registered-consumer identity.

Ordinary returned records contain metadata only. Raw KV values or dynamic
provider credential data may enter only the registered consumer channel.

## 3. State records and transaction design

The external Bao/OpenBao authority remains the source of provider secret values
and provider lease truth.

Local `heptabao_leases_1.sqlite3` contains:

- provider lease ID, mount and namespace;
- registered consumer ID;
- exact request/scope digests;
- keyed secret fingerprint and fingerprint-key ID;
- renewable bit, issue/expiry timestamps;
- monotone rotation generation;
- state and revision.

It does not contain the provider credential JSON.

The operation ledger contains operation ID, operation kind, optional provider
lease ID, semantic digest, state, bounded provider-observation digest and
timestamps. States are `prepared`, `dispatching`, `applied`,
`not_applied` and `indeterminate`.

An identical operation ID + semantic digest is idempotent before dispatch.
Reusing an operation ID with changed semantics conflicts.

## 4. Deterministic algorithm, linearization and recovery

For issue/renew/revoke:

1. validate the typed request and exact consumer/lease binding;
2. prepare the durable operation identity;
3. validate/claim final-use authorization;
4. durably change `prepared -> dispatching`;
5. perform one provider request with no protocol retry;
6. classify a definitely rejected request as `not_applied`;
7. commit provider-observed metadata as `applied`, or retain
   `indeterminate` when the provider outcome cannot be proved.

A restart that finds `dispatching` or `indeterminate` does not resend the
operation.

For renew/revoke ambiguity, the local lease is fenced as
`renew_indeterminate` or `revoke_indeterminate`. Provider lookup settles the
current truth:

- active provider lease: update observed TTL/renewability; renew becomes
  `applied`, revoke becomes `not_applied`;
- absent/zero-TTL provider lease: local state becomes `revoked`; revoke becomes
  `applied`, renew becomes `not_applied`.

Issuance ambiguity is intentionally different. If the provider created a
dynamic credential but the lease-ID response was lost, a generic provider
lookup has no stable lease ID. The implementation therefore requires an
independently trusted provider/audit observation. Unknown stays indeterminate;
it never creates another dynamic credential as a probe.

Rotation generation is allocated transactionally and monotonically for one
provider mount + namespace + consumer + scope tuple.

## 5. Secret handling and fingerprint policy

Dynamic provider response bodies are bounded to one mebibyte and stored in a
zeroizing byte buffer. The provider `data` JSON is borrowed from that buffer
and is passed only to the final registered consumer callback.

Durable secret-derived metadata is HMAC-SHA-256 under host-provisioned
`BaoReceiptKey`; it is not a plain value SHA-256. The key is not persisted by
the adapter and its `Debug` representation is redacted. Fingerprints remain
sensitive correlation metadata and require host retention/access policy.

Zeroization covers adapter-owned buffers only. It is not a claim that TLS,
HTTP, allocator or operating-system internals never retain transient copies.

## 6. Capacity and performance profile

Current module-owned bounds:

- response body: <= 1 MiB;
- one provider operation per API call;
- renewal request increment: 1..604800 seconds;
- accepted provider lease duration: 1..2678400 seconds;
- local lease records: <= 250000;
- local operation records: <= 1000000;
- reconciliation page: 1..1024 operations.

The SQLite ledger uses indexed point operations and `BEGIN IMMEDIATE`
transactions; one claim does not rewrite the whole lease registry.

These bounds do not change the shared kernel-authority replay compatibility
store. Its replay capacity/storage/HA work is separately owned by
`kernel.authority`.

## 7. Concrete verification cases

- BAO-01: raw secret bytes are absent from durable lease rows, ordinary return
  values and debug formatting;
- BAO-02: rotation generation is monotone for the same scope;
- BAO-03: a dispatching operation survives restart and cannot be blindly
  reissued;
- BAO-04: renew ambiguity fences use until provider lookup reconciliation;
- BAO-05: revoke ambiguity + provider absence becomes terminally revoked;
- BAO-06: an issuance ambiguity without a received lease ID requires a trusted
  observation and cannot auto-retry;
- BAO-07: keyed fingerprint changes with the receipt key and does not expose
  the HMAC key through `Debug`;
- BAO-08: dynamic issuance delivers provider data only to the final-use
  consumer while persisted metadata contains no credential value.

Source test identities:
`src/https_consumer_tests.rs`, `src/lease_client_tests.rs`,
`src/lease_store_tests.rs`, and registered-host tests in
`src/final_use_host.rs`.

## 8. Current native implementation and remaining integration

Implemented source:

- `codex-rs/hepta-bao-adapter/src/https_consumer.rs`;
- `codex-rs/hepta-bao-adapter/src/lease_client.rs`;
- `codex-rs/hepta-bao-adapter/src/lease_store.rs`;
- `codex-rs/hepta-bao-adapter/src/final_use_host.rs`;
- `codex-rs/hepta-bao-adapter/migrations/0001_secret_lease.sql`.

Remaining integration/evidence work is not an unimplemented module API:

- select a named product-process caller and production state root;
- provision `BaoReceiptKey` and authority/approval/revocation trust through
  protected host/KMS/operator channels;
- exercise provider-native dynamic issue/renew/revoke/lookup against the exact
  enrolled OpenBao/HeptaBao source pin;
- retain exact-head and deterministic synthetic-merge execution receipts;
- qualify target-host recovery, backup/anti-rollback and operator procedures;
- close the separately owned `kernel.authority` replay scalability and
  distributed active-active boundary;
- independent acceptance, canary, promotion and release.

No source document or passing repository-owned test grants those external
states.
