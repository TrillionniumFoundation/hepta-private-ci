use pretty_assertions::assert_eq;

use super::*;

#[test]
fn action_error_survives_in_report_when_postcheck_error_takes_priority() -> io::Result<()> {
    let diagnostics = CompletedDiagnostics::new(64);
    let result: io::Result<()> = (|| {
        let value = Err(io::Error::from_raw_os_error(libc::EACCES));
        diagnostics.record_result(CompletedStage::ContextAction, &value);
        diagnostics.check(
            CompletedStage::ContextSignerPostcheck,
            || -> io::Result<()> { Err(io::Error::from_raw_os_error(libc::EPERM)) },
        )?;
        value
    })();
    let returned = result.expect_err("original postcheck must still refuse");
    assert_eq!(returned.raw_os_error(), Some(libc::EPERM));
    let mut bytes = Vec::new();
    diagnostics.write_report(&returned, &mut bytes)?;
    assert_eq!(
        String::from_utf8(bytes).expect("fixed ASCII report"),
        format!(
            "root_diagnostic=completed request_id=64 index=0 stage=context_action kind=permission_denied errno={}\nroot_diagnostic=completed request_id=64 index=1 stage=context_signer_postcheck kind=permission_denied errno={}\nroot_diagnostic=completed_return request_id=64 stored=2 truncated=false kind=permission_denied errno={}\n",
            libc::EACCES,
            libc::EPERM,
            libc::EPERM,
        )
    );
    Ok(())
}

#[test]
fn error_payload_is_not_formatted_or_wrapped() -> io::Result<()> {
    #[derive(Debug)]
    struct NeverFormat;
    impl std::fmt::Display for NeverFormat {
        fn fmt(&self, _: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            panic!("diagnostics must never format an error payload")
        }
    }
    impl std::error::Error for NeverFormat {}

    let diagnostics = CompletedDiagnostics::new(64);
    let result: io::Result<()> = diagnostics.check(CompletedStage::Publication, || {
        Err(io::Error::other(NeverFormat))
    });
    let returned = result.expect_err("original error required");
    assert!(
        returned
            .get_ref()
            .is_some_and(|inner| inner.is::<NeverFormat>())
    );
    let mut bytes = Vec::new();
    diagnostics.write_report(&returned, &mut bytes)?;
    assert_eq!(bytes, b"root_diagnostic=completed request_id=64 index=0 stage=publication kind=other errno=none\nroot_diagnostic=completed_return request_id=64 stored=1 truncated=false kind=other errno=none\n");
    Ok(())
}

#[test]
fn repeated_errors_are_bounded_and_do_not_hide_returned_error() -> io::Result<()> {
    let diagnostics = CompletedDiagnostics::new(u64::MAX);
    let error: io::Result<()> = Err(io::Error::from_raw_os_error(i32::MIN));
    for _ in 0..64 {
        diagnostics.record_result(CompletedStage::ContextMetadataPostcheck, &error);
    }
    let returned = io::Error::new(io::ErrorKind::TimedOut, "private payload");
    let mut bytes = [0_u8; REPORT_BOUND];
    let mut output = io::Cursor::new(bytes.as_mut_slice());
    diagnostics.write_report(&returned, &mut output)?;
    let length = output.position() as usize;
    let report = std::str::from_utf8(&bytes[..length]).expect("fixed ASCII report");
    assert_eq!(report.lines().count(), MAX_FAILURES + 1);
    assert!(report.ends_with("stored=8 truncated=true kind=timed_out errno=none\n"));
    assert!(!report.contains("private payload"));
    assert!(length < REPORT_BOUND);
    Ok(())
}

#[test]
fn successful_checks_leave_no_failure_records() -> io::Result<()> {
    let diagnostics = CompletedDiagnostics::new(64);
    let value = diagnostics.check(CompletedStage::ContextTrustPostcheck, || Ok(vec![7, 9]))?;
    assert_eq!(
        (value, diagnostics.failures.get(), diagnostics.stored.get()),
        (vec![7, 9], [None; MAX_FAILURES], 0)
    );
    Ok(())
}
