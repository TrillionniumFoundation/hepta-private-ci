use std::ffi::OsString;
use std::fs::File;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::fd::IntoRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixDatagram;
use std::os::unix::net::UnixListener;
use std::time::Duration;
use std::time::Instant;

use pretty_assertions::assert_eq;

use super::PrimaryInputs;
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
    let mut clock = libc::timespec {
        tv_sec: 0,
        tv_nsec: 0,
    };
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
fn inherited_deployment_cannot_retain_the_root_producers_writable_description() -> anyhow::Result<()>
{
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
        (
            libc::fcntl(reader.as_raw_fd(), libc::F_GETFD),
            libc::fcntl(reader.as_raw_fd(), libc::F_GETFL),
        )
    };
    assert!(flags & libc::FD_CLOEXEC != 0);
    assert_eq!(mode & libc::O_ACCMODE, libc::O_RDONLY);
    Ok(())
}

struct DesktopDescriptors {
    descriptors: Vec<OwnedFd>,
    _peers: [UnixDatagram; 2],
    _directory: tempfile::TempDir,
}

impl DesktopDescriptors {
    fn new() -> anyhow::Result<Self> {
        let directory = tempfile::tempdir()?;
        let (root, root_peer) = UnixDatagram::pair()?;
        let (desktop, desktop_peer) = UnixDatagram::pair()?;
        let control = UnixListener::bind(directory.path().join("control.sock"))?;
        let app_server = UnixListener::bind(directory.path().join("app-server.sock"))?;
        let producer = tempfile::tempfile()?;
        let deployment = File::open(format!("/proc/self/fd/{}", producer.as_raw_fd()))?;
        // SAFETY: pidfd_open creates one new held descriptor for this test's
        // actual process; no numeric-PID signalling or external process is used.
        let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, std::process::id(), 0) };
        anyhow::ensure!(raw >= 0, "{}", std::io::Error::last_os_error());
        // SAFETY: this owns exactly the new descriptor returned above.
        let session = unsafe { OwnedFd::from_raw_fd(raw as i32) };
        Ok(Self {
            descriptors: vec![
                root.into(),
                control.into(),
                app_server.into(),
                desktop.into(),
                deployment.into(),
                session,
            ],
            _peers: [root_peer, desktop_peer],
            _directory: directory,
        })
    }

    fn arguments(&self) -> Vec<OsString> {
        let mut arguments = [
            "--root-production-profile",
            "desktop",
            "--root-production-uid",
            "1000",
            "--root-production-gid",
            "1000",
        ]
        .map(OsString::from)
        .to_vec();
        for (name, descriptor) in [
            "--root-production-handoff-fd",
            "--root-production-control-fd",
            "--root-production-app-server-fd",
            "--desktop-production-handoff-fd",
            "--desktop-thread-deployment-fd",
            "--desktop-session-pidfd",
        ]
        .into_iter()
        .zip(&self.descriptors)
        {
            arguments.extend([name.into(), descriptor.as_raw_fd().to_string().into()]);
        }
        arguments
    }

    fn assert_retained(&self) {
        for descriptor in &self.descriptors {
            // SAFETY: F_GETFD only observes this fixture's owned descriptors.
            assert!(unsafe { libc::fcntl(descriptor.as_raw_fd(), libc::F_GETFD) } >= 0);
        }
    }
}

#[test]
fn explicit_desktop_transfers_distinct_readonly_capabilities_without_notes_inputs()
-> anyhow::Result<()> {
    let mut fixture = DesktopDescriptors::new()?;
    let arguments = fixture.arguments();
    let expected = fixture
        .descriptors
        .iter()
        .map(AsRawFd::as_raw_fd)
        .collect::<Vec<_>>();
    for descriptor in fixture.descriptors.drain(..) {
        // Ownership is explicitly transferred once to the production parser.
        let _ = descriptor.into_raw_fd();
    }
    let (inputs, ordinary) = parse(arguments)?;
    let inputs = inputs.ok_or_else(|| anyhow::anyhow!("explicit Desktop was not selected"))?;
    assert!(ordinary.is_empty() && inputs.notes.is_none() && inputs.notes_ui.is_none());
    let PrimaryInputs::Desktop {
        handoff,
        deployment,
        session_pidfd,
        deadline,
    } = inputs.primary
    else {
        anyhow::bail!("Desktop was reinterpreted as another primary");
    };
    assert_eq!(
        vec![
            inputs.handoff.as_raw_fd(),
            inputs.control.as_raw_fd(),
            inputs.app_server.as_raw_fd(),
            handoff.as_raw_fd(),
            deployment.as_raw_fd(),
            session_pidfd.as_raw_fd()
        ],
        expected,
    );
    assert!(deadline.remaining()? <= Duration::from_secs(30));
    // SAFETY: both operations inspect the retained live deployment consumer.
    let (mode, flags) = unsafe {
        (
            libc::fcntl(deployment.as_raw_fd(), libc::F_GETFL),
            libc::fcntl(deployment.as_raw_fd(), libc::F_GETFD),
        )
    };
    assert_eq!(mode & libc::O_ACCMODE, libc::O_RDONLY);
    assert!(flags & libc::FD_CLOEXEC != 0);
    Ok(())
}

#[test]
fn partial_mixed_and_alias_desktop_inputs_refuse_before_taking_rights() -> anyhow::Result<()> {
    let fixture = DesktopDescriptors::new()?;
    for omitted in [
        "--desktop-production-handoff-fd",
        "--desktop-thread-deployment-fd",
        "--desktop-session-pidfd",
    ] {
        let arguments = fixture
            .arguments()
            .chunks_exact(2)
            .filter(|pair| pair[0] != omitted)
            .flatten()
            .cloned()
            .collect();
        assert!(parse(arguments).is_err());
        fixture.assert_retained();
    }
    for (flag, value) in [
        (
            "--notes-production-handoff-fd",
            fixture.descriptors[3].as_raw_fd().to_string(),
        ),
        ("--android-runtime-server", "existing-runtime".into()),
    ] {
        let mut arguments = fixture.arguments();
        arguments.extend([flag.into(), value.into()]);
        assert!(parse(arguments).is_err());
        fixture.assert_retained();
    }
    let mut aliased = fixture.arguments();
    let value = aliased
        .iter()
        .position(|arg| arg == "--desktop-session-pidfd")
        .unwrap()
        + 1;
    aliased[value] = fixture.descriptors[0].as_raw_fd().to_string().into();
    assert!(parse(aliased).is_err());
    fixture.assert_retained();
    Ok(())
}
