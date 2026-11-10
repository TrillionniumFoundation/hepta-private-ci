//! Concrete handoff to the original learning runtime. The outbox carries no
//! learning authority: current source/frontier/signature checks remain there.

use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::CircuitLearningDeliveryV1;
use codex_hepta_automation::CircuitLearningIntentV1;
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

/// Finish only local slot retirement after a previously committed exact ACK.
/// This returns no learning snapshot and cannot submit, restore, attest or
/// accept an iteration. The original durable ACK remains the cleanup witness.
pub(crate) async fn retire_acknowledged_delivery(
    store: &AutomationStore,
    request: &LearningIterationRequestV1,
    owners: &LearningIterationOwnersV1,
    row: &CircuitLearningDeliveryV1,
) -> Result<(), Error> {
    let request_digest = request_digest(store, request, owners, &row.intent)?;
    if row.request_digest.as_ref() != Some(&request_digest) {
        return Err(Error::WrongScope);
    }
    let head = row.acknowledged_head.as_ref().ok_or(Error::CommitUncertain)?;
    // The original owner re-reads and compares intent, request and ACK inside
    // its transaction. A stale caller observation never authorizes cleanup.
    store
        .retire_acknowledged_circuit_learning(&row.intent, &request_digest, head)
        .await
        .map_err(|_| Error::CommitUncertain)
}

fn request_digest(
    store: &AutomationStore,
    request: &LearningIterationRequestV1,
    owners: &LearningIterationOwnersV1,
    intent: &CircuitLearningIntentV1,
) -> Result<Sha256Digest, Error> {
    if request.agent_id.as_str() != store.owner_agent_id().as_str()
        || request.source_run_id.as_str() != intent.source_run_id
        || request.operation_id.as_str() != intent.operation_id
        || request.completed_task_receipt.to_string() != intent.completed_task_receipt.as_str()
        || request.envelope.objective_digest.to_string() != intent.objective_digest.as_str()
    {
        return Err(Error::WrongScope);
    }
    let initial = LearningIterationCoordinatorV1::new(request.clone(), owners.clone())?;
    Sha256Digest::parse(initial.snapshot().head_digest.to_string()).map_err(|_| Error::WrongScope)
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
    let request_digest = request_digest(store, &request, &owners, intent)?;
    // Refuse known queue/owner unavailability before recording a durable claim.
    // Loss after the claim remains uncertain and permits only original readback.
    let reservation = backend.reserve()?;
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
        reservation.submit(request.clone()).await?
    } else {
        reservation.readback(request.clone()).await?
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
    store
        .retire_acknowledged_circuit_learning(intent, &request_digest, &head)
        .await
        .map_err(|_| Error::CommitUncertain)?;
    Ok(completed.snapshot().clone())
}
