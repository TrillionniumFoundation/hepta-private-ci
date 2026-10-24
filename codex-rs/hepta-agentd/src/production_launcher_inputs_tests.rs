use std::ffi::OsString;
use std::os::fd::AsRawFd;
use std::os::unix::net::UnixDatagram;
use std::time::Duration;
use std::time::Instant;

use pretty_assertions::assert_eq;

use super::original_deadline;
use super::parse;
use super::read_payload;

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
