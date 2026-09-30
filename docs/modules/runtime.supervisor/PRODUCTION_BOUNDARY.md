# runtime.supervisor production composition boundary

This document defines the product boundary that must be true before
`runtime.supervisor` can be activated. It is a requirement, not deployment or
acceptance evidence. Current source, repository qualification, target-host
qualification, independent acceptance and activation are separate facts in
[`CAPABILITY_STATUS.json`](CAPABILITY_STATUS.json).

## 1. Build separation

The lifecycle daemon and offline authority tools have different build identities:

- `production-verifier` enables public-key verification and signed mutation
  admission for `hepta-supervisord`;
- `offline-authority-tools` enables private-key loaders and signer/approver
  binaries and implies the verifier contracts needed to validate what they emit;
- `qualification` enables deterministic fault injection and must not appear in a
  production daemon artifact;
- `production-authority` is retained only as the internal compatibility feature
  implied by `production-verifier`; product manifests must not select it directly.

A production daemon is built with exactly `production-verifier`. Its artifact
receipt must prove that `qualification` and `offline-authority-tools` were not
enabled and that no signer, approver, revocation-signer or authority-bundle
construction binary is present in the shipped daemon image.

`hepta-supervisord` accepts production trust material only through
`--authority-bundle ABSOLUTE_PATH --authority-bundle-sha256 SHA256`. The former
six-field grant/H7 key, signer-id and epoch tuple is not a supported daemon
interface. The bundle contains public verification material only and is pinned
by its canonical digest before Fleet state is opened.

## 2. Service identity and filesystem isolation

The deployment manifest must name a dedicated supervisor service identity. The
following are acceptance requirements:

1. `hepta-supervisord` runs under a service UID that is not shared by Agentd,
   Matrixd, App Server workers or ordinary operators.
2. The Fleet root, supervisor lock, authority bundle and control-socket parent
   are writable only by the supervisor service identity or a narrowly scoped
   installer identity.
3. Managed children do not inherit a writable Fleet root, the administrative
   control socket, authority material descriptors or offline signer material.
4. A platform confinement policy—systemd sandboxing plus AppArmor/SELinux on
   Linux, or the corresponding launchd/sandbox controls on macOS—denies child
   access even when discretionary permissions are accidentally widened.
5. Observation and destructive administration endpoints are separated by
   deployment policy. Same-UID Unix-domain peer checks are not treated as a
   security boundary against a compromised sibling process.
6. The deployment receipt binds UID/GID, socket path and mode, Fleet-root owner
   and mode, authority-bundle owner and mode, confinement policy digest, unit or
   launch manifest digest and final daemon binary digest.

## 3. External key custody

The supervisor never loads a private signing key. Production acceptance requires
content-addressed receipts for:

- key creation and custody location;
- signer identity and epoch rotation;
- revocation propagation and stale signer rejection;
- emergency restore from an independently protected backup;
- deletion or retirement of predecessor signing material.

Each ceremony must bind the authority-bundle digest installed on the target
host, the verifier key identities, operator identities, timestamps, policy
version and immutable raw audit material. A source fixture or repository test
key is never a custody receipt.

## 4. Recovery observation

The current signed recovery decision binds the grant, signed intent, release
transaction, observed immutable release bytes, lifecycle generation and daemon
authority epoch. Production activation additionally requires one daemon-generated
`ProductionRecoveryObservationV1` created under the lifecycle owner boundary.
Its digest must bind at least:

- supervisor epoch and observation sequence;
- Agent identity and lifecycle generation;
- exact main and Matrix process identities;
- current release bytes and admission-frontier digest;
- durable control-intent and release-transaction digests;
- signer/bundle epoch and bundle digest;
- capture time and expiry.

Client-side double reads may remain a diagnostic technique but are not an atomic
snapshot and cannot satisfy this gate. Until the source and tests for this
observation exist, the capability remains `not_implemented` and production
acceptance must fail closed.

## 5. Target-host and production evidence

[`TARGET_HOST_PROFILE.json`](TARGET_HOST_PROFILE.json) freezes the supported
host/filesystem combinations, 256-real-process workload, fault scenarios and
latency/watchdog SLOs. Target-host receipts are validated by
`scripts/hepta_supervisor_external_receipt.py target` and remain distinct from
repository CI.

[`PRODUCTION_QUALIFICATION_PROFILE.json`](PRODUCTION_QUALIFICATION_PROFILE.json)
requires final-merge target-host receipts for Linux and macOS, key-custody
receipts, the atomic recovery observation, an independent operator recovery
drill, and distinct accepted reviews for code, security and operations. The
production validator rejects an embedded activation claim: acceptance records
eligibility, while activation remains a separate controlled action.

Every fault result binds the final binary digest, source/base/merge identities,
workflow identity, host/kernel/filesystem, feature set, profile and workload
digests, fault cut, raw log digest, and durable snapshots before and after the
cut. Missing, queued, skipped or stale evidence is not a passing result.
