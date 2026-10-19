use super::*;

fn scope() -> OwnerScope {
    OwnerScope {
        principal_id: "human:one".into(),
        session_id: "session:one".into(),
        connection_generation: 1,
        permission_revision: 2,
        agent_id: "agent:one".into(),
        agent_generation: 3,
        thread_id: "thread:one".into(),
    }
}

fn session() -> OwnerSession {
    OwnerSession {
        protocol: CHAT_OWNER_PROTOCOL.into(),
        scope: scope(),
        expires_at_ms: 500_000,
        capabilities: vec![
            ChatCapability::SubmitSignedText,
            ChatCapability::ReadDeliveryStatus,
        ],
    }
}

fn envelope(message_id: &str) -> SignedTextRef {
    SignedTextRef::new(
        scope(),
        SignedEnvelopeMetadata {
            host_reference: format!("host:{message_id}"),
            issuer_id: "issuer:owner".into(),
            key_epoch: 1,
            message_id: message_id.into(),
            sequence: 41,
            expires_at_ms: 200_000,
            payload_sha256: Sha256::digest(r#"{"spawn_generation":3,"thread_id":"thread:one","text":"你好, exact original input"}"#.as_bytes()).into(),
            envelope_sha256: [2; 32],
        },
        "你好, exact original input".into(),
    )
    .unwrap()
}

fn adapter() -> ChatOwnerAdapter {
    let mut adapter = ChatOwnerAdapter::default();
    adapter.install_owner(session(), 1000).unwrap();
    adapter
}

fn dispatched(admission: SubmissionAdmission) -> DispatchTicket {
    match admission {
        SubmissionAdmission::Dispatch(ticket) => *ticket,
        SubmissionAdmission::Existing(_) => panic!("expected one host dispatch"),
    }
}

/// Owner fixture only: it does not authenticate, sign, create a runtime or call a model.
fn observation(ticket: &DispatchTicket, state: OwnerDeliveryState) -> OwnerDeliveryObservation {
    let attempts = if state == OwnerDeliveryState::Queued {
        0
    } else {
        1
    };
    OwnerDeliveryObservation {
        observer: ticket.observer().clone(),
        message_id: ticket.envelope().metadata().message_id.clone(),
        payload_sha256: ticket.envelope().metadata().payload_sha256,
        envelope_sha256: ticket.envelope().metadata().envelope_sha256,
        delivery_id: [3; 32],
        state,
        delivery_attempts: attempts,
        queue_receipt_digest: (state == OwnerDeliveryState::QueueAccepted).then_some([4; 32]),
    }
}

#[test]
fn unavailable_or_read_only_owner_cannot_turn_clicks_into_admission() {
    let mut adapter = ChatOwnerAdapter::default();
    assert_eq!(
        adapter.begin_submit(envelope("one"), 1000),
        Err(ChatOwnerError::Unavailable)
    );
    let mut read_only = session();
    read_only.capabilities = vec![ChatCapability::ReadHistory];
    adapter.install_owner(read_only, 1000).unwrap();
    assert_eq!(
        adapter.begin_submit(envelope("one"), 1000),
        Err(ChatOwnerError::PermissionDenied)
    );
    for capability in [
        ChatCapability::CreateThread,
        ChatCapability::InterruptTurn,
        ChatCapability::ResolveApproval,
    ] {
        assert_eq!(
            adapter.require_capability(capability, 1000),
            Err(ChatOwnerError::Unsupported)
        );
    }
    assert!(adapter.pending.is_empty());
}

#[test]
fn repeated_clicks_share_the_exact_in_flight_submission() {
    let mut adapter = adapter();
    let input = envelope("one");
    let ticket = dispatched(adapter.begin_submit(input.clone(), 1000).unwrap());
    assert_eq!(ticket.kind(), DispatchKind::InitialSubmit);
    let expected = DeliveryView {
        message_id: "one".into(),
        delivery_id: None,
        state: DeliveryState::Sending,
        delivery_attempts: 0,
        queue_receipt_digest: None,
        fresh: false,
    };
    for _ in 0..5 {
        assert_eq!(
            adapter.begin_submit(input.clone(), 1000).unwrap(),
            SubmissionAdmission::Existing(expected.clone())
        );
    }
    assert_eq!(adapter.pending.len(), 1);
    assert_eq!(adapter.view("one", 1000), Some(&expected));
}

#[test]
fn lost_initial_reply_retries_exact_envelope_and_fences_late_reply() {
    let mut adapter = adapter();
    let initial = dispatched(adapter.begin_submit(envelope("one"), 1000).unwrap());
    adapter.mark_unknown(&initial).unwrap();
    assert_eq!(
        adapter.view("one", 1000).unwrap().state,
        DeliveryState::Unknown
    );
    let retry = dispatched(adapter.retry_same_envelope("one", 1001).unwrap());
    assert_eq!(retry.kind(), DispatchKind::ExactInitialRetry);
    assert_eq!(retry.envelope(), initial.envelope());
    assert_eq!(
        adapter.observe_response(
            &initial,
            observation(&initial, OwnerDeliveryState::Queued),
            1001
        ),
        Err(ChatOwnerError::StaleObservation)
    );
    let accepted = adapter
        .observe_response(
            &retry,
            observation(&retry, OwnerDeliveryState::QueueAccepted),
            1001,
        )
        .unwrap();
    assert_eq!(
        accepted,
        DeliveryView {
            message_id: "one".into(),
            delivery_id: Some([3; 32]),
            state: DeliveryState::QueueAccepted,
            delivery_attempts: 1,
            queue_receipt_digest: Some([4; 32]),
            fresh: true
        }
    );
    assert_eq!(
        adapter.retry_same_envelope("one", 1001),
        Err(ChatOwnerError::RetryRequiresLookup)
    );
}

#[test]
fn immutable_signed_identity_rejects_same_id_with_changed_payload_or_handle() {
    let mut adapter = adapter();
    let original = envelope("one");
    assert_eq!(
        SignedTextRef::new(
            scope(),
            original.metadata.clone(),
            "substituted before admission".into()
        ),
        Err(ChatOwnerError::BindingMismatch)
    );
    let ticket = dispatched(adapter.begin_submit(original.clone(), 1000).unwrap());
    adapter.mark_unknown(&ticket).unwrap();
    let mut text_changed = original.clone();
    text_changed.text.push('!');
    let mut envelope_changed = original.clone();
    envelope_changed.metadata.envelope_sha256 = [9; 32];
    let mut handle_changed = original.clone();
    handle_changed.metadata.host_reference = "other:envelope".into();
    let mut sequence_changed = original.clone();
    sequence_changed.metadata.sequence += 1;
    for changed in [
        text_changed,
        envelope_changed,
        handle_changed,
        sequence_changed,
    ] {
        assert_eq!(
            adapter.begin_submit(changed, 1001),
            Err(ChatOwnerError::BindingMismatch)
        );
    }
    assert_eq!(adapter.pending["one"].envelope, original);
}

#[test]
fn cross_principal_session_thread_and_hash_observations_are_rejected() {
    let mut adapter = adapter();
    let ticket = dispatched(adapter.begin_submit(envelope("one"), 1000).unwrap());
    let valid = observation(&ticket, OwnerDeliveryState::Queued);
    let mut wrong_principal = valid.clone();
    wrong_principal.observer.principal_id = "human:two".into();
    let mut wrong_session = valid.clone();
    wrong_session.observer.session_id = "session:two".into();
    let mut wrong_thread = valid.clone();
    wrong_thread.observer.thread_id = "thread:two".into();
    let mut stale_permission = valid.clone();
    stale_permission.observer.permission_revision -= 1;
    let mut wrong_payload = valid.clone();
    wrong_payload.payload_sha256 = [8; 32];
    for invalid in [
        wrong_principal,
        wrong_session,
        wrong_thread,
        stale_permission,
        wrong_payload,
    ] {
        assert_eq!(
            adapter.observe_response(&ticket, invalid, 1000),
            Err(ChatOwnerError::BindingMismatch)
        );
    }
    adapter.observe_response(&ticket, valid, 1000).unwrap();
}

#[test]
fn disconnect_preserves_unknown_and_revocation_cannot_accept_a_late_ack() {
    let mut adapter = adapter();
    let ticket = dispatched(adapter.begin_submit(envelope("one"), 1000).unwrap());
    adapter.disconnect();
    assert_eq!(adapter.pending["one"].view.state, DeliveryState::Unknown);
    assert!(adapter.view("one", 1000).is_none());
    assert_eq!(
        adapter.observe_response(
            &ticket,
            observation(&ticket, OwnerDeliveryState::Queued),
            1001
        ),
        Err(ChatOwnerError::Unavailable)
    );
    let mut revoked_scope = session();
    revoked_scope.scope.permission_revision += 1;
    revoked_scope.capabilities = vec![ChatCapability::ReadDeliveryStatus];
    adapter.install_owner(revoked_scope, 1001).unwrap();
    assert_eq!(
        adapter.retry_same_envelope("one", 1001),
        Err(ChatOwnerError::PermissionDenied)
    );
    assert_eq!(adapter.pending.len(), 1);
}

#[test]
fn new_session_can_only_lookup_its_own_known_owner_delivery() {
    let mut adapter = adapter();
    let ticket = dispatched(adapter.begin_submit(envelope("one"), 1000).unwrap());
    adapter
        .observe_response(
            &ticket,
            observation(&ticket, OwnerDeliveryState::Queued),
            1000,
        )
        .unwrap();
    let mut next = session();
    next.scope.session_id = "session:next".into();
    next.scope.connection_generation += 1;
    next.scope.permission_revision += 1;
    adapter.install_owner(next, 1001).unwrap();
    assert_eq!(
        adapter.retry_same_envelope("one", 1001),
        Err(ChatOwnerError::BindingMismatch)
    );
    let lookup = dispatched(adapter.begin_status("one", 1001).unwrap());
    assert_eq!(lookup.kind(), DispatchKind::DeliveryStatus);
    assert_eq!(lookup.delivery_id(), Some([3; 32]));
    adapter
        .observe_response(
            &lookup,
            observation(&lookup, OwnerDeliveryState::QueueAccepted),
            1001,
        )
        .unwrap();
    let mut other = session();
    other.scope.principal_id = "human:two".into();
    adapter.install_owner(other, 1002).unwrap();
    assert!(adapter.view("one", 1002).is_none());
    assert_eq!(
        adapter.begin_status("one", 1002),
        Err(ChatOwnerError::BindingMismatch)
    );
}

#[test]
fn known_delivery_identity_and_terminal_queue_receipt_cannot_drift() {
    let mut adapter = adapter();
    let ticket = dispatched(adapter.begin_submit(envelope("one"), 1000).unwrap());
    adapter
        .observe_response(
            &ticket,
            observation(&ticket, OwnerDeliveryState::QueueAccepted),
            1000,
        )
        .unwrap();
    let lookup = dispatched(adapter.begin_status("one", 1001).unwrap());
    let mut different = observation(&lookup, OwnerDeliveryState::QueueAccepted);
    different.delivery_id = [7; 32];
    assert_eq!(
        adapter.observe_response(&lookup, different, 1001),
        Err(ChatOwnerError::BindingMismatch)
    );
    let mut regression = observation(&lookup, OwnerDeliveryState::Leased);
    regression.delivery_attempts = 1;
    assert_eq!(
        adapter.observe_response(&lookup, regression, 1001),
        Err(ChatOwnerError::StaleObservation)
    );
    let mut changed_terminal = observation(&lookup, OwnerDeliveryState::QueueAccepted);
    changed_terminal.delivery_attempts += 1;
    assert_eq!(
        adapter.observe_response(&lookup, changed_terminal, 1001),
        Err(ChatOwnerError::StaleObservation)
    );
    adapter.mark_unknown(&lookup).unwrap();
    let view = adapter.view("one", 1001).unwrap();
    assert_eq!(
        (view.state, view.fresh, view.queue_receipt_digest),
        (DeliveryState::QueueAccepted, false, Some([4; 32]))
    );
}

#[test]
fn quarantine_is_not_unsent_or_model_completion_and_does_not_retry() {
    let mut adapter = adapter();
    let ticket = dispatched(adapter.begin_submit(envelope("one"), 1000).unwrap());
    let result = adapter
        .observe_response(
            &ticket,
            observation(&ticket, OwnerDeliveryState::Quarantined),
            1000,
        )
        .unwrap();
    assert_eq!(
        (result.state, result.queue_receipt_digest),
        (DeliveryState::Quarantined, None)
    );
    assert_eq!(
        adapter.retry_same_envelope("one", 1001),
        Err(ChatOwnerError::RetryRequiresLookup)
    );
}

#[test]
fn expiry_clock_regression_and_reload_never_authorize_a_new_submission() {
    let mut adapter = adapter();
    let ticket = dispatched(adapter.begin_submit(envelope("one"), 1000).unwrap());
    adapter.mark_unknown(&ticket).unwrap();
    assert_eq!(
        adapter.retry_same_envelope("one", 999),
        Err(ChatOwnerError::ClockRegressed)
    );
    assert_eq!(
        adapter.retry_same_envelope("one", 200_000),
        Err(ChatOwnerError::Expired)
    );
    let mut fresh = ChatOwnerAdapter::default();
    fresh.install_owner(session(), 200_000).unwrap();
    assert_eq!(
        fresh.retry_same_envelope("one", 200_000),
        Err(ChatOwnerError::UnknownDelivery)
    );
    assert_eq!(
        fresh.begin_status("one", 200_000),
        Err(ChatOwnerError::UnknownDelivery)
    );
}

#[test]
fn bounded_capacity_preserves_all_unresolved_identity_without_eviction() {
    let mut adapter = adapter();
    for index in 0..MAX_PENDING_DELIVERIES {
        let ticket = dispatched(
            adapter
                .begin_submit(envelope(&format!("message:{index}")), 1000)
                .unwrap(),
        );
        adapter.mark_unknown(&ticket).unwrap();
    }
    assert_eq!(
        adapter.begin_submit(envelope("overflow"), 1000),
        Err(ChatOwnerError::Capacity)
    );
    assert_eq!(adapter.pending.len(), MAX_PENDING_DELIVERIES);
    assert!(
        adapter
            .pending
            .values()
            .all(|pending| pending.view.state == DeliveryState::Unknown)
    );
}

#[test]
fn exact_acknowledgement_handoff_reclaims_capacity_without_evicting_unknowns() {
    let mut adapter = adapter();
    let first = dispatched(adapter.begin_submit(envelope("one"), 1000).unwrap());
    let sending = adapter.view("one", 1000).unwrap().clone();
    assert_eq!(
        adapter.retire_queue_acknowledgement(&sending, 1000),
        Err(ChatOwnerError::NotRetirable)
    );
    let accepted = adapter
        .observe_response(
            &first,
            observation(&first, OwnerDeliveryState::QueueAccepted),
            1000,
        )
        .unwrap();
    for index in 1..MAX_PENDING_DELIVERIES {
        let ticket = dispatched(
            adapter
                .begin_submit(envelope(&format!("message:{index}")), 1000)
                .unwrap(),
        );
        adapter.mark_unknown(&ticket).unwrap();
    }
    let mut altered = accepted.clone();
    altered.delivery_id = Some([7; 32]);
    assert_eq!(
        adapter.retire_queue_acknowledgement(&altered, 1000),
        Err(ChatOwnerError::NotRetirable)
    );
    assert_eq!(
        adapter
            .retire_queue_acknowledgement(&accepted, 1000)
            .unwrap(),
        accepted
    );
    assert_eq!(
        adapter.observe_response(
            &first,
            observation(&first, OwnerDeliveryState::QueueAccepted),
            1000
        ),
        Err(ChatOwnerError::StaleObservation)
    );
    let next = dispatched(adapter.begin_submit(envelope("next"), 1000).unwrap());
    assert_eq!(next.kind(), DispatchKind::InitialSubmit);
    assert_eq!(adapter.pending.len(), MAX_PENDING_DELIVERIES);
    assert!(
        adapter
            .pending
            .values()
            .filter(|pending| pending.view.state == DeliveryState::Unknown)
            .count()
            == MAX_PENDING_DELIVERIES - 1
    );
}

#[test]
fn utf8_and_json_escaping_are_bounded_without_truncation_or_secret_debug() {
    let original = envelope("one");
    for text in [
        "界".repeat(MAX_SIGNED_TEXT_BYTES / 3 + 1),
        "\u{1}".repeat(4000),
        "  ".into(),
    ] {
        assert_eq!(
            SignedTextRef::new(scope(), original.metadata.clone(), text),
            Err(ChatOwnerError::InvalidInput)
        );
    }
    let debug = format!("{original:?}");
    assert!(!debug.contains(original.text()));
    assert!(!debug.contains(&original.metadata.host_reference));
    let mut invalid = session();
    invalid.protocol = "hepta.ui-control.v1".into();
    let mut adapter = adapter();
    assert_eq!(
        adapter.install_owner(invalid, 1000),
        Err(ChatOwnerError::InvalidInput)
    );
    assert_eq!(
        adapter.begin_submit(original, 1000),
        Err(ChatOwnerError::Unavailable)
    );
}
