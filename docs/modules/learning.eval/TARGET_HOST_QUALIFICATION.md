# `learning.eval` target-host qualification

This document defines the externally issued evidence packet required to move
beyond repository source qualification. It does not declare any host qualified.
The machine verifier is `scripts/hepta-learning-eval-target-host.py`; generated
repository source truth remains `CURRENT_STATUS.json`.

## Claim separation

Repository CI can prove that one exact candidate and its ordered-parent synthetic
merge compile, pass tests, satisfy coverage and emit attested source evidence.
Those facts do **not** authenticate a deployment host, prove storage semantics on
the selected topology, establish real future-calendar outcomes, provide
independent acceptance or authorize activation and release.

A packet uses schema `hepta.learning-eval.target-host-evidence.v1`. It is supplied
by deployment and independent qualification authorities, never synthesized from
`learning.eval` source or CI. The verifier rejects missing fields, duplicate JSON
keys, identity collisions, invalid time ordering and claims stronger than their
evidence.

## Exact candidate binding

The `candidate` object binds:

- the exact commit SHA and tree SHA;
- the SHA-256 digest of `codex-rs/Cargo.lock`;
- the SHA-256 digest of `PRODUCTION_CONTRACT.md`;
- the SHA-256 digest of `CURRENT_STATUS.json`.

With `--require-current-candidate`, commit and tree must equal the checked-out
`HEAD` and `HEAD^{tree}`.

## Host topology and trust

`host.topology` is closed to:

```text
single_host
cross_host
```

The host object binds the host identity plus OS/kernel, filesystem, trusted clock
and resource-measurement profiles. The trust object binds the active trust
distribution, revocation snapshot and authority epoch. Request payloads cannot
construct or replace these host-owned values.

A `single_host` packet must not claim cross-host qualification. A `cross_host`
packet may claim target-host qualification only when it also carries a nonzero
cross-host qualification digest and asserts qualified lock, CAS and fsync
semantics for the actual shared storage topology.

## Storage qualification

The storage object binds:

- final-holdout namespace;
- independently retained rollback anchor store;
- qualification publication store;
- evaluation-attempt journal;
- fault-injection report;
- capacity/recovery/compaction profile.

A true `targetHostQualified` claim requires all of the following:

1. linearizable CAS for the selected topology;
2. qualified fsync and containing-directory durability;
3. rollback anchor retained independently from journal backups;
4. accepted-but-unknown publication reconciled without duplicate semantic writes;
5. stale writers rejected after fence takeover;
6. stale backup restoration rejected;
7. crash recovery exercised against the deployed storage implementation;
8. cross-host qualification when and only when `host.topology` is `cross_host`.

The repository locked-file backend provides source-tested single-filesystem
behavior. It does not self-qualify an arbitrary network filesystem.

## Longitudinal, privacy and unlearning evidence

The packet carries at least two non-overlapping real future-calendar windows.
Every window binds:

- stable window identity;
- start, end and observation times in Unix microseconds with
  `start < end <= observed`;
- positive observed count;
- a distinct source-cut digest;
- outcome-evidence and observer-attestation digests.

At least three distinct snapshot identities are required. The packet also binds
retention, change-point, statistical-power, subgroup/privacy, unlearning and
backup non-resurrection evidence. Synthetic IDs, virtual time and repository test
fixtures do not satisfy this section.

## Closed-world role separation

`acceptance.roles` must contain exactly these seven roles:

```text
generator
evaluator
observer
semanticReviewer
operator
selector
release
```

Each role binds a principal identity, credential-chain digest, signing-key digest,
controller digest and attestation digest. The seven roles must be pairwise
distinct independently on all four authority dimensions:

- principal;
- credential chain;
- signing key;
- controller.

Changing a display name while retaining a shared controller or key does not count
as independence.

The acceptance object separately binds semantic acceptance, operator acceptance,
canary, selection, promotion and release authorization evidence.

## Monotone claims

Claims may only advance in this order:

1. `targetHostQualified` requires the complete storage qualification for the
   declared topology;
2. `independentAcceptance` requires target-host qualification;
3. `productionQualified` requires target-host qualification and independent
   acceptance;
4. `activationAuthorized` requires production qualification;
5. `releaseAuthorized` requires both production qualification and activation.

The verifier never turns a false claim into true. It only checks whether a
supplied true claim is supported by a complete, candidate-bound packet.

## Verification

```bash
python3 scripts/hepta-learning-eval-target-host.py self-test
python3 scripts/hepta-learning-eval-target-host.py verify \
  evidence/learning-eval-target-host.json \
  --require-current-candidate
```

The output is a structural, candidate-bound verification receipt. Cryptographic
signature verification, issuer authorization, evidence retrieval and long-term
retention remain responsibilities of the external evidence authority and selected
host trust profile.
