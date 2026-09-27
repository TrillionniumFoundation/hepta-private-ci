# kernel.evidence implementation delivery, 2026-09-27

## Candidate and authority boundary

The sole integration candidate is PR #1092 on
`fix/kernel-evidence-production-closure`, based on exact `main`
`a126987b84737dbc2ee2592442a314117bddb4a2`. No force push, main merge,
independent approval, deployment, canary, promotion or release was performed.
Other module branches were not modified.

The direct A–C source-capability anchor is
`001e557716e884fbd47d5ab2f0ca9f47175f958e`, tree
`6ecfb41b6e18406ea019fbffa3a972aba5cc4baf`. Later commits synchronize
human-readable truth, implementation mapping and qualification triggering. They
do not inherit execution evidence from earlier heads.

This file is a delivery narrative, not a second canonical status source. The
machine-readable `STATUS_SOURCE.json` remains authoritative for persistent
qualification, deployment and governance gates.

## Historical starting point

The earlier delivery through `88dfa09120ecd856611d106dec485df3aa153e55`
closed the first recovery-snapshot slice and added diagnostic tests, but it
correctly recorded remaining gaps in publication, complete admission
provenance, monotonic trust, product paging, backup/build proof and long-running
history. Its local Python/SQLite probe was useful protocol evidence only; it did
not compile the Rust implementation or qualify any later Git object.

Those historical limitations must not be copied forward as the current source
state, and their historical runs or artifacts must not be copied forward as
current execution evidence.

## Current repository-controlled implementation

### A. Trustworthy decision semantics

- `identity_assignment.rs` implements bounded, frame-correct assignment of
  required roles to distinct principals and distinct signing identities;
- the fixed Alice/Bob three-role counterexample and exhaustive bounded oracle
  equivalence are native Rust tests;
- `qualification_policy.rs` owns a closed-world, non-empty verification profile
  inventory, so a caller cannot lower the required role set;
- `VerifiedEvidenceTrustSnapshot` and `VerifiedEvidenceIssuer` are sealed
  outside the evidence crate; production cannot pass arbitrary raw trust
  bindings or caller-constructed issuer registrations;
- trust schema V2 binds agent, generation, predecessor digest, signer policy and
  issuer/key/role inventory; stale, skipped and substituted generations fail
  closed.

### B. Persistence, recovery and publication

- authenticated qualification admission, replay advancement, immutable row and
  publication intent share one `BEGIN IMMEDIATE` mutation boundary;
- migration `0016` persists original signature material and accepted trust
  generation/digest for new rows; missing historical provenance is never
  fabricated;
- `qualification_commitment.rs` commits every authority-relevant admission
  field, not only the public envelope digest;
- `authenticated_recovery_snapshot()` reads migration, store identity,
  qualification commitment and replay frontier through one SQLite read
  transaction with row and byte bounds;
- trust and frontier acceptance are atomic at an exact expected snapshot;
- migration `0014` and `publication.rs` provide durable owner generation/lease
  fencing, exact publication batches and the states `prepared`, `dispatching`,
  `indeterminate` and `acknowledged`;
- uncertain external CAS outcomes are reconciled from authenticated latest
  state. A new operation ID or blind retry cannot erase uncertainty;
- local acknowledgement requires a durable backend acknowledgement or a
  re-synchronized matching historical record and atomically completes the
  frontier, batch and row intents.

### C. Product and long-running operation

- Agentd exposes stable cursor paging with a page maximum of 128 and returns a
  bounded verification summary instead of an unbounded evidence vector;
- development and production are explicit typed profiles; production cannot
  silently route through a legacy verifier;
- production admission hashes the actual backup object bytes and length,
  validates storage acknowledgement, governed source-to-executable build
  provenance and an independently identified successful restore witness;
- the production file backend keeps a bounded active tail, immutable linked
  segments and a self-authenticating atomic latest index;
- stale-index recovery, archived acknowledgement recovery, crash-duplicate
  prefix handling and capacity/headroom telemetry preserve history rather than
  clearing it.

### D. Documentation and integration truth

- `CURRENT_IMPLEMENTATION.md`, `STORE_V1.md` and `TRACEABILITY.md` describe the
  direct A–C source implementation and migrations through `0016`;
- `IMPLEMENTATION_MAP.json` maps the real evidence and Agentd operations,
  callers, writers and tests while keeping
  `productionImplementation=false` and `productExecutionProved=false` until the
  final candidate passes;
- the stable `TECHNICAL.md` blob is the version registered by the closed-world
  `MODULE_DOCS.json` index; detailed current closure facts live in the three
  synchronized companion documents and implementation map;
- legacy branch-writing closure generators are retired or suppressed on the
  sealed candidate so qualification cannot race a source rewrite.

## Verification state

The final integration head is identified in PR #1092 and carries
`[kernel-evidence-closure]` plus `[kernel-evidence-status-sync]`. Exact-source,
deterministic fixed-base merge, bounded-core, publication, Agentd, Lane-A,
documentation, implementation-map, architecture and blocking-CI workflows have
been requested for that head.

Queued, pending, skipped, cancelled and action-required results are not passes.
No final workflow run ID or artifact digest is written into
`STATUS_SOURCE.json` until the corresponding retained artifacts are successful
and bound to the unchanged final object. Any source repair creates a new
candidate and invalidates earlier exact-head claims.

## Remaining repository-controlled gates

1. Complete native formatting, strict lint, evidence/Agentd tests and builds on
   the unchanged final head.
2. Complete exact-source and deterministic fixed-base merge qualification with
   retained command JSON, raw logs and artifact digests.
3. Complete documentation, implementation-map, repository CI and architecture
   checks on that same object.
4. Preserve and administratively enforce the stable required-check fan-ins.

These are execution and repository-policy gates. They are not evidence that the
A–C source surfaces are absent.

## Remaining external gates

The following remain false until separately authorized receipts exist:

- deployment of the external rollback-domain storage with verified coherent
  locking, durable file/directory synchronization and power-loss behavior;
- issuer-trust and threshold-signer ceremonies;
- target-host contention, latency, capacity, RPO and RTO measurements;
- durable backup publication plus witnessed restore and rollback rejection;
- independent exact-candidate semantic and security acceptance;
- operator acceptance, canary, promotion and release.

Repository source and CI cannot manufacture those principals or advance their
states by inference.
