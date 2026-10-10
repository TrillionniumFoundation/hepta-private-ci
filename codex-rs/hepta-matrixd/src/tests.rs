use std::collections::VecDeque;
use std::sync::Arc;
use std::sync::Mutex as StdMutex;

use codex_app_server_protocol::UserInput;
use codex_hepta_contracts::AgentId;
use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;

use super::*;

#[derive(Clone, Default)]
struct FakeTransport {
    state: Arc<StdMutex<FakeState>>,
}

#[derive(Default)]
struct FakeState {
    project_request: Option<BridgeProjectCreate>,
    project: Option<BridgeProject>,
    threads: Vec<BridgeThread>,
    thread_start_calls: usize,
    reconcile_requests: Vec<BridgeQueueReconcile>,
    reconcile_responses: VecDeque<Result<BridgeQueueReconcileResponse, MatrixBridgeError>>,
    hide_threads_from_list: bool,
}

impl FakeTransport {
    fn snapshot(&self) -> FakeSnapshot {
        let state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        FakeSnapshot {
            thread_start_calls: state.thread_start_calls,
            reconcile_requests: state.reconcile_requests.clone(),
        }
    }

    fn script_reconcile(&self, response: BridgeQueueReconcileResponse) {
        self.state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .reconcile_responses
            .push_back(Ok(response));
    }

    fn hide_threads_from_list(&self, hide: bool) {
        self.state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .hide_threads_from_list = hide;
    }
}

struct FakeSnapshot {
    thread_start_calls: usize,
    reconcile_requests: Vec<BridgeQueueReconcile>,
}

impl MatrixAppServerTransport for FakeTransport {
    fn create_project(&self, request: BridgeProjectCreate) -> BridgeFuture<'_, BridgeProject> {
        Box::pin(async move {
            let mut state = self
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            if let Some(existing_request) = state.project_request.as_ref()
                && existing_request != &request
            {
                return Err(MatrixBridgeError::Protocol(
                    "fake received project/create idempotency drift".to_string(),
                ));
            }
            state.project_request.get_or_insert_with(|| request.clone());
            let project = state
                .project
                .get_or_insert_with(|| BridgeProject {
                    id: "project-room-a".to_string(),
                    roots: request.roots,
                    metadata: request.metadata,
                })
                .clone();
            Ok(project)
        })
    }

    fn list_threads(
        &self,
        request: BridgeThreadList,
    ) -> BridgeFuture<'_, BridgePage<BridgeThread>> {
        Box::pin(async move {
            let state = self
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            let data = if state.hide_threads_from_list {
                Vec::new()
            } else {
                state
                    .threads
                    .iter()
                    .filter(|thread| {
                        thread.project_id.as_deref() == Some(request.project_id.as_str())
                            && thread.cwd == request.cwd
                    })
                    .cloned()
                    .collect()
            };
            Ok(BridgePage {
                data,
                next_cursor: None,
            })
        })
    }

    fn start_thread(&self, request: BridgeThreadStart) -> BridgeFuture<'_, BridgeThread> {
        Box::pin(async move {
            let mut state = self
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            state.thread_start_calls += 1;
            let thread = BridgeThread {
                id: format!("thread-{}", state.thread_start_calls),
                project_id: Some(request.project_id),
                cwd: request.cwd,
                ephemeral: false,
                thread_source: Some(BRIDGE_THREAD_SOURCE.to_string()),
            };
            state.threads.push(thread.clone());
            Ok(thread)
        })
    }

    fn reconcile_queue(
        &self,
        request: BridgeQueueReconcile,
    ) -> BridgeFuture<'_, BridgeQueueReconcileResponse> {
        Box::pin(async move {
            let mut state = self
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            state.reconcile_requests.push(request);
            state.reconcile_responses.pop_front().unwrap_or_else(|| {
                Err(MatrixBridgeError::Protocol(
                    "fake reconcile response was not scripted".to_string(),
                ))
            })
        })
    }
}

