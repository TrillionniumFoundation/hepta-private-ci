use super::FIRST_PROMPT;
use super::FIRST_TASK;
use super::SECOND_TASK;
use super::mount_completed_worker;
use super::mount_root_collaboration_call;
use anyhow::Result;
use codex_core::config::Config;
use codex_extension_api::ExtensionFuture;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::ThreadIdleInput;
use codex_extension_api::ThreadLifecycleContributor;
use codex_extension_api::ThreadStartInput;
use codex_features::Feature;
use codex_protocol::models::PermissionProfile;
use codex_protocol::models::PermissionProfileSnapshot;
use codex_protocol::protocol::EnvironmentConfig;
use codex_protocol::protocol::EnvironmentConfigState;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::SessionSource;
use codex_protocol::protocol::ThreadSettingsOverrides;
use codex_protocol::protocol::TurnEnvironmentSelections;
use core_test_support::submit_thread_settings;
use core_test_support::test_codex::test_codex;
use core_test_support::wait_for_event;
use pretty_assertions::assert_eq;
use serde_json::json;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;
use test_case::test_case;
use tokio::sync::Notify;
use tokio::time::timeout;

#[derive(Default)]
struct HeldSecondResidentFinish {
    children: AtomicUsize,
    entered: Notify,
    release: Notify,
}

struct HeldFinish;

impl ThreadLifecycleContributor<Config> for HeldSecondResidentFinish {
    fn on_thread_start<'a>(
        &'a self,
        input: ThreadStartInput<'a, Config>,
    ) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            if matches!(input.session_source, SessionSource::SubAgent(_))
                && self.children.fetch_add(1, Ordering::SeqCst) == 1
            {
                input.thread_store.insert(HeldFinish);
            }
        })
    }

    fn on_thread_idle<'a>(&'a self, input: ThreadIdleInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            if input.thread_store.get::<HeldFinish>().is_some() {
                self.entered.notify_one();
                self.release.notified().await;
            }
        })
    }
}

#[derive(Clone, Copy)]
enum WaitingCaller {
    Retained,
    Cancelled,
}

#[test_case(WaitingCaller::Retained; "waits for the captured finish")]
#[test_case(WaitingCaller::Cancelled; "cancelled wait retains resident accounting")]
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn residency_reload_waits_for_the_actual_terminal_owner(caller: WaitingCaller) -> Result<()> {
    const REPLACEMENT_PROMPT: &str = "replace the first resident while retaining its history";
    let server = core_test_support::responses::start_mock_server().await;
    mount_root_collaboration_call(
        &server,
        FIRST_PROMPT,
        "held-first-call",
        "spawn_agent",
        json!({"message": FIRST_TASK, "task_name": "first", "fork_turns": "none"}),
    )
    .await;
    mount_completed_worker(&server, FIRST_TASK, "held-first-call").await;
    mount_root_collaboration_call(
        &server,
        REPLACEMENT_PROMPT,
        "held-replacement-call",
        "spawn_agent",
        json!({"message": SECOND_TASK, "task_name": "replacement", "fork_turns": "none"}),
    )
    .await;
    mount_completed_worker(&server, SECOND_TASK, "held-replacement-call").await;

    let held = Arc::new(HeldSecondResidentFinish::default());
    let mut extensions = ExtensionRegistryBuilder::<Config>::new();
    extensions.thread_lifecycle_contributor(held.clone());
    let mut builder = test_codex()
        .with_model("gpt-5.6-sol")
        .with_extensions(Arc::new(extensions.build()))
        .with_config(|config| {
            for feature in [Feature::Collab, Feature::MultiAgentV2] {
                config
                    .features
                    .enable(feature)
                    .expect("test config should allow feature update");
            }
            config.multi_agent_v2.max_concurrent_threads_per_session = 2;
        });
    let test = builder.build_with_auto_env(&server).await?;
    let mut child_environment = test.executor_environment().selection().clone();
    child_environment.config = EnvironmentConfigState::Ready(EnvironmentConfig {
        allow_login_shell: test.config.permissions.allow_login_shell,
        permission_profile: PermissionProfileSnapshot::legacy(PermissionProfile::read_only()),
        shell_environment_policy: Default::default(),
        exec_policy: None,
        mcp_policy: None,
        network_policy: None,
        selected_capability_roots: Vec::new(),
    });
    submit_thread_settings(
        &test.codex,
        ThreadSettingsOverrides {
            environments: Some(TurnEnvironmentSelections::new(
                test.config.cwd.clone(),
                vec![child_environment],
            )),
            ..Default::default()
        },
    )
    .await?;
    let mut created_threads = test.thread_manager.subscribe_thread_created();
    test.submit_text_turn(FIRST_PROMPT).await?;
    let first_id = created_threads.recv().await?;
    let first = test.thread_manager.get_thread(first_id).await?;
    wait_for_event(first.as_ref(), |event| {
        matches!(event, EventMsg::TurnComplete(_))
    })
    .await;
    let original_cwd = first.config_snapshot().await.cwd().clone();
    let original_environments = first.environment_selections().await;
    test.submit_text_turn(REPLACEMENT_PROMPT).await?;
    let replacement_id = created_threads.recv().await?;
    let replacement = test.thread_manager.get_thread(replacement_id).await?;
    wait_for_event(replacement.as_ref(), |event| {
        matches!(event, EventMsg::TurnComplete(_))
    })
    .await;
    timeout(Duration::from_secs(2), held.entered.notified()).await?;
    assert!(test.thread_manager.get_thread(first_id).await.is_err());

    let mut reload = Box::pin(
        test.thread_manager
            .ensure_multi_agent_v2_child_loaded(first_id),
    );
    // The actual Finish callback is held, so the public reload must remain
    // pending instead of rejecting capacity or evicting its unretired owner.
    let pending = timeout(Duration::from_secs(2), reload.as_mut()).await;
    if pending.is_ok() {
        held.release.notify_one();
    }
    assert!(
        pending.is_err(),
        "reload settled while its only reclaimable resident still owned Finish: {pending:?}"
    );
    assert!(test.thread_manager.get_thread(replacement_id).await.is_ok());
    assert_eq!(test.thread_manager.list_thread_ids().await.len(), 2);

    if matches!(caller, WaitingCaller::Cancelled) {
        drop(reload);
        reload = Box::pin(
            test.thread_manager
                .ensure_multi_agent_v2_child_loaded(first_id),
        );
        let pending = timeout(Duration::from_secs(2), reload.as_mut()).await;
        if pending.is_ok() {
            held.release.notify_one();
        }
        assert!(
            pending.is_err(),
            "cancelling the first wait exposed unretired resident capacity: {pending:?}"
        );
        assert!(test.thread_manager.get_thread(replacement_id).await.is_ok());
        assert_eq!(test.thread_manager.list_thread_ids().await.len(), 2);
    }
    held.release.notify_one();
    timeout(Duration::from_secs(2), reload).await??;

    let reloaded = test.thread_manager.get_thread(first_id).await?;
    assert_eq!(
        reloaded.environment_selections().await,
        original_environments
    );
    assert_eq!(reloaded.config_snapshot().await.cwd(), &original_cwd);
    assert!(
        test.thread_manager
            .get_thread(replacement_id)
            .await
            .is_err()
    );
    assert_eq!(test.thread_manager.list_thread_ids().await.len(), 2);
    Ok(())
}
