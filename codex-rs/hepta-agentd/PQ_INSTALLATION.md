# PQ ordinary installation candidate

The ordinary cognitive bootstrap decoder has an explicit ML-DSA-65 profile. The
host must independently authorize the entire descriptor digest. A descriptor is
untrusted input until the original owners reconstruct and verify its evidence.
This candidate does not make every Agentd control protocol post-quantum.

## Version and trust selection

Classical descriptors keep their existing family schema and fixed hexadecimal
Ed25519 fields. PQ installation uses schema `hepta.agentd.cognitive-bootstrap.pq.v4`
and one of these family profiles:

- `published_product_qualification_pq_v2` for tabular parameters;
- `published_neural_product_qualification_pq_v2` for neural parameters.

The descriptor `authentication_profile` and its CURRENT owner's profile must both
select the typed `MlDsa65V2` variant. A missing field defaults only to the classical
profile and therefore cannot satisfy either PQ schema/profile pair. Learning role
keys and signatures use the exact prefix `ml-dsa-65-v2:` followed by hexadecimal
bytes: 1,974 bytes for canonical ML-DSA-65 SPKI and 3,309 bytes for a signature. No
alternate context, pre-hash or classic-or-PQ acceptance is attempted.

The host must remove authorization for old descriptor digests when deployment
activates the PQ profile. This decoder does not replace the external host policy
that authorizes a descriptor or prove that policy's rollback resistance.

## Reconstruction order

1. Bound the descriptor to 4 MiB, open it as a regular nonaliased file, and verify
   its independently supplied digest, family, authentication profile, agent ID and
   launch generation.
2. Require trust, journal and owner paths to be outside the Agentd-owned home,
   run and workspace directories. Require nonempty independently retained ledger
   and final-holdout anchors.
3. Reconstruct the root-signed learning distribution from `pq_learning_activation`
   plus the descriptor's full role trust. Authenticate a protected Unix clock and
   the exact independent current distribution floor before opening mutable history.
4. Recover the explicitly selected PQ ledger history against the pinned record
   anchor. The classical history header or records cannot be relabelled into this
   profile. Reconstruct the dataset and re-run the original sealed product
   evaluation/holdout replay and evidence verification.
5. Reopen the original artifact owner's CURRENT reader with PQ writer/head keys
   and the host's retained signed head floor. Every refresh uses protected time.
6. Require CURRENT and independently admitted selection to have the same profile.
   Bind the cached bytes to the opaque CURRENT view's profile and trust digest.
   Tabular and neural material validity, refresh, and final cache consumption use
   the same retained protected clock as the CURRENT owner.
7. The original SmolLM composition requires the selected learning profile to match
   the opened FinalUse authority before opening its inference journal or starting
   the model. The inference owner consumes a per-use issuer grant, signed
   revocation feed, external frontier and durable nonce. The separate Bao consumer
   composition additionally requires independent operator approval and matching
   authority, approver and revocation distributor profiles.

Step 4 may perform the already-authorized history recovery, including truncation
of an unconfirmed tail and fsync, before the final CURRENT check. Product replay
requires a pre-existing frozen holdout plan and unchanged anchor; existing evidence
files accept only exact retries. This is not a promise of an entirely read-only
installation preflight.

The learning distribution and opaque roles retain their root expiry, revocation
and current distribution floor. With a protected clock present, its time is the
authorization time: caller wall time cannot activate future evidence early or
postpone expiry. PQ time windows are half-open. CURRENT times are Unix seconds;
learning/evaluation times are Unix microseconds; the external clock wire returns
Unix milliseconds and conversions are checked or rounded to the relevant boundary.

## `pq_learning_activation` fields

| Field group | Purpose |
| --- | --- |
| `root_id`, `root_scope_digest`, `root_verifying_key` | Host-pinned root identity and scope |
| `root_valid_from`, `root_expires_at`, `root_revoked_at` | Root authority lifetime |
| `distribution_id`, `generation`, `effective_at` | Exact distribution and ordered activation |
| `issued_at`, `expires_at`, `signature` | Root-signed distribution proof and lifetime |
| `clock`, `frontier` | Pinned external service endpoints |

Each external endpoint contains an absolute `socket_path`, `peer_uid`, `service_id`,
`key_generation`, canonical `public_key_spki`, its `public_key_id`, and `timeout_ms`.
Installation requires the socket path to equal its canonical path and to be outside
the canonical Agentd-owned roots; an alias in an ancestor directory is rejected.
The contracts client binds a fresh challenge and exact operation to a signed
response and enforces the peer UID, bounded frames and an absolute deadline. The
learning floor uses a distinct operation type and owner namespace
`hepta-learning-trust:<ledger-binding-hex>`. It is never accepted as a FinalUse
frontier. There is no local or unsigned fallback.

Signed responses authenticate the configured service's answers. Deployment still
must qualify that service's protected time, durable CAS, rollback isolation, key
custody and operator separation. The test services do not establish these properties.

## Qualification boundaries

The new decoder source and integration tests must pass the actual Agentd/worker
build and execution gates before this installation route is qualified. A trusted
parameter payload, CURRENT view or valid signature alone does not establish model
improvement or product evaluation. The original released material, frozen plans,
future windows, sealed product qualification and independent selector remain
required. Independent FinalUse admission remains separate from parameter selection.

Other classical protocols remain explicit open work, including AuthBus message,
time and settlement signatures; RunStart authentication; PoN automation caller
credentials; the separate v1 plasticity bootstrap owner; and the intelligence
owner freshness file and its `--intelligence-authority-*` CLI trust entrypoint.
A deployment must not
claim whole-Hepta PQ activation while those required authorization relationships
can still authorize a protected operation through a classic path. The new learning
route neither silently upgrades nor weakens them.

The Cell P2P download/install bridge, network confidentiality, PoN quantum work and
proof-system audits require separate evidence. ML-DSA authenticates statements;
it does not establish an ML-KEM channel or encrypt model weights.
