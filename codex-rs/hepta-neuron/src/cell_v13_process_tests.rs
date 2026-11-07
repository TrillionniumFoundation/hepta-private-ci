//! Actual owned Python transport, without model assets or trained-model claims.

use std::fs;
use std::path::PathBuf;

use pretty_assertions::assert_eq;

use super::*;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

static NEXT: AtomicU64 = AtomicU64::new(0);

struct Directory(PathBuf);

impl Directory {
    fn new() -> TestResult<Self> {
        let id = NEXT.fetch_add(1, Ordering::Relaxed);
        let path =
            std::env::temp_dir().join(format!("hepta-v13-process-{}-{id}", std::process::id()));
        fs::create_dir(&path)?;
        Ok(Self(path))
    }
}

impl Drop for Directory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

struct Interpreter {
    path: PathBuf,
    file: File,
    digest: [u8; 32],
}

impl Interpreter {
    fn open() -> TestResult<Self> {
        // Python is an explicit prerequisite of the Linux transport, and a
        // missing interpreter fails this test rather than skipping execution.
        let path = PathBuf::from("/usr/bin/python3").canonicalize()?;
        let file = File::open(&path)?;
        let digest = executable_digest(&file)?;
        Ok(Self { path, file, digest })
    }

    fn request<'a>(
        &'a self,
        script: &'a str,
        cancellation: &'a AtomicBool,
        clock: &'a (dyn Fn() -> u64 + Send + Sync),
    ) -> ProcessRequest<'a> {
        ProcessRequest {
            executable: &self.file,
            executable_digest: self.digest,
            interpreter_argv0: &self.path,
            script,
            payload: Vec::new(),
            cancellation,
            deadline_micros: 1_000_000,
            wall_limit: Duration::from_secs(5),
            clock,
        }
    }
}

#[test]
fn actual_transport_preserves_bytes_and_counts_both_pipe_directions() -> TestResult {
    let interpreter = Interpreter::open()?;
    let cancellation = AtomicBool::new(false);
    let clock = || 1;
    let payload = b"actual bounded caller input\n".repeat(2048);
    let mut request = interpreter.request(
        "import sys; data=sys.stdin.buffer.read(); sys.stdout.buffer.write(data[::-1]); sys.stdout.buffer.flush()",
        &cancellation,
        &clock,
    );
    request.payload = payload.clone();
    let observed = run(request)?;
    assert!(matches!(observed.status, ProcessStatus::Succeeded));
    assert_eq!(
        observed.stdout,
        payload.iter().rev().copied().collect::<Vec<_>>()
    );
    assert_eq!(
        observed.communication_bytes,
        2 * u64::try_from(payload.len())?
    );
    assert!(observed.wall_micros > 0);
    Ok(())
}

#[test]
fn cancellation_after_actual_child_entry_waits_for_its_terminal_observation() -> TestResult {
    let directory = Directory::new()?;
    let marker = directory.0.join("entered");
    let interpreter = Interpreter::open()?;
    let cancellation = AtomicBool::new(false);
    let script = format!(
        "import pathlib,time; pathlib.Path({}).write_text('entered'); time.sleep(60)",
        serde_json::to_string(&marker)?
    );
    let clock = || {
        if marker.exists() {
            cancellation.store(true, Ordering::Release);
        }
        1
    };
    let observed = run(interpreter.request(&script, &cancellation, &clock))?;
    assert!(marker.exists());
    assert!(matches!(observed.status, ProcessStatus::Cancelled));
    assert!(observed.stdout.is_empty());
    assert!(observed.wall_micros > 0);
    Ok(())
}

#[test]
fn expired_precontact_deadline_and_stalled_clock_wall_limit_are_distinct() -> TestResult {
    let directory = Directory::new()?;
    let marker = directory.0.join("entered");
    let interpreter = Interpreter::open()?;
    let cancellation = AtomicBool::new(false);
    let clock = || 1;
    let script = format!(
        "import pathlib,time; pathlib.Path({}).write_text('entered'); time.sleep(60)",
        serde_json::to_string(&marker)?
    );
    let mut expired = interpreter.request(&script, &cancellation, &clock);
    expired.deadline_micros = 1;
    let observed = run(expired)?;
    assert!(matches!(observed.status, ProcessStatus::Deadline));
    assert!(!marker.exists());
    assert_eq!(observed.communication_bytes, 0);

    // A callback that never advances cannot defeat the independent wall bound.
    let mut stalled = interpreter.request("import time; time.sleep(60)", &cancellation, &clock);
    stalled.wall_limit = Duration::from_millis(50);
    let observed = run(stalled)?;
    assert!(matches!(observed.status, ProcessStatus::Deadline));
    assert!(observed.stdout.is_empty());
    Ok(())
}

#[test]
fn actual_child_overflow_and_clock_regression_cannot_be_success() -> TestResult {
    let directory = Directory::new()?;
    let marker = directory.0.join("entered");
    let interpreter = Interpreter::open()?;
    let cancellation = AtomicBool::new(false);
    let overflow = run(interpreter.request(
        "import sys; sys.stdout.buffer.write(b'x' * 200000); sys.stdout.buffer.flush()",
        &cancellation,
        &|| 2,
    ))?;
    assert!(matches!(overflow.status, ProcessStatus::Failed));
    assert!(overflow.stdout.is_empty());
    assert!(overflow.communication_bytes > MAX_PROCESS_RESULT_BYTES as u64);

    let script = format!(
        "import pathlib,time; pathlib.Path({}).write_text('entered'); time.sleep(60)",
        serde_json::to_string(&marker)?
    );
    let clock = || if marker.exists() { 1 } else { 2 };
    let observed = run(interpreter.request(&script, &cancellation, &clock))?;
    assert!(marker.exists());
    assert!(matches!(observed.status, ProcessStatus::Failed));
    assert!(observed.stdout.is_empty());
    Ok(())
}
