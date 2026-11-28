#![allow(clippy::expect_used)]

use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

use anyhow::Context;
use codex_analytics::AnalyticsEventsClient;
use codex_core::IdleWorkPriority;
use codex_core::StartIfIdleSubmission;
use codex_core::TurnInputRequest;
use codex_core::TurnInputSubmission;
use codex_core::config::Config;
use codex_extension_api::ExtensionData;
use codex_extension_api::ExtensionFuture;
use codex_extension_api::ExtensionRegistry;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::ThreadIdleCause;
use codex_extension_api::ThreadIdleInput;
use codex_extension_api::ThreadLifecycleContributor;
use codex_extension_api::ThreadStartInput;
use codex_goal_extension::GoalExtensionConfig;
use codex_goal_extension::GoalObjectiveUpdate;
use codex_goal_extension::GoalService;
use codex_goal_extension::GoalSetRequest;
use codex_goal_extension::GoalTokenBudgetUpdate;
use codex_goal_extension::install_with_backend;
use codex_protocol::protocol::AgentStatus;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::SessionSource;
use codex_protocol::protocol::ThreadGoalStatus;
use codex_protocol::user_input::UserInput;
use codex_state::SqliteConfig;
use core_test_support::responses;
use core_test_support::responses::start_mock_server;
use core_test_support::test_codex::TestCodex;
use core_test_support::test_codex::test_codex;
use core_test_support::wait_for_event_match;
use pretty_assertions::assert_eq;
use tokio::sync::Notify;
use tokio::sync::oneshot;

struct FirstIdleGate {
    first: AtomicBool,
    entered: Notify,
    release: Notify,
}

impl FirstIdleGate {
    fn new() -> Self {
        Self {
            first: AtomicBool::new(true),
            entered: Notify::new(),
            release: Notify::new(),
        }
    }
}

impl ThreadLifecycleContributor<codex_core::config::Config> for FirstIdleGate {
    fn on_thread_idle<'a>(&'a self, _input: ThreadIdleInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            if self.first.swap(false, Ordering::SeqCst) {
                self.entered.notify_one();
                self.release.notified().await;
            }
        })
    }
}

struct LiveGoal {
    registry: ExtensionRegistry<()>,
    session_store: ExtensionData,
    thread_store: ExtensionData,
    service: Arc<GoalService>,
}

impl LiveGoal {
    async fn install(test: &TestCodex) -> anyhow::Result<Self> {
        let state = test.codex.state_db().context("state runtime unavailable")?;
        let service = Arc::new(GoalService::new());
        let mut builder = ExtensionRegistryBuilder::<()>::new();
        install_with_backend(
            &mut builder,
            state,
            AnalyticsEventsClient::disabled(),
            None,
            Arc::downgrade(&test.thread_manager),
            Arc::clone(&service),
            |_| GoalExtensionConfig {
                enabled: true,
                max_goal_token_budget: None,
            },
        );
        let registry = builder.build();
        let session_store = ExtensionData::new("live-goal-cleanup-test");
        let thread_store = ExtensionData::new(test.session_configured.thread_id.to_string());
        for contributor in registry.thread_lifecycle_contributors() {
            contributor
                .on_thread_start(ThreadStartInput {
                    config: &(),
                    session_source: &SessionSource::Cli,
                    installation_id: "11111111-1111-4111-8111-111111111111",
                    persistent_thread_state_available: true,
                    environments: &[],
                    mcp_resource_client: None,
                    extension_metrics: None,
                    session_store: &session_store,
                    thread_store: &thread_store,
                })
                .await;
        }
        Ok(Self {
            registry,
            session_store,
            thread_store,
            service,
        })
    }

    async fn set_active(&self, test: &TestCodex) -> anyhow::Result<()> {
        let state = test.codex.state_db().context("state runtime unavailable")?;
        let outcome = self
            .service
            .set_thread_goal(
                state.as_ref(),
                GoalSetRequest {
                    thread_id: test.session_configured.thread_id,
                    objective: GoalObjectiveUpdate::Set("preserve exact cleanup ownership"),
                    status: Some(ThreadGoalStatus::Active),
                    token_budget: GoalTokenBudgetUpdate::Set(Some(1_000)),
                    max_goal_token_budget: None,
                },
            )
            .await?;
        outcome.apply_runtime_effects(&self.service).await;
        Ok(())
    }

    async fn notify_idle(&self) {
        for contributor in self.registry.thread_lifecycle_contributors() {
            contributor
                .on_thread_idle(ThreadIdleInput {
                    cause: ThreadIdleCause::Completed,
                    session_store: &self.session_store,
                    thread_store: &self.thread_store,
                })
                .await;
        }
    }
}

fn configure_goal_state(config: &mut Config) {
    config.include_environment_context = false;
    // A fresh SQLite home lets the real runtime create its own private directory.
    config.sqlite = SqliteConfig::new_for_testing(config.codex_home.join("goal-state"));
}

fn user_request(text: &str) -> TurnInputRequest {
    TurnInputRequest::user_input(vec![UserInput::Text {
        text: text.to_string(),
        text_elements: Vec::new(),
    }])
}

