use std::future::Future;
use std::sync::Arc;
use std::sync::Barrier;
use std::task::Context;
use std::task::Poll;
use std::task::Waker;

use codex_api::EncodedRequestBodyObserver;
use codex_api::EncodedRequestTerminal;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::PromptRuntimeExactAttemptV2;
use super::PromptRuntimeExactBodyObserver;
use super::check_deadline;
use crate::PromptRuntimeAttachmentV1;
use crate::PromptRuntimeDeveloperFragmentV1;
use crate::PromptRuntimeHost;
use crate::PromptRuntimeHostError;
use crate::PromptRuntimeRequestKindV2;
use crate::PromptRuntimeTransportV2;

const BODY: &[u8] = br#"{"model":"model","input":[{"role":"developer","content":[{"type":"input_text","text":"approved-context"}]}]}"#;

fn attempt() -> PromptRuntimeExactAttemptV2 {
    PromptRuntimeExactAttemptV2 {
        thread_id: "thread".to_owned(),
        turn_id: "turn".to_owned(),
        attempt_id: "attempt".to_owned(),
        request_binding_id: "binding".to_owned(),
        request_kind: PromptRuntimeRequestKindV2::Turn,
        provider_id: "provider".to_owned(),
        provider_config_digest: Digest32::of_bytes(b"config"),
        model: "model".to_owned(),
        transport: PromptRuntimeTransportV2::Http,
        endpoint_digest: Digest32::of_bytes(b"endpoint"),
        logical_request_digest: Digest32::of_bytes(b"logical"),
        provider_wire_semantic_digest: Digest32::of_bytes(b"wire"),
        ephemeral_input_digest: None,
        ephemeral_input_witness_digest: None,
        previous_response_id_digest: None,
        generate: true,
    }
}

fn observer() -> PromptRuntimeExactBodyObserver {
    let host = PromptRuntimeHost::new(
        "context-test-host",
        |_| Box::pin(async { Ok(None) }),
        |_| Box::pin(async { Ok(()) }),
        |_| Box::pin(async { Ok(()) }),
    )
    .expect("host")
    .with_final_request_observer(|_| {
        Box::pin(std::future::pending::<Result<(), PromptRuntimeHostError>>())
    });
    let fragment = PromptRuntimeDeveloperFragmentV1::new("approved-context").expect("fragment");
    let attachment = PromptRuntimeAttachmentV1::new(
        StableId::new("compilation").expect("id"),
        Digest32::of_bytes(b"attachment"),
        fragment.content_digest,
        "model",
        u64::MAX,
        vec![fragment],
    )
    .expect("attachment");
    PromptRuntimeExactBodyObserver::new(host, attachment)
}

#[test]
fn concurrent_body_callbacks_have_one_exclusive_claim() {
    let observer = Arc::new(observer());
    observer.bind_attempt(attempt()).expect("bind");
    let barrier = Arc::new(Barrier::new(2));
    let handles = (0..2)
        .map(|_| {
            let observer = Arc::clone(&observer);
            let barrier = Arc::clone(&barrier);
            std::thread::spawn(move || {
                barrier.wait();
                observer.begin_body(Digest32::of_bytes(BODY)).is_ok()
            })
        })
        .collect::<Vec<_>>();
    let claimed = handles
        .into_iter()
        .map(|handle| usize::from(handle.join().expect("thread")))
        .sum::<usize>();
    assert_eq!(claimed, 1);
}

#[test]
fn cancellation_before_owner_callback_can_clear_binding() {
    let observer = observer();
    let attempt = attempt();
    observer.bind_attempt(attempt.clone()).expect("bind");
    observer.cancel_attempt(&attempt);
    observer.bind_attempt(attempt).expect("safe rebind");
}

#[test]
fn cancelled_in_flight_callback_cannot_be_rearmed() {
    let observer = observer();
    let attempt = attempt();
    observer.bind_attempt(attempt.clone()).expect("bind");
    let mut callback = observer.observe_encoded_body(BODY);
    let mut context = Context::from_waker(Waker::noop());
    assert_eq!(callback.as_mut().poll(&mut context), Poll::Pending);
    drop(callback);
    observer.cancel_attempt(&attempt);
    assert!(observer.bind_attempt(attempt).is_err());
    assert!(observer.begin_body(Digest32::of_bytes(BODY)).is_err());
}

#[test]
fn finishing_requires_the_same_request_digest() {
    let observer = observer();
    let attempt = attempt();
    let digest = Digest32::of_bytes(BODY);
    observer.bind_attempt(attempt.clone()).expect("bind");
    observer.begin_body(digest).expect("claim");
    assert!(observer.finish_body(&attempt, Digest32::of_bytes(b"other")).is_err());
    observer.finish_body(&attempt, digest).expect("same proof");
}

#[test]
fn indeterminate_and_abandoned_observations_do_not_unlock_dispatch() {
    for terminal in [
        EncodedRequestTerminal::Indeterminate { reason_code: "lost".to_owned() },
        EncodedRequestTerminal::Abandoned { reason_code: "cancelled".to_owned() },
    ] {
        let observer = observer();
        let attempt = attempt();
        let digest = Digest32::of_bytes(BODY);
        observer.bind_attempt(attempt.clone()).expect("bind");
        observer.begin_body(digest).expect("claim");
        observer.finish_body(&attempt, digest).expect("proof");
        observer.record_terminal(terminal).expect("retain unresolved");
        assert!(observer.bind_attempt(attempt).is_err());
        assert!(observer.record_terminal(EncodedRequestTerminal::Completed {
            response_id: "late-unbound-terminal".to_owned(),
        }).is_err());
    }
}

#[test]
fn terminal_during_proof_does_not_reset_the_claim() {
    let observer = observer();
    let attempt = attempt();
    observer.bind_attempt(attempt.clone()).expect("bind");
    observer.begin_body(Digest32::of_bytes(BODY)).expect("claim");
    assert!(observer.record_terminal(EncodedRequestTerminal::Rejected {
        reason_code: "observer-failure".to_owned(),
    }).is_err());
    assert!(observer.bind_attempt(attempt).is_err());
}

#[test]
fn expiry_is_exclusive_including_after_expensive_preparation() {
    assert_eq!(check_deadline(99, 100), Ok(()));
    assert_eq!(check_deadline(100, 100), Err("context_attachment_expired".to_owned()));
    assert_eq!(check_deadline(101, 100), Err("context_attachment_expired".to_owned()));
}

#[test]
fn observer_debug_never_contains_raw_context() {
    assert!(!format!("{:?}", observer()).contains("approved-context"));
}
