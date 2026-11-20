use super::*;
use crate::root_observation_diagnostic::ObservationDiagnostics;
use crate::root_observation_diagnostic::ObservationFailure;
use pretty_assertions::assert_eq;

#[test]
fn request_samples_and_startup_stage_are_frozen_at_the_first_failure() {
    let diagnostics = ObservationDiagnostics::default();
    diagnostics.attach(AttachStage::OpeningFrontiers);
    diagnostics.refresh(RefreshEvent::Started(100));
    diagnostics.refresh(RefreshEvent::Replied(140));
    diagnostics.refresh(RefreshEvent::Accepted);
    diagnostics.refresh(RefreshEvent::Validated);
    diagnostics.refresh(RefreshEvent::Sleeping);
    let expected = ObservationProgress {
        refresh_phase: RefreshPhase::Sleeping,
        request_sequence: 1,
        wake_ns: None,
        request_started_ns: Some(100),
        reply_ended_ns: Some(140),
        previous_request_started_ns: None,
        previous_reply_ended_ns: None,
        accepted_request_started_ns: Some(100),
        validated_request_started_ns: Some(100),
        attach_stage: AttachStage::OpeningFrontiers,
        incomplete: false,
    };
    diagnostics.record(ObservationFailure {
        stage: "original_failure",
        ..Default::default()
    });
    diagnostics.refresh(RefreshEvent::Started(900));
    diagnostics.attach(AttachStage::OpeningWriter);
    diagnostics.record(ObservationFailure {
        stage: "later_cleanup_failure",
        ..Default::default()
    });
    assert_eq!(
        diagnostics.first(),
        Some(ObservationFailure {
            stage: "original_failure",
            progress: Some(expected),
            ..Default::default()
        })
    );
}

#[test]
fn contention_never_waits_and_a_lost_event_is_explicit() {
    let cell = ProgressCell::default();
    cell.attach(AttachStage::ReadingCurrent);
    let guard = cell.value.lock().unwrap();
    cell.refresh(RefreshEvent::Started(10));
    assert_eq!(cell.snapshot(), None);
    drop(guard);
    assert_eq!(
        cell.snapshot(),
        Some(ObservationProgress {
            attach_stage: AttachStage::ReadingCurrent,
            incomplete: true,
            ..Default::default()
        })
    );
}

#[test]
fn an_inflight_request_is_distinct_from_the_last_accepted_request() {
    let cell = ProgressCell::default();
    cell.refresh(RefreshEvent::Started(10));
    cell.refresh(RefreshEvent::Replied(20));
    cell.refresh(RefreshEvent::Accepted);
    cell.refresh(RefreshEvent::Woke {
        boottime_ns: Some(850),
    });
    cell.refresh(RefreshEvent::Started(900));
    assert_eq!(
        cell.snapshot(),
        Some(ObservationProgress {
            refresh_phase: RefreshPhase::RequestInFlight,
            request_sequence: 2,
            wake_ns: Some(850),
            request_started_ns: Some(900),
            reply_ended_ns: None,
            previous_request_started_ns: Some(10),
            previous_reply_ended_ns: Some(20),
            accepted_request_started_ns: Some(10),
            ..Default::default()
        })
    );
    cell.value.lock().unwrap().request_sequence = u64::MAX;
    cell.refresh(RefreshEvent::Started(u64::MAX));
    assert_eq!(cell.snapshot().unwrap().request_sequence, u64::MAX);
    assert!(format!("{:?}", cell.snapshot()).len() < 1024);
    cell.refresh(RefreshEvent::Woke { boottime_ns: None });
    assert_eq!(cell.snapshot().unwrap().wake_ns, None);
}
