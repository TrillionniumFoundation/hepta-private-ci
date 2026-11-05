use super::*;
use crate::ControlStateDigest;
use crate::SupervisorEpoch;
use crate::SupervisordMethod;
use crate::SupervisordPayload;
use crate::SupervisordRequest;
use crate::SupervisordResponse;
use crate::daemon_protocol::MAX_SUPERVISORD_CONTROL_FRAME_BYTES;
use crate::daemon_protocol::SUPERVISORD_CONTROL_SCHEMA_VERSION;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::ReleaseId;
use pretty_assertions::assert_eq;
use serde_json::json;

const AGENT: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const EPOCH: &str = "018f4f72-5f8f-4cc1-8f55-df9fb3aa2c12";

fn fence() -> SupervisordControlFence {
    SupervisordControlFence {
        agent_id: AgentId::parse(AGENT).unwrap(),
        supervisor_epoch: SupervisorEpoch::parse(EPOCH).unwrap(),
        lifecycle: AgentLifecycle::Running,
        lifecycle_generation: 7,
        spawn_generation: Some(5),
        runtime_generation: Some(7),
        current_release: Some(ReleaseId::parse("agentd-v1").unwrap()),
        previous_release: None,
        release_change_pending: false,
        state_digest: ControlStateDigest::parse("a".repeat(64)).unwrap(),
    }
}

/// Deliberately unauthenticated transport fixture. Its signature-sized bytes
/// exercise wire bounds; these tests do not grant it cryptographic authority.
fn state(history_count: usize) -> ProductionMutationState {
    let digest = Sha256Digest::for_bytes(b"transport-only");
    let history: Vec<_> = (0..history_count)
        .map(|index| {
            json!({
                "target_release": format!("agentd-v{}", index + 2), "transition": "upgrade",
                "decision": {
                    "schema_version": 2, "namespace": "transport-only",
                    "agent_id": AGENT, "grant_sha256": digest, "intent_sha256": digest,
                    "release_transaction_sha256": digest, "observed_release": "agentd-v1",
                    "observed_manifest_sha256": digest, "observed_agentd_sha256": digest,
                    "observed_matrixd_sha256": null, "outcome": "abandon_unknown",
                    "unknown_observation": null, "expected_lifecycle_generation": 7,
                    "authority_epoch": 9, "signer_id": "transport-only", "signer_epoch": 1,
                    "issued_at_unix_seconds": 100, "expires_at_unix_seconds": 200,
                    "signature_base64": "A".repeat(4412), "decision_sha256": digest,
                }
            })
        })
        .collect();
    serde_json::from_value(json!({
        "receipt": {
            "grant_sha256": digest, "agent_id": AGENT, "transition": "upgrade",
            "source_release": "agentd-v1", "target_release": "agentd-v2",
            "control_revision": 13, "status": "aborted", "production_authority": false,
            "external_effects": false, "operator_acceptance": false, "promotion": false,
        },
        "intent_sha256": digest, "release_transaction_sha256": digest,
        "unknown_effects": history,
    }))
    .unwrap()
}

fn pages(state: &ProductionMutationState) -> Vec<ProductionMutationPageV1> {
    let mut result = Vec::new();
    let mut cursor = None;
    loop {
        let page = production_mutation_page(Some(state.clone()), fence(), cursor.as_ref()).unwrap();
        cursor = page.next_cursor.clone();
        result.push(page);
        if cursor.is_none() {
            return result;
        }
        assert!(result.len() < MAX_PRODUCTION_MUTATION_PAGES);
    }
}

fn response_bytes(request_id: u64, payload: SupervisordPayload) -> Vec<u8> {
    let mut bytes = serde_json::to_vec(&SupervisordResponse {
        schema_version: SUPERVISORD_CONTROL_SCHEMA_VERSION,
        request_id,
        payload,
    })
    .unwrap();
    bytes.push(b'\n');
    bytes
}

