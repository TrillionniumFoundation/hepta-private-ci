use std::sync::Arc;
use std::sync::OnceLock;
use std::sync::Weak;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_core::CodexThread;
use codex_core::StartIfIdleSubmission;
use codex_core::StartThreadOptions;
use codex_core::TurnInputRequest;
use codex_core::config::Config;
use codex_extension_api::ExtensionFuture;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::ThreadIdleInput;
use codex_extension_api::ThreadLifecycleContributor;
use codex_features::Feature;
use codex_protocol::ThreadId;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::MultiAgentVersion;
use codex_protocol::protocol::SessionSource;
use codex_protocol::protocol::SubAgentSource;
use codex_protocol::user_input::UserInput;
use codex_rollout::RolloutItem;
use codex_rollout::RolloutRecorder;
use core_test_support::responses;
use core_test_support::test_codex::test_codex;
use pretty_assertions::assert_eq;
use test_case::test_case;
use tokio::sync::Notify;
use tokio::time::timeout;

struct RestartOnIdle {
    kind: ThreadKind,
    thread: OnceLock<(ThreadId, Weak<CodexThread>)>,
    submissions: async_channel::Sender<Result<StartIfIdleSubmission, String>>,
    calls: AtomicUsize,
    first_idle: Notify,
    release_first: Notify,
    second_idle: Notify,
}

impl ThreadLifecycleContributor<Config> for RestartOnIdle {
    fn on_thread_idle<'a>(&'a self, input: ThreadIdleInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            let Some((thread_id, thread)) = self.thread.get() else {
                return;
            };
            if input.thread_store.level_id() != thread_id.to_string() {
                return;
            }
            let Some(thread) = thread.upgrade() else {
                return;
            };
            match self.calls.fetch_add(1, Ordering::SeqCst) {
                0 => {
                    self.first_idle.notify_one();
                    if !matches!(self.kind, ThreadKind::RootClient) {
                        let submitted = thread
                            .start_turn_if_idle(user_message("continue from idle"))
                            .await
                            .map_err(|error| error.to_string());
                        self.submissions
                            .send(submitted)
                            .await
                            .expect("test receiver open");
                    }
                    self.release_first.notified().await;
                }
                1 => self.second_idle.notify_one(),
                _ => {}
            }
        })
    }
}

fn user_message(text: &str) -> TurnInputRequest {
    TurnInputRequest::user_input(vec![UserInput::Text {
        text: text.to_string(),
        text_elements: Vec::new(),
    }])
}

#[derive(Clone, Copy)]
enum ThreadKind {
    RootClient,
    RootIdleCallback,
    V2WorkerAtCapacity,
}

async fn next_completed_turn(thread: &CodexThread) -> Vec<(&'static str, String)> {
    timeout(Duration::from_secs(5), async {
        let mut observed = Vec::new();
        loop {
            let event = thread.next_event().await.expect("read turn event");
            match event.msg {
                EventMsg::TurnStarted(_) => observed.push(("started", event.id)),
                EventMsg::TurnComplete(completed) => {
                    let (items, _, errors) = RolloutRecorder::load_rollout_items(
                        &thread.rollout_path().expect("rollout path"),
                    )
                    .await
                    .expect("read rollout immediately after terminal notification");
                    assert_eq!(errors, 0);
                    let persisted = items.into_iter().find_map(|item| match item {
                        RolloutItem::EventMsg(EventMsg::TurnComplete(saved))
                            if saved.turn_id == completed.turn_id =>
                        {
                            Some(saved)
                        }
                        _ => None,
                    });
                    assert_eq!(
                        serde_json::to_value(persisted).expect("serialize persisted terminal"),
                        serde_json::to_value(Some(completed)).expect("serialize client terminal"),
                    );
                    observed.push(("completed", event.id));
                    break observed;
                }
                _ => {}
            }
        }
    })
    .await
    .expect("turn completes")
}

