# Evaluated NoUpdate and the incumbent's next task

This opt-in profile binds an already committed, signed native learning result
to the existing `OwnerDrainedSameModel` task boundary. The learning coordinator
stays terminal `NoUpdate`; the continuation is a separate Control operation.
It does not append a learning `NextUse` stage, select or adopt a candidate,
submit a zero-delta V5 update, or change no-op and positive-gain rules.

## Host contract

The admitted host supplies `AgentdLearningNoUpdateInputsV1`: the existing
learning owner ports, pinned verifier, exact request and owner identities,
independently retained expected learning head, and current host time. Restore
keeps its existing authenticated rollback, withdrawal and revocation duties.
An incoming checkpoint cannot choose these pins or its own trust root.

For this profile only, `completed_task_receipt` is the drained predecessor's
actual generation owner checkpoint, and `selected_artifact_digest` is the
content digest of the independently selected canonical V2 manifest payload.
These domains must be bound when the original learning request is admitted.
An unrelated digest in an older request cannot be silently relabeled.

The source agent, cell and run must match that predecessor. The bridge accepts
exactly Experience, Dataset, Training and Evaluation receipts ending in
evaluated `NoUpdate`. It checks the original chain, current signed evidence,
trainer/evaluator separation, host time, and a stable second owner restore.
Proposal-owner rejection and zero-eligible-data outcomes are outside this
profile; they need their own anchored evidence path.

Before moving the selected owner into preparation, retain its sealed
`AgentdGenerationSelectionObservationV1`. Call
`prepare_agentd_generation_evaluated_no_update_task_v1` with the actual guarded
predecessor, unchanged selected manifest and fresh next-task files. Its derived
operation identity binds the learning head, source checkpoint, selected payload
and observation, and target owner. The original
`agentd.cell-generation.next-task-same-model` FinalUse purpose still applies.
Only an independently issued grant may publish the original Control CAS.

Retain `prepared.recovery()` before publication. If the response is uncertain,
use `recover_agentd_generation_update_v1` with that exact operation and intent;
never infer nonexecution, issue a replacement nonce, or reset either journal.
The ordinary generation service executes the new input, retains its result,
and records actual delivery acknowledgement and drain.

Afterward, `observe_agentd_evaluated_no_update_next_use_v1` combines the retained
sealed selection, sealed publication, and terminal owner observation. It
requires a committed input and non-genesis checkpoint, reauthenticates the
NoUpdate result, and returns a serialize-only historical readback. Its
authority is `DENY_ALL`. It is neither a lease across owners nor permission
to dispatch after later revocation. Physical costs remain in the original
observation, including unknown costs.

## Engineering verification and limits

The targeted `evaluated_no_update` runtime test uses the existing learning
coordinator, owner fixtures and independent test keys. Its next-task worker
reads an actual frozen two-weight F32 file, checks the manifest's weight digest,
computes from the new input, and persists the result. It checks failed evidence,
publication ACK loss, real output ACK/drain, native cold recovery without a
second model execution, old-owner fencing and later FinalUse revocation.

Set `HEPTA_NO_UPDATE_EVIDENCE_DIR` in the test runner to retain original journal,
witness, Control, grant, learning signing-payload/signature and model-output
bytes alongside the sealed readbacks. The learning restore fixture is memory
backed; the exported debug snapshot is not a production decoder. The fixture
trainer and evaluator are deterministic. These results establish an engineering
path, not real-task quality, deployed production authority, cross-process
learning-owner recovery, power-loss safety, or five-family/retention completion.

## Authenticated history and current execution

The restored chain is checked against bootstrap-pinned trust before returning
any result. Terminal replay retains the existing expiry contract: exact NoUpdate
history stays readable after expiry and never starts a stage or writes a new
checkpoint. Its private audit rechecks signatures and actor separation within a
common historical validity window before the operation deadline. This proves
neither the actual admission time nor current permission; it returns no verified
authority. Production custody must separately authenticate actual admission.

Owner attestation reads always receive real current host time. Current owner
refusal, damaged signatures, future observations and mismatched trust/head pins
still fail without changing the retained history. Nonterminal recovery and the
next-task bridge require evidence valid at current time; historical readback
does not relax FinalUse, revocation, no-op or positive-gain rules. Proposal
receipts remain anchored proposal-owner results, with current-head, rollback,
withdrawal and revocation checks still mandatory host duties.

The Unix `restored_no_update_authenticates_across_processes` test exits one
producer before twelve fresh readers exercise these boundaries against bounded
disk fixtures. Reader ports count and refuse every stage/proposal/checkpoint
mutation and check the real owner clock. These are fixture keys, local head pins
and deterministic producer/evaluator behavior. Production learning-owner
enrollment, actual admission custody, power-loss and cross-boot recovery remain
unestablished; process restart evidence cannot substitute for them.
