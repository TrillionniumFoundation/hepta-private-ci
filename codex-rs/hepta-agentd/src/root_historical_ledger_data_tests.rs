//! Untrusted wire-data tests only. These values are never a Root observation,
//! physical A execution, completed handoff or historical recipient capability.

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::ResourceBudget;
use pretty_assertions::assert_eq;

use super::*;

pub(crate) fn fixture_data() -> anyhow::Result<RootHistoricalLedgerReadDataV1> {
    let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let registered = HostAuthorityRegisteredIdentity {
        agent_id: agent.clone(),
        spawn_generation: 1,
        // Validation must remain pure data; these paths need not exist.
        fleet_root: "/unopened-ledger-data/fleet".into(),
        workspace: "/unopened-ledger-data/workspace".into(),
        resources: ResourceBudget::local_default(),
    };
    let target: CellGenerationOwnerBindingV1 = serde_json::from_value(serde_json::json!({
        "scope": {"agent_id": agent.as_str(), "cell_id": "cell", "run_id": "A",
                  "principal_digest": vec![1; 32]},
        "manifest_digest": vec![2; 32], "source_frontier": vec![3; 32],
        "task_digest": vec![4; 32], "initial_snapshot_digest": vec![5; 32],
        "config_digest": vec![6; 32], "generation": 1, "writer_epoch": 1
    }))?;
    let digest = |label: &str| Digest32::of_bytes(label.as_bytes()).to_string();
    let pin = |inode| RootHistoricalLedgerFilePinV1 {
        device: 1,
        inode,
        uid: 60001,
        gid: 60001,
        mode: 0o100600,
    };
    let trust = LearningTrustPinV1 {
        mapping: digest("mapping"),
        target: Digest32::from_array(target.digest()?).to_string(),
        task: Digest32::from_array(target.task_digest()).to_string(),
        source_metadata: digest("source"),
        root: digest("root"),
        distribution: digest("distribution"),
        trust: digest("trust"),
        learning_scope: digest("scope"),
        objective: digest("objective"),
        roles: digest("roles"),
    };
    Ok(RootHistoricalLedgerReadDataV1 {
        schema: 1,
        purpose: LEDGER_READ_DATA_PURPOSE.into(),
        initial_profile: digest("initial"),
        identity: digest("identity"),
        registered_identity: serde_json::to_string(&registered)?,
        writer: digest("writer"),
        publisher_epoch: 1,
        publisher: CognitiveCheckpointPeerLifetime {
            uid: 60001,
            pid: 123,
            boot_id: "component-boot".into(),
            process_start_ticks: 1,
        },
        peer_gid: 60001,
        target,
        files: [pin(1), pin(2), pin(3), pin(4)],
        metadata: digest("metadata"),
        registered_at: 1,
        trust,
        source: RootHistoricalLedgerSourceDataV1 {
            files: [pin(5), pin(6)],
            target_files: digest("target-files"),
            configuration: digest("configuration"),
            witness_context: digest("witness-context"),
            sequence: 7,
            checkpoint: digest("source-checkpoint"),
            publication: digest("publication"),
            completed_task: digest("completed-task"),
            fence: digest("fence"),
        },
        cut: RootHistoricalLedgerCutDataV1 {
            source_pin: digest("source-pin"),
            source_publication: digest("publication"),
            cell_decision: digest("cell"),
            ledger_binding: digest("binding"),
            ledger_sequence: 2,
            ledger_chain: digest("outcome"),
            ledger_length: 4096,
            ledger_image: digest("ledger"),
            witness_length: 248,
            witness_image: digest("witness"),
            signature_binding: digest("signatures"),
            signature_sequence: 5,
            signature_checkpoint: digest("signature-checkpoint"),
            signature_length: 8192,
            signature_image: digest("signature-image"),
            signature_witness_length: 1024,
            signature_witness_image: digest("signature-witness"),
            decision_chain: digest("decision"),
            outcome_chain: digest("outcome"),
        },
    })
}

#[test]
fn historical_ledger_data_roundtrip_has_no_filesystem_or_authority_side_effects()
-> anyhow::Result<()> {
    let original = fixture_data()?;
    original.validate_data()?;
    let bytes = serde_json::to_vec(&original)?;
    let decoded: RootHistoricalLedgerReadDataV1 = serde_json::from_slice(&bytes)?;
    assert_eq!(decoded, original);
    assert_eq!(decoded.data_cut_digest()?, original.data_cut_digest()?);
    assert_eq!(decoded.ledger_cut()?, original.ledger_cut()?);
    assert!(bytes.len() < 12 * 1024);
    Ok(())
}

