use std::io;
use std::io::Write;

use codex_hepta_contracts::AgentId;
use pretty_assertions::assert_eq;

use super::RECORD_BYTES;
use super::write_restart_failure;
use crate::SupervisorError;

#[test]
fn large_unicode_causes_keep_both_stages_within_one_record() {
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").unwrap();
    let mutation = SupervisorError::Invalid("λ".repeat(8192));
    let post = SupervisorError::CorruptLease("界".repeat(8192));
    let mut output = Vec::new();
    let written = write_restart_failure(
        &mut output,
        &agent_id,
        /*control_revision*/ 7,
        Some(&mutation),
        Some(&post),
    )
    .unwrap();
    assert_eq!(written, output.len());
    assert!(output.len() <= RECORD_BYTES);
    let output = String::from_utf8(output).unwrap();
    assert!(output.contains("primary=mutation"));
    assert!(output.contains("mutation_format_complete=false mutation_error=Some(Invalid("));
    assert!(
        output.contains("post_status_format_complete=false post_status_error=Some(CorruptLease(")
    );
    assert!(output.ends_with('\n'));
}

#[test]
fn post_status_is_primary_only_when_mutation_succeeded() {
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").unwrap();
    let error = SupervisorError::UnknownAgent(agent_id.clone());
    let mut output = Vec::new();
    let written = write_restart_failure(
        &mut output,
        &agent_id,
        /*control_revision*/ 8,
        /*mutation_error*/ None,
        Some(&error),
    )
    .unwrap();
    assert_eq!(written, output.len());
    let output = String::from_utf8(output).unwrap();
    assert!(output.contains("primary=post_status"));
    assert!(output.contains("mutation_format_complete=true mutation_error=None"));
    assert!(
        output.contains("post_status_format_complete=true post_status_error=Some(UnknownAgent(")
    );
}

#[test]
fn failed_diagnostic_write_does_not_propagate_or_retry() {
    struct FailingWriter {
        writes: usize,
    }

    impl Write for FailingWriter {
        fn write(&mut self, _bytes: &[u8]) -> io::Result<usize> {
            self.writes += 1;
            Err(io::Error::from(io::ErrorKind::BrokenPipe))
        }

        fn flush(&mut self) -> io::Result<()> {
            panic!("diagnostic must not add a flush");
        }
    }

    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").unwrap();
    let error = SupervisorError::RestartBudgetExhausted(agent_id.clone());
    let mut writer = FailingWriter { writes: 0 };
    let result = write_restart_failure(
        &mut writer,
        &agent_id,
        /*control_revision*/ 9,
        Some(&error),
        /*post_status_error*/ None,
    );
    assert_eq!(result.unwrap_err().kind(), io::ErrorKind::BrokenPipe);
    assert_eq!(writer.writes, 1);
}
