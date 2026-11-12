//! Live original Dataset custody retained by the original Trainer host.
//! The batch and optimizer digests stay exactly as frozen by Root. This separate
//! capture binds the original data owners and both complete Observer signatures.
//! It is not a lease or signing grant. A remote profile retains one original
//! Material connection; it transfers no Source object, writer, path or key.

use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU8;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationError;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::DatasetFreezePlanV2;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_types::Digest32;
use tokio::runtime::Handle;

use crate::AgentdIdentity;
use crate::CellQ24DatasetErrorV1;
use crate::CellQ24DatasetReaderV1;
use crate::CellQ24DatasetRuleV1;
use crate::CellQ24SgdRuleV1;
use crate::CellQ24SingleHeadTrainingPlanV1;
use crate::CellQ24TrainingBatchV1;
use crate::CircuitTaskSourceReadbackV1;
use crate::LearningIterationEvidenceClientV1;
use crate::LoadedCellQ24ModelV1;
use crate::OriginalCellQ24DatasetV1;
use crate::OriginalCellQ24RemoteMaterialClientV1;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCellQ24TrainingSourceErrorV1 {
    #[error("original training source binding: {0}")]
    Binding(&'static str),
    #[error("original training source ledger is occupied or poisoned")]
    Busy,
    #[error("original Material evidence owner is unavailable")]
    OwnerUnavailable,
    #[error("original training source capture did not finish")]
    CaptureUncertain,
    #[error("original training Dataset: {0}")]
    Dataset(#[from] CellQ24DatasetErrorV1),
    #[error("original training source iteration: {0}")]
    Iteration(#[from] LearningIterationError),
    #[error("original Material evidence: {0}")]
    Evidence(#[from] SignedEvidenceError),
}

type Error = OriginalCellQ24TrainingSourceErrorV1;

#[path = "cell_q24_training_source_operation.rs"]
mod operation;
pub(crate) use operation::OriginalCellQ24TrainingSourceOperationV1;

/// These are exact retained bytes, not permission to issue replacement
/// attestations. The live original owners must return both same signatures.
#[derive(Clone)]
pub struct OriginalCellQ24TrainingSourceConfigV1 {
    pub dataset: LearningIterationSnapshotV1,
    pub scope: FrozenLearningScopeV2,
    pub rule: CellQ24DatasetRuleV1,
    pub optimizer: CellQ24SgdRuleV1,
    pub freeze_plan: DatasetFreezePlanV2,
    pub freeze_evidence: SignedLearningEvidenceV1,
    pub experience_evidence: SignedLearningEvidenceV1,
    pub dataset_evidence: SignedLearningEvidenceV1,
    pub verifier: LearningEvidenceVerifierV1,
}

/// Transfer actual readback capabilities and share exclusive access to the
/// original ledger, never a reopened writer. Its mutex is released before every
/// evidence RPC. This type does not transport Source or Ledger across UIDs;
/// original host handoff is still required for a separate Trainer process.
pub struct OriginalCellQ24TrainingSourceOwnersV1<SW: AnchorWitnessStore> {
    pub source: CircuitTaskSourceReadbackV1<SW>,
    pub identity: AgentdIdentity,
    pub ledger: Arc<Mutex<LedgerWriter>>,
    pub baseline: Arc<LoadedCellQ24ModelV1>,
    pub experience: LearningIterationEvidenceClientV1,
    pub dataset: LearningIterationEvidenceClientV1,
}

/// Transfer an already pinned original Material channel, the exact local
/// baseline, and both original receipt-owner channels. No received DTO or
/// caller-selected batch can be converted into a Source capability.
pub struct OriginalCellQ24RemoteTrainingSourceOwnersV1 {
    pub material: OriginalCellQ24RemoteMaterialClientV1,
    pub baseline: Arc<LoadedCellQ24ModelV1>,
    pub experience: LearningIterationEvidenceClientV1,
    pub dataset: LearningIterationEvidenceClientV1,
}

trait OriginalMaterialReadback: Send + Sync {
    fn read(
        &self,
        config: &OriginalCellQ24TrainingSourceConfigV1,
    ) -> Result<OriginalCellQ24DatasetV1, Error>;
}

struct SourceOwners<SW: AnchorWitnessStore> {
    source: CircuitTaskSourceReadbackV1<SW>,
    identity: AgentdIdentity,
    ledger: Arc<Mutex<LedgerWriter>>,
    baseline: Arc<LoadedCellQ24ModelV1>,
}

impl<SW: AnchorWitnessStore + Send> OriginalMaterialReadback for SourceOwners<SW> {
    fn read(
        &self,
        config: &OriginalCellQ24TrainingSourceConfigV1,
    ) -> Result<OriginalCellQ24DatasetV1, Error> {
        read_original_material(self, config)
    }
}

fn read_original_material(
    original: &SourceOwners<impl AnchorWitnessStore>,
    config: &OriginalCellQ24TrainingSourceConfigV1,
) -> Result<OriginalCellQ24DatasetV1, Error> {
    let initial = LearningIterationCoordinatorV1::new(
        config.dataset.request.clone(),
        config.dataset.owners.clone(),
    )?;
    let mut ledger = original.ledger.try_lock().map_err(|_| Error::Busy)?;
    let mut reader = CellQ24DatasetReaderV1::new(&original.source, &original.identity, &mut ledger);
    // current_material has already read both original completed signatures.
    // This read-only recovery path does not authorize new work after expiry.
    Ok(reader.read_current_for_original_receipt(
        initial.snapshot(),
        &original.baseline,
        config.rule,
        config.freeze_plan.clone(),
        &config.freeze_evidence,
    )?)
}

enum OriginalMaterialSource {
    Local(Box<dyn OriginalMaterialReadback>),
    Remote(OriginalCellQ24RemoteMaterialClientV1),
}

impl OriginalMaterialSource {
    async fn read_current_material(
        &self,
        config: &OriginalCellQ24TrainingSourceConfigV1,
        baseline: &Arc<LoadedCellQ24ModelV1>,
    ) -> Result<OriginalCellQ24DatasetV1, Error> {
        match self {
            Self::Local(original) => original.read(config),
            Self::Remote(original) => {
                OriginalCellQ24RemoteMaterialClientV1::require_source_binding(
                    original, config, baseline,
                )
                .map_err(|_| Error::Binding("same original remote Material capture"))?;
                OriginalCellQ24RemoteMaterialClientV1::read_current(original)
                    .await
                    .map_err(|_| Error::OwnerUnavailable)
            }
        }
    }
}

struct LiveOwners {
    original: OriginalMaterialSource,
    experience: LearningIterationEvidenceClientV1,
    dataset: LearningIterationEvidenceClientV1,
    baseline: Arc<LoadedCellQ24ModelV1>,
}

/// A sealed live capability; no raw-batch, boolean, digest-only, callback or
/// signer constructor exists. Only captured native-owner factories consume it.
/// Keeping this value does not freeze other owners or guarantee future reads.
pub struct OriginalCellQ24TrainingSourceV1 {
    live: LiveOwners,
    config: Arc<OriginalCellQ24TrainingSourceConfigV1>,
    material: OriginalCellQ24DatasetV1,
    binding: Digest32,
    runtime: Handle,
    operation_state: AtomicU8,
}

/// Read actual data and original completed Material owners in a blocking lane.
/// Dropping the future does not cancel already running reads. No journal is
/// created and no Training claim or signature is produced by this capture.
pub async fn capture_original_cell_q24_training_source_v1(
    owners: OriginalCellQ24TrainingSourceOwnersV1<impl AnchorWitnessStore + Send + 'static>,
    config: OriginalCellQ24TrainingSourceConfigV1,
) -> Result<OriginalCellQ24TrainingSourceV1, Error> {
    let live = LiveOwners {
        baseline: Arc::clone(&owners.baseline),
        original: OriginalMaterialSource::Local(Box::new(SourceOwners {
            source: owners.source,
            identity: owners.identity,
            ledger: owners.ledger,
            baseline: owners.baseline,
        })),
        experience: owners.experience,
        dataset: owners.dataset,
    };
    capture_live_original_source(live, config).await
}

/// Capture through the same original remote Material owner. Its private
/// decoder verifies the complete Dataset provenance and already frozen rule.
/// The receipt-owner channels are still read before and after both fresh reads.
pub async fn capture_original_remote_cell_q24_training_source_v1(
    owners: OriginalCellQ24RemoteTrainingSourceOwnersV1,
    config: OriginalCellQ24TrainingSourceConfigV1,
) -> Result<OriginalCellQ24TrainingSourceV1, Error> {
    OriginalCellQ24RemoteMaterialClientV1::require_source_binding(
        &owners.material,
        &config,
        &owners.baseline,
    )
    .map_err(|_| Error::Binding("same original remote Material capture"))?;
    let live = LiveOwners {
        original: OriginalMaterialSource::Remote(owners.material),
        baseline: owners.baseline,
        experience: owners.experience,
        dataset: owners.dataset,
    };
    capture_live_original_source(live, config).await
}

async fn capture_live_original_source(
    live: LiveOwners,
    config: OriginalCellQ24TrainingSourceConfigV1,
) -> Result<OriginalCellQ24TrainingSourceV1, Error> {
    let runtime = Handle::current();
    tokio::task::spawn_blocking(move || {
        let material = runtime.block_on(live.current_material(&config))?;
        // Validate the existing Root-frozen rule; never derive a new scope
        // from the subsequently issued Experience/Dataset signatures.
        let _ = material.training_plan(
            config.dataset.clone(),
            config.scope.clone(),
            Arc::clone(&live.baseline),
            config.optimizer,
        )?;
        let binding = capture_binding(&config, &material);
        Ok(OriginalCellQ24TrainingSourceV1 {
            live,
            config: Arc::new(config),
            material,
            binding,
            runtime,
            operation_state: AtomicU8::new(0),
        })
    })
    .await
    .map_err(|_| Error::CaptureUncertain)?
}

impl OriginalCellQ24TrainingSourceV1 {
    pub(crate) fn native_inputs(
        &self,
    ) -> Result<
        (
            CellQ24SingleHeadTrainingPlanV1,
            CellQ24TrainingBatchV1,
            CellQ24SgdRuleV1,
        ),
        Error,
    > {
        let plan = self.material.training_plan(
            self.config.dataset.clone(),
            self.config.scope.clone(),
            Arc::clone(&self.live.baseline),
            self.config.optimizer,
        )?;
        Ok((plan, self.material.batch().clone(), self.config.optimizer))
    }

    pub(crate) fn source_capture_binding(&self) -> Digest32 {
        self.binding
    }

    /// Only the original Stage's bounded spawn_blocking lane calls this.
    /// Never call it on an executor thread. No original writer is unlocked,
    /// reopened, cloned or held across an evidence-client await.
    pub(crate) fn require_current_in_lane(&self) -> Result<(), Error> {
        if self.source_operation_fenced() {
            return Err(Error::CaptureUncertain);
        }
        let material = self
            .runtime
            .block_on(self.live.current_material(&self.config))?;
        require_same_material(&self.material, &material)?;
        if capture_binding(&self.config, &material) != self.binding {
            return Err(Error::Binding("same original capture identity"));
        }
        Ok(())
    }
}

impl LiveOwners {
    async fn current_material(
        &self,
        config: &OriginalCellQ24TrainingSourceConfigV1,
    ) -> Result<OriginalCellQ24DatasetV1, Error> {
        let started_at = now()?;
        verify_original_evidence(config, started_at)?;
        self.read_original_evidence(config).await?;
        let before = self
            .original
            .read_current_material(config, &self.baseline)
            .await?;
        require_observations(config, &before)?;
        self.read_original_evidence(config).await?;
        let after = self
            .original
            .read_current_material(config, &self.baseline)
            .await?;
        require_same_material(&before, &after)?;
        let fresh_now = now()?;
        if fresh_now < started_at {
            return Err(Error::Binding("source capture clock moved backwards"));
        }
        verify_original_evidence(config, fresh_now)?;
        Ok(after)
    }

    async fn read_original_evidence(
        &self,
        config: &OriginalCellQ24TrainingSourceConfigV1,
    ) -> Result<(), Error> {
        let experience = &config.dataset.receipts[0];
        let dataset = &config.dataset.receipts[1];
        let original_experience = LearningIterationEvidenceClientV1::readback(
            &self.experience,
            &config.dataset,
            experience,
        )
        .await
        .map_err(|_| Error::OwnerUnavailable)?;
        if original_experience != config.experience_evidence {
            return Err(Error::Binding("complete original Material signatures"));
        }
        let original_dataset =
            LearningIterationEvidenceClientV1::readback(&self.dataset, &config.dataset, dataset)
                .await
                .map_err(|_| Error::OwnerUnavailable)?;
        if original_dataset != config.dataset_evidence {
            return Err(Error::Binding("complete original Material signatures"));
        }
        Ok(())
    }
}

fn verify_original_evidence(
    config: &OriginalCellQ24TrainingSourceConfigV1,
    at: u64,
) -> Result<(), Error> {
    let coordinator = LearningIterationCoordinatorV1::from_snapshot(config.dataset.clone())?;
    config.scope.validate_snapshot(&config.dataset)?;
    if coordinator.next_stage() != Some(LearningIterationStageV1::Training)
        || config.dataset.receipts.len() != 2
        || config.dataset.owners.evidence_trust_digest != config.verifier.trust_digest()
        || config.dataset.request.envelope.objective_digest != config.verifier.objective_digest()
    {
        return Err(Error::Binding("exact signed Dataset cut and frozen scope"));
    }
    for (receipt, evidence) in config
        .dataset
        .receipts
        .iter()
        .zip([&config.experience_evidence, &config.dataset_evidence])
    {
        let payload = learning_iteration_receipt_signing_bytes_v1(receipt)?;
        let verified =
            config
                .verifier
                .verify(LearningEvidenceRoleV1::Observer, evidence, &payload, at)?;
        if verified.principal().principal_id != receipt.actor_id
            || receipt.observed_unix_seconds != evidence.issued_at
            || receipt.observed_unix_seconds > at
        {
            return Err(Error::Binding(
                "original Material actor and signature window",
            ));
        }
    }
    Ok(())
}

fn require_observations(
    config: &OriginalCellQ24TrainingSourceConfigV1,
    material: &OriginalCellQ24DatasetV1,
) -> Result<(), Error> {
    if config.dataset.receipts[0].observation != material.experience_observation()
        || config.dataset.receipts[1].observation != material.dataset_observation()
        || config.dataset.receipts[0].evidence_digest != material.provenance_digest()
        || config.dataset.receipts[1].evidence_digest != material.provenance_digest()
    {
        return Err(Error::Binding(
            "original Material observations and live data",
        ));
    }
    Ok(())
}

fn require_same_material(
    before: &OriginalCellQ24DatasetV1,
    after: &OriginalCellQ24DatasetV1,
) -> Result<(), Error> {
    if before.provenance_digest() != after.provenance_digest()
        || before.receipt() != after.receipt()
        || before.experience_observation() != after.experience_observation()
        || before.dataset_observation() != after.dataset_observation()
        || before.batch().encoded() != after.batch().encoded()
        || before.batch().digest() != after.batch().digest()
    {
        return Err(Error::Binding(
            "original material changed during source capture",
        ));
    }
    Ok(())
}

fn capture_binding(
    config: &OriginalCellQ24TrainingSourceConfigV1,
    material: &OriginalCellQ24DatasetV1,
) -> Digest32 {
    let mut experience = config.experience_evidence.signing_bytes();
    experience.extend_from_slice(&config.experience_evidence.signature);
    let mut dataset = config.dataset_evidence.signing_bytes();
    dataset.extend_from_slice(&config.dataset_evidence.signature);
    Digest32::of_parts(&[
        b"hepta.cell.q24.original-training-source.v1\0",
        config.dataset.head_digest.as_array(),
        config.scope.binding().as_array(),
        material.provenance_digest().as_array(),
        Digest32::of_bytes(&experience).as_array(),
        Digest32::of_bytes(&dataset).as_array(),
    ])
}

fn now() -> Result<u64, Error> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|value| value.as_secs())
        .map_err(|_| Error::Binding("source capture clock before Unix epoch"))
}
