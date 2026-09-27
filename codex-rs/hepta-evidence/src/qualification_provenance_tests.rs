use codex_hepta_contracts::Sha256Digest;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use serde_json::json;
use tempfile::TempDir;

use super::*;

fn config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp path"),
    )
}

async fn insert_qualification(
    store: &HeptaEvidenceStore,
    ordinal: u64,
    signature: Option<Vec<u8>>,
    trust_generation: Option<u64>,
    trust_digest: Option<&Sha256Digest>,
) {
    let evidence_id = EvidenceId::parse(format!("evidence:provenance:{ordinal}"))
        .expect("evidence id");
    let envelope = QualificationEvidenceEnvelopeV1 {
        schema_version: QUALIFICATION_EVIDENCE_SCHEMA_VERSION,
        evidence_id: evidence_id.clone(),
        candidate: EvidenceCandidateV1 {
            candidate_id: "candidate:provenance".to_string(),
            source_commit: "a".repeat(40),
            source_tree: "b".repeat(40),
        },
        claim_class: EvidenceClaimClassV1::ExactSource,
        receipt_kind: EvidenceReceiptKindV1::Evidence,
        issuer_role: EvidenceIssuerRoleV1::Architecture,
        payload: json!({"ordinal": ordinal}),
        predecessor_evidence_id: None,
        target_evidence_id: None,
        observed_unix_ms: 1,
        expires_unix_ms: Some(10_000),
        asset_digests: Vec::new(),
    };
    let envelope_bytes = qualification_envelope_bytes(&envelope).expect("canonical envelope");
    let envelope_json = String::from_utf8(envelope_bytes.clone()).expect("utf8 envelope");
    let payload = crate::canonical::canonical_json(&envelope.payload).expect("canonical payload");
    let payload_sha256 = Sha256Digest::for_bytes(&payload);
    let envelope_sha256 = Sha256Digest::for_bytes(&envelope_bytes);
    let signing_identity_sha256 = Sha256Digest::for_bytes(b"issuer:provenance:key");

    sqlx::query(
        "INSERT INTO qualification_evidence (
            evidence_id, schema_version, candidate_id, source_commit, source_tree,
            claim_class, receipt_kind, issuer_role, issuer_principal_id,
            issuer_key_epoch, issuer_signing_identity_sha256, auth_message_id,
            auth_sequence, auth_expires_at_ms, auth_signature,
            trust_registry_generation, trust_registry_sha256,
            payload_sha256, envelope_sha256, predecessor_evidence_id,
            target_evidence_id, observed_at_ms, expires_at_ms,
            asset_count, envelope_json, recorded_at_ms
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(evidence_id.as_str())
    .bind(i64::from(QUALIFICATION_EVIDENCE_SCHEMA_VERSION))
    .bind(&envelope.candidate.candidate_id)
    .bind(&envelope.candidate.source_commit)
    .bind(&envelope.candidate.source_tree)
    .bind(envelope.claim_class.as_str())
    .bind("evidence")
    .bind(envelope.issuer_role.as_str())
    .bind("issuer:provenance")
    .bind(1_u64.to_be_bytes().to_vec())
    .bind(signing_identity_sha256.as_str())
    .bind(format!("message:provenance:{ordinal}"))
    .bind(ordinal.saturating_add(1).to_be_bytes().to_vec())
    .bind(20_000_u64.to_be_bytes().to_vec())
    .bind(signature)
    .bind(
        trust_generation
            .map(u64::to_be_bytes)
            .map(|bytes| bytes.to_vec()),
    )
    .bind(trust_digest.map(Sha256Digest::as_str))
    .bind(payload_sha256.as_str())
    .bind(envelope_sha256.as_str())
    .bind(Option::<String>::None)
    .bind(Option::<String>::None)
    .bind(envelope.observed_unix_ms.to_be_bytes().to_vec())
    .bind(
        envelope
            .expires_unix_ms
            .map(u64::to_be_bytes)
            .map(|bytes| bytes.to_vec()),
    )
    .bind(0_i64)
    .bind(envelope_json)
    .bind(i64::try_from(ordinal.saturating_add(1)).expect("recorded time"))
    .execute(&store.pool)
    .await
    .expect("insert qualification row");
}

async fn accept_trust_generation(
    store: &HeptaEvidenceStore,
    generation: u64,
    digest: &Sha256Digest,
) {
    let predecessor = (generation > 1).then(|| Sha256Digest::for_bytes(b"predecessor"));
    sqlx::query(
        "INSERT INTO evidence_trust_acceptance (
            store_id, agent_id, registry_generation, registry_sha256,
            predecessor_sha256, accepted_frontier_generation,
            accepted_frontier_sha256, backend_identity_sha256, accepted_at_ms
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind("store:provenance")
    .bind("agent:provenance")
    .bind(generation.to_be_bytes().to_vec())
    .bind(digest.as_str())
    .bind(predecessor.as_ref().map(Sha256Digest::as_str))
    .bind(generation.to_be_bytes().to_vec())
    .bind(Sha256Digest::for_bytes(b"frontier").as_str())
    .bind(Sha256Digest::for_bytes(b"backend").as_str())
    .bind(1_u64.to_be_bytes().to_vec())
    .execute(&store.pool)
    .await
    .expect("accept trust generation");
}

#[tokio::test]
async fn production_provenance_rejects_missing_signature_or_trust_identity() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&config(&temp)).await.expect("open store");
    store
        .bind_recovery_store_id("store:provenance")
        .await
        .expect("enroll store");
    let current = Sha256Digest::for_bytes(b"trust:current");
    insert_qualification(&store, 1, None, Some(2), Some(&current)).await;

    let error = store
        .verify_production_qualification_provenance_bounded(2, &current)
        .await
        .expect_err("missing signature must fail closed");
    assert!(error.to_string().contains("lacks complete authentication provenance"));
    store.close().await;
}

#[tokio::test]
async fn production_provenance_pages_and_accepts_current_or_prior_accepted_trust() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&config(&temp)).await.expect("open store");
    store
        .bind_recovery_store_id("store:provenance")
        .await
        .expect("enroll store");
    let prior = Sha256Digest::for_bytes(b"trust:prior");
    let current = Sha256Digest::for_bytes(b"trust:current");
    accept_trust_generation(&store, 1, &prior).await;

    insert_qualification(&store, 1, Some(vec![7_u8; 64]), Some(1), Some(&prior)).await;
    for ordinal in 2..=258 {
        insert_qualification(
            &store,
            ordinal,
            Some(vec![8_u8; 64]),
            Some(2),
            Some(&current),
        )
        .await;
    }

    store
        .verify_production_qualification_provenance_bounded(2, &current)
        .await
        .expect("paged provenance verification");
    store.close().await;
}

#[tokio::test]
async fn production_provenance_rejects_unaccepted_noncurrent_trust() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&config(&temp)).await.expect("open store");
    store
        .bind_recovery_store_id("store:provenance")
        .await
        .expect("enroll store");
    let prior = Sha256Digest::for_bytes(b"trust:unaccepted");
    let current = Sha256Digest::for_bytes(b"trust:current");
    insert_qualification(
        &store,
        1,
        Some(vec![9_u8; 64]),
        Some(1),
        Some(&prior),
    )
    .await;

    let error = store
        .verify_production_qualification_provenance_bounded(2, &current)
        .await
        .expect_err("unaccepted prior trust must fail closed");
    assert!(error.to_string().contains("unaccepted trust generation"));
    store.close().await;
}
