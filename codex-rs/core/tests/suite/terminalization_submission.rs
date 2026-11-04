use codex_config::types::Personality;
use codex_core::TurnInputRequest;
use codex_core::config::Config;
use codex_extension_api::ExtensionFuture;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::ThreadIdleInput;
use codex_extension_api::ThreadLifecycleContributor;
use codex_features::Feature;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::Op;
use codex_protocol::protocol::ThreadSettingsOverrides;
use codex_protocol::user_input::UserInput;
use core_test_support::responses;
use core_test_support::test_codex::test_codex;
use core_test_support::wait_for_event;
use futures::FutureExt;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use tokio::sync::Notify;
use tokio::time::timeout;

struct BlockingFirstIdle {
    entered: Arc<Notify>,
    release: Arc<Notify>,
    claimed: AtomicBool,
}

impl ThreadLifecycleContributor<Config> for BlockingFirstIdle {
    fn on_thread_idle<'a>(&'a self, _input: ThreadIdleInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            if !self.claimed.swap(true, Ordering::SeqCst) {
                self.entered.notify_one();
                self.release.notified().await;
            }
        })
    }
}

enum SubmissionPath {
    Plain,
    WithTrace,
}

async fn settings_after_turn_complete_wait_for_terminalization(path: SubmissionPath) {
    let server = responses::start_mock_server().await;
    let response = responses::mount_sse_once(
        &server,
        responses::sse(vec![
            responses::ev_response_created("response-1"),
            responses::ev_assistant_message("message-1", "Done"),
            responses::ev_completed("response-1"),
        ]),
    )
    .await;
    let idle_entered = Arc::new(Notify::new());
    let idle_release = Arc::new(Notify::new());
    let mut extensions = ExtensionRegistryBuilder::<Config>::new();
    extensions.thread_lifecycle_contributor(Arc::new(BlockingFirstIdle {
        entered: Arc::clone(&idle_entered),
        release: Arc::clone(&idle_release),
        claimed: AtomicBool::new(false),
    }));
    let test = test_codex()
        .with_config(|config| {
            config.personality = None;
            config
                .features
                .enable(Feature::Personality)
                .expect("enable personality updates");
        })
        .with_extensions(Arc::new(extensions.build()))
        .build_with_auto_env(&server)
        .await
        .expect("build real turn session");
    test.codex
        .start_or_steer_turn(TurnInputRequest::user_input(vec![UserInput::Text {
            text: "finish this turn".to_string(),
            text_elements: Vec::new(),
        }]))
        .await
        .expect("start real turn");
    wait_for_event(&test.codex, |event| {
        matches!(event, EventMsg::TurnComplete(_))
    })
    .await;
    timeout(Duration::from_secs(10), idle_entered.notified())
        .await
        .expect("terminalizer must reach the blocked idle callback");
    assert!(test.codex.pending_turn_terminalization().is_some());

    let submission = async {
        let op = Op::ThreadSettings {
            thread_settings: ThreadSettingsOverrides {
                personality: Some(Personality::Friendly),
                ..Default::default()
            },
        };
        match path {
            SubmissionPath::Plain => test.codex.submit(op).await,
            SubmissionPath::WithTrace => test.codex.submit_with_trace(op, /*trace*/ None).await,
        }
    };
    tokio::pin!(submission);
    let completed_early = submission.as_mut().now_or_never();
    idle_release.notify_one();
    assert!(
        completed_early.is_none(),
        "settings submission must wait for the exact terminalization owner"
    );
    let submission_id = timeout(Duration::from_secs(10), submission)
        .await
        .expect("submission must resume after terminalization")
        .expect("submit settings update");
    let applied = timeout(Duration::from_secs(10), async {
        loop {
            let event = test.codex.next_event().await.expect("session event");
            if event.id == submission_id {
                let EventMsg::ThreadSettingsApplied(applied) = event.msg else {
                    panic!("settings update was not applied: {:?}", event.msg);
                };
                break applied;
            }
        }
    })
    .await
    .expect("settings update must finish after the real turn");
    assert_eq!(
        applied.thread_settings.personality,
        Some(Personality::Friendly)
    );
    assert_eq!(
        test.codex.config_snapshot().await.personality,
        Some(Personality::Friendly)
    );
    assert_eq!(response.requests().len(), 1);
}

#[tokio::test]
async fn plain_settings_submission_waits_after_turn_complete() {
    settings_after_turn_complete_wait_for_terminalization(SubmissionPath::Plain).await;
}

#[tokio::test]
async fn traced_settings_submission_waits_after_turn_complete() {
    settings_after_turn_complete_wait_for_terminalization(SubmissionPath::WithTrace).await;
}
