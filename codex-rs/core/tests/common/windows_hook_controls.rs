//! Failure-only comparisons for the fixed-print Queue fixture. File snapshots
//! change capture semantics and never replace the original result/assertions.

use std::io;
use std::io::Read;
use std::path::Path;
use std::process::Command;
use std::process::ExitStatus;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

use base64::Engine;
use tempfile::NamedTempFile;

const OUTPUT_CAP: u64 = 16 * 1024;
const CONTROL_DEADLINE: Duration = Duration::from_secs(5);
const REAP_DEADLINE: Duration = Duration::from_secs(2);
const POLL_INTERVAL: Duration = Duration::from_millis(10);
const FIXTURE_SCRIPT: &[u8] = b"print('queue-python-exact-path')\n";
const EXPECTED_MARKER: &str = "queue-python-exact-path";

#[derive(Default)]
struct Snapshot {
    file_len: Option<u64>,
    captured_bytes: Option<usize>,
    marker_match: Option<bool>,
    read_complete: bool,
    error: Option<io::Error>,
}

fn error_code(error: &Option<io::Error>) -> Option<String> {
    error
        .as_ref()
        .map(|error| format!("{:?}/os={:?}", error.kind(), error.raw_os_error()))
}

impl Snapshot {
    fn read(file: &NamedTempFile) -> Self {
        let mut snapshot = Self::default();
        let read = (|| {
            snapshot.file_len = Some(file.as_file().metadata()?.len());
            // ReOpenFile supplies an independent cursor. try_clone + seek could
            // move a surviving writer's shared file position.
            let reader = file.reopen()?;
            snapshot.read_bytes(reader)?;
            Ok::<_, io::Error>(())
        })();
        snapshot.error = read.err();
        snapshot
    }

    fn read_bytes(&mut self, reader: impl Read) -> io::Result<()> {
        let mut bytes = Vec::new();
        let result = reader.take(OUTPUT_CAP).read_to_end(&mut bytes);
        self.captured_bytes = Some(bytes.len());
        result?;
        self.read_complete = true;
        // This compares only a bounded snapshot, never claims stream EOF.
        self.marker_match = Some(String::from_utf8_lossy(&bytes).trim() == EXPECTED_MARKER);
        Ok(())
    }

    fn report(&self) -> String {
        let error = error_code(&self.error);
        format!(
            "file_len_at_observation={:?} snapshot_bytes={:?} snapshot_read_complete={} snapshot_marker_match={:?} error={error:?}",
            self.file_len, self.captured_bytes, self.read_complete, self.marker_match
        )
    }
}

#[derive(Default)]
struct ControlResult {
    status: Option<ExitStatus>,
    stop: &'static str,
    error: Option<io::Error>,
    kill_error: Option<io::Error>,
    reap_error: Option<io::Error>,
    reap_unconfirmed: bool,
    stdout: Snapshot,
    stderr: Snapshot,
    cleanup_errors: Vec<String>,
}

impl ControlResult {
    fn report(&self) -> String {
        let status = self.status.map(|status| status.to_string());
        let error = error_code(&self.error);
        let kill_error = error_code(&self.kill_error);
        let reap_error = error_code(&self.reap_error);
        let stdout = self.stdout.report();
        let stderr = self.stderr.report();
        format!(
            "status={status:?} stop={} error={error:?} kill_error={kill_error:?} reap_error={reap_error:?} reap_unconfirmed={} stdout=[{stdout}] stderr=[{stderr}] cleanup_errors={:?}",
            self.stop, self.reap_unconfirmed, self.cleanup_errors
        )
    }
}

// Deliberately no Debug: encoded_command contains private paths.
pub struct HookControls {
    pub encoded_command: Option<String>,
    direct: Option<ControlResult>,
    encoded: Option<ControlResult>,
    fixture_error: Option<io::Error>,
    fixture_matches: bool,
}

impl HookControls {
    pub fn report(&self, sanitize: &impl Fn(&str) -> String) -> String {
        let direct = self.direct.as_ref().map(ControlResult::report);
        let encoded = self.encoded.as_ref().map(ControlResult::report);
        let fixture_error = error_code(&self.fixture_error);
        sanitize(&format!(
            "capture_mode=file-snapshot snapshot_not_stream_eof=true direct={direct:?} encoded={encoded:?} encoded_applicable={} fixture_matches={} fixture_error={fixture_error:?} cleanup_scope=direct-child-only descendants_may_survive=true descendants_may_keep_writing=true deletion_may_remain_pending=true disk_growth_not_strictly_bounded=true synchronous_os_calls_not_interruptible=true",
            self.encoded_command.is_some(),
            self.fixture_matches
        ))
    }
}

