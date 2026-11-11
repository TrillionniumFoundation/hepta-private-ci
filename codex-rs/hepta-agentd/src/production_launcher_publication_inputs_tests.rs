//! Descriptor custody only. No Root owner, publication enrollment or CURRENT
//! transition is constructed by this parser fixture.

use super::*;
use pretty_assertions::assert_eq;

const PUBLICATION: &str = "--root-generation-publication-handoff-fd";

fn add(arguments: &mut Vec<OsString>, flag: &str, fd: i32) {
    arguments.extend([flag.into(), fd.to_string().into()]);
}

fn retained(fd: i32) {
    // SAFETY: each descriptor remains owned by its fixture on refused parses.
    assert!(unsafe { libc::fcntl(fd, libc::F_GETFD) } >= 0);
}

#[test]
fn publication_requires_original_learning_before_claiming_any_right() -> anyhow::Result<()> {
    let fixture = DesktopDescriptors::new()?;
    let (publication, _peer) = UnixDatagram::pair()?;
    let fd = publication.as_raw_fd();
    let mut arguments = fixture.arguments();
    add(&mut arguments, PUBLICATION, fd);
    let error = parse(arguments).err().ok_or_else(|| anyhow::anyhow!("missing learning was accepted"))?;
    assert!(matches!(error, crate::AgentdError::Invalid(message)
        if message.contains("publication requires its learning handoff")));
    fixture.assert_retained();
    retained(fd);
    assert!(publication.local_addr()?.is_unnamed());
    Ok(())
}

#[test]
fn publication_partial_duplicate_standard_and_alias_inputs_keep_original_rights() -> anyhow::Result<()> {
    let fixture = DesktopDescriptors::new()?;
    let (learning, _learning_peer) = UnixDatagram::pair()?;
    let (model, _model_peer) = UnixDatagram::pair()?;
    let (publication, _publication_peer) = UnixDatagram::pair()?;
    let publication_fd = publication.as_raw_fd();
    let mut base = fixture.arguments();
    add(&mut base, "--root-learning-handoff-fd", learning.as_raw_fd());
    add(&mut base, "--root-q24-model-handoff-fd", model.as_raw_fd());
    let aliases = fixture.descriptors.iter().map(AsRawFd::as_raw_fd)
        .chain([learning.as_raw_fd(), model.as_raw_fd()]).collect::<Vec<_>>();
    for alias in aliases {
        let mut arguments = base.clone();
        add(&mut arguments, PUBLICATION, alias);
        let error = parse(arguments).err().ok_or_else(|| anyhow::anyhow!("alias accepted"))?;
        assert!(matches!(error, crate::AgentdError::Invalid(message)
            if message.contains("descriptors must be distinct")));
        fixture.assert_retained();
        retained(learning.as_raw_fd());
        retained(model.as_raw_fd());
        retained(publication_fd);
    }
    let mut duplicate = base.clone();
    add(&mut duplicate, PUBLICATION, publication_fd);
    add(&mut duplicate, PUBLICATION, publication_fd);
    let error = parse(duplicate).err().ok_or_else(|| anyhow::anyhow!("duplicate accepted"))?;
    assert!(matches!(error, crate::AgentdError::Invalid(message)
        if message.contains("duplicate original production launch flag")));
    for fd in [0, 1, 2] {
        let mut arguments = base.clone();
        add(&mut arguments, PUBLICATION, fd);
        let error = parse(arguments).err().ok_or_else(|| anyhow::anyhow!("standard stream accepted"))?;
        assert!(matches!(error, crate::AgentdError::Invalid(message)
            if message.contains("standard streams")));
    }
    assert!(parse(vec![PUBLICATION.into(), publication_fd.to_string().into()]).is_err());
    fixture.assert_retained();
    retained(learning.as_raw_fd());
    retained(model.as_raw_fd());
    retained(publication_fd);
    Ok(())
}

#[test]
fn publication_is_claimed_once_without_reading_or_connecting_its_offer() -> anyhow::Result<()> {
    let mut fixture = DesktopDescriptors::new()?;
    let (learning, _learning_peer) = UnixDatagram::pair()?;
    let (publication, publication_peer) = UnixDatagram::pair()?;
    let expected = publication.as_raw_fd();
    let pending = b"queued transport fixture, not Root authority";
    assert_eq!(publication_peer.send(pending)?, pending.len());
    let mut arguments = fixture.arguments();
    add(&mut arguments, "--root-learning-handoff-fd", learning.as_raw_fd());
    add(&mut arguments, PUBLICATION, expected);
    arguments.extend(["--objective-profile-file".into(), "/original/objective.json".into()]);
    for descriptor in fixture.descriptors.drain(..) {
        let _ = descriptor.into_raw_fd();
    }
    let _ = learning.into_raw_fd();
    let _ = publication.into_raw_fd();
    let (inputs, ordinary) = parse(arguments)?;
    let inputs = inputs.ok_or_else(|| anyhow::anyhow!("original launch missing"))?;
    assert!(inputs.q24_model_handoff.is_none(),
        "a retained/no-update purpose does not itself require a new Model offer");
    let publication = inputs.publication_handoff
        .ok_or_else(|| anyhow::anyhow!("original publication descriptor missing"))?;
    assert_eq!(publication.as_raw_fd(), expected);
    assert!(publication.local_addr()?.is_unnamed() && publication.peer_addr()?.is_unnamed());
    // SAFETY: this observes the sole descriptor retained by the actual parser.
    assert_ne!(unsafe { libc::fcntl(publication.as_raw_fd(), libc::F_GETFD) } & libc::FD_CLOEXEC, 0);
    publication.set_read_timeout(Some(Duration::from_millis(100)))?;
    let mut raw = [0; 128];
    let length = publication.recv(&mut raw)?;
    assert_eq!(&raw[..length], pending);
    assert_eq!(ordinary, vec![
        OsString::from("--objective-profile-file"), OsString::from("/original/objective.json"),
    ]);
    Ok(())
}
