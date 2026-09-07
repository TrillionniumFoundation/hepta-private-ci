#![cfg(unix)]

use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use anyhow::Context;
use anyhow::Result;
use anyhow::anyhow;
use anyhow::bail;
use anyhow::ensure;
use app_test_support::MockResponsesConfig;
use codex_app_server_client::AppServerEvent;
use codex_app_server_client::RemoteAppServerClient;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ServerNotification;
use codex_app_server_protocol::ThreadItem;
use codex_app_server_protocol::ThreadReadParams;
use codex_app_server_protocol::ThreadReadResponse;
use codex_app_server_protocol::ThreadStartParams;
use codex_app_server_protocol::ThreadStartResponse;
use codex_app_server_protocol::TurnStartParams;
use codex_app_server_protocol::TurnStartResponse;
use codex_app_server_protocol::TurnStatus;
use codex_app_server_protocol::UserInput as V2UserInput;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_agentd::MemoryFederationCapabilityState;
use codex_hepta_agentd::MemoryFederationScopeKind;
use codex_hepta_automation::AutomationSchedule;
use codex_hepta_automation::AutomationTaskDraft;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::ForgetMemoryDraft;
use codex_hepta_memory::H7TrajectoryEventKind;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::MemoryDraft;
use codex_hepta_memory::MemoryLifecycleState;
use codex_hepta_memory::MemoryRevisionDraft;
use codex_hepta_memory::MemoryVerification;
use codex_hepta_memory::SourceDraft;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use core_test_support::responses;
use core_test_support::responses::ResponseMock;
use core_test_support::responses::ResponsesRequest;
use serde_json::Value;
use serde_json::json;
use tokio::time::timeout;
use wiremock::Mock;
use wiremock::MockServer;
use wiremock::Request;
use wiremock::Respond;
use wiremock::ResponseTemplate;
use wiremock::matchers::method;
use wiremock::matchers::path;

mod support;

use support::fleet::AgentFixture;
use support::fleet::FleetHarness;
use support::fleet::connect_app_server;

const AGENT_A: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const AGENT_B: &str = "019153a4-3088-7e03-a56a-9b1964f75dd3";
const AGENT_C: &str = "019153a4-3088-7e03-a56a-9b1964f75dd4";
const AGENT_D: &str = "019153a4-3088-7e03-a56a-9b1964f75dd5";
const AGENT_E: &str = "019153a4-3088-7e03-a56a-9b1964f75dd6";
const COGNITIVE_NAMESPACE: &str = "hepta_cognitive";
const COGNITIVE_REFERENCE_OPEN: &str = "<hepta_memory_reference schema=\"1\">";
const COGNITIVE_REFERENCE_CLOSE: &str = "</hepta_memory_reference>";
const TURN_TIMEOUT: Duration = Duration::from_secs(20);
const STABLE_REQUEST_WINDOW: Duration = Duration::from_millis(500);

struct ProductClient {
    inner: RemoteAppServerClient,
    next_request_id: i64,
}

impl ProductClient {
    async fn connect(agent: &AgentFixture, control: &AgentdClient) -> Result<Self> {
        let ingress = control.session_ingress().await?;
        ensure!(
            ingress.socket_path == agent.layout.app_server_socket(),
            "control plane returned the wrong App Server socket"
        );
        let inner =
            connect_app_server(&ingress.socket_path, "hepta-cognitive-product-e2e", 256).await?;
        let codex_home = inner
            .codex_home()
            .context("App Server initialize response omitted product home")?;
        let expected_home = agent.layout.home_root().to_string_lossy();
        ensure!(
            codex_home == expected_home.as_ref(),
            "App Server initialized against the wrong product home"
        );
        Ok(Self {
            inner,
            next_request_id: 1,
        })
    }

    fn request_id(&mut self) -> RequestId {
        let request_id = self.next_request_id;
        self.next_request_id += 1;
        RequestId::Integer(request_id)
    }

    async fn start_thread(&mut self, workspace: &Path) -> Result<String> {
        self.start_thread_with_ephemeral(workspace, true).await
    }

    async fn start_thread_with_ephemeral(
        &mut self,
        workspace: &Path,
        ephemeral: bool,
    ) -> Result<String> {
        let request_id = self.request_id();
        let response: ThreadStartResponse = self
            .inner
            .request_typed(ClientRequest::ThreadStart {
                request_id,
                params: ThreadStartParams {
                    cwd: Some(workspace.to_string_lossy().into_owned()),
                    ephemeral: Some(ephemeral),
                    ..ThreadStartParams::default()
                },
            })
            .await?;
        ensure!(
            response.cwd.as_path() == workspace,
            "thread started in the wrong workspace"
        );
        Ok(response.thread.id)
    }

    /// Start a thread while asserting the provider/model selected by the
    /// app-server.  The external-provider smoke must not pass merely because
    /// a fallback model (or a different provider) completed the turn.
    async fn start_thread_with_expected_provider(
        &mut self,
        workspace: &Path,
        expected_model: &str,
        expected_provider: &str,
    ) -> Result<String> {
        let request_id = self.request_id();
        let response: ThreadStartResponse = self
            .inner
            .request_typed(ClientRequest::ThreadStart {
                request_id,
                params: ThreadStartParams {
                    model: Some(expected_model.to_string()),
                    model_provider: Some(expected_provider.to_string()),
                    cwd: Some(workspace.to_string_lossy().into_owned()),
                    // The surrounding FleetHarness home is temporary, but a
                    // non-ephemeral thread is required so the read-only gate
                    // can inspect persisted items after turn completion.
                    ephemeral: Some(false),
                    ..ThreadStartParams::default()
                },
            })
            .await?;
        ensure!(
            response.model == expected_model,
            "app-server selected unexpected model: expected {expected_model}, got {}",
            response.model
        );
        ensure!(
            response.model_provider == expected_provider,
            "app-server selected unexpected provider: expected {expected_provider}, got {}",
            response.model_provider
        );
        ensure!(
            response.cwd.as_path() == workspace,
            "thread started in the wrong workspace"
        );
        Ok(response.thread.id)
    }

    async fn read_thread(&mut self, thread_id: &str) -> Result<ThreadReadResponse> {
        let request_id = self.request_id();
        self.inner
            .request_typed(ClientRequest::ThreadRead {
                request_id,
                params: ThreadReadParams {
                    thread_id: thread_id.to_string(),
                    include_turns: true,
                },
            })
            .await
            .map_err(Into::into)
    }

    async fn run_turn(&mut self, thread_id: &str, text: &str) -> Result<String> {
        self.run_turn_with_timeout(thread_id, text, TURN_TIMEOUT)
            .await
    }

    async fn run_turn_with_timeout(
        &mut self,
        thread_id: &str,
        text: &str,
        turn_timeout: Duration,
    ) -> Result<String> {
        let request_id = self.request_id();
        // The qualification writer is intentionally inert without a durable
        // client admission key.  Product E2E supplies one per user message so
        // the test exercises the same stable logical-turn path as App Server
        // clients instead of silently falling back to legacy turn IDs.
        let client_user_message_id = format!("qualification-e2e-message:{request_id:?}");
        let response: TurnStartResponse = self
            .inner
            .request_typed(ClientRequest::TurnStart {
                request_id,
                params: TurnStartParams {
                    thread_id: thread_id.to_string(),
                    client_user_message_id: Some(client_user_message_id),
                    input: vec![V2UserInput::Text {
                        text: text.to_string(),
                        text_elements: Vec::new(),
                    }],
                    ..TurnStartParams::default()
                },
            })
            .await?;
        let turn_id = response.turn.id;
        self.wait_for_turn_with_timeout(thread_id, &turn_id, turn_timeout)
            .await?;
        Ok(turn_id)
    }

    async fn wait_for_turn_with_timeout(
        &mut self,
        thread_id: &str,
        turn_id: &str,
        turn_timeout: Duration,
    ) -> Result<()> {
        timeout(turn_timeout, async {
            loop {
                let event = self
                    .inner
                    .next_event()
                    .await
                    .context("App Server event stream closed before turn/completed")?;
                if let AppServerEvent::ServerNotification(notification) = event
                    && let ServerNotification::TurnCompleted(completed) = notification.as_ref()
                    && completed.thread_id == thread_id
                    && completed.turn.id == turn_id
                {
                    ensure!(
                        completed.turn.status == TurnStatus::Completed,
                        "turn ended with {:#?}",
                        completed.turn
                    );
                    return Ok::<(), anyhow::Error>(());
                }
            }
        })
        .await
        .context("timed out waiting for turn/completed")??;
        Ok(())
    }

