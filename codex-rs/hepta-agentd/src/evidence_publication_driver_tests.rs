use super::*;
use codex_hepta_evidence::EvidencePublicationBatchStateV1;
use codex_hepta_evidence::EvidencePublicationBatchV1;
use codex_hepta_evidence::EvidenceRecoveryFrontierSignatureV2;
use codex_hepta_evidence::EvidenceRecoverySnapshotV1;

fn continuation() -> (EvidencePublicationBatchV1, EvidenceRecoveryFrontierV2, EvidenceRecoveryFrontierV2) {
    let snapshot = EvidenceRecoverySnapshotV1 {
        schema_version: 2,
        database_lineage: codex_hepta_evidence::EVIDENCE_DATABASE_LINEAGE.to_string(),
        migration_set_sha256: Sha256Digest::for_bytes(b"migration"),
        qualification_max_seq: 1,
        qualification_frontier_sha256: Sha256Digest::for_bytes(b"evidence"),
        authbus_replay_frontier_sha256: Sha256Digest::for_bytes(b"replay"),
    };
    let predecessor = EvidenceRecoveryFrontierV2 {
        schema_version: 2,
        store_id: "store:publisher-test".to_string(),
        frontier_generation: 1,
        ledger_root_sha256: evidence_recovery_ledger_root_v2(&snapshot),
        snapshot: snapshot.clone(),
        issuer_trust_registry_sha256: Sha256Digest::for_bytes(b"issuer"),
        frontier_signer_registry_sha256: Sha256Digest::for_bytes(b"signers"),
        backend_identity_sha256: Sha256Digest::for_bytes(b"backend"),
        build_artifact_sha256: Sha256Digest::for_bytes(b"build"),
        qualification_receipt_sha256: Sha256Digest::for_bytes(b"checks"),
        backup_publication_sha256: Sha256Digest::for_bytes(b"backup"),
        source_commit: "a".repeat(40),
        source_tree: "b".repeat(40),
        created_at_unix_ms: 1_900_000_000_000,
        signer_policy_generation: 1,
        signatures: vec![EvidenceRecoveryFrontierSignatureV2 {
            signer_principal_id: "signer:fixture".to_string(),
            signer_key_epoch: 1,
            signature_hex: "11".repeat(64),
        }],
    };
    let proposed = EvidenceRecoveryFrontierV2 {
        frontier_generation: 2,
        created_at_unix_ms: predecessor.created_at_unix_ms + 1,
        ..predecessor.clone()
    };
    let batch = EvidencePublicationBatchV1 {
        batch_id: "batch:publisher-test".to_string(),
        store_id: predecessor.store_id.clone(),
        prepared_owner_id: "owner:publisher-test".to_string(),
        prepared_owner_generation: 1,
        state: EvidencePublicationBatchStateV1::Prepared,
        first_intent_seq: 1,
        last_intent_seq: 1,
        intent_count: 1,
        snapshot,
        snapshot_sha256: Sha256Digest::for_bytes(b"fixture-not-admission"),
        expected_frontier_generation: Some(1),
        expected_frontier_sha256: Some(evidence_recovery_frontier_v2_sha256(&predecessor).unwrap()),
        expected_backend_identity_sha256: Some(predecessor.backend_identity_sha256.clone()),
        proposed_frontier_generation: 2,
        proposed_frontier_sha256: None,
        backend_identity_sha256: None,
        durable_audit_sequence: None,
        created_at_unix_ms: predecessor.created_at_unix_ms,
        updated_at_unix_ms: predecessor.created_at_unix_ms,
    };
    (batch, predecessor, proposed)
}

#[test]
fn publication_domain_accepts_only_the_exact_prepared_continuation() {
    let (batch, predecessor, proposed) = continuation();
    validate_publication_continuation(&batch, &predecessor, &proposed).unwrap();
    let mutations: [fn(&mut EvidenceRecoveryFrontierV2); 10] = [
        |value| value.store_id = "store:other".to_string(),
        |value| value.frontier_generation += 1,
        |value| value.snapshot.qualification_max_seq += 1,
        |value| value.source_commit = "c".repeat(40),
        |value| value.source_tree = "d".repeat(40),
        |value| value.issuer_trust_registry_sha256 = Sha256Digest::for_bytes(b"other"),
        |value| value.frontier_signer_registry_sha256 = Sha256Digest::for_bytes(b"other"),
        |value| value.build_artifact_sha256 = Sha256Digest::for_bytes(b"other"),
        |value| value.qualification_receipt_sha256 = Sha256Digest::for_bytes(b"other"),
        |value| value.backend_identity_sha256 = Sha256Digest::for_bytes(b"other"),
    ];
    for mutate in mutations {
        let mut altered = proposed.clone();
        mutate(&mut altered);
        assert!(validate_publication_continuation(&batch, &predecessor, &altered).is_err());
    }
}

#[test]
fn publication_predecessor_cannot_be_replaced_at_the_same_generation() {
    let (mut batch, predecessor, proposed) = continuation();
    batch.expected_frontier_sha256 = Some(Sha256Digest::for_bytes(b"another predecessor"));
    assert!(validate_publication_continuation(&batch, &predecessor, &proposed).is_err());
}

#[test]
fn owner_publication_request_rejects_unknown_and_duplicate_fields() {
    let valid = br#"{"schemaVersion":1,"request":{"action":"prepare","maximum_intents":8}}"#;
    assert!(serde_json::from_slice::<EvidencePublicationRequestV1>(valid).is_ok());
    for invalid in [
        r#"{"schemaVersion":1,"schemaVersion":1,"request":{"action":"prepare","maximum_intents":8}}"#,
        r#"{"schemaVersion":1,"request":{"action":"prepare","maximum_intents":8,"activation":true}}"#,
        r#"{"schemaVersion":1,"request":{"action":"publish","batch_id":"batch:x"}}"#,
    ] {
        assert!(serde_json::from_str::<EvidencePublicationRequestV1>(invalid).is_err());
    }
}
