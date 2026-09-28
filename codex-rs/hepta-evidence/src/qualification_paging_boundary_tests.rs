use codex_hepta_contracts::Sha256Digest;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use serde_json::json;
use tempfile::TempDir;

use crate::EvidenceCandidateV1;
use crate::EvidenceClaimClassV1;
use crate::EvidenceId;
use crate::EvidenceIssuerRoleV1;
use crate::EvidenceReceiptKindV1;
use crate::HeptaEvidenceStore;
use crate::QualificationEvidenceEnvelopeV1;
use crate::qualification_envelope_bytes;

fn config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp path"),
    )
}

async fn insert_evidence(store: &HeptaEvidenceStore, suffix: &str, recorded_at_ms: i64) {
    let envelope = QualificationEvidenceEnvelopeV1 {
        schema_version: 1,
        evidence_id: EvidenceId::parse(format!("evidence:{suffix}")).expect("evidence id"),
        candidate: EvidenceCandidateV1 {
            candidate_id: "candidate:publication".to_string(),
            source_commit: "a".repeat(40),
            source_tree: "b".repeat(40),
        },
        claim_class: EvidenceClaimClassV1::ExactSource,
        receipt_kind: EvidenceReceiptKindV1::Evidence,
        issuer_role: EvidenceIssuerRoleV1::Architecture,
        payload: json!({"case": suffix}),
        predecessor_evidence_id: None,
        target_evidence_id: None,
        observed_unix_ms: 1,
        expires_unix_ms: None,
        asset_digests: Vec::new(),
    };
    let envelope_bytes = qualification_envelope_bytes(&envelope).expect("canonical envelope");
    let envelope_json = String::from_utf8(envelope_bytes.clone()).expect("UTF-8 envelope");
    let payload_sha256 = Sha256Digest::for_bytes(
        &crate::canonical::canonical_json(&envelope.payload).expect("canonical payload"),
    );
    let envelope_sha256 = Sha256Digest::for_bytes(&envelope_bytes);
    sqlx::query(
        "INSERT INTO qualification_evidence (
            evidence_id, schema_version, candidate_id, source_commit, source_tree,
            claim_class, receipt_kind, issuer_role, issuer_principal_id,
            issuer_key_epoch, issuer_signing_identity_sha256, auth_message_id,
            auth_sequence, auth_expires_at_ms, payload_sha256, envelope_sha256,
            predecessor_evidence_id, target_evidence_id, observed_at_ms, expires_at_ms,
            asset_count, envelope_json, recorded_at_ms
         ) VALUES (?, 1, ?, ?, ?, 'exact_source', 'evidence', 'architecture', ?,
                   ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, NULL, 0, ?, ?)",
    )
    .bind(envelope.evidence_id.as_str())
    .bind(&envelope.candidate.candidate_id)
    .bind(&envelope.candidate.source_commit)
    .bind(&envelope.candidate.source_tree)
    .bind("principal:architecture")
    .bind(1_u64.to_be_bytes().to_vec())
    .bind(Sha256Digest::for_bytes(b"issuer-key").as_str())
    .bind(format!("message:{suffix}"))
    .bind(1_u64.to_be_bytes().to_vec())
    .bind(10_000_u64.to_be_bytes().to_vec())
    .bind(payload_sha256.as_str())
    .bind(envelope_sha256.as_str())
    .bind(envelope.observed_unix_ms.to_be_bytes().to_vec())
    .bind(envelope_json)
    .bind(recorded_at_ms)
    .execute(&store.pool)
    .await
    .expect("insert qualification row");
}

fn candidate() -> EvidenceCandidateV1 {
    EvidenceCandidateV1 {
        candidate_id: "candidate:publication".to_string(),
        source_commit: "a".repeat(40),
        source_tree: "b".repeat(40),
    }
}

#[tokio::test]
async fn page_rejects_payload_digest_drift_using_the_full_row_decoder() {
    let temp = TempDir::new().expect("temp");
    let store = HeptaEvidenceStore::open(&config(&temp)).await.expect("store");
    insert_evidence(&store, "one", 10).await;
    sqlx::query("DROP TRIGGER qualification_evidence_no_update")
        .execute(&store.pool).await.expect("test-only corruption seam");
    sqlx::query("UPDATE qualification_evidence SET payload_sha256 = ?")
        .bind(Sha256Digest::for_bytes(b"not the payload").as_str())
        .execute(&store.pool).await.expect("corrupt digest");
    assert!(
        store.query_qualification_claim_page(&candidate(), EvidenceClaimClassV1::ExactSource, None, 1)
            .await.is_err()
    );
    store.close().await;
}

#[tokio::test]
async fn page_cursor_is_scoped_to_the_exact_candidate_and_claim() {
    let temp = TempDir::new().expect("temp");
    let store = HeptaEvidenceStore::open(&config(&temp)).await.expect("store");
    insert_evidence(&store, "one", 10).await;
    insert_evidence(&store, "two", 20).await;
    let first = store
        .query_qualification_claim_page(&candidate(), EvidenceClaimClassV1::ExactSource, None, 1)
        .await.expect("first page");
    let cursor = first.next_after_seq.expect("continuation");
    let mut wrong = candidate();
    wrong.source_tree = "c".repeat(40);
    assert!(
        store.query_qualification_claim_page(&wrong, EvidenceClaimClassV1::ExactSource, Some(cursor), 1)
            .await.is_err()
    );
    assert!(
        store.query_qualification_claim_page(&candidate(), EvidenceClaimClassV1::MandatoryTests, Some(cursor), 1)
            .await.is_err()
    );
    assert!(
        store.query_qualification_claim_page(&candidate(), EvidenceClaimClassV1::ExactSource, Some(999), 1)
            .await.is_err()
    );
    let second = store
        .query_qualification_claim_page(&candidate(), EvidenceClaimClassV1::ExactSource, Some(cursor), 1)
        .await.expect("valid continuation");
    assert_eq!(second.evidence.len(), 1);
    assert_eq!(second.evidence[0].evidence_id.as_str(), "evidence:two");
    store.close().await;
}
