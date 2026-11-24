use codex_core::TurnInputRequest;
use codex_core::config::Config;
use codex_extension_api::ExtensionFuture;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::ThreadIdleInput;
use codex_extension_api::ThreadLifecycleContributor;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::Op;
use codex_protocol::protocol::ThreadSettingsOverrides;
use codex_protocol::user_input::UserInput;
use core_test_support::responses::ev_completed;
use core_test_support::responses::ev_response_created;
use core_test_support::responses::mount_sse_once;
use core_test_support::responses::sse;
use core_test_support::responses::start_mock_server;
use core_test_support::test_codex::test_codex;
use core_test_support::wait_for_event;
use core_test_support::wait_for_event_match;
use futures::FutureExt;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use tokio::sync::Notify;
use tokio::time::timeout;

#[derive(Default)]
struct IdleBarrier {
    armed: AtomicBool,
    entered: Notify,
    release: Notify,
}

impl ThreadLifecycleContributor<Config> for IdleBarrier {
    fn on_thread_idle<'a>(&'a self, _input: ThreadIdleInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            if self.armed.swap(false, Ordering::SeqCst) {
                self.entered.notify_one();
                self.release.notified().await;
            }
        })
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn terminal_receipt_admits_public_settings_and_next_turn_after_idle_cleanup()
-> anyhow::Result<()> {
    let server = start_mock_server().await;
    let barrier = Arc::new(IdleBarrier::default());
    let mut extensions = ExtensionRegistryBuilder::<Config>::new();
    extensions.thread_lifecycle_contributor(barrier.clone());
    let test = test_codex()
        .with_extensions(Arc::new(extensions.build()))
        .build_with_auto_env(&server)
        .await?;
    let first = mount_sse_once(
        &server,
        sse(vec![ev_response_created("first"), ev_completed("first")]),
    )
    .await;
    barrier.armed.store(true, Ordering::SeqCst);
    test.codex
        .start_or_steer_turn(TurnInputRequest::user_input(vec![UserInput::Text {
            text: "first turn".to_string(),
            text_elements: Vec::new(),
        }]))
        .await?;
    timeout(Duration::from_secs(10), barrier.entered.notified()).await?;

    // The lifecycle is held at a real extension boundary. All prior queued
    // events can be read, but terminal receipt must not precede that cleanup.
    while let Some(event) = test.codex.next_event().now_or_never() {
        assert!(!matches!(
            event?.msg,
            EventMsg::TurnComplete(_) | EventMsg::TurnAborted(_)
        ));
    }
    barrier.release.notify_one();
    wait_for_event(&test.codex, |event| {
        matches!(event, EventMsg::TurnComplete(_))
    })
    .await;
    assert_eq!(first.requests().len(), 1);

    test.codex
        .submit(Op::ThreadSettings {
            thread_settings: ThreadSettingsOverrides::default(),
        })
        .await?;
    wait_for_event_match(&test.codex, |event| match event {
        EventMsg::ThreadSettingsApplied(_) => Some(Ok(())),
        EventMsg::Error(error) => Some(Err(anyhow::anyhow!(error.message.clone()))),
        _ => None,
    })
    .await?;

    let second = mount_sse_once(
        &server,
        sse(vec![ev_response_created("second"), ev_completed("second")]),
    )
    .await;
    test.codex
        .start_or_steer_turn(TurnInputRequest::user_input(vec![UserInput::Text {
            text: "second turn immediately after terminal".to_string(),
            text_elements: Vec::new(),
        }]))
        .await?;
    wait_for_event(&test.codex, |event| {
        matches!(event, EventMsg::TurnComplete(_))
    })
    .await;
    assert_eq!(second.requests().len(), 1);
    test.codex.shutdown_and_wait().await?;
    Ok(())
}
