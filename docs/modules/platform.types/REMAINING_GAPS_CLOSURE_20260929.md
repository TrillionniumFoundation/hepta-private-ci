# `platform.types` remaining-gap closure — 2026-09-29

This note records source changes and exact acceptance boundaries. It is not a
qualification receipt, an independent approval, or a deployment authorization.

## Closed in source

### Explicit candidate selection

The deep workflow resolves `workflow_dispatch.inputs.candidate_ref`, freezes the
resulting full commit identity, and checks that the checked-out candidate equals
that identity. An invalid or missing requested ref fails closed; it is not
silently replaced with the default branch.

### Reproducible acceptance toolchain

Receipt-bearing native/MSRV work uses the explicitly pinned Rust 1.96.0
toolchain. Latest-stable compatibility remains a separate, non-substituting
signal. Candidate evidence records compiler, Cargo, runner, architecture,
workflow and workload context.

### Cryptographic registry identity

`ContractRegistryV1` uses its versioned canonical `Digest32`/SHA-256 commitment.
The legacy concern about an FNV checksum does not describe the current candidate.
The digest proves immutable content identity only; owner-pinned generation
freshness, authorization and final-use acceptance remain separate.

### Immutable registry lookup reuse

Construction now creates a bounded immutable digest projection sorted by
`(kind, digest, canonical entry index)`. `resolve_digest` performs a lower-bound
lookup in that projection instead of scanning all definitions. Exact identity
and numeric-profile lookup continue to reuse their canonical sort order. No
freshness, authorization or deployment conclusion is cached.

The existing same-candidate registry benchmark retains construction,
identity-lookup, digest-lookup and registry-identity timings for both an 8-entry
case and the 256-entry maximum. The new capacity regression test exercises every
digest entry and the kind-separated negative path.

### Product-owner boundary

The existing owner paths remain authoritative: NDU pins registry/root-seed
context and Runtime Supervisor pins topology, host and calibration context.
Every source-level admission receipt remains non-authorizing. Source composition
is not deployed activation, operator acceptance, promotion or release.

## Acceptance still required for the final exact head

A source commit is not accepted merely because these changes exist. The final
head and its deterministic synthetic merge must each execute all required gates
and retain their own successful receipt. Failure diagnostics and uploaded
artifacts do not become receipts. An eligible independent approval must bind to
the same final source head.

At the time this source note was prepared, the latest GitHub-hosted runs for the
then-current candidate were in GitHub's `action_required` state before jobs were
created. That state is an execution-authorization blocker, not a passing or
failing test result. Current status must always be read from GitHub checks and
retained artifacts rather than inherited from this dated note.
