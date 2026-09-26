use hepta_native::update_handoff::UpdateHandoff;
fn args() -> Vec<String> {
    [
        "--endpoint-manifest",
        "/manifest",
        "--trusted-keys",
        "/keys",
        "--state-dir",
        "/state",
    ]
    .map(String::from)
    .to_vec()
}
#[test]
fn restart_binding_rejects_smoke_profiles_and_detects_argument_changes() {
    let original = args();
    let handoff = UpdateHandoff::from_invocation("1".repeat(64), &original).unwrap();
    let mut changed = original.clone();
    changed[1] = "/other-manifest".into();
    assert_ne!(
        handoff,
        UpdateHandoff::from_invocation("1".repeat(64), &changed).unwrap()
    );
    for flag in ["--self-test", "--qualification-e2e", "--update-handoff"] {
        let mut rejected = original.clone();
        rejected.push(flag.into());
        assert!(UpdateHandoff::from_invocation("1".repeat(64), &rejected).is_err());
    }
    assert!(UpdateHandoff::from_invocation("0".repeat(64), &original).is_err());
    assert!(UpdateHandoff::from_invocation("1".repeat(64), &[]).is_err());
}