#[test]
fn all_32_signature_sized_history_items_fit_pages_without_changing_the_frame_bound() {
    let state = state(/*history_count*/ 32);
    assert!(
        response_bytes(
            u64::MAX,
            SupervisordPayload::ProductionMutationStatus {
                state: Some(state.clone()),
            }
        )
        .len() as u64
            > MAX_SUPERVISORD_CONTROL_FRAME_BYTES
    );
    let mut pages = pages(&state).into_iter();
    let first = pages.next().unwrap();
    let mut assembler =
        ProductionMutationPageAssembler::new(first.clone(), &fence().agent_id).unwrap();
    let mut count = 1;
    for page in std::iter::once(&first).chain(pages.clone().as_slice()) {
        assert!(
            response_bytes(
                u64::MAX,
                SupervisordPayload::ProductionMutationStatusPageV1 { page: page.clone() }
            )
            .len() as u64
                <= MAX_SUPERVISORD_CONTROL_FRAME_BYTES
        );
    }
    for page in pages {
        assembler.push(page).unwrap();
        count += 1;
    }
    assert_eq!(count, 8);
    assert_eq!(assembler.finish().unwrap(), Some(state));
}

#[test]
fn cursor_refuses_changed_durable_state_epoch_control_fence_and_agent() {
    let state = state(/*history_count*/ 8);
    let cursor = pages(&state)[0].next_cursor.clone().unwrap();
    let mut changed = state.clone();
    changed.intent_sha256 = Sha256Digest::for_bytes(b"new intent");
    assert!(production_mutation_page(Some(changed), fence(), Some(&cursor)).is_err());
    let mut changed = state.clone();
    changed.receipt.control_revision += 1;
    assert!(production_mutation_page(Some(changed), fence(), Some(&cursor)).is_err());
    let mut changed = state.clone();
    changed.unknown_effects[7].target_release = "agentd-other".to_string();
    assert!(production_mutation_page(Some(changed), fence(), Some(&cursor)).is_err());
    for changed in [
        SupervisordControlFence {
            supervisor_epoch: SupervisorEpoch::new(),
            ..fence()
        },
        SupervisordControlFence {
            lifecycle_generation: 8,
            ..fence()
        },
        SupervisordControlFence {
            state_digest: ControlStateDigest::parse("b".repeat(64)).unwrap(),
            ..fence()
        },
    ] {
        assert!(production_mutation_page(Some(state.clone()), changed, Some(&cursor)).is_err());
    }
    let request = SupervisordRequest::new(
        1,
        SupervisordMethod::ProductionMutationStatusPageV1 {
            agent_id: AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13").unwrap(),
            cursor: Some(cursor.clone()),
        },
    );
    assert!(request.validate().is_err());
    for offset in [0, 32, u16::MAX] {
        let mut changed = cursor.clone();
        changed.history_offset = offset;
        assert!(changed.validate().is_err());
    }
    let mut encoded = serde_json::to_value(cursor).unwrap();
    encoded["unbound"] = json!(true);
    assert!(serde_json::from_value::<ProductionMutationCursorV1>(encoded).is_err());
}

#[test]
fn assembler_refuses_missing_repeated_reordered_mixed_and_forged_pages() {
    let pages = pages(&state(/*history_count*/ 12));
    let new = || ProductionMutationPageAssembler::new(pages[0].clone(), &fence().agent_id).unwrap();
    assert!(new().finish().is_err());
    assert!(new().push(pages[0].clone()).is_err());
    assert!(new().push(pages[2].clone()).is_err());
    let mut changed = pages[1].clone();
    changed.summary.as_mut().unwrap().receipt.target_release = "other".to_string();
    assert!(new().push(changed).is_err());
    let mut changed = pages[1].clone();
    changed.unknown_effects.pop();
    assert!(new().push(changed).is_err());
    let mut changed = pages[1].clone();
    changed.next_cursor.as_mut().unwrap().history_offset = 11;
    assert!(new().push(changed).is_err());
    let mut changed = pages[1].clone();
    changed.unknown_effects[0]
        .decision
        .signature_base64
        .replace_range(..1, "B");
    let mut assembled = new();
    assembled.push(changed).unwrap();
    assembled.push(pages[2].clone()).unwrap();
    assert!(
        assembled.finish().is_err(),
        "public digest must cover the complete history bytes"
    );
    assert!(ProductionMutationPageAssembler::new(pages[1].clone(), &fence().agent_id).is_err());
    let mut encoded = serde_json::to_value(&pages[0]).unwrap();
    encoded["unbound"] = json!(true);
    assert!(serde_json::from_value::<ProductionMutationPageV1>(encoded).is_err());
}

