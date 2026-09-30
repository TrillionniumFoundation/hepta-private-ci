# channel.matrix current status

Status: **ordinary source frozen; metadata candidate and exact execution receipts pending. Not production-qualified.**

## Frozen ordinary-source identity

- ordinary-source commit: `712bc2e7e77bbb42b93d35ac4ea0730dabf572c5`
- ordinary-source tree: `87a2f91a1058322bc43bff690737c148fc9dc633`
- integration base: `main@a126987b84737dbc2ee2592442a314117bddb4a2`
- source binding: `IMPLEMENTATION_MAP.json` plus the external exact-candidate receipt

This document is part of a metadata-only descendant. A commit cannot contain its
own future Git identity, so the read-only exact-candidate workflow records the
metadata commit/tree, map bytes and inspected blobs externally. The ordinary
source above is immutable and is the only source snapshot qualified by this
metadata candidate.

## Repository-controlled closure

### Source, documentation and evidence consistency

- Source-writing, patch-apply and finalizer workflows and encoded staging bundles are absent.
- Matrix qualification workflows use `contents: read`; they do not edit, commit or push source.
- One v2 command policy is imported by receipt generation, status rendering, scenario qualification, paired verification and readiness derivation.
- Source-head and deterministic-merge lanes directly execute locked all-target build, public API compile-fail doctests, locked native and repository regression tests with Q01-Q29 JUnit, strict Clippy and rustfmt.
- The same command set covers every candidate-bound Rust owner: `codex-hepta-contracts`, `codex-state`, `codex-hepta-operations`, `codex-hepta-matrix-protocol`, `codex-hepta-matrix-store`, `codex-hepta-matrix-sdk` and `codex-hepta-matrixd`.
- `source-after.json` must equal `source.json`; `clean_tree` and `api_compile_fail` are separate evidence states.
- Tracked-source provenance rejects generated source, caches and artifact material, and binds workflow run, attempt, runner image, target triple and exact Git objects.
- One fail-closed readiness manifest binds source head, base, deterministic merge, GitHub synthetic merge, workflow identity, lockfile, migrations, test set, qualification profile, implementation map, documentation and artifacts. Evidence from different attempts cannot be combined.

### Runtime correctness

- `MatrixDurableStore` remains the single durable Matrix writer and terminal-truth owner.
- The typed pre-entry `Admission` and post-entry `EnteredSend` boundary remains intact.
- Post-entry persistence, authority, revocation, transport/session identity, cancellation, deadline, clock, store, permit and invariant faults retain distinct identity-free diagnostics while all remain conservative unknown effects.
- Transport acceptance is nonterminal; only authenticated `/sync` may qualify stable-transaction success or redaction.
- Stable transaction identity, random claim capability fencing, entered-use proof, delayed-echo attribution, terminal monotonicity and redaction lineage survive restart and retry.
- Compile-fail API coverage prevents construction of the raw seal, import of the private permit, override of the authorized adapter and raw SDK-client escape.
- The production transport TCB registers only the statically linked safe-Rust `MatrixSdkClient`; unsafe Rust, FFI, dynamic libraries and remote-sidecar physical-send modes are forbidden.
- Dispatch time uses a monotonic epoch and a separately observed wall anchor. Large forward jumps fail the sender closed; rollback retains the monotonic anchor and cannot extend a grant. Protected target-host clock-discontinuity execution is still external.

### Performance and operations

- Just-in-time single-record claiming is retained; `claim_limit` remains a work-per-pass bound.
- Bounded identity-free histograms cover claim-to-first-poll, final-use broker, revocation refresh, SQLite owner work and physical transport.
- Diagnostics and alert policy cover sync freshness, oldest unresolved and indeterminate work, parked work, claim expiry, rate limiting, authority denial, response loss, clock discontinuity and ingress-recovery pressure.
- Migration compatibility remains floor 13; `MIGRATIONS.md` and the recovery/runbook documents define forward migration, startup verification, rollback restrictions and operator evidence preservation.

### Production qualification contract

The repository contains closed machine-readable profiles and process drivers for:

- real enrolled homeserver and encrypted room execution;
- multi-device and session rotation;
- protected backup restore;
- ENOSPC, permission loss, WAL/SHM corruption and stale-snapshot recovery;
- sustained capacity, 429, reconnect, slow homeserver and long unknown effects;
- ACK loss, delayed echo, redaction, concurrent retry and sync rollback;
- broker rotation and stale owner, claim, session, authority and Supervisor fencing;
- forward/backward wall-clock discontinuity under a protected clock profile;
- target-bound Matrixd, Agentd, test-binary, configuration, process-identity, runner and homeserver-image identities;
- independent evidence reproduction, runbook, security, restore/rollback and release-boundary review.

These profiles define evidence; they do not manufacture it.

## Required next evidence

1. The metadata candidate must obtain terminal-success source-head and deterministic-merge receipts from one workflow run and attempt.
2. All mapped Q01-Q29 cases, API-negative proofs and clean-tree checks must pass in both lanes.
3. After integration, the real merge SHA must run again against its actual preceding `main` SHA; no PR-head receipt is reusable.
4. Protected real target execution and distinct security/operations acceptance signatures remain external.
5. Canary, activation, promotion and release remain separate governed decisions.

`productionImplementation`, `productExecutionProved`, `deploymentQualificationComplete`, `independentAcceptance`, `activation`, `promotion` and `release` remain **false**.
