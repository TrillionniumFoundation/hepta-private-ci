//! Parser custody controls use real local descriptors. They do not establish
//! a real Root session, a human original turn, or a training authorization.

use super::*;
use pretty_assertions::assert_eq;

fn arguments(
    fixture: &DesktopDescriptors,
    ui: &UnixListener,
    paired: &UnixDatagram,
) -> Vec<OsString> {
    let mut arguments = fixture.arguments();
    for pair in arguments.chunks_exact_mut(2) {
        match pair[0].to_str().unwrap() {
            "--root-production-profile" => pair[1] = "notes".into(),
            "--desktop-production-handoff-fd" => pair[0] = "--notes-production-handoff-fd".into(),
            "--desktop-thread-deployment-fd" => pair[0] = "--notes-literal-deployment-fd".into(),
            "--desktop-session-pidfd" => pair[0] = "--notes-session-pidfd".into(),
            _ => {}
        }
    }
    arguments.extend([
        "--notes-literal-ui-fd".into(),
        ui.as_raw_fd().to_string().into(),
        "--root-paired-training-handoff-fd".into(),
        paired.as_raw_fd().to_string().into(),
        "--paired-failure-record-digest".into(),
        "12".repeat(32).into(),
        "--paired-correction-record-digest".into(),
        "34".repeat(32).into(),
    ]);
    arguments
}

#[test]
fn paired_group_and_canonical_pins_refuse_before_taking_original_rights() -> anyhow::Result<()> {
    let fixture = DesktopDescriptors::new()?;
    let ui = UnixListener::bind(fixture._directory.path().join("notes-ui.sock"))?;
    let (paired, _root) = UnixDatagram::pair()?;
    let original = arguments(&fixture, &ui, &paired);
    for omitted in [
        "--root-paired-training-handoff-fd",
        "--paired-failure-record-digest",
        "--paired-correction-record-digest",
    ] {
        let incomplete = original
            .chunks_exact(2)
            .filter(|pair| pair[0] != omitted)
            .flatten()
            .cloned()
            .collect();
        assert!(parse(incomplete).is_err());
        fixture.assert_retained();
    }
    for invalid in [
        "0".repeat(64),
        "A".repeat(64),
        "1".repeat(63),
        "g".repeat(64),
    ] {
        let mut malformed = original.clone();
        let index = malformed
            .iter()
            .position(|value| value == "--paired-failure-record-digest")
            .unwrap()
            + 1;
        malformed[index] = invalid.into();
        assert!(parse(malformed).is_err());
        fixture.assert_retained();
    }
    let mut duplicate = original.clone();
    duplicate.extend([
        "--paired-correction-record-digest".into(),
        "34".repeat(32).into(),
    ]);
    assert!(parse(duplicate).is_err());
    let mut desktop = fixture.arguments();
    desktop.extend(
        original
            .chunks_exact(2)
            .filter(|pair| {
                matches!(
                    pair[0].to_str(),
                    Some(
                        "--root-paired-training-handoff-fd"
                            | "--paired-failure-record-digest"
                            | "--paired-correction-record-digest"
                    )
                )
            })
            .flatten()
            .cloned(),
    );
    assert!(parse(desktop).is_err());
    fixture.assert_retained();
    // SAFETY: all rejected parses precede adoption of these retained rights.
    assert!(unsafe { libc::fcntl(ui.as_raw_fd(), libc::F_GETFD) } >= 0);
    assert!(paired.local_addr()?.is_unnamed());
    Ok(())
}

#[test]
fn paired_handoff_aliases_refuse_before_any_original_descriptor_moves() -> anyhow::Result<()> {
    let fixture = DesktopDescriptors::new()?;
    let ui = UnixListener::bind(fixture._directory.path().join("notes-ui.sock"))?;
    let (paired, _root) = UnixDatagram::pair()?;
    for descriptor in fixture
        .descriptors
        .iter()
        .map(AsRawFd::as_raw_fd)
        .chain([ui.as_raw_fd()])
    {
        let mut selected = arguments(&fixture, &ui, &paired);
        let index = selected
            .iter()
            .position(|value| value == "--root-paired-training-handoff-fd")
            .unwrap()
            + 1;
        selected[index] = descriptor.to_string().into();
        assert!(parse(selected).is_err());
        fixture.assert_retained();
    }
    let mut learning_alias = arguments(&fixture, &ui, &paired);
    learning_alias.extend([
        "--root-learning-handoff-fd".into(),
        paired.as_raw_fd().to_string().into(),
    ]);
    assert!(parse(learning_alias).is_err());
    fixture.assert_retained();
    assert!(paired.local_addr()?.is_unnamed());
    Ok(())
}

#[test]
fn paired_notes_input_transfers_one_distinct_socket_and_independent_pins() -> anyhow::Result<()> {
    let mut fixture = DesktopDescriptors::new()?;
    let ui = UnixListener::bind(fixture._directory.path().join("notes-ui.sock"))?;
    let (paired, _root) = UnixDatagram::pair()?;
    let expected = paired.as_raw_fd();
    let selected = arguments(&fixture, &ui, &paired);
    for descriptor in fixture.descriptors.drain(..) {
        let _ = descriptor.into_raw_fd();
    }
    let _ = ui.into_raw_fd();
    let _ = paired.into_raw_fd();
    let (inputs, ordinary) = parse(selected)?;
    let inputs = inputs.ok_or_else(|| anyhow::anyhow!("paired Notes profile missing"))?;
    assert!(matches!(inputs.primary, PrimaryInputs::Notes));
    assert!(
        inputs.notes.is_some() && inputs.notes_ui.is_some() && inputs.learning_handoff.is_none()
    );
    assert!(ordinary.is_empty());
    let paired = inputs
        .paired_training
        .ok_or_else(|| anyhow::anyhow!("paired owner missing"))?;
    assert_eq!(paired.handoff.as_raw_fd(), expected);
    assert_eq!(
        paired.records,
        crate::PairedRecordPinsV1 {
            failure_record_digest: "12".repeat(32).parse()?,
            correction_record_digest: "34".repeat(32).parse()?,
        }
    );
    // SAFETY: the parser now owns the one retained descriptor.
    assert_ne!(
        unsafe { libc::fcntl(paired.handoff.as_raw_fd(), libc::F_GETFD) } & libc::FD_CLOEXEC,
        0
    );
    Ok(())
}
