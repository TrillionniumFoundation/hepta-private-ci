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
