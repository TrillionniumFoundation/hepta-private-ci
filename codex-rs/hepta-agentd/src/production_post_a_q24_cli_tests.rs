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
fn post_a_q24_cli_requires_all_original_purposes_before_descriptor_take() -> Result<(), AgentdError>
{
    let ordinary = ordinary();
    let full = [Some(31), Some(32), Some(33), Some(34), Some(37)];
    validate(Profile::PostAQ24, &ordinary, Some(36), &full, &[])?;
    assert!(
        validate(
            Profile::PostAQ24,
            &ordinary,
            /*deployment*/ None,
            &full,
            &[]
        )
        .is_err()
    );
    for index in 0..full.len() {
        let mut missing = full;
        missing[index] = None;
        assert!(validate(Profile::PostAQ24, &ordinary, Some(36), &missing, &[]).is_err());
    }
    assert!(validate(Profile::PostAQ24, &ordinary, Some(36), &full, &[Some(35)]).is_err());
    for profile in [
        Profile::InitialQ24,
        Profile::Android,
        Profile::Notes,
        Profile::Desktop,
    ] {
        assert!(validate(profile, &ordinary, Some(36), &full, &[]).is_err());
    }
    Ok(())
}

#[test]
fn post_a_q24_cli_rejects_missing_replay_and_competing_execution_inputs() {
    let full = ordinary();
    let handoffs = [Some(31), Some(32), Some(33), Some(34), Some(37)];
    for start in [0, 2, 4] {
        let mut missing = full.clone();
        missing.drain(start..start + 2);
        assert!(validate(Profile::PostAQ24, &missing, Some(36), &handoffs, &[]).is_err());
    }
    let mut duplicate = full.clone();
    duplicate.extend_from_slice(&full[..2]);
    assert!(validate(Profile::PostAQ24, &duplicate, Some(36), &handoffs, &[]).is_err());
    for flag in [
        "--plasticity-bootstrap-descriptor",
        "--neuron-generation-bootstrap-descriptor",
        "--intelligence-authority-file",
    ] {
        let mut competing = full.clone();
        competing.extend([OsString::from(flag), OsString::from("/other")]);
        assert!(validate(Profile::PostAQ24, &competing, Some(36), &handoffs, &[]).is_err());
    }
}