    async fn shutdown(self) -> Result<()> {
        self.inner.shutdown().await?;
        Ok(())
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[cfg_attr(
    not(feature = "qualification-cognitive-write"),
    ignore = "requires the explicit qualification-cognitive-write profile; local-development keeps remember/correct/forget disabled"
)]
async fn real_agentd_remember_recall_correct_and_forget_revalidate_physical_sends() -> Result<()> {
    const ORIGINAL: &str = "Project Aurora deadline is Friday.";
    const CORRECTED: &str = "Project Aurora deadline is Monday.";
    const FORGET_REASON: &str = "Project Aurora deadline memory should be forgotten.";
    const ORIGINAL_ALIAS: &str = "Luminous Initiative";
    const CORRECTED_ALIAS: &str = "Radiant Initiative";
    const SUPERSEDED_ALIAS_QUERY: &str = "Luminous";
    const REMEMBER_CALL: &str = "remember-aurora";
    const CORRECT_CALL: &str = "correct-aurora";
    const FORGET_CALL: &str = "forget-aurora";

    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(AGENT_A, "workspace-a")?;
    let model = responses::start_mock_server().await;
    MockResponsesConfig::new(&model.uri()).write(agent.layout.home_root())?;
    fleet.start(&agent)?;
    let (control, initial_health) = fleet.wait_ready(&agent, 1).await?;
    let mut product = ProductClient::connect(&agent, &control).await?;

    let thread_a = product.start_thread(&agent.workspace).await?;
    let remember = responses::mount_sse_sequence(
        &model,
        vec![
            tool_sse(
                "remember-response",
                REMEMBER_CALL,
                "remember",
                json!({
                    "stable_key": "project-aurora-deadline",
                    "content": ORIGINAL,
                    "scope": "workspace_private",
                    "kg": project_deadline_facts(ORIGINAL_ALIAS, "Friday")
                }),
            ),
            final_sse("remember-final"),
        ],
    )
    .await;
    let remember_turn_id = product.run_turn(&thread_a, ORIGINAL).await?;
    assert_physical_request_count_stable(&remember, 2, "remember").await?;
    let remember_requests = remember.requests();
    let remember_tool = remember_requests[0]
        .tool_by_name(COGNITIVE_NAMESPACE, "remember")
        .context("the real ToolRegistry did not advertise cognitive remember")?;
    ensure!(
        remember_tool["parameters"]["properties"]["kg"]["properties"]["entities"]["type"]
            == "array"
            && remember_tool["parameters"]["properties"]["kg"]["properties"]["relations"]["type"]
                == "array",
        "the physical ToolRegistry schema omitted structured cognitive KG facts"
    );
    assert_no_cognitive_reference(&remember_requests[0])?;
    assert_no_cognitive_reference(&remember_requests[1])?;
    let remembered = tool_output(&remember, REMEMBER_CALL)?;
    ensure!(remembered["schema_version"] == 2);
    ensure!(remembered["operation"] == "remembered");
    ensure!(remembered["memory"]["revision"] == 1);
    ensure!(remembered["memory"]["verification"] == "verified");
    ensure!(remembered["memory"]["lifecycle"]["state"] == "active");
    let memory_id = remembered["memory"]["memory_id"]
        .as_str()
        .context("remember output omitted memory_id")?
        .to_string();
    let remember_source_id = remembered["source"]["source_id"]
        .as_str()
        .context("remember output omitted source_id")?
        .to_string();
    ensure!(remembered["source"]["revision"] == 1);
    let remember_projection = assert_projection_receipt(&remembered, 1, 3, 2, 1, 2, 1)?;

    product.shutdown().await?;
    fleet.supervisor.kill(&agent.agent_id)?;
    wait_inactive(&mut fleet, &agent.agent_id).await?;
    let trajectory_store = CognitiveStore::open(&agent.layout).await?;
    let remember_trajectory =
        read_h7_trajectory_for_turn(&trajectory_store, &agent, &remember_turn_id)
            .await?
            .context("qualification turn did not leave an H7 trajectory")?;
    ensure!(
        remember_trajectory.events.len() == 2,
        "qualification turn trajectory was not start+terminal: {:?}",
        remember_trajectory.events
    );
    ensure!(
        remember_trajectory.events[0].event_kind == H7TrajectoryEventKind::TurnStart
            && remember_trajectory.events[1].event_kind == H7TrajectoryEventKind::Terminal
            && remember_trajectory.events[0].causal_parent_seq.is_none()
            && remember_trajectory.events[1].causal_parent_seq == Some(1)
            && remember_trajectory.events[1].causal_parent_sha256.is_some()
            && remember_trajectory
                .events
                .iter()
                .all(|event| !event.external_effect_executed
                    && !event.kg_write_authority
                    && !event.production_caller),
        "qualification H7 trajectory violated its local observation-only boundary"
    );
    let before_restart =
        read_kg_sqlite_evidence(&agent, &memory_id, 1, &remember_source_id).await?;
    ensure!(before_restart.generation == 1);
    ensure!(before_restart.fact_count == 3);
    ensure!(before_restart.entity_count == 2);
    ensure!(before_restart.relation_count == 1);
    ensure!(before_restart.node_count == 2);
    ensure!(before_restart.edge_count == 1);
    ensure!(
        before_restart.fact_set_sha256 == remember_projection.fact_set_sha256
            && before_restart.input_heads_sha256 == remember_projection.input_heads_sha256
            && before_restart.output_sha256 == remember_projection.output_sha256,
        "physical remember output did not bind the persisted KG receipt digests"
    );

    fleet.supervisor.restart(&agent.agent_id, Instant::now())?;
    let restarted_generation = agent_generation(&fleet, &agent.agent_id)?;
    ensure!(restarted_generation > 1, "Agent generation did not advance");
    let restarted_control = fleet.control_client(&agent, restarted_generation)?;
    let restarted_health = fleet
        .wait_until_ready(&agent.agent_id, &restarted_control)
        .await?;
    ensure!(
        restarted_health.process_id != initial_health.process_id,
        "Agentd restart reused the original process"
    );
    let after_restart = read_kg_sqlite_evidence(&agent, &memory_id, 1, &remember_source_id).await?;
    ensure!(
        after_restart == before_restart,
        "immutable facts or the current KG receipt drifted across Agentd restart"
    );

    let mut product = ProductClient::connect(&agent, &restarted_control).await?;
    let thread_b = product.start_thread(&agent.workspace).await?;
    ensure!(
        !ORIGINAL.contains(ORIGINAL_ALIAS),
        "KG alias accidentally appeared in memory content"
    );
    let after_restart_recall =
        responses::mount_sse_sequence(&model, vec![final_sse("after-restart-recall-final")]).await;
    product.run_turn(&thread_b, ORIGINAL_ALIAS).await?;
    assert_physical_request_count_stable(&after_restart_recall, 1, "post-restart KG recall")
        .await?;
    let after_restart_request = after_restart_recall.single_request();
    assert_single_memory_reference_with_channels(
        &after_restart_request,
        &memory_id,
        1,
        ORIGINAL,
        &["entity_fts", "graph_one_hop", "recency"],
    )?;
    assert_memory_source(&after_restart_request, &memory_id, &remember_source_id)?;

    let correct = responses::mount_sse_sequence(
        &model,
        vec![
            tool_sse(
                "correct-response",
                CORRECT_CALL,
                "correct",
                json!({
                    "memory_id": memory_id,
                    "expected_revision": 1,
                    "content": CORRECTED,
                    "kg": project_deadline_facts(CORRECTED_ALIAS, "Monday")
                }),
            ),
            final_sse("correct-final"),
        ],
    )
    .await;
    product.run_turn(&thread_b, CORRECTED).await?;
    assert_physical_request_count_stable(&correct, 2, "correct").await?;
    let correct_requests = correct.requests();
    assert_single_memory_reference(&correct_requests[0], &memory_id, 1, ORIGINAL)?;
    assert_no_cognitive_reference(&correct_requests[1])?;
    let corrected = tool_output(&correct, CORRECT_CALL)?;
    ensure!(corrected["operation"] == "corrected");
    ensure!(corrected["memory"]["revision"] == 2);
    let corrected_source_id = corrected["source"]["source_id"]
        .as_str()
        .context("correct output omitted source_id")?
        .to_string();
    ensure!(corrected["source"]["revision"] == 1);
    let corrected_projection = assert_projection_receipt(&corrected, 2, 3, 2, 1, 2, 1)?;
    ensure!(
        read_kg_sqlite_evidence(&agent, &memory_id, 2, &corrected_source_id).await?
            == corrected_projection,
        "correction tool output did not match the current persisted KG receipt"
    );

    let old_alias = responses::mount_sse_sequence(&model, vec![final_sse("old-alias-final")]).await;
    product.run_turn(&thread_b, SUPERSEDED_ALIAS_QUERY).await?;
    assert_physical_request_count_stable(&old_alias, 1, "superseded alias lookup").await?;
    let old_alias_request = old_alias.single_request();
    assert_single_memory_reference_with_channels(
        &old_alias_request,
        &memory_id,
        2,
        CORRECTED,
        &["recency"],
    )?;
    ensure!(
        !attachment_text(&old_alias_request)?.contains(ORIGINAL),
        "superseded content reached a later physical send"
    );

    ensure!(
        !CORRECTED.contains(CORRECTED_ALIAS),
        "corrected KG alias accidentally appeared in memory content"
    );
    let new_alias = responses::mount_sse_sequence(&model, vec![final_sse("new-alias-final")]).await;
    product.run_turn(&thread_b, CORRECTED_ALIAS).await?;
    assert_physical_request_count_stable(&new_alias, 1, "corrected alias lookup").await?;
    let new_alias_request = new_alias.single_request();
    assert_single_memory_reference_with_channels(
        &new_alias_request,
        &memory_id,
        2,
        CORRECTED,
        &["entity_fts", "graph_one_hop", "recency"],
    )?;
    assert_memory_source(&new_alias_request, &memory_id, &corrected_source_id)?;

    let forget = responses::mount_sse_sequence(
        &model,
        vec![
            tool_sse(
                "forget-response",
                FORGET_CALL,
                "forget",
                json!({
                    "memory_id": memory_id,
                    "expected_revision": 2,
                    "reason": FORGET_REASON
                }),
            ),
            final_sse("forget-final"),
        ],
    )
    .await;
    product.run_turn(&thread_b, FORGET_REASON).await?;
    assert_physical_request_count_stable(&forget, 2, "forget").await?;
    let forget_requests = forget.requests();
    assert_single_memory_reference(&forget_requests[0], &memory_id, 2, CORRECTED)?;
    assert_no_cognitive_reference(&forget_requests[1])?;
    let forgotten = tool_output(&forget, FORGET_CALL)?;
    ensure!(forgotten["operation"] == "forgotten");
    ensure!(forgotten["memory"]["revision"] == 3);
    ensure!(forgotten["memory"]["lifecycle"]["state"] == "tombstoned");
    let forgotten_source_id = forgotten["source"]["source_id"]
        .as_str()
        .context("forget output omitted source_id")?;
    ensure!(forgotten["source"]["revision"] == 1);
    let forgotten_projection = assert_projection_receipt(&forgotten, 3, 0, 0, 0, 0, 0)?;
    ensure!(
        read_kg_sqlite_evidence(&agent, &memory_id, 3, forgotten_source_id).await?
            == forgotten_projection,
        "forget tool output did not match the current persisted empty KG projection"
    );

    let after_forget =
        responses::mount_sse_sequence(&model, vec![final_sse("after-forget-final")]).await;
    product.run_turn(&thread_b, CORRECTED_ALIAS).await?;
    assert_physical_request_count_stable(&after_forget, 1, "post-forget lookup").await?;
    assert_no_cognitive_reference(&after_forget.single_request())?;

    product.shutdown().await?;
    Ok(())
}

/// The local-development profile's first product slice is deliberately
/// read-only: verified memory is prepared by the host, while the live Agent
/// may only recall and explain it.  This is the real-process equivalent of
/// memory-review and must remain usable without granting KG write authority.
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[cfg_attr(
    feature = "qualification-cognitive-write",
    ignore = "qualification profile runs the separate bounded cognitive-write E2E"
)]
async fn real_agentd_local_memory_review_is_read_only_and_replayable() -> Result<()> {
    const MEMORY: &str = "Local memory-review checkpoint is green.";
    const QUERY: &str = "memory-review checkpoint";

    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(AGENT_A, "workspace-local-memory-review")?;
    let model = responses::start_mock_server().await;
    MockResponsesConfig::new(&model.uri()).write(agent.layout.home_root())?;
    let (memory_id, source_id, _) =
        seed_verified_agent_memory_with_receipt(&agent, "local-memory-review", MEMORY).await?;

    fleet.start(&agent)?;
    let (control, initial_health) = fleet.wait_ready(&agent, 1).await?;
    let mut product = ProductClient::connect(&agent, &control).await?;
    let thread = product
        .start_thread_with_ephemeral(&agent.workspace, false)
        .await?;

    let first = responses::mount_sse_once(
        &model,
        final_sse_with_citation(
            "local-memory-review-first",
            &format!("hepta-memory/{source_id}"),
        ),
    )
    .await;
    product.run_turn(&thread, QUERY).await?;
    assert_physical_request_count_stable(&first, 1, "local memory-review").await?;
    assert_thread_read_contains_cited_answer(
        &product.read_thread(&thread).await?,
        &format!("hepta-memory/{source_id}"),
    )?;
    let first_request = first.single_request();
    for operation in ["remember", "correct", "forget"] {
        ensure!(
            first_request
                .tool_by_name(COGNITIVE_NAMESPACE, operation)
                .is_none(),
            "local-development ToolRegistry exposed write tool {operation}"
        );
    }
    for operation in ["recall", "explain"] {
        ensure!(
            first_request
                .tool_by_name(COGNITIVE_NAMESPACE, operation)
                .is_some(),
            "local-development ToolRegistry omitted read tool {operation}"
        );
    }
    assert_single_memory_reference_with_channels(
        &first_request,
        &memory_id,
        1,
        MEMORY,
        &["memory_fts", "recency"],
    )?;
    assert_memory_source(&first_request, &memory_id, &source_id)?;

    product.shutdown().await?;
    fleet.supervisor.kill(&agent.agent_id)?;
    wait_inactive(&mut fleet, &agent.agent_id).await?;
    fleet.supervisor.restart(&agent.agent_id, Instant::now())?;
    let restarted_generation = agent_generation(&fleet, &agent.agent_id)?;
    ensure!(
        restarted_generation > 1,
        "Agentd restart did not advance the generation"
    );
    let restarted_control = fleet.control_client(&agent, restarted_generation)?;
    let restarted_health = fleet
        .wait_until_ready(&agent.agent_id, &restarted_control)
        .await?;
    ensure!(
        restarted_health.process_id != initial_health.process_id,
        "Agentd restart reused the original process"
    );
    let mut restarted_product = ProductClient::connect(&agent, &restarted_control).await?;
    let restarted_thread = restarted_product
        .start_thread_with_ephemeral(&agent.workspace, false)
        .await?;
    let second = responses::mount_sse_once(
        &model,
        final_sse_with_citation(
            "local-memory-review-replay",
            &format!("hepta-memory/{source_id}"),
        ),
    )
    .await;
    restarted_product.run_turn(&restarted_thread, QUERY).await?;
    assert_physical_request_count_stable(&second, 1, "local memory-review replay").await?;
    assert_thread_read_contains_cited_answer(
        &restarted_product.read_thread(&restarted_thread).await?,
        &format!("hepta-memory/{source_id}"),
    )?;
    let second_request = second.single_request();
    assert_single_memory_reference_with_channels(
        &second_request,
        &memory_id,
        1,
        MEMORY,
        &["memory_fts", "recency"],
    )?;
    assert_memory_source(&second_request, &memory_id, &source_id)?;
    restarted_product.shutdown().await?;
    Ok(())
}

/// A host-owned tombstone must become visible to the real read-only product
/// without granting the live Agent any cognitive write tool.  This closes the
/// semantic gap between a store-level forget regression and the process path
/// that actually builds the next provider request, and verifies that the
/// tombstone survives an Agentd reopen.
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[cfg_attr(
    feature = "qualification-cognitive-write",
    ignore = "qualification profile runs the separate bounded cognitive-write E2E"
)]
async fn real_agentd_local_memory_review_hides_host_tombstone_after_reopen() -> Result<()> {
    const MEMORY: &str = "Host-owned tombstone checkpoint is visible only before withdrawal.";
    const QUERY: &str = "host-owned tombstone checkpoint";
    const FORGET_REASON: &str = "host-owned semantic tombstone regression";

    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(AGENT_A, "workspace-local-memory-tombstone")?;
    let model = responses::start_mock_server().await;
    MockResponsesConfig::new(&model.uri()).write(agent.layout.home_root())?;
    let (memory_id, source_id, source_citation) =
        seed_verified_agent_memory_with_receipt(&agent, "local-memory-tombstone", MEMORY).await?;

    fleet.start(&agent)?;
    let (control, _) = fleet.wait_ready(&agent, 1).await?;
    let mut product = ProductClient::connect(&agent, &control).await?;
    let thread = product
        .start_thread_with_ephemeral(&agent.workspace, false)
        .await?;

    let before = responses::mount_sse_once(
        &model,
        final_sse_with_citation(
            "local-memory-tombstone-before",
            &format!("hepta-memory/{source_id}"),
        ),
    )
    .await;
    product.run_turn(&thread, QUERY).await?;
    assert_physical_request_count_stable(&before, 1, "pre-tombstone memory-review").await?;
    assert_thread_read_contains_cited_answer(
        &product.read_thread(&thread).await?,
        &format!("hepta-memory/{source_id}"),
    )?;
    let before_request = before.single_request();
    assert_single_memory_reference_with_channels(
        &before_request,
        &memory_id,
        1,
        MEMORY,
        &["memory_fts", "recency"],
    )?;
    assert_memory_source(&before_request, &memory_id, &source_id)?;
    for operation in ["remember", "correct", "forget"] {
        ensure!(
            before_request
                .tool_by_name(COGNITIVE_NAMESPACE, operation)
                .is_none(),
            "read-only memory-review exposed write tool {operation}"
        );
    }

    // The host owns this bounded qualification mutation.  It is deliberately
    // outside the Agent turn and uses the existing CAS/tombstone API; no live
    // writer capability, provider effect, or production authority is enabled.
    let store = CognitiveStore::open(&agent.layout).await?;
    let forgotten = store
        .forget_memory(
            &CognitiveAccess::agent_private(agent.agent_id.clone()),
            &codex_hepta_memory::StableMemoryId::parse(memory_id.clone())
                .map_err(anyhow::Error::msg)?,
            1,
            &ForgetMemoryDraft {
                scope: CognitiveScope::AgentPrivate,
                reason: FORGET_REASON.to_string(),
                valid_from_unix_seconds: i64::try_from(
                    SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs(),
                )?,
                citations: vec![source_citation],
            },
        )
        .await?;
    ensure!(
        forgotten.id.revision == 2,
        "host tombstone did not advance revision"
    );
    ensure!(
        matches!(forgotten.lifecycle, MemoryLifecycleState::Tombstoned { .. }),
        "host forget did not append a tombstoned revision"
    );

    let after = responses::mount_sse_once(&model, final_sse("local-memory-tombstone-after")).await;
    product.run_turn(&thread, QUERY).await?;
    assert_physical_request_count_stable(&after, 1, "post-tombstone memory-review").await?;
    assert_no_cognitive_reference(&after.single_request())?;
    product.shutdown().await?;

    fleet.supervisor.kill(&agent.agent_id)?;
    wait_inactive(&mut fleet, &agent.agent_id).await?;
    fleet.supervisor.restart(&agent.agent_id, Instant::now())?;
    let generation = agent_generation(&fleet, &agent.agent_id)?;
    ensure!(generation > 1, "Agentd reopen did not advance generation");
    let restarted_control = fleet.control_client(&agent, generation)?;
    fleet
        .wait_until_ready(&agent.agent_id, &restarted_control)
        .await?;
    let mut restarted_product = ProductClient::connect(&agent, &restarted_control).await?;
    let restarted_thread = restarted_product
        .start_thread_with_ephemeral(&agent.workspace, false)
        .await?;
    let after_reopen =
        responses::mount_sse_once(&model, final_sse("local-memory-tombstone-after-reopen")).await;
    restarted_product.run_turn(&restarted_thread, QUERY).await?;
    assert_physical_request_count_stable(&after_reopen, 1, "post-reopen tombstone memory-review")
        .await?;
    assert_no_cognitive_reference(&after_reopen.single_request())?;
    restarted_product.shutdown().await?;
    Ok(())
}

/// Opt-in smoke for a real local model process.  The provider URL is accepted
/// only when it is loopback, and the test always uses a fresh temporary fleet
/// home.  This deliberately verifies provider/app-server/lifecycle wiring, not
/// production effects or an external provider contract.
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "set HEPTA_LOCAL_PROVIDER_BASE_URL and HEPTA_LOCAL_PROVIDER_MODEL for a loopback model smoke"]
async fn real_agentd_loopback_provider_read_only_smoke() -> Result<()> {
    let provider_base_url = std::env::var("HEPTA_LOCAL_PROVIDER_BASE_URL")
        .context("HEPTA_LOCAL_PROVIDER_BASE_URL is required for this ignored smoke")?;
    let model_id = std::env::var("HEPTA_LOCAL_PROVIDER_MODEL")
        .context("HEPTA_LOCAL_PROVIDER_MODEL is required for this ignored smoke")?;
    ensure!(
        provider_base_url.starts_with("http://127.0.0.1:")
            || provider_base_url.starts_with("http://localhost:"),
        "loopback provider smoke refuses non-local URL: {provider_base_url}"
    );
    ensure!(
        !model_id.trim().is_empty(),
        "loopback provider model must not be empty"
    );

    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(AGENT_A, "workspace-loopback-provider")?;
    MockResponsesConfig::new("http://127.0.0.1:1")
        .with_model_provider("local_mlx")
        .with_provider_name("Local MLX qualification provider")
        .with_provider_base_url(&provider_base_url)
        .with_model(&model_id)
        .with_provider_config("supports_websockets = false")
        .with_root_config("model_reasoning_effort = \"minimal\"")
        .write(agent.layout.home_root())?;

    fleet.start(&agent)?;
    let (control, _health) = fleet.wait_ready(&agent, 1).await?;
    let mut product = ProductClient::connect(&agent, &control).await?;
    let thread = product.start_thread(&agent.workspace).await?;
    product
        .run_turn(
            &thread,
            "Reply with exactly READY. Do not call tools or access external resources.",
        )
        .await?;
    product.shutdown().await?;
    Ok(())
}

/// Opt-in smoke for the real first-party ChatGPT provider.  This test is
/// intentionally ignored by default and requires an explicit auth.json path;
/// the credential is copied only into the ephemeral Agent home created by the
/// FleetHarness and is never included in a receipt or repository artifact.
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "set HEPTA_EXTERNAL_CODEX_AUTH_JSON to run the bounded GPT-5.3 Spark provider smoke"]
async fn real_agentd_external_gpt53_spark_read_only_smoke() -> Result<()> {
    const MODEL_ID: &str = "gpt-5.3-codex-spark";
    const CHATGPT_CODEX_BASE_URL: &str = "https://chatgpt.com/backend-api/codex";
    const CHATGPT_BASE_URL: &str = "https://chatgpt.com/backend-api";

    let auth_source = std::env::var("HEPTA_EXTERNAL_CODEX_AUTH_JSON")
        .context("HEPTA_EXTERNAL_CODEX_AUTH_JSON is required for this ignored smoke")?;
    let model_id =
        std::env::var("HEPTA_EXTERNAL_PROVIDER_MODEL").unwrap_or_else(|_| MODEL_ID.to_string());
    ensure!(
        model_id == MODEL_ID,
        "external provider smoke is pinned to {MODEL_ID}, got {model_id}"
    );
    let auth_source = Path::new(&auth_source);
    ensure!(
        auth_source.is_file(),
        "external provider auth source is not a regular file"
    );

    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(AGENT_A, "workspace-external-gpt53-spark")?;
    let auth_target = agent.layout.home_root().join("auth.json");
    std::fs::copy(auth_source, &auth_target)
        .context("copying explicitly supplied ChatGPT auth into ephemeral Agent home")?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut permissions = std::fs::metadata(&auth_target)?.permissions();
        permissions.set_mode(0o600);
        std::fs::set_permissions(&auth_target, permissions)?;
    }

    MockResponsesConfig::new("http://127.0.0.1:1")
        .with_model_provider("openai_external")
        .with_provider_name("OpenAI")
        .with_provider_base_url(CHATGPT_CODEX_BASE_URL)
        .with_model(MODEL_ID)
        .with_provider_config("requires_openai_auth = true")
        .with_provider_config("supports_websockets = false")
        .with_root_config(&format!(
            "chatgpt_base_url = \"{CHATGPT_BASE_URL}\"\nmodel_reasoning_effort = \"low\"\nweb_search = \"disabled\""
        ))
        .write(agent.layout.home_root())?;

    fleet.start(&agent)?;
    let (control, _health) = fleet.wait_ready(&agent, 1).await?;
    let mut product = ProductClient::connect(&agent, &control).await?;
    let thread = product
        .start_thread_with_expected_provider(&agent.workspace, MODEL_ID, "openai_external")
        .await?;
    let turn_id = product
        .run_turn_with_timeout(
            &thread,
            "Reply with exactly READY. Do not call tools, access memory, or cause any external effect.",
            Duration::from_secs(90),
        )
        .await?;
    let thread_read = product.read_thread(&thread).await?;
    assert_external_read_only_turn(&thread_read, &turn_id, "READY")?;
    product.shutdown().await?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[cfg_attr(
    not(feature = "qualification-cognitive-write"),
    ignore = "requires the explicit qualification-cognitive-write profile; default/local binary keeps cognitive writes disabled"
)]
async fn two_real_agentd_app_servers_never_cross_recall() -> Result<()> {
    const MEMORY_A: &str = "Agent Alpha project milestone is Tuesday.";
    const MEMORY_B: &str = "Agent Beta project milestone is Thursday.";
    const ALIAS_A: &str = "Crimson Cedar Initiative";
    const ALIAS_B: &str = "Cobalt Ocean Initiative";
    const CROSS_ALIAS_A_QUERY: &str = "Crimson Cedar";
    const CROSS_ALIAS_B_QUERY: &str = "Cobalt Ocean";
    const REMEMBER_A_CALL: &str = "remember-agent-alpha";
    const REMEMBER_B_CALL: &str = "remember-agent-beta";

    let mut fleet = FleetHarness::new()?;
    let agent_a = fleet.register(AGENT_A, "workspace-a")?;
    let agent_b = fleet.register(AGENT_B, "workspace-b")?;
    let model_a = responses::start_mock_server().await;
    let model_b = responses::start_mock_server().await;
    MockResponsesConfig::new(&model_a.uri()).write(agent_a.layout.home_root())?;
    MockResponsesConfig::new(&model_b.uri()).write(agent_b.layout.home_root())?;

    fleet.start(&agent_a)?;
    fleet.start(&agent_b)?;
    let (control_a, _) = fleet.wait_ready(&agent_a, 1).await?;
    let (control_b, _) = fleet.wait_ready(&agent_b, 1).await?;
    let mut product_a = ProductClient::connect(&agent_a, &control_a).await?;
    let mut product_b = ProductClient::connect(&agent_b, &control_b).await?;
    let thread_a = product_a.start_thread(&agent_a.workspace).await?;
    let thread_b = product_b.start_thread(&agent_b.workspace).await?;

    let remember_a = responses::mount_sse_sequence(
        &model_a,
        vec![
            tool_sse(
                "remember-agent-a-response",
                REMEMBER_A_CALL,
                "remember",
                json!({
                    "stable_key": "agent-alpha-project",
                    "content": MEMORY_A,
                    "scope": "workspace_private",
                    "kg": project_deadline_facts(ALIAS_A, "Tuesday")
                }),
            ),
            final_sse("remember-agent-a-final"),
        ],
    )
    .await;
    product_a.run_turn(&thread_a, MEMORY_A).await?;
    assert_physical_request_count_stable(&remember_a, 2, "Agent A remember").await?;
    let remembered_a = tool_output(&remember_a, REMEMBER_A_CALL)?;
    let memory_id_a = remembered_a["memory"]["memory_id"]
        .as_str()
        .context("Agent A remember output omitted memory_id")?
        .to_string();
    assert_projection_receipt(&remembered_a, 1, 3, 2, 1, 2, 1)?;

    let remember_b = responses::mount_sse_sequence(
        &model_b,
        vec![
            tool_sse(
                "remember-agent-b-response",
                REMEMBER_B_CALL,
                "remember",
                json!({
                    "stable_key": "agent-beta-project",
                    "content": MEMORY_B,
                    "scope": "workspace_private",
                    "kg": project_deadline_facts(ALIAS_B, "Thursday")
                }),
            ),
            final_sse("remember-agent-b-final"),
        ],
    )
    .await;
    product_b.run_turn(&thread_b, MEMORY_B).await?;
    assert_physical_request_count_stable(&remember_b, 2, "Agent B remember").await?;
    let remembered_b = tool_output(&remember_b, REMEMBER_B_CALL)?;
    let memory_id_b = remembered_b["memory"]["memory_id"]
        .as_str()
        .context("Agent B remember output omitted memory_id")?
        .to_string();
    assert_projection_receipt(&remembered_b, 1, 3, 2, 1, 2, 1)?;

    let recall_a = responses::mount_sse_sequence(&model_a, vec![final_sse("agent-a-final")]).await;
    product_a.run_turn(&thread_a, ALIAS_A).await?;
    assert_physical_request_count_stable(&recall_a, 1, "Agent A own KG recall").await?;
    let request_a = recall_a.single_request();
    assert_single_memory_reference_with_channels(
        &request_a,
        &memory_id_a,
        1,
        MEMORY_A,
        &["entity_fts", "graph_one_hop", "recency"],
    )?;
    assert_memory_absent(&request_a, &memory_id_b)?;

    let recall_b = responses::mount_sse_sequence(&model_b, vec![final_sse("agent-b-final")]).await;
    product_b.run_turn(&thread_b, ALIAS_B).await?;
    assert_physical_request_count_stable(&recall_b, 1, "Agent B own KG recall").await?;
    let request_b = recall_b.single_request();
    assert_single_memory_reference_with_channels(
        &request_b,
        &memory_id_b,
        1,
        MEMORY_B,
        &["entity_fts", "graph_one_hop", "recency"],
    )?;
    assert_memory_absent(&request_b, &memory_id_a)?;

    let model_b_before_a_probe = model_b.received_requests().await.unwrap_or_default().len();
    let cross_alias_a =
        responses::mount_sse_sequence(&model_a, vec![final_sse("agent-a-cross-alias-final")]).await;
    product_a.run_turn(&thread_a, CROSS_ALIAS_B_QUERY).await?;
    assert_physical_request_count_stable(&cross_alias_a, 1, "Agent A cross-Agent KG probe").await?;
    let cross_alias_a_request = cross_alias_a.single_request();
    assert_single_memory_reference_with_channels(
        &cross_alias_a_request,
        &memory_id_a,
        1,
        MEMORY_A,
        &["recency"],
    )?;
    assert_memory_absent(&cross_alias_a_request, &memory_id_b)?;
    assert_server_request_count_stable(
        &model_b,
        model_b_before_a_probe,
        "Agent B provider during Agent A KG probe",
    )
    .await?;

    let model_a_before_b_probe = model_a.received_requests().await.unwrap_or_default().len();
    let cross_alias_b =
        responses::mount_sse_sequence(&model_b, vec![final_sse("agent-b-cross-alias-final")]).await;
    product_b.run_turn(&thread_b, CROSS_ALIAS_A_QUERY).await?;
    assert_physical_request_count_stable(&cross_alias_b, 1, "Agent B cross-Agent KG probe").await?;
    let cross_alias_b_request = cross_alias_b.single_request();
    assert_single_memory_reference_with_channels(
        &cross_alias_b_request,
        &memory_id_b,
        1,
        MEMORY_B,
        &["recency"],
    )?;
    assert_memory_absent(&cross_alias_b_request, &memory_id_a)?;
    assert_server_request_count_stable(
        &model_a,
        model_a_before_b_probe,
        "Agent A provider during Agent B KG probe",
    )
    .await?;

    product_a.shutdown().await?;
    product_b.shutdown().await?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 6)]
