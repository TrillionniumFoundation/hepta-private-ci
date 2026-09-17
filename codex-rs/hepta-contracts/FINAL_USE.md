# Final-use authority and independent issuer

This document specifies the executable final-use admission boundary used by the
[HeptaBao HTTPS consumer](../hepta-bao-adapter/README.md). It supplements the
stable `kernel.authority`, `runtime.supervisor` and `secrets.heptabao` module
guides. The existing H7 upgrade/rollback signer and the legacy Bao metadata
projection keep their existing semantics.

## Ownership and trust

`final_use.rs` owns validation and the non-constructible `VerifiedUseToken`.
`final_use_store.rs` owns durable replay/revocation state. The host supplies one
pinned Ed25519 public key, signer identity, initial revocation head and private
state directory through its protected configuration channel. There is no
permissive default, signing key in the verifier, or conversion from a boolean,
`Granted` projection or unsigned proposal to a verified token.

The separately invoked supervisor binary `hepta-final-use-signer` owns the
explicit signing operation. The adapter must not invoke it to authorize its own
requests. A trusted owner reviews the complete proposed binding and chooses the
subject, destination, epoch, nonce and time window before invoking the command.
Access to the signing key is the issuer authority boundary.

The Rust callback, public-key configuration, destination enrollment and state
location are trusted host inputs. This library is not a sandbox for untrusted
code in the same process or Unix account. Protect configuration, directory
ancestors, clock and issuer key.

## Wire and signing schemas

All grants use `schema_version = 1`, deny unknown JSON fields, and serialize
integer byte arrays. The signing preimage is
`hepta.kernel.authority.final-use.v1\0` followed by compact JSON encoding of the
validated `FinalUseGrant` in declared field order. Changing field order,
encoding or semantics requires a new version/signing domain.

| Type / field | Meaning and bound |
| --- | --- |
| `FinalUseBinding.subject_id`, `destination_id` | Exact principal and effect destination; bounded ASCII identifier |
| `request_sha256` | Nonzero digest of the complete adapter operation |
| `scope_sha256` | Nonzero digest of destination/resource/consumer scope |
| `payload_sha256` | Nonzero digest of the expected payload/operation parameters |
| `FinalUseGrant.signer_id`, `grant_id` | Bounded owner and revocation identifiers |
| `authority_epoch` | Nonzero epoch; exactly equals the current durable head |
| `nonce` | Nonzero 32-byte single-use value, unique within an authority epoch |
| `not_before_unix_ms`, `expires_at_unix_ms` | Host-clock bounds; positive interval <= 300,000 ms |
| `SignedFinalUseGrant.signature` | Exactly 64 raw Ed25519 signature bytes |
| `FinalUseRevocations` | Epoch, monotonic revision and at most 16,384 revoked grant IDs |

For HeptaBao, operation bindings include the enrolled HTTPS origin, CA digest,
provider namespace/resource, consumer and destination identity. A replica-aware
destination such as `provider:heptabao:node-a` makes the signed grant non-portable
to another replica.

## Durable schema and storage protocol

The supported store is an owner-controlled local Unix filesystem providing
process locks, atomic same-directory rename and file/directory fsync. Other
platforms reject configuration until an equivalent backend exists. Distributed
or NFS lock behavior is not qualified by the local tests.

The root directory must belong to the effective user and have no group/world
permission bits. Directory/file opens use `NOFOLLOW`; regular-file ownership,
link count and permissions are checked.

### State entries

| Entry | Contents and invariant |
| --- | --- |
| `authority.lock` | Owner-only regular file; exclusive OS lock held by the shared authority owner |
| `authority.json` | Schema 2 trust/revocation snapshot: signer ID, verifying key and revocation head only |
| `authority.next` | Temporary complete metadata replacement used before atomic rename |
| `authority.claims` | Append-only fixed-width replay journal; each record is 8-byte epoch + 32-byte nonce |

A successful claim appends exactly one 40-byte record to `authority.claims` and
calls `sync_data` before dispatch. Steady-state claim persistence therefore does
not serialize or rewrite the complete replay set. Restart scans the journal,
loads only records for the current epoch, rejects zero/future-epoch malformed
records and reconstructs the current replay set in memory.

The journal has a 1 GiB fail-closed local resource/corruption guard. This is not
the former 16,384-claim semantic limit: an epoch can exceed 16,384 admitted
claims while storage remains within the qualified resource envelope. A resource
failure makes the live authority unavailable rather than evicting old replay
facts.

Revocation/trust updates serialize the small schema-2 metadata snapshot to
`authority.next`, fsync it, rename over `authority.json` and fsync the directory.
An epoch increase fences all old grants and clears the current in-memory nonce
set; old journal records remain durable but no longer collide with the new
epoch.

### Legacy migration

