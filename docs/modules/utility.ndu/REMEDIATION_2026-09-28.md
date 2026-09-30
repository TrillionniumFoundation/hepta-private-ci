# utility.ndu A–D remediation and acceptance ledger

## Candidate and evidence identities

This work remains on `work/utility-ndu-abcd-convergence-20260928`. It inherits
PR #997's deterministic NDU candidate; it does not select a production policy,
merge the repository, enroll an external authority provider, or grant effects.
The baseline used during this work is
`a126987b84737dbc2ee2592442a314117bddb4a2`.

The initial repair candidate `b4da6de225486606e07978122dae5d5bd19a3b50`
was actually executed in run `36333845011`: source, core, callers, product and
lint passed in both lanes, while both mounted-filesystem host suites failed.
The failure was a real read-only bind-remount error, not an AWS upload failure.
The subsequent source `fabb8c345dc67b857c2929ce785bb69eedc056c8` in run
`36336845801` includes the durability, feature/actor and telemetry changes below.
Its Bazel lock update returned zero and its exact source map was verified.
Its protocol regression then caught a Serde unit variant silently accepting
unknown `metrics_v2` fields; the final revision uses a strict empty-struct
variant and keeps both the JSON round-trip and hostile-field regression cases.
These are historical identities, not automatic acceptance of this document's
containing commit. Later receipts must name the later source SHA and tree.

For the final revision, use the run's `materialize` output `sha`, each lane's
`suite-receipt.json`, and the `ndu-qualified-evidence-SOURCE_SHA` aggregate.
The workflow bootstrap commit is not necessarily the materialized source commit.
A synthetic merge intentionally has a different SHA and ordered parents
`[BASE_SHA, SOURCE_SHA]`. Do not substitute an older green run or require the two
intentionally different commits to have the same SHA.

## A — source and qualification

- Replaced the self-matching regular-expression scanner with a lexical scanner
  that distinguishes Rust comments, strings and actual macro invocations.
  Scanner regression cases run in the mandatory source suite.
- Retained the actual Control/Steward contract repairs and corrected strict
  Clippy findings. Consumer code and protocol tests compile in independent
  caller/product suites, not only the core crate's library tests.
- Corrected the materializer's mismatched patch identity; repaired code is now
  present in normal source files, with its temporary delivery patch removed.
- Added the direct `rustix 1.1.4` dependency and regenerated the Bazel lock. The
  earlier ambiguous Cargo lock entry was fixed, not waived by disabling checks.
- Both qualification lanes use one frozen source/base pair. Every suite keeps
  exact commands, exit codes, source/tree/parent identities and log hashes.
  Failed commands do not suppress later independent commands.
- Added closed-world, bounded evidence manifests and an all-twelve-suite
  aggregate. Trusted aggregation reopens the raw named-host and mounted fault
  receipts and checks actual workload, numerical SLOs and recovery observations;
  copied summary flags or recomputed checksums cannot override a failed result.
- Added a separate protected, default-branch-only AWS/OIDC publisher with
  account and versioning checks, conditional creation, SSE-KMS, immutable
  version identity and exact-version readback. No live AWS publication is
  asserted without its successful publication receipt.

## B — durability and owner boundaries

`NduProjectionStoreV1::open_durable` and
`NduProjectionJournalV1::new_ephemeral` make the modes explicit. The actual
Agentd owner already returned a durable-open error; there was no observed
production path silently replacing it with an ephemeral journal. The on-disk
format is binary V1, not JSONL, so no speculative JSONL migration was added.

The store now validates Unix UID/mode, no-follow regular-file opens, hard-link
counts, and root/lock device-and-inode identity before authoritative operations.
A replaced root/lock or newly unsafe permissions fail closed. Linux filesystem
classification rejects unsupported families and explicitly identifies volatile
or unqualified profiles. A deployment must still qualify its actual storage
stack. This is not protection against a malicious process with the same owner
that ignores advisory locking or races every admitted path.