#[test]
fn absent_empty_and_excessive_histories_have_explicit_bounded_results() {
    let empty = production_mutation_page(None, fence(), None).unwrap();
    assert_eq!(
        ProductionMutationPageAssembler::new(empty, &fence().agent_id)
            .unwrap()
            .finish()
            .unwrap(),
        None
    );
    let state = state(/*history_count*/ 0);
    let empty = production_mutation_page(Some(state.clone()), fence(), None).unwrap();
    assert_eq!(
        ProductionMutationPageAssembler::new(empty, &fence().agent_id)
            .unwrap()
            .finish()
            .unwrap(),
        Some(state)
    );
    let cursor = pages(&self::state(/*history_count*/ 8))[0]
        .next_cursor
        .clone()
        .unwrap();
    assert!(production_mutation_page(None, fence(), Some(&cursor)).is_err());
    assert!(
        production_mutation_page(Some(self::state(/*history_count*/ 33)), fence(), None).is_err()
    );
    let mut oversized = self::state(/*history_count*/ 1);
    oversized.unknown_effects[0].target_release = "x".repeat(MAX_PAGE_BYTES);
    assert!(production_mutation_page(Some(oversized), fence(), None).is_err());
}

#[cfg(unix)]
mod unix {
    use super::*;
    use crate::SupervisordClient;
    use pretty_assertions::assert_eq;
    use std::time::Duration;
    use tokio::io::AsyncReadExt;
    use tokio::io::AsyncWriteExt;
    use tokio::net::UnixListener;
    use tokio::net::UnixStream;
    use tokio::time::timeout;

    async fn request(listener: &UnixListener) -> (UnixStream, SupervisordRequest) {
        timeout(Duration::from_secs(3), async {
            let (mut stream, _) = listener.accept().await.unwrap();
            let mut bytes = Vec::new();
            (&mut stream)
                .take(MAX_SUPERVISORD_CONTROL_FRAME_BYTES + 1)
                .read_to_end(&mut bytes)
                .await
                .unwrap();
            assert!(bytes.len() as u64 <= MAX_SUPERVISORD_CONTROL_FRAME_BYTES);
            let request: SupervisordRequest = serde_json::from_slice(&bytes).unwrap();
            request.validate().unwrap();
            (stream, request)
        })
        .await
        .expect("bounded fixture request wait")
    }

    #[tokio::test]
    async fn real_control_socket_reassembles_all_history_through_only_bounded_read_requests() {
        let root = tempfile::tempdir().unwrap();
        let path = root.path().join("pages.sock");
        let listener = UnixListener::bind(&path).unwrap();
        let expected = state(/*history_count*/ 32);
        let fixture = expected.clone();
        let server = tokio::spawn(async move {
            let mut seen = 0;
            loop {
                let (mut stream, request) = request(&listener).await;
                let SupervisordMethod::ProductionMutationStatusPageV1 { agent_id, cursor } =
                    request.method
                else {
                    panic!("expected a bounded read request");
                };
                assert_eq!(agent_id, fence().agent_id);
                let page =
                    production_mutation_page(Some(fixture.clone()), fence(), cursor.as_ref())
                        .unwrap();
                let finished = page.next_cursor.is_none();
                let bytes = response_bytes(
                    request.request_id,
                    SupervisordPayload::ProductionMutationStatusPageV1 { page },
                );
                assert!(bytes.len() as u64 <= MAX_SUPERVISORD_CONTROL_FRAME_BYTES);
                stream.write_all(&bytes).await.unwrap();
                stream.shutdown().await.unwrap();
                seen += 1;
                if finished {
                    return seen;
                }
            }
        });
        let actual = SupervisordClient::new(path)
            .unwrap()
            .production_mutation_status(fence().agent_id)
            .await
            .unwrap();
        assert_eq!(actual, Some(expected));
        assert_eq!(server.await.unwrap(), 8);
    }