#[test]
fn historical_ledger_data_rejects_extra_authority_claims_and_missing_cuts() -> anyhow::Result<()> {
    let value = serde_json::to_value(fixture_data()?)?;
    for key in [
        "grant",
        "retired",
        "completed",
        "root_key",
        "path",
        "initialize",
    ] {
        let mut changed = value.clone();
        changed[key] = serde_json::json!(true);
        assert!(serde_json::from_value::<RootHistoricalLedgerReadDataV1>(changed).is_err());
    }
    for key in ["source", "cut", "trust", "publisher", "registered_identity"] {
        let mut changed = value.clone();
        changed
            .as_object_mut()
            .ok_or_else(|| anyhow::anyhow!("object"))?
            .remove(key);
        assert!(serde_json::from_value::<RootHistoricalLedgerReadDataV1>(changed).is_err());
    }
    let mut changed = value;
    changed["source"]["retired"] = serde_json::json!(true);
    assert!(serde_json::from_value::<RootHistoricalLedgerReadDataV1>(changed).is_err());
    Ok(())
}

#[test]
fn historical_ledger_data_rejects_aliases_wrong_owner_and_nonprivate_files() -> anyhow::Result<()> {
    let original = fixture_data()?;
    let mut alias = original.clone();
    alias.source.files[0] = alias.files[2].clone();
    assert!(alias.validate_data().is_err());
    let mut owner = original.clone();
    owner.files[0].uid += 1;
    assert!(owner.validate_data().is_err());
    let mut access = original.clone();
    access.source.files[0].mode |= 0o040;
    assert!(access.validate_data().is_err());
    let mut kind = original;
    kind.files[0].mode = 0o040600;
    assert!(kind.validate_data().is_err());
    Ok(())
}

#[test]
fn historical_ledger_data_rejects_partial_frontiers_and_unjoined_history() -> anyhow::Result<()> {
    let original = fixture_data()?;
    let mut ledger = original.clone();
    ledger.cut.ledger_sequence = 1;
    assert!(ledger.validate_data().is_err());
    let mut signature = original.clone();
    signature.cut.signature_sequence = 4;
    assert!(signature.validate_data().is_err());
    let mut witness = original.clone();
    witness.cut.witness_length -= 1;
    assert!(witness.validate_data().is_err());
    let mut chain = original.clone();
    chain.cut.outcome_chain = chain.cut.decision_chain.clone();
    assert!(chain.validate_data().is_err());
    let mut source = original;
    source.source.publication = Digest32::of_bytes(b"different").to_string();
    assert!(source.validate_data().is_err());
    Ok(())
}

#[test]
fn historical_ledger_data_keeps_canonical_target_identity_and_commitments() -> anyhow::Result<()> {
    let original = fixture_data()?;
    let mut target = original.clone();
    target.trust.target = Digest32::of_bytes(b"other-target").to_string();
    assert!(target.validate_data().is_err());
    let mut registration = original.clone();
    registration.registered_identity.push(' ');
    assert!(registration.validate_data().is_err());
    let mut malformed = original.clone();
    malformed.cut.ledger_image = "not-a-digest".into();
    assert!(malformed.validate_data().is_err());
    let mut absent = original;
    absent.cut.signature_image = Digest32::ZERO.to_string();
    assert!(absent.validate_data().is_err());
    Ok(())
}

#[test]
fn historical_ledger_data_commitment_covers_source_metadata_and_file_identity() -> anyhow::Result<()>
{
    let original = fixture_data()?;
    let expected = original.data_cut_digest()?;
    let mut metadata = original.clone();
    metadata.metadata = Digest32::of_bytes(b"new-metadata").to_string();
    assert_ne!(metadata.data_cut_digest()?, expected);
    let mut file = original.clone();
    file.files[0].inode += 100;
    assert_ne!(file.data_cut_digest()?, expected);
    let mut source = original.clone();
    source.source.checkpoint = Digest32::of_bytes(b"new-source").to_string();
    assert_ne!(source.data_cut_digest()?, expected);
    let mut registered: HostAuthorityRegisteredIdentity =
        serde_json::from_str(&original.registered_identity)?;
    registered.workspace = format!("/{}", "x".repeat(4096)).into();
    let mut oversized = original;
    oversized.registered_identity = serde_json::to_string(&registered)?;
    assert!(oversized.validate_data().is_err());
    Ok(())
}
