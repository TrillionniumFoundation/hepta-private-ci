# runtime.codex interface audit, 2026-10-02

## Exact candidates and completion boundary

This review distinguishes three source compositions. Their implementation and
execution receipts are not interchangeable:

* [Runtime PR #1244](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1244),
  `975e3ab2bbabd7ecb67440a88317e7eb59b9017e`, remains a construction/materialization
  candidate. Its own review policy requires ordinary source, removal of source
  writers, and new exact-head/current-main merge evidence before acceptance.
* [Inference PR #1304](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1304),
  `ef2d2d14e36fb694f9fc7bbdf58c177010f9832a`, is ordinary V2 source, stacked on
  `0a8c7eea57fdafe36bf72eb59fb4916880a8e278`. This audit's retained-journal repair
  starts from that source; it does not merge the runtime construction programs.
* [Integration PR #1303](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1303),
  observed at `6000e4068ce9c3c215346cd81686a37932fa53a1`, contains an ordinary-source
  runtime durable-owner/effect-permit composition. It does not contain #1304's
  `native_control_v2_*`, `control_actor.rs`, or `control_port.rs` implementation.

Documentation completeness, implemented source, a linked product caller, executed
qualification, independent acceptance, activation and release remain separate.
No combined runtime/inference completion or production qualification is established.

## Actual owner map

* App Server under `codex-rs/app-server` owns thread/turn execution and observations.
  `hepta-codex-adapter` owns contract translation/correlation, not a second executor.
* Agentd's `lane_b_runtime` owns the Agent run lifecycle and generation-bound
  context handoff. The ordinary integration candidate additionally persists that
  owner before publishing mutations and exchanges exact dispatch/abort bindings.
* `hepta-infer-worker-host::AppServerModelDriver` is the named effect caller.
  Its inference reservation/history belongs to `DurableInferenceControl`; V2
  exposes that single writer through `NativeControlPort` and one writer actor.
* Final-use grants remain independently issued. A local request or inferred
  success cannot substitute for the grant, durable preparation or terminal evidence.

The final repair must retain one inference writer, one Agent lifecycle owner and
one App Server transport writer. Copying either candidate over the other would
discard implemented protections.

## Confirmed source and CI blockers

The construction source has a concrete incompatible interface: its
`native_execution.rs` calls `run_mark_dispatched_exact` and consumes
`dispatch_digest`, while its Agentd client/protocol expose
`run_mark_dispatched_bound` and `dispatch_binding_digest`, including an abort
commitment. Renaming symbols alone would omit the semantic binding review.

The [runtime qualification run](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/36689697359)
has successful intermediate Actions step badges because the helper records command
results for a final gate. Its exact-head artifact records failed Lane-B truth and
format checks, and exit 101 for all Rust test/lint commands because `--locked`
rejects Cargo.lock drift. These are not successful compile, crash or product-E2E
receipts. The receipt-helper command passed; both final qualification gates failed.

The [alternate materializer run](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/36689689785)
failed in setup-rusty-v8 with `ModuleNotFoundError: tomllib`; its source-writing
step did not run. Fixing this Python setup is not evidence of delivered ordinary
source or a reason to execute the migration programs over another candidate.

## Remaining final-send boundary

At #1304, `native_run_control.rs::run_bound` binds the signed execution plan, but
`native_app_server.rs::run_once` creates a new `adapted_at_ms + config.timeout`
deadline after preparatory awaits. The signed plan and original operation budget
are not carried to that deadline. The final-use token is entered before the
App Server client's bounded command queue and socket readiness waits.

This is a source-confirmed enforcement gap; an expired physical-send reproduction
and a complete product-path fix have not yet been delivered by this audit stage.
The proposed additive transport API must execute in the existing command owner:

1. Serialize and await socket readiness with cancellation, abandonment and the
   original monotonic deadline selected concurrently.
2. Obtain fresh owner health/ingress observations after queue/readiness waits.
3. Recheck the immutable absolute ceiling, cancellation and final-use token,
   then call `start_send` with no intervening await.
4. Treat flush/response errors after `start_send` as potentially dispatched.

A private, request-bound `NotDispatched` proof may release the pre-effect token
only when the command owner proves it did not enter `start_send`. Timeout or
caller-future drop alone is not this proof. Admission is not packet completion.
An async generation observation is not atomic cross-process fencing: a live
owner-issued permit or server ingress fence still needs separate composition.

## Executable observation is a different owner boundary

`runtime_executable.rs` is unlinked in the runtime, inference and prompt candidates
examined here. In integration `6000e406`, `lib.rs` links it and the actual caller is
`runtime.rs -> AutomationService::open -> module_selection::observe_compiled_selection`.
The `SupervisorSelected` profile verifies the current executable plus canonical
manifest for `automation.taskflow` against the Supervisor's selected binding.
This is a real optional TaskFlow startup consumer, not proof that all runtime or
inference modules use executable registration. Linking orphan tests merely to
meet a minimum-test count would not supply that owner composition.

## Minimal staged convergence

1. Complete the independent V2 retained-history repair described in the
   [inference audit](../inference.control/RETENTION_AUDIT_20261002.md).
2. Implement and qualify the additive guarded transport seam and immutable signed
   deadline on ordinary source, preserving unguarded legacy-call semantics.
3. Review a typed Agentd bridge for admitted absolute deadline, exact generation,
   dispatch binding, abort commitment/opening and durable outbox reconciliation.
   Port the ordinary implementation, not source-writing programs.
4. Route bridge transitions through the existing V2 actor without adding another
   reservation store. Test lost dispatch/abort acknowledgements and process loss.
5. Freeze one ordinary-source candidate, refresh owner source maps and obtain
   exact-head plus deterministic current-main merge receipts with zero-test,
   skipped-command and command-exit checks enforced. Keep external gates false.
