use super::reject_impersonation;
use windows_sys::Win32::Foundation::ERROR_ACCESS_DENIED;
use windows_sys::Win32::Foundation::ERROR_CANT_OPEN_ANONYMOUS;
use windows_sys::Win32::Foundation::ERROR_INVALID_HANDLE;
use windows_sys::Win32::Foundation::ERROR_NO_TOKEN;

#[test]
fn only_a_confirmed_absent_thread_token_admits_process_owner_policy() {
    assert!(reject_impersonation(Err(ERROR_NO_TOKEN)).is_ok());
    assert!(reject_impersonation(Ok(())).is_err());
    for error in [
        ERROR_ACCESS_DENIED,
        ERROR_CANT_OPEN_ANONYMOUS,
        ERROR_INVALID_HANDLE,
        0,
    ] {
        let rejected = reject_impersonation(Err(error)).expect_err("query uncertainty rejects");
        assert_eq!(rejected.raw_os_error(), Some(error as i32));
    }
}

#[test]
fn a_real_thread_impersonation_token_is_rejected_without_changing_caller_identity() {
    // Only this new native-test thread impersonates its own process token.
    // Thread exit destroys that test-only context; product code never reverts,
    // enables privileges or modifies a token to force admission.
    std::thread::spawn(|| {
        use windows_sys::Win32::Security::ImpersonateSelf;
        use windows_sys::Win32::Security::SecurityIdentification;
        super::require_non_impersonating_thread().expect("no-token positive control");
        assert_ne!(
            unsafe { ImpersonateSelf(SecurityIdentification) },
            0,
            "impersonation attack setup must succeed, not count as rejection"
        );
        assert!(super::require_non_impersonating_thread().is_err());
    })
    .join()
    .expect("native identity checker thread");
}
