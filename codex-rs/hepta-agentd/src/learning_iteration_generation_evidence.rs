//! Authenticate existing Selection/NextUse receipts against the original actor.
//! This reader neither publishes a generation nor signs or executes work.

use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_neuron::CellBackendManifestV2;
use codex_hepta_neuron::CellGenerationIntentV2;

use crate::LearningIterationEvidenceClientV1;
use crate::LearningIterationRuntimeErrorV1;
use crate::NeuronGenerationLearningReadErrorV1;
use crate::NeuronGenerationRuntimeHandleV2;

/// Original publication profile and, for NextUse, the original committed intent.
/// The updated profile checks its complete predecessor manifest at the actor.
#[derive(Clone, Copy)]
pub enum GenerationLearningStageReadV1<'a> {
    RetainedSelection,
    RetainedNextUse { intent: &'a CellGenerationIntentV2 },
    UpdatedSelection { previous_manifest: &'a CellBackendManifestV2 },
    UpdatedNextUse {
        previous_manifest: &'a CellBackendManifestV2,
        intent: &'a CellGenerationIntentV2,
    },
}

/// Exact already-issued receipt and original connected owners. The receipt's
/// timestamp and evidence identity are never synthesized by this adapter.
pub struct GenerationLearningStageReadbackRequestV1<'a> {
    pub runtime: &'a NeuronGenerationRuntimeHandleV2,
    pub snapshot: &'a LearningIterationSnapshotV1,
    pub receipt: &'a LearningIterationReceiptV1,
    pub read: GenerationLearningStageReadV1<'a>,
    pub verifier: &'a LearningEvidenceVerifierV1,
}

/// A current authenticated read, not a checkpoint or a publication capability.
/// The ordinary worker must still verify actor separation and checkpoint it.
/// Exact owner equality and a current signature do not assemble daemon startup
/// or grant ongoing selection, publication or execution authority.
#[derive(Clone, Debug)]
pub struct AuthenticatedGenerationLearningStageV1 {
    receipt: LearningIterationReceiptV1,
    attestation: SignedLearningEvidenceV1,
    verified_at_unix_seconds: u64,
}

impl AuthenticatedGenerationLearningStageV1 {
    pub fn receipt(&self) -> &LearningIterationReceiptV1 { &self.receipt }
    pub fn attestation(&self) -> &SignedLearningEvidenceV1 { &self.attestation }
    pub fn verified_at_unix_seconds(&self) -> u64 { self.verified_at_unix_seconds }
}

#[derive(Debug, thiserror::Error)]
pub enum GenerationLearningStageReadbackErrorV1 {
    #[error("original generation observation: {0}")]
    Generation(#[from] NeuronGenerationLearningReadErrorV1),
    #[error("original learning evidence: {0}")]
    Evidence(#[from] LearningIterationRuntimeErrorV1),
}

/// Resolve the same original observation before and after its attestation read.
/// Unpublished actors, missing use, substituted receipts and changed CURRENT,
/// withdrawal or revocation remain errors. Neither read executes a model.
pub async fn read_generation_learning_stage_v1(
    request: GenerationLearningStageReadbackRequestV1<'_>,
    evidence: &LearningIterationEvidenceClientV1,
) -> Result<AuthenticatedGenerationLearningStageV1, GenerationLearningStageReadbackErrorV1> {
    let role = match request.read {
        GenerationLearningStageReadV1::RetainedSelection
        | GenerationLearningStageReadV1::UpdatedSelection { .. } => LearningEvidenceRoleV1::Selector,
        GenerationLearningStageReadV1::RetainedNextUse { .. }
        | GenerationLearningStageReadV1::UpdatedNextUse { .. } => LearningEvidenceRoleV1::Observer,
    };
    let prefix = receipt_predecessor(request.snapshot, request.receipt)?;
    if request.snapshot.owners.evidence_trust_digest != request.verifier.trust_digest()
        || request.snapshot.request.envelope.objective_digest != request.verifier.objective_digest()
    {
        return Err(LearningIterationRuntimeErrorV1::WrongScope.into());
    }
    let first = read_observation(&request, &prefix).await?;
    if first != request.receipt.observation {
        return Err(LearningIterationRuntimeErrorV1::WrongScope.into());
    }
    let attestation = evidence.readback(request.snapshot, request.receipt).await?;
    if read_observation(&request, &prefix).await? != first {
        return Err(LearningIterationRuntimeErrorV1::WrongScope.into());
    }
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| LearningIterationRuntimeErrorV1::OwnerUnavailable("generation evidence clock"))?
        .as_secs();
    let payload = learning_iteration_receipt_signing_bytes_v1(request.receipt)
        .map_err(LearningIterationRuntimeErrorV1::from)?;
    let verified = request.verifier.verify(role, &attestation, &payload, now)
        .map_err(LearningIterationRuntimeErrorV1::Evidence)?;
    if verified.principal().principal_id != request.receipt.actor_id
        || &request.receipt.actor_id != request.snapshot.owners.owner(request.receipt.observation.stage())
        || verified.trust_digest() != request.snapshot.owners.evidence_trust_digest
        || verified.objective_digest() != request.snapshot.request.envelope.objective_digest
        || request.receipt.observed_unix_seconds > now
    {
        return Err(LearningIterationRuntimeErrorV1::WrongScope.into());
    }
    Ok(AuthenticatedGenerationLearningStageV1 {
        receipt: request.receipt.clone(), attestation, verified_at_unix_seconds: now,
    })
}

/// Rebuild only the exact retained predecessor, including for completed history.
/// Structural replay uses historical times and never creates a durable record.
fn receipt_predecessor(
    snapshot: &LearningIterationSnapshotV1,
    receipt: &LearningIterationReceiptV1,
) -> Result<LearningIterationCoordinatorV1, LearningIterationRuntimeErrorV1> {
    let restored = LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?;
    let prefix = match snapshot.receipts.iter().position(|original| original == receipt) {
        Some(index) => {
            let mut prefix = LearningIterationCoordinatorV1::new(
                snapshot.request.clone(), snapshot.owners.clone(),
            )?;
            for original in snapshot.receipts.iter().take(index) {
                prefix.record(original.clone(), original.observed_unix_seconds)?;
            }
            prefix
        }
        None => restored,
    };
    if !matches!(receipt.observation.stage(), LearningIterationStageV1::Selection | LearningIterationStageV1::NextUse) {
        return Err(LearningIterationRuntimeErrorV1::WrongScope);
    }
    let mut checked = prefix.clone();
    checked.record(receipt.clone(), receipt.observed_unix_seconds)?;
    Ok(prefix)
}

async fn read_observation(
    request: &GenerationLearningStageReadbackRequestV1<'_>,
    prefix: &LearningIterationCoordinatorV1,
) -> Result<LearningIterationObservationV1, GenerationLearningStageReadbackErrorV1> {
    Ok(match request.read {
        GenerationLearningStageReadV1::RetainedSelection => {
            request.runtime.read_learning_selection(prefix).await?
        }
        GenerationLearningStageReadV1::RetainedNextUse { intent } => {
            request.runtime.read_learning_next_use(prefix, intent).await?
        }
        GenerationLearningStageReadV1::UpdatedSelection { previous_manifest } => {
            request.runtime.read_learning_updated_selection(prefix, previous_manifest).await?
        }
        GenerationLearningStageReadV1::UpdatedNextUse { previous_manifest, intent } => {
            request.runtime.read_learning_updated_next_use(prefix, previous_manifest, intent).await?
        }
    })
}
