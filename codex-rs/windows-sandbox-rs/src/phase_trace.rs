use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::process::Command;
use std::process::Stdio;
use std::sync::OnceLock;

const PHASE_TRACE_ENV: &str = "SBX_PHASE_TRACE";

fn enabled() -> bool {
    static ENABLED: OnceLock<bool> = OnceLock::new();
    *ENABLED.get_or_init(|| std::env::var(PHASE_TRACE_ENV).ok().as_deref() == Some("1"))
}

/// Records lifecycle boundaries only when the diagnostic trace is enabled.
///
/// Callers supply phase names and object paths, never credentials, request
/// payloads, token contents, lease witnesses or environment maps.
pub fn trace_sandbox_phase(phase: &str, base_dir: Option<&Path>) {
    if !enabled() {
        return;
    }
    let line = format!(
        "PHASE pid={} thread={:?} {phase}",
        std::process::id(),
        std::thread::current().id(),
    );
    crate::logging::log_note(&line, base_dir);
    // A disappearing diagnostic reader must not change helper authorization or
    // lifetime behavior. In particular, do not panic on a broken stderr pipe.
    let _ = writeln!(
        std::io::stderr().lock(),
        "[{}] {line}",
        chrono::Utc::now().to_rfc3339(),
    );
}

pub(crate) fn configure_helper_phase_stderr(command: &mut Command, base_dir: &Path) {
    if !enabled() {
        return;
    }
    // The orchestrator opens the existing log destination with its own rights.
    // The helper can trace a mutex wait through this inherited handle before
    // validating its lease, without opening an elevated path before admission.
    let path = crate::logging::current_log_file_path(base_dir);
    match OpenOptions::new().create(true).append(true).open(path) {
        Ok(file) => {
            command.stderr(Stdio::from(file));
        }
        Err(error) => trace_sandbox_phase(
            &format!("helper phase log unavailable: {:?}", error.kind()),
            Some(base_dir),
        ),
    }
}
