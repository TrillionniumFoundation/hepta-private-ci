# Protected original-owner production composition

## Scope and entry point

On Linux, the embedding host may call `attach_production_operation_host` with
`AgentdProductionHostInputs<C>` before starting Agentd. This assembles existing
owners and protocols; default environment/CLI startup does not activate it.
There is no signing key, compatibility clock, recovered-cut discovery, new
writer, replacement ledger, Notes receiver, or retrying issuer in this API.

The base is the bounded issuer provider in PR #3383, on the original Notes
recovery stack. `runtime.agentd.production_operation` must still be implemented
and deployed by the independent issuer service. A transport adapter cannot
establish that service's availability, authorization policy, or key custody.

## Explicit inputs and responsibility

The embedding host must supply all seven original authority inputs:

| Input | Original type / boundary | Host obligation |
| --- | --- | --- |
| Independent issuer endpoint | Connected `UnixStream`, `AgentdFinalUseIssuerPeer`, bounded timeout | Authenticate the descriptor and pin its peer independently; support the original operation and grant schema |
| Protected time | `Arc<dyn AuthorityClock>` | Supply protected current time; unavailability and lease expiry fail closed |
| External durable frontier | `Arc<dyn AuthorityFrontierStore<FinalUseFrontier>>` | Independently retain exact state and atomic CAS across rollback of local files |
| Pinned issuer keyring | `Vec<FinalUseIssuerTrustKey>` | Supply independently trusted public keys and epoch windows |
| Current revocation head | `FinalUseRevocations` | Authenticate current epoch, revision and revoked grants; establish freshness independently |
| Original writer authority | `ProductionAuthorityLease`, opaque verified token, `ProductionAuthorityVerifier`, exact lease/generation | Preserve the original grant, owner, scope, epoch and revocation checks |
| Independently retained current cut and publisher | `CognitiveRecoveryRequirement::ExactCurrentCut` or `Revoked`, mandatory `Arc<C: ObjectiveSenderCheckpoint>` and ACK deadline | Independently authenticate the initial current cut before recovery; authenticate and durably retain the changed live cut under the same original writer fence; a local digest or echo is not authority |

The primary `FinalUseProductionOutboxTarget` and reconciliation interval are
also explicit. Supplying a trait implementation is not proof that a clock,
frontier, issuer, or application is protected or production qualified.

`AgentdProductionNotesInputs` is optional. Its inherited `UnixDatagram` is the
original Session bootstrap channel. Its separate `AgentdFinalUseHostInputs`
must independently supply the Notes keyring, protected clock, frontier, and
revocation head; none are inferred from the target's offer or issuer response.
The original Session offer supplies the original application identity and both
effect/recovery descriptors. The composition does not create an identity.

## Order, persistent ownership and failure

1. Reject an already configured host before consulting injected target,
   clock, issuer, Notes handoff, verifier or checkpoint. Reject an invalid
   checkpoint deadline before any external input access, then reject
   revoked/wrong-owner cuts, generation mismatch, absent opaque token and invalid
   scalar inputs.
2. Wrap the original live verifier with the same protected clock used by the
   primary FinalUse owner. Check time before and after each original verifier
   invocation, including checks retained by recovery, the writer and runtime.
   Original SystemTime checks remain conservative additional restrictions.
3. Validate the independently pinned issuer peer and open the original
   keyring-aware FinalUse authority against the external frontier.
4. Open exactly one original writer with authenticated current-cut recovery.
   Validate the same recovered writer, lease and mutation capability.
5. When Notes inputs exist, open their original protected FinalUse authority
   and call the existing `with_notes_from_session` descriptor/ACK path. It
   adds the original Notes target to the same runtime and writer.
6. Call the same original writer's `checkpoint_current` with the mandatory
   checkpoint. Its lease acquisition changed the exact cut; the original
   independent recovery input is not a substitute for acknowledgement of this
   new cut. The callback runs under the original `BEGIN IMMEDIATE` full-cut
   transaction and must return the exact cut with the checked original fence.
   Create the restricted Objective sender from that same writer and checkpoint
   Arc before installation; this creates no request, event or transport.
7. After all awaits and metadata callbacks, synchronously recheck the retained
   live verifier, then assign both configuration handles without another
   fallible operation. Only success returns `AgentdProductionHostAttachment<C>`,
   containing `original_sender` and `notes_identity`. The latter is `Some` only
   for an installed original Notes target; the generic path returns `None` in
   that field.

Failure leaves both configuration handles unpublished. It does not delete or
roll back original durable recovery or FinalUse files. A retry requires fresh,
independently established current-cut and authority inputs; it cannot reuse a
suspect source or silently fall back to ordinary writable opening.

