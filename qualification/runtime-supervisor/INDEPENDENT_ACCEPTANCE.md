# runtime.supervisor independent acceptance and release ceremony

This ceremony begins only after the final candidate has green exact-source and
prospective-merge qualification on every required host profile. It prepares an
externally reviewable packet; it does **not** let repository CI, the source
producer, or the Supervisor process grant itself deployment qualification,
operator acceptance, promotion, merge, or release authority.

## 1. Roles and independence

The following roles are distinct:

- **source producer** — writes the Supervisor source and repository-controlled
  qualification harness;
- **qualification runner** — executes the exact candidate and retains command,
  host, artifact and failure receipts;
- **threat-model reviewer** — reviews authority, replay, process, filesystem and
  recovery boundaries independently of the source producer;
- **recovery-drill operator** — performs the target-host recovery drill against
  the frozen artifact set;
- **acceptance signer** — signs the bounded operator decision with trust material
  not stored in the repository or its CI secret set;
- **release authority** — decides whether the accepted artifact may be promoted
  and deployed.

A different display name is not independence. Where policy requires multiple
roles, they must use distinct authenticated principals and distinct signing
identities. Repository workflows may verify externally supplied receipts but
must never mint the receipt they are verifying.

## 2. Frozen candidate inputs

The acceptance reviewer receives an immutable packet containing:

1. source commit and tree;
2. base commit plus the deterministic prospective-merge commit/tree and ordered
   base/source parents;
3. the four Supervisor qualification lanes:
   - Linux source head, at least 256 real process fixtures;
   - Linux prospective merge;
   - macOS source head, at least 64 real process fixtures;
   - macOS prospective merge;
4. each lane's `result.json`, `physical-host.json`,
   `physical-host-policy.json`, bounded logs and uploaded-artifact digest;
5. frozen binaries and SHA-256 digests for:
   - `hepta-supervisord`;
   - `hepta-supervisor-release-controller`;
   - `hepta-authority-signer`;
6. the exact production authority/recovery protocol source digests;
7. the implementation map, caller inventory, recovery runbook and threat model;
8. target deployment configuration, external public-key distribution and
   revocation/rotation policy;
9. recovery-drill and long-soak evidence produced outside repository CI.

Run `scripts/hepta-supervisor-acceptance-bundle.py` from a clean checkout of the
final source commit after downloading the four workflow artifacts and freezing
the three production binaries. The tool verifies exact source/merge identity,
requires every command and host-policy gate to pass, binds the chosen
`hepta-supervisord` binary to its physical-host receipt, and emits a canonical
manifest plus SHA-256 sidecar. Its output status is only
`prepared_for_external_review`; every authority flag remains false.

Example shape, with paths replaced by the externally retained artifact roots:

```text
python3 scripts/hepta-supervisor-acceptance-bundle.py \
  --source-commit "$SOURCE_SHA" \
  --source-tree "$SOURCE_TREE" \
  --base-commit "$BASE_SHA" \
  --merge-commit "$MERGE_SHA" \
  --merge-tree "$MERGE_TREE" \
  --lane linux-source-head=/evidence/linux-source \
  --lane linux-merge-candidate=/evidence/linux-merge \
  --lane darwin-source-head=/evidence/darwin-source \
  --lane darwin-merge-candidate=/evidence/darwin-merge \
  --artifact hepta-supervisord=/frozen/bin/hepta-supervisord \
  --artifact hepta-supervisor-release-controller=/frozen/bin/hepta-supervisor-release-controller \
  --artifact hepta-authority-signer=/frozen/bin/hepta-authority-signer \
  --release-lane linux-source-head \
  --out /frozen/audit/runtime-supervisor-acceptance-bundle.json
```

The frozen packet must be moved to read-only storage before independent review.
Changing any binary, receipt, protocol source, trust policy or deployment
configuration creates a new candidate and invalidates the prior decision.

## 3. Threat-model review

The reviewer must explicitly decide whether the frozen candidate preserves all
of the following properties:

- daemon socket peer identity is owner-local and bounded;
- ordinary release mutation cannot bypass signed production authority;
- caller, signer, daemon and durable owner have distinct responsibilities;
- private key material never enters the daemon, release-controller journal,
  logs or qualification artifacts;
- grant, recovery decision and response bind exact agent, transition, authority
  epoch, control revision, lifecycle generation, intent digest, transaction
  digest, release identity, binary/manifest digest and expiry as applicable;
