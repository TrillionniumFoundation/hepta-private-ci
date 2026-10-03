use super::*;

#[test]
fn intent_is_account_bound_and_never_persisted() {
    let mut state = AppState::default();
    let mut intent = AdaptiveDockRestore::capture();
    assert!(!intent.is_current(&state));
    state.logged_in = true;
    assert!(intent.is_current(&state));
    intent.epoch += 1;
    assert!(!intent.is_current(&state));
    intent = AdaptiveDockRestore::capture();
    intent.user = Some("@other:example.invalid".try_into().unwrap());
    assert!(!intent.is_current(&state));
    state.adaptive_dock_restore = Some(AdaptiveDockRestore::capture());
    let bytes = serde_json::to_vec(&state).unwrap();
    let restored: AppState = serde_json::from_slice(&bytes).unwrap();
    assert!(restored.adaptive_dock_restore.is_none());
}
