use super::tests::stored_pre_send;
use super::tests::stored_terminal;
use super::*;

#[test]
fn unknown_observations_cannot_release_the_final_reservation() {
    let mut state = StoredExactDeliveryState {
        schema: EXACT_DELIVERY_SCHEMA,
        ..Default::default()
    };
    state.pre_sends.insert(
        "attempt".into(),
        stored_pre_send("thread", "turn", "attempt"),
    );
    let reserved = completion_reserve(&state).expect("reserve");
    let mut unknown = stored_terminal("attempt");
    unknown.disposition = "Indeterminate".into();
    unknown.provider_receipt_digest = [21; 32];
    apply_observation(&mut state, unknown).expect("observe unknown");
    assert_eq!(
        completion_reserve(&state).expect("unknown reserve"),
        reserved
    );
    apply_observation(&mut state, stored_terminal("attempt")).expect("final");
    assert_eq!(completion_reserve(&state).expect("final reserve"), 0);
    assert_eq!(state.observations.len(), 1);
}

#[test]
fn reserve_exhaustion_rejects_before_writing_and_does_not_poison() {
    let directory = tempfile::tempdir().expect("directory");
    let (store, mut state) = ExactDeliveryStore::open(directory.path()).expect("store");
    state.pre_sends.insert(
        "attempt".into(),
        stored_pre_send("thread", "turn", "attempt"),
    );
    assert_eq!(
        store.persist_reserving(&state, MAX_DURABLE_STATE_BYTES),
        Err(ExactContextDeliveryError::Capacity)
    );
    assert!(!directory.path().join(STATE_FILE).exists());
    assert!(!directory.path().join(NEXT_FILE).exists());
    store
        .persist_reserving(&state, completion_reserve(&state).expect("reserve"))
        .expect("capacity rejection does not poison");
}

#[test]
fn oversized_terminal_cannot_exceed_its_reserved_record_bound() {
    let mut terminal = stored_terminal("attempt");
    validate_terminal_size(&terminal).expect("bounded fixture terminal");
    terminal.attempt_id = "x".repeat(128 * 1024);
    assert_eq!(
        validate_terminal_size(&terminal),
        Err(ExactContextDeliveryError::Capacity)
    );
}
