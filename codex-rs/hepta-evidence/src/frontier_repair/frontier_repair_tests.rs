#![expect(clippy::expect_used, reason = "test fixtures use explicit failure messages")]

use std::fmt::Write as _;

use codex_hepta_contracts::Sha256Digest;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use tempfile::TempDir;

use super::EvidenceFrontierRepairActionV1;
use super::EvidenceFrontierRepairStateV1;
use crate::EVIDENCE_DATABASE_LINEAGE;
use crate::EVIDENCE_RECOVERY_FRONTIER_V2_SCHEMA_VERSION;
use crate::EvidenceError;
use crate::EvidenceFrontierDurableAckV1;
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

fn sqlite_config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp path"),
    )
}

fn digest(label: &str) -> Sha256Digest {
    Sha256Digest::for_bytes(label.as_bytes())
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
    nonce_byte: u8,
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
        nonce_hex: format!("{nonce_byte:02x}").repeat(32),
        authority_key_id: authority.authority_key_id.clone(),
        authority_key_epoch: authority.authority_key_epoch,
        authority_algorithm: authority.algorithm,
        trust_root_generation: authority.trust_root_generation,
        authority_signature_hex: String::new(),
    };
    let bytes = frontier_repair_authorization_signing_bytes(&authorization)
        .expect("repair signing bytes");
    authorization.authority_signature_hex = encode_hex(&signing_key.sign(&bytes).to_bytes());
    (current, target, authorization, authority)
}

async fn opened_store(temp: &TempDir) -> HeptaEvidenceStore {
    let store = HeptaEvidenceStore::open(&sqlite_config(temp))
        .await
        .expect("open evidence store");
    store
        .bind_recovery_store_id("store:kernel-evidence")
        .await
        .expect("bind recovery identity");
    store
}

#[tokio::test]
async fn exact_repair_prepare_is_idempotent_and_survives_reopen() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = opened_store(&temp).await;
    let now = 1_900_000_010_000;
    let (current, target, authorization, authority) = repair_fixture(0xab, now);

    let first = store
        .prepare_frontier_repair(&authorization, &authority, &current, &target, now)
        .await
        .expect("prepare repair");
    let second = store
        .prepare_frontier_repair(&authorization, &authority, &current, &target, now)
        .await
        .expect("idempotent repair retry");
    assert_eq!(first, second);
    assert_eq!(first.state, EvidenceFrontierRepairStateV1::Prepared);
    assert_eq!(
        first.next_action(),
        EvidenceFrontierRepairActionV1::DispatchExactTransition
    );
    drop(store);

    let reopened = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("reopen verified repair ledger");
    assert_eq!(
        reopened
            .get_frontier_repair(&first.repair_id)
            .await
            .expect("load repair"),
        Some(first)
    );
}

#[tokio::test]
async fn reused_nonce_with_semantic_drift_conflicts() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp).await;
    let now = 1_900_000_010_000;
    let (current, target, authorization, authority) = repair_fixture(0xab, now);
    store
        .prepare_frontier_repair(&authorization, &authority, &current, &target, now)
        .await
        .expect("prepare repair");

    let (other_current, other_target, mut other_authorization, other_authority) =
        repair_fixture(0xab, now + 1);
    other_authorization.operator_principal_id = "operator:recovery:secondary".to_string();
    let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
    let bytes = frontier_repair_authorization_signing_bytes(&other_authorization)
        .expect("repair signing bytes");
    other_authorization.authority_signature_hex =
        encode_hex(&signing_key.sign(&bytes).to_bytes());
    let error = store
        .prepare_frontier_repair(
            &other_authorization,
            &other_authority,
            &other_current,
            &other_target,
            now + 1,
        )
        .await
        .expect_err("nonce semantic drift must conflict");
    assert!(matches!(error, EvidenceError::IdempotencyConflict { .. }));
}

#[tokio::test]
async fn dispatch_indeterminate_and_acknowledgement_are_exactly_fenced() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp).await;
    let now = 1_900_000_010_000;
    let (current, target, authorization, authority) = repair_fixture(0xab, now);
    let prepared = store
        .prepare_frontier_repair(&authorization, &authority, &current, &target, now)
        .await
        .expect("prepare repair");
    let dispatch = store
        .begin_frontier_repair_dispatch(
            &prepared.repair_id,
            "dispatch:repair:one",
            &target.backend_identity_sha256,
            now + 1,
        )
        .await
        .expect("fence dispatch");
    assert_eq!(dispatch.state, EvidenceFrontierRepairStateV1::Dispatching);
    assert_eq!(
        dispatch.next_action(),
        EvidenceFrontierRepairActionV1::ObserveExactOperation
    );
    let stale = store
        .mark_frontier_repair_indeterminate(
            &prepared.repair_id,
            "dispatch:repair:stale",
            now + 2,
        )
        .await
        .expect_err("stale dispatch token must fail");
    assert!(matches!(stale, EvidenceError::InvalidRecord(_)));
    let indeterminate = store
        .mark_frontier_repair_indeterminate(
            &prepared.repair_id,
            "dispatch:repair:one",
            now + 2,
        )
        .await
        .expect("mark indeterminate");
    assert_eq!(
        indeterminate.state,
        EvidenceFrontierRepairStateV1::Indeterminate
    );

    let acknowledgement = EvidenceFrontierDurableAckV1 {
        backend_id: "backend:repair".to_string(),
        backend_identity_sha256: target.backend_identity_sha256.clone(),
        store_id: target.store_id.clone(),
        frontier_generation: target.frontier_generation,
        frontier_sha256: authorization.target_frontier_sha256.clone(),
        audit_sequence: 41,
    };
    let acknowledged = store
        .acknowledge_frontier_repair(
            &prepared.repair_id,
            "dispatch:repair:one",
            &acknowledgement,
            now + 3,
        )
        .await
        .expect("acknowledge exact target");
    assert_eq!(
        acknowledged.state,
        EvidenceFrontierRepairStateV1::Acknowledged
    );
    assert_eq!(
        acknowledged.next_action(),
        EvidenceFrontierRepairActionV1::Complete
    );
    assert_eq!(acknowledged.durable_audit_sequence, Some(41));
}

