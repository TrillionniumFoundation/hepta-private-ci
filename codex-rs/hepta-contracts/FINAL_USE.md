# Final-use authority and independent issuer

This document specifies the executable final-use admission boundary used by the
[HeptaBao HTTPS consumer](../hepta-bao-adapter/README.md). It supplements the
stable `kernel.authority`, `runtime.supervisor` and `secrets.heptabao` module
guides. The production-control extension for independent approval, authenticated
revocation ingestion and a registered consumer host is specified in
[`FINAL_USE_CONTROL.md`](FINAL_USE_CONTROL.md). The existing H7 upgrade/rollback
signer and the legacy Bao metadata projection keep their existing semantics.

## Ownership and trust

`final_use.rs` owns validation and the non-constructible `VerifiedUseToken`.
`final_use_store.rs` owns durable nonce/revocation state. The compatibility path supplies one pinned Ed25519 public key. Production
composition may instead supply a bounded `FinalUseIssuerTrustKey` ring with
inclusive authority-epoch windows, plus signer identity, initial revocation
head and private state directory through its protected configuration channel. There is no
permissive default, signing key in the verifier, or conversion from a boolean,
`Granted` projection or unsigned proposal to a verified token.

The separately invoked supervisor binary `hepta-final-use-signer` owns the
explicit signing operation. The adapter must not invoke it to authorize its
own requests. A trusted owner reviews the complete proposed binding and
chooses the subject, epoch, nonce and time window before invoking the command.
The base signer does not implement an identity provider or approval policy
engine. A production-capable host may additionally require the independent
approval and revocation-distributor roles defined in `FINAL_USE_CONTROL.md` so
possession of the grant-issuer key alone is insufficient on that path.

The Rust callback, public-key configuration and state location are trusted host
inputs. Production construction additionally binds an `AuthorityClock` and an
externally durable `AuthorityFrontierStore<FinalUseFrontier>`. The local store
is not allowed to manufacture either trust fact. This library is not a sandbox
for untrusted code in the same process or Unix account. The registered Bao host
binds signed `consumer_id` values to a closed process-local callback registry;
a signed consumer-name string cannot authenticate a closure supplied by a
plugin. Protect the configuration, directory ancestors, clock, external
frontier and all issuer/approver/distributor trust material.

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
| `payload_sha256` | Nonzero 32-byte digest of the expected material |
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
| `authority.lock` | Owner-only regular file; `File::try_lock` held by the shared authority owner |
| `authority.json` | JSON `{schema:1, signer_id, verifying_key, state:{head, used_nonces}}`; maximum read 8 MiB |
| `authority.next` | Temporary complete replacement written with owner-only permissions before rename |

Files must be regular, singly linked, owned by the effective user and have no
group/world permissions; opens reject symlinks. The lock is held until the
last authority/token reference disappears. It also releases automatically on
process death. Concurrent opens fail with `StateLocked`.

Every successful claim or head update serializes the complete next state,
truncates and writes `authority.next`, fsyncs that file, renames it over
`authority.json`, and fsyncs the root directory. The operation is not admitted
until persistence succeeds. On a storage error, the live authority becomes
unavailable and stays fenced; callers cannot remove a bad temporary file and
silently retry through that same instance.

The lock file also records that initialization has begun. If a later open
finds it but no durable state file, it fails closed instead of resetting the
nonce registry. Corrupt or oversized JSON and trust-key/schema mismatch also
fail closed. A crash during first initialization can therefore require owner
recovery rather than automatic recreation.

Normal restart loads the persisted nonce set and revocation head automatically.
An old configuration cannot roll back a stronger stored head. A newer trusted
startup head can be applied atomically when its revision increases, its epoch
does not decrease, and same-epoch revocations are a superset. An epoch increase
fences every old grant and clears the previous nonce set. There is no silent
nonce eviction: 16,384 claims fill the epoch and reject further claims until a
trusted epoch transition.

These files are not an external anti-rollback oracle. For production
composition, `open_state_dir_with_trust` additionally requires an externally
durable `FinalUseFrontier` whose digest covers the complete revocation head and
claimed-nonce set. Every claim/head mutation CAS-advances that external frontier
before the local fsync/rename. A restored local snapshot therefore mismatches
the external frontier and fails closed. If external CAS succeeds but the local
commit fails, the owner remains fenced and recovery is explicit. Deleting or
switching the local store is never permission to reset replay history.

The compatibility `open_state_dir` path uses the process system clock and no
external rollback oracle. It remains useful for qualification/backward source
compatibility but is not a production anti-rollback or attested-time claim.

## Admission, concurrency and recovery

1. `claim(signed, expected)` validates the exact binding, signer and signature.
2. Under the owner mutex it checks the current clock, epoch and revocations,
   rejects a consumed nonce or full registry, and persists the nonce claim.
3. It samples time again after disk I/O, then returns a private, non-cloneable,
   non-serializable `VerifiedUseToken`. The claim is the dispatch admission
   point; rejection or expiry after persistence does not refund the nonce.
4. The adapter performs its bounded asynchronous HTTPS read. It does not hold
   the owner mutex over network awaits, so trusted revocations can progress.
