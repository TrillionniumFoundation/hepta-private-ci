use std::ffi::OsString;
use std::os::fd::AsRawFd;
use std::os::fd::IntoRawFd;
use std::os::unix::net::UnixDatagram;
use std::time::Duration;
use std::time::Instant;

use pretty_assertions::assert_eq;

use super::original_deadline;
use super::parse;
use super::read_payload;
use super::take_readonly_file;

#[test]
fn ordinary_daemon_arguments_remain_byte_exact() -> anyhow::Result<()> {
    use std::os::unix::ffi::OsStringExt;

    let arguments = vec![
        OsString::from("--objective-profile-file"),
        OsString::from_vec(b"/original/profile-\xff".to_vec()),
    ];
    let (production, ordinary) = parse(arguments.clone())?;
    assert!(production.is_none());
    assert_eq!(ordinary, arguments);
    Ok(())
}

#[test]
fn partial_and_duplicate_launch_flags_preserve_inherited_rights() -> anyhow::Result<()> {
    let (handoff, _root) = UnixDatagram::pair()?;
    let descriptor = handoff.as_raw_fd();
    let flag = OsString::from("--root-production-handoff-fd");
    let value = OsString::from(descriptor.to_string());
    assert!(parse(vec![flag.clone(), value.clone()]).is_err());
    assert!(parse(vec![flag.clone(), value.clone(), flag, value]).is_err());
    // SAFETY: F_GETFD only observes the live descriptor owned by handoff.
    assert!(unsafe { libc::fcntl(descriptor, libc::F_GETFD) } >= 0);
    assert!(handoff.local_addr()?.is_unnamed());
    Ok(())
}

#[test]
fn absolute_original_deadline_cannot_be_renewed() -> anyhow::Result<()> {
    assert!(original_deadline(0).is_err());
    assert!(original_deadline(u64::MAX).is_err());
    let before = Instant::now();
    let mut clock = libc::timespec { tv_sec: 0, tv_nsec: 0 };
    // SAFETY: the kernel initializes one valid stack timespec.
    anyhow::ensure!(unsafe { libc::clock_gettime(libc::CLOCK_MONOTONIC, &mut clock) } == 0);
    let deadline = (clock.tv_sec as u64) * 1_000_000_000 + clock.tv_nsec as u64 + 10_000_000_000;
    let converted = original_deadline(deadline)?;
    assert!(converted > before);
    // Cross-clock sampling may only shorten the launcher's original bound.
    assert!(converted <= Instant::now() + Duration::from_secs(10));
    Ok(())
}

#[test]
fn ordinary_payload_file_is_not_a_sealed_original_input() -> anyhow::Result<()> {
    use std::io::Write;

    let mut payload = tempfile::tempfile()?;
    payload.write_all(b"{}")?;
    assert!(read_payload(payload).is_err());
    Ok(())
}

#[test]
fn inherited_deployment_cannot_retain_the_root_producers_writable_description() -> anyhow::Result<()> {
    let producer = tempfile::tempfile()?;
    let writable_duplicate = producer.try_clone()?;
    let descriptor = writable_duplicate.as_raw_fd();
    assert!(take_readonly_file(descriptor).is_err());
    // Refusal does not adopt or close the caller's writable descriptor.
    // SAFETY: F_GETFD only observes the live descriptor retained above.
    assert!(unsafe { libc::fcntl(descriptor, libc::F_GETFD) } >= 0);
    let reader = std::fs::File::open(format!("/proc/self/fd/{}", producer.as_raw_fd()))?;
    let reader = take_readonly_file(reader.into_raw_fd())?;
    // A separate read-only description remains usable after ownership moves.
    assert_eq!(reader.metadata()?.len(), producer.metadata()?.len());
    // SAFETY: both queries read metadata of the live consumer descriptor.
    let (flags, mode) = unsafe {
        (libc::fcntl(reader.as_raw_fd(), libc::F_GETFD), libc::fcntl(reader.as_raw_fd(), libc::F_GETFL))
    };
    assert!(flags & libc::FD_CLOEXEC != 0);
    assert_eq!(mode & libc::O_ACCMODE, libc::O_RDONLY);
    Ok(())
}
