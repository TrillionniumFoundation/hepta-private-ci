//! Original Version custody. Public construction consumes actual capabilities;
//! it neither opens a writer nor accepts an uploaded future learning cut.
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU8;
use std::sync::atomic::Ordering;
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
use super::RetainedVersionPurposeV1;
use crate::OriginalCellEvaluationCommandConnectionV1;
use crate::OriginalCellEvaluationCommandClientV1;
use super::Error;
use super::OriginalCircuitRetainedTaskInputsV1;
use super::RetainedVersionOriginV1;
use super::c_task::RetainedVersionInstalledTaskV1;
use super::context::OriginalVersionCut;
use crate::AgentdConfig;
use crate::AgentdIdentity;
use crate::AgentdUnixFinalUseGrantProvider;
use crate::CircuitTaskSourceReadbackV1;
use crate::NeuronGenerationCurrentOwnerV1;
use crate::OriginalCellQ24DatasetCommandReadbackV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::OriginalCellQ24TrainingCommandClientV1;
use crate::OriginalCellQ24TrainingCommandConnectionV1;
use crate::OriginalCircuitLearningReadOwnerV1;
use crate::OriginalRootRetainedVersionIssuerV1;
use crate::PublishedCircuitCellOwnerV1;

#[path = "circuit_retained_version_artifact.rs"]
mod artifact;
#[path = "circuit_retained_version_effect.rs"]
mod effect;
#[path = "circuit_retained_version_issuer.rs"]
mod issuer;
#[path = "circuit_retained_version_service.rs"]
mod service;
#[path = "circuit_retained_version_state.rs"]
mod state;

#[path = "circuit_retained_version_prepared.rs"]
mod prepared_custody;
use prepared_custody::RetainedVersionPreparedV1;

enum InitialVersionEvidence {
    TrainingNoUpdate,
    EvaluatedNoUpdate(OriginalCellEvaluationCommandConnectionV1),
}
impl InitialVersionEvidence {
    fn purpose(&self) -> RetainedVersionPurposeV1 {
        match self {
            Self::TrainingNoUpdate => RetainedVersionPurposeV1::TrainingNoUpdate,
            Self::EvaluatedNoUpdate(_) => RetainedVersionPurposeV1::EvaluatedNoUpdate,
        }
    }
    fn into_evaluator(self) -> Option<OriginalCellEvaluationCommandConnectionV1> {
        match self {
            Self::TrainingNoUpdate => None,
            Self::EvaluatedNoUpdate(evaluator) => Some(evaluator),
        }
    }
}
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
#[derive(Clone, Copy, Eq, PartialEq)]
#[repr(u8)]
enum RetainedVersionFinalUseOutcomeV1 {
    Awaiting = 0,
    Requested = 1,
    Denied = 2,
    Uncertain = 3,
    Published = 4,
}
struct RetainedVersionHostStateV1 {
    dataset: OriginalCellQ24DatasetCommandReadbackV1,
    initial_trainer: Option<OriginalCellQ24TrainingCommandConnectionV1>,
    trainer: Option<OriginalCellQ24TrainingCommandClientV1>,
    initial_evaluator: Option<OriginalCellEvaluationCommandConnectionV1>,
    evaluator: Option<OriginalCellEvaluationCommandClientV1>,
    cut: Option<OriginalVersionCut>,
    expected: Option<RetainedVersionColdCutV1>,
    control: Arc<NeuronGenerationCurrentOwnerV1>,
    artifacts: RetainedVersionArtifactOwnerV1,
    final_use_issuer: Option<OriginalRootRetainedVersionIssuerV1>,
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
    purpose: RetainedVersionPurposeV1,
    state: Mutex<RetainedVersionHostStateV1>,
    preparation_requested: AtomicBool,
    publication_requested: AtomicBool,
    issuer_worker_started: AtomicBool,
    final_use_outcome: AtomicU8,
    runtime_started: AtomicBool,
    end: Instant,
    runtime: Handle,
    connections: Arc<Semaphore>,
    installed: Notify,
    prepared: Notify,
}
impl OriginalCircuitRetainedVersionHostV1 {
    /// Original host setup, before D/T exist. This keeps the same supplied
    /// descriptor deadlines and the three independent publication authorities.
    /// The issuer must already be bound by `from_root_stream`; a legacy
    /// unprotected provider cannot be promoted into this purpose.
    pub fn from_original_owners(
        material: OriginalCellQ24MaterialReceiptConfigV1,
        dataset: OriginalCellQ24DatasetCommandReadbackV1,
        trainer: OriginalCellQ24TrainingCommandConnectionV1,
        inputs: RetainedVersionInputsV1,
        task: OriginalCircuitRetainedTaskInputsV1,
        artifact_checkpoint: OriginalCircuitRetainedArtifactCheckpointV1,
        final_use_issuer: AgentdUnixFinalUseGrantProvider,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        Self::from_original_profile(material, dataset, trainer, InitialVersionEvidence::TrainingNoUpdate,
            inputs, task, artifact_checkpoint, final_use_issuer, lifetime)
    }

    /// The separate evaluated purpose requires an original E connection held
    /// before the future T/B cut. The Version host only reads that E owner.
    pub fn from_original_evaluated_owners(
        material: OriginalCellQ24MaterialReceiptConfigV1,
        dataset: OriginalCellQ24DatasetCommandReadbackV1,
        trainer: OriginalCellQ24TrainingCommandConnectionV1,
        evaluator: OriginalCellEvaluationCommandConnectionV1,
        inputs: RetainedVersionInputsV1,
        task: OriginalCircuitRetainedTaskInputsV1,
        artifact_checkpoint: OriginalCircuitRetainedArtifactCheckpointV1,
        final_use_issuer: AgentdUnixFinalUseGrantProvider,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        Self::from_original_profile(material, dataset, trainer,
            InitialVersionEvidence::EvaluatedNoUpdate(evaluator), inputs, task,
            artifact_checkpoint, final_use_issuer, lifetime)
    }

