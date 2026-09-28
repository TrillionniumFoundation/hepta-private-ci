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
use crate::PromptRuntimeTerminalOutcomeV1;
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
    assert!(
        observer
            .finish_body(&attempt, Digest32::of_bytes(b"other"))
            .is_err()
    );
    observer.finish_body(&attempt, digest).expect("same proof");
}

#[test]
fn identity_bound_indeterminate_does_not_unlock_dispatch() {
    let observer = observer();
    let attempt = attempt();
    let digest = Digest32::of_bytes(BODY);
    observer.bind_attempt(attempt.clone()).expect("bind");
    observer.begin_body(digest).expect("claim");
    observer.finish_body(&attempt, digest).expect("proof");
    observer
        .record_terminal(&attempt, PromptRuntimeTerminalOutcomeV1::Indeterminate)
        .expect("retain unresolved");
    assert!(observer.bind_attempt(attempt.clone()).is_err());
    assert!(
        observer
            .record_terminal(&attempt, PromptRuntimeTerminalOutcomeV1::Delivered)
            .is_err()
    );
}

#[test]
fn terminal_during_proof_does_not_reset_the_claim() {
    let observer = observer();
    let attempt = attempt();
    observer.bind_attempt(attempt.clone()).expect("bind");
    observer
        .begin_body(Digest32::of_bytes(BODY))
        .expect("claim");
    assert!(
        observer
            .record_terminal(&attempt, PromptRuntimeTerminalOutcomeV1::Rejected)
            .is_err()
    );
    assert!(observer.bind_attempt(attempt).is_err());
}

#[test]
fn expiry_is_exclusive_including_after_expensive_preparation() {
    assert_eq!(check_deadline(99, 100), Ok(()));
    assert_eq!(
        check_deadline(100, 100),
        Err("context_attachment_expired".to_owned())
    );
    assert_eq!(
        check_deadline(101, 100),
        Err("context_attachment_expired".to_owned())
    );
}

#[test]
fn observer_debug_never_contains_raw_context() {
    assert!(!format!("{:?}", observer()).contains("approved-context"));
}

#[test]
fn unbound_transport_notifications_cannot_mutate_any_attempt_phase() {
    for proven in [false, true] {
        let observer = observer();
        let attempt = attempt();
        let digest = Digest32::of_bytes(BODY);
        observer.bind_attempt(attempt.clone()).expect("bind");
        observer.begin_body(digest).expect("claim");
        if proven {
            observer.finish_body(&attempt, digest).expect("proof");
        }
        let before = observer.phase.lock().expect("phase").clone();
        for terminal in [
            EncodedRequestTerminal::Completed {
                response_id: "late-A".to_owned(),
            },
            EncodedRequestTerminal::Rejected {
                reason_code: "late-A".to_owned(),
            },
            EncodedRequestTerminal::Indeterminate {
                reason_code: "late-A".to_owned(),
            },
            EncodedRequestTerminal::Abandoned {
                reason_code: "late-A".to_owned(),
            },
        ] {
            let mut future = observer.observe_terminal(terminal);
            let mut context = Context::from_waker(Waker::noop());
            assert_eq!(future.as_mut().poll(&mut context), Poll::Ready(Ok(())));
            assert_eq!(*observer.phase.lock().expect("phase"), before);
        }
        assert!(observer.bind_attempt(attempt).is_err());
    }
}

#[test]
fn late_bound_terminal_cannot_clear_or_poison_the_successor() {
    let observer = observer();
    let first = attempt();
    let digest = Digest32::of_bytes(BODY);
    observer.bind_attempt(first.clone()).expect("first bind");
    observer.begin_body(digest).expect("first claim");
    observer.finish_body(&first, digest).expect("first proof");
    observer
        .record_terminal(&first, PromptRuntimeTerminalOutcomeV1::Delivered)
        .expect("first final");
    let mut second = first.clone();
    second.attempt_id = "second".to_owned();
    second.request_binding_id = "second-binding".to_owned();
    observer.bind_attempt(second.clone()).expect("second bind");
    observer.begin_body(digest).expect("second claim");
    observer.finish_body(&second, digest).expect("second proof");
    let before = observer.phase.lock().expect("phase").clone();
    for outcome in [
        PromptRuntimeTerminalOutcomeV1::Delivered,
        PromptRuntimeTerminalOutcomeV1::Rejected,
        PromptRuntimeTerminalOutcomeV1::NotDispatched,
        PromptRuntimeTerminalOutcomeV1::Indeterminate,
    ] {
        assert_eq!(
            observer.record_terminal(&first, outcome),
            Err("context_terminal_attempt_mismatch".to_owned())
        );
        assert_eq!(*observer.phase.lock().expect("phase"), before);
    }
    observer
        .record_terminal(&second, PromptRuntimeTerminalOutcomeV1::Delivered)
        .expect("second final");
}

#[test]
fn terminal_checks_complete_attempt_binding_not_just_its_id() {
    let observer = observer();
    let original = attempt();
    let digest = Digest32::of_bytes(BODY);
    observer.bind_attempt(original.clone()).expect("bind");
    observer.begin_body(digest).expect("claim");
    observer.finish_body(&original, digest).expect("proof");
    let mut wrong = original.clone();
    wrong.provider_wire_semantic_digest = Digest32::of_bytes(b"different-wire");
    assert_eq!(
        observer.record_terminal(&wrong, PromptRuntimeTerminalOutcomeV1::Delivered),
        Err("context_terminal_attempt_mismatch".to_owned())
    );
    observer
        .record_terminal(&original, PromptRuntimeTerminalOutcomeV1::Delivered)
        .expect("original final");
}
