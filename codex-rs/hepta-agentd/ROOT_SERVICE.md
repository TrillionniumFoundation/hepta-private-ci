# Original protected authority service and Agentd assembly

This stage imports the original service closure recorded in
`ROOT_SERVICE_SOURCE.json`. It preserves the original FinalUse issuer, original
consumer frontiers and protected CognitiveStore host APIs for one Agentd owner.
Trusted startup assembly and ordinary FinalUse Current publication are separate
following stages; importing these APIs alone does not activate a production host.
It does not import previous acceptance reports or manufacture production policy.
The service's fresh initializer explicitly reports `production_ready: false`.

## Trust and deployment inputs

The trusted launcher supplies all seven original production inputs: the live
writer authorization, issuer trust keys, revocations, protected clock/currentness,
consumer frontier state, authenticated original SQLite Current cut, and the live
exact-target grant provider. JSON from a renderer, Session or ordinary runtime
cannot establish the provenance of any of them.

`authority_host_config` requires root-owned 0600 single-link regular configuration
and a root-owned 0700 protected directory. The configured bind source, mount,
device and inode must agree. The public handoff contains no private signing key.
It includes the exact root and consumer process incarnations, separately held
pidfds, public issuer key, lease/proof, fixed lane paths, original checkpoint and
consumer heads. A path or PID lookup by the untrusted consumer is not a pidfd
handoff and cannot replace it.

`hepta-authority-host initialize --state PATH --bootstrap PATH` creates a fresh
registered owner once. It does not reset existing state or repair a stale cut.
`register-writer --config PATH` binds the original signed writer authorization.
`serve-session --config PATH --registration PATH --owner-pidfd-stdin` retains the
actual consumer lifetime and serves the registered purpose-limited session.
Only the trusted launcher may provide these administrative inputs. Runtime peers
cannot select a signer, owner, checkpoint directory, or registration.

## Five original lanes

The observation lane provides the protected boot-time projection and current
revocation/authority heads. The issuer lane signs original typed FinalUse and
AuthBus Objective requests. These are different authority classes; permission to
use one does not imply permission to use the other. There is no arbitrary-byte
signing endpoint. The checkpoint lane implements only read-head, begin-writes,
prepare-publication, commit-publication and fence-publisher. The device and Notes
frontier lanes persist the original consumers' exact compare-and-set frontiers.
The five lanes share the registered root and consumer incarnations; replacement
at the same pathname cannot reconnect an expired capability.

The cached verifier measures feed freshness from before the observation I/O.
An expired feed, lease, pidfd or epoch permanently fences the session. Clock and
live-verifier callbacks do no blocking channel I/O. Original consumer persistence
and typed issuance use their own bounded lanes and cannot bypass final entry.

The v2 observation publisher reloads the original protected clock record and
samples time after that read. It reuses the same durable projection only when
its exact projectable remainder covers the fixed 500ms request-start freshness
lifetime. A shorter window causes one original durable renewal; the post-I/O
sample must still have 500ms remaining or the response is refused without a
retry. The integer-ms ceiling's sub-ms phase is accounted for conservatively.
This avoids renewing the protected clock on every poll while preserving the
one-second durable ceiling, 10ms sample-span bound, original lease/proof and
complete revocation checks. The existing current-time API and forced-refresh
API keep their original behavior. Runtime peers cannot choose this horizon.

Validate this path in `codex-hepta-contracts` and `codex-hepta-agentd` using
`just test`, including exact remainder boundaries and a slow renewal that burns
its remaining horizon. Controlled unit stores do not establish Root filesystem
or native performance. Preserve the separate root-only slow-I/O qualifications;
if privileges are unavailable, report them as unrun. A new static artifact must
also pass the original one-vCPU native profile and unchanged authority gates.

## Whole-owner SQLite and Objective sender

`AgentdProductionWriterHost::open_with_protected_recovery` verifies the root's
Current receipt against the exact original owner, spawn, lease and authority
before recovering the authenticated cut. It binds the checkpoint while the
original CognitiveStore is exclusively owned, before exposing the writer or
read-side clones. The underlying `codex-state` SQLite commit hook and physically
READONLY observer pool are required parts of this integration, not optional
transport wrappers. A lost publication acknowledgement leaves the original
owner fenced; it must not locally re-hash its database and call that Current.

The same protected checkpoint is reused by the original Objective sender's
schema 17 retention. Its one-use send ticket is not recreated on recovery. The
Root typed Objective signer can supply the original envelope, while original
Objective admission/history remain in Agentd. FinalUse effects and Objective
admission retain distinct receipts and completion semantics.

Ordinary error paths await SQLx pool closure before releasing the original open
and writer guards. Initialization and shutdown must be awaited to completion;
this does not claim arbitrary external future cancellation is safe. Existing
Notes/Desktop private settlement checks, round-robin target reconciliation, and
Unknown-without-replay behavior remain in force.

## Development and verification

Build the owning library, `codex-hepta-agentd` and `hepta-authority-host` binaries
with the locked dependency graph. Run `just test -p codex-hepta-agentd --lib` and
the checkpoint/Objective tests in `codex-hepta-memory`; run applicable
`codex-state` tests when changing the commit-hook seam. Apply scoped `just fix`
and `just fmt` after tests. Changes to binary declarations require the usual
Bazel lock review and explicit Bazel target integration.

The ignored Root service qualification uses a new private bind-mounted state
area, real root service ownership, and a dedicated unprivileged UID 60001 client.
Enable its writer proof, checkpoint and consumer lanes together; retain actual
process logs and source/binary fingerprints. Same-UID unit fixtures and historical
qualification receipts are not evidence of a newly deployed production policy.
Never point qualification at an existing authority directory or widen an existing
secrets/no-effect policy to make it pass.

Asterinas must separately qualify the same std/Tokio/SQLite owner and native HOS2
execution. Linux-host Root or X11 results do not establish native kernel
integration, native pidfd/BOOTTIME correctness, or survival of kernel reboot.

## Recorded stage validation

The owning Agentd library run exercised 301 tests: 298 passed and three session
fixtures were rejected because their temporary directories lacked the original
0700 requirement. After explicitly setting 0700 in those fixtures, the three
affected tests passed. Production directory checks were unchanged. Both original
binaries and the original peer qualification example built with the locked graph;
the Bazel lock refresh had no drift and the new Root binary target resolved.

The separately executed ignored service test passed with all five lanes enabled
in a private mount namespace and a fresh root-owned bind-mounted directory. Its
actual UID 60001 client verified writer observation, exact checkpoint CAS/refusal,
both independent original FinalUse consumers, nonce replay refusal, and typed
FinalUse/Objective issuance. This is explicitly no-effect qualification with
`production_ready: false`; its checkpoint probe did not mutate the production
writer. The qualification state was removed after the run. The retained logs are
`root-service-owning-tests-01`, `root-service-session-tests-02`, and
`root-service-actual-root-01` under the task's external evidence directory.