#[tokio::test]
async fn wrong_target_acknowledgement_cannot_complete_repair() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp).await;
    let now = 1_900_000_010_000;
    let (current, target, authorization, authority) = repair_fixture(0xab, now);
    let prepared = store
        .prepare_frontier_repair(&authorization, &authority, &current, &target, now)
        .await
        .expect("prepare repair");
    store
        .begin_frontier_repair_dispatch(
            &prepared.repair_id,
            "dispatch:repair:one",
            &target.backend_identity_sha256,
            now + 1,
        )
        .await
        .expect("fence dispatch");
    let wrong = EvidenceFrontierDurableAckV1 {
        backend_id: "backend:repair".to_string(),
        backend_identity_sha256: target.backend_identity_sha256.clone(),
        store_id: target.store_id.clone(),
        frontier_generation: target.frontier_generation,
        frontier_sha256: digest("wrong-target"),
        audit_sequence: 41,
    };
    let error = store
        .acknowledge_frontier_repair(
            &prepared.repair_id,
            "dispatch:repair:one",
            &wrong,
            now + 2,
        )
        .await
        .expect_err("wrong target acknowledgement must fail");
    assert!(matches!(error, EvidenceError::InvalidRecord(_)));
    assert_eq!(
        store
            .get_frontier_repair(&prepared.repair_id)
            .await
            .expect("load repair")
            .expect("repair exists")
            .state,
        EvidenceFrontierRepairStateV1::Dispatching
    );
}

#[tokio::test]
async fn terminal_conflict_releases_the_single_open_repair_slot() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp).await;
    let now = 1_900_000_010_000;
    let (current, target, authorization, authority) = repair_fixture(0xab, now);
    let first = store
        .prepare_frontier_repair(&authorization, &authority, &current, &target, now)
        .await
        .expect("prepare first repair");
    store
        .begin_frontier_repair_dispatch(
            &first.repair_id,
            "dispatch:repair:one",
            &target.backend_identity_sha256,
            now + 1,
        )
        .await
        .expect("dispatch first repair");
    let conflicted = store
        .conflict_frontier_repair(
            &first.repair_id,
            "dispatch:repair:one",
            9,
            &digest("observed-conflict"),
            now + 2,
        )
        .await
        .expect("record terminal conflict");
    assert_eq!(conflicted.state, EvidenceFrontierRepairStateV1::Conflicted);
    assert_eq!(
        conflicted.next_action(),
        EvidenceFrontierRepairActionV1::Conflict
    );

    let (second_current, second_target, second_authorization, second_authority) =
        repair_fixture(0xcd, now + 3);
    store
        .prepare_frontier_repair(
            &second_authorization,
            &second_authority,
            &second_current,
            &second_target,
            now + 3,
        )
        .await
        .expect("terminal conflict permits a new independently authorized repair");
}

#[tokio::test]
async fn ordinary_automatic_successor_is_rejected_by_repair_ledger() {
    let temp = TempDir::new().expect("temp dir");
    let store = opened_store(&temp).await;
    let now = 1_900_000_010_000;
    let (current, mut target, mut authorization, authority) = repair_fixture(0xab, now);
    target.source_commit = current.source_commit.clone();
    authorization.target_frontier_sha256 =
        evidence_recovery_frontier_v2_sha256(&target).expect("target digest");
    let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
    let bytes = frontier_repair_authorization_signing_bytes(&authorization)
        .expect("repair signing bytes");
    authorization.authority_signature_hex = encode_hex(&signing_key.sign(&bytes).to_bytes());
    let error = store
        .prepare_frontier_repair(&authorization, &authority, &current, &target, now)
        .await
        .expect_err("ordinary CAS transition must not enter repair ledger");
    assert!(matches!(error, EvidenceError::InvalidRecord(_)));
}

#[tokio::test]
async fn concurrent_exact_prepare_consumes_one_nonce_row() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let first = opened_store(&temp).await;
    let second = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open second evidence store");
    let now = 1_900_000_010_000;
    let (current, target, authorization, authority) = repair_fixture(0xab, now);
    let (left, right) = tokio::join!(
        first.prepare_frontier_repair(&authorization, &authority, &current, &target, now),
        second.prepare_frontier_repair(&authorization, &authority, &current, &target, now),
    );
    let left = left.expect("left prepare");
    let right = right.expect("right prepare");
    assert_eq!(left, right);
}

fn encode_hex(bytes: &[u8]) -> String {
    let mut encoded = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        write!(&mut encoded, "{byte:02x}").expect("writing to a string cannot fail");
    }
    encoded
}
