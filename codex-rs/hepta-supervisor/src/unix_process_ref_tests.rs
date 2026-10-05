#![cfg(any(target_os = "linux", target_os = "macos"))]

use std::io;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

use super::ProcessRef;

struct ChildOwner(Child);

impl ChildOwner {
    fn spawn() -> Self {
        Self(
            Command::new("/bin/sleep")
                .arg("30")
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()
                .expect("spawn owned lifetime fixture"),
        )
    }

    fn reference(&self) -> ProcessRef {
        ProcessRef::open(self.0.id())
            .expect("stable process reference is required on this host")
            .expect("fixture is live")
    }
}

impl Drop for ChildOwner {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

fn observe_exit(reference: &ProcessRef) {
    let deadline = Instant::now() + Duration::from_secs(3);
    loop {
        if reference.exited().expect("poll stable process reference") {
            return;
        }
        assert!(
            Instant::now() < deadline,
            "kernel exit observation exceeded deadline"
        );
        std::thread::sleep(Duration::from_millis(1));
    }
}

#[test]
fn lifetime_reference_rejects_nonpositive_and_out_of_range_pids() {
    assert!(ProcessRef::open(0).is_err());
    assert!(ProcessRef::open(u32::MAX).is_err());
}

#[test]
fn lifetime_reference_signals_exact_live_process_and_observes_exit() {
    let mut child = ChildOwner::spawn();
    let reference = child.reference();
    assert!(!reference.exited().expect("initial lifetime"));
    reference
        .signal(libc::SIGTERM)
        .expect("signal exact lifetime");
    observe_exit(&reference);
    assert!(!child.0.wait().expect("reap owned child").success());
    // Darwin's one-shot kqueue event must remain an immutable observation.
    assert!(reference.exited().expect("repeat terminal observation"));
}

#[test]
fn expired_lifetime_cannot_signal_a_later_process() {
    let mut predecessor = ChildOwner::spawn();
    let reference = predecessor.reference();
    predecessor.0.kill().expect("kill owned predecessor");
    predecessor
        .0
        .wait()
        .expect("reap predecessor before later spawn");
    observe_exit(&reference);
    let mut unrelated = ChildOwner::spawn();
    for signal in [libc::SIGTERM, libc::SIGKILL] {
        let error = reference
            .signal(signal)
            .expect_err("dead lifetime cannot deliver signal");
        assert_eq!(error.raw_os_error(), Some(libc::ESRCH));
        assert!(
            unrelated
                .0
                .try_wait()
                .expect("observe unrelated child")
                .is_none()
        );
    }
    // This is a real lifetime/reap test, not a forced numeric-PID-reuse receipt.
}

#[test]
fn unsupported_signal_is_rejected_without_touching_process() {
    let mut child = ChildOwner::spawn();
    let reference = child.reference();
    let error = reference
        .signal(libc::SIGUSR1)
        .expect_err("unregistered control signal");
    assert_eq!(error.kind(), io::ErrorKind::InvalidInput);
    assert!(child.0.try_wait().expect("owned child is live").is_none());
}

#[test]
fn dropping_reference_does_not_terminate_the_owned_process() {
    let mut child = ChildOwner::spawn();
    drop(child.reference());
    assert!(child.0.try_wait().expect("owned child is live").is_none());
}
