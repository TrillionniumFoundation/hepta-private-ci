# utility.ndu unified candidate

Status: source candidate; exact-head and deterministic synthetic-merge qualification must be regenerated for every head; production activation and release authority are false.

## 1. Purpose

This document is the execution record for the single `utility.ndu` integration line. It prevents code, evidence and status from being assembled mentally across unrelated branches.

The unique line is `work/utility-ndu-unified-candidate-20260930`, reviewed by PR #1225 against `main`. It descends from current `main`, the #1140 A-D convergence line and the #1206 bounded FBSDE line, and contains a two-parent integration of #1221 production hardening.

## 2. Conflict-resolution policy

Where the three lines touched the same surface, the integration used these rules:

1. preserve the implementation with the stronger mutation, replay and recovery invariant;
2. preserve V1 source compatibility rather than privatizing a published V1 field in place;
3. add V2/V3 validated construction and migration rather than changing V1 meaning;
4. retain exact journal predecessor-CAS and capacity reserved for every possible live revocation;
5. retain context-bound iteration receipts and the authenticated owner/store path;
6. import the V2 artifact catalog, hierarchy snapshot proof and production-hardening contracts;
7. never inherit a qualification receipt from either parent.

The resulting candidate is one Git history and one tree. A capability present only in an abandoned parent branch is not part of the candidate.

## 3. Source and evidence ownership

The closed-world source definition is the union of:

- `IMPLEMENTATION_MAP.json` — canonical baseline operations and source objects;
- `IMPLEMENTATION_MAP_EXTENSIONS.json` — previously reviewed A-D and FBSDE extensions;
- `IMPLEMENTATION_MAP_UNIFIED.json` — current integration operations and exact object overrides.

The unified map may hash the historical maps as inputs but may not hash itself. This avoids self-referential object IDs while still binding every source, script, workflow and normative document consumed by qualification.

The current source head does not embed its own passing status. Workflow receipts own the exact source SHA, tree, base, deterministic merge, ordered parents, command lines, exits, log hashes and cleanliness result.

## 4. Version and migration matrix

| Surface | V1 behavior | Additive current behavior | Migration rule |
| --- | --- | --- | --- |
| iteration receipt | public fields and context-bound digest | sealed `NduIterationReceiptV2` with full canonical recomputation and legacy receipt binding | V1 must independently validate before V2 is emitted |
| Z/Q24 receipt | public converted coefficients, raw Q24 and digests | V2 also binds the original source matrix and recomputes conversion, quantization and both digest layers | caller must supply original source matrix and admitted profile; missing input cannot be guessed |
| projection journal | semantic V1 journal/store | projection catalog V2 separates action from preference/utility/coefficient kind and binds durable artifacts | explicit resolver supplies immutable artifact bindings; ambiguous legacy kind fails closed |
| store image | crash-bounded V1 writer | additive catalog/epoch candidates | immutable V1 backup before first acknowledged V2 mutation; after acknowledgement rollback is forward-only |
| hierarchy evidence | deterministic snapshot/path self-consistency | signed V2 proof with key ID, trust revision, validity, policy and revocation frontier | unsigned V1 proof is not promoted to authenticated evidence without an external signer |
| artifact location | bounded printable locator | V2 content-addressed or exact-version-plus-content-digest locator | mutable locator alone is rejected |

The public API baseline and external compile fixture make accidental V1 field privacy/removal/reordering a qualification failure.

## 5. Authenticity model

`NduAuthorityTrustBindingV2` admits an Ed25519 verifying key only together with:

- stable key identity;
- validity interval;
- non-zero trust revision;
- policy digest;
- canonical binding digest.

Signed hierarchy and artifact payloads include domain separation, complete semantic fields, signer identity, policy, issuance/expiry, revocation epoch and revocation-frontier digest. Verification uses trusted caller-supplied time and current revocation state. A valid old signature with a stale epoch or stale frontier is rejected.

Authenticated artifact V3 binds the signed projection to the validated durable artifact binding and the immutable locator binding. Signature validity cannot compensate for locator drift, content-digest drift or durable-binding drift.

## 6. Replay and current-use state machine

