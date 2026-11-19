//! Actual original Agentd/App Server file callback and item readback through a
//! raw transport latency fixture. No callback, item or owner response is forged.
use super::*;
use codex_app_server_protocol::FileChangeApprovalDecision;
use codex_app_server_protocol::FileChangeRequestApprovalResponse;
use codex_app_server_protocol::TurnStartParams;
use codex_app_server_protocol::TurnStartResponse;
use codex_hepta_agentd::text_session::AgentdTextObservation;
use codex_hepta_agentd::text_session::TextApprovalObservation;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn slow_original_file_approval_preview_survives_repeated_select_cancellation() -> Result<()> {
    run_original_file_approval(/*exceed_preview_deadline*/ false).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn original_file_preview_total_deadline_keeps_callback_declineable() -> Result<()> {
    run_original_file_approval(/*exceed_preview_deadline*/ true).await
}

async fn run_original_file_approval(exceed_preview_deadline: bool) -> Result<()> {
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(AGENT_ID, "slow-original-file-approval")?;
    let marker = agent.workspace.join("declined-native-patch.txt");
    let patch = "*** Begin Patch\n*** Add File: declined-native-patch.txt\n+original proposed content\n*** End Patch\n";
    let model = app_test_support::create_mock_responses_server_sequence(vec![
        app_test_support::create_apply_patch_sse_response(patch, "slow-original-patch")?,
        app_test_support::create_final_assistant_message_sse_response("declined, no file change")?,
    ])
    .await;
    MockResponsesConfig::new(&model.uri())
        .with_approval_policy("on-request")
        .with_sandbox_mode("read-only")
        .write(agent.layout.home_root())?;
    fleet.start(&agent)?;
    let (control, _) = fleet.wait_ready(&agent, 1).await?;
    let ingress = control.session_ingress().await?;
    let client = connect_app_server_with_experimental(
        &ingress.socket_path,
        "slow-original-approval-test",
        64,
        true,
    )
    .await?;
    let mut request_id = 1;
    let thread = start_thread(&client, &mut request_id, &agent.workspace).await?;
    let view: ThreadReadResponse = client
        .request_typed(ClientRequest::ThreadRead {
            request_id: take_request_id(&mut request_id),
            params: ThreadReadParams {
                thread_id: thread.clone(),
                include_turns: false,
            },
        })
        .await?;
    // The fixture only delays the bytes of the exact original socket. The
    // already connected primary retains the same real thread and callback.
    let (reply_delay, preview_delay) = if exceed_preview_deadline {
        (Duration::ZERO, Duration::from_secs(6))
    } else {
        (Duration::from_millis(900), Duration::from_millis(900))
    };
    let delay = OriginalSocketDelay::start(&ingress.socket_path, reply_delay, preview_delay)?;
    let mut session = AgentdTextSession::connect(AgentdTextSessionConfig {
        control_socket: agent.layout.agentd_control_socket().to_path_buf(),
        agent_id: agent.agent_id.clone(),
        spawn_generation: 1,
        thread_id: thread.clone(),
        app_server_session_id: view.thread.session_id,
        codex_home: agent.layout.home_root().to_path_buf(),
    })
    .await?;
    delay.armed.store(true, Ordering::SeqCst);
    let began = tokio::time::Instant::now();
    let _: TurnStartResponse = client
        .request_typed(ClientRequest::TurnStart {
            request_id: take_request_id(&mut request_id),
            params: TurnStartParams {
                thread_id: thread.clone(),
                input: vec![UserInput::Text {
                    text: "review the original proposed patch".into(),
                    text_elements: Vec::new(),
                }],
                ..Default::default()
            },
        })
        .await?;
    let mut tick = tokio::time::interval(Duration::from_millis(250));
    tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    let mut ticks = 0;
    let pending = timeout(WAIT_TIMEOUT, async {
        loop {
            // This is the worker's actual cancellation pattern. Previously,
            // each tick dropped a callback already consumed from the socket.
            tokio::select! {
                _ = tick.tick() => { ticks += 1; },
                observation = session.events.next_observation() => {
                    if let AgentdTextObservation::Approval(TextApprovalObservation::Pending(approval)) = observation?.context("original stream ended")? {
                        break Ok::<_, anyhow::Error>(approval);
                    }
                }
            }
        }
    }).await??;
    ensure!(ticks >= 3);
    ensure!(
        delay.saw_item_page.load(Ordering::SeqCst),
        "no actual original item page crossed the delayed transport"
    );
    ensure!(pending.thread_id == thread && pending.item_id == "slow-original-patch");
    ensure!(pending.can_decline);
    if exceed_preview_deadline {
        ensure!(!pending.can_accept && pending.details.contains("total deadline"));
        ensure!(began.elapsed() >= Duration::from_secs(5));
        delay.armed.store(false, Ordering::SeqCst);
    } else {
        ensure!(pending.can_accept && pending.details.contains("original proposed content"));
        ensure!(delay.delayed_chunks.load(Ordering::SeqCst) >= 2);
    }
    ensure!(!marker.exists());
    // An explicit original test client declines; no synthetic human Root
    // permission or UI authorization is installed by this regression test.
    client
        .resolve_server_request(
            serde_json::from_str(&pending.id)?,
            serde_json::to_value(FileChangeRequestApprovalResponse {
                decision: FileChangeApprovalDecision::Decline,
            })?,
        )
        .await?;
    timeout(WAIT_TIMEOUT, async {
        let mut resolved = false;
        loop {
            tokio::select! {
                _ = tick.tick() => {},
                observation = session.events.next_observation() => match observation?.context("original stream ended")? {
                    AgentdTextObservation::Approval(TextApprovalObservation::Resolved { id, .. }) if id == pending.id => resolved = true,
                    AgentdTextObservation::Notification(event) if matches!(event.notification, ServerNotification::TurnCompleted(_)) => {
                        ensure!(resolved, "original turn completed without request-resolution observation"); break;
                    }
                    AgentdTextObservation::Approval(TextApprovalObservation::Pending(approval)) => {
                        anyhow::bail!("original callback was duplicated: {}", approval.id);
                    }
                    _ => {},
                }
            }
        }
        Ok::<_, anyhow::Error>(())
    }).await??;
    ensure!(!marker.exists() && physical_send_count(&model).await == 2);
    session.events.shutdown().await?;
    drop(delay);
    client.shutdown().await?;
    Ok(())
}

struct OriginalSocketDelay {
    path: PathBuf,
    original: PathBuf,
    task: tokio::task::JoinHandle<Result<()>>,
    armed: Arc<AtomicBool>,
    delayed_chunks: Arc<AtomicUsize>,
    saw_item_page: Arc<AtomicBool>,
}

impl OriginalSocketDelay {
    fn start(path: &Path, reply_delay: Duration, preview_delay: Duration) -> Result<Self> {
        let original = path.with_file_name("text-delay-original");
        let permissions = std::fs::metadata(path)?.permissions();
        std::fs::rename(path, &original)?;
        let listener = match tokio::net::UnixListener::bind(path) {
            Ok(listener) => listener,
            Err(error) => {
                let _ = std::fs::rename(&original, path);
                return Err(error.into());
            }
        };
        std::fs::set_permissions(path, permissions)?;
        let armed = Arc::new(AtomicBool::new(false));
        let delayed_chunks = Arc::new(AtomicUsize::new(0));
        let saw_item_page = Arc::new(AtomicBool::new(false));
        let (is_armed, count, item_page) =
            (armed.clone(), delayed_chunks.clone(), saw_item_page.clone());
        let target = original.clone();
        let task = tokio::spawn(async move {
            let (client, _) = listener.accept().await?;
            let server = tokio::net::UnixStream::connect(target).await?;
            let (mut client_read, mut client_write) = client.into_split();
            let (mut server_read, mut server_write) = server.into_split();
            let upload = async {
                tokio::io::copy(&mut client_read, &mut server_write).await?;
                server_write.shutdown().await?;
                Ok::<_, std::io::Error>(())
            };
            let download = async {
                let mut bytes = [0; 16 * 1024];
                let mut tail = Vec::new();
                loop {
                    let size = server_read.read(&mut bytes).await?;
                    if size == 0 {
                        client_write.shutdown().await?;
                        break;
                    }
                    if is_armed.load(Ordering::SeqCst) {
                        // Server WebSocket frames are unmasked. This bounded
                        // observation proves original item pages traversed the
                        // delayed path; it never changes a frame or response.
                        tail.extend_from_slice(&bytes[..size]);
                        let is_item_page = tail.windows(6).any(|part| part == b"\"data\"")
                            && tail.windows(8).any(|part| part == b"\"turnId\"");
                        if is_item_page {
                            item_page.store(true, Ordering::SeqCst);
                            tail.clear();
                        }
                        if tail.len() > 8192 {
                            tail.drain(..tail.len() - 8192);
                        }
                        tokio::time::sleep(if is_item_page {
                            preview_delay
                        } else {
                            reply_delay
                        })
                        .await;
                        count.fetch_add(1, Ordering::SeqCst);
                    }
                    client_write.write_all(&bytes[..size]).await?;
                }
                Ok::<_, std::io::Error>(())
            };
            tokio::try_join!(upload, download)?;
            Ok(())
        });
        Ok(Self {
            path: path.into(),
            original,
            task,
            armed,
            delayed_chunks,
            saw_item_page,
        })
    }
}

impl Drop for OriginalSocketDelay {
    fn drop(&mut self) {
        self.task.abort();
        let _ = std::fs::remove_file(&self.path);
        let _ = std::fs::rename(&self.original, &self.path);
    }
}
