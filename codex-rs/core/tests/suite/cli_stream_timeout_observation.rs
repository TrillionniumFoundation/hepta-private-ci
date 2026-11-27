use super::CliTimeoutObservation;
use codex_utils_pty::ProcessExitObserver;
use codex_utils_pty::ProcessExitState;
use std::io;
use std::io::Write;
use std::time::Instant;

const LOG_BYTES: usize = 1024;

pub(super) fn report(
    observation: &CliTimeoutObservation,
    observer: &io::Result<ProcessExitObserver>,
) {
    let (prefix, command, fallback): (&str, &str, &[u8]) = match observation {
        CliTimeoutObservation::Disabled => return,
        CliTimeoutObservation::InitialSession => (
            "HEPTA_CLI_INITIAL_TIMEOUT",
            "first_exec",
            b"HEPTA_CLI_INITIAL_TIMEOUT case=integration_creates_and_checks_session_file command=first_exec process=unknown error_stage=format\n",
        ),
        CliTimeoutObservation::ResumeSession => (
            "HEPTA_CLI_RESUME_TIMEOUT",
            "second_resume",
            b"HEPTA_CLI_RESUME_TIMEOUT case=integration_creates_and_checks_session_file command=second_resume process=unknown error_stage=format\n",
        ),
    };
    let started = Instant::now();
    let (clone, process, exit_code, error_stage, error_kind, raw_os_error) = match observer {
        Err(error) => (
            "failed",
            "unknown",
            None,
            "clone",
            Some(error.kind()),
            error.raw_os_error(),
        ),
        Ok(observer) => match observer.snapshot() {
            Ok(ProcessExitState::Running) => ("ok", "running", None, "none", None, None),
            Ok(ProcessExitState::Exited { exit_code }) => {
                ("ok", "exited", Some(exit_code), "none", None, None)
            }
            Err(error) => (
                "ok",
                "unknown",
                None,
                "query",
                Some(error.kind()),
                error.raw_os_error(),
            ),
        },
    };
    let observation_elapsed_us = started.elapsed().as_micros();
    let mut bytes = [0_u8; LOG_BYTES];
    let (format_result, length) = {
        let mut remaining = &mut bytes[..];
        let result = writeln!(
            remaining,
            "{prefix} case=integration_creates_and_checks_session_file command={command} clone={clone} process={process} exit_code={exit_code:?} error_stage={error_stage} error_kind={error_kind:?} raw_os_error={raw_os_error:?} observation_elapsed_us={observation_elapsed_us}"
        );
        (result, LOG_BYTES - remaining.len())
    };
    let output: &[u8] = if format_result.is_ok() {
        &bytes[..length]
    } else {
        fallback
    };
    // One best-effort write; a short write or error never changes the original
    // TimedOut result. The byte cap does not bound stderr I/O latency.
    let _ = io::stderr().write(output);
}
