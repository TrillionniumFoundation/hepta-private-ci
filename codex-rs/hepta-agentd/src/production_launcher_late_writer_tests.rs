//! Negative admission tests use only identity data and unprivileged inherited
//! descriptors. Actual Root/Starting success belongs to the UID0 parent fixture.

use super::*;
use std::os::fd::AsRawFd;
use std::os::fd::IntoRawFd;
use std::os::unix::net::UnixListener;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::ResourceBudget;
use pretty_assertions::assert_eq;

struct DescriptorInputs {
    descriptors: Vec<OwnedFd>,
    _root_peer: UnixDatagram,
    _directory: tempfile::TempDir,
}

impl DescriptorInputs {
    fn new() -> anyhow::Result<Self> {
        let directory = tempfile::tempdir()?;
        let (handoff, peer) = UnixDatagram::pair()?;
        let control = UnixListener::bind(directory.path().join("control.sock"))?;
        let app_server = UnixListener::bind(directory.path().join("app.sock"))?;
        let producer = tempfile::tempfile()?;
        let payload = File::open(format!("/proc/self/fd/{}", producer.as_raw_fd()))?;
        Ok(Self {
            descriptors: vec![
                handoff.into(),
                control.into(),
                app_server.into(),
                payload.into(),
            ],
            _root_peer: peer,
            _directory: directory,
        })
    }

    fn arguments(&self) -> anyhow::Result<Vec<OsString>> {
        let mut clock = libc::timespec {
            tv_sec: 0,
            tv_nsec: 0,
        };
        // SAFETY: the kernel writes one initialized, live stack timespec.
        anyhow::ensure!(unsafe { libc::clock_gettime(libc::CLOCK_MONOTONIC, &mut clock) } == 0);
        let deadline = clock.tv_sec as u64 * 1_000_000_000 + clock.tv_nsec as u64 + 10_000_000_000;
        // SAFETY: only actual kernel credentials are observed.
        let actual = unsafe { libc::geteuid() };
        let wrong_owner = if actual == 60001 { 60002 } else { 60001 };
        let mut arguments = Vec::new();
        for (flag, value) in [
            ("--root-production-profile", "android".to_string()),
            (
                "--root-production-handoff-fd",
                self.descriptors[0].as_raw_fd().to_string(),
            ),
            ("--root-production-uid", wrong_owner.to_string()),
            ("--root-production-gid", wrong_owner.to_string()),
            (
                "--root-production-control-fd",
                self.descriptors[1].as_raw_fd().to_string(),
            ),
            (
                "--root-production-app-server-fd",
                self.descriptors[2].as_raw_fd().to_string(),
            ),
            (
                "--android-runtime-server",
                "original-component-server".to_string(),
            ),
            (
                "--android-runtime-environment",
                "original-component-environment".to_string(),
            ),
            (
                "--android-original-payload-fd",
                self.descriptors[3].as_raw_fd().to_string(),
            ),
            ("--android-original-deadline-ns", deadline.to_string()),
        ] {
            arguments.extend([OsString::from(flag), OsString::from(value)]);
        }
        Ok(arguments)
    }
}

fn identity() -> anyhow::Result<(tempfile::TempDir, AgentdIdentity)> {
    let directory = tempfile::tempdir()?;
    let fleet = directory.path().join("fleet");
    let workspace = directory.path().join("workspace");
    std::fs::create_dir(&fleet)?;
    std::fs::create_dir(&workspace)?;
    // This supplies only the exact-comparison argument, no registry admission,
    // Root proof, retained source, consumer or writer capability.
    let expected = crate::HostAuthorityRegisteredIdentity {
        agent_id: AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?,
        spawn_generation: 1,
        fleet_root: fleet.canonicalize()?,
        workspace: workspace.canonicalize()?,
        resources: ResourceBudget::local_default(),
    }
    .identity()?;
    Ok((directory, expected))
}

