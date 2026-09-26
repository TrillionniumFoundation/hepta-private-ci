use codex_hepta_contracts::Sha256Digest;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use serde_json::json;
use sqlx::Row;
use tempfile::TempDir;

use crate::EVIDENCE_DATABASE_LINEAGE;
use crate::EvidenceCandidateV1;
use crate::EvidenceClaimClassV1;
use crate::EvidenceId;
use crate::EvidenceIssuerRoleV1;
use crate::EvidenceReceiptKindV1;
use crate::HeptaEvidenceStore;
use crate::QUALIFICATION_EVIDENCE_SCHEMA_VERSION;
use crate::QualificationEvidenceEnvelopeV1;
use crate::qualification_envelope_bytes;

fn sqlite_config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp path"),
    )
}

fn candidate() -> EvidenceCandidateV1 {
    EvidenceCandidateV1 {
        candidate_id: "candidate:paging".to_string(),
        source_commit: "a".repeat(40),
        source_tree: "b".repeat(40),
    }
}

async fn insert_rows(store: &HeptaEvidenceStore, count: u64) {
    let candidate = candidate();
    for index in 1..=count {
        let envelope = QualificationEvidenceEnvelopeV1 {
            schema_version: QUALIFICATION_EVIDENCE_SCHEMA_VERSION,
            evidence_id: EvidenceId::parse(format!("evidence:paging:{index:04}"))
                .expect("evidence id"),
            candidate: candidate.clone(),
            claim_class: EvidenceClaimClassV1::MandatoryTests,
            receipt_kind: EvidenceReceiptKindV1::Evidence,
            issuer_role: EvidenceIssuerRoleV1::Evaluator,
            payload: json!({"index": index}),
            predecessor_evidence_id: None,
            target_evidence_id: None,
            observed_unix_ms: 1_900_000_000_000 + index,
            expires_unix_ms: None,
            asset_digests: Vec::new(),
        };
        let envelope_bytes = qualification_envelope_bytes(&envelope).expect("canonical envelope");
        let envelope_json = String::from_utf8(envelope_bytes.clone()).expect("UTF-8 envelope");
        let envelope_sha256 = Sha256Digest::for_bytes(&envelope_bytes);
        let payload_sha256 = Sha256Digest::for_bytes(
            &serde_json::to_vec(&envelope.payload).expect("serialize payload"),
        );
        sqlx::query(
            "INSERT INTO qualification_evidence (
                evidence_id, schema_version, candidate_id, source_commit, source_tree,
                claim_class, receipt_kind, issuer_role, issuer_principal_id,
                issuer_key_epoch, issuer_signing_identity_sha256, auth_message_id,
                auth_sequence, auth_expires_at_ms, payload_sha256, envelope_sha256,
                predecessor_evidence_id, target_evidence_id, observed_at_ms, expires_at_ms,
                asset_count, envelope_json, recorded_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, NULL, 0, ?, ?)",
        )
        .bind(envelope.evidence_id.as_str())
        .bind(i64::from(QUALIFICATION_EVIDENCE_SCHEMA_VERSION))
        .bind(&candidate.candidate_id)
        .bind(&candidate.source_commit)
        .bind(&candidate.source_tree)
        .bind(EvidenceClaimClassV1::MandatoryTests.as_str())
        .bind("evidence")
        .bind(EvidenceIssuerRoleV1::Evaluator.as_str())
        .bind("issuer:paging")
        .bind(1_u64.to_be_bytes().to_vec())
        .bind(Sha256Digest::for_bytes(b"issuer-key").as_str())
        .bind(format!("message:paging:{index:04}"))
        .bind(index.to_be_bytes().to_vec())
        .bind((1_900_000_100_000_u64 + index).to_be_bytes().to_vec())
        .bind(payload_sha256.as_str())
        .bind(envelope_sha256.as_str())
        .bind(envelope.observed_unix_ms.to_be_bytes().to_vec())
        .bind(envelope_json)
        .bind(i64::try_from(1_900_000_000_000_u64 + index).expect("recorded time"))
        .execute(&store.pool)
        .await
        .expect("insert qualification row");
    }
}

#[tokio::test]
async fn cursor_pages_are_stable_complete_and_non_overlapping() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence store");
    insert_rows(&store, 5).await;

    let mut after = None;
    let mut ids = Vec::new();
    loop {
        let page = store
            .query_qualification_claim_page(
                &candidate(),
                EvidenceClaimClassV1::MandatoryTests,
                after,
                2,
            )
            .await
            .expect("query page");
        ids.extend(
            page.evidence
                .iter()
                .map(|reference| reference.evidence_id.to_string()),
        );
        match page.next_after_seq {
            Some(cursor) => {
                assert!(after.is_none_or(|previous| cursor > previous));
                after = Some(cursor);
            }
            None => break,
        }
    }
    assert_eq!(
        ids,
        (1..=5)
            .map(|index| format!("evidence:paging:{index:04}"))
            .collect::<Vec<_>>()
    );
}

#[tokio::test]
async fn cursor_query_rejects_unbounded_limits_and_large_cursors() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence store");
    for limit in [0, 513] {
        assert!(
            store
                .query_qualification_claim_page(
                    &candidate(),
                    EvidenceClaimClassV1::MandatoryTests,
                    None,
                    limit,
                )
                .await
                .is_err()
        );
    }
    assert!(
        store
            .query_qualification_claim_page(
                &candidate(),
                EvidenceClaimClassV1::MandatoryTests,
                Some(u64::MAX),
                1,
            )
            .await
            .is_err()
    );
}

#[tokio::test]
async fn cursor_query_uses_the_candidate_claim_sequence_index() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence store");
    let rows = sqlx::query(
        "EXPLAIN QUERY PLAN
         SELECT seq FROM qualification_evidence
         WHERE candidate_id = ? AND source_commit = ? AND source_tree = ?
           AND claim_class = ? AND seq > ?
         ORDER BY seq ASC LIMIT ?",
    )
    .bind("candidate:paging")
    .bind("a".repeat(40))
    .bind("b".repeat(40))
    .bind(EvidenceClaimClassV1::MandatoryTests.as_str())
    .bind(0_i64)
    .bind(2_i64)
    .fetch_all(&store.pool)
    .await
    .expect("query plan");
    let details = rows
        .iter()
        .map(|row| row.try_get::<String, _>("detail").expect("plan detail"))
        .collect::<Vec<_>>()
        .join("\n");
    assert!(
        details.contains("idx_qualification_evidence_candidate_claim"),
        "unexpected query plan for {EVIDENCE_DATABASE_LINEAGE}: {details}"
    );
}