async fn running_consumer_observes_owner_control_grant_and_revoke_without_restart() -> Result<()> {
    const SHARED: &str = "Owner Alpha shares the unique heliotrope observatory marker.";
    const LOCAL: &str = "Consumer Beta keeps the local heliotrope observatory notebook.";

    let mut fleet = FleetHarness::new()?;
    let owner = fleet.register(AGENT_A, "workspace-owner")?;
    let consumer = fleet.register(AGENT_B, "workspace-consumer")?;
    let owner_model = responses::start_mock_server().await;
    let consumer_model = responses::start_mock_server().await;
    MockResponsesConfig::new(&owner_model.uri()).write(owner.layout.home_root())?;
    MockResponsesConfig::new(&consumer_model.uri()).write(consumer.layout.home_root())?;
    seed_verified_agent_memory(&owner, "shared-observatory-marker", SHARED).await?;
    seed_verified_agent_memory(&consumer, "local-observatory-marker", LOCAL).await?;

    fleet.start(&owner)?;
    let (owner_control, _) = fleet.wait_ready(&owner, 1).await?;
    fleet.start(&consumer)?;
    let (consumer_control, _) = fleet.wait_ready(&consumer, 1).await?;
    let mut product = ProductClient::connect(&consumer, &consumer_control).await?;
    let thread = product.start_thread(&consumer.workspace).await?;

    let before = responses::mount_sse_once(&consumer_model, final_sse("before-grant")).await;
    product
        .run_turn(&thread, "Recall the heliotrope observatory marker.")
        .await
        .context("before-grant consumer turn")?;
    ensure!(
        !raw_requests_contain(&before, SHARED),
        "consumer saw owner memory before an explicit grant"
    );
    ensure!(
        raw_requests_contain(&before, LOCAL),
        "consumer did not retain its local cognitive memory before federation"
    );

    let capability = owner_control
        .memory_federation_grant(
            consumer.agent_id.clone(),
            MemoryFederationScopeKind::AgentPrivate,
            3_600,
        )
        .await?;
    ensure!(capability.state == MemoryFederationCapabilityState::Granted);
    ensure!(capability.owner_agent_id == owner.agent_id);
    ensure!(capability.consumer_agent_id == consumer.agent_id);
    let listed = owner_control.memory_federation_list(16).await?;
    ensure!(listed.as_slice() == std::slice::from_ref(&capability));
    ensure!(
        owner_control
            .memory_federation_status(capability.capability_id.clone())
            .await?
            == Some(capability.clone())
    );

    let after = responses::mount_sse_once(&consumer_model, final_sse("after-grant")).await;
    product
        .run_turn(&thread, "Recall the heliotrope observatory marker.")
        .await
        .context("after-grant consumer turn")?;
    ensure!(
        raw_requests_contain(&after, SHARED),
        "already-running consumer did not dynamically observe the owner grant"
    );
    ensure!(
        raw_requests_contain(&after, LOCAL),
        "single Cognitive proposal dropped local memory while merging federation"
    );
    ensure!(
        raw_requests_contain(&after, owner.agent_id.as_str()),
        "federated context omitted source AgentId provenance"
    );

    let nested_workspace = consumer.workspace.join("other-scope");
    std::fs::create_dir(&nested_workspace)?;
    let nested_workspace = nested_workspace.canonicalize()?;
    let nested_thread = product.start_thread(&nested_workspace).await?;
    let wrong_scope = responses::mount_sse_once(&consumer_model, final_sse("wrong-scope")).await;
    product
        .run_turn(&nested_thread, "Recall the heliotrope observatory marker.")
        .await
        .context("cross-workspace consumer turn")?;
    ensure!(
        !raw_requests_contain(&wrong_scope, SHARED),
        "grant escaped its registry-derived consumer workspace binding"
    );

    let self_grant = owner_control
        .memory_federation_grant(
            owner.agent_id.clone(),
            MemoryFederationScopeKind::AgentPrivate,
            3_600,
        )
        .await
        .expect_err("owner cannot grant to itself")
        .to_string();
    ensure!(self_grant.contains("another registered AgentId"));

    let first_seen = Arc::new(AtomicBool::new(false));
    let responder = DelayedToolSequence::new(
        Arc::clone(&first_seen),
        tool_sse(
            "federated-revalidate-tool",
            "federated-revalidate-recall",
            "recall",
            json!({"query": "local no-op query"}),
        ),
        final_sse("federated-revalidate-final"),
    );
    let delayed_start = consumer_model
        .received_requests()
        .await
        .unwrap_or_default()
        .len();
    Mock::given(method("POST"))
        .and(path("/v1/responses"))
        .respond_with(responder)
        .up_to_n_times(3)
        .mount(&consumer_model)
        .await;
    let turn = product.run_turn(&thread, "Recall the heliotrope observatory marker.");
    let revoke = async {
        timeout(Duration::from_secs(5), async {
            while !first_seen.load(Ordering::Acquire) {
                tokio::time::sleep(Duration::from_millis(5)).await;
            }
        })
        .await
        .context("first physical send did not reach the delayed model")?;
        let revoked = owner_control
            .memory_federation_revoke(capability.capability_id.clone())
            .await?;
        Ok::<_, anyhow::Error>(revoked)
    };
    let (turn_result, revoked) = tokio::join!(turn, revoke);
    turn_result.context("revalidation consumer turn")?;
    let revoked = revoked?;
    ensure!(revoked.state == MemoryFederationCapabilityState::Revoked);
    ensure!(revoked.revision == capability.revision + 1);

    let captured = consumer_model.received_requests().await.unwrap_or_default();
    let delayed = captured
        .iter()
        .skip(delayed_start)
        .map(|request| String::from_utf8_lossy(&request.body).into_owned())
        .collect::<Vec<_>>();
    ensure!(
        (2..=3).contains(&delayed.len()),
        "delayed model received an unexpected number of sends: {}",
        delayed.len()
    );
    ensure!(
        delayed[0].contains(SHARED),
        "prepared federated context was absent from the first physical send"
    );
    ensure!(
        delayed
            .iter()
            .skip(1)
            .all(|request| !request.contains(SHARED)),
        "revoked federated context survived a retry/follow-up physical-send revalidation"
    );
    ensure!(
        delayed.iter().all(|request| request.contains(LOCAL)),
        "local cognitive context was lost while federated context was revoked"
    );

    let owner_database = owner.layout.cognitive_root().join("cognitive_1.sqlite3");
    let unavailable_database = owner.layout.cognitive_root().join("cognitive_1.offline");
    std::fs::rename(&owner_database, &unavailable_database)?;
    let unavailable =
        responses::mount_sse_once(&consumer_model, final_sse("owner-unavailable")).await;
    product
        .run_turn(
            &thread,
            "Continue while the federation source is unavailable.",
        )
        .await
        .context("unavailable-source consumer turn")?;
    ensure!(
        !raw_requests_contain(&unavailable, SHARED),
        "unavailable owner source did not degrade to no federated context"
    );
    ensure!(
        consumer_control.health().await?.ready,
        "owner-source failure incorrectly blocked normal consumer turns"
    );
    std::fs::rename(&unavailable_database, &owner_database)?;

    product.shutdown().await?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 8)]
