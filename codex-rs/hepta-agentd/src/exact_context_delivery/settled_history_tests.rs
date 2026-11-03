use super::tests::stored_pre_send;
use super::tests::stored_terminal;
use super::*;

fn state_with_attempt(index: usize) -> StoredExactDeliveryState {
    let attempt = format!("attempt-{index}");
    let mut state = StoredExactDeliveryState::default();
    state.pre_sends.insert(
        attempt.clone(),
        stored_pre_send("thread", &format!("turn-{index}"), &attempt),
    );
    state
        .terminals
        .insert(attempt, stored_terminal(&format!("attempt-{index}")));
    state
}

#[test]
fn final_settlement_releases_raw_recovery_and_provider_material() {
    let mut state = state_with_attempt(0);
    let pre_send = state.pre_sends.get_mut("attempt-0").expect("pre-send");
    pre_send.recovery_binding_digest = [17; 32];
    pre_send.recovery_archive = Some(vec![3; 1024]);
    let terminal = state.terminals.get_mut("attempt-0").expect("terminal");
    terminal.provider_receipt = None;
    terminal.observation_version = 2;

    settled_history::settle_final_attempt(&mut state, "attempt-0").expect("settle");

    assert!(state.pre_sends.is_empty());
    assert!(state.terminals.is_empty());
    assert!(state.observations.is_empty());
    let settled = &state.settled_attempts["attempt-0"];
    assert_eq!(settled.recovery_binding_digest, [17; 32]);
    assert_ne!(settled.record_digest, [0; 32]);
    validate_stored_state(&state).expect("valid compact state");
}

#[test]
fn recent_history_rolls_into_a_versioned_fail_closed_checkpoint() {
    let mut state = StoredExactDeliveryState::default();
    for index in 0..=settled_history::MAX_RECENT_SETTLED_ATTEMPTS {
        let attempt = format!("attempt-{index}");
        state.pre_sends.insert(
            attempt.clone(),
            stored_pre_send("thread", &format!("turn-{index}"), &attempt),
        );
        state
            .terminals
            .insert(attempt.clone(), stored_terminal(&attempt));
        settled_history::settle_final_attempt(&mut state, &attempt).expect("settle");
    }

    assert_eq!(
        state.settled_attempts.len(),
        settled_history::MAX_RECENT_SETTLED_ATTEMPTS
    );
    assert_eq!(state.settlement_checkpoint.archived_count, 1);
    assert_eq!(state.settlement_checkpoint.last_sequence, 1);
    assert_ne!(state.settlement_checkpoint.records_chain_digest, [0; 32]);
    assert!(settled_history::has_checkpointed_attempt(&state, "attempt-0"));
    assert!(settled_history::has_seen_turn(&state, "thread", "turn-0"));
    assert!(!state.settled_attempts.contains_key("attempt-0"));
    validate_stored_state(&state).expect("valid checkpoint");
}

#[test]
fn checkpoint_and_recent_tampering_are_rejected() {
    let mut state = state_with_attempt(0);
    settled_history::settle_final_attempt(&mut state, "attempt-0").expect("settle");
    state
        .settled_attempts
        .get_mut("attempt-0")
        .expect("settled")
        .provider_request_digest = [99; 32];
    assert_eq!(
        validate_stored_state(&state),
        Err(ExactContextDeliveryError::CorruptState)
    );

    let mut checkpointed = StoredExactDeliveryState::default();
    for index in 0..=settled_history::MAX_RECENT_SETTLED_ATTEMPTS {
        let attempt = format!("checkpoint-{index}");
        checkpointed.pre_sends.insert(
            attempt.clone(),
            stored_pre_send("thread", &format!("turn-{index}"), &attempt),
        );
        checkpointed
            .terminals
            .insert(attempt.clone(), stored_terminal(&attempt));
        settled_history::settle_final_attempt(&mut checkpointed, &attempt).expect("settle");
    }
    checkpointed.settlement_checkpoint.membership_digest = [88; 32];
    assert_eq!(
        validate_stored_state(&checkpointed),
        Err(ExactContextDeliveryError::CorruptState)
    );
}

#[test]
fn schema_three_final_history_migrates_without_recovery_authority() {
    let mut state = state_with_attempt(0);
    state.schema = 3;
    migrate_state(&mut state).expect("migrate");
    assert_eq!(state.schema, EXACT_DELIVERY_SCHEMA);
    assert!(state.pre_sends.is_empty());
    assert!(state.terminals.is_empty());
    assert_eq!(state.settled_attempts.len(), 1);
    assert!(!state.has_unresolved_attempt("attempt-0"));
    validate_stored_state(&state).expect("valid migration");
}

#[test]
fn unresolved_and_indeterminate_attempts_never_enter_settlement_history() {
    let mut state = StoredExactDeliveryState::default();
    state.pre_sends.insert(
        "attempt".into(),
        stored_pre_send("thread", "turn", "attempt"),
    );
    assert_eq!(
        settled_history::settle_final_attempt(&mut state, "attempt"),
        Err(ExactContextDeliveryError::CorruptState)
    );
    assert!(state.has_unresolved_attempt("attempt"));
    assert!(state.settled_attempts.is_empty());

    let mut unknown = stored_terminal("attempt");
    unknown.disposition = "Indeterminate".into();
    unknown.provider_receipt_digest = [21; 32];
    apply_observation(&mut state, unknown).expect("indeterminate");
    assert_eq!(
        settled_history::settle_final_attempt(&mut state, "attempt"),
        Err(ExactContextDeliveryError::CorruptState)
    );
    assert!(state.has_unresolved_attempt("attempt"));
    assert_eq!(state.observations.len(), 1);
}
