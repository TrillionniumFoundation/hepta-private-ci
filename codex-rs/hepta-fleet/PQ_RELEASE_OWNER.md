# Fleet PQ release owner

The ordinary Fleet release consumer uses the existing M15 release authority,
the Fleet publication journal, and a separately configured PQ-authenticated
release frontier. A valid publisher signature is necessary but does not by
itself authorize a process launch: the current release set, per-agent
allowance, actual installed bytes, trusted time, and complete external frontier
must still agree at the real spawn or adoption entry.

## Opening and independent trust inputs

`FleetRegistry::initialize` and `open_existing` open state only. They remain
usable by state readers, but installation, allowance, and release resolution
require a release authority. They never infer a release root from that state.

Use these explicit entry points:

| Entry point | Required state and effect |
| --- | --- |
| `initialize_with_release_authority` | Explicit first initialization, externally pinned initial M15 root and configuration, absent external release frontier. Writes the first durable journal and exact external CAS. |
| `open_existing_with_release_authority` | Existing journal and a fresh, complete matching external frontier. Never bootstraps or clears an uncertain attempt. |
| `recover_completed_release_update` | An actual externally committed original or reconciliation winner. Validates its exact retained bytes and finishes local publication without another CAS or process effect. |
| `open_existing_for_release_intent_recovery` | Explicit, fenced recovery mode for a validated retained intent-only publication. Cannot install, allow, resolve for launch, spawn, or adopt. Successful recovery still requires an ordinary reopen. |

`FleetReleaseTrustConfig` requires schema `1`, profile
`hepta.fleet.release-trust.pq.v1`, an owner identifier beginning with
`hepta.fleet.release.` (nonempty suffix, total at most 128 bytes), nonzero
`initial_root_sha256`, `network_id`, and `platform_sha256`, and separate explicit
clock/frontier endpoint descriptions. Each endpoint pins the Unix socket,
peer UID, service ID, key generation, canonical ML-DSA-65 public SPKI/key ID,
and a bounded timeout. The initial root, service identity, and expected
external history are operator inputs; placing a new checkpoint beside a
rolled-back journal does not create independent rollback protection.

`FleetReleaseTrustConfig::read` uses the bounded, immutable regular-file reader.
The ordinary supervisor requires `--release-trust-config ABSOLUTE_PATH`.
H7 production mutation additionally requires the explicit
`--production-authority-policy ABSOLUTE_PATH`; that file's exact bytes must be
the current M15 `ProtocolConfiguration` content. Control authorization and
software publication are separate roles of the same retained owner.

`initialize_for_qualification` and `open_existing_for_qualification` are
explicit test/qualification interfaces. Enabling the qualification feature
through dev-dependency unification never makes the ordinary daemon select them.

## Publishing, installing, and rolling releases

1. Construct a `hepta.fleet.release-set.v1` record containing every release
   that may currently run, including old and new members during a rolling
   transition. Each member binds its exact Fleet manifest, argument vectors,
   agentd bytes, optional matrixd bytes, and its actual source/build/SBOM record.
2. Sign the set's real M15 bundle digest for `NodeSoftware` using the current
   publisher root, and submit the signed JSON to `publish_release_set`.
   `rotate_release_root` uses M15's original dual-authorized root transition.
   `publish_protocol_configuration` separately accepts the signed H7 policy
   digest under the `ProtocolConfiguration` role.
3. Install the exact current signed member through the ordinary Fleet install
   API, then call `allow_release` for the intended agent. The journaled
   allowance and local marker only narrow the publisher's current set;
   neither can keep a withdrawn or expired member authorized.
4. Keep both versions in a current signed set to permit rolling restarts or
   an authorized rollback. Removing a member, expiring the set, revoking its
   per-agent allowance, or rotating its authority invalidates later use.

The set uses `releases/<release-id>/...` artifact and SBOM namespaces. Required
packages preserve actual `codex-hepta-agentd` and, when present,
`codex-hepta-matrixd` names, versions, and sources within that namespace. An
empty required-package list is not accepted. The outer publisher signature
covers the exact member build records; it does not fabricate independent old
bundle signatures or prove that a build was reproduced.

The set is limited to 8 MiB and 256 members, subject also to M15's existing
artifact/package bounds. The entire journal, including retained reconciliation
material, remains limited to 32 MiB. History is not pruned to evade a bound.

