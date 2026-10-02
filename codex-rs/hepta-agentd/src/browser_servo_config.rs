//! Selected artifact paths and limits for the Linux Browser composition.

use std::path::PathBuf;

use super::BrowserServoError;
use super::JS_SAFE_INTEGER;
use super::MAX_SERVICE_BYTES;
use super::MAX_WORKER_BYTES;
use super::artifact;

#[derive(Clone, Debug)]
pub struct BrowserServoProcessConfig {
    pub node_path: PathBuf,
    /// A bundled, standalone ESM artifact. The digest binds its complete bytes;
    /// the filename extension does not establish an import closure.
    pub service_path: PathBuf,
    pub service_sha256: [u8; 32],
    pub worker_path: PathBuf,
    pub worker_sha256: [u8; 32],
    pub profile_root: PathBuf,
    pub journal_path: PathBuf,
    pub bwrap_path: PathBuf,
    pub driver_timeout_ms: u64,
}

impl BrowserServoProcessConfig {
    pub fn validate(&self) -> Result<(), BrowserServoError> {
        self.validate_paths()?;
        artifact::verify_file_digest(&self.service_path, self.service_sha256, MAX_SERVICE_BYTES)?;
        artifact::verify_file_digest(&self.worker_path, self.worker_sha256, MAX_WORKER_BYTES)
    }

    pub(super) fn prepare_service_snapshot(
        &self,
    ) -> Result<artifact::ServiceSnapshot, BrowserServoError> {
        self.validate_paths()?;
        artifact::verify_file_digest(&self.worker_path, self.worker_sha256, MAX_WORKER_BYTES)?;
        let mut source = artifact::open_bounded(&self.service_path, MAX_SERVICE_BYTES)?;
        artifact::snapshot_service(&mut source, self.service_sha256, MAX_SERVICE_BYTES)
    }

    fn validate_paths(&self) -> Result<(), BrowserServoError> {
        for (name, path) in [
            ("Node executable", &self.node_path),
            ("Browser service", &self.service_path),
            ("Servo worker", &self.worker_path),
            ("Browser profile root", &self.profile_root),
            ("Browser journal", &self.journal_path),
            ("Bubblewrap executable", &self.bwrap_path),
        ] {
            if !path.is_absolute() {
                return Err(BrowserServoError::Invalid(format!(
                    "{name} path must be absolute"
                )));
            }
        }
        if self
            .service_path
            .extension()
            .and_then(|value| value.to_str())
            != Some("mjs")
        {
            return Err(BrowserServoError::Invalid(
                "Browser service must be a standalone bundled .mjs artifact".into(),
            ));
        }
        if self.driver_timeout_ms == 0 || self.driver_timeout_ms > JS_SAFE_INTEGER {
            return Err(BrowserServoError::Invalid(
                "Browser driver timeout must be a positive safe integer".into(),
            ));
        }
        Ok(())
    }
}
