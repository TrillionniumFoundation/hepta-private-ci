use std::os::fd::AsFd;
use std::os::fd::OwnedFd;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::Sha256Digest;
use pretty_assertions::assert_eq;

use super::*;

fn binding() -> ActionSkillBindingV1 {
    ActionSkillBindingV1 {
        provider_intent: ProviderEffectIntent::new(
            ProviderEffectKey::for_logical_effect("native.wait.test", "original").unwrap(),
            Sha256Digest::for_bytes(b"payload"),
        ),
        effect_intent_digest: Sha256Digest::for_bytes(b"effect"),
        contract_digest: Sha256Digest::for_bytes(b"contract"),
        destination_id: "native.wait.test".into(),
    }
}

#[test]
fn actual_pidfd_and_pipe_identify_only_the_original_blocked_reader() {
    let mut child = Command::new("/bin/sh")
        .args(["-c", "IFS= read -r line; test \"$line\" = resume"])
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
    let pid = child.id();
    let writer: OwnedFd = child.stdin.take().unwrap().into();
    let process = rustix::process::Pid::from_raw(pid as i32).unwrap();
    let pidfd = rustix::process::pidfd_open(process, rustix::process::PidfdFlags::empty()).unwrap();
    let observer = NativeProcessInputWaitObserver::from_inherited(
        pidfd.as_fd(),
        writer.as_fd(),
        pid,
        0,
        binding(),
    )
    .unwrap();
    let deadline = Instant::now() + Duration::from_secs(5);
    let evidence = loop {
        match observer.observe().unwrap() {
            NativeProcessInputWaitObservationV1::WaitingForInput { evidence } => break evidence,
            NativeProcessInputWaitObservationV1::Unknown => {
                assert!(
                    Instant::now() < deadline,
                    "child never blocked on original stdin"
                );
                std::thread::sleep(Duration::from_millis(5));
            }
        }
    };
    assert_eq!(evidence.binding, binding());
    assert_eq!(evidence.process_id, pid);
    assert_eq!(evidence.input_reader_fd, 0);
    assert!(evidence.process_start_ticks > 0);

    drop(observer);
    assert!(
        child.try_wait().unwrap().is_none(),
        "dropping the observer must not close the owner's input capability"
    );
    drop(writer);
    assert!(!child.wait().unwrap().success());
}

#[test]
fn compute_and_network_sleep_never_become_input_wait() {
    for command in ["sleep 30", "while :; do :; done"] {
        let mut child = Command::new("/bin/sh")
            .args(["-c", command])
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .unwrap();
        let pid = child.id();
        let writer: OwnedFd = child.stdin.take().unwrap().into();
        let process = rustix::process::Pid::from_raw(pid as i32).unwrap();
        let pidfd =
            rustix::process::pidfd_open(process, rustix::process::PidfdFlags::empty()).unwrap();
        let observer = NativeProcessInputWaitObserver::from_inherited(
            pidfd.as_fd(),
            writer.as_fd(),
            pid,
            0,
            binding(),
        )
        .unwrap();
        std::thread::sleep(Duration::from_millis(25));
        assert_eq!(
            observer.observe().unwrap(),
            NativeProcessInputWaitObservationV1::Unknown
        );
        child.kill().unwrap();
        child.wait().unwrap();
    }
}

#[test]
fn wrong_reader_descriptor_is_refused_before_observation() {
    let mut child = Command::new("/bin/sh")
        .args(["-c", "IFS= read -r line"])
        .stdin(Stdio::piped())
        .spawn()
        .unwrap();
    let pid = child.id();
    let writer: OwnedFd = child.stdin.take().unwrap().into();
    let process = rustix::process::Pid::from_raw(pid as i32).unwrap();
    let pidfd = rustix::process::pidfd_open(process, rustix::process::PidfdFlags::empty()).unwrap();
    let error = NativeProcessInputWaitObserver::from_inherited(
        pidfd.as_fd(),
        writer.as_fd(),
        pid,
        9,
        binding(),
    )
    .err()
    .unwrap();
    assert!(matches!(error, NativeProcessWaitError::Unavailable(_)));
    child.kill().unwrap();
    child.wait().unwrap();
}

#[test]
fn stopped_original_reader_remains_unknown_until_resumed() {
    struct OwnedChild(std::process::Child);

    impl Drop for OwnedChild {
        fn drop(&mut self) {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }

    let mut child = OwnedChild(
        Command::new("/bin/sh")
            .args(["-c", "IFS= read -r line; test \"$line\" = resume"])
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .unwrap(),
    );
    let pid = child.0.id();
    let writer: OwnedFd = child.0.stdin.take().unwrap().into();
    let process = rustix::process::Pid::from_raw(pid as i32).unwrap();
    let pidfd = rustix::process::pidfd_open(process, rustix::process::PidfdFlags::empty()).unwrap();
    let observer = NativeProcessInputWaitObserver::from_inherited(
        pidfd.as_fd(),
        writer.as_fd(),
        pid,
        0,
        binding(),
    )
    .unwrap();
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        if matches!(
            observer.observe().unwrap(),
            NativeProcessInputWaitObservationV1::WaitingForInput { .. }
        ) {
            break;
        }
        assert!(Instant::now() < deadline, "reader never reached input wait");
        std::thread::sleep(Duration::from_millis(5));
    }

    rustix::process::pidfd_send_signal(pidfd.as_fd(), rustix::process::Signal::STOP).unwrap();
    let deadline = Instant::now() + Duration::from_secs(5);
    while process_snapshot(pid).unwrap().1 != 'T' {
        assert!(Instant::now() < deadline, "original reader never stopped");
        std::thread::sleep(Duration::from_millis(5));
    }
    assert!(
        blocked_in_read(pid, 0).unwrap(),
        "stopped reader must retain the original read syscall for this regression"
    );
    for _ in 0..3 {
        assert_eq!(
            observer.observe().unwrap(),
            NativeProcessInputWaitObservationV1::Unknown
        );
    }

    rustix::process::pidfd_send_signal(pidfd.as_fd(), rustix::process::Signal::CONT).unwrap();
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        if matches!(
            observer.observe().unwrap(),
            NativeProcessInputWaitObservationV1::WaitingForInput { .. }
        ) {
            break;
        }
        assert!(Instant::now() < deadline, "resumed reader lost input wait");
        std::thread::sleep(Duration::from_millis(5));
    }
    drop(observer);
    drop(writer);
    assert!(!child.0.wait().unwrap().success());
}
