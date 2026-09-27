# Matrix canonical-content and physical-entry amendment

Status: source increment, not native-test success, deployment qualification or release. Date: 2026-09-27. This amendment updates the nine existing module guides for the content/permit changes below. Where older prose implies raw body hashing is complete payload authorization, or witness strings alone prove qualified execution, this amendment takes precedence. The existing guides remain the architecture, configuration, storage and operations references; no second Matrix runtime is introduced.

## 1. Exact source and remaining acceptance boundary

Runtime source observation: commit `4cbe8a21f3fc1a1261d8758437294b0eefb17e84`, tree `934ec781f04a2e7822a44d20d5d5b51cd197ba12`. It follows `e32c43a60f5b415587d87ac4aa5f7872ec188ed6` and the existing candidate `b09690f5c25c6cf9c2e834335ee0db5097c5969e`.

`IMPLEMENTATION_MAP.sourceBase` remains immutable provenance. `observedAtHead` identifies the code inspection snapshot. The candidate verifier emits the actual tested HEAD/tree, map bytes, source blobs and document hashes outside the commit. Requiring a committed file to embed its own future commit SHA is circular; it is not an executable freshness policy. Static marker checks establish navigation, not type checking, call-graph proof, authorization correctness or successful execution.

## 2. Actual owner and send sequence

```text
supervisor::start_matrix_companion
  -> matrixd::runner::run
  -> MatrixDurableStore + MatrixFinalUseBroker + MatrixSdkClient
  -> outbound_v2::dispatch_outbox_once
       claim_outbox_fenced
       prepare_outbox_dispatch / record_outbox_prepared
       build_matrix_final_use_request
       pin_outbox_content (same durable owner; no external effect)
       request independent signed grant
       refresh revocations / kernel claim
       persist witness metadata and authority claim
       record_outbox_dispatching (intent, not a physical-I/O receipt)
       final per-poll gate -> kernel entry -> MatrixSendPermit
       MatrixSdkClient::send_authorized
       record transport acceptance or indeterminate outcome
  -> authenticated Matrix sync -> canonical durable reconciliation
```

Initial durable sync still precedes inbox replay in the daemon. The send observer remains an alias to the durable owner state, not another BTreeMap or sender. The existing attempt-event history and remote-outcome ledger represent different facts: claiming, entering and observing are not interchangeable success receipts.

## 3. Canonical payload bytes

The signed proposal is now `MatrixFinalUseRequest` schema **2**. Both the signer proposal and real transport use `src/content.rs` to construct plaintext `m.room.message` content. Ordinary messages include `body` and `msgtype`; replacements also include `m.new_content` and the complete `m.relates_to` object, including the replacement event ID. Retargeting an edit changes the signed payload digest even when its text is unchanged.

The content digest is SHA-256 over this exact concatenation:

```text
UTF-8 "hepta.matrix.canonical-outbound-content.v1" + NUL
u64 big-endian event-type byte count
UTF-8 event type ("m.room.message")
u64 big-endian canonical-JSON byte count
canonical-JSON UTF-8 bytes
```

Objects are recursively key-sorted independently of serde_json map insertion order. Arrays retain order. Text is not Unicode-normalized. The producer only emits strings and objects. Invalid UTF-8 and body input above the durable 1 MiB ceiling fail proposal construction; that local ceiling is not proof that a homeserver accepts the resulting event size. The digest binds semantic plaintext, not random ciphertext produced by encryption.

The request digest domain changes to `hepta.matrix.final-use.request.v2`. Subject, room, homeserver, Matrix user/device, configured session generation, binding revision, operation, stable transaction, logical outbox identity and attempt remain bound through the scope/request envelope. A broker must explicitly implement schema 2 and independently approve the proposed content. There is no schema-1/raw-body fallback and no signing key in the adapter.

## 4. SDK boundary

The public SDK facade exposes session/configuration/sync operations but not a raw `matrix_sdk::Client`, a Deref escape or an ungoverned plaintext-send method. The real SDK's legacy `send` trait entry rejects without network I/O. `send_authorized` requires a non-cloneable, non-deserializable `MatrixSendPermit` with private fields; only the final gate can construct it from a genuine consumed kernel token and exact request binding.

The old session/sync implementation is retained byte-for-byte in the private `sdk_implementation.rs`; its internal raw-client helper is not a public escape. The facade owns one instance, not a duplicate transport. At the governed room send, SDK retry backoff is disabled so a second send attempt must return through the durable owner and a fresh grant. This does not claim that an encrypted SDK operation performs exactly one HTTP request internally.

Each continuation poll refreshes revocations and checks current epoch/revision, identity, cancellation, deadline and canonical digest before polling the send future. No detached physical work is allowed by the transport contract. This is not a global atomic lock over the network stack. A dropped already-entered future may already have written bytes and is therefore indeterminate, not canceled-with-no-effect. The protected clock, authenticated revocation feed and login/access-token transaction domain still require target qualification.

