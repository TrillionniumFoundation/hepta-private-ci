#![cfg(target_os = "linux")]

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::time::Duration;

use codex_hepta_agentd::AgentdUnixFinalUseGrantProvider;
use codex_hepta_agentd::LearningIterationEvidencePeerV1;
use codex_hepta_agentd::OriginalCellEvaluationCommandErrorV1;
use codex_hepta_agentd::OriginalCellEvaluationModelMaterialConnectionV1;
use codex_hepta_agentd::OriginalCellEvaluationPanelRegistrationV1;
use codex_hepta_agentd::OriginalCellQ24DatasetCommandReadbackV1;
use codex_hepta_agentd::OriginalCellQ24MaterialReceiptConfigV1;
use codex_hepta_agentd::OriginalCellQ24NoUpdatePeerStreamV1;
use codex_hepta_agentd::OriginalCellQ24TrainingCommandConnectionV1;
use codex_hepta_agentd::OriginalCircuitNextUseCommandClientV1;
use codex_hepta_agentd::OriginalCircuitNextUseCommandErrorV1;
use codex_hepta_agentd::OriginalCircuitRetainedArtifactCheckpointV1;
use codex_hepta_agentd::OriginalCircuitRetainedPublicationInputsV1;
use codex_hepta_agentd::OriginalCircuitRetainedPublicationTaskV1;
use codex_hepta_agentd::OriginalCircuitRetainedTaskInputsV1;
use codex_hepta_agentd::OriginalCircuitRetainedVersionErrorV1;
use codex_hepta_agentd::OriginalCircuitRetainedVersionHostV1;
use codex_hepta_agentd::OriginalCircuitSelectionCommandClientV1;
use codex_hepta_agentd::OriginalCircuitSelectionCommandErrorV1;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_neuron::FileAnchorWitnessStore;

type PositionalSelector =
    fn(
        UnixStream,
        LearningIterationEvidencePeerV1,
        OwnedFd,
        LearningIterationSnapshotV1,
        FrozenLearningScopeV2,
        LearningEvidenceVerifierV1,
        SignedLearningEvidenceV1,
        Option<(LearningIterationSnapshotV1, SignedLearningEvidenceV1)>,
        Duration,
        Duration,
    )
        -> Result<OriginalCircuitSelectionCommandClientV1, OriginalCircuitSelectionCommandErrorV1>;

type NamedSelector =
    fn(
        OriginalCellQ24NoUpdatePeerStreamV1,
        LearningIterationSnapshotV1,
        FrozenLearningScopeV2,
        LearningEvidenceVerifierV1,
        SignedLearningEvidenceV1,
        Option<(LearningIterationSnapshotV1, SignedLearningEvidenceV1)>,
    )
        -> Result<OriginalCircuitSelectionCommandClientV1, OriginalCircuitSelectionCommandErrorV1>;

type PositionalNextUse =
    fn(
        UnixStream,
        LearningIterationEvidencePeerV1,
        OwnedFd,
        LearningIterationSnapshotV1,
        FrozenLearningScopeV2,
        LearningEvidenceVerifierV1,
        SignedLearningEvidenceV1,
        SignedLearningEvidenceV1,
        Option<(LearningIterationSnapshotV1, SignedLearningEvidenceV1)>,
        Duration,
        Duration,
    ) -> Result<OriginalCircuitNextUseCommandClientV1, OriginalCircuitNextUseCommandErrorV1>;

type NamedNextUse =
    fn(
        OriginalCellQ24NoUpdatePeerStreamV1,
        LearningIterationSnapshotV1,
        FrozenLearningScopeV2,
        LearningEvidenceVerifierV1,
        SignedLearningEvidenceV1,
        SignedLearningEvidenceV1,
        Option<(LearningIterationSnapshotV1, SignedLearningEvidenceV1)>,
    ) -> Result<OriginalCircuitNextUseCommandClientV1, OriginalCircuitNextUseCommandErrorV1>;

type PositionalMaterial = fn(
    UnixStream,
    LearningIterationEvidencePeerV1,
    OwnedFd,
    LearningIterationSnapshotV1,
    FrozenLearningScopeV2,
    OriginalCellEvaluationPanelRegistrationV1,
    LearningEvidenceVerifierV1,
    Duration,
    Duration,
) -> Result<
    OriginalCellEvaluationModelMaterialConnectionV1,
    OriginalCellEvaluationCommandErrorV1,
>;

type NamedMaterial = fn(
    OriginalCellQ24NoUpdatePeerStreamV1,
    LearningIterationSnapshotV1,
    FrozenLearningScopeV2,
    OriginalCellEvaluationPanelRegistrationV1,
    LearningEvidenceVerifierV1,
) -> Result<
    OriginalCellEvaluationModelMaterialConnectionV1,
    OriginalCellEvaluationCommandErrorV1,
>;

type PositionalPublication =
    fn(
        OriginalCellQ24MaterialReceiptConfigV1,
        OriginalCellQ24DatasetCommandReadbackV1,
        OriginalCellQ24TrainingCommandConnectionV1,
        OriginalCircuitRetainedPublicationInputsV1<FileAnchorWitnessStore, FileAnchorWitnessStore>,
        OriginalCircuitRetainedTaskInputsV1,
        OriginalCircuitRetainedArtifactCheckpointV1,
        AgentdUnixFinalUseGrantProvider,
        Duration,
    ) -> Result<OriginalCircuitRetainedVersionHostV1, OriginalCircuitRetainedVersionErrorV1>;

type NamedPublication =
    fn(
        OriginalCellQ24MaterialReceiptConfigV1,
        OriginalCellQ24DatasetCommandReadbackV1,
        OriginalCellQ24TrainingCommandConnectionV1,
        OriginalCircuitRetainedPublicationTaskV1,
        OriginalCircuitRetainedArtifactCheckpointV1,
        AgentdUnixFinalUseGrantProvider,
        Duration,
    ) -> Result<OriginalCircuitRetainedVersionHostV1, OriginalCircuitRetainedVersionErrorV1>;

#[test]
fn public_v1_command_and_publication_constructors_keep_their_calling_forms() {
    let _: PositionalSelector =
        OriginalCircuitSelectionCommandClientV1::recover_from_original_stream;
    let _: NamedSelector =
        OriginalCircuitSelectionCommandClientV1::recover_from_original_peer_stream;
    let _: PositionalNextUse = OriginalCircuitNextUseCommandClientV1::recover_from_original_stream;
    let _: NamedNextUse = OriginalCircuitNextUseCommandClientV1::recover_from_original_peer_stream;
    let _: PositionalMaterial =
        OriginalCellEvaluationModelMaterialConnectionV1::from_original_stream;
    let _: NamedMaterial =
        OriginalCellEvaluationModelMaterialConnectionV1::from_original_peer_stream;
    let _: PositionalPublication = OriginalCircuitRetainedVersionHostV1::from_original_owners;
    let _: NamedPublication = OriginalCircuitRetainedVersionHostV1::from_original_publication_task;
}
