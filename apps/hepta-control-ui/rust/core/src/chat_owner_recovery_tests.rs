use super::*;

#[test]
fn root_recovery_of_expired_old_generation_is_lookup_only() {
    let mut adapter = ChatOwnerAdapter::default();
    let mut current = session();
    current.scope.agent_generation += 1;
    current.scope.connection_generation += 1;
    current.scope.session_id = "replacement-session".into();
    adapter.install_owner(current, 210_000).unwrap();
    let original = envelope("prior-input");
    let view = adapter
        .restore_reference(original.clone(), [8; 32], 210_000)
        .unwrap();
    assert_eq!(view.state, DeliveryState::Unknown);
    assert!(!view.fresh);
    assert_eq!(
        adapter.begin_submit(original, 210_000),
        Err(ChatOwnerError::BindingMismatch)
    );
    assert_eq!(
        adapter.retry_same_envelope("prior-input", 210_000),
        Err(ChatOwnerError::BindingMismatch)
    );
    let lookup = dispatched(adapter.begin_status("prior-input", 210_000).unwrap());
    assert_eq!(lookup.kind(), DispatchKind::DeliveryStatus);
    assert_eq!(lookup.delivery_id(), Some([8; 32]));
}

#[test]
fn original_recovery_rejects_other_principal_or_changed_reference() {
    let mut adapter = adapter();
    let original = envelope("prior-input");
    adapter
        .restore_reference(original.clone(), [8; 32], 1000)
        .unwrap();
    assert_eq!(
        adapter.restore_reference(original.clone(), [9; 32], 1000),
        Err(ChatOwnerError::BindingMismatch)
    );
    let mut other = session();
    other.scope.principal_id = "other-human".into();
    adapter.install_owner(other, 1001).unwrap();
    assert_eq!(
        adapter.restore_reference(original, [8; 32], 1001),
        Err(ChatOwnerError::BindingMismatch)
    );
    assert!(adapter.view("prior-input", 1001).is_none());
}

#[test]
fn root_retirement_callback_is_exact_fenced_and_never_fabricates_queue_ack() {
    let mut adapter = adapter();
    adapter
        .restore_reference(envelope("closed-input"), [8; 32], 1000)
        .unwrap();
    let old = dispatched(adapter.begin_status("closed-input", 1000).unwrap());
    let mut current = session();
    current.scope.connection_generation += 1;
    adapter.install_owner(current, 1001).unwrap();
    assert_eq!(
        adapter.retire_original_reference(&old, 1001),
        Err(ChatOwnerError::StaleObservation)
    );
    let exact = dispatched(adapter.begin_status("closed-input", 1001).unwrap());
    let consumed = adapter.retire_original_reference(&exact, 1001).unwrap();
    assert_eq!(consumed.state, DeliveryState::Unknown);
    assert_eq!(consumed.queue_receipt_digest, None);
    assert!(adapter.view("closed-input", 1001).is_none());
    assert_eq!(
        adapter.retire_original_reference(&exact, 1001),
        Err(ChatOwnerError::StaleObservation)
    );
}
