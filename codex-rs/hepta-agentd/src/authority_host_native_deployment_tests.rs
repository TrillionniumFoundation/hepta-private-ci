use super::*;
use std::fs::OpenOptions;
use std::os::fd::AsFd;
use std::os::fd::FromRawFd;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::process::CommandExt;

#[test]
fn foreign_descriptors_never_become_deployment_locks() {
    let (socket, _other) = std::os::unix::net::UnixStream::pair().unwrap();
    assert!(NativeDeploymentLock::from_inherited(socket.into()).is_err());
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("lock");
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .mode(0o644)
        .open(&path)
        .unwrap();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o644)).unwrap();
    assert!(NativeDeploymentLock::from_inherited(file.into()).is_err());
    let unlinked = tempfile::tempfile().unwrap();
    assert!(NativeDeploymentLock::from_inherited(unlinked.into()).is_err());
}

#[test]
fn protected_lock_is_retained_and_closes_on_exec() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("lock");
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .mode(0o600)
        .open(&path)
        .unwrap();
    let descriptor = file.as_fd().try_clone_to_owned().unwrap();
    // User-mode tests verify rejection; root-mode runs exercise the actual
    // deployment lock lifetime. Neither branch changes the real host owner.
    if file.metadata().unwrap().uid() != 0 {
        assert!(NativeDeploymentLock::from_inherited(descriptor).is_err());
        return;
    }
    let raw = descriptor.as_raw_fd();
    let guard = NativeDeploymentLock::from_inherited(descriptor).unwrap();
    drop(file);
    // SAFETY: the guard owns raw and F_GETFD only observes its flags.
    assert_ne!(
        unsafe { libc::fcntl(raw, libc::F_GETFD) } & libc::FD_CLOEXEC,
        0
    );
    let contender = OpenOptions::new()
        .read(true)
        .write(true)
        .open(&path)
        .unwrap();
    assert!(NativeDeploymentLock::from_inherited(contender.into()).is_err());
    drop(guard);
    let successor = OpenOptions::new()
        .read(true)
        .write(true)
        .open(&path)
        .unwrap();
    NativeDeploymentLock::from_inherited(successor.into()).unwrap();
}

#[test]
fn native_child_cannot_inherit_any_duplicate_deployment_descriptor() {
    let file = tempfile::tempfile().unwrap();
    // Deliberately create an inheritable alias at a high fd so the exec'd shell
    // cannot accidentally reuse its number for stdio or its script input.
    // SAFETY: file owns a live descriptor and fcntl returns a new one.
    let raw = unsafe { libc::fcntl(file.as_raw_fd(), libc::F_DUPFD, 128) };
    assert!(raw >= 128);
    // SAFETY: successful F_DUPFD returned this new owned descriptor.
    let _alias = unsafe { OwnedFd::from_raw_fd(raw) };
    let visible = format!("test -e /proc/self/fd/{raw}");
    assert!(
        std::process::Command::new("/bin/sh")
            .args(["-c", &visible])
            .status()
            .unwrap()
            .success()
    );
    let invisible = format!("test ! -e /proc/self/fd/{raw}");
    let mut child = std::process::Command::new("/bin/sh");
    child.args(["-c", &invisible]);
    // SAFETY: the production hook runs only async-signal-safe descriptor calls.
    unsafe {
        child.pre_exec(protect_child_descriptors);
    }
    assert!(child.status().unwrap().success());
    // The parent's descriptor must remain available with its original flags.
    // SAFETY: _alias still owns raw; F_GETFD only observes its flags.
    assert_eq!(
        unsafe { libc::fcntl(raw, libc::F_GETFD) } & libc::FD_CLOEXEC,
        0
    );
}

#[test]
fn managed_release_cannot_bypass_the_prefix_lock_via_generic_launch() {
    let directory = tempfile::tempdir().unwrap();
    let program = directory
        .path()
        .join("releases/aaaaaaaaaaaa-bbbbbbbbbbbb/bin/trill-shell");
    assert!(verify_program_lock(&program, /*lock*/ None).is_err());
    let path = directory.path().join(".native-deployment.lock");
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .mode(0o600)
        .open(&path)
        .unwrap();
    if file.metadata().unwrap().uid() != 0 {
        return;
    }
    let lock = NativeDeploymentLock::from_inherited(file.into()).unwrap();
    verify_program_lock(&program, Some(&lock)).unwrap();
    let other = tempfile::tempdir().unwrap();
    let other_program = other
        .path()
        .join("releases/aaaaaaaaaaaa-bbbbbbbbbbbb/bin/trill-shell");
    assert!(verify_program_lock(&other_program, Some(&lock)).is_err());
    std::fs::rename(&path, directory.path().join("old-lock")).unwrap();
    let _replacement = OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(0o600)
        .open(&path)
        .unwrap();
    assert!(verify_program_lock(&program, Some(&lock)).is_err());
}
