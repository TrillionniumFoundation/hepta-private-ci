use super::is_stale_cleanup_kill;
use codex_hepta_supervisor::SupervisorError;

#[test]
fn cleanup_refresh_requires_the_complete_stale_rejection() {
    let message = "supervisord rejected request (stale_control_fence): selected Agent changed; refresh before retry";
    assert!(is_stale_cleanup_kill(&SupervisorError::Invalid(
        message.to_owned()
    )));
    for changed in [
        "stale_control_fence".to_owned(),
        format!("prefix: {message}"),
        format!("{message}\n"),
        message.replace("selected Agent changed", "selected Agent unavailable"),
    ] {
        assert!(
            !is_stale_cleanup_kill(&SupervisorError::Invalid(changed.clone())),
            "changed rejection must not authorize a cleanup refresh: {changed}"
        );
    }
}

#[test]
fn cleanup_refresh_rejects_transport_and_indeterminate_errors() {
    let stale_text = "supervisord rejected request (stale_control_fence): selected Agent changed; refresh before retry";
    let errors = [
        SupervisorError::Io(std::io::Error::other(stale_text)),
        SupervisorError::Invalid("supervisord read timed out".to_owned()),
        SupervisorError::Invalid(
            "supervisord rejected request (operation_indeterminate): operation outcome is indeterminate; refresh before retry"
                .to_owned(),
        ),
        SupervisorError::Invalid(
            "supervisord rejected request (generation_fence): selected Agent changed; refresh before retry"
                .to_owned(),
        ),
    ];
    for error in errors {
        assert!(
            !is_stale_cleanup_kill(&error),
            "non-stale error must propagate without another Kill: {error}"
        );
    }
}
