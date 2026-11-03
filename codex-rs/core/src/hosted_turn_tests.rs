use std::collections::BTreeMap;

use codex_history::{TurnRecoveryHistoryBoundary, TurnRecoveryReplayV1, TurnRecoveryRequestBinding, TurnRecoveryStartState};
use futures::FutureExt;
use pretty_assertions::assert_eq;
use tokio_util::sync::CancellationToken;

use super::{HostedQueueBinding, HostedQueueCompletion, HostedTurnProvenance};

#[tokio::test]
async fn effects_wait_for_original_queue_completion_after_host_admission() {
    let (owner, waiter) = HostedQueueCompletion::channel();
    let cancellation = CancellationToken::new();
    let waiting = waiter.wait(&cancellation);
    tokio::pin!(waiting);
    assert!(waiting.as_mut().now_or_never().is_none());
    owner.committed();
    waiting.await.expect("original queue committed");
}

#[tokio::test]
async fn unknown_queue_owner_drop_does_not_release_effects() {
    let (owner, waiter) = HostedQueueCompletion::channel();
    drop(owner);
    let error = waiter.wait(&CancellationToken::new()).await.expect_err("unknown remains held");
    assert!(error.to_string().contains("completion is unknown"));
}

#[tokio::test]
async fn cancellation_can_stop_a_waiter_without_committing_the_queue() {
    let (_owner, waiter) = HostedQueueCompletion::channel();
    let cancellation = CancellationToken::new();
    cancellation.cancel();
    let error = waiter.wait(&cancellation).await.expect_err("cancelled original queue waiter");
    assert!(matches!(error.details(), codex_protocol::error::CodexErrorDetails::TurnAborted));
}

#[test]
fn original_hosted_route_and_queue_identity_survive_typed_recovery() {
    let provenance = HostedTurnProvenance {
        executor_id: "test-owner".to_string(),
        correlation: BTreeMap::from([("run".to_string(), "original-run".to_string())]),
        queue: HostedQueueBinding { queued_item_id: "queued-one".to_string(), client_id: "client-one".to_string(), payload_sha256: "a".repeat(64) },
    };
    let boundary = TurnRecoveryHistoryBoundary { item_count: 0, prefix_sha256: "b".repeat(64) };
    let recovery = TurnRecoveryRequestBinding {
        turn_id: "original-turn".to_string(), generation: 0, fingerprint_sha256: "c".repeat(64),
        history_boundary: Some(boundary.clone()),
        replay: Some(TurnRecoveryReplayV1 {
            history_boundary: boundary, turn_context_sha256: "d".repeat(64),
            start: TurnRecoveryStartState { final_output_json_schema: None, parent_turn_id: None, root_turn_id: None, responses_metadata_extra: provenance.metadata().expect("bounded metadata") },
            environments: Vec::new(),
        }),
        replay_applied_from_generation: None,
    };
    assert_eq!(HostedTurnProvenance::from_recovery(&recovery).expect("read original metadata"), Some(provenance));
    let mut oversized = recovery;
    oversized.replay.as_mut().unwrap().start.responses_metadata_extra
        .insert(super::PROVENANCE_KEY.to_string(), "x".repeat(super::MAX_PROVENANCE_BYTES + 1));
    assert!(HostedTurnProvenance::from_recovery(&oversized).is_err());
}