/// Compare only the fixed Queue print fixture, using captured identities.
/// File redirection changes capture semantics: success suggests transport or
/// capture sensitivity, not uniquely command parsing. Each applicable control
/// runs once. The caller adds encoded_command to its redactions and preserves
/// the original assertion failure regardless of these results.
pub fn run_queue_python_controls(
    python: &Path,
    program: &str,
    argv: &[String],
    command: &str,
    script: &Path,
    cwd: &Path,
) -> HookControls {
    let mut result = HookControls {
        encoded_command: None,
        direct: None,
        encoded: None,
        fixture_error: None,
        fixture_matches: false,
    };
    match std::fs::read(script) {
        Ok(bytes) => result.fixture_matches = bytes == FIXTURE_SCRIPT,
        Err(error) => result.fixture_error = Some(error),
    }
    if !result.fixture_matches {
        return result;
    }
    // Limit this helper to the exact command constructed for that fixed script.
    let expected = format!(
        "& '{}' '{}'",
        python.to_string_lossy().replace('\'', "''"),
        script.to_string_lossy().replace('\'', "''")
    );
    if argv
        .last()
        .is_some_and(|arg| arg.eq_ignore_ascii_case("-Command"))
        && command == expected
    {
        result.encoded_command = Some(encode_command(command));
    }
    let mut direct = Command::new(python);
    direct.arg(script);
    result.direct = Some(collect(direct, cwd));
    if let Some(encoded) = &result.encoded_command {
        let mut child = Command::new(program);
        child
            .args(&argv[..argv.len() - 1])
            .arg("-EncodedCommand")
            .arg(encoded);
        result.encoded = Some(collect(child, cwd));
    }
    result
}

fn encode_command(command: &str) -> String {
    let bytes = command
        .encode_utf16()
        .flat_map(u16::to_le_bytes)
        .collect::<Vec<_>>();
    base64::engine::general_purpose::STANDARD.encode(bytes)
}

fn close_file(file: NamedTempFile, result: &mut ControlResult) {
    if let Err(error) = file.close() {
        result
            .cleanup_errors
            .push(format!("{:?}/os={:?}", error.kind(), error.raw_os_error()));
    }
}

fn collect(mut command: Command, cwd: &Path) -> ControlResult {
    let deadline = Instant::now() + CONTROL_DEADLINE;
    let mut result = ControlResult::default();
    let stdout = match NamedTempFile::new_in(cwd) {
        Ok(file) => file,
        Err(error) => {
            return ControlResult {
                stop: "stdout_file_error",
                error: Some(error),
                ..Default::default()
            };
        }
    };
    let stderr = match NamedTempFile::new_in(cwd) {
        Ok(file) => file,
        Err(error) => {
            result.stop = "stderr_file_error";
            result.error = Some(error);
            close_file(stdout, &mut result);
            return result;
        }
    };
    let spawn = (|| {
        command
            .current_dir(cwd)
            .env("PATH", "")
            .stdin(Stdio::null())
            .stdout(Stdio::from(stdout.reopen()?))
            .stderr(Stdio::from(stderr.reopen()?));
        command.spawn()
    })();
    // Release the parent's write handles before snapshot/removal attempts.
    drop(command);
    match spawn {
        Err(error) => {
            result.stop = "spawn_error";
            result.error = Some(error);
        }
        Ok(mut child) => {
            loop {
                match child.try_wait() {
                    Ok(status) => result.status = status,
                    Err(error) => {
                        result.stop = "wait_error";
                        result.error = Some(error);
                        break;
                    }
                }
                let sizes = stdout.as_file().metadata().and_then(|out| {
                    stderr
                        .as_file()
                        .metadata()
                        .map(|err| (out.len(), err.len()))
                });
                match sizes {
                    Ok((out, err)) if out > OUTPUT_CAP || err > OUTPUT_CAP => {
                        result.stop = "file_cap";
                        break;
                    }
                    Ok(_) => {}
                    Err(error) => {
                        result.stop = "metadata_error";
                        result.error = Some(error);
                        break;
                    }
                }
                if result.status.is_some() {
                    result.stop = "root_exited";
                    break;
                }
                let now = Instant::now();
                if now >= deadline {
                    result.stop = "process_deadline";
                    break;
                }
                std::thread::sleep(POLL_INTERVAL.min(deadline - now));
            }
            if result.status.is_none() {
                result.kill_error = child.kill().err();
                let reap_deadline = Instant::now() + REAP_DEADLINE;
                loop {
                    match child.try_wait() {
                        Ok(Some(status)) => {
                            result.status = Some(status);
                            break;
                        }
                        Ok(None) => {}
                        Err(error) => {
                            result.reap_error = Some(error);
                            result.reap_unconfirmed = true;
                            break;
                        }
                    }
                    let now = Instant::now();
                    if now >= reap_deadline {
                        result.reap_unconfirmed = true;
                        break;
                    }
                    std::thread::sleep(POLL_INTERVAL.min(reap_deadline - now));
                }
            }
        }
    }
    // Snapshots are non-atomic and are never emitted as bytes/text. Surviving
    // descendants can keep writing after return, even if deletion is pending.
    // Length polling cannot impose a hard disk-write cap. Synchronous process
    // creation and filesystem calls cannot themselves be interrupted here.
    result.stdout = Snapshot::read(&stdout);
    result.stderr = Snapshot::read(&stderr);
    close_file(stdout, &mut result);
    close_file(stderr, &mut result);
    result
}

#[cfg(test)]
#[path = "windows_hook_controls_tests.rs"]
mod tests;
