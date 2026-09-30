use super::*;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_matrix_protocol::PendingApproval;
use codex_hepta_matrix_store::MatrixDurableConfig;
use codex_hepta_matrix_store::PendingApprovalDraft;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;
use tempfile::TempDir;
use tokio::sync::Notify;

#[derive(Default)]
struct LifecycleTransport {
    effects: Mutex<Vec<&'static str>>,
    interrupt_entered: Notify,
    interrupt_released: Notify,
}

impl MatrixControlTransport for LifecycleTransport {
    fn interrupt_turn(&self, _thread_id: String, _turn_id: String) -> MatrixControlFuture<'_> {
        Box::pin(async move {
            self.effects.lock().await.push("interrupt");
            self.interrupt_entered.notify_one();
            self.interrupt_released.notified().await;
            Ok(())
        })
    }

    fn resolve_approval(
        &self,
        _request_id: RequestId,
        _request_kind: PendingApprovalKind,
        _decision: LocalApprovalDecision,
    ) -> MatrixControlFuture<'_> {
        Box::pin(async move {
            self.effects.lock().await.push("resolve");
            Ok(())
        })
    }
}

struct Fixture {
    _temp: TempDir,
    state: Arc<MatrixdControlState>,
    transport: Arc<LifecycleTransport>,
    socket: PathBuf,
}

impl Fixture {
    async fn new() -> anyhow::Result<Self> {
        let temp = tempfile::Builder::new()
            .prefix("hmx-lifecycle-")
            .tempdir_in("/tmp")?;
        let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
        let layout = HeptaFleetRoot::parse(temp.path().canonicalize()?)?
            .layout()
            .agent(&agent_id);
        let store = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
        store.record_turn_started("thread-1", "turn-1", 10).await?;
        store
            .store_pending_approval(&PendingApprovalDraft {
                approval: PendingApproval {
                    approval_key: "approval-1".to_string(),
                    kind: "command_execution".to_string(),
                    thread_id: "thread-1".to_string(),
                    turn_id: "turn-1".to_string(),
                    summary: "Command approval requested; action: cargo check".to_string(),
                    created_at_ms: 10,
                    allowed_decisions: vec![LocalApprovalDecision::Accept],
                },
                request_id_json: "17".to_string(),
                request_kind: PendingApprovalKind::CommandExecution,
                attached_agent_generation: 7,
                process_incarnation: "matrixd-1".to_string(),
            })
            .await?;
        let connections = Arc::new(MatrixdConnectionState::default());
        connections.set_agentd_connected(true);
        connections.set_matrix_sync_connected(true);
        let transport = Arc::new(LifecycleTransport::default());
        let state = Arc::new(MatrixdControlState::new(
            MatrixdControlIdentity {
                agent_id,
                release_id: "release-1".to_string(),
                fence: MatrixdFence {
                    binding_revision: 1,
                    binding_digest: Sha256Digest::parse("a".repeat(64))?,
                    attached_agent_generation: 7,
                    process_incarnation: "matrixd-1".to_string(),
                    plane_epoch: 1,
                },
                expected_mxid: MatrixUserId::parse("@agent:example.test")?,
                active_rooms: vec![MatrixRoomId::parse("!room:example.test")?],
            },
            store,
            transport.clone(),
            connections,
        )?);
        Ok(Self {
            _temp: temp,
            state,
            transport,
            socket: layout.matrixd_control_socket().to_path_buf(),
        })
    }

    fn request(&self, method: MatrixdMethod) -> MatrixdRequest {
        MatrixdRequest {
            schema_version: MATRIXD_CONTROL_SCHEMA_VERSION,
            request_id: 1,
            agent_id: self.state.identity.agent_id.clone(),
            fence: Some(self.state.identity.fence.clone()),
            method,
        }
    }
}

#[tokio::test]
async fn lifecycle_fence_and_dependency_loss_block_exact_fence_mutations() -> anyhow::Result<()> {
    for lifecycle in [
        MatrixdLifecycle::Fenced,
        MatrixdLifecycle::Draining,
        MatrixdLifecycle::Degraded,
    ] {
        let fixture = Fixture::new().await?;
        match lifecycle {
            MatrixdLifecycle::Fenced => fixture.state.connections.set_fenced(),
            MatrixdLifecycle::Draining => fixture.state.connections.set_draining(),
            MatrixdLifecycle::Degraded => {
                fixture.state.connections.set_agentd_connected(false);
            }
            MatrixdLifecycle::Ready => unreachable!(),
        }
        for method in [
            MatrixdMethod::CancelTurn {
                thread_id: "thread-1".to_string(),
                turn_id: "turn-1".to_string(),
            },
            MatrixdMethod::ResolveApproval {
                approval_key: "approval-1".to_string(),
                decision: LocalApprovalDecision::Accept,
            },
        ] {
            let response = fixture.state.response(fixture.request(method)).await;
            let expected_code = if lifecycle == MatrixdLifecycle::Degraded {
                "not_ready"
            } else {
                "fenced"
            };
            assert!(
                matches!(response.payload, MatrixdPayload::Error { ref code, .. } if code == expected_code)
            );
        }
        assert!(fixture.transport.effects.lock().await.is_empty());
        assert_eq!(
            fixture
                .state
                .store
                .pending_approval("approval-1")
                .await?
                .expect("pending approval")
                .resolution_decision,
            None
        );
    }
    Ok(())
}

