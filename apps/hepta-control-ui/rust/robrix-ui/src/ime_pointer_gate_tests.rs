use super::*;

#[test]
fn rejected_click_stays_rejected_after_preedit_ends() {
    let mut gate = PointerGate::default();
    let id = PointerId::Mouse(0);
    assert_eq!(
        gate.start(id, Preedit::Active, Position::OutsideFocusedField),
        Route::SuppressUiDispatch
    );
    assert_eq!(gate.motion(id), Route::SuppressUiDispatch);
    assert_eq!(
        gate.finish(
            id,
            Preedit::Inactive,
            Position::OutsideFocusedField,
            Capture::OtherOrNone
        ),
        Route::SuppressUiDispatch
    );
    assert_eq!(
        gate.start(id, Preedit::Inactive, Position::OutsideFocusedField),
        Route::Forward
    );
}

#[test]
fn independent_touch_motion_and_release_remain_forwarded() {
    let mut gate = PointerGate::default();
    let outside = PointerId::Touch(1);
    let inside = PointerId::Touch(2);
    assert_eq!(
        gate.start(outside, Preedit::Active, Position::OutsideFocusedField),
        Route::SuppressUiDispatch
    );
    assert_eq!(
        gate.start(inside, Preedit::Active, Position::FocusedField),
        Route::Forward
    );
    assert_eq!(gate.motion(inside), Route::Forward);
    assert_eq!(gate.motion(outside), Route::SuppressUiDispatch);
    assert_eq!(
        gate.finish(
            inside,
            Preedit::Active,
            Position::OutsideFocusedField,
            Capture::FocusedField
        ),
        Route::Forward
    );
    assert_eq!(
        gate.finish(
            outside,
            Preedit::Active,
            Position::FocusedField,
            Capture::OtherOrNone
        ),
        Route::SuppressUiDispatch
    );
}

#[test]
fn outside_release_cannot_blur_preedit_without_a_recorded_start() {
    let mut gate = PointerGate::default();
    assert_eq!(
        gate.finish(
            PointerId::Mouse(0),
            Preedit::Active,
            Position::OutsideFocusedField,
            Capture::OtherOrNone
        ),
        Route::SuppressUiDispatch
    );
}

#[test]
fn mouse_and_touch_identifiers_cannot_alias() {
    let mut gate = PointerGate::default();
    gate.start(
        PointerId::Mouse(1),
        Preedit::Active,
        Position::OutsideFocusedField,
    );
    assert_eq!(gate.motion(PointerId::Touch(1)), Route::Forward);
    assert_eq!(gate.motion(PointerId::Mouse(1)), Route::SuppressUiDispatch);
}

#[test]
fn duplicate_start_does_not_unblock_an_existing_sequence() {
    let mut gate = PointerGate::default();
    let id = PointerId::Touch(2);
    gate.start(id, Preedit::Active, Position::OutsideFocusedField);
    assert_eq!(
        gate.start(id, Preedit::Inactive, Position::FocusedField),
        Route::SuppressUiDispatch
    );
    assert_eq!(gate.blocked.len(), 1);
}

#[test]
fn capacity_failure_stays_closed_until_platform_reset() {
    let mut gate = PointerGate::default();
    for id in 0..=MAX_BLOCKED_POINTERS as u64 {
        gate.start(
            PointerId::Touch(id),
            Preedit::Active,
            Position::OutsideFocusedField,
        );
    }
    assert_eq!(gate.blocked.len(), MAX_BLOCKED_POINTERS);
    assert!(gate.is_overflowed());
    assert_eq!(
        gate.start(
            PointerId::Mouse(0),
            Preedit::Inactive,
            Position::FocusedField
        ),
        Route::SuppressUiDispatch
    );
    for id in 0..=MAX_BLOCKED_POINTERS as u64 {
        assert_eq!(
            gate.finish(
                PointerId::Touch(id),
                Preedit::Inactive,
                Position::OutsideFocusedField,
                Capture::OtherOrNone
            ),
            Route::SuppressUiDispatch
        );
    }
    assert_eq!(gate.motion(PointerId::Mouse(0)), Route::SuppressUiDispatch);
    gate.platform_input_reset_completed();
    assert_eq!(
        gate.start(
            PointerId::Mouse(0),
            Preedit::Inactive,
            Position::FocusedField
        ),
        Route::Forward
    );
}

#[test]
fn ordinary_noncomposing_input_is_not_retained() {
    let mut gate = PointerGate::default();
    for id in 0..1000 {
        let id = PointerId::Touch(id);
        assert_eq!(
            gate.start(id, Preedit::Inactive, Position::OutsideFocusedField),
            Route::Forward
        );
        assert_eq!(
            gate.finish(
                id,
                Preedit::Inactive,
                Position::OutsideFocusedField,
                Capture::OtherOrNone
            ),
            Route::Forward
        );
    }
    assert!(gate.blocked.is_empty());
    assert!(!gate.is_overflowed());
}