#[test_case(ThreadKind::RootClient; "root client")]
#[test_case(ThreadKind::RootIdleCallback; "root idle callback")]
#[test_case(ThreadKind::V2WorkerAtCapacity; "v2 worker at capacity")]
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn idle_continuation_preserves_terminal_order_and_durability(kind: ThreadKind) {
    let server = responses::start_mock_server().await;
    responses::mount_sse_sequence(
        &server,
        vec![
            responses::sse(vec![responses::ev_completed("first-response")]),
            responses::sse(vec![responses::ev_completed("second-response")]),
        ],
    )
    .await;
    let (submissions, submitted) = async_channel::bounded(1);
    let continuation = Arc::new(RestartOnIdle {
        kind,
        thread: OnceLock::new(),
        submissions,
        calls: AtomicUsize::new(0),
        first_idle: Notify::new(),
        release_first: Notify::new(),
        second_idle: Notify::new(),
    });
    let mut extensions = ExtensionRegistryBuilder::<Config>::new();
    extensions.thread_lifecycle_contributor(continuation.clone());
    let test = test_codex()
        .with_model("gpt-5.6-sol")
        .with_extensions(Arc::new(extensions.build()))
        .with_config(|config| {
            config
                .features
                .enable(Feature::MultiAgentV2)
                .expect("enable v2");
            // Includes the root, leaving exactly one execution slot for workers.
            config.multi_agent_v2.max_concurrent_threads_per_session = 2;
        })
        .build_with_auto_env(&server)
        .await
        .expect("build terminal-order fixture");
    let (thread_id, thread) = match kind {
        ThreadKind::RootClient | ThreadKind::RootIdleCallback => {
            (test.session_configured.thread_id, Arc::clone(&test.codex))
        }
        ThreadKind::V2WorkerAtCapacity => {
            let worker = test
                .thread_manager
                .start_thread(StartThreadOptions {
                    session_source: Some(SessionSource::SubAgent(SubAgentSource::Other(
                        "idle-continuation-worker".to_string(),
                    ))),
                    ..StartThreadOptions::new(test.config.clone())
                })
                .await
                .expect("start v2 worker");
            (worker.thread_id, worker.thread)
        }
    };
    assert_eq!(thread.multi_agent_version(), Some(MultiAgentVersion::V2));
    continuation
        .thread
        .set((thread_id, Arc::downgrade(&thread)))
        .expect("set fixture thread");
    let first = thread
        .start_turn_if_idle(user_message("first turn"))
        .await
        .expect("start first turn");
    let StartIfIdleSubmission::Started { turn_id: first_id } = first else {
        panic!("first turn was not started: {first:?}");
    };
    let mut observed = next_completed_turn(&thread).await;
    timeout(Duration::from_secs(5), continuation.first_idle.notified())
        .await
        .expect("first turn reaches its blocked idle callback");
    let second = match kind {
        ThreadKind::RootClient => thread
            .start_turn_if_idle(user_message("continue after terminal notification"))
            .await
            .expect("client can submit after completion"),
        ThreadKind::RootIdleCallback | ThreadKind::V2WorkerAtCapacity => {
            timeout(Duration::from_secs(5), submitted.recv())
                .await
                .expect("idle callback submits its continuation")
                .expect("submission channel open")
                .expect("idle continuation retains execution capacity")
        }
    };
    let StartIfIdleSubmission::Started { turn_id: second_id } = second else {
        panic!("idle continuation was not admitted: {second:?}");
    };

    observed.extend(next_completed_turn(&thread).await);
    assert_eq!(
        observed,
        vec![
            ("started", first_id.clone()),
            ("completed", first_id),
            ("started", second_id.clone()),
            ("completed", second_id),
        ]
    );
    // The first callback is deliberately still pending. Its completion
    // tracking must not suppress the next turn's idle notification.
    timeout(Duration::from_secs(5), continuation.second_idle.notified())
        .await
        .expect("second turn emits idle before the first callback returns");
    assert_eq!(continuation.calls.load(Ordering::SeqCst), 2);
    continuation.release_first.notify_one();
    thread
        .shutdown_and_wait()
        .await
        .expect("drain terminal callbacks and shut down");
}