On Linux the lock is held through a read-only descriptor with `flock`, so an open
writer does not prevent the test filesystem from being remounted read-only.
The mounted test observes real errno 28/30, restores capacity/access, reopens,
checks non-resurrection and commits a subsequent operation. The process-kill and
injected write/sync/rename/directory-sync matrix remains independently executed.
Unknown commit outcomes poison the handle and require exact-identity recovery.
Exact successful identity replay and identical restore avoid unnecessary I/O.

Permission, hard-link, root/lock replacement and replay regressions are native
Rust tests. Physical power-loss and target-host shared-volume guarantees are
not inferred from hosted CI or temporary tmpfs fixtures.

## C — model input and governance

The new host-evidence contract binds all feature values, candidate/organ/axis
identities and source digests. Origins are Measured, Derived, Defaulted, Missing
and Structural. Missing features reject; permitted low-risk utility proxies
require an uncertainty floor. Risk/resource proxies and high-risk proxies do
not masquerade as exact measurements. Structural origins are restricted to the
zero-valued, no-effect abstain candidate.

The high-risk policy freezes an explicit affected-actor roster and per-actor
risk/uncertainty limits. Missing, duplicate, foreign or substituted actor rows
reject. Actual Control V2 preparation binds the evidence policy and complete
manifest; effect payloads/risk profiles cannot use the legacy evidence-free
entry or lower their policy. Error codes are `NDU-EVID-001` through `009`.

The real read-only context caller produces evidence from its observed read
receipt, count and byte measurements; it does not fabricate a `CodexStateV1`
proxy pipeline. Provenance binding is not source authentication: a trusted
host must still obtain genuine measurements and the correct actor roster.

Native numerical regressions add an independent Q32 rounding oracle, exhaustive
small Pareto/tolerance/permutation cases, and bounded journal corruption
mutation cases. These are executable invariants, not a convergence proof for
an arbitrary learned stochastic/FBSDE policy. Existing lifecycle admission,
withdrawn datasets, current registry/witness/trust and signed selection rules
are retained. Learning proposals and numerical receipts remain advisory;
rollback requires a new eligible governed selection, never stale backup restore.

## D — observations and retained history

V2 metrics preserve the V1 wire contract and add evaluation errors, latency and
uncertainty distributions, rejection categories, persistence count/failure/
latency, corrupt/recovery observations, backend/filesystem profile and storage
health. Metrics do not wait on the owner lock: contended readiness is unknown,
not a fabricated healthy result. Counters are process-local and must be tagged
with host generation. Memory fallback is zero because the owner has no fallback
branch; backup age remains unknown until a verified off-host observation exists.

The named-host benchmark measures the registered hot workload separately from
the full 128-candidate/4096-contribution envelope. Target thresholds remain
p95 <= 2 ms and p99 <= 5 ms for the registered hot workload, not the entire
maximum envelope or end-to-end authorization path.

Sealed qualification evidence supports create-only lossless compression and
versioned external publication. It does **not** truncate live journal history.
The selected 4096-record V1 store and reserved revocation capacity remain enforced.

The additive `projection_epoch` candidate implements bounded active-epoch rotation,
compact operation replay, explicit recorded/revoked/selected checkpoints, lossless
archive chaining from epoch zero and acknowledgement-bound local retention planning.
Archive pruning requires the exact transition digest and full archive checksum,
minimum external copies, immutable object-version identity, restore-drill receipt,
and the exact current monotonic checkpoint frontier. The planner returns digests;
it never deletes files or external objects. The existing V1 store is not migrated
or truncated by this source change.

Production activation still requires a crash-bounded durable epoch manifest/archive
store on the named target filesystem, real off-host copies, executed restore drills
and operator-controlled retention/deletion. Clearing a full journal is not an
accepted remedy.

## Remaining acceptance gates

A final source candidate requires all twelve actual suites and the recomputed
aggregate, with retained and downloadable checksums. In addition, production
acceptance requires the real named target filesystem/host, enrolled protected
clock and independent CAS/frontier providers, an approved cloud account/bucket/
KMS policy, a live versioned publication/readback, production backup/restore/
retention drills and actual monitoring/alert integration. None is supplied by
setting a status flag or by writing this ledger. Preserve existing safety and
independent stochastic-policy acceptance gates.
