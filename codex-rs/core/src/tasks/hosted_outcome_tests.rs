use super::*;

#[test]
fn only_uncancelled_internal_hosted_failures_preserve_the_unfinished_tail() {
    let technical = Err(CodexErr::InvalidRequest("original storage observation remains unknown".to_owned()));
    assert!(hosted_failure_is_unresolved(true, false, &technical));
    let projection = Err(CodexErr::Fatal("hosted assistant projection persistence is uncertain".to_owned()));
    assert!(hosted_failure_is_unresolved(true, false, &projection),
        "a typed-output storage failure must retain original hosted recovery");
    assert!(!hosted_failure_is_unresolved(true, true, &projection),
        "original cancellation remains authoritative during projection");
    assert!(!hosted_failure_is_unresolved(false, false, &technical),
        "ordinary task terminalization must keep its existing behavior");
    assert!(!hosted_failure_is_unresolved(true, true, &technical),
        "a wrapped technical error cannot hide the original Core cancellation token");
    assert!(!hosted_failure_is_unresolved(true, false, &Err(CodexErr::TurnAborted)));
    assert!(!hosted_failure_is_unresolved(true, false, &Ok(None)));
}
