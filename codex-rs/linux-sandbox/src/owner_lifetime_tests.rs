use super::*;
use std::os::fd::IntoRawFd;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::sync::mpsc;
use std::time::Duration;

fn running_owner() -> io::Result<(Child, File)> {
    let child = Command::new("/bin/sh")
        .args(["-c", "read token || :"])
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()?;
    let owner = open_pidfd(child.id() as libc::pid_t)?;
    Ok((child, owner))
}

#[test]
fn already_exited_owner_is_rejected_before_payload_start() {
    let (mut child, owner) = running_owner().expect("start an owner waiting for stdin EOF");
    ensure_owner_alive(&owner).expect("live owner is admitted");
    drop(child.stdin.take());
    assert!(child.wait().expect("reap owner").success());

    assert!(ensure_owner_alive(&owner).is_err());
    wait_for_owner_exit(&owner).expect("an already reaped owner's pidfd is ready");
}

#[test]
fn owner_exit_is_observed_after_observer_start() {
    let (mut child, owner) = running_owner().expect("start an owner waiting for stdin EOF");
    ensure_owner_alive(&owner).expect("owner is alive before waiting");
    let (started_tx, started_rx) = mpsc::channel();
    let (finished_tx, finished_rx) = mpsc::channel();
    let waiter = thread::spawn(move || {
        started_tx.send(()).expect("announce waiter");
        finished_tx
            .send(wait_for_owner_exit(&owner))
            .expect("report owner exit");
    });
    started_rx
        .recv_timeout(Duration::from_secs(5))
        .expect("waiter starts before owner exits");
    assert!(finished_rx.try_recv().is_err());
    drop(child.stdin.take());
    assert!(child.wait().expect("reap owner").success());
    finished_rx
        .recv_timeout(Duration::from_secs(5))
        .expect("owner exit is observed")
        .expect("pidfd observation succeeds");
    waiter
        .join()
        .expect("waiter joins after observing owner exit");
}

#[test]
fn inherited_owner_handle_is_resealed_before_inner_setup() {
    let owner = open_current_owner().expect("open current owner");
    let fd = owner.as_raw_fd();
    assert_eq!(unsafe { libc::fcntl(fd, libc::F_SETFD, 0) }, 0);
    let inherited_fd = owner.into_raw_fd();
    // SAFETY: into_raw_fd transferred exclusive ownership of this open fd.
    let inherited = unsafe { take_inherited_owner(inherited_fd) }.expect("take inherited owner");
    ensure_owner_alive(&inherited).expect("same owner remains alive");
    let flags = unsafe { libc::fcntl(inherited.as_raw_fd(), libc::F_GETFD) };
    assert!(flags >= 0, "read owner descriptor flags");
    assert_ne!(flags & libc::FD_CLOEXEC, 0);
}
