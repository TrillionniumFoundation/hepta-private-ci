# Protected original-owner production composition

## Scope and entry point

On Linux, the embedding host may call `attach_production_operation_host` with
`AgentdProductionHostInputs` before starting Agentd. This assembles existing
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
| Independently retained current cut | `CognitiveRecoveryRequirement::ExactCurrentCut` or `Revoked` | Establish that the anchor is authenticated and current before calling; a local digest is not authority |

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
   clock, issuer, Notes handoff, or verifier. Reject revoked/wrong-owner cuts,
   generation mismatch, absent opaque token and invalid scalar inputs.
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
6. After all awaits and metadata callbacks, synchronously recheck the retained
   live verifier, then assign both configuration handles without another
   fallible operation. Only success returns `Some(original Notes identity)`;
   the generic path returns `None`.

Failure leaves both configuration handles unpublished. It does not delete or
roll back original durable recovery or FinalUse files. A retry requires fresh,
independently established current-cut and authority inputs; it cannot reuse a
suspect source or silently fall back to ordinary writable opening.

The original Notes `attached` ACK confirms explicit recovered-owner handoff
composition. It can precede a final protected-clock or grant-verifier refusal.
It is not proof that Agentd started, a grant was accepted, an effect occurred,
or a terminal receipt was committed. On final refusal the factory returns an
error, publishes neither handle, and drops the uninstalled target channels.
The original writer retains the wrapped verifier after installation, so later
mutations still reject protected-clock expiry/unavailability and live revocation.

The existing Notes receiver owns its two-second handoff deadline. The bounded
issuer provider owns its separate I/O deadline, excluding Tokio blocking-pool
queue wait. This composition does not claim an overall bootstrap deadline or
certify the latency of external verifier/frontier implementations.

## Verification and required gates

The new original Agentd tests cover issuer peer rejection, frontier/current-cut
refusal, initial and recovery-time expiry, unavailable protected time, original
verifier revocation, final metadata-callback expiry, unique writer ownership,
repeat assembly without input access, and live checks on later writer writes.
Notes tests use real socketpairs and SCM_RIGHTS: successful original offer/ACK,
missing descriptors, mismatched identity, unavailable ACK, independent frontier
refusal, and observed `attached` ACK followed by final live-authority refusal.
The latter requires both handles to remain absent and the effect stream to close
without an effect. These tests are compiled under the original Linux Agentd
package, with its actual Fleet, SQLite owner and original Notes receiver.

Run `just test --locked -p codex-hepta-agentd -E 'test(production_composition::)'`
in a complete original workspace. Owning-package and reverse-consumer CI must
compile and execute this code. The isolated contracts/authority harness does
not compile the factory, SQLite owner, Tokio worker, or Notes handoff.

Local authority-only execution passed five tests with seven provider tests
filtered out, and passed Clippy with warnings denied. That harness uses the
original contracts Rust source but a different locked registry resolution
(32 entries differ from the original workspace). The original package attempt
was blocked before compilation by the partial workspace's missing
`codex-rs/aws-auth/Cargo.toml`; it is not a factory test result.

Production qualification still requires the seven real external inputs,
independent issuer operation deployment, concrete parent-to-Session descriptor
custody, original-owner recovery/effect/receipt acceptance gates, and required CI.
This entry point neither signs AuthBus Objective requests nor supplies their
sender-side durable retain-before-send lifecycle.

The [protected original FinalUse consumer frontier adapter](HOST_FINAL_USE_FRONTIERS.md) preserves the two fixed original owners. Its Root/data qualification does not imply service wire or recovered-writer qualification.

[Original fleet and restart durability qualification](acceptance/2026-10-23-fleet-durability/README.md) records bounded independent fixture work and canonical restart no-op synchronization; four case successes do not qualify the complete aggregate.

[Original writer succession](HOST_COLD_WRITER_HANDOFF.md) keeps actual Fleet
process binding separate from one-step local lease generation and supplies a
whole-owner Current acknowledgement without a ticket. Its 54-test component
scope uses explicit Root fixtures; real Root service/native recovery remains a
separate requirement.