#[tokio::test]
async fn late_writer_refuses_incomplete_and_aliased_inputs_before_claiming_rights()
-> anyhow::Result<()> {
    let (_identity_root, expected) = identity()?;
    let fixture = DescriptorInputs::new()?;
    let partial = vec![
        OsString::from("--root-production-handoff-fd"),
        OsString::from(fixture.descriptors[0].as_raw_fd().to_string()),
    ];
    let mut aliased = fixture.arguments()?;
    let handoff = aliased[3].clone();
    let control = aliased
        .iter()
        .position(|value| value == "--root-production-control-fd")
        .ok_or_else(|| anyhow::anyhow!("control argument absent"))?;
    aliased[control + 1] = handoff;
    for arguments in [Vec::new(), partial, aliased] {
        let result =
            AgentdProductionLaunch::receive_original_late_writer(arguments, &expected).await;
        assert!(matches!(result, Err(AgentdError::Invalid(_))));
        for descriptor in &fixture.descriptors {
            // SAFETY: F_GETFD only inspects each still-owned original descriptor.
            assert!(unsafe { libc::fcntl(descriptor.as_raw_fd(), libc::F_GETFD) } >= 0);
        }
    }
    Ok(())
}

#[tokio::test]
async fn late_writer_requires_actual_credentials_before_receiving_any_root_offer()
-> anyhow::Result<()> {
    let (_identity_root, expected) = identity()?;
    let mut fixture = DescriptorInputs::new()?;
    let arguments = fixture.arguments()?;
    for descriptor in fixture.descriptors.drain(..) {
        // Ownership passes once into the original parser, even on later refusal.
        let _ = descriptor.into_raw_fd();
    }
    let result = AgentdProductionLaunch::receive_original_late_writer(arguments, &expected).await;
    let Err(AgentdError::Invalid(reason)) = result else {
        anyhow::bail!("actual owner mismatch reached another startup stage");
    };
    assert_eq!(
        reason,
        "late writer requires its already dedicated actual non-Root owner",
    );
    Ok(())
}

#[test]
fn late_writer_cli_entry_is_explicit_and_preserves_ordinary_bytes() -> anyhow::Result<()> {
    use super::super::late_startup::OriginalStartupSelection;
    use super::super::late_startup::select_original_startup_entry;
    use std::os::unix::ffi::OsStringExt;

    let ordinary = vec![
        OsString::from("--objective-profile-file"),
        OsString::from_vec(b"/original/profile-\xff".to_vec()),
        OsString::from("--original-value"),
        OsString::from("--root-production-entry"),
    ];
    assert_eq!(
        select_original_startup_entry(ordinary.clone())?,
        OriginalStartupSelection::Existing(ordinary.clone()),
    );
    let mut explicit = vec![
        OsString::from("--root-production-entry"),
        OsString::from("late-writer"),
    ];
    explicit.extend(ordinary.clone());
    assert_eq!(
        select_original_startup_entry(explicit)?,
        OriginalStartupSelection::LateWriter(ordinary),
    );
    Ok(())
}

#[test]
fn late_writer_cli_entry_refuses_duplicate_or_unknown_modes_before_rights() -> anyhow::Result<()> {
    use super::super::late_startup::select_original_startup_entry;

    let fixture = DescriptorInputs::new()?;
    for values in [
        vec!["--root-production-entry"],
        vec!["--root-production-entry", "fresh"],
        vec![
            "--root-production-entry",
            "late-writer",
            "--root-production-entry",
            "late-writer",
        ],
    ] {
        let arguments = values.into_iter().map(OsString::from).collect();
        assert!(select_original_startup_entry(arguments).is_err());
        for descriptor in &fixture.descriptors {
            // SAFETY: observe the still-owned original descriptor.
            assert!(unsafe { libc::fcntl(descriptor.as_raw_fd(), libc::F_GETFD) } >= 0);
        }
    }
    Ok(())
}

#[test]
fn late_writer_cli_preflight_consumes_failed_owner_attempt_without_default_fallback()
-> anyhow::Result<()> {
    let mut fixture = DescriptorInputs::new()?;
    let mut arguments = vec![
        OsString::from("--root-production-entry"),
        OsString::from("late-writer"),
    ];
    arguments.extend(fixture.arguments()?);
    for descriptor in fixture.descriptors.drain(..) {
        let _ = descriptor.into_raw_fd();
    }
    let result = AgentdProductionStartup::from_process_environment(arguments);
    let Err(AgentdError::Invalid(reason)) = result else {
        anyhow::bail!("explicit late-writer owner refusal changed phase or fell back");
    };
    assert_eq!(
        reason,
        "late writer requires its already dedicated actual non-Root owner"
    );
    // Observe the retained kernel socket, not a possibly reused numeric FD.
    assert!(fixture._root_peer.send(b"original-offer").is_err());
    Ok(())
}
