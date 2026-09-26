//! Observations from the ordinary GUI startup, not the static smoke profile.
use crate::error::ShellError;
use crate::model::{RuntimeView, SessionIncarnation};
use std::path::PathBuf;
use std::time::Instant;

pub struct StartupRecorder {
    path: PathBuf,
    started: Instant,
    manifest_digest: String,
}
impl StartupRecorder {
    pub fn new(path: PathBuf, started: Instant, manifest_digest: String) -> Self {
        Self {
            path,
            started,
            manifest_digest,
        }
    }
    pub(crate) fn record(
        self,
        session: &SessionIncarnation,
        view: &RuntimeView,
    ) -> Result<(), ShellError> {
        session.validate()?;
        view.validate()?;
        if view.session_id != session.session_id || view.session_generation != session.generation {
            return Err(ShellError::State(
                "startup view has mixed session identity".into(),
            ));
        }
        crate::update_storage::persist_json_atomic(
            &self.path,
            &serde_json::json!({
                "schema":"hepta.native-product-startup.v1", "process_id":std::process::id(),
                "endpoint_manifest_digest":self.manifest_digest, "session":session,
                "view_digest":view.digest, "view_revision":view.revision,
                "elapsed_ms":self.started.elapsed().as_millis(), "gui_frame_callback_completed":true,
                "platform_acceptance":false, "screen_reader_acceptance":false,
                "independent_acceptance":false, "release":false
            }),
        )
    }
}