- exact duplicate delivery is idempotent and conflicting replay is rejected;
- stale signer epoch, revoked key, substituted purpose, stale generation,
  substituted release or mismatched intent cannot produce a terminal success;
- an unresolved signed intent keeps the daemon reachable but not ready and
  prevents another release transition;
- lifecycle termination never establishes user-task success;
- typed drain closes admission and preserves durable unknown/indeterminate work
  for reconciliation;
- registry, release transaction, restart budget, caller journal and recovery
  record failures fail closed;
- emergency kill authority is not silently widened into release authority;
- repository qualification cannot assert deployment qualification or operator
  acceptance.

The review records every rejected assumption and every deployment-specific
condition. A conditional acceptance expires when any bound condition changes.

## 4. Target-host recovery drill

GitHub-hosted Linux/macOS evidence is repository-controlled host-boundary
qualification, not deployment qualification. The deployment operator must rerun
the frozen artifacts on the actual host profile and retain at least:

- normal start, health, typed drain, stop, restart, signed upgrade, signed
  rollback and signed recovery;
- daemon `SIGKILL` followed by exact child adoption without duplicate spawn;
- child death at each release-transaction cut;
- 10%, 50% and 100% concurrent child crash waves with unrelated process
  identity preserved;
- restart flapping through durable budget exhaustion and restart-window reset;
- malformed, oversized and trickled control/drain frames;
- PID reuse/stale lease simulation;
- permission denial, read-only path, `ENOSPC`, write error, rename failure,
  file `fsync` failure and parent-directory `fsync` failure;
- torn journal tail and acknowledged-prefix rollback rejection;
- external authority key rotation and revocation;
- stale/replayed grant and recovery decision;
- system-manager restart and machine reboot;
- artifact replacement, wrong owner/mode and digest mismatch;
- durable Automation/TaskFlow work during drain;
- clock rollback and expiry boundaries;
- sustained mixed read/mutation load with the documented lock-wait, snapshot,
  tick-delay, restart-detection and journal-publish SLOs;
- hardware power loss or an equivalent storage-controller cut on the actual
  durability stack;
- long soak with bounded file, descriptor, process, memory and journal growth.

A simulated CI interposer is useful evidence for named system-call cuts but is
not a substitute for the actual filesystem, kernel, service manager and storage
stack.

## 5. External acceptance receipt

The acceptance signer reviews the frozen packet digest and target-host drill,
then emits a detached, canonical receipt containing at minimum:

- receipt schema/version and unique decision ID;
- exact source/base/merge commits and trees;
- acceptance-bundle SHA-256;
- all frozen artifact SHA-256 values;
- deployment-host profile digest;
- authority trust-policy digest and key epoch;
- reviewer principal and signing-key fingerprint;
- reviewed threat-model and recovery-drill digests;
- `accept`, `reject`, or `abstain`;
- bounded conditions and explicit expiry;
- `automatic_transition=false`;
- no merge, promotion or release authority.

The receipt is signed outside the repository with externally governed trust
material. Verification must check canonical encoding, signature, signer
allow-list, scope/purpose, key epoch and revocation, exact packet digest,
non-replay decision identity and expiry. Storage of an authentic decision does
not transform `reject` or `abstain` into acceptance and does not grant release.

The existing repository-specific `hepta-operator-acceptance` V1 tool is bound to
its own frozen product roots; it must not be silently reused for this module.
Either an externally governed runtime-supervisor profile is added to that same
acceptance system and independently qualified, or an equivalent external
verifier is selected. Creating a second in-repository self-approval path is
forbidden.

## 6. Release decision

Release is a separate action after a valid unexpired acceptance receipt exists.
The release authority must:

1. rehash the deployed binaries and compare them with the accepted packet;
2. reverify the exact authority public key, signer epoch and revocation state;
3. reverify deployment configuration and service-manager unit digest;
4. confirm rollback predecessor availability and recovery operator readiness;
5. execute a bounded canary with audit receipts;
6. issue a distinct release decision bound to candidate, artifact, host,
   acceptance receipt and expiry;
7. preserve an immediate, rehearsed rollback path.

Only after those externally governed steps may a separate, reviewable change
update activation or release state. The source candidate and its own CI must
keep `deploymentQualificationComplete=false`,
`independentAcceptanceComplete=false`, `activation=false` and `release=false`.

## 7. Current status

This repository now provides the source-side caller, writer, signer, signed
recovery path, cross-platform exact-candidate qualification and packet-preparation
mechanics. No independent external acceptance, actual deployment-host power-loss
receipt, activation, promotion or release decision is asserted by this document.
