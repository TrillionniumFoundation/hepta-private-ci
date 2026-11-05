# PQ final-use owner integration

This is an explicit signature profile of the original durable authority owner.
It does not qualify production key custody, external time/frontier services,
network confidentiality, ordinary model installation or the PoN work proof.

## Acceptance path

`FinalUseAuthority::open_pq_state_dir_with_issuer_keys` requires host-pinned
ML-DSA-65 keys, a protected clock and an independent external compare-and-set
frontier. It uses the existing claim journal, epoch/revocation checks,
single-entry token, write-ahead ordering and post-persistence expiry check.
Successful verification cannot manufacture `VerifiedUseToken` outside this
owner. A failed or uncertain effect still consumes its nonce.

Every token, consumer, effect and dispatch boundary also compares the current
revocation head with the exact head authenticated at claim time. A revision
advance requires a fresh claim even when the old grant was not explicitly
revoked. The stale claim's nonce remains consumed.

Every final effect entry reloads its configured external frontier while holding
its original state mutex. The complete profile-bound state digest must match,
including consumed nonces and revocation state; an epoch/revision match alone
is insufficient. Divergence or an unavailable frontier permanently fences that
owner. Local observability getters remain local; claim and revocation updates
retain their original atomic external CAS. An external advance visible to this
entry observation fences the old owner before its token can be admitted.
Refusal never refunds its nonce. The frontier implementation must provide a
current, authenticated observation; a cached response cannot establish current
authorization. Its synchronous call must also be bounded and must not reenter
the same owner while the state mutex is held.
This adds one external load and a complete frontier digest computation at each
PQ effect entry. No throughput or latency qualification is implied.

The external observation precedes the existing clock and local effect-entry
checks. It does not make frontier observation and an external provider effect
one distributed transaction. Another owner can advance the frontier after this
observation, including during the protected clock call and before local effect
entry. Closing that distributed race requires a shared admission lease or
transaction; this check neither supplies one nor cancels an admitted remote
effect. The existing in-flight effect and reconciliation semantics remain.

The canonical implementation is RustCrypto `ml-dsa = 0.1.1`. The pure FIPS 204
mode has an empty algorithm context; the complete versioned Hepta application
domain is inside the signed message. The SPKI grammar, key-ID domain,
65,536-byte message bound and 3,309-byte signature encoding match the
Trillionnium canonical adapter. Another implementation is a differential
verification source, never an alternative acceptance backend.

## Versions and downgrade refusal

| Owner object | Classical version | PQ version |
| --- | --- | --- |
| Grant | schema 1 | schema 2, `final-use.pq.v2` domain |
| Independent approval | schema 1 | schema 2, `final-use-approval.pq.v2` domain |
| Revocation feed | schema 2 | schema 3, `revocation-feed.pq.v3` domain |
| Applied-update acknowledgement | schema 1 | schema 2, `revocation-ack.pq.v2` domain |
| Durable authority snapshot | schemas 1–3 | fresh schema 4 and PQ key-ring identity |
| External frontier hash | `final-use-frontier.v1` | `final-use-frontier.pq.v2` |

The host selects the profile. A received schema cannot switch it. PQ owners
reject classic grants before signature work; approval, feed and acknowledgement
verifiers use only their configured profile. The feed additionally checks the
authority owner's profile before any durable mutation. Neither store profile
opens the other profile's namespace, and no implicit migration is performed.

Each key ring is bounded to eight distinct keys and inclusive authority-epoch
windows. A deployment must additionally keep issuer, independent approver,
revocation distributor, clock and frontier identities separate. Merely giving
one key several role names does not establish independent authorization.

The ordinary Unix `UnixFinalUseAuthorizer::open` entry requires the explicit
`ml_dsa65_v2` profile. An omitted or classical profile is refused before any
issuer/clock/frontier contact or durable authority opening. The explicit
low-level classical constructors remain available for compatibility analysis;
they are not a fallback in the ordinary configuration path. Existing classical
snapshots are not implicitly migrated into PQ authorization.

The ordinary Unix final-use configuration checks its issuer and revocation
rings and its clock and frontier keys before contacting external services or
opening local authority state. It decodes the canonical SPKI, verifies the
pinned key identity and rejects repeated public-key bytes across these roles,
including keys reserved for future epochs. Valid independent rotation keys
retain their original epoch windows and persistent trust identity. This check
does not attest independent service operation or secret custody, and the
separately configured approver still requires its own deployment review.

## Resource and custody boundary

The PQ revocation payload is limited to 256 grant IDs; the legacy feed limit
remains unchanged. Every canonical PQ verification requires an exact 3,309-byte
signature. Host framing, concurrency and failed-verification budgets still
belong to the concrete caller and must include JSON/base64 overhead where used.
These source limits are not a measured throughput or latency qualification.

The three original supervisor signers accept `--pq-key-id HEX` only as an
explicit PQ selection. Grant and approval inputs must then use schema 2.
Without that option they accept only the classical schema. The independently
pinned key ID is checked against the derived public key before output. The
shared custody reader retains the existing no-symlink, singly linked,
owner-only regular-file checks and exact 32-byte raw seed bound. Secret buffers
are zeroized; no implicit key generation or secret export is added.

## Separate gates

ML-DSA authenticates an identity; it does not encrypt transport. ML-KEM or a
hybrid TLS key exchange requires its own authenticated peer identity and
deployment qualification. A PQ signature on a manifest authenticates its
content root; individual weight chunks remain content-addressed and do not
need independent large signatures.

This local integration is not an independently audited whole-chain PQ result.
Learning/artifact installation, every original ordinary caller, continuous
operator and paid History coverage, explicit network activation, quantum work
analysis and proof-system soundness remain separately tracked gates. No
boolean in this document can enable them.
