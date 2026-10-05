use super::*;

#[test]
fn portable_fixture_keeps_reader_error_without_fallback() {
    let source = CurrentArtifactRegistrySourceV1::fixture(|_| Err("withdrawn".to_string()));
    assert!(matches!(source.read_at(/*now*/ 7), Err(error) if error == "withdrawn"));
}

#[cfg(not(target_os = "linux"))]
#[test]
fn protected_owner_request_is_explicitly_unsupported() -> Result<(), Box<dyn std::error::Error>> {
    use codex_hepta_agent_components::types::Digest32;
    use codex_hepta_agent_components::types::Generation;
    use codex_hepta_agent_components::types::StableId;
    let root = tempfile::tempdir()?;
    let owner_path = root.path().join("absent-owner");
    let trust = ArtifactOwnerTrustV1 {
        registry_id: StableId::new("platform-test")?,
        withdrawal_scope_digest: Digest32::of_bytes(b"platform-test"),
        minimum_registry_generation: Generation::new(1)?,
        genesis_predecessor_head_digest: Digest32::of_bytes(b"genesis"),
        minimum_authority_epoch: 1,
        writer_signers: vec![],
        head_signers: vec![],
    };
    assert!(matches!(
        CurrentArtifactRegistrySourceV1::open(owner_path.clone(), trust, DatasetWithdrawalRegistry::new()),
        Err(error) if error == "protected artifact CURRENT owner requires Linux"
    ));
    assert!(!owner_path.exists());
    Ok(())
}
