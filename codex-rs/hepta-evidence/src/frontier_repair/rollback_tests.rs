#![expect(clippy::expect_used, reason = "test fixtures use explicit failure messages")]

use std::fmt::Write as _;

use codex_hepta_contracts::Sha256Digest;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use tempfile::TempDir;

use crate::EVIDENCE_DATABASE_LINEAGE;
use crate::EVIDENCE_RECOVERY_FRONTIER_V2_SCHEMA_VERSION;
use crate::EvidenceFrontierRepairStateV1;
use crate::EvidenceRecoveryFrontierSignatureV2;
use crate::EvidenceRecoveryFrontierV2;
use crate::EvidenceRecoverySnapshotV1;
use crate::FRONTIER_REPAIR_AUTHORIZATION_SCHEMA_VERSION;
use crate::FRONTIER_REPAIR_AUTHORITY_SCHEMA_VERSION;
use crate::FrontierRepairAlgorithmV1;
use crate::FrontierRepairAuthorityV1;
use crate::FrontierRepairAuthorizationV1;
use crate::FrontierRepairReasonV1;
use crate::HeptaEvidenceStore;
use crate::evidence_recovery_frontier_v2_sha256;
use crate::evidence_recovery_ledger_root_v2;
use crate::frontier_repair_authorization_signing_bytes;

fn digest(label: &str) -> Sha256Digest {
    Sha256Digest::for_bytes(label.as_bytes())
}

fn sqlite_config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp path"),
    )
}

fn frontier(generation: u64) -> EvidenceRecoveryFrontierV2 {
    let snapshot = EvidenceRecoverySnapshotV1 {
        schema_version: 2,
        database_lineage: EVIDENCE_DATABASE_LINEAGE.to_string(),
        migration_set_sha256: digest("migrations"),
        qualification_max_seq: generation,
        qualification_frontier_sha256: digest(&format!("qualification:{generation}")),
        authbus_replay_frontier_sha256: digest(&format!("replay:{generation}")),
    };
    EvidenceRecoveryFrontierV2 {
        schema_version: EVIDENCE_RECOVERY_FRONTIER_V2_SCHEMA_VERSION,
        store_id: "store:kernel-evidence".to_string(),
        frontier_generation: generation,
        ledger_root_sha256: evidence_recovery_ledger_root_v2(&snapshot),
        snapshot,
        issuer_trust_registry_sha256: digest("issuer-registry"),
        frontier_signer_registry_sha256: digest("signer-registry"),
        backend_identity_sha256: digest("backend"),
        build_artifact_sha256: digest("artifact"),
        qualification_receipt_sha256: digest("qualification-receipts"),
        backup_publication_sha256: digest(&format!("backup:{generation}")),
        source_commit: "a".repeat(40),
        source_tree: "b".repeat(40),
        created_at_unix_ms: 1_900_000_000_000 + generation,
        signer_policy_generation: 3,
        signatures: vec![EvidenceRecoveryFrontierSignatureV2 {
            signer_principal_id: "issuer:recovery".to_string(),
            signer_key_epoch: 1,
            signature_hex: "11".repeat(64),
        }],
    }
}

fn repair_fixture(
    now: u64,
) -> (
    EvidenceRecoveryFrontierV2,
    EvidenceRecoveryFrontierV2,
    FrontierRepairAuthorizationV1,
    FrontierRepairAuthorityV1,
) {
    let current = frontier(7);
    let mut target = current.clone();
    target.frontier_generation += 1;
    target.snapshot.qualification_max_seq += 1;
    target.snapshot.qualification_frontier_sha256 = digest("qualification:8");
    target.snapshot.authbus_replay_frontier_sha256 = digest("replay:8");
    target.ledger_root_sha256 = evidence_recovery_ledger_root_v2(&target.snapshot);
    target.backup_publication_sha256 = digest("backup:8");
    target.source_commit = "c".repeat(40);
    target.created_at_unix_ms += 1;

    let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
    let authority = FrontierRepairAuthorityV1 {
        schema_version: FRONTIER_REPAIR_AUTHORITY_SCHEMA_VERSION,
        authority_key_id: "key:frontier-repair:primary".to_string(),
        authority_key_epoch: 4,
        trust_root_generation: 9,
        algorithm: FrontierRepairAlgorithmV1::Ed25519,
        public_key_hex: encode_hex(signing_key.verifying_key().as_bytes()),
        not_before_unix_ms: now - 1_000,
        not_after_unix_ms: now + 100_000,
        revoked: false,
    };
    let mut authorization = FrontierRepairAuthorizationV1 {
        schema_version: FRONTIER_REPAIR_AUTHORIZATION_SCHEMA_VERSION,
        store_id: current.store_id.clone(),
        current_frontier_sha256: evidence_recovery_frontier_v2_sha256(&current)
            .expect("current frontier digest"),
        target_frontier_sha256: evidence_recovery_frontier_v2_sha256(&target)
            .expect("target frontier digest"),
        current_generation: current.frontier_generation,
        target_generation: target.frontier_generation,
        reason_code: FrontierRepairReasonV1::OperatorDisasterRecovery,
        operator_principal_id: "operator:recovery:primary".to_string(),
        issued_at_unix_ms: now - 100,
        expires_at_unix_ms: now + 10_000,
        nonce_hex: "ab".repeat(32),
        authority_key_id: authority.authority_key_id.clone(),
        authority_key_epoch: authority.authority_key_epoch,
        authority_algorithm: authority.algorithm,
        trust_root_generation: authority.trust_root_generation,
        authority_signature_hex: String::new(),
    };
    let signing_bytes = frontier_repair_authorization_signing_bytes(&authorization)
        .expect("repair authorization signing bytes");
    authorization.authority_signature_hex =
        encode_hex(&signing_key.sign(&signing_bytes).to_bytes());
    (current, target, authorization, authority)
}

#[tokio::test]
async fn failed_event_insert_rolls_back_repair_row_and_nonce() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence store");
    store
        .bind_recovery_store_id("store:kernel-evidence")
        .await
        .expect("bind recovery identity");
    let now = 1_900_000_010_000;
    let (current, target, authorization, authority) = repair_fixture(now);

    sqlx::query(
        "CREATE TRIGGER test_fail_frontier_repair_event_insert \
         BEFORE INSERT ON evidence_frontier_repair_events \
         BEGIN SELECT RAISE(ABORT, 'injected repair event failure'); END",
    )
    .execute(&store.pool)
    .await
    .expect("install repair event failure trigger");

    store
        .prepare_frontier_repair(&authorization, &authority, &current, &target, now)
        .await
        .expect_err("event failure must abort the complete repair transaction");

    let repair_rows: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM evidence_frontier_repairs")
        .fetch_one(&store.pool)
        .await
        .expect("count repair rows after rollback");
    let event_rows: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM evidence_frontier_repair_events")
            .fetch_one(&store.pool)
            .await
            .expect("count repair event rows after rollback");
    assert_eq!(repair_rows, 0);
    assert_eq!(event_rows, 0);

    sqlx::query("DROP TRIGGER test_fail_frontier_repair_event_insert")
        .execute(&store.pool)
        .await
        .expect("remove repair event failure trigger");

    let prepared = store
        .prepare_frontier_repair(&authorization, &authority, &current, &target, now + 1)
        .await
        .expect("rolled-back nonce remains available for the exact repair");
    assert_eq!(prepared.state, EvidenceFrontierRepairStateV1::Prepared);
}

fn encode_hex(bytes: &[u8]) -> String {
    let mut encoded = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        write!(&mut encoded, "{byte:02x}").expect("writing to a string cannot fail");
    }
    encoded
}