The original Notes `attached` ACK confirms explicit recovered-owner handoff
composition. It can precede a checkpoint, protected-clock or grant-verifier
refusal. This handoff does not write a CognitiveStore row, and the full-cut ACK
must not be described as a persisted Notes attachment receipt.
It is not proof that Agentd started, a grant was accepted, an effect occurred,
or a terminal receipt was committed. On final refusal the factory returns an
error, publishes neither handle, and drops the uninstalled target channels.
The original writer retains the wrapped verifier after installation, so later
mutations still reject protected-clock expiry/unavailability and live revocation.

The existing Notes receiver owns its two-second handoff deadline. The bounded
issuer provider owns its separate I/O deadline, excluding Tokio blocking-pool
queue wait. This composition does not claim an overall bootstrap deadline or
certify the latency of external verifier/frontier implementations.
The mandatory checkpoint deadline is positive and at most five seconds. It is
only a cooperative limit on the ACK future, excluding transaction acquisition,
bounded full-cut capture, synchronous future construction, live checks and
rollback. All synchronous callbacks and each future poll must be bounded and
nonblocking. Cancellation must not leave an obsolete background publication;
this API supplies no worker or replacement backend to enforce that external
contract. After the original write lock is released, later owner writes can
invalidate the acknowledged cut.

## API migration and remaining current-cut ownership

Every caller of the strict factory must now supply `checkpoint` and
`checkpoint_deadline`; there is no optional/default ACK and no successful legacy
factory overload. Consumers read the old optional identity from
`attachment.notes_identity` and use `attachment.original_sender` for the canonical
same-writer, same-publisher Objective path. The explicit
`AgentdConfig::original_objective_sender(checkpoint, deadline)` getter remains
for other trusted embeddings. Such callers can choose another provider; this
slice does not claim global enforcement outside the strict attachment path.

The current repository has no production implementation of
`ObjectiveSenderCheckpoint` or authenticated Cognitive current-cut latest-read
service. A real implementation must authenticate the original grant/fence,
prevent stale publishers and durably establish the exact current cut in its
independent rollback domain. The initial recovery cut still comes from that
independent authority, never from a fresh capture of the suspect database.

Bootstrap publication does not checkpoint every later owner mutation. Original
operation admission, dispatch claims, reconciliation and cognitive writes need
their own success-boundary integration. The new no-ticket entry point is
limited to a current **active** lease: after `release` or `rollback_lease` it
refuses without invoking the publisher. Terminal-cut/takeover publication needs
a separate original-authority design. Existing Notes terminal settlement writes
the original SQLite chain, while receipt retirement currently checks that local
terminal record and live authority without an independent full-cut ACK. This
application-discard boundary remains open; the bootstrap ACK does not close it.

## Verification and required gates

The new original Agentd tests cover issuer peer rejection, frontier/current-cut
refusal, initial and recovery-time expiry, unavailable protected time, original
verifier revocation, final metadata-callback expiry, unique writer ownership,
repeat assembly without input access, and live checks on later writer writes.
They also require an ACK of the post-acquisition cut, preserve zero publisher
calls on early refusal, reject invalid deadlines before input access and refuse
refused/held/mismatched ACKs or post-ACK authority faults without installing.
Notes tests use real socketpairs and SCM_RIGHTS: successful original offer/ACK,
missing descriptors, mismatched identity, unavailable ACK, independent frontier
refusal, and observed `attached` ACK followed by final live-authority refusal.
The latter requires both handles to remain absent and the effect stream to close
without an effect. These tests are compiled under the original Linux Agentd
package, with its actual Fleet, SQLite owner and original Notes receiver.
The added real-Notes test observes `attached`, then refuses, withholds or
mismatches the current-cut ACK and requires both handles to remain absent,
application stream EOF and zero issuer/effect bytes. The original sender bridge
consumes the returned attachment and verifies the same writer and provider.

Run `just test --locked -p codex-hepta-agentd -E 'test(production_composition::)'`
in a complete original workspace. Owning-package and reverse-consumer CI must
compile and execute this code. The isolated contracts/authority harness does
not compile the factory, SQLite owner, Tokio worker, or Notes handoff.

Local authority-only execution passed five tests with seven provider tests
filtered out, and passed Clippy with warnings denied. That harness uses the
original contracts Rust source but a different locked registry resolution
(32 entries differ from the original workspace). The original package attempt
was blocked before compilation by a partial workspace's missing
`codex-rs/aws-auth/Cargo.toml`; later complete-workspace reconstruction removed
that historical source-layout blocker. Agentd compilation later exhausted the
local resource budget before this owning package could execute. These historical
attempts are not factory test results; final-source tests and the required
owning-package CI must be recorded separately. The original memory package's
earlier 322 passing tests do not qualify this new checkpoint refactor.

Production qualification still requires the seven real external inputs,
independent issuer operation deployment, concrete parent-to-Session descriptor
custody, original-owner recovery/effect/receipt acceptance gates, and required CI.
This entry point does not sign AuthBus Objective requests. Its returned sender
reuses the original durable retain-before-send lifecycle; real authentication,
independent current-cut service and original transport remain injected host
responsibilities.
