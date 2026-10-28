use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_core::NotSubmittedReason;
use codex_core::StartIfIdleSubmission;
use codex_core::TurnInputRequest;
use codex_core::config::Config;
use codex_extension_api::ExtensionFuture;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::ThreadIdleInput;
use codex_extension_api::ThreadLifecycleContributor;
use codex_protocol::protocol::EventMsg;
use codex_protocol::user_input::UserInput;
use core_test_support::responses;
use core_test_support::test_codex::test_codex;
use core_test_support::wait_for_event_match;
use pretty_assertions::assert_eq;
use tokio::sync::Notify;

#[derive(Default)]
struct FirstIdleGate {
    entered: Notify,
    release: Notify,
    calls: AtomicUsize,
}

impl ThreadLifecycleContributor<Config> for FirstIdleGate {
    fn on_thread_idle<'a>(&'a self, _input: ThreadIdleInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            if self.calls.fetch_add(1, Ordering::AcqRel) == 0 {
                self.entered.notify_one();
                self.release.notified().await;
            }
        })
    }
}

fn request(text: &str) -> TurnInputRequest {
    TurnInputRequest::user_input(vec![UserInput::Text {
        text: text.to_owned(),
        text_elements: Vec::new(),
    }])
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn public_completion_survives_cancel_and_waits_for_real_idle_cleanup() -> anyhow::Result<()> {
    let server = responses::start_mock_server().await;
    let responses = responses::mount_sse_sequence(
        &server,
        vec![
            responses::sse_completed("first"),
            responses::sse_completed("second"),
        ],
    )
    .await;
    let gate = Arc::new(FirstIdleGate::default());
    let mut extensions = ExtensionRegistryBuilder::new();
    extensions.thread_lifecycle_contributor(gate.clone());
    let test = test_codex()
        .with_extensions(Arc::new(extensions.build()))
        .build_with_auto_env(&server)
        .await?;
    let first = test.codex.start_turn_if_idle(request("first")).await?;
    let StartIfIdleSubmission::Started { turn_id: first_id } = first else {
        panic!("initial turn must be admitted: {first:?}");
    };
    tokio::time::timeout(Duration::from_secs(5), gate.entered.notified()).await?;
    assert!(test.codex.pending_turn_cleanup().is_some());
    assert!(
        tokio::time::timeout(
            Duration::from_millis(30),
            wait_for_event_match(test.codex.as_ref(), |event| {
                matches!(event, EventMsg::TurnComplete(_)).then_some(())
            }),
        )
        .await
        .is_err()
    );
    assert_eq!(
        test.codex.start_turn_if_idle(request("too early")).await?,
        StartIfIdleSubmission::NotSubmitted {
            reason: NotSubmittedReason::NotIdle,
        },
    );
    gate.release.notify_one();
    let completed = wait_for_event_match(test.codex.as_ref(), |event| match event {
        EventMsg::TurnComplete(event) => Some(event.turn_id.clone()),
        _ => None,
    })
    .await;
    assert_eq!(completed, first_id);
    let next = test.codex.start_turn_if_idle(request("second")).await?;
    let StartIfIdleSubmission::Started { turn_id: next_id } = next else {
        panic!("public completion must leave normal admission ready: {next:?}");
    };
    let completed = wait_for_event_match(test.codex.as_ref(), |event| match event {
        EventMsg::TurnComplete(event) => Some(event.turn_id.clone()),
        _ => None,
    })
    .await;
    assert_eq!(completed, next_id);
    assert_eq!(gate.calls.load(Ordering::Acquire), 2);
    assert_eq!(responses.requests().len(), 2);
    Ok(())
}
