use super::*;
use pretty_assertions::assert_eq;

#[test]
fn another_live_thread_is_rejected_without_changing_credentials() {
    // This checks the admission barrier only, never performs privilege changes.
    // SAFETY: getuid/geteuid/getgid/getegid read kernel credentials.
    let before = unsafe { (libc::getuid(), libc::geteuid(), libc::getgid(), libc::getegid()) };
    let (ready, wait) = std::sync::mpsc::channel();
    let (release, held) = std::sync::mpsc::channel();
    let worker = std::thread::spawn(move || {
        ready.send(()).unwrap();
        held.recv().unwrap();
    });
    wait.recv().unwrap();
    let error = require_single_thread().err().expect("a live worker must refuse credential transition");
    assert!(matches!(error, AgentdError::GenerationFenced(message) if message.contains("runtime thread")));
    release.send(()).unwrap();
    worker.join().unwrap();
    // SAFETY: read the same actual kernel credential fields after refusal.
    assert_eq!(unsafe { (libc::getuid(), libc::geteuid(), libc::getgid(), libc::getegid()) }, before);
}
