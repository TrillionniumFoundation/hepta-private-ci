use super::*;

fn id(value: &str) -> StableId {
    let Ok(value) = StableId::new(value) else {
        panic!("test identifier must be valid");
    };
    value
}

fn revision(value: u64) -> Revision {
    let Ok(value) = Revision::new(value) else {
        panic!("test revision must be valid");
    };
    value
}

fn state() -> ControlState {
    ControlState {
        revision: revision(1),
        authority_epoch: 7,
        mode: ControlMode::Ready,
        configuration_digest: Digest32::of_bytes(b"configuration"),
    }
}

fn intent(action: ControlAction) -> ControlIntent {
    ControlIntent {
        operation_id: id("operation:1"),
        expected_revision: revision(1),
        expected_authority_epoch: 7,
        action,
        payload_digest: Digest32::of_bytes(b"payload"),
    }
}

#[test]
fn quarantine_updates_desired_state_without_effect_authority() {
    let Ok((next, receipt)) = apply(&state(), intent(ControlAction::Quarantine)) else {
        panic!("quarantine transition must succeed");
    };
    assert_eq!(next.mode, ControlMode::Quarantined);
    assert!(!receipt.authority.grants_any());
}

#[test]
fn stale_revision_is_rejected() {
    let mut value = intent(ControlAction::Quarantine);
    value.expected_revision = revision(2);
    assert_eq!(apply(&state(), value), Err(Error::StaleRevision));
}

#[test]
fn stale_epoch_is_rejected() {
    let mut value = intent(ControlAction::Quarantine);
    value.expected_authority_epoch = 8;
    assert_eq!(apply(&state(), value), Err(Error::StaleAuthorityEpoch));
}

#[test]
fn invalid_transition_is_rejected() {
    assert_eq!(
        apply(&state(), intent(ControlAction::MarkReady)),
        Err(Error::InvalidTransition)
    );
}