fn agent_id() -> AgentId {
    AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent id")
}

fn room_id() -> MatrixRoomId {
    MatrixRoomId::parse("!room-a:example.test").expect("room id")
}

fn event_id() -> MatrixEventId {
    MatrixEventId::parse("$event-a").expect("event id")
}

fn config() -> MatrixBridgeConfig {
    MatrixBridgeConfig::new(
        agent_id(),
        AbsolutePathBuf::from_absolute_path("/tmp/hepta-matrix-agent-a")
            .expect("absolute workspace"),
    )
}

fn input() -> Vec<UserInput> {
    vec![UserInput::Text {
        text: "hello from Matrix".to_string(),
        text_elements: Vec::new(),
    }]
}

fn different_input() -> Vec<UserInput> {
    vec![UserInput::Text {
        text: "different Matrix payload".to_string(),
        text_elements: Vec::new(),
    }]
}

fn input_payload_sha256(input: &[UserInput]) -> String {
    bridge_user_input_payload_sha256(input).expect("canonical user-input digest")
}

fn matrix_client_id() -> String {
    client_user_message_id(&agent_id(), &room_id(), &event_id())
}

fn queued_reconcile_response(created: bool) -> BridgeQueueReconcileResponse {
    let client_id = matrix_client_id();
    let payload_sha256 = input_payload_sha256(&input());
    BridgeQueueReconcileResponse {
        client_user_message_id: client_id.clone(),
        payload_sha256: Some(payload_sha256.clone()),
        outcome: BridgeQueueReconcileOutcome::Queued {
            queued_submission: BridgeQueuedSubmission {
                id: "queue-1".to_string(),
                client_user_message_id: client_id,
                payload_sha256: Some(payload_sha256),
            },
            created,
        },
    }
}

fn persisted_reconcile_response(turn_id: &str) -> BridgeQueueReconcileResponse {
    BridgeQueueReconcileResponse {
        client_user_message_id: matrix_client_id(),
        payload_sha256: Some(input_payload_sha256(&input())),
        outcome: BridgeQueueReconcileOutcome::Persisted {
            turn_id: turn_id.to_string(),
        },
    }
}

#[tokio::test]
async fn first_message_recovers_thread_after_crash_without_second_thread_start() {
    let fake = FakeTransport::default();
    let first_process =
        MatrixAppServerBridge::new(config(), fake.clone()).expect("first bridge process");
    let first = first_process
        .ensure_room_thread(&room_id())
        .await
        .expect("first process starts the thread");
    assert!(!first.recovered);
    drop(first_process);

    let restarted_process =
        MatrixAppServerBridge::new(config(), fake.clone()).expect("restarted bridge process");
    fake.script_reconcile(queued_reconcile_response(true));
    let submitted = restarted_process
        .submit_matrix_event(&room_id(), &event_id(), input())
        .await
        .expect("restarted process recovers and queues first message");

    assert!(submitted.binding.recovered);
    assert_eq!(submitted.binding.thread_id, first.thread_id);
    assert!(matches!(
        submitted.state,
        MatrixSubmissionState::Queued { .. }
    ));
    let snapshot = fake.snapshot();
    assert_eq!(snapshot.thread_start_calls, 1);
    assert_eq!(snapshot.reconcile_requests.len(), 1);
}

#[tokio::test]
async fn durable_thread_identity_survives_unmaterialized_thread_list() {
    let fake = FakeTransport::default();
    let first_process =
        MatrixAppServerBridge::new(config(), fake.clone()).expect("first bridge process");
    let first = first_process
        .ensure_room_thread(&room_id())
        .await
        .expect("first process starts the thread");
    assert!(!first.recovered);
    drop(first_process);

    // Real App Server intentionally omits a new thread from thread/list until
    // the first queued user message materializes it in state.  Recovery must
    // use the exact durable ID instead of creating a replacement.
    fake.hide_threads_from_list(true);
    let restarted =
        MatrixAppServerBridge::new(config(), fake.clone()).expect("restarted bridge process");
    let recovered = restarted
        .reconcile_room_thread(&room_id(), &first.thread_id)
        .await
        .expect("durable thread reconciles before materialization");
    assert_eq!(recovered.thread_id, first.thread_id);
    assert!(recovered.recovered);
    assert_eq!(fake.snapshot().thread_start_calls, 1);
}