    fn from_original_profile(
        material: OriginalCellQ24MaterialReceiptConfigV1,
        dataset: OriginalCellQ24DatasetCommandReadbackV1,
        trainer: OriginalCellQ24TrainingCommandConnectionV1,
        evidence: InitialVersionEvidence,
        inputs: RetainedVersionInputsV1,
        task: OriginalCircuitRetainedTaskInputsV1,
        artifact_checkpoint: OriginalCircuitRetainedArtifactCheckpointV1,
        final_use_issuer: AgentdUnixFinalUseGrantProvider,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        let purpose = evidence.purpose();
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
        let final_use_issuer =
            AgentdUnixFinalUseGrantProvider::into_original_retained_version_issuer(
                final_use_issuer,
            )?;
        let phase = RetainedVersionHostPhaseV1::Awaiting {
            inputs: Box::new(inputs),
            task,
        };
        Self::new(
            material,
            initial_binding,
            RetainedVersionOriginV1::Fresh,
            purpose,
            RetainedVersionHostStateV1 {
                dataset,
                initial_trainer: Some(trainer),
                trainer: None,
                initial_evaluator: evidence.into_evaluator(),
                evaluator: None,
                cut: None,
                expected: None,
                control,
                artifacts,
                phase: Some(phase),
                selection_reader: None,
                final_use_issuer: Some(final_use_issuer),
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
        Self::recover_original_profile(material, dataset, trainer,
            InitialVersionEvidence::TrainingNoUpdate, original, lifetime)
    }

    /// Read-only cold recovery of a complete four-cut evaluated NoUpdate.
    /// The original E connection and already-held C owners remain mandatory.
    pub fn recover_from_original_evaluated_owners(
        material: OriginalCellQ24MaterialReceiptConfigV1,
        dataset: OriginalCellQ24DatasetCommandReadbackV1,
        trainer: OriginalCellQ24TrainingCommandConnectionV1,
        evaluator: OriginalCellEvaluationCommandConnectionV1,
        original: OriginalCircuitRetainedVersionRecoveryV1,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        Self::recover_original_profile(material, dataset, trainer,
            InitialVersionEvidence::EvaluatedNoUpdate(evaluator), original, lifetime)
    }

    fn recover_original_profile(
        material: OriginalCellQ24MaterialReceiptConfigV1,
        dataset: OriginalCellQ24DatasetCommandReadbackV1,
        trainer: OriginalCellQ24TrainingCommandConnectionV1,
        evidence: InitialVersionEvidence,
        original: OriginalCircuitRetainedVersionRecoveryV1,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        let purpose = evidence.purpose();
        let count = match purpose {
            RetainedVersionPurposeV1::TrainingNoUpdate => 3,
            RetainedVersionPurposeV1::EvaluatedNoUpdate => 4,
        };
        let (initial_binding, _) =
            OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(&material)?;
        OriginalCellQ24DatasetCommandReadbackV1::require_initial_context(&dataset, &material)?;
        if original.intent_digest.is_zero()
            || original.training.receipts.len() != count
            || original.attestations.len() != count
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
            purpose,
            RetainedVersionHostStateV1 {
                dataset,
                initial_trainer: Some(trainer),
                trainer: None,
                initial_evaluator: evidence.into_evaluator(),
                evaluator: None,
                cut: None,
                expected: Some(RetainedVersionColdCutV1 {
                    training: original.training,
                    attestations: original.attestations,
                }),
                control: original.current,
                artifacts,
                phase: Some(phase),
                selection_reader: None,
                final_use_issuer: None,
            },
            lifetime,
        )
    }

    fn new(
        material: OriginalCellQ24MaterialReceiptConfigV1,
        initial_binding: Digest32,
        origin: RetainedVersionOriginV1,
        purpose: RetainedVersionPurposeV1,
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
            purpose,
            state: Mutex::new(state),
            preparation_requested: AtomicBool::new(origin == RetainedVersionOriginV1::Recovered),
            publication_requested: AtomicBool::new(origin == RetainedVersionOriginV1::Recovered),
            issuer_worker_started: AtomicBool::new(origin == RetainedVersionOriginV1::Recovered),
            final_use_outcome: AtomicU8::new(match origin {
                RetainedVersionOriginV1::Fresh => RetainedVersionFinalUseOutcomeV1::Awaiting as u8,
                RetainedVersionOriginV1::Recovered => {
                    RetainedVersionFinalUseOutcomeV1::Published as u8
                }
            }),
            runtime_started: AtomicBool::new(origin == RetainedVersionOriginV1::Recovered),
            end,
            runtime: Handle::try_current().map_err(|_| Error::Unavailable)?,
            connections: Arc::new(Semaphore::new(4)),
            installed: Notify::new(),
            prepared: Notify::new(),
        })
    }

    fn require_lifetime(&self) -> Result<(), Error> {
        if Instant::now() >= self.end {
            return Err(Error::Unavailable);
        }
        Ok(())
    }

    fn original_final_use_outcome(&self) -> RetainedVersionFinalUseOutcomeV1 {
        match self.final_use_outcome.load(Ordering::Acquire) {
            0 => RetainedVersionFinalUseOutcomeV1::Awaiting,
            1 => RetainedVersionFinalUseOutcomeV1::Requested,
            2 => RetainedVersionFinalUseOutcomeV1::Denied,
            4 => RetainedVersionFinalUseOutcomeV1::Published,
            _ => RetainedVersionFinalUseOutcomeV1::Uncertain,
        }
    }
}