## Current admissions and stable transaction bindings

Keep `CurrentReleaseAdmission` through the actual spawn/adopt entry. Revalidate
after copying, hashing, or queueing. The consumer re-reads the exact manifest
through one bounded regular-file descriptor, checks the actual program bytes,
then checks fresh trusted time and the full external frontier. This is a
current-use guard, not a clonable observation or a promise of atomic execution
against arbitrary concurrent filesystem mutation by the same UID.

The semantic permission digest binds the initial root, actual M15 publication
checkpoint, exact release member, and this agent's retained allow/revoke
projection. The admission binding also includes the original local markers.
An intent-only journal event advances the complete external frontier without
changing this permission digest. Actual root, policy, release-set, or relevant
allowance changes still invalidate the binding. Every use continues to check
the complete fresh frontier; a stable permission digest cannot replace it.

## H7 intent history and uncertain publication

H7 anchors each full durable intent before actual dispatch. A typed anchor
binds the agent, monotonic generation, complete intent digest, stable grant
identity, original grant-policy identity, and phase. Completed history also
binds the exact transaction and release-state CAS witness. Consumed grant
identities are retained. H7's existing 32-decision history bound remains in
force; an unconfirmed local abort stays fenced.

The current policy/release guards expose same-lock anchor observations and
consume exact expected-old anchors for an update. The H7 owner must first
verify the real PQ signature and complete intent/state/history obligations.
It then calls `with_verified_decision_window` with the actual signed window
(or the grant/artifact intersection), using checked seconds-to-milliseconds
conversion. A recovery, confirmation, retry, or new pending transition with
no bound window is rejected. The window, both current roles, trusted clock,
and full frontier are checked again after proposal/attempt fsync and before
the external CAS. Historical completion records and known-winner cleanup do
not revive or require an expired old grant.

Any uncertain CAS response leaves the original attempt and proposal intact.
A later old frontier read cannot prove that an earlier request will never
complete. The explicit `--release-intent-recovery` daemon mode admits only
status, signed recovery, and necessary containment; it never grants launch
permission and never silently replaces ordinary open.

For an eligible intent-only attempt, `admit_pending_intent_reconciliation`
returns a separate recovery guard. A fresh signed unknown disposition or
completion-publication confirmation may create one bounded replacement
proposal with the same expected external frontier. A late original and that
replacement cannot both win. Both are retained until a fresh complete winner
is known. The replacement journal retains the exact original attempt and last
intent delta, with its original set and previous-frontier context, so a later
release-set publication cannot erase the original proposal's provenance.

If the replacement itself is uncertain, or its proposal was fsynced before its
attempt could be created, ordinary recovery remains fenced. A separate fresh
signed `retry_retained_publication` decision must bind the original pending
digest, replacement pending digest, retained-state digest, expected anchor,
and actual H7 state. It can only issue one CAS of that exact retained pair;
it cannot overwrite signed material, create a third proposal, or retry an
application effect. A missing attempt is created with the exact canonical
bytes; an existing attempt must match. No retry is automatic.

An expired/withdrawn recovery policy while the owner is fenced remains a
separate operator recovery requirement. These APIs do not invent a new root,
renew a policy from local files, delete uncertainty markers, or backdate time
to make an unavailable authorization current.

## Qualification boundaries

Component fixtures exercise real signatures, Unix framing, durable files,
external CAS conflicts, cold reopen, rollback refusal, and current-use checks.
They do not supply the following independent deployment qualifications:

1. Production release-root identity, independently administered custody, and
   operational threshold/key-rotation ceremonies.
2. Independent external frontier and trusted-clock retention across actual
   host, backup, restore, and disaster-recovery boundaries.
3. Reproducible build and supply-chain provenance validation for published
   agentd/matrixd artifacts and platform packages.
4. Full deployed supervisor/installer lifecycle qualification for each
   supported operating system and process driver.
5. Account, transaction, task, evaluator, and Cell current-authorization
   coverage outside these Fleet/H7 consumers.
6. Actual production listener authentication, replay protection, and required
   private-task confidentiality, including WAN deployment.
7. Quantum PoN work-cost, difficulty, and fork-choice security assumptions and
   their independent research/operational validation.