5. `with_verified_use` checks that token and authority share the same owner,
   validates binding/time/epoch/revocation under the authority mutex, then
   releases the mutex before invoking the already selected synchronous
   callback. The successful final validation is the consumer-entry
   linearization point.
6. Callers that need revocation to linearize with a short local irreversible
   transition use `dispatch_final_use` / `with_dispatch_boundary`. That path
   holds the mutex only while durable intent is published or the already
   selected local adapter/worker boundary is crossed, then releases it. Network
   waits, terminal provider observation, reconciliation and arbitrary plugin or
   user code are forbidden inside that callback.

A revocation committed before that linearization point denies entry. A
revocation committed after it is ordered after entry and cannot retroactively
cancel the already-entered synchronous effect. The callback no longer runs
while holding the authority mutex, so a slow, panicking or re-entrant callback
cannot block a later revocation update or poison the authority mutex. The
callback must still be bounded because the external effect itself may become
slow or indeterminate even though authority progress is no longer blocked.

A dispatch failure, cancellation or timeout retains the claim. If a process
dies after claiming, the new process rejects that nonce. If it dies after
consumer entry but before recording a receipt, the host must treat the effect
as uncertain and reconcile it before issuing another grant.

`VerifiedUseToken` has no public constructor and cannot be cloned. Keeping an
outstanding token also keeps its owner and process lock alive. Mutex poisoning
inside authority code or persistence failure refuses further operations;
callback panics occur after the final authority lock has been released.

## APIs and failure semantics

| API / result | Host action |
| --- | --- |
| `open_state_dir` | Compatibility/test open using the system clock and local durability only |
| `open_state_dir_with_clock` | Bind an explicit host clock; still has no external rollback oracle |
| `open_state_dir_with_trust` | Single-issuer compatibility open binding explicit clock plus external CAS frontier |
| `open_state_dir_with_issuer_keys` | Production-oriented open binding epoch-window issuer key ring, explicit clock and external CAS frontier; durable schema V2 pins the complete trust-set digest |
| `issuer_key_ids` | Read configured issuer key identifiers for audit/operations; grants no authority |
| `frontier` | Read the current rollback-protection digest/epoch/revision projection |
| `update_revocations` | Apply only a newer trusted revision; same-epoch revocations cannot be removed |
| `claim` | Burn one valid nonce before effect dispatch; never reuse the grant on retry |
| `with_verified_use` | Revalidate, linearize entry, release the authority lock, then consume the token at the final synchronous boundary |
| `dispatch_final_use` / `with_dispatch_boundary` | Revalidate and hold the lock only across one short local irreversible dispatch boundary |
| `InvalidGrant`, `InvalidSignature`, `BindingMismatch` | Reject the proposal; do not dispatch |
| `EpochMismatch`, `Revoked`, `NotYetValid`, `Expired` | Reject stale or currently unauthorized use |
| `AlreadyClaimed`, `CapacityExceeded` | Require owner reconciliation/new authorization or an epoch transition |
| `InvalidTrust`, `AntiRollbackViolation`, `UnsafeStateDirectory`, `StateLocked`, `Unavailable` | Fail closed; repair owner clock/frontier/configuration/storage without resetting authority implicitly |
| `StaleRevocationHead` | Reject a rollback/inconsistent host update |

Bao additionally distinguishes provider denial, missing data, transport failure,
timeout, malformed/oversized replies, version mismatch and digest mismatch.
None invokes the consumer. A callback that reports failure after entry returns
`ConsumerIndeterminate`; it is not proof that no effect occurred. Receipts
contain only request/body/secret digests, version and byte count.

## Independent signer operations

Build the grant issuer with the existing `production-authority` feature:

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

Production-capable source composition also provides separate
`hepta-final-use-approver` and `hepta-final-use-revocation-signer` binaries.
Their protocol and trust separation are specified in `FINAL_USE_CONTROL.md`.
They reuse the explicit owner-only external key loading boundary, generate no
keys and confer no authority merely by being built.

## Verification and rollout boundary

Kernel tests cover field/key substitution, injected trusted time, expiry,
epoch fences, monotonic revocation, cross-restart replay rejection, concurrent
owners, missing state, unsafe permissions/symlinks, external-frontier restored
snapshot rejection, newer compatibility-startup heads, SIGKILL of a lock holder
while retaining its persisted claim, and final/dispatch linearization. Control
tests cover exact independent approval, bounded epoch key rotation, signed-feed
freshness, authenticated monotonic revocation ingestion and forged-feed
rejection.
Adapter tests cover real loopback TLS, exact headers/version, bad trust,
forged/denied grants, response bounds, revocation during network wait, timeout
and consumer uncertainty. Registered-host tests cover closed and unique
consumer identities. Test fixtures explicitly create private directories;
timeout cleanup cancels its local test server even when cancellation happened
before TCP accept.

The runnable [real service fixture](../hepta-bao-adapter/qa/real_service_smoke.py)
uses independent signer and consumer processes against the actual Bao TLS
server. [Recorded evidence](../hepta-bao-adapter/qa/evidence/real-consumer-20260908.json)
contains 20 checks and metadata only. Full workspace, Bazel, selected product
process activation and release gates remain separate from this bounded
integration. No legacy `PROVIDER_DISPATCH_ENABLED` flag is enabled by these
changes.

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