    #[tokio::test]
    async fn recovery_is_sent_once_and_stale_followup_pages_do_not_repeat_it() {
        let root = tempfile::tempdir().unwrap();
        let path = root.path().join("recovery.sock");
        let listener = UnixListener::bind(&path).unwrap();
        let fixture = state(/*history_count*/ 8);
        let decision = fixture.unknown_effects[0].decision.clone();
        let server = tokio::spawn(async move {
            let (mut stream, request) = request(&listener).await;
            assert!(matches!(
                request.method,
                SupervisordMethod::ResolveProductionRecoveryPageV1 { .. }
            ));
            let page = production_mutation_page(Some(fixture), fence(), None).unwrap();
            stream
                .write_all(&response_bytes(
                    request.request_id,
                    SupervisordPayload::ProductionMutationStatusPageV1 { page },
                ))
                .await
                .unwrap();
            stream.shutdown().await.unwrap();
            let (mut stream, request) = self::request(&listener).await;
            assert!(matches!(
                request.method,
                SupervisordMethod::ProductionMutationStatusPageV1 {
                    cursor: Some(_),
                    ..
                }
            ));
            stream
                .write_all(&response_bytes(
                    request.request_id,
                    SupervisordPayload::Error {
                        code: "stale_page".to_string(),
                        message: "durable state changed".to_string(),
                        actual: None,
                    },
                ))
                .await
                .unwrap();
            stream.shutdown().await.unwrap();
            listener
        });
        let error = SupervisordClient::new(path)
            .unwrap()
            .resolve_production_recovery(fence(), decision)
            .await
            .unwrap_err();
        assert!(error.to_string().contains("stale_page"));
        let listener = server.await.unwrap();
        assert!(
            timeout(Duration::from_millis(150), listener.accept())
                .await
                .is_err()
        );
    }

    #[tokio::test]
    async fn all_pages_share_the_original_two_second_deadline() {
        let root = tempfile::tempdir().unwrap();
        let path = root.path().join("deadline.sock");
        let listener = UnixListener::bind(&path).unwrap();
        let fixture = state(/*history_count*/ 8);
        let server = tokio::spawn(async move {
            for _ in 0..2 {
                let (mut stream, request) = request(&listener).await;
                let SupervisordMethod::ProductionMutationStatusPageV1 { cursor, .. } =
                    request.method
                else {
                    panic!("only read requests are permitted");
                };
                let page =
                    production_mutation_page(Some(fixture.clone()), fence(), cursor.as_ref())
                        .unwrap();
                tokio::time::sleep(Duration::from_millis(1_200)).await;
                let _ = stream
                    .write_all(&response_bytes(
                        request.request_id,
                        SupervisordPayload::ProductionMutationStatusPageV1 { page },
                    ))
                    .await;
            }
        });
        let error = SupervisordClient::new(path)
            .unwrap()
            .production_mutation_status(fence().agent_id)
            .await
            .unwrap_err();
        assert!(error.to_string().contains("total page deadline"));
        server.await.unwrap();
    }

    #[tokio::test(flavor = "current_thread")]
    async fn ready_response_is_rejected_when_client_polling_resumes_after_deadline() {
        use std::future::Future;
        use std::task::Context;
        use std::task::Waker;

        let root = tempfile::tempdir().unwrap();
        let path = root.path().join("delayed-poll.sock");
        let listener = UnixListener::bind(&path).unwrap();
        let (ready_sender, mut ready_receiver) = tokio::sync::oneshot::channel();
        let server = tokio::spawn(async move {
            let (mut stream, request) = request(&listener).await;
            let page = production_mutation_page(Some(state(0)), fence(), None).unwrap();
            stream
                .write_all(&response_bytes(
                    request.request_id,
                    SupervisordPayload::ProductionMutationStatusPageV1 { page },
                ))
                .await
                .unwrap();
            ready_sender.send(()).unwrap();
        });
        let client = SupervisordClient::new(path).unwrap();
        let mut operation = std::pin::pin!(client.production_mutation_status(fence().agent_id));
        let preparation_deadline = std::time::Instant::now() + Duration::from_secs(1);
        loop {
            if ready_receiver.try_recv().is_ok() {
                break;
            }
            assert!(
                std::time::Instant::now() < preparation_deadline,
                "fixture did not become ready"
            );
            let mut context = Context::from_waker(Waker::noop());
            assert!(operation.as_mut().poll(&mut context).is_pending());
            tokio::time::sleep(Duration::from_millis(1)).await;
        }
        // Deliberately stall this executor after the peer's response is ready.
        // A timer that polls its inner future first must not accept the result.
        std::thread::sleep(Duration::from_millis(2_100));
        let error = operation.await.unwrap_err();
        assert!(error.to_string().contains("total page deadline"));
        server.await.unwrap();
    }
}
