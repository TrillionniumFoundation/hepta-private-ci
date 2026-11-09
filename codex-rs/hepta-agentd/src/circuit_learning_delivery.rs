//! Concrete handoff to the original learning runtime. The outbox carries no
//! learning authority: current source/frontier/signature checks remain there.

use codex_hepta_automation::AutomationStore;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationOwnersV1;
use codex_hepta_learning_artifacts::LearningIterationRequestV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;

use crate::LearningIterationHandleV1;
use crate::LearningIterationRuntimeErrorV1 as Error;

enum DeliveryMode {
    FirstAttempt,
    Readback,
}

/// No backend leaves the intent pending. A prior durable claim, including one
/// whose process crashed before submit, permits only the original readback.
pub async fn deliver_circuit_learning_v1(
    store: &AutomationStore,
    backend: Option<&LearningIterationHandleV1>,
    request: LearningIterationRequestV1,
    owners: LearningIterationOwnersV1,
) -> Result<LearningIterationSnapshotV1, Error> {
    delivery(store, backend, request, owners, DeliveryMode::FirstAttempt).await
}

/// Use after any uncertain delivery or ACK. Never claims or submits new work.
pub async fn reconcile_circuit_learning_v1(
    store: &AutomationStore,
    backend: Option<&LearningIterationHandleV1>,
    request: LearningIterationRequestV1,
    owners: LearningIterationOwnersV1,
) -> Result<LearningIterationSnapshotV1, Error> {
    delivery(store, backend, request, owners, DeliveryMode::Readback).await
}

async fn delivery(
    store: &AutomationStore,
    backend: Option<&LearningIterationHandleV1>,
    request: LearningIterationRequestV1,
    owners: LearningIterationOwnersV1,
    mode: DeliveryMode,
) -> Result<LearningIterationSnapshotV1, Error> {
    let backend = backend.ok_or(Error::OwnerUnavailable("learning backend is not installed"))?;
    let row = store
        .circuit_learning_delivery(request.source_run_id.as_str())
        .await
        .map_err(|_| Error::CommitUncertain)?
        .ok_or(Error::OwnerUnavailable(
            "completion intent is not available",
        ))?;
    let intent = &row.intent;
    if request.agent_id.as_str() != store.owner_agent_id().as_str()
        || request.operation_id.as_str() != intent.operation_id
        || request.completed_task_receipt.to_string() != intent.completed_task_receipt.as_str()
        || request.envelope.objective_digest.to_string() != intent.objective_digest.as_str()
    {
        return Err(Error::WrongScope);
    }
    let initial = LearningIterationCoordinatorV1::new(request.clone(), owners.clone())?;
    let request_digest = Sha256Digest::parse(initial.snapshot().head_digest.to_string())
        .map_err(|_| Error::WrongScope)?;
    let submit = if matches!(mode, DeliveryMode::Readback) {
        if row.request_digest.as_ref() != Some(&request_digest) {
            return Err(Error::CommitUncertain);
        }
        false
    } else {
        store
            .claim_circuit_learning(intent, &request_digest)
            .await
            .map_err(|_| Error::CommitUncertain)?
    };
    let snapshot = if submit {
        backend.submit(request.clone()).await?
    } else {
        backend.readback(request.clone()).await?
    };
    if snapshot.request != request || snapshot.owners != owners {
        return Err(Error::WrongScope);
    }
    let completed = LearningIterationCoordinatorV1::from_snapshot(snapshot)?;
    // NoUpdate without a committed, distinct next task is still incomplete.
    if completed.next_stage().is_some() {
        return Err(Error::CommitUncertain);
    }
    let head = Sha256Digest::parse(completed.snapshot().head_digest.to_string())
        .map_err(|_| Error::WrongScope)?;
    store
        .acknowledge_circuit_learning(intent, &request_digest, &head)
        .await
        .map_err(|_| Error::CommitUncertain)?;
    Ok(completed.snapshot().clone())
}
