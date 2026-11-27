#![cfg(target_os = "linux")]

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_agentd::LearningIterationEvidencePeerV1;
use codex_hepta_agentd::LoadedCellQ24ModelV1;
use codex_hepta_agentd::OriginalCellQ24MaterialSourceConnectionV1;
use codex_hepta_agentd::OriginalCellQ24MaterialSourceErrorV1;
use codex_hepta_agentd::OriginalCellQ24NoUpdatePeerStreamV1;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;

type ConnectionResult =
    Result<OriginalCellQ24MaterialSourceConnectionV1, OriginalCellQ24MaterialSourceErrorV1>;

type PositionalConstructor = fn(
    UnixStream,
    LearningIterationEvidencePeerV1,
    OwnedFd,
    LearningIterationSnapshotV1,
    FrozenLearningScopeV2,
    Arc<LoadedCellQ24ModelV1>,
    Duration,
    Duration,
) -> ConnectionResult;

type NamedConstructor = fn(
    OriginalCellQ24NoUpdatePeerStreamV1,
    LearningIterationSnapshotV1,
    FrozenLearningScopeV2,
    Arc<LoadedCellQ24ModelV1>,
) -> ConnectionResult;

#[test]
fn public_material_source_constructors_accept_both_v1_signatures() {
    let _: PositionalConstructor = OriginalCellQ24MaterialSourceConnectionV1::from_original_stream;
    let _: NamedConstructor = OriginalCellQ24MaterialSourceConnectionV1::from_original_peer_stream;
}
