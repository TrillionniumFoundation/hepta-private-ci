#![cfg(target_os = "linux")]

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::time::Duration;

use codex_hepta_agentd::LearningIterationEvidencePeerV1;
use codex_hepta_agentd::OriginalCellEvaluationCommandConnectionV1;
use codex_hepta_agentd::OriginalCellEvaluationCommandErrorV1;
use codex_hepta_agentd::OriginalCellEvaluationPanelRegistrationV1;
use codex_hepta_agentd::OriginalCellQ24MaterialReceiptConfigV1;
use codex_hepta_agentd::OriginalCellQ24ModelCommandConnectionV1;
use codex_hepta_agentd::OriginalCellQ24ModelCommandErrorV1;
use codex_hepta_agentd::OriginalCellQ24NoUpdatePeerStreamV1;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_types::Digest32;

type EvaluationConnection =
    Result<OriginalCellEvaluationCommandConnectionV1, OriginalCellEvaluationCommandErrorV1>;
type ModelConnection =
    Result<OriginalCellQ24ModelCommandConnectionV1, OriginalCellQ24ModelCommandErrorV1>;
type ExpectedModel = Option<(LearningIterationSnapshotV1, Digest32)>;

type PositionalEvaluation = fn(
    UnixStream,
    LearningIterationEvidencePeerV1,
    OwnedFd,
    LearningIterationSnapshotV1,
    FrozenLearningScopeV2,
    OriginalCellEvaluationPanelRegistrationV1,
    LearningEvidenceVerifierV1,
    Duration,
    Duration,
) -> EvaluationConnection;
type NamedEvaluation = fn(
    OriginalCellQ24NoUpdatePeerStreamV1,
    LearningIterationSnapshotV1,
    FrozenLearningScopeV2,
    OriginalCellEvaluationPanelRegistrationV1,
    LearningEvidenceVerifierV1,
) -> EvaluationConnection;
type PositionalModel = fn(
    UnixStream,
    LearningIterationEvidencePeerV1,
    OwnedFd,
    OriginalCellQ24MaterialReceiptConfigV1,
    OriginalCellEvaluationPanelRegistrationV1,
    ExpectedModel,
    Duration,
    Duration,
) -> ModelConnection;
type NamedModel = fn(
    OriginalCellQ24NoUpdatePeerStreamV1,
    OriginalCellQ24MaterialReceiptConfigV1,
    OriginalCellEvaluationPanelRegistrationV1,
    ExpectedModel,
) -> ModelConnection;

#[test]
fn public_v1_candidate_peer_constructors_retain_both_calling_forms() {
    let _: PositionalEvaluation = OriginalCellEvaluationCommandConnectionV1::from_original_stream;
    let _: NamedEvaluation = OriginalCellEvaluationCommandConnectionV1::from_original_peer_stream;
    let _: PositionalEvaluation =
        OriginalCellEvaluationCommandConnectionV1::recover_from_original_stream;
    let _: NamedEvaluation =
        OriginalCellEvaluationCommandConnectionV1::recover_from_original_peer_stream;
    let _: PositionalModel = OriginalCellQ24ModelCommandConnectionV1::recover_from_original_stream;
    let _: NamedModel = OriginalCellQ24ModelCommandConnectionV1::recover_from_original_peer_stream;
}