async fn hold_initial_turn(test: &TestCodex, gate: &FirstIdleGate) -> anyhow::Result<String> {
    let submitted = test
        .codex
        .start_or_steer_turn(user_request("initial fenced user turn"))
        .await?;
    gate.entered.notified().await;
    // Public terminal delivery waits for this exact owner. Capture the real
    // admitted turn ID without waiting for the gate that this fixture holds.
    let TurnInputSubmission::Started { turn_id } = submitted else {
        anyhow::bail!("initial user turn must acquire normal idle admission");
    };
    Ok(turn_id)
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn external_goal_set_defers_once_until_exact_cleanup_owner_finishes() -> anyhow::Result<()> {
    let server = start_mock_server().await;
    let responses = responses::mount_sse_sequence(
        &server,
        ["initial-fenced", "one-goal-continuation"]
            .into_iter()
            .map(responses::sse_completed)
            .collect(),
    )
    .await;
    let gate = Arc::new(FirstIdleGate::new());
    let mut extensions = ExtensionRegistryBuilder::new();
    extensions.thread_lifecycle_contributor(gate.clone());
    let test = test_codex()
        .with_extensions(Arc::new(extensions.build()))
        .with_config(configure_goal_state)
        .build_with_auto_env(&server)
        .await?;

    tokio::time::timeout(Duration::from_secs(10), async {
        let initial = hold_initial_turn(&test, gate.as_ref()).await?;
        // This fixture starts just one turn and holds its first idle callback.
        // Capture the registered owner before scheduling any other turn.
        let finish = test
            .codex
            .pending_admission_fence_completion()
            .context("held idle callback must retain its finish owner")?;
        let goal = LiveGoal::install(&test).await?;
        // This public external-set entry point must defer too, even without a
        // Core Goal lifecycle callback wrapping it.
        goal.set_active(&test).await?;
        for _ in 0..64 {
            goal.notify_idle().await;
        }
        assert_eq!(responses.requests().len(), 1);
        // Goal owns exactly one automatic slot; all other 30 automatic slots
        // and Queue's reserved slot remain available while cleanup is held.
        for _ in 0..30 {
            test.codex.defer_idle_work(
                IdleWorkPriority::AutomaticContinuation,
                test.codex
                    .pending_admission_fence_completion()
                    .expect("initial cleanup remains held"),
                async {},
            )?;
        }
        test.codex.defer_idle_work(
            IdleWorkPriority::QueuedInput,
            test.codex
                .pending_admission_fence_completion()
                .expect("initial cleanup remains held"),
            async {},
        )?;
        assert!(
            test.codex
                .defer_idle_work(
                    IdleWorkPriority::AutomaticContinuation,
                    test.codex
                        .pending_admission_fence_completion()
                        .expect("initial cleanup remains held"),
                    async {},
                )
                .is_err()
        );
        gate.release.notify_one();
        finish.await;
        let published_initial = wait_for_event_match(test.codex.as_ref(), |event| match event {
            EventMsg::TurnComplete(completed) => Some(completed.turn_id.clone()),
            _ => None,
        })
        .await;
        assert_eq!(published_initial, initial);
        let continued = wait_for_event_match(test.codex.as_ref(), |event| match event {
            EventMsg::TurnComplete(completed) if completed.turn_id != initial => {
                Some(completed.turn_id.clone())
            }
            _ => None,
        })
        .await;
        assert_ne!(continued, initial);
        assert_eq!(responses.requests().len(), 2);
        test.codex.shutdown_and_wait().await?;
        anyhow::Ok(())
    })
    .await??;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn automatic_goal_rechecks_generation_after_queued_turn_finishes() -> anyhow::Result<()> {
    let server = start_mock_server().await;
    let responses = responses::mount_sse_sequence(
        &server,
        ["initial-fenced", "newer-queued-turn"]
            .into_iter()
            .map(responses::sse_completed)
            .collect(),
    )
    .await;
    let gate = Arc::new(FirstIdleGate::new());
    let mut extensions = ExtensionRegistryBuilder::new();
    extensions.thread_lifecycle_contributor(gate.clone());
    let test = test_codex()
        .with_extensions(Arc::new(extensions.build()))
        .with_config(configure_goal_state)
        .build_with_auto_env(&server)
        .await?;

    tokio::time::timeout(Duration::from_secs(10), async {
        let initial = hold_initial_turn(&test, gate.as_ref()).await?;
        // This fixture starts just one turn and holds its first idle callback.
        // Capture the registered owner before scheduling any other turn.
        let finish = test
            .codex
            .pending_admission_fence_completion()
            .context("held idle callback must retain its finish owner")?;
        let goal = LiveGoal::install(&test).await?;
        goal.set_active(&test).await?;
        let queued_thread = Arc::clone(&test.codex);
        let expected_initial = initial.clone();
        let (queued_tx, queued_rx) = oneshot::channel();
        // Register Queue after Goal, then keep its callback until the newer
        // turn is fully idle again. A status-only recheck would miss this race.
        test.codex.defer_idle_work(
            IdleWorkPriority::QueuedInput,
            test.codex
                .pending_admission_fence_completion()
                .expect("initial cleanup remains held"),
            async move {
                let outcome = async {
                    let submitted = queued_thread
                        .start_turn_if_idle(user_request("newer queued user turn"))
                        .await?;
                    let StartIfIdleSubmission::Started { turn_id } = submitted else {
                        anyhow::bail!("queued turn must acquire normal idle admission");
                    };
                    let published_initial =
                        wait_for_event_match(queued_thread.as_ref(), |event| match event {
                            EventMsg::TurnComplete(completed) => Some(completed.turn_id.clone()),
                            _ => None,
                        })
                        .await;
                    assert_eq!(published_initial, expected_initial);
                    wait_for_event_match(queued_thread.as_ref(), |event| match event {
                        EventMsg::TurnComplete(completed) if completed.turn_id == turn_id => {
                            Some(())
                        }
                        _ => None,
                    })
                    .await;
                    anyhow::Ok(queued_thread.agent_status().await)
                }
                .await;
                let _ = queued_tx.send(outcome);
            },
        )?;
        let (automatic_tx, automatic_rx) = oneshot::channel();
        test.codex.defer_idle_work(
            IdleWorkPriority::AutomaticContinuation,
            test.codex
                .pending_admission_fence_completion()
                .expect("initial cleanup remains held"),
            async move {
                let _ = automatic_tx.send(());
            },
        )?;
        gate.release.notify_one();
        finish.await;
        let queued_status = queued_rx.await??;
        automatic_rx.await?;
        assert_eq!(test.codex.agent_status().await, queued_status);
        assert_eq!(responses.requests().len(), 2);
        test.codex.shutdown_and_wait().await?;
        anyhow::Ok(())
    })
    .await??;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn deferred_goal_does_not_submit_after_loaded_thread_replacement() -> anyhow::Result<()> {
    let server = start_mock_server().await;
    let responses =
        responses::mount_sse_sequence(&server, vec![responses::sse_completed("initial-fenced")])
            .await;
    let gate = Arc::new(FirstIdleGate::new());
    let mut extensions = ExtensionRegistryBuilder::new();
    extensions.thread_lifecycle_contributor(gate.clone());
    let test = test_codex()
        .with_extensions(Arc::new(extensions.build()))
        .with_config(configure_goal_state)
        .build_with_auto_env(&server)
        .await?;

    tokio::time::timeout(Duration::from_secs(10), async {
        let initial = hold_initial_turn(&test, gate.as_ref()).await?;
        // This fixture starts just one turn and holds its first idle callback.
        // Capture the registered owner before scheduling any other turn.
        let finish = test
            .codex
            .pending_admission_fence_completion()
            .context("held idle callback must retain its finish owner")?;
        let goal = LiveGoal::install(&test).await?;
        goal.set_active(&test).await?;
        let (automatic_tx, automatic_rx) = oneshot::channel();
        test.codex.defer_idle_work(
            IdleWorkPriority::AutomaticContinuation,
            test.codex
                .pending_admission_fence_completion()
                .expect("initial cleanup remains held"),
            async move {
                let _ = automatic_tx.send(());
            },
        )?;
        let thread_id = test.session_configured.thread_id;
        let removed = test
            .thread_manager
            .remove_thread(&thread_id)
            .await
            .context("original thread is registered")?;
        assert!(Arc::ptr_eq(&removed, &test.codex));
        // Resume must honor the live local writer guard. Close that writer
        // through its public flush-and-close lifecycle while the independent
        // Core finish owner is still held, then replace the loaded Arc.
        test.thread_store.shutdown_thread(thread_id).await?;
        let resumed = test
            .thread_manager
            .resume_thread_from_rollout(
                test.config.clone(),
                test.codex.rollout_path().context("rollout path missing")?,
                test.thread_manager.auth_manager(),
                None,
                Default::default(),
            )
            .await?;
        assert_eq!(resumed.thread_id, thread_id);
        assert!(!Arc::ptr_eq(&resumed.thread, &test.codex));
        assert!(Arc::ptr_eq(
            &test.thread_manager.get_thread(thread_id).await?,
            &resumed.thread,
        ));
        let old_status = test.codex.agent_status().await;
        let resumed_status = resumed.thread.agent_status().await;
        assert!(!matches!(old_status, AgentStatus::Running));
        assert!(!matches!(resumed_status, AgentStatus::Running));
        gate.release.notify_one();
        finish.await;
        let published_initial = wait_for_event_match(test.codex.as_ref(), |event| match event {
            EventMsg::TurnComplete(completed) => Some(completed.turn_id.clone()),
            _ => None,
        })
        .await;
        assert_eq!(published_initial, initial);
        automatic_rx.await?;
        assert_eq!(test.codex.agent_status().await, old_status);
        assert_eq!(resumed.thread.agent_status().await, resumed_status);
        assert_eq!(responses.requests().len(), 1);
        test.codex.shutdown_and_wait().await?;
        resumed.thread.shutdown_and_wait().await?;
        anyhow::Ok(())
    })
    .await??;
    Ok(())
}
