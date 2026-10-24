# Protected original-owner production composition

## Authenticated descriptor launch path

`attach_root_production_operation_host` is the composition entry for the explicit
original production launcher. It consumes `AgentdRootProductionInputs` from
`receive_root_production_inputs`: the actual sealed Root handoff, pre-held Root
pidfd, original live session, already activated Device/Notes consumers, protected
Current/checkpoint transport and original grant provider. It does not call the
legacy factory's `from_stream`, reopen either consumer or fall back to an
unprotected local current cut.

The launcher supplies its actual primary target, optional inherited Session
Notes bootstrap datagram, and reconciliation interval. The primary may be the
real original Android runtime target; an absent device is not replaced with a
no-op or fabricated HOS2 consumer. This combined profile is distinct from a
future Notes-only primary composition.

The factory performs `open_with_protected_recovery` once, using the exact original
writer lease/generation and live verifier. The whole-owner checkpoint is bound
before that writer is constructed. It configures Notes as an additional target,
then uses the same existing atomic configuration installation and final live
authority check. Failure leaves the handles unpublished and preserves the
actual protected durable state for authorized recovery.

Its `AgentdRootProductionAttachment` returns four existing capabilities:

- `root_session`: keep the original feed alive until the runtime stops.
- `checkpoint`: reuse this exact checkpoint for `original_objective_sender`;
  do not open another writer or construct a local echo checkpoint.
- `grants`: a clone of the same original provider, also exposing its existing
  typed Objective signing method to the trusted compiler; no second socket or
  signing authority is created.
- `notes`: the read-only `AgentdNotesDocumentObserver` of the actual inherited
  Notes target. Its target is the returned application identity, and its private
  recovery lane supplies the actual predecessor revision immediately before
  compilation. A serialized target identity cannot substitute for that read.

`with_notes_from_session_with_observer` now preserves this observer in the
runtime handoff path. The older identity-only method delegates to it and retains
its existing API. The direct-host and runtime handoff test both use original
SQLite ownership and actual SCM_RIGHTS/socketpair transport, assert the same
writer remains installed, read the exact original document state and emit no
effect or issuer request. Their issuer/application inputs remain explicit
fixtures; they do not qualify a production Root deployment.

The Root launcher must separately register the actual Session Reserved target's
Notes grant route with the **same retained Root issuer/lease registry** before
effects. Activating the Notes FinalUse frontier is not that registration. The
Session offer/ACK remains bounded and startup-only. Desktop ordinary product
startup and a configured chat socket cannot manufacture this descriptor custody.

This constructor does not supply the finite literal Notes UI compiler or a
production implementation of Desktop's `ObjectiveHostAuthority`. Those must
actually consume the returned observer, original writer/sender/checkpoint and
typed Root signer, then enter the original Objective run/dispatch/terminal path.
Native text/App Server chat is a separate route and does not implicitly perform
that Notes action. The final composition execution record must cover the actual
caller, not merely these callable APIs.

## Finite Notes preparation on that same writer

The unique launcher can call `AgentdConfig::with_root_notes_literal_adapter`
after attaching the Root inputs and selecting the original Objective profile
file. It returns the configured `AgentdConfig` and a non-cloneable
`AgentdNotesLiteralAdapter` to retain alongside ordinary `run`. The profile must
equal the shared `hepta-objective` literal Notes profile in full. Deployment
supplies its principal scope, issuer, policy generation, locale and five actual
runtime/artifact digests explicitly. This code supplies no guessed digest,
default model, authentication, protected Current or signing key.

`prepare(client_intent_id, text)` accepts only those two untrusted values. It
derives a bounded run ID from the original owner, principal and navigation ID;
an existing original sender record is returned for read/reconciliation without
observation, signing or another send permit. A new request reads the actual
private Notes predecessor, refuses a pending application receipt, uses the
original 4096-text/8192-payload validator and retains the exact original operation
before typed Root signing. Protected time comes from that same live Root session,
and the source has a five-second deadline. No destination, predecessor, subject,
generation, scope, digest or signing body comes from the renderer.

Signing and observer I/O run in one bounded blocking slot; started work keeps
the slot across cancellation. Expiry is rechecked before signing, after signing
and after the original sender acknowledges its durable fence. A timeout does
not erase preparation, roll back a checkpoint, resign a retained request or
create a second ledger. `Ready` contains the original sender/ticket and exact
signed ingress already retained by that owner. Its trusted caller must still
consume `mark_send_started`, use authenticated original control ingress and
retain the actual transport observation. This API does not directly dispatch,
issue a FinalUse grant or claim that a document was changed.

Original-owner tests verify pending-receipt and escaped-payload refusal before
preparation, exact UTF-8/predecessor retention, duplicate operation identity
protection and zero grant/device calls. The separate shared compiler tests run
the real Objective decoder/admission/compiler with explicitly synthetic source
authentication. Run `just test --locked --offline -p codex-hepta-agentd --lib
-E 'test(notes_literal)'` and the corresponding `codex-hepta-objective` test.
Actual UI submission, original Root terminal, lost-reply recovery and final
receipt retirement remain execution gates until the unique launcher calls this
adapter through its complete original transport path.

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

[The static V2 execution record](acceptance/2026-10-23-static-authority-v2/README.md)
preserves the original default release build/shape success, failed Linux/data
attempts, separate SSD reference success and actual native500ms failure. It
does not qualify an installed production authority or recovered writer.

The subsequent [native clock-window V2 qualification](acceptance/2026-10-23-native-clock-window/README.md)
passed the same original bounds on frozen5a2+d5a (feed19ms). Checkpoint still
had no ACK; that preflight is separate from the freshcounter1/five-lane writer
composition and does not qualify production effects or recovery.