#[tokio::test]
async fn durable_thread_identity_rejects_a_different_materialized_thread() {
    let fake = FakeTransport::default();
    let first_process =
        MatrixAppServerBridge::new(config(), fake.clone()).expect("first bridge process");
    let first = first_process
        .ensure_room_thread(&room_id())
        .await
        .expect("first process starts the thread");

    let error = first_process
        .reconcile_room_thread(&room_id(), "different-durable-thread")
        .await
        .expect_err("materialized thread drift must fail closed");
    assert!(matches!(error, MatrixBridgeError::Protocol(_)));
    assert_eq!(fake.snapshot().thread_start_calls, 1);
    assert_ne!(first.thread_id, "different-durable-thread");
}

#[tokio::test]
async fn submission_uses_one_atomic_reconcile_rpc_and_revalidates_the_response() {
    let fake = FakeTransport::default();
    fake.script_reconcile(queued_reconcile_response(true));
    let bridge = MatrixAppServerBridge::new(config(), fake.clone()).expect("bridge");

    let submitted = bridge
        .submit_matrix_event(&room_id(), &event_id(), input())
        .await
        .expect("atomic admission");

    assert_eq!(
        submitted.state,
        MatrixSubmissionState::Queued {
            queued_submission_id: "queue-1".to_string(),
        }
    );
    let snapshot = fake.snapshot();
    assert_eq!(snapshot.reconcile_requests.len(), 1);
    let request = &snapshot.reconcile_requests[0];
    assert_eq!(request.client_user_message_id, matrix_client_id());
    assert_eq!(
        request.expected_payload_sha256,
        input_payload_sha256(&input())
    );
    assert_eq!(request.input, input());
    assert_eq!(request.mode, MatrixAdmissionMode::AllowIfAbsent);
}

#[tokio::test]
async fn queued_and_persisted_reconcile_outcomes_map_without_client_side_scans() {
    let fake = FakeTransport::default();
    fake.script_reconcile(queued_reconcile_response(false));
    fake.script_reconcile(persisted_reconcile_response("turn-1"));
    let bridge = MatrixAppServerBridge::new(config(), fake.clone()).expect("bridge");

    let queued = bridge
        .submit_matrix_event(&room_id(), &event_id(), input())
        .await
        .expect("existing queue binding");
    assert_eq!(
        queued.state,
        MatrixSubmissionState::ReconciledQueued {
            queued_submission_id: "queue-1".to_string(),
        }
    );
    let persisted = bridge
        .submit_matrix_event(&room_id(), &event_id(), input())
        .await
        .expect("persisted binding");
    assert_eq!(
        persisted.state,
        MatrixSubmissionState::ReconciledTurn {
            turn_id: "turn-1".to_string(),
        }
    );
    assert_eq!(fake.snapshot().reconcile_requests.len(), 2);
}

#[tokio::test]
async fn reconcile_only_is_forwarded_and_missing_or_cancelled_never_resurrects() {
    let fake = FakeTransport::default();
    let bridge = MatrixAppServerBridge::new(config(), fake.clone()).expect("bridge");
    let binding = bridge
        .ensure_room_thread(&room_id())
        .await
        .expect("binding");
    for outcome in [
        BridgeQueueReconcileOutcome::Missing,
        BridgeQueueReconcileOutcome::Cancelled,
    ] {
        fake.script_reconcile(BridgeQueueReconcileResponse {
            client_user_message_id: matrix_client_id(),
            payload_sha256: Some(input_payload_sha256(&input())),
            outcome,
        });
        let error = bridge
            .submit_matrix_event_on_binding(
                &room_id(),
                &event_id(),
                input(),
                &binding,
                MatrixAdmissionMode::ReconcileOnly,
            )
            .await
            .expect_err("durable absence must fail closed");
        assert!(error.to_string().contains("missing or cancelled"));
    }
    let snapshot = fake.snapshot();
    assert_eq!(snapshot.reconcile_requests.len(), 2);
    assert!(
        snapshot
            .reconcile_requests
            .iter()
            .all(|request| request.mode == MatrixAdmissionMode::ReconcileOnly)
    );
}

