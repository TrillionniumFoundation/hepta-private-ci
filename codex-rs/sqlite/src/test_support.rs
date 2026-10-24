//! Original test-only temporary-name helper, retained without runtime metadata.

use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;
use uuid::Uuid;

#[cfg(test)]
pub(crate) fn unique_temp_dir() -> PathBuf {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |duration| duration.as_nanos());
    std::env::temp_dir().join(format!(
        "codex-state-runtime-test-{nanos}-{}",
        Uuid::new_v4()
    ))
}
