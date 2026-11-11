//! Original descriptor parsing only. These fixtures neither enroll Root nor
//! publish a model; actual initial CURRENT/FinalUse belongs to its UID0 parent.

use std::ffi::OsString;
use std::os::fd::AsRawFd;
use std::os::fd::IntoRawFd;
use std::os::unix::net::UnixDatagram;

use super::DesktopDescriptors;
use super::parse;
use pretty_assertions::assert_eq;

#[test]
fn initial_offer_transfers_once_without_learning_or_model_inputs() -> anyhow::Result<()> {
    let mut fixture = DesktopDescriptors::new()?;
    let (initial, _root) = UnixDatagram::pair()?;
    let expected = initial.as_raw_fd();
    let mut arguments = fixture.arguments();
    arguments.extend([
        "--root-generation-initial-handoff-fd".into(),
        expected.to_string().into(),
        "--objective-profile-file".into(),
        "/original/first-task.json".into(),
    ]);
    for descriptor in fixture.descriptors.drain(..) {
        let _ = descriptor.into_raw_fd();
    }
    let _ = initial.into_raw_fd();
    let (inputs, ordinary) = parse(arguments)?;
    let inputs = inputs.ok_or_else(|| anyhow::anyhow!("original initial launch absent"))?;
    assert!(inputs.learning_handoff.is_none() && inputs.q24_model_handoff.is_none());
    assert!(inputs.publication_handoff.is_none());
    let initial = inputs
        .initial_handoff
        .ok_or_else(|| anyhow::anyhow!("original initial descriptor was lost"))?;
    assert_eq!(initial.as_raw_fd(), expected);
    assert!(initial.local_addr()?.is_unnamed() && initial.peer_addr()?.is_unnamed());
    assert_eq!(
        ordinary,
        vec![
            OsString::from("--objective-profile-file"),
            OsString::from("/original/first-task.json"),
        ]
    );
    // SAFETY: only observes the actual sole retained descriptor's metadata.
    assert_ne!(
        unsafe { libc::fcntl(initial.as_raw_fd(), libc::F_GETFD) } & libc::FD_CLOEXEC,
        0
    );
    Ok(())
}

#[test]
fn initial_and_learned_publication_refuse_before_any_descriptor_is_taken() -> anyhow::Result<()> {
    let fixture = DesktopDescriptors::new()?;
    let (initial, _initial_root) = UnixDatagram::pair()?;
    let (publication, _publication_root) = UnixDatagram::pair()?;
    let (learning, _learning_root) = UnixDatagram::pair()?;
    let mut arguments = fixture.arguments();
    for (name, file) in [
        ("--root-generation-initial-handoff-fd", &initial),
        ("--root-generation-publication-handoff-fd", &publication),
        ("--root-learning-handoff-fd", &learning),
    ] {
        arguments.extend([name.into(), file.as_raw_fd().to_string().into()]);
    }
    let Err(crate::AgentdError::Invalid(message)) = parse(arguments) else {
        anyhow::bail!("mixed original purposes must refuse before ownership transfer");
    };
    assert_eq!(
        message,
        "initial and learned publication require separate original Root sessions"
    );
    fixture.assert_retained();
    for file in [&initial, &publication, &learning] {
        // SAFETY: these original descriptors were never adopted by a parser.
        assert!(unsafe { libc::fcntl(file.as_raw_fd(), libc::F_GETFD) } >= 0);
    }
    Ok(())
}

#[test]
fn initial_aliases_incomplete_and_duplicate_flags_preserve_original_rights() -> anyhow::Result<()> {
    let fixture = DesktopDescriptors::new()?;
    let (initial, _root) = UnixDatagram::pair()?;
    let flag = OsString::from("--root-generation-initial-handoff-fd");
    let value = OsString::from(initial.as_raw_fd().to_string());
    assert!(parse(vec![flag.clone(), value.clone()]).is_err());
    let mut duplicated = fixture.arguments();
    duplicated.extend([flag.clone(), value.clone(), flag.clone(), value]);
    assert!(parse(duplicated).is_err());
    fixture.assert_retained();
    for descriptor in &fixture.descriptors {
        let mut arguments = fixture.arguments();
        arguments.extend([flag.clone(), descriptor.as_raw_fd().to_string().into()]);
        let Err(crate::AgentdError::Invalid(message)) = parse(arguments) else {
            anyhow::bail!("aliased initial descriptor must refuse");
        };
        assert_eq!(message, "original production descriptors must be distinct");
        fixture.assert_retained();
    }
    // SAFETY: the dedicated initial socket is still owned by this fixture.
    assert!(unsafe { libc::fcntl(initial.as_raw_fd(), libc::F_GETFD) } >= 0);
    assert!(initial.local_addr()?.is_unnamed());
    Ok(())
}