#[tokio::test]
async fn queued_control_request_observes_fence_after_mutation_gate() -> anyhow::Result<()> {
    let fixture = Fixture::new().await?;
    let permit = fixture.state.mutation_gate.acquire().await?;
    let request = fixture.request(MatrixdMethod::ResolveApproval {
        approval_key: "approval-1".to_string(),
        decision: LocalApprovalDecision::Accept,
    });
    let operation = fixture.state.response(request);
    tokio::pin!(operation);
    assert!(
        std::future::poll_fn(|context| std::task::Poll::Ready(operation.as_mut().poll(context)))
            .await
            .is_pending()
    );
    fixture.state.connections.set_fenced();
    drop(permit);
    assert!(
        matches!(operation.await.payload, MatrixdPayload::Error { ref code, .. } if code == "fenced")
    );
    assert!(fixture.transport.effects.lock().await.is_empty());
    Ok(())
}

#[tokio::test]
async fn control_shutdown_joins_in_flight_connections() -> anyhow::Result<()> {
    let fixture = Fixture::new().await?;
    let cancellation = CancellationToken::new();
    let server = MatrixdControlServer::bind(
        fixture.socket.clone(),
        fixture.state.clone(),
        cancellation.clone(),
    )
    .await?;
    let task = tokio::spawn(server.run());
    let mut stream = UnixStream::connect(&fixture.socket).await?;
    let request = fixture.request(MatrixdMethod::CancelTurn {
        thread_id: "thread-1".to_string(),
        turn_id: "turn-1".to_string(),
    });
    let mut bytes = serde_json::to_vec(&request)?;
    bytes.push(b'\n');
    stream.write_all(&bytes).await?;
    timeout(
        Duration::from_secs(1),
        fixture.transport.interrupt_entered.notified(),
    )
    .await?;
    cancellation.cancel();
    timeout(Duration::from_secs(1), task).await???;
    let mut byte = [0];
    // Joining the listener alone must not leave a detached effect-bearing
    // connection alive until its unrelated I/O deadline expires.
    assert_eq!(
        timeout(Duration::from_secs(1), stream.read(&mut byte)).await??,
        0
    );
    Ok(())
}

#[tokio::test]
async fn socket_write_without_authoritative_ack_preserves_resolution_across_restart()
-> anyhow::Result<()> {
    let fixture = Fixture::new().await?;
    let response = fixture
        .state
        .response(fixture.request(MatrixdMethod::ResolveApproval {
            approval_key: "approval-1".to_string(),
            decision: LocalApprovalDecision::Accept,
        }))
        .await;
    assert!(matches!(response.payload, MatrixdPayload::Accepted));
    let resolving = fixture
        .state
        .store
        .pending_approval("approval-1")
        .await?
        .expect("resolving approval");
    assert_eq!(
        resolving.resolution_decision,
        Some(LocalApprovalDecision::Accept)
    );
    assert!(
        !fixture
            .state
            .store
            .read_control_events(0, 16)
            .await?
            .batch
            .events
            .iter()
            .any(|event| matches!(
                &event.kind,
                codex_hepta_matrix_protocol::MatrixdEventKind::ApprovalResolved { .. }
            ))
    );
    let layout = HeptaFleetRoot::parse(fixture._temp.path().canonicalize()?)?
        .layout()
        .agent(&fixture.state.identity.agent_id);
    fixture.state.store.close().await;
    let reopened = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    assert_eq!(
        reopened.pending_approval("approval-1").await?,
        Some(resolving)
    );
    // Only a matching owner/process/thread server observation settles the
    // durable decision; repeating that observation after receipt loss is safe.
    assert!(
        reopened
            .reconcile_server_request_resolved("17", "thread-1", 7, "matrixd-1", 30)
            .await?
            .is_some()
    );
    assert!(
        reopened
            .reconcile_server_request_resolved("17", "thread-1", 7, "matrixd-1", 31)
            .await?
            .is_none()
    );
    assert!(reopened.pending_approval("approval-1").await?.is_none());
    assert_eq!(reopened.read_control_events(0, 16).await?.batch.events.iter().filter(|event| matches!(&event.kind, codex_hepta_matrix_protocol::MatrixdEventKind::ApprovalResolved { approval_key } if approval_key == "approval-1")).count(), 1);
    Ok(())
}
