# Literal Notes Objective adapter

This opt-in adapter executes one named `notes.replace` action through the
existing Objective, Run and production operation owners. It interprets text as
literal document content and performs no model turn, shell command or network
operation. Default Agentd startup does not enable it.

The trusted host registers `AgentdNotesObjectiveConfig { profile_digest,
target }` with `AgentdConfig::with_notes_objective`. The digest must identify the
frozen literal Notes admission profile; the target must be the actual Notes
application identity returned by the original Session handoff. A dedicated
Notes profile cannot also select the general seven-owner invocation runner.

Before signing Objective ingress, the trusted compiler must prepare the exact
original `OperationIntentV1` and payload with the installed writer. Its
`operation_id` equals the stable Objective `run_id`. The source provenance
digest equals that operation's semantic digest, binding payload, subject,
policy generation, destination incarnation, scope and expected predecessor.
The operation subject is the original writer's Agent ID; the authenticated
human or workspace principal remains in the separate Objective principal scope.

Before durable Objective publication, the adapter reads that operation from
the original event/outbox owner, reruns the original Notes payload validator,
and checks the Run ID, source digest, frozen profile and target. It refuses a
missing or different operation. A successful publication is then projected
through the sole Run coordinator. Its context binds the original operation;
its compilation identity comes from the original Objective compiler.

Only the coordinator's first dispatch transition may call the existing grant
provider and final-use dispatcher. The original operation's durable effect
fence remains authoritative. Repeated Objective requests, status queries and
reconciliation never grant another effect entry. An unknown result remains
indeterminate and uses the original observer-only reconciliation path. Run
success follows the original committed Notes outcome, including exact
application readback; it is not inferred from admission or a successful send.

The bounded runtime monitor revisits up to sixteen original publications per
cycle. It does not invent new runs for stale generations. Original operation
recovery can observe an unresolved effect across writer handoff; projection of
historical runs across Agentd generation changes remains governed by the
existing Run owner. This adapter does not change that owner's schema or claim
that Notes' in-memory document survives application restart or power loss.

`notes_objective_tests.rs` runs original signed admission, profile compilation,
durable publication, Run transitions, production operation dispatch, application
receipt validation and lost-ACK reconciliation together. Its key, grant issuer
and application channel are explicitly synthetic test fixtures. Real deployment
qualification must additionally bind the genuine authority services, independent
current-cut checkpoint, real Session/Notes process and exact source pair.