async fn five_running_agents_share_only_with_the_explicit_consumer() -> Result<()> {
    const SHARED: &str = "Only Agent B may read the unique umber lighthouse marker.";

    let mut fleet = FleetHarness::new()?;
    let owner = fleet.register(AGENT_A, "workspace-a-five")?;
    let consumer = fleet.register(AGENT_B, "workspace-b-five")?;
    let agent_c = fleet.register(AGENT_C, "workspace-c-five")?;
    let agent_d = fleet.register(AGENT_D, "workspace-d-five")?;
    let agent_e = fleet.register(AGENT_E, "workspace-e-five")?;
    let fixtures = [&owner, &consumer, &agent_c, &agent_d, &agent_e];
    let mut models = Vec::new();
    for fixture in fixtures {
        let model = responses::start_mock_server().await;
        MockResponsesConfig::new(&model.uri()).write(fixture.layout.home_root())?;
        models.push(model);
    }
    seed_verified_agent_memory(&owner, "five-agent-shared-marker", SHARED).await?;

    let mut controls = Vec::new();
    for fixture in fixtures {
        fleet.start(fixture)?;
        controls.push(fleet.wait_ready(fixture, 1).await?.0);
    }
    controls[0]
        .memory_federation_grant(
            consumer.agent_id.clone(),
            MemoryFederationScopeKind::AgentPrivate,
            3_600,
        )
        .await?;

    for (index, fixture) in fixtures.iter().enumerate().skip(1) {
        let mut product = ProductClient::connect(fixture, &controls[index]).await?;
        let thread = product.start_thread(&fixture.workspace).await?;
        let response =
            responses::mount_sse_once(&models[index], final_sse(&format!("five-agent-{index}")))
                .await;
        product
            .run_turn(&thread, "Recall the unique umber lighthouse marker.")
            .await?;
        ensure!(
            raw_requests_contain(&response, SHARED) == (index == 1),
            "five-Agent federation leaked to the wrong consumer index {index}"
        );
        product.shutdown().await?;
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[cfg(not(feature = "qualification-cognitive-write"))]
async fn unavailable_cognitive_store_keeps_read_tools_and_omits_write_tools() -> Result<()> {
    const UNAVAILABLE_CALL: &str = "unavailable-recall";
    const QUERY: &str = "unavailable runtime probe";

    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(AGENT_A, "workspace-a")?;
    let model = responses::start_mock_server().await;
    MockResponsesConfig::new(&model.uri()).write(agent.layout.home_root())?;
    let blocking_path = agent.layout.cognitive_root().join("cognitive_1.sqlite3");
    std::fs::create_dir(&blocking_path)?;

    fleet.start(&agent)?;
    let (control, _) = fleet.wait_ready(&agent, 1).await?;
    ensure!(control.health().await?.ready, "agentd did not stay ready");
    let mut product = ProductClient::connect(&agent, &control).await?;
    let thread = product.start_thread(&agent.workspace).await?;
    let unavailable = responses::mount_sse_sequence(
        &model,
        vec![
            tool_sse(
                "unavailable-response",
                UNAVAILABLE_CALL,
                "recall",
                json!({ "query": QUERY }),
            ),
            final_sse("unavailable-final"),
        ],
    )
    .await;
    product.run_turn(&thread, QUERY).await?;
    assert_physical_request_count_stable(&unavailable, 2, "unavailable cognitive read").await?;
    let requests = unavailable.requests();
    assert_no_cognitive_reference(&requests[0])?;
    for operation in ["remember", "correct", "forget"] {
        ensure!(
            requests[0]
                .tool_by_name(COGNITIVE_NAMESPACE, operation)
                .is_none(),
            "unavailable runtime incorrectly advertised write tool {operation}"
        );
    }
    for operation in ["recall", "explain"] {
        ensure!(
            requests[0]
                .tool_by_name(COGNITIVE_NAMESPACE, operation)
                .is_some(),
            "unavailable runtime incorrectly removed read tool {operation}"
        );
    }
    assert_no_cognitive_reference(&requests[1])?;
    let output = unavailable
        .function_call_output_text(UNAVAILABLE_CALL)
        .context("unavailable tool output did not reach the model")?;
    let typed: Value = serde_json::from_str(&output)?;
    ensure!(typed["error"]["code"] == "hepta_cognitive_unavailable");
    ensure!(
        typed["error"]["message"]
            .as_str()
            .is_some_and(|message| message.contains("storage_unavailable")),
        "typed error omitted the sanitized stable reason"
    );
    ensure!(
        !output.contains(blocking_path.to_string_lossy().as_ref())
            && !output.to_ascii_lowercase().contains("sqlite"),
        "typed unavailable error leaked storage details"
    );

    product.shutdown().await?;
    Ok(())
}

/// The explicit writer qualification profile has a stronger startup
/// contract than local read-only development: an unavailable cognitive store
/// must stop before App Server can serve a turn.  Keep this assertion next to
/// the default-profile degraded-runtime test so enabling the feature cannot
/// accidentally weaken the E.24 available-only gate.
#[cfg(feature = "qualification-cognitive-write")]
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn qualification_cognitive_store_unavailable_fails_closed_before_provider() -> Result<()> {
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(AGENT_A, "workspace-a-qualification-unavailable")?;
    let blocking_path = agent.layout.cognitive_root().join("cognitive_1.sqlite3");
    std::fs::create_dir(&blocking_path)?;

    fleet.start(&agent)?;
    let deadline = Instant::now() + Duration::from_secs(20);
    loop {
        let report = fleet.supervisor.tick(Instant::now());
        ensure!(
            report.faults.is_empty(),
            "supervisor faulted while observing qualification startup rejection: {:?}",
            report.faults
        );
        let lifecycle = fleet
            .registry
            .load()?
            .agent(&agent.agent_id)
            .context("qualification Agent disappeared from registry")?
            .lifecycle
            .lifecycle;
        let snapshot = fleet
            .supervisor
            .snapshot(&agent.agent_id)
            .context("qualification Agent disappeared from supervisor")?;
        if lifecycle == AgentLifecycle::Failed && !snapshot.active {
            let logs = snapshot
                .logs
                .iter()
                .map(|log| String::from_utf8_lossy(&log.bytes))
                .collect::<String>();
            ensure!(
                logs.contains("qualification cognitive runtime unavailable"),
                "qualification startup omitted the fail-closed error; logs={logs:?}"
            );
            ensure!(
                !snapshot.healthy,
                "qualification startup rejection was reported healthy"
            );
            return Ok(());
        }
        ensure!(
            Instant::now() < deadline,
            "qualification Agent did not fail closed; lifecycle={lifecycle:?}; snapshot={snapshot:?}"
        );
        tokio::time::sleep(Duration::from_millis(25)).await;
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn unavailable_automation_store_keeps_real_agentd_and_app_server_ready() -> Result<()> {
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(AGENT_A, "workspace-a")?;
    let model = responses::start_mock_server().await;
    MockResponsesConfig::new(&model.uri()).write(agent.layout.home_root())?;
    let blocking_path = agent.layout.automation_root().join("automation_1.sqlite3");
    std::fs::create_dir(&blocking_path)?;

    fleet.start(&agent)?;
    let (control, _) = fleet.wait_ready(&agent, 1).await?;
    ensure!(control.health().await?.ready, "agentd did not stay ready");
    let error = control
        .automation_list(1)
        .await
        .expect_err("unavailable automation must return a typed error")
        .to_string();
    ensure!(
        error.contains("automation_unavailable"),
        "typed automation error omitted its stable code: {error}"
    );
    ensure!(
        !error.contains(blocking_path.to_string_lossy().as_ref())
            && !error.to_ascii_lowercase().contains("sqlite"),
        "typed automation error leaked storage details"
    );

    let mut product = ProductClient::connect(&agent, &control).await?;
    let thread = product.start_thread(&agent.workspace).await?;
    let normal = responses::mount_sse_sequence(
        &model,
        vec![final_sse("automation-unavailable-normal-turn")],
    )
    .await;
    product
        .run_turn(&thread, "Continue normal work without automation storage.")
        .await?;
    ensure!(
        normal.requests().len() == 1,
        "normal App Server turn did not survive automation storage outage"
    );
    product.shutdown().await?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn runtime_automation_store_failure_does_not_end_real_agentd_or_normal_turns() -> Result<()> {
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(AGENT_A, "workspace-a")?;
    let model = responses::start_mock_server().await;
    MockResponsesConfig::new(&model.uri()).write(agent.layout.home_root())?;

    fleet.start(&agent)?;
    let (control, _) = fleet.wait_ready(&agent, 1).await?;
    let mut product = ProductClient::connect(&agent, &control).await?;
    let thread = product.start_thread(&agent.workspace).await?;
    let created_at_ms = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
    let task = control
        .automation_create(AutomationTaskDraft::new(
            thread.clone(),
            "runtime automation store failure probe",
            AutomationSchedule::Once,
            created_at_ms + 60_000,
            created_at_ms,
        ))
        .await?;
    ensure!(
        control.automation_list(1).await? == [task],
        "automation was not available before runtime sabotage"
    );

    let database_path = agent.layout.automation_root().join("automation_1.sqlite3");
    let sqlite_home = AbsolutePathBuf::from_absolute_path(agent.layout.automation_root())?;
    let sabotage = SqliteConfig::from_sqlite_home(sqlite_home)
        .open_durable_evidence_pool(&database_path)
        .await?;
    sqlx::query("DROP TABLE automation_tasks")
        .execute(&sabotage)
        .await?;
    sabotage.close().await;

    let error = timeout(Duration::from_secs(5), async {
        loop {
            match control.automation_list(1).await {
                Ok(_) => tokio::time::sleep(Duration::from_millis(25)).await,
                Err(error) => {
                    let rendered = error.to_string();
                    if rendered.contains("automation_unavailable") {
                        return Ok::<String, anyhow::Error>(rendered);
                    }
                    return Err(anyhow!(
                        "unexpected automation control failure after store sabotage: {rendered}"
                    ));
                }
            }
        }
    })
    .await
    .context("runtime automation store failure was not quarantined")??;
    ensure!(
        !error.contains(database_path.to_string_lossy().as_ref())
            && !error.to_ascii_lowercase().contains("sqlite"),
        "runtime automation error leaked storage details"
    );
    ensure!(
        control.health().await?.ready,
        "automation failure incorrectly stopped the real agentd"
    );

    let normal = responses::mount_sse_sequence(
        &model,
        vec![final_sse("runtime-automation-unavailable-normal-turn")],
    )
    .await;
    product
        .run_turn(
            &thread,
            "Continue normal work after the automation store failed.",
        )
        .await?;
    ensure!(
        normal.requests().len() == 1,
        "normal model turn did not survive runtime automation failure"
    );

    product.shutdown().await?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 8)]
async fn five_real_agents_survive_one_automation_store_failure_without_peer_stall() -> Result<()> {
    let mut fleet = FleetHarness::new()?;
    let agent_a = fleet.register(AGENT_A, "workspace-a-store-failure-five")?;
    let agent_b = fleet.register(AGENT_B, "workspace-b-store-failure-five")?;
    let agent_c = fleet.register(AGENT_C, "workspace-c-store-failure-five")?;
    let agent_d = fleet.register(AGENT_D, "workspace-d-store-failure-five")?;
    let agent_e = fleet.register(AGENT_E, "workspace-e-store-failure-five")?;
    let fixtures = [&agent_a, &agent_b, &agent_c, &agent_d, &agent_e];

    let mut models = Vec::new();
    for fixture in fixtures {
        let model = responses::start_mock_server().await;
        MockResponsesConfig::new(&model.uri()).write(fixture.layout.home_root())?;
        models.push(model);
    }

    let mut controls = Vec::new();
    let mut before = Vec::new();
    for fixture in fixtures {
        fleet.start(fixture)?;
        let (control, health) = fleet.wait_ready(fixture, 1).await?;
        controls.push(control);
        before.push(health);
    }

    // Materialize Agent A's automation store before sabotaging only that Agent.
    let mut owner_product = ProductClient::connect(&agent_a, &controls[0]).await?;
    let owner_thread = owner_product.start_thread(&agent_a.workspace).await?;
    let created_at_ms = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
    controls[0]
        .automation_create(AutomationTaskDraft::new(
            owner_thread,
            "five-agent peer store failure probe",
            AutomationSchedule::Once,
            created_at_ms + 60_000,
            created_at_ms,
        ))
        .await?;
    owner_product.shutdown().await?;

    let database_path = agent_a
        .layout
        .automation_root()
        .join("automation_1.sqlite3");
    let sqlite_home = AbsolutePathBuf::from_absolute_path(agent_a.layout.automation_root())?;
    let sabotage = SqliteConfig::from_sqlite_home(sqlite_home)
        .open_durable_evidence_pool(&database_path)
        .await?;
    sqlx::query("DROP TABLE automation_tasks")
        .execute(&sabotage)
        .await?;
    sabotage.close().await;

    let unavailable = timeout(Duration::from_secs(5), async {
        loop {
            match controls[0].automation_list(1).await {
                Ok(_) => tokio::time::sleep(Duration::from_millis(25)).await,
                Err(error) => {
                    let rendered = error.to_string();
                    if rendered.contains("automation_unavailable") {
                        return Ok::<String, anyhow::Error>(rendered);
                    }
                    return Err(anyhow!(
                        "unexpected Agent A automation failure after sabotage: {rendered}"
                    ));
                }
            }
        }
    })
    .await
    .context("Agent A automation store failure was not quarantined")??;
    ensure!(
        !unavailable.contains(database_path.to_string_lossy().as_ref())
            && !unavailable.to_ascii_lowercase().contains("sqlite"),
        "Agent A typed automation error leaked storage details"
    );
    ensure!(
        controls[0].health().await?.ready,
        "Agent A automation failure incorrectly stopped agentd"
    );

    // While Agent A is quarantined, every peer must retain its exact process and
    // complete an ordinary App Server turn through its own model/socket.
    for index in 1..fixtures.len() {
        let health_before = &before[index];
        let health = controls[index].health().await?;
        ensure!(
            health.ready,
            "peer {index} lost readiness after Agent A failure"
        );
        ensure!(
            health.process_id == health_before.process_id,
            "peer {index} was restarted after Agent A store failure"
        );
        let mut product = ProductClient::connect(fixtures[index], &controls[index]).await?;
        let thread = product.start_thread(&fixtures[index].workspace).await?;
        let created_at_ms =
            u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
        let peer_task = controls[index]
            .automation_create(AutomationTaskDraft::new(
                thread.clone(),
                format!("peer {index} automation store probe"),
                AutomationSchedule::Once,
                created_at_ms + 60_000,
                created_at_ms,
            ))
            .await?;
        let listed = controls[index].automation_list(8).await?;
        ensure!(
            listed.iter().any(|task| task.task_id == peer_task.task_id),
            "peer {index} automation store became unavailable"
        );
        controls[index].automation_cancel(peer_task.task_id).await?;
        let response = responses::mount_sse_once(
            &models[index],
            final_sse(&format!("peer-store-failure-{index}")),
        )
        .await;
        product
            .run_turn(
                &thread,
                "Continue normal work while Agent A storage is unavailable.",
            )
            .await?;
        ensure!(
            response.requests().len() == 1,
            "peer {index} did not complete a normal model turn"
        );
        let health_after = controls[index].health().await?;
        ensure!(
            health_after.ready && health_after.process_id == health_before.process_id,
            "peer {index} changed process/readiness during Agent A store failure"
        );
        product.shutdown().await?;
    }

    Ok(())
}

fn tool_sse(response_id: &str, call_id: &str, operation: &str, arguments: Value) -> String {
    responses::sse(vec![
        responses::ev_response_created(response_id),
        responses::ev_function_call_with_namespace(
            call_id,
            COGNITIVE_NAMESPACE,
            operation,
            &arguments.to_string(),
        ),
        responses::ev_completed(response_id),
    ])
}

fn final_sse(response_id: &str) -> String {
    responses::sse(vec![
        responses::ev_response_created(response_id),
        responses::ev_assistant_message(&format!("message-{response_id}"), "done"),
        responses::ev_completed(response_id),
    ])
}

fn final_sse_with_citation(response_id: &str, citation_path: &str) -> String {
    responses::sse(vec![
        responses::ev_response_created(response_id),
        responses::ev_assistant_message(
            &format!("message-{response_id}"),
            &format!(
                "done<oai-mem-citation><citation_entries>\n{citation_path}:1-1|note=[verified source]\n</citation_entries>\n</oai-mem-citation>"
            ),
        ),
        responses::ev_completed(response_id),
    ])
}

fn assert_thread_read_contains_cited_answer(
    response: &ThreadReadResponse,
    expected_citation_path: &str,
) -> Result<()> {
    let agent_message = response
        .thread
        .turns
        .iter()
        .flat_map(|turn| turn.items.iter())
        .filter_map(|item| match item {
            ThreadItem::AgentMessage {
                text,
                memory_citation,
                ..
            } => Some((text, memory_citation.as_ref())),
            _ => None,
        })
        .next_back()
        .context("thread/read omitted the completed assistant message")?;
    ensure!(
        agent_message.0 == "done",
        "assistant response text was not persisted"
    );
    let citation = agent_message
        .1
        .context("assistant response omitted its parsed memory citation")?;
    ensure!(
        citation
            .entries
            .iter()
            .any(|entry| entry.path == expected_citation_path),
        "assistant memory citation did not bind to the expected source path"
    );
    Ok(())
}

fn assert_external_read_only_turn(
    response: &ThreadReadResponse,
    turn_id: &str,
    expected_text: &str,
) -> Result<()> {
    let turn = response
        .thread
        .turns
        .iter()
        .find(|turn| turn.id == turn_id)
        .context("thread/read omitted the completed external-provider turn")?;
    ensure!(
        turn.items_view == codex_app_server_protocol::TurnItemsView::Full,
        "thread/read did not return full turn items"
    );
    // For this one-shot smoke, only user/assistant/reasoning items are valid.
    // Reject every other variant (including command, MCP, dynamic, web, and
    // collaboration calls) instead of relying on the prompt as a soft guard.
    ensure!(
        turn.items.iter().all(|item| matches!(
            item,
            ThreadItem::UserMessage { .. }
                | ThreadItem::AgentMessage { .. }
                | ThreadItem::Reasoning { .. }
        )),
        "external-provider smoke produced a non-read-only thread item"
    );
    let assistant_text = turn
        .items
        .iter()
        .filter_map(|item| match item {
            ThreadItem::AgentMessage { text, .. } => Some(text.as_str()),
            _ => None,
        })
        .next_back()
        .context("external-provider turn omitted an assistant message")?;
    ensure!(
        assistant_text.trim() == expected_text,
        "external-provider assistant text mismatch: expected {expected_text:?}, got {assistant_text:?}"
    );
    Ok(())
}

struct DelayedToolSequence {
    call_count: AtomicUsize,
    first_seen: Arc<AtomicBool>,
    first: String,
    second: String,
}

impl DelayedToolSequence {
    fn new(first_seen: Arc<AtomicBool>, first: String, second: String) -> Self {
        Self {
            call_count: AtomicUsize::new(0),
            first_seen,
            first,
            second,
        }
    }
}

impl Respond for DelayedToolSequence {
    fn respond(&self, _request: &Request) -> ResponseTemplate {
        let call = self.call_count.fetch_add(1, Ordering::AcqRel);
        let body = match call {
            0 => {
                self.first_seen.store(true, Ordering::Release);
                // TurnInput preparation and the first physical request have
                // completed, while the model response is still withheld. This
                // gives owner control a deterministic revocation window before
                // the tool follow-up creates the next physical send.
                std::thread::sleep(Duration::from_millis(750));
                &self.first
            }
            _ => &self.second,
        };
        ResponseTemplate::new(200)
            .insert_header("content-type", "text/event-stream")
            .set_body_string(body.clone())
    }
}

fn raw_requests_contain(mock: &ResponseMock, needle: &str) -> bool {
    mock.requests()
        .iter()
        .any(|request| request.body_contains_text(needle))
}

async fn assert_physical_request_count_stable(
    mock: &ResponseMock,
    expected: usize,
    label: &str,
) -> Result<()> {
    let deadline = Instant::now() + STABLE_REQUEST_WINDOW;
    loop {
        let observed = mock.requests().len();
        ensure!(
            observed == expected,
            "{label} physical request count changed during the stable window: expected {expected}, found {observed}"
        );
        if Instant::now() >= deadline {
            return Ok(());
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
}

async fn assert_server_request_count_stable(
    server: &MockServer,
    expected: usize,
    label: &str,
) -> Result<()> {
    let deadline = Instant::now() + STABLE_REQUEST_WINDOW;
    loop {
        let observed = server.received_requests().await.unwrap_or_default().len();
        ensure!(
            observed == expected,
            "{label} request count changed during the stable window: expected {expected}, found {observed}"
        );
        if Instant::now() >= deadline {
            return Ok(());
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
}

fn tool_output(mock: &ResponseMock, call_id: &str) -> Result<Value> {
    let output = mock
        .function_call_output_text(call_id)
        .with_context(|| format!("tool output for {call_id} did not reach the model"))?;
    serde_json::from_str(&output).context("cognitive tool output was not JSON")
}

fn cognitive_attachments(request: &ResponsesRequest) -> Result<Vec<Value>> {
    request
        .message_input_texts("user")
        .into_iter()
        .filter(|text| text.contains("<hepta_memory_reference"))
        .map(|text| {
            ensure!(
                text.starts_with(COGNITIVE_REFERENCE_OPEN),
                "cognitive reference outer wrapper drifted from schema 1"
            );
            let envelope = text
                .strip_prefix(COGNITIVE_REFERENCE_OPEN)
                .and_then(|text| text.strip_suffix(COGNITIVE_REFERENCE_CLOSE))
                .map(str::trim)
                .context("malformed cognitive reference wrapper")?;
            let envelope: Value = serde_json::from_str(envelope)?;
            ensure!(envelope["trust"] == "quoted_untrusted_reference");
            let summary = envelope["summary"]
                .as_str()
                .context("cognitive reference omitted its quoted summary")?;
            let attachment: Value = serde_json::from_str(summary)?;
            ensure!(attachment["schema_version"] == 2);
            ensure!(attachment["source"] == "verified_versioned_memory");
            Ok(attachment)
        })
        .collect()
}

fn assert_single_memory_reference(
    request: &ResponsesRequest,
    memory_id: &str,
    revision: u64,
    content: &str,
) -> Result<()> {
    let attachments = cognitive_attachments(request)?;
    ensure!(
        attachments.len() == 1,
        "expected exactly one cognitive attachment"
    );
    let memories = attachments[0]["memories"]
        .as_array()
        .context("cognitive attachment omitted memories")?;
    ensure!(memories.len() == 1, "expected exactly one attached memory");
    ensure!(memories[0]["memory_id"] == memory_id);
    ensure!(memories[0]["revision"] == revision);
    ensure!(memories[0]["content"] == content);
    let content_sha256 = json_sha256(&memories[0], "content_sha256")?;
    let citations = memories[0]["citations"]
        .as_array()
        .context("cognitive attachment omitted citations")?;
    ensure!(
        citations.len() == 1,
        "expected exactly one attached source citation"
    );
    ensure!(
        citations[0]["source_id"]
            .as_str()
            .is_some_and(|source_id| source_id.starts_with("source:v1:")),
        "cognitive attachment omitted its canonical source ID"
    );
    ensure!(citations[0]["revision"] == 1);
    ensure!(
        json_sha256(&citations[0], "content_sha256")? == content_sha256,
        "memory and exact source citation hashes diverged in the physical attachment"
    );
    Ok(())
}

fn assert_single_memory_reference_with_channels(
    request: &ResponsesRequest,
    memory_id: &str,
    revision: u64,
    content: &str,
    expected_channels: &[&str],
) -> Result<()> {
    assert_single_memory_reference(request, memory_id, revision, content)?;
    let memory = attached_memory(request, memory_id)?;
    let channels = memory["channels"]
        .as_array()
        .context("schema-2 cognitive attachment omitted channels")?
        .iter()
        .map(|channel| {
            channel
                .as_str()
                .context("cognitive retrieval channel was not a string")
        })
        .collect::<Result<Vec<_>>>()?;
    ensure!(
        channels == expected_channels,
        "physical cognitive attachment carried unexpected retrieval channels: expected {expected_channels:?}, found {channels:?}"
    );
    Ok(())
}

fn attached_memory(request: &ResponsesRequest, memory_id: &str) -> Result<Value> {
    let matching = cognitive_attachments(request)?
        .into_iter()
        .flat_map(|attachment| {
            attachment["memories"]
                .as_array()
                .cloned()
                .unwrap_or_default()
        })
        .filter(|memory| memory["memory_id"] == memory_id)
        .collect::<Vec<_>>();
    ensure!(
        matching.len() == 1,
        "expected one attached occurrence of memory {memory_id}, found {}",
        matching.len()
    );
    matching
        .into_iter()
        .next()
        .context("length-checked cognitive attachment missing")
}

fn assert_memory_absent(request: &ResponsesRequest, memory_id: &str) -> Result<()> {
    let found = cognitive_attachments(request)?
        .into_iter()
        .any(|attachment| {
            attachment["memories"].as_array().is_some_and(|memories| {
                memories
                    .iter()
                    .any(|memory| memory["memory_id"] == memory_id)
            })
        });
    ensure!(
        !found,
        "memory {memory_id} crossed an Agent/workspace boundary"
    );
    Ok(())
}

fn assert_memory_source(
    request: &ResponsesRequest,
    memory_id: &str,
    expected_source_id: &str,
) -> Result<()> {
    let memory = attached_memory(request, memory_id)?;
    let citations = memory["citations"]
        .as_array()
        .context("cognitive attachment omitted citations")?;
    ensure!(
        citations.len() == 1 && citations[0]["source_id"] == expected_source_id,
        "physical cognitive attachment did not preserve the tool receipt source citation"
    );
    Ok(())
}

fn assert_no_cognitive_reference(request: &ResponsesRequest) -> Result<()> {
    ensure!(
        cognitive_attachments(request)?.is_empty(),
        "unexpected cognitive reference reached a physical provider request"
    );
    Ok(())
}

fn attachment_text(request: &ResponsesRequest) -> Result<String> {
    let attachments = cognitive_attachments(request)?;
    ensure!(
        !attachments.is_empty(),
        "physical request contained no cognitive attachment"
    );
    Ok(serde_json::to_string(&attachments)?)
}

fn project_deadline_facts(alias: &str, weekday: &str) -> Value {
    let weekday_key = weekday.to_ascii_lowercase();
    json!({
        "entities": [
            {
                "key": "project-aurora",
                "entity_type": "project",
                "label": alias
            },
            {
                "key": weekday_key,
                "entity_type": "weekday",
                "label": weekday
            }
        ],
        "relations": [
            {
                "key": "project-deadline",
                "from_entity_key": "project-aurora",
                "to_entity_key": weekday_key,
                "relation": "deadline_is"
            }
        ]
    })
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct KgProjectionEvidence {
    generation: u64,
    fact_count: u64,
    entity_count: u64,
    relation_count: u64,
    node_count: u64,
    edge_count: u64,
    fact_set_sha256: String,
    input_heads_sha256: String,
    output_sha256: String,
}

fn assert_projection_receipt(
    tool_output: &Value,
    generation: u64,
    fact_count: u64,
    entity_count: u64,
    relation_count: u64,
    node_count: u64,
    edge_count: u64,
) -> Result<KgProjectionEvidence> {
    let projection = &tool_output["projection"];
    let evidence = KgProjectionEvidence {
        generation: json_u64(projection, "generation")?,
        fact_count: json_u64(projection, "fact_count")?,
        entity_count: json_u64(projection, "entity_count")?,
        relation_count: json_u64(projection, "relation_count")?,
        node_count: json_u64(projection, "node_count")?,
        edge_count: json_u64(projection, "edge_count")?,
        fact_set_sha256: json_sha256(projection, "fact_set_sha256")?,
        input_heads_sha256: json_sha256(projection, "input_heads_sha256")?,
        output_sha256: json_sha256(projection, "output_sha256")?,
    };
    ensure!(
        evidence.generation == generation
            && evidence.fact_count == fact_count
            && evidence.entity_count == entity_count
            && evidence.relation_count == relation_count
            && evidence.node_count == node_count
            && evidence.edge_count == edge_count,
        "unexpected cognitive KG projection receipt: {evidence:?}"
    );
    Ok(evidence)
}

fn json_u64(value: &Value, field: &str) -> Result<u64> {
    value[field]
        .as_u64()
        .with_context(|| format!("cognitive projection omitted integer {field}"))
}

fn json_sha256(value: &Value, field: &str) -> Result<String> {
    let digest = value[field]
        .as_str()
        .with_context(|| format!("cognitive projection omitted {field}"))?;
    ensure!(
        digest.len() == 64
            && digest
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte)),
        "cognitive projection returned a non-canonical {field}"
    );
    Ok(digest.to_string())
}

async fn read_h7_trajectory_for_turn(
    store: &CognitiveStore,
    agent: &AgentFixture,
    turn_id: &str,
) -> Result<Option<codex_hepta_memory::H7TrajectoryRead>> {
    let database_path = agent.layout.cognitive_root().join("cognitive_1.sqlite3");
    let sqlite_home = AbsolutePathBuf::from_absolute_path(agent.layout.cognitive_root())?;
    let pool = SqliteConfig::from_sqlite_home(sqlite_home)
        .open_read_only_pool(&database_path)
        .await?;
    let trajectory_id: Option<String> = sqlx::query_scalar(
        "SELECT trajectory_id
         FROM cognitive_h7_trajectory_events
         WHERE turn_id = ?
         ORDER BY recorded_at_unix_seconds DESC, event_seq DESC
         LIMIT 1",
    )
    .bind(turn_id)
    .fetch_optional(&pool)
    .await?;
    let Some(trajectory_id) = trajectory_id else {
        return Ok(None);
    };
    Ok(store.read_h7_trajectory(trajectory_id).await?)
}

async fn read_kg_sqlite_evidence(
    agent: &AgentFixture,
    memory_id: &str,
    memory_revision: u64,
    expected_source_id: &str,
) -> Result<KgProjectionEvidence> {
    let database_path = agent.layout.cognitive_root().join("cognitive_1.sqlite3");
    let sqlite_home = AbsolutePathBuf::from_absolute_path(agent.layout.cognitive_root())?;
    let pool = SqliteConfig::from_sqlite_home(sqlite_home)
        .open_read_only_pool(&database_path)
        .await?;
    let memory_revision = i64::try_from(memory_revision)?;
    let (
        fact_set_sha256,
        fact_source_id,
        fact_source_revision,
        immutable_entity_count,
        immutable_relation_count,
    ): (String, String, i64, i64, i64) = sqlx::query_as(
        "SELECT fact_set_sha256, source_id, source_revision, entity_count, relation_count
             FROM kg_revision_fact_sets
             WHERE memory_id = ? AND memory_revision = ?",
    )
    .bind(memory_id)
    .bind(memory_revision)
    .fetch_one(&pool)
    .await?;
    ensure!(
        fact_source_id == expected_source_id && fact_source_revision == 1,
        "immutable KG fact set did not preserve the tool receipt source citation"
    );
    let immutable_entities: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM kg_revision_entities
         WHERE memory_id = ? AND memory_revision = ?
           AND source_id = ? AND source_revision = 1",
    )
    .bind(memory_id)
    .bind(memory_revision)
    .bind(expected_source_id)
    .fetch_one(&pool)
    .await?;
    let immutable_relations: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM kg_revision_relations
         WHERE memory_id = ? AND memory_revision = ?
           AND source_id = ? AND source_revision = 1",
    )
    .bind(memory_id)
    .bind(memory_revision)
    .bind(expected_source_id)
    .fetch_one(&pool)
    .await?;
    ensure!(
        immutable_entity_count == immutable_entities
            && immutable_relation_count == immutable_relations,
        "immutable KG fact rows did not match their fact-set receipt"
    );
    let (
        generation,
        receipt_fact_set_sha256,
        input_heads_sha256,
        output_sha256,
        entity_count,
        relation_count,
        node_count,
        edge_count,
        actual_node_count,
        actual_edge_count,
    ): (i64, String, String, String, i64, i64, i64, i64, i64, i64) = sqlx::query_as(
        "SELECT r.generation, r.fact_set_sha256, r.input_heads_sha256, r.output_sha256,
                r.entity_count, r.relation_count, r.node_count, r.edge_count,
                (SELECT COUNT(*) FROM kg_nodes AS n
                 WHERE n.projection_scope = r.projection_scope
                   AND n.generation = r.generation
                   AND n.memory_id = r.trigger_memory_id
                   AND n.memory_revision = r.trigger_memory_revision
                   AND n.source_id = ? AND n.source_revision = 1),
                (SELECT COUNT(*) FROM kg_edges AS e
                 WHERE e.projection_scope = r.projection_scope
                   AND e.generation = r.generation
                   AND e.memory_id = r.trigger_memory_id
                   AND e.memory_revision = r.trigger_memory_revision
                   AND e.source_id = ? AND e.source_revision = 1)
         FROM kg_projection_generation_receipts AS r
         JOIN kg_projection AS p
           ON p.projection_scope = r.projection_scope AND p.generation = r.generation
         WHERE r.trigger_memory_id = ? AND r.trigger_memory_revision = ?",
    )
    .bind(expected_source_id)
    .bind(expected_source_id)
    .bind(memory_id)
    .bind(memory_revision)
    .fetch_one(&pool)
    .await?;
    pool.close().await;
    ensure!(
        receipt_fact_set_sha256 == fact_set_sha256,
        "current projection receipt did not bind the immutable fact set"
    );
    ensure!(
        node_count == actual_node_count && edge_count == actual_edge_count,
        "current projection rows did not match their generation receipt"
    );
    Ok(KgProjectionEvidence {
        generation: u64::try_from(generation)?,
        fact_count: u64::try_from(immutable_entity_count + immutable_relation_count)?,
        entity_count: u64::try_from(entity_count)?,
        relation_count: u64::try_from(relation_count)?,
        node_count: u64::try_from(node_count)?,
        edge_count: u64::try_from(edge_count)?,
        fact_set_sha256,
        input_heads_sha256,
        output_sha256,
    })
}

async fn wait_inactive(fleet: &mut FleetHarness, agent_id: &AgentId) -> Result<()> {
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        let report = fleet.supervisor.tick(Instant::now());
        ensure!(
            report.faults.is_empty(),
            "supervisor faults while killing {agent_id}: {:?}",
            report.faults
        );
        let inactive = fleet
            .supervisor
            .snapshot(agent_id)
            .is_some_and(|snapshot| !snapshot.active);
        let stopped = fleet
            .registry
            .load()?
            .agent(agent_id)
            .is_some_and(|record| record.lifecycle.lifecycle == AgentLifecycle::Stopped);
        if inactive && stopped {
            return Ok(());
        }
        if Instant::now() >= deadline {
            bail!("timed out waiting for Agent {agent_id} to stop");
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
}

fn agent_generation(fleet: &FleetHarness, agent_id: &AgentId) -> Result<u64> {
    Ok(fleet
        .registry
        .load()?
        .agent(agent_id)
        .with_context(|| format!("Agent {agent_id} missing from registry"))?
        .lifecycle
        .generation)
}

async fn seed_verified_agent_memory(
    agent: &AgentFixture,
    stable_key: &str,
    content: &str,
) -> Result<()> {
    seed_verified_agent_memory_with_receipt(agent, stable_key, content).await?;
    Ok(())
}

async fn seed_verified_agent_memory_with_receipt(
    agent: &AgentFixture,
    stable_key: &str,
    content: &str,
) -> Result<(String, String, codex_hepta_memory::SourceRevisionId)> {
    let store = CognitiveStore::open(&agent.layout).await?;
    ensure!(store.owner_agent_id() == &agent.agent_id);
    let access = CognitiveAccess::agent_private(agent.agent_id.clone());
    let scope = CognitiveScope::AgentPrivate;
    let now = i64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs())?;
    let citation = store
        .append_source(
            &access,
            &SourceDraft {
                scope: scope.clone(),
                kind: LedgerSourceKind::ExplicitMemoryDirective,
                event_key: format!("seed:{stable_key}"),
                content: content.as_bytes().to_vec(),
                observed_at_unix_seconds: now,
            },
        )
        .await?;
    let memory = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: stable_key.to_string(),
                revision: MemoryRevisionDraft {
                    scope,
                    content: content.to_string(),
                    verification: MemoryVerification::Verified,
                    lifecycle: MemoryLifecycleState::Active,
                    valid_from_unix_seconds: now,
                    valid_to_unix_seconds: None,
                    citations: vec![citation.clone()],
                },
            },
        )
        .await?;
    Ok((
        memory.id.memory_id.as_str().to_string(),
        citation.source_id.as_str().to_string(),
        citation,
    ))
}
