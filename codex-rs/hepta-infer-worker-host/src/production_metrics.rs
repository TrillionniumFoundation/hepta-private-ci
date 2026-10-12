//! Production native control bootstrap: the WAL and its independent Evidence
//! metric journal must both reopen successfully before the Worker runs.
//!
//! Telemetry is never an authorization source and cannot cause effect replay.
//! A failed final flush instead withholds the production acceptance signal.

use std::error::Error;
use std::io;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;

use codex_hepta_agentd::DurablePhaseMetricSinkV1;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;

const METRICS_QUEUE_CAPACITY: usize = 4_096;
const METRICS_GROUP_SIZE: usize = 128;
const METRICS_FLUSH_INTERVAL_MS: u64 = 250;

/// A separate sibling journal avoids mixing telemetry lines into the control
/// WAL. The caller must hold an owner-only directory and an absolute path.
pub fn production_metrics_journal_path_v1(journal: &Path) -> Result<PathBuf, io::Error> {
    if !journal.is_absolute() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "native control journal must have an absolute path",
        ));
    }
    let file_name = journal.file_name().ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            "native control journal must have a file name",
        )
    })?;
    let mut metrics_name = file_name.to_os_string();
    metrics_name.push(".metrics");
    Ok(journal.with_file_name(metrics_name))
}

/// Opens actual control WAL and the persistent Evidence metrics sink. A
/// corrupt, locked or unavailable metrics journal denies Worker readiness;
/// no empty or no-op telemetry fallback is permitted on this serving path.
pub fn open_metrics_bound_native_control_v1(
    journal: &Path,
    capacity: usize,
) -> Result<DurableInferenceControl, Box<dyn Error + Send + Sync>> {
    let metrics_path = production_metrics_journal_path_v1(journal)?;
    let control = DurableInferenceControl::open(journal, capacity)?;
    let metrics = Arc::new(DurablePhaseMetricSinkV1::open(
        &metrics_path,
        /* capacity */ METRICS_QUEUE_CAPACITY,
        /* group_size */ METRICS_GROUP_SIZE,
        /* flush_interval_ms */ METRICS_FLUSH_INTERVAL_MS,
    )?);
    let control = control.with_metrics_sink(metrics);
    if !control.production_metrics_ready() {
        return Err("native inference control has no healthy persistent metrics sink".into());
    }
    Ok(control)
}

#[cfg(test)]
#[path = "production_metrics_tests.rs"]
mod tests;
