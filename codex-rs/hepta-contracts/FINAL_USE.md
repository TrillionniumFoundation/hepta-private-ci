# Final-use authority and independent issuer

This document specifies the executable final-use admission boundary used by the
[HeptaBao HTTPS consumer](../hepta-bao-adapter/README.md). It supplements the
stable `kernel.authority`, `runtime.supervisor` and `secrets.heptabao` module
guides. The existing H7 upgrade/rollback signer and the legacy Bao metadata
projection keep their existing semantics.

## Ownership and trust

`final_use.rs` owns validation and the non-constructible `VerifiedUseToken`.
`final_use_store.rs` owns durable nonce/revocation state. The host supplies one
pinned Ed25519 public key, signer identity, initial revocation head and private
state directory through its protected configuration channel. There is no
permissive default, signing key in the verifier, or conversion from a boolean,
`Granted` projection or unsigned proposal to a verified token.

The separately invoked supervisor binary `hepta-final-use-signer` owns the
explicit signing operation. The adapter must not invoke it to authorize its
own requests. A trusted owner reviews the complete proposed binding and
chooses the subject, epoch, nonce and time window before invoking the command.
This utility does not implement an identity provider or an approval policy
engine; access to its signing key is the issuer's authority boundary.

The Rust callback, public-key configuration and state location are trusted host
inputs. This library is not a sandbox for untrusted code in the same process
or Unix account. A host selects the callback from its own consumer registry;
a signed consumer-name string cannot authenticate a closure supplied by a
plugin. Protect the configuration, directory ancestors, clock and issuer key.

## Wire and signing schemas

All grants use `schema_version = 1`, deny unknown JSON fields, and serialize
integer byte arrays. The signing preimage is the byte string
`hepta.kernel.authority.final-use.v1\0` followed by the compact JSON encoding
of the validated Rust `FinalUseGrant` struct in its declared field order.
Use `FinalUseGrant::signing_bytes()` as the reference encoder; this is not a
claim that arbitrary JSON serializations are interchangeable. Changing field
order, encoding or semantics requires a new version and signing domain.

| Type / field | Meaning and bound |
| --- | --- |
| `FinalUseBinding.subject_id`, `destination_id` | Exact principal and effect destination; 1–128 ASCII identifier bytes |
| `request_sha256` | Nonzero 32-byte digest of the complete adapter operation |
| `scope_sha256` | Nonzero 32-byte digest of destination/resource/consumer scope |
| `payload_sha256` | Nonzero 32-byte digest of the exact effect payload. Static secret reads bind the expected secret digest; dynamic issuance/control binds the exact request because future secret bytes do not exist before dispatch. |
| `FinalUseGrant.signer_id`, `grant_id` | Bounded owner and revocation identifiers |
| `authority_epoch` | Nonzero epoch; must exactly match the current durable head |
| `nonce` | Nonzero 32-byte random value; unique across that authority epoch |
| `binding` | The complete operation binding above |
| `not_before_unix_ms`, `expires_at_unix_ms` | Host clock bounds; positive interval no longer than 300,000 ms |
| `SignedFinalUseGrant.signature` | Exactly 64 raw Ed25519 signature bytes |
| `FinalUseRevocations` | Epoch, nonzero monotonically increasing revision and at most 16,384 revoked grant IDs |

For Bao, the request digest binds the HTTPS origin, CA bytes, namespace, mount,
path, field, exact KV v2 version, expected secret digest, subject and consumer.
The destination is `provider:heptabao`. Signature validation uses Ed25519
`verify_strict`; weak trust keys, malformed signatures and changed bindings
are rejected before dispatch.

## Durable schema and storage protocol

The supported store is an owner-controlled local Unix filesystem providing
process locks, atomic same-directory rename and file/directory fsync. Other
platforms reject configuration until an equivalent ACL and durability backend
exists. Distributed/NFS lock behavior is not qualified by the local tests.

The root directory must belong to the effective user and have no group/world
permission bits. Creation requests mode 0700. The directory is opened with
`DIRECTORY | NOFOLLOW | CLOEXEC`; subsequent operations use that directory
file descriptor, `openat`, `statat` and `renameat`. Replacing an ancestor path
does not redirect an already opened authority's writes.