#[tokio::test]
async fn reconcile_response_identity_and_payload_drift_fail_closed() {
    let fake = FakeTransport::default();
    let bridge = MatrixAppServerBridge::new(config(), fake.clone()).expect("bridge");
    let mut wrong_client = queued_reconcile_response(true);
    wrong_client.client_user_message_id = "different-client".to_string();
    fake.script_reconcile(wrong_client);
    let error = bridge
        .submit_matrix_event(&room_id(), &event_id(), input())
        .await
        .expect_err("client identity drift");
    assert!(
        error
            .to_string()
            .contains("mismatched client message identity")
    );

    let mut wrong_digest = queued_reconcile_response(true);
    wrong_digest.payload_sha256 = Some(input_payload_sha256(&different_input()));
    fake.script_reconcile(wrong_digest);
    let error = bridge
        .submit_matrix_event(&room_id(), &event_id(), input())
        .await
        .expect_err("payload drift");
    assert!(error.to_string().contains("payload digest"));

    let mut missing_digest = queued_reconcile_response(true);
    missing_digest.payload_sha256 = None;
    fake.script_reconcile(missing_digest);
    let error = bridge
        .submit_matrix_event(&room_id(), &event_id(), input())
        .await
        .expect_err("missing payload digest");
    assert!(error.to_string().contains("no canonical payload digest"));
}

#[test]
fn remote_reconcile_mapping_preserves_all_typed_outcomes() {
    let payload_sha256 = input_payload_sha256(&input());
    for (mode, expected) in [
        (
            MatrixAdmissionMode::AllowIfAbsent,
            ThreadQueueReconcileMode::AllowIfAbsent,
        ),
        (
            MatrixAdmissionMode::ReconcileOnly,
            ThreadQueueReconcileMode::ReconcileOnly,
        ),
    ] {
        let params = bridge_queue_reconcile_params(BridgeQueueReconcile {
            thread_id: "thread-1".to_string(),
            input: input(),
            client_user_message_id: matrix_client_id(),
            expected_payload_sha256: payload_sha256.clone(),
            mode,
        });
        assert_eq!(params.mode, expected);
        assert_eq!(params.thread_id, "thread-1");
        assert_eq!(params.client_user_message_id, matrix_client_id());
        assert_eq!(params.expected_payload_sha256, payload_sha256);
    }
    let queued = bridge_queue_reconcile_response(ThreadQueueReconcileResponse {
        client_user_message_id: matrix_client_id(),
        payload_sha256: payload_sha256.clone(),
        outcome: ThreadQueueReconcileOutcome::Queued {
            queued_submission: QueuedSubmission {
                id: "queue-1".to_string(),
                input: input(),
                client_user_message_id: matrix_client_id(),
            },
            created: true,
        },
    })
    .expect("queued mapping");
    assert!(matches!(
        queued.outcome,
        BridgeQueueReconcileOutcome::Queued { created: true, .. }
    ));

    for outcome in [
        ThreadQueueReconcileOutcome::Persisted {
            turn_id: "turn-1".to_string(),
        },
        ThreadQueueReconcileOutcome::Missing,
        ThreadQueueReconcileOutcome::Cancelled,
    ] {
        bridge_queue_reconcile_response(ThreadQueueReconcileResponse {
            client_user_message_id: matrix_client_id(),
            payload_sha256: payload_sha256.clone(),
            outcome,
        })
        .expect("typed response mapping");
    }
}
