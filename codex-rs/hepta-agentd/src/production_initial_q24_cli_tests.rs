use super::*;

fn ordinary() -> Vec<OsString> {
    [
        "--authbus-trust-file",
        "/original/authbus",
        "--authbus-checkpoint-file",
        "/original/replay",
        "--objective-profile-file",
        "/original/objective",
    ]
    .into_iter()
    .map(OsString::from)
    .collect()
}

#[test]
fn initial_q24_cli_requires_original_pairing_before_descriptor_take() -> Result<(), AgentdError> {
    let ordinary = ordinary();
    validate(Profile::InitialQ24, &ordinary, Some(31), Some(32), &[])?;
    assert!(
        validate(
            Profile::InitialQ24,
            &ordinary,
            /*deployment*/ None,
            Some(32),
            &[]
        )
        .is_err()
    );
    assert!(
        validate(
            Profile::InitialQ24,
            &ordinary,
            Some(31),
            /*initial_handoff*/ None,
            &[]
        )
        .is_err()
    );
    assert!(
        validate(
            Profile::InitialQ24,
            &ordinary,
            Some(31),
            Some(32),
            &[Some(33)]
        )
        .is_err()
    );
    for profile in [Profile::Android, Profile::Notes, Profile::Desktop] {
        assert!(validate(profile, &ordinary, Some(31), Some(32), &[]).is_err());
    }
    Ok(())
}

#[test]
fn initial_q24_cli_rejects_missing_duplicate_and_competing_authority_inputs() {
    let full = ordinary();
    for start in [0, 2, 4] {
        let mut missing = full.clone();
        missing.drain(start..start + 2);
        assert!(validate(Profile::InitialQ24, &missing, Some(31), Some(32), &[]).is_err());
    }
    let mut duplicate = full.clone();
    duplicate.extend_from_slice(&full[..2]);
    assert!(validate(Profile::InitialQ24, &duplicate, Some(31), Some(32), &[]).is_err());
    for flag in [
        "--plasticity-bootstrap-descriptor",
        "--neuron-generation-bootstrap-descriptor",
        "--intelligence-authority-file",
    ] {
        let mut competing = full.clone();
        competing.extend([OsString::from(flag), OsString::from("/other")]);
        assert!(validate(Profile::InitialQ24, &competing, Some(31), Some(32), &[]).is_err());
    }
}
