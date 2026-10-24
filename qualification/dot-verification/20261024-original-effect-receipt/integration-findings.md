# Existing durable effect owner integration assessment

Exact source: 103bb2011629d12c658b7004d3a4a163a548df02. Read-only assessment before tests/edits.

## Reuse, do not replace

Agentd runtime.rs installs AgentdAutomationEffectHost only from explicit host configuration. state_control.rs AutomationExecuteEffect checks original readiness and calls host.execute. The host validates intent, refreshes revocations and first reads the original terminal receipt, then derives the current TaskFlow fence and invokes AutomationStore::execute_authorized_taskflow_effect. The immutable SQLite attempt is inserted before provider dispatch, observation is appended before step/run projection, and replay either settles original evidence or returns RecoveryRequired. These are deliberately separated durable boundaries, not one all-or-nothing transaction across a remote effect. Existing integration tests cover task panic after contact, close/reopen and no redispatch with a controlled driver.

## Native adapter gaps

1. runner.rs operation_key binds run/turn/generation/admission/round/call/name/arguments. The existing provider key uses provider_scope/run_id/step_id. The original owner must retain the immutable mapping to its admitted AuthorizedEffectIntent, exact payload, SignedFinalUseGrant and command. The intent itself is not a signed type. A new generation must not manufacture a new provider operation or fresh grant to replay an old effect.
2. TaskFlowStepReceipt carries receipt digest and terminal status, not original tool output bytes. Returning a digest string as Completed(String) would misrepresent the tool observation. The owning result store must retain/retrieve exact output bound to that receipt.
3. Host execute/reconcile has no provider cancellation ACK endpoint matching EffectOwner::cancel. A request/cancellation flag or local stream stop cannot become StopObservation::Stopped. Uncertain attempts must stay unresolved until real owner evidence is available.
4. Native TurnOwner/InferenceOwner/EffectOwner remain controlled-test implementations. New Responses bridge accepts a previously admitted stream and delegates retention; it is not a durable dispatch owner.

## Smallest useful current acceptance

Run the unchanged authorized_effect integration target on the exact source and repository Rust 1.96.0, then extend the existing fixture to test its actual terminal readback API over close/reopen, full receipt equality and wrong intent/command rejection. No second ledger, live provider, socket, forged cancellation ACK or production admission is introduced. Passing this does not close the three adapter contracts above.

Initial execution incorrectly retained the prior task RUSTUP_TOOLCHAIN=1.95.0 override. The exact repository configuration already says1.96.0. Offline missing-package and subsequent MSRV failure logs are retained as operator/environment setup failures, not product regressions. Official rustup fixed version1.96.0 installed without changing repository lock or toolchain configuration.