The state machine distinguishes:

```text
historical operation outcome
        !=
current selected artifact
        !=
current final-use admission
```

Historical replay is resolved by operation identity and semantic digest. It allows a caller to reconcile a lost response without repeating a mutation. It remains valid evidence of the old terminal result after later revocation.

Current-use admission separately verifies:

- catalog still selects the requested projection;
- authenticated artifact projection and durable binding match that selection;
- authenticated artifact has not expired;
- trusted-time receipt is present;
- current revocation frontier is present;
- artifact-availability receipt is present;
- final-use grant binding is present;
- current production policy is present.

A later revocation removes the selection and therefore blocks current use while leaving historical replay intact.

## 7. Production composition

The closed role set is deliberately explicit:

| Role | Required binding |
| --- | --- |
| persistent projection store | adapter, implementation/configuration digest, policy revision, deployment instance, capability receipt |
| authenticated owner/writer | same |
| process fence | same |
| cross-host fence | same |
| trusted time | same |
| revocation frontier | same |
| artifact registry | same |
| encrypted remote backup | same |
| restore executor | same |
| metrics exporter | same |
| real product caller | same |

Duplicate roles, duplicate adapter identities and missing roles fail closed. The composition digest is deterministic over the closed role order.

A readiness receipt can be sealed only when source, merge, target host/filesystem, shared-volume fence, backup readback, restore drill, metrics delivery, real caller and independent stochastic evidence are all supplied. The receipt is still deny-all evidence and cannot mint activation.

## 8. Verification matrix

The current source candidate must cover at least:

- publish/select/revoke/identical replay/current-use separation;
- V1-to-V2 migration, ambiguous legacy projection and forward-only rollback;
- restart/reopen, truncated or corrupt journal and semantic rehash attacks;
- catalog and journal capacity, revocation reserve and duplicate identity;
- stale owner, stale generation and predecessor-CAS/ABA rejection;
- process kill around write, file sync, rename and directory sync;
- ENOSPC, EDQUOT, EROFS, permission, symlink, hard-link, root/lock replacement and indeterminate commit;
- backup acknowledgement loss and restore monotonicity;
- concurrent writer and fence loss;
- frozen V1 source API and additive V2 exports;
- signature, time, policy, key, locator and revocation mutations;
- FBSDE leakage, numerical reference, convergence, calibration, utility improvement, shadow volume and rollback.

Hosted fixtures prove only their named environment. The target production filesystem and external services require separately retained receipts.

## 9. Qualification lanes

The exact-head and synthetic-merge lanes must run the same source-defined suites. The deterministic merge uses the current base and exact source head in an ordered two-parent commit with a reproducible tree.

At minimum, release consideration requires all of the following on one source head:

- NDU deterministic qualification aggregate;
- NDU cryptographic fixture gate;
- public API compatibility in both lanes;
- development-document projection;
- Lane-D semantic conformance;
- blocking CI, all-target compilation and strict Clippy;
- named-host and fault receipts;
- clean source before and after every suite.

No provider or consumer expansion is permitted while these gates are red.

## 10. Independent FBSDE evidence

The FBSDE candidate is not accepted merely because training code converges on a fixture. The independent evidence object requires registered data, immutable location, filtration/leakage audit, independent oracle, convergence/calibration/utility/regression acceptance, sufficient shadow volume, advisory and restricted-write runtime receipts, target-host evidence and rollback policy.

The rollback evaluator uses integer Q24 thresholds for holdout error, calibration error, utility improvement, failures and minimum decision count. Any violated threshold sets a deterministic reason bit. A triggered rollback receipt blocks independent acceptance.

Even a complete independent-acceptance receipt stays `DENY_ALL` and records no production activation.

## 11. External closure

Source work cannot manufacture:

- real target-host power-loss behavior;
- approved cloud account, bucket, key policy or immutable object version;
- off-host copy count and readback;
- restore, retention and deletion execution;
- deployed alert delivery and operator response;
- independent model-governance approval;
- canary, promotion, production activation or release authorization.

Those remain explicit external gates and must appear as retained, identity-bound receipts before any readiness claim changes.