A schema-1 `authority.json` containing `used_nonces` is accepted only when its
trust/head data is valid. Missing legacy nonce records are first appended to the
new replay journal and fsynced; only then is the metadata snapshot replaced by
schema 2. Migration failure fails closed and never resets replay history.

The lock file records that initialization began. If a later open finds the
initialized lock but no durable state metadata, it fails closed instead of
creating an empty authority. Corrupt, oversized or trust-mismatched state also
fails closed.

These files are not an external anti-rollback oracle. Deleting/restoring the
entire store or switching its configured location is an authority reset and
requires independent trust/epoch recovery.

## Admission, concurrency and recovery

1. `claim(signed, expected)` validates the exact binding, signer and signature.
2. Under the owner mutex it validates time/epoch/revocations and rejects a
   replayed nonce.
3. The nonce is fsync-appended to `authority.claims`; dispatch is not admitted
   until this succeeds.
4. Time is sampled again after durable I/O; expiry does not refund the nonce.
5. The adapter performs bounded asynchronous external work without holding the
   authority mutex, so revocation updates can progress.
6. `with_verified_use` verifies owner/binding/time/epoch/revocation again and
   invokes the synchronous consumer while holding the revocation fence.

The callback must be bounded and must not reenter the authority. Revocation can
wait for an already-entered synchronous callback; it cannot undo a completed
effect. A dispatch failure, cancellation or timeout retains the claim. Process
death after claim does not make the nonce reusable.

`VerifiedUseToken` has no public constructor and cannot be cloned. An
outstanding token keeps its owner and process lock alive. Mutex poisoning or
persistence failure refuses further operations.

## Active-active boundary

One local state directory remains **single active owner**. The exclusive lock is
intentional and is not a distributed multi-writer mechanism.

For HeptaBao active-active composition, the implemented safe mode is authority
sharding: each replica uses a distinct signed `destination_id` and its own
private final-use state. A grant for replica A fails binding validation on
replica B, so there is no shared replay namespace that two local stores can
silently diverge on.

If multiple writers must share the same `destination_id`/authority identity, a
separately qualified strongly consistent shared replay/revocation backend is
required. This local store does not claim that capability.

## APIs and failure semantics

| API / result | Host action |
| --- | --- |
| `open_state_dir` | Pin trust, validate private storage, acquire local owner lock and load/migrate state |
| `update_revocations` | Apply only a newer trusted revision; same-epoch revocations cannot be removed |
| `claim` | Durably burn one valid nonce before effect dispatch; never reuse the grant on retry |
| `with_verified_use` | Consume the verified token at the final synchronous secret-use boundary |
| `InvalidGrant`, `InvalidSignature`, `BindingMismatch` | Reject; do not dispatch |
| `EpochMismatch`, `Revoked`, `NotYetValid`, `Expired` | Reject stale/currently unauthorized use |
| `AlreadyClaimed` | Require owner reconciliation/new authorization |
| `CapacityExceeded` | Compatibility error variant; no longer emitted at 16,384 replay claims |
| `InvalidTrust`, `UnsafeStateDirectory`, `StateLocked`, `Unavailable` | Fail closed; repair owner configuration/storage without implicit reset |
| `StaleRevocationHead` | Reject rollback/inconsistent host update |

HeptaBao additionally distinguishes provider denial/not-found, definite client
rejection, transport/timeout, malformed/oversized replies and indeterminate
provider effects. A callback failure after entry is uncertain; it is not proof
that no effect occurred.

## Independent signer operations

Build the supervisor binary with the existing `production-authority` feature:

```text
cargo build -p codex-hepta-supervisor --features production-authority --bin hepta-final-use-signer
hepta-final-use-signer sign --key OWNER_ONLY_SEED_FILE < complete-grant-proposal.json
```

The seed file contains exactly 32 raw Ed25519 bytes and is provisioned
separately by the authority owner. The signer rejects symlink/non-regular/shared
or unsafe key files, bounds input and zeroizes temporary seed buffers. There is
no default wildcard scope or adapter-owned signing-key generation.

## Verification and rollout boundary

Kernel source tests cover signature/binding substitution, expiry, epoch fences,
monotonic revocation, cross-restart replay rejection, concurrent owners,
unsafe/missing state, process death and journal behavior beyond the former
16,384-claim cap. The HeptaBao adapter separately covers real loopback TLS,
exact KV reads, dynamic issue/renew/revoke, uncertainty/reconciliation and
replica destination binding.

The focused exact-candidate workflow is
`/.github/workflows/heptabao-lease-qualification.yml`. It executes format,
owner tests and strict Clippy for `codex-hepta-contracts` and
`codex-hepta-bao-adapter` and emits a receipt binding the tested SHA/tree and
executed command-record digests. Full workspace, target-host production
composition, operator acceptance, promotion and release remain separate gates.
