//! Original Version custody. Public construction consumes actual capabilities;
//! it neither opens a writer nor accepts an uploaded future learning cut.
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_learning_artifacts::ArtifactSelectionVerifierV1;
use codex_hepta_learning_artifacts::LearningArtifactOwnerService;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::SignedArtifactSelectionV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use tokio::runtime::Handle;
use tokio::sync::Notify;
use tokio::sync::Semaphore;

use super::super::OriginalCircuitRetainedPublicationInputsV1;
use super::super::PreparedOriginalCircuitRetainedPublicationV1;
use super::Error;
use super::OriginalCircuitRetainedTaskInputsV1;
use super::RetainedVersionOriginV1;
use super::c_task::RetainedVersionInstalledTaskV1;
use super::context::OriginalVersionCut;
use crate::AgentdConfig;
use crate::AgentdIdentity;
use crate::CircuitTaskSourceReadbackV1;
use crate::NeuronGenerationCurrentOwnerV1;
use crate::OriginalCellQ24DatasetCommandReadbackV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::OriginalCellQ24TrainingCommandClientV1;
use crate::OriginalCellQ24TrainingCommandConnectionV1;
use crate::OriginalCircuitLearningReadOwnerV1;
use crate::PublishedCircuitCellOwnerV1;

#[path = "circuit_retained_version_artifact.rs"]
mod artifact;
#[path = "circuit_retained_version_effect.rs"]
mod effect;
#[path = "circuit_retained_version_service.rs"]
mod service;
#[path = "circuit_retained_version_state.rs"]
mod state;

type RetainedVersionPreparedV1 =
    PreparedOriginalCircuitRetainedPublicationV1<FileAnchorWitnessStore, FileAnchorWitnessStore>;
type RetainedVersionInputsV1 =
    OriginalCircuitRetainedPublicationInputsV1<FileAnchorWitnessStore, FileAnchorWitnessStore>;

/// Expected identity of an already started original artifact transaction.
/// This metadata can only narrow actual owner readback; it grants nothing.
pub struct OriginalCircuitRetainedArtifactCheckpointV1 {
    pub operation_id: StableId,
    pub intent_digest: Digest32,
}

/// Recovery consumes actual already-held C owners. It does not call a Source
/// recovery factory that could acknowledge a durable suffix, and has no fresh
/// files, creation flag, prepared writer or FinalUse effect entry.
pub struct OriginalCircuitRetainedVersionRecoveryV1 {
    pub training: LearningIterationSnapshotV1,
    pub attestations: Vec<SignedLearningEvidenceV1>,
    pub intent_digest: Digest32,
    pub cell: PublishedCircuitCellOwnerV1<FileAnchorWitnessStore>,
    pub source: Arc<CircuitTaskSourceReadbackV1<FileAnchorWitnessStore>>,
    pub identity: AgentdIdentity,
    pub current: Arc<NeuronGenerationCurrentOwnerV1>,
    pub artifacts: Arc<Mutex<LearningArtifactOwnerService>>,
    pub artifact_checkpoint: OriginalCircuitRetainedArtifactCheckpointV1,
    pub artifact_selection: SignedArtifactSelectionV1,
    pub artifact_verifier: ArtifactSelectionVerifierV1,
}

