//! Bounded cached diagnostics are prepared by the refresh worker.

use std::io::Write;

use crate::error::ShellError;

const MAX_RENDERED_STATUS_BYTES: usize = 4 * 1024 * 1024;

#[derive(Default)]
struct BoundedStatus(Vec<u8>);

impl Write for BoundedStatus {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        if bytes.len() > MAX_RENDERED_STATUS_BYTES.saturating_sub(self.0.len()) {
            return Err(std::io::Error::other(
                "runtime status exceeds the GUI presentation byte bound",
            ));
        }
        self.0.extend_from_slice(bytes);
        Ok(bytes.len())
    }

    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

pub(super) fn render_runtime_status(status: &serde_json::Value) -> Result<String, ShellError> {
    let mut output = BoundedStatus::default();
    serde_json::to_writer_pretty(&mut output, status).map_err(|error| {
        ShellError::Backend(format!("cannot render bounded runtime status: {error}"))
    })?;
    String::from_utf8(output.0).map_err(|error| {
        ShellError::Backend(format!("runtime status rendering is not UTF-8: {error}"))
    })
}

#[cfg(test)]
#[path = "runtime_status_tests.rs"]
mod tests;

/// Adapt exact gateway observations to the shared Rust presentation core.
/// This runs on the existing worker, never the frame callback, and grants no authority.
pub(super) fn project_native_runtime_view(
    endpoint_id: &str,
    view: &crate::model::RuntimeView,
) -> Result<hepta_control_ui::native_projection::NativeReadOnlyProjection, ShellError> {
    hepta_control_ui::native_projection::project_native_view(
        hepta_control_ui::native_projection::NativeObservation {
            endpoint_id: endpoint_id.to_owned(),
            session_id: view.session_id.clone(),
            session_generation: view.session_generation,
            generation: view.generation,
            revision: view.revision,
            digest: view.digest.clone(),
            modules: view.modules.clone(),
        },
    )
    .map_err(|error| ShellError::Backend(format!("native control projection rejected: {error}")))
}