## 5. Storage and upgrade

Migration 8 adds `matrix_dispatch_content_bindings`, keyed by the existing stable transaction. It stores canonicalization version, canonical content digest, scope digest, original raw-body digest and pin time. The row is immutable; identical retry is idempotent, content/scope drift conflicts. Migration-6 raw-body digest columns are not silently reinterpreted as canonical digests. New pin admission uses the live random claim token, attempt and lease epoch in a SQLite writer transaction and compares exact table/trigger DDL.

Migration 9 adds `matrix_dispatch_legacy_content_holds`. It snapshots only existing, attempted outbox records which have no canonical pin. After migration, insert/update/delete of that snapshot is prohibited. This distinguishes inherited unknown effects from a new attempt canceled or crashed before its first pin. Such new work may acquire its first pin only when no legacy hold, authority claim, authority witness or possibly-entered attempt event exists. A pin is identity metadata, never an authorization.

No older migration is edited. These new critical-boundary DDL checks do **not** yet establish complete startup validation of every ledger object or protection against restoring an obsolete entire database. Old binaries must not be installed over upgraded state. Do not delete pins/holds, reset attempts, rename transaction IDs or erase the database to clear a blocked send.

## 6. Recovery disposition

| Cut or event | Required disposition in this increment |
|---|---|
| New claim canceled before pin | Release pre-entry claim; after reopen, same transaction may establish first pin when the durable history proves no prior authorization/entry |
| Legacy attempted row without pin | Hold; do not infer a new content/session identity or silently replay |
| Existing pin with changed edit target/body/scope | Conflict before grant acquisition |
| Cancellation/revocation/deadline before kernel entry | No transport entry; release only the pre-entry claim |
| Cancellation/timeout after entry | Preserve unknown external outcome and transaction identity |
| SDK returns event ID | TransportAccepted, not qualified Confirmed |
| Sync confirms while an attempt later rejects | Preserve observed terminality; do not overwrite it with failure |
| Authenticated redaction | Reconcile through the existing durable sync owner |

Item-level legacy-hold remediation and a bounded operator reconciliation command remain implementation work; currently a pin conflict can stop the sender. Generating another transaction is not a safe workaround.

## 7. Verification actually performed

27 local tests passed: 13 isolated migration-8 SQLite tests, six migration-9 snapshot tests, and eight verifier contracts using temporary Git fixtures. They cover constraints, reopen, immutability, historical/new distinction, exact file-byte binding, path escape and strictly boolean false claims. These are isolated files and temporary fixtures, **not** a full checkout build or native Matrix execution receipt. The new Rust canonical-content and real-store tests are source only in this increment. The permit compile-fail example is not reported as executed; the SDK currently disables doctests.

The prior candidate's downloaded source-head artifact from run `36278075076` was verified against its API ZIP digest and manifest file hashes. `candidate.json` passed, but `focused-tests.log` records a Cargo.lock/manifest mismatch under `--locked` (wrapper exit 102, cargo metadata exit 101). This corrects an earlier interpretation of step summaries. That old artifact cannot prove this increment. The lockfile remains unchanged here; removal of `--locked` is not a fix.

The existing CI now includes `test_channel_matrix*.py`, retains the local-unit log, checks actual source/document bytes and both source-head and deterministic merge candidates. Workflow definition, source mapping and Python success do not imply that native tests, clippy, formatting or a real homeserver passed.

## 8. Remaining merge and activation gates

Resolve the lockfile with the pinned resolver and review the resulting scoped diff; execute all native fixtures, strict lint/format and complete startup/migration tests. Close the kernel-proof-to-durable-authority-to-authenticated-terminal trust chain: public caller-filled witness metadata must not become qualified proof merely because a sealed physical send permit exists. Validate configured session generation against real authenticated login/access-token and encryption-session rotation.

Finally run the supported pinned unencrypted Synapse profile, encrypted-room rotation, ACK-loss/crash recovery, revocation-at-entry, redaction/restore and sustained-capacity scenarios with exact-candidate receipts. Independent operator/security acceptance, activation and release remain false. No enrollment, real production send, credential distribution, mainline merge or release is authorized by this source increment.

## 9. Subsequent source closure

Later commits supersede the source-gap statements above without changing their historical execution claims. Migration 10 now stores the non-constructible entered-use proof and makes qualified success/redaction depend on the exact claim, authority, content and proof tuple. Store open compares exact normalized SQL for the dispatch objects from migrations 6-11 and checks integrity, foreign keys, claims, content, use entries, terminal states and legacy holds.

Migration 11 gives every sealed legacy hold a durable `accepted` or `indeterminate` ledger row, closes stale claims with append-only evidence, parks active queue rows at the maximum signed schedule and installs an anti-reactivation trigger. Only authenticated sync may settle the original transaction. The five narrow migration-11 tests passed in the authoring harness; exact-candidate Rust/CI and real homeserver qualification are still required.
