# Original human text provenance

An original dynamic tool item proves which Core thread/turn/call produced it.
It does not itself prove authenticated human ingress. The Notes model profile
must also resolve the original turn's user input to its original admitted
AuthBus delivery and use Core `ReconcileOnly` to verify that delivery's exact
client ID and payload belong to that same turn. Direct `turn/start` has no such
retained authenticated delivery and cannot authorize Notes preparation.

The Root native UI lane adds `human_binding` to the original retained text
signature in the **same issuer CAS** as the original signature and counter.
It contains the trusted launcher's principal, human session, permission
revision, expiry and exact AppServer route. The existing private peer/pidfd
checks still authenticate the actual UI. Generic Agentd text signing writes
no human binding. Legacy records default to no binding; looking them up does
not change them, and signing again cannot upgrade them into human evidence.
No additional journal, lease, grant or operation ledger is introduced.

`AgentdUnixFinalUseGrantProvider::verify_original_human_text` is a bounded
read-only request on the already retained Root issuer channel. Root requires
the exact envelope/body/signature in its original record, the exact current
human registration and namespace, a live held UI pidfd, and the current writer
lease before and after the lookup. The response echoes the complete ingress
digest and projects the existing `TextOwnerReceipt`; it is metadata, not an
effect grant. Missing, expired, changed or unstamped records fail closed. This
entry does not re-sign text, renew authority, prepare an Objective or resend.

The trusted launcher installs that current registration once, before serving
the original lanes. No RPC supplies a human registration. Original Root,
human login, UI, Session, Agentd and model lifetimes still require real product
acceptance; local persistence/protocol fixtures do not establish those gates.

For the local physical-login product, the provider transfers its already-held
logind leader descriptor. `with_original_logind_session` independently queries
the Root-owned system bus through the checked loginctl inode, compares actual
UID/local/active/seat/type/leader and boot/start identity to the protected
profile, then retains that same descriptor and exact human binding. A changed
profile or current UI registration cannot reuse it. Every original Root lane
checks the retained login lifetime around each exchange; the human text proof
also requires this capture to exist. A profile string alone cannot qualify the
model Notes human gate. Legacy UI-only launch remains structurally compatible.

The protected Notes launch profile and sealed deployment select an explicit
`interaction`: `{"kind":"literal_ui_v1"}` for the original no-model UI, or
`{"kind":"original_thread_tool_v1","route":{...}}` for a previously created
and durably saved original thread. Absence retains the old literal selection.
Root and Agentd compare the model route to the actual registered daemon. Model
mode requires its inherited Session lifetime, installs no literal endpoint and
uses the original retained tool catalog on normal thread resume. The deployment
selection and catalog do not themselves supply human authorization.