| Entry | Contents and invariant |
| --- | --- |
| `authority.lock` | Owner-only regular file; short-lived cross-process mutation/final-use fence |
| `authority.json` | Schema-v2 JSON containing signer identity, verifying key and current revocation head; maximum read 8 MiB |
| `authority.next` | Temporary head replacement written with owner-only permissions before rename |
| `claims.log` | Append-only fixed-size replay records: magic, epoch, nonce and SHA-256 record checksum |
| `claims.next` | Schema-v1 migration staging journal; atomically renamed before the v2 head is published |

Files must be regular, singly linked, owned by the effective user and have no
group/world permissions; opens reject symlinks. The lock is acquired only
around a mutation or final synchronous consumer execution and releases
automatically when that guard file descriptor closes or the process dies.
Multiple processes may therefore open one qualified state directory.

A claim refreshes the small head and only journal records appended since that
owner's last verified offset, rejects a duplicate nonce, appends one checksummed
record to `claims.log` and `sync_data`s it before dispatch admission. A
revocation update atomically replaces only the small head via
`authority.next`, file fsync, rename and directory fsync. Final secret delivery
takes the same cross-process fence, refreshes current head/journal state and
rechecks live authority before callback entry. Storage error fences the affected
authority instance.

The lock file also records that initialization has begun. If a later open
finds it but no durable state file, it fails closed instead of resetting the
nonce registry. Corrupt or oversized JSON and trust-key/schema mismatch also
fail closed. A crash during first initialization can therefore require owner
recovery rather than automatic recreation.

Normal restart scans the replay journal once and loads the current revocation
head. Active owners thereafter refresh only newly appended journal records.
An old configuration cannot roll back a stronger stored head. A newer trusted
startup head can be applied atomically when its revision increases, its epoch
does not decrease, and same-epoch revocations are a superset. An epoch increase
fences every old grant and clears the active in-memory nonce set; old journal
records retain their epoch and are ignored for the new epoch. Claims are not
silently evicted and the former 16,384 per-epoch claim admission ceiling has
been removed. The revoked-grant set remains explicitly bounded at 16,384 IDs.

These files are not an external anti-rollback oracle. Deleting the entire
store, restoring an old filesystem snapshot, or switching its configured
location is an authority reset. Recovery must independently rotate issuer
trust or advance the authoritative epoch before accepting new grants; do not
restore a former epoch alongside still-valid grants. No automatic repair may
turn missing/corrupt state into an empty registry.

## Admission, concurrency and recovery

1. `claim(signed, expected)` validates the exact binding, signer and signature.
2. Under the in-process mutex and cross-process mutation fence it refreshes the
   durable head/journal tail, checks clock/epoch/revocations, rejects a consumed
   nonce, and appends/syncs the nonce claim.
3. It samples time again after disk I/O, then returns a private, non-cloneable,
   non-serializable `VerifiedUseToken`. The claim is the dispatch admission
   point; rejection or expiry after persistence does not refund the nonce.
4. The adapter performs its bounded asynchronous HTTPS read. It does not hold
   the owner mutex over network awaits, so trusted revocations can progress.
5. `with_verified_use` takes the in-process and cross-process fences, refreshes
   durable state, checks that token and authority share the same owner, validates
   binding/time/epoch/revocation again, and invokes the synchronous callback
   while those revocation fences remain held. A completed revocation from
   another active owner cannot slip between this final check and callback entry.

The callback must be bounded and must not reenter the authority. Revocation
waits for an already entered synchronous callback to return; it cannot undo a
completed effect. A dispatch failure, cancellation or timeout retains the
claim. If a process dies after claiming, the new process rejects that nonce.
If it dies after consumer entry but before recording a receipt, the host must
treat the effect as uncertain and reconcile it before issuing another grant.

`VerifiedUseToken` has no public constructor and cannot be cloned. Keeping an
outstanding token keeps its in-process owner alive but does not monopolize the
cross-process lock during asynchronous network work. Mutex poisoning,
journal/head corruption or persistence failure refuses further operations.

## APIs and failure semantics