struct RetainedVersionColdCutV1 {
    training: LearningIterationSnapshotV1,
    attestations: Vec<SignedLearningEvidenceV1>,
}
struct RetainedVersionArtifactOwnerV1 {
    owner: Arc<Mutex<LearningArtifactOwnerService>>,
    checkpoint: OriginalCircuitRetainedArtifactCheckpointV1,
    selection: SignedArtifactSelectionV1,
    verifier: ArtifactSelectionVerifierV1,
    withdrawal_scope: Digest32,
    withdrawal_head: Digest32,
}
enum RetainedVersionHostPhaseV1 {
    Awaiting {
        inputs: Box<RetainedVersionInputsV1>,
        task: OriginalCircuitRetainedTaskInputsV1,
    },
    Prepared {
        original: Box<RetainedVersionPreparedV1>,
        task: OriginalCircuitRetainedTaskInputsV1,
    },
    Installed {
        original: RetainedVersionInstalledTaskV1,
        config: Option<AgentdConfig>,
    },
    Recovered(RetainedVersionInstalledTaskV1),
}
struct RetainedVersionHostStateV1 {
    dataset: OriginalCellQ24DatasetCommandReadbackV1,
    initial_trainer: Option<OriginalCellQ24TrainingCommandConnectionV1>,
    trainer: Option<OriginalCellQ24TrainingCommandClientV1>,
    cut: Option<OriginalVersionCut>,
    expected: Option<RetainedVersionColdCutV1>,
    control: Arc<NeuronGenerationCurrentOwnerV1>,
    artifacts: RetainedVersionArtifactOwnerV1,
    // Taking the sole phase before an effect leaves None on failure/cancellation.
    // No code fills a None phase from a checkpoint or a new connection.
    phase: Option<RetainedVersionHostPhaseV1>,
    selection_reader: Option<
        Arc<OriginalCircuitLearningReadOwnerV1<FileAnchorWitnessStore, FileAnchorWitnessStore>>,
    >,
}
pub struct OriginalCircuitRetainedVersionHostV1 {
    material: OriginalCellQ24MaterialReceiptConfigV1,
    initial_binding: Digest32,
    origin: RetainedVersionOriginV1,
    state: Mutex<RetainedVersionHostStateV1>,
    preparation_requested: AtomicBool,
    publication_requested: AtomicBool,
    runtime_started: AtomicBool,
    end: Instant,
    runtime: Handle,
    connections: Arc<Semaphore>,
    installed: Notify,
}
impl OriginalCircuitRetainedVersionHostV1 {
    /// Original host setup, before D/T exist. This keeps the same supplied
    /// descriptor deadlines and the three independent publication authorities.
    pub fn from_original_owners(
        material: OriginalCellQ24MaterialReceiptConfigV1,
        dataset: OriginalCellQ24DatasetCommandReadbackV1,
        trainer: OriginalCellQ24TrainingCommandConnectionV1,
        inputs: RetainedVersionInputsV1,
        task: OriginalCircuitRetainedTaskInputsV1,
        artifact_checkpoint: OriginalCircuitRetainedArtifactCheckpointV1,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        let started = super::now()?;
        let (initial_binding, at) =
            OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(&material)?;
        super::require_clock(started, at)?;
        OriginalCellQ24DatasetCommandReadbackV1::require_initial_context(&dataset, &material)?;
        task.require_completed_a(&inputs.completed)?;
        let artifacts = RetainedVersionArtifactOwnerV1::new(
            Arc::clone(&inputs.authorities.artifacts),
            artifact_checkpoint,
            inputs.selection.signed.clone(),
            inputs.selection.verifier.clone(),
        )?;
        let control = Arc::clone(&inputs.current);
        let phase = RetainedVersionHostPhaseV1::Awaiting {
            inputs: Box::new(inputs),
            task,
        };
        Self::new(
            material,
            initial_binding,
            RetainedVersionOriginV1::Fresh,
            RetainedVersionHostStateV1 {
                dataset,
                initial_trainer: Some(trainer),
                trainer: None,
                cut: None,
                expected: None,
                control,
                artifacts,
                phase: Some(phase),
                selection_reader: None,
            },
            lifetime,
        )
    }

    /// Cold expected bytes are accepted only by this permanent read-only
    /// constructor, then compared with actual D/T before any response.
    pub fn recover_from_original_owners(
        material: OriginalCellQ24MaterialReceiptConfigV1,
        dataset: OriginalCellQ24DatasetCommandReadbackV1,
        trainer: OriginalCellQ24TrainingCommandConnectionV1,
        original: OriginalCircuitRetainedVersionRecoveryV1,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        let (initial_binding, _) =
            OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(&material)?;
        OriginalCellQ24DatasetCommandReadbackV1::require_initial_context(&dataset, &material)?;
        if original.intent_digest.is_zero()
            || original.training.receipts.len() != 3
            || original.attestations.len() != 3
        {
            return Err(Error::Binding("original retained recovery cut"));
        }
        let artifacts = RetainedVersionArtifactOwnerV1::new(
            original.artifacts,
            original.artifact_checkpoint,
            original.artifact_selection,
            original.artifact_verifier,
        )?;
        let phase = RetainedVersionHostPhaseV1::Recovered(RetainedVersionInstalledTaskV1 {
            cell: original.cell,
            source: original.source,
            identity: original.identity,
            intent: original.intent_digest,
        });
        Self::new(
            material,
            initial_binding,
            RetainedVersionOriginV1::Recovered,
            RetainedVersionHostStateV1 {
                dataset,
                initial_trainer: Some(trainer),
                trainer: None,
                cut: None,
                expected: Some(RetainedVersionColdCutV1 {
                    training: original.training,
                    attestations: original.attestations,
                }),
                control: original.current,
                artifacts,
                phase: Some(phase),
                selection_reader: None,
            },
            lifetime,
        )
    }

    fn new(
        material: OriginalCellQ24MaterialReceiptConfigV1,
        initial_binding: Digest32,
        origin: RetainedVersionOriginV1,
        state: RetainedVersionHostStateV1,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        if lifetime.is_zero() || lifetime > Duration::from_secs(300) {
            return Err(Error::Binding("original Version lifetime"));
        }
        let end = Instant::now().checked_add(lifetime).ok_or(Error::Clock)?;
        Ok(Self {
            material,
            initial_binding,
            origin,
            state: Mutex::new(state),
            preparation_requested: AtomicBool::new(origin == RetainedVersionOriginV1::Recovered),
            publication_requested: AtomicBool::new(origin == RetainedVersionOriginV1::Recovered),
            runtime_started: AtomicBool::new(origin == RetainedVersionOriginV1::Recovered),
            end,
            runtime: Handle::try_current().map_err(|_| Error::Unavailable)?,
            connections: Arc::new(Semaphore::new(4)),
            installed: Notify::new(),
        })
    }

    fn require_lifetime(&self) -> Result<(), Error> {
        if Instant::now() >= self.end {
            return Err(Error::Unavailable);
        }
        Ok(())
    }
}
