//! Local failure detail for a restart whose effect cannot be acknowledged.
//!
//! The caller must release the supervisor lock before writing. These bounded
//! local diagnostics do not change the deliberately closed RPC error payload.

use std::io;
use std::io::Write;

use codex_hepta_contracts::AgentId;

use crate::SupervisorError;

const RECORD_BYTES: usize = 4096;
const ERROR_BYTES: usize = 1536;

pub(super) fn write_restart_failure(
    writer: &mut impl Write,
    agent_id: &AgentId,
    control_revision: u64,
    mutation_error: Option<&SupervisorError>,
    post_status_error: Option<&SupervisorError>,
) -> io::Result<usize> {
    let primary = if mutation_error.is_some() {
        "mutation"
    } else {
        "post_status"
    };
    let mut record = [0_u8; RECORD_BYTES];
    let written = {
        let mut output = &mut record[..];
        let _ = write!(
            output,
            "HEPTA_SUPERVISORD_RESTART_FAILURE agent_id={agent_id} control_revision={control_revision} primary={primary}"
        );
        for (stage, error) in [
            ("mutation", mutation_error),
            ("post_status", post_status_error),
        ] {
            // Format directly into a separate fixed buffer for each cause, so
            // one large error cannot consume the other cause or its marker.
            let mut detail = [0_u8; ERROR_BYTES];
            let (detail_written, format_complete) = {
                let mut remaining = &mut detail[..];
                let complete = write!(remaining, "{error:?}").is_ok();
                (ERROR_BYTES - remaining.len(), complete)
            };
            let detail = &detail[..detail_written];
            let valid_len = match std::str::from_utf8(detail) {
                Ok(_) => detail.len(),
                Err(error) => error.valid_up_to(),
            };
            let detail = std::str::from_utf8(&detail[..valid_len]).unwrap_or_default();
            let complete = format_complete && valid_len == detail_written;
            let _ = write!(
                output,
                " {stage}_format_complete={complete} {stage}_error={detail}"
            );
        }
        let _ = writeln!(output);
        RECORD_BYTES - output.len()
    };
    // One best-effort write: a short write or I/O error must not replace the
    // original operation outcome. A byte bound is not a write-time bound.
    writer.write(&record[..written])
}

#[cfg(test)]
#[path = "daemon_mutation_diagnostic_tests.rs"]
mod tests;