| API / result | Host action |
| --- | --- |
| `open_state_dir` | Pin trust, validate private storage and load/migrate the head plus replay journal; multiple active owners may open the same qualified directory |
| `update_revocations` | Apply only a newer trusted revision; same-epoch revocations cannot be removed |
| `claim` | Burn one valid nonce before effect dispatch; never reuse the grant on retry |
| `with_verified_use` | Consume that token at the final synchronous secret-use boundary |
| `InvalidGrant`, `InvalidSignature`, `BindingMismatch` | Reject the proposal; do not dispatch |
| `EpochMismatch`, `Revoked`, `NotYetValid`, `Expired` | Reject stale or currently unauthorized use |
| `AlreadyClaimed` | Reject replay; require a new authorization only after any uncertain effect is reconciled |
| `CapacityExceeded`, `StateLocked` | Retained compatibility variants; the schema-v2 replay journal does not emit them for ordinary claim/concurrent-open flow |
| `InvalidTrust`, `UnsafeStateDirectory`, `Unavailable` | Fail closed; repair owner configuration/storage without resetting authority implicitly |
| `StaleRevocationHead` | Reject a rollback/inconsistent host update |

Bao additionally distinguishes provider denial, missing data, transport failure,
timeout, malformed/oversized replies, version mismatch and digest mismatch.
None invokes the consumer. A callback that reports failure after entry returns
`ConsumerIndeterminate`; it is not proof that no effect occurred. Static verification may compute body/secret digests internally, but ordinary
serialized/debug receipts omit the provider-body and secret fingerprints.
Dynamic lease receipts contain request identity, lease metadata and delivered
byte count, never raw secret material.

## Independent signer operations

Build the supervisor binary with the existing `production-authority` feature:

```text
cargo build -p codex-hepta-supervisor --features production-authority --bin hepta-final-use-signer
hepta-final-use-signer sign --key OWNER_ONLY_SEED_FILE < complete-grant-proposal.json
```

The file contains exactly 32 raw Ed25519 seed bytes, provisioned separately by
the authority owner. The signer rejects symlink opens, non-regular/multiply
linked files, other owners and group/world permissions. It reads at most
33 bytes, zeroizes temporary seed buffers, and accepts at most 16 KiB of grant
JSON on stdin. There is no implicit sign command, default wildcard scope or
adapter-owned key generation. Stdout contains the public signed grant only.
The existing H7 signer has a separate protocol and is not widened by this tool.

## Verification and rollout boundary

Kernel tests cover field/key substitution, expiry, epoch fences, monotonic
revocation, cross-restart replay rejection, concurrent active-owner replay and
revocation visibility, missing state, unsafe permissions/symlinks, newer
startup heads, SIGKILL while retaining a persisted claim, and schema-v1 replay
sets larger than the former claim ceiling migrating without eviction. Adapter tests cover real loopback TLS,
exact headers/version, bad trust, forged/denied grants, response bounds,
revocation during network wait, timeout and consumer uncertainty. Test fixtures
explicitly create private directories; timeout cleanup cancels its local test
server even when cancellation happened before TCP accept.

The runnable [real service fixture](../hepta-bao-adapter/qa/real_service_smoke.py)
uses independent signer and consumer processes against the actual Bao TLS
server. [Recorded evidence](../hepta-bao-adapter/qa/evidence/real-consumer-20260908.json)
contains 20 checks and metadata only. Full workspace, Bazel, production caller
composition and release gates remain separate from this bounded integration.
No legacy `PROVIDER_DISPATCH_ENABLED` flag is enabled by these changes.

The [candidate validation record](../hepta-bao-adapter/qa/evidence/validation-20260908.json)
marks the initial normal locked workspace test as `blocked_space` (zero tests executed)
and the normal signer workspace build as not started. The source-linked
behavioral/Clippy checks and real signer/consumer process fixture remain separate
passing evidence. The approved-client follow-up ran 243 normal workspace tests:
237 passed, including all 132 contracts tests and 18 adapter tests; six older
HTTP TLS tests failed and also failed on an independent prior-source checkout.
The newly built normal-workspace consumer passed the real 20-scenario
fixture again. Its [receipt](../hepta-bao-adapter/qa/evidence/real-consumer-http-client-20260908.json)
identifies the tested tree before final formatting and documentation changes;
it is not a claim that the retained binary was built from the final commit.
The local Bazel lock update was blocked by an automatic
telemetry approval rejection and subsequent privacy-configured extraction /
network-approval failure. Separate old-source CI diagnostics proved a real
Bazel check/update/check with zero exits and no lock change; the subsequent
HTTP dependency migration still requires current-head CI. Document validation
passed. These recorded limits must not be reported as complete workspace or
production qualification.
