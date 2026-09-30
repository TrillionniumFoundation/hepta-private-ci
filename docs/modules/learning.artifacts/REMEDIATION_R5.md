# learning.artifacts R5: owner boundaries, capability storage and live withdrawal safety

## Candidate identity and claim boundary

This document describes the source revision on branch
`work/learning-artifacts-owner-durability-revocation-20260930-r4`. The final Git
commit, deterministic merge and retained GitHub Actions evidence are supplied by
the qualification workflow, not by this document.

R5 does **not** assert target-host power-loss qualification, independent operator
acceptance, production activation, promotion or release. The daemon and storage
adapters are repository candidates. A physical power-cut claim remains false until
an independently controlled target-host run completes every required matrix case.

## 1. Four explicit owner boundaries

The product writer is now composed as:

```text
Request / current-authority validation
        |
        v
Publication state-machine coordination
        |
        v
OwnerPublicationStoreV1 + OwnerControlStoreV1
        |
        v
Recovery / reconciliation
```

`LearningArtifactOwnerService` no longer owns a concrete
`LearningArtifactOwnerHost`, durable marker filename or synchronization layout. It
holds two narrow injected ports:

- `OwnerPublicationStoreV1` owns the exclusive writer fence, authenticated current
  head discovery, immutable registry recovery, phase checkpointing, payload /
  registry / witness durability and acknowledgement;
- `OwnerControlStoreV1` owns the drain record and monotone scoped withdrawal floor.

`FsOwnerPublicationStoreV1` and `FsOwnerControlStoreV1` retain the reviewed file
implementation. `open_with_stores` checks the canonical root, registry identity,
withdrawal scope, storage binding and trust digest before recovery. A substituted
adapter cannot claim an unrelated store identity.

The publication transaction remains the existing
`Prepared -> PayloadDurable -> RegistryDurable -> WitnessDurable -> Acknowledged`
state machine. R5 does not create a second state machine or reinterpret historical
checkpoint bytes.

## 2. Live withdrawal and final-use authority

A verified registry snapshot alone does not describe the current withdrawal
frontier or expiry of the CURRENT authority. R5 adds `CurrentArtifactUseViewV1`,
which binds:

- the opaque `VerifiedCurrentRegistryViewV1`;
- `withdrawal_scope_digest`;
- `withdrawal_head_digest` and monotone `withdrawal_epoch`;
- CURRENT `authority_epoch`, generation and head digest;
- `authority_expires_at`;
- `verified_at`.

`WithdrawalAwareCandidateSessionV1` requires a fresh use view before every cached
use. It permanently closes on:

- any withdrawal-frontier or scope change;
- expired authority or verification-time regression;
- CURRENT generation / authority rollback;
- an equal-generation head fork;
- registry revalidation failure or a panicking consumer.

A withdrawal advance is conservatively treated as requiring explicit reload even
when the changed dataset is not obviously related to the candidate. Reload must
repeat the complete V3 admission and normal independently governed selection path.
An old pinned handle cannot infer that a withdrawal is irrelevant.

Agentd's learned ranker now consumes this final-use view for every ranking call.
A failed refresh removes the cached session; an old model cannot silently resume
when the current authority later becomes available.

## 3. Linux capability-safe path resolution

The Unix request-journal adapter already retained a root directory descriptor and
used relative `openat`. On Linux, R5 strengthens every descendant open to
`openat2` with:

```text
RESOLVE_BENEATH
RESOLVE_NO_SYMLINKS
RESOLVE_NO_MAGICLINKS
```

The canonical root itself is opened with no-symlink / no-magic-link resolution.
Create-only files remain `O_EXCL`, each final file is synchronized, and the already
opened containing directory is synchronized. No descendant operation re-resolves
an ambient absolute ancestor.

`owner_capability_store_profile_v1` exposes the effective profile:

- Linux: `LinuxOpenat2`, production-capability candidate;
- other Unix: `UnixOpenatNoFollowUnqualified`;
- non-Unix: `Unsupported`.

The production embedding refuses startup when the profile is not explicitly
qualified. There is no silent fallback from the required Linux capability model.
This does not establish physical media durability or protection against rollback
of the whole independently retained root.

## 4. Bounded single-writer embedding

`hepta-learning-artifactd` is a concrete single-process embedding over the existing
reference host. It:

- accepts only an absolute, regular, non-symlink configuration path;
- refuses a non-loopback listener;
- uses bounded 4-byte length-prefixed request / response frames;
- accepts only `SignedArtifactOwnerRequestV1` requests;
- relies on the existing keyring generation, peer key, freshness and per-action
  authorization checks;
- handles one request at a time under the service's exclusive writer fence;
- persists the existing durable shutdown intent before termination.

The transport itself grants no authority. No public-network TLS profile is added;
production exposure beyond a protected loopback supervisor remains outside this
candidate.

## 5. Target-host durability matrix

R5 adds a closed evidence contract rather than pretending that process-crash tests
prove physical durability. Every target-host qualification attempt must bind the
source commit/tree, binary, runner image, kernel, filesystem, block-device profile,
host identity, attempt and independent operator.

Every cross-product case is required:

| Persistence boundary | Required injected faults |
| --- | --- |
| write | process termination, forced unmount, VM power cut, truncated write, delayed write, old-directory restore, old-file restore, exact retry |
| file fsync | same eight faults |
| child-directory fsync | same eight faults |
| parent-directory fsync | same eight faults |
| checkpoint append | same eight faults |
| head publication | same eight faults |
| acknowledgement | same eight faults |
| restart / reopen | same eight faults |

Externally controlled cases such as power cut, forced unmount, delayed media write
and snapshot restore require an independently observed result. Missing, duplicate,
identity-free or contradictory cases fail the report. An indeterminate effect
cannot be upgraded to success.

This schema is a harness contract, not the completed target-host run. Until a real
selected host executes it, `externalPhysicalDurabilityProved` remains false.

## 6. Recovery, backup and migration boundary

The existing reference host continues to provide signed request authentication,
create-only request/result journaling, exact replay, backup, restore, migration,
status and operational metrics. R5 does not claim that those repository adapters
constitute an accepted deployment.

Whole-store rollback resistance still requires independently retained monotone
CURRENT and withdrawal floors outside the restored root. Backup and migration
qualification must prove that old directory and single-file restores fail closed.
No normal retry may delete or overwrite an uncertain record.

## 7. Verification obligations

The exact candidate must pass, from one workflow attempt:

- exact-head and ordered deterministic-merge lanes;
- Linux x86_64, Linux ARM64, macOS ARM64 and MSRV profiles;
- closed-world/source-object binding;
- locked all-target build;
- strict Clippy and rustfmt;
- complete nextest discovery and execution without skips or retries;
- source-bound requirement traceability;
- readiness aggregation that rejects mixed attempts.

New source obligations include:

- injected publication/control store identity rejection;
- withdrawal-frontier advance, authority expiry, time regression and head fork;
- Linux symlink/magic-link/beneath resolution;
- non-Linux production-profile refusal;
- complete durability-matrix validation and missing/external-observation rejection;
- bounded daemon framing and signed command dispatch.

## 8. Completion state

Repository source now contains the owner/storage split, Linux capability backend,
live withdrawal-aware use boundary, reference daemon and durability evidence
contract. The following remain separate and false until independently established:

```text
exactHeadQualification = pending_current_candidate
externalPhysicalDurabilityProved = false
independentAcceptance = false
productionActivation = false
promotion = false
release = false
```

The final immutable implementation map and readiness manifest must bind the actual
candidate SHA. No document, receipt hash or locally green subset authorizes merge,
activation or release.
