//! Real child ownership tests with deterministic post-acquisition setup faults.
//! These do not inject host resource exhaustion or certify a deployed binary.

use std::process::Command;
use std::process::Stdio;

use super::*;
use crate::ManagedProcess;
use crate::ProcessState;

struct ChildCleanup(Child);

impl Drop for ChildCleanup {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

struct Cleanup(UnixManagedProcess);

impl Drop for Cleanup {
    fn drop(&mut self) {
        let _ = self.0.kill();
        if let UnixProcessHandle::Child(child) = &mut self.0.handle {
            let _ = child.wait();
        }
    }
}

fn child(stdout: bool, stderr: bool) -> Child {
    Command::new("/bin/sh")
        .args(["-c", "exec sleep 10"])
        .stdin(Stdio::null())
        .stdout(if stdout { Stdio::piped() } else { Stdio::null() })
        .stderr(if stderr { Stdio::piped() } else { Stdio::null() })
        .spawn()
        .expect("real test child")
}

fn inactive_probe() -> HealthProbe {
    HealthProbe {
        ready: Arc::new(AtomicBool::new(false)),
        shutdown: Arc::new(AtomicBool::new(true)),
    }
}

#[test]
fn failed_probe_retains_both_main_and_companion_child_handles() {
    for companion in [false, true] {
        let child = child(true, true);
        let pid = child.id();
        let acquired = finish_child(
            child,
            u64::MAX,
            companion,
            Err(ProcessDriverError::new("injected probe thread creation failure")),
            None,
            1,
        );
        let mut retained = Cleanup(acquired.process);
        assert_eq!(acquired.identity.system_id(), u64::from(pid));
        assert_eq!(retained.0.initialization_failure(), Some("injected probe thread creation failure"));
        assert!(matches!(retained.0.poll(0).expect("poll").state,
            ProcessState::Running { healthy: false, drained: false }));
        assert!(retained.0.request_drain().is_err());
        retained.0.kill().expect("retained child can be terminated");
        let UnixProcessHandle::Child(child) = &mut retained.0.handle else {
            panic!("spawned child ownership was replaced");
        };
        child.wait().expect("observe actual exit");
        assert!(matches!(retained.0.poll(0).expect("terminal observation").state,
            ProcessState::Exited(_)));
        assert!(retained.0.initialization_failure().is_some());
    }
}

#[test]
fn missing_log_pipe_is_a_retained_failure_not_a_dropped_child() {
    for (stdout, stderr) in [(false, true), (true, false), (false, false)] {
        let acquired = finish_child(child(stdout, stderr), 7, false, Ok(inactive_probe()), None, 1);
        let mut retained = Cleanup(acquired.process);
        assert!(retained.0.initialization_failure().is_some());
        assert!(matches!(retained.0.poll(0).expect("poll").state,
            ProcessState::Running { healthy: false, drained: false }));
        retained.0.kill().expect("kill after pipe setup failure");
    }
}

#[test]
fn generated_identity_remains_bounded_at_numeric_extremes() {
    for companion in [false, true] {
        let text = if companion {
            format!("unix-matrix-pid-{}-agent-generation-{}", u32::MAX, u64::MAX)
        } else {
            format!("unix-pid-{}-generation-{}", u32::MAX, u64::MAX)
        };
        assert!(text.len() <= 79);
        ProcessIdentity::new(u64::from(u32::MAX), text).expect("bounded constructor invariant");
    }
}

#[cfg(any(target_os = "linux", target_os = "macos"))]
#[test]
fn failed_probe_retains_an_adopted_lifetime_reference() {
    let mut original = ChildCleanup(child(true, true));
    let reference = ProcessRef::open(original.0.id())
        .expect("host process-reference acquisition")
        .expect("live reference");
    let mut retained = Cleanup(finish_adoption(
        reference,
        Err(ProcessDriverError::new("injected adopted probe failure")),
        None,
    ));
    assert!(retained.0.initialization_failure().is_some());
    retained.0.kill().expect("signal exact adopted reference");
    original.0.wait().expect("observe actual child exit");
    assert!(matches!(retained.0.poll(0).expect("reference observation").state,
        ProcessState::Exited(_)));
}
