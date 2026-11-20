use super::*;
use pretty_assertions::assert_eq;

#[test]
fn contended_progress_keeps_the_first_static_cause_without_waiting_or_overwrite() {
    let diagnostics = CheckpointDiagnostics::default();
    diagnostics.stage(CheckpointStage::ReadBody);
    let held = diagnostics.state.lock().unwrap();
    diagnostics.fail(CheckpointFailureCause::Timeout);
    let first = diagnostics.first().unwrap();
    assert_eq!(first.stage, CheckpointStage::Start);
    assert_eq!(first.cause, Some(CheckpointFailureCause::Timeout));
    assert!(first.incomplete && first.elapsed_ns.is_some());
    drop(held);
    diagnostics.stage(CheckpointStage::Finished);
    diagnostics.fail(CheckpointFailureCause::Cancelled);
    assert_eq!(diagnostics.first(), Some(first));
    assert!(format!("{first:?}").len() < 512);
}
