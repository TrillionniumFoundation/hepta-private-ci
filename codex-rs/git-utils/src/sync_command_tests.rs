use super::GitCommandCancellation;
use super::run_git_command_with_custody;
use pretty_assertions::assert_eq;
use std::io::Write;
use std::process::Command;
use std::sync::mpsc;
use std::time::Duration;
use std::time::Instant;

const FIXTURE: &str = "sync_command::tests::native_sync_fixture";
const ROLE: &str = "CODEX_GIT_SYNC_CUSTODY_FIXTURE_ROLE";
const READY: &str = "CODEX_GIT_SYNC_CUSTODY_FIXTURE_READY";
const PAYLOAD_BYTES: usize = 128 * 1024;

struct CancelOnDrop(GitCommandCancellation);

impl Drop for CancelOnDrop {
    fn drop(&mut self) {
        self.0.cancel();
    }
}

fn command(role: &str) -> Command {
    let mut command = Command::new(std::env::current_exe().unwrap());
    command
        .args(["--ignored", "--exact", FIXTURE, "--nocapture"])
        .env(ROLE, role);
    command
}

fn payload(bytes: &[u8], begin: &[u8], end: &[u8]) -> Vec<u8> {
    let start = bytes
        .windows(begin.len())
        .position(|window| window == begin)
        .unwrap()
        + begin.len();
    let remainder = &bytes[start..];
    let finish = remainder
        .windows(end.len())
        .position(|window| window == end)
        .unwrap();
    remainder[..finish].to_vec()
}

#[test]
fn native_output_larger_than_pipe_buffers_is_captured_without_an_eof_wait() {
    let output = run_git_command_with_custody(
        &mut command("large-output"),
        "native capture fixture",
        Duration::from_secs(5),
        &GitCommandCancellation::default(),
    )
    .unwrap();
    assert!(output.status.success());
    assert_eq!(
        payload(
            &output.stdout,
            b"CAPTURE_STDOUT_BEGIN",
            b"CAPTURE_STDOUT_END"
        ),
        vec![b'x'; PAYLOAD_BYTES]
    );
    assert_eq!(
        payload(
            &output.stderr,
            b"CAPTURE_STDERR_BEGIN",
            b"CAPTURE_STDERR_END"
        ),
        vec![b'y'; PAYLOAD_BYTES]
    );
}

#[test]
fn cancellation_stops_a_real_in_flight_command_before_its_original_timeout() {
    let directory = tempfile::tempdir().unwrap();
    let ready = directory.path().join("ready");
    let cancellation = GitCommandCancellation::default();
    std::thread::scope(|scope| {
        let _cancel_on_exit = CancelOnDrop(cancellation.clone());
        let worker_cancellation = cancellation.clone();
        let worker_ready = ready.clone();
        let (done, terminal) = mpsc::channel();
        let worker = scope.spawn(move || {
            let mut command = command("hold");
            command.env(READY, worker_ready);
            let result = run_git_command_with_custody(
                &mut command,
                "native cancellation fixture",
                Duration::from_secs(30),
                &worker_cancellation,
            );
            done.send(result).unwrap();
        });
        let deadline = Instant::now() + Duration::from_secs(5);
        while !ready.exists() {
            assert!(
                Instant::now() < deadline,
                "actual native fixture did not start"
            );
            std::thread::sleep(Duration::from_millis(5));
        }
        assert_eq!(terminal.try_recv().unwrap_err(), mpsc::TryRecvError::Empty);
        cancellation.cancel();
        let error = terminal
            .recv_timeout(Duration::from_secs(5))
            .unwrap()
            .unwrap_err();
        assert!(
            error.contains("cancelled"),
            "unexpected terminal error: {error}"
        );
        worker.join().unwrap();
    });
}

#[test]
#[ignore = "native helper invoked by the exact owning test executable"]
fn native_sync_fixture() {
    match std::env::var(ROLE).unwrap().as_str() {
        "large-output" => {
            let mut stdout = std::io::stdout().lock();
            stdout.write_all(b"CAPTURE_STDOUT_BEGIN").unwrap();
            stdout.write_all(&vec![b'x'; PAYLOAD_BYTES]).unwrap();
            stdout.write_all(b"CAPTURE_STDOUT_END").unwrap();
            stdout.flush().unwrap();
            let mut stderr = std::io::stderr().lock();
            stderr.write_all(b"CAPTURE_STDERR_BEGIN").unwrap();
            stderr.write_all(&vec![b'y'; PAYLOAD_BYTES]).unwrap();
            stderr.write_all(b"CAPTURE_STDERR_END").unwrap();
            stderr.flush().unwrap();
        }
        "hold" => {
            std::fs::write(std::env::var_os(READY).unwrap(), b"actual child started").unwrap();
            loop {
                std::thread::sleep(Duration::from_secs(1));
            }
        }
        role => panic!("unknown native fixture role: {role}"),
    }
}
