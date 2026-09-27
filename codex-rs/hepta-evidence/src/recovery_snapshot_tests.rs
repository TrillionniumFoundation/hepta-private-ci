use codex_hepta_contracts::Sha256Digest;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use tempfile::TempDir;

use super::snapshot;
use crate::HeptaEvidenceStore;

async fn store(temp: &TempDir) -> HeptaEvidenceStore {
    let sqlite = SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp path"),
    );
    let store = HeptaEvidenceStore::open(&sqlite).await.expect("open evidence");
    store.bind_recovery_store_id("store:snapshot-test").await.expect("enroll");
    store
}

async fn append_replay(store: &HeptaEvidenceStore) {
    sqlx::query(
        "INSERT INTO authbus_replay_sequences
         (issuer_id, key_epoch, subject_id, scope_digest, sequence, envelope_digest)
         VALUES ('issuer:test', ?, 'subject:test', ?, ?, ?)",
    ).bind(1_u64.to_be_bytes().to_vec()).bind(vec![1_u8; 32])
        .bind(1_u64.to_be_bytes().to_vec()).bind(vec![2_u8; 32])
        .execute(&store.pool).await.expect("append replay");
}

#[tokio::test]
async fn recovery_snapshot_retains_one_wal_read_epoch() {
    let temp = TempDir::new().expect("temp");
    let store = store(&temp).await;
    let before = store.authenticated_recovery_snapshot().await.expect("before");
    let mut reader = store.pool.begin().await.expect("read transaction");
    let _: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM _sqlx_migrations")
        .fetch_one(&mut *reader).await.expect("establish WAL snapshot");
    append_replay(&store).await;
    let held = snapshot::collect_in_transaction(&mut reader, snapshot::Domain::AuthenticatedAdmission)
        .await.expect("collect held snapshot");
    assert_eq!(held, before);
    reader.commit().await.expect("release reader");
    let after = store.authenticated_recovery_snapshot().await.expect("after");
    assert_ne!(after.authbus_replay_frontier_sha256, before.authbus_replay_frontier_sha256);
    store.close().await;
}

#[tokio::test]
async fn authenticated_snapshot_requires_enrollment_and_binds_store_identity() {
    let temp = TempDir::new().expect("temp");
    let sqlite = SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp path"),
    );
    let first = HeptaEvidenceStore::open(&sqlite).await.expect("open");
    assert!(first.authenticated_recovery_snapshot().await.is_err());
    first.bind_recovery_store_id("store:first").await.expect("enroll first");
    let first_snapshot = first.authenticated_recovery_snapshot().await.expect("first snapshot");
    let legacy = first.recovery_snapshot().await.expect("legacy");
    assert_eq!(legacy.schema_version, 1);
    assert_eq!(first_snapshot.schema_version, 2);
    assert_ne!(first_snapshot.qualification_frontier_sha256, legacy.qualification_frontier_sha256);
    let second_temp = TempDir::new().expect("second temp");
    let second = store(&second_temp).await;
    let second_snapshot = second.authenticated_recovery_snapshot().await.expect("second snapshot");
    assert_ne!(first_snapshot.qualification_frontier_sha256, second_snapshot.qualification_frontier_sha256);
    first.close().await;
    second.close().await;
}

#[tokio::test]
async fn authenticated_commitment_covers_admission_columns_omitted_by_legacy() {
    let temp = TempDir::new().expect("temp");
    let store = store(&temp).await;
    let envelope = crate::QualificationEvidenceEnvelopeV1 {
        schema_version: 1,
        evidence_id: crate::EvidenceId::parse("evidence:snapshot").expect("id"),
        candidate: crate::EvidenceCandidateV1 {
            candidate_id: "candidate:snapshot".into(), source_commit: "a".repeat(40), source_tree: "b".repeat(40),
        },
        claim_class: crate::EvidenceClaimClassV1::MandatoryTests,
        receipt_kind: crate::EvidenceReceiptKindV1::Evidence,
        issuer_role: crate::EvidenceIssuerRoleV1::Evaluator,
        payload: serde_json::json!({"passed": true}),
        predecessor_evidence_id: None, target_evidence_id: None,
        observed_unix_ms: 1, expires_unix_ms: None, asset_digests: Vec::new(),
    };
    let canonical = crate::qualification_envelope_bytes(&envelope).expect("envelope");
    let payload = crate::canonical::canonical_json(&envelope.payload).expect("payload");
    sqlx::query(
        "INSERT INTO qualification_evidence
         (evidence_id,schema_version,candidate_id,source_commit,source_tree,claim_class,receipt_kind,
          issuer_role,issuer_principal_id,issuer_key_epoch,issuer_signing_identity_sha256,
          auth_message_id,auth_sequence,auth_expires_at_ms,payload_sha256,envelope_sha256,
          observed_at_ms,asset_count,envelope_json,recorded_at_ms)
         VALUES (?,1,?,?,?,'mandatory_tests','evidence','evaluator','issuer:original',?,?,'message:test',?,?,?, ?,?,0,?,1)",
    ).bind(envelope.evidence_id.as_str()).bind(&envelope.candidate.candidate_id)
        .bind(&envelope.candidate.source_commit).bind(&envelope.candidate.source_tree)
        .bind(1_u64.to_be_bytes().to_vec()).bind(Sha256Digest::for_bytes(b"key").as_str())
        .bind(1_u64.to_be_bytes().to_vec()).bind(2_u64.to_be_bytes().to_vec())
        .bind(Sha256Digest::for_bytes(&payload).as_str()).bind(Sha256Digest::for_bytes(&canonical).as_str())
        .bind(1_u64.to_be_bytes().to_vec()).bind(String::from_utf8(canonical).expect("UTF-8"))
        .execute(&store.pool).await.expect("fixture row");
    let legacy = store.recovery_snapshot().await.expect("legacy before");
    let authenticated = store.authenticated_recovery_snapshot().await.expect("authenticated before");
    // Deliberate offline-tamper simulation, never a runtime authority path.
    sqlx::query("DROP TRIGGER qualification_evidence_no_update")
        .execute(&store.pool).await.expect("tamper fixture");
    for statement in [
        "UPDATE qualification_evidence SET issuer_principal_id = 'issuer:replacement'",
        "UPDATE qualification_evidence SET issuer_key_epoch = X'0000000000000002'",
        "UPDATE qualification_evidence SET issuer_signing_identity_sha256 = 'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc'",
        "UPDATE qualification_evidence SET auth_message_id = 'message:replacement'",
        "UPDATE qualification_evidence SET auth_sequence = X'0000000000000003'",
        "UPDATE qualification_evidence SET auth_expires_at_ms = X'0000000000000004'",
        "UPDATE qualification_evidence SET recorded_at_ms = 5",
    ] {
        let mut tamper = store.pool.begin().await.expect("tamper transaction");
        sqlx::query(statement).execute(&mut *tamper).await.expect("mutate one field");
        let changed = snapshot::collect_in_transaction(&mut tamper, snapshot::Domain::AuthenticatedAdmission)
            .await.expect("changed snapshot");
        assert_ne!(changed.qualification_frontier_sha256, authenticated.qualification_frontier_sha256, "{statement}");
        let unchanged = snapshot::collect_in_transaction(&mut tamper, snapshot::Domain::LegacyEnvelope)
            .await.expect("legacy snapshot");
        assert_eq!(unchanged, legacy);
        tamper.rollback().await.expect("isolate each mutation");
    }
    store.close().await;
}
