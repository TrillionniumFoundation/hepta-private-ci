use codex_hepta_contracts::Sha256Digest;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use serde_json::json;
use tempfile::TempDir;

use super::*;
use crate::EvidenceCandidateV1;
use crate::EvidenceClaimClassV1;
use crate::EvidenceId;
use crate::EvidenceIssuerRoleV1;
use crate::EvidenceReceiptKindV1;
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

#[tokio::test]
async fn owner_fencing_and_indeterminate_cas_reuse_one_durable_batch() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&config(&temp))
        .await
        .expect("open store");
    store
        .bind_recovery_store_id("store:publication")
        .await
        .expect("enroll store");
    insert_evidence(&store, "one", 10).await;
    assert_eq!(store.pending_publication_count().await.expect("pending"), 1);

    let owner_a = store
        .claim_publication_owner("publisher:a", 100, 100)
        .await
        .expect("first owner");
    assert_eq!(owner_a.owner_generation, 1);
    assert!(
        store
            .claim_publication_owner("publisher:b", 150, 100)
            .await
            .is_err(),
        "a live publication owner must fence competitors"
    );

    let prepared = store
        .prepare_publication_batch(&owner_a, 110, 32)
        .await
        .expect("prepare")
        .expect("batch");
    assert_eq!(prepared.state, EvidencePublicationBatchStateV1::Prepared);
    assert_eq!(prepared.expected_frontier_generation, None);
    assert_eq!(prepared.proposed_frontier_generation, 1);
    let repeated = store
        .prepare_publication_batch(&owner_a, 111, 32)
        .await
        .expect("repeat prepare")
        .expect("same batch");
    assert_eq!(repeated.batch_id, prepared.batch_id);

    let frontier_sha256 = Sha256Digest::for_bytes(b"frontier:one");
    let backend_sha256 = Sha256Digest::for_bytes(b"backend:one");
    let dispatched = store
        .mark_publication_dispatched(
            &owner_a,
            &prepared.batch_id,
            &frontier_sha256,
            &backend_sha256,
            120,
        )
        .await
        .expect("dispatch fence");
    assert_eq!(
        dispatched.state,
        EvidencePublicationBatchStateV1::Dispatching
    );
    assert_eq!(
        store
            .classify_publication_latest(&prepared.batch_id, None)
            .await
            .expect("classify predecessor"),
        EvidencePublicationLatestDisposition::RetrySameBatch
    );
    let indeterminate = store
        .mark_publication_indeterminate(&owner_a, &prepared.batch_id, 130)
        .await
        .expect("mark indeterminate");
    assert_eq!(
        indeterminate.state,
        EvidencePublicationBatchStateV1::Indeterminate
    );

    let owner_b = store
        .claim_publication_owner("publisher:b", 201, 100)
        .await
        .expect("successor owner");
    assert_eq!(owner_b.owner_generation, 2);
    assert!(
        store
            .mark_publication_indeterminate(&owner_a, &prepared.batch_id, 202)
            .await
            .is_err(),
        "the predecessor owner must remain fenced"
    );
    let latest = EvidencePublicationLatestV1 {
        frontier_generation: 1,
        frontier_sha256: frontier_sha256.clone(),
        backend_identity_sha256: backend_sha256.clone(),
    };
    assert_eq!(
        store
            .classify_publication_latest(&prepared.batch_id, Some(&latest))
            .await
            .expect("classify applied CAS"),
        EvidencePublicationLatestDisposition::RecoverDurableAcknowledgement
    );
    let acknowledgement = EvidenceFrontierDurableAckV1 {
        backend_id: "backend:one".to_string(),
        backend_identity_sha256: backend_sha256,
        store_id: "store:publication".to_string(),
        frontier_generation: 1,
        frontier_sha256,
        audit_sequence: 1,
    };
    assert_eq!(
        store
            .acknowledge_publication(&owner_b, &prepared.batch_id, &acknowledgement, 210)
            .await
            .expect("acknowledge"),
        EvidencePublicationAckDisposition::Acknowledged
    );
    assert_eq!(store.pending_publication_count().await.expect("pending"), 0);
    assert_eq!(
        store
            .acknowledge_publication(&owner_b, &prepared.batch_id, &acknowledgement, 211)
            .await
            .expect("idempotent acknowledgement"),
        EvidencePublicationAckDisposition::AlreadyAcknowledged
    );
    assert_eq!(
        store
            .classify_publication_latest(&prepared.batch_id, Some(&latest))
            .await
            .expect("classify acknowledged"),
        EvidencePublicationLatestDisposition::AlreadyAcknowledged
    );
}

#[tokio::test]
async fn enrolled_store_backfills_and_new_appends_enqueue_once() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&config(&temp))
        .await
        .expect("open store");
    insert_evidence(&store, "before-enrollment", 10).await;
    assert_eq!(store.pending_publication_count().await.expect("pending"), 0);
    store
        .bind_recovery_store_id("store:backfill")
        .await
        .expect("enroll store");
    assert_eq!(
        store.pending_publication_count().await.expect("backfill"),
        1
    );
    insert_evidence(&store, "after-enrollment", 20).await;
    assert_eq!(store.pending_publication_count().await.expect("trigger"), 2);
    store
        .bind_recovery_store_id("store:backfill")
        .await
        .expect("idempotent enrollment");
    assert_eq!(
        store
            .pending_publication_count()
            .await
            .expect("no duplicate"),
        2
    );
}

#[tokio::test]
async fn dispatch_rejects_owner_expired_while_waiting_for_writer() {
    use std::time::Duration;
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    let now_unix_ms = || {
        u64::try_from(
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .expect("host clock after epoch")
                .as_millis(),
        )
        .expect("host clock fits publication timestamp")
    };
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&config(&temp))
        .await
        .expect("open store");
    store
        .bind_recovery_store_id("store:writer-wait-expiry")
        .await
        .expect("enroll store");
    insert_evidence(&store, "writer-wait-expiry", /*recorded_at_ms*/ 10).await;
    let lease = store
        .claim_publication_owner(
            "publisher:writer-wait",
            now_unix_ms(),
            /*lease_duration_ms*/ 2_000,
        )
        .await
        .expect("claim initially current owner");
    let prepared = store
        .prepare_publication_batch(&lease, now_unix_ms(), /*maximum_intents*/ 1)
        .await
        .expect("prepare before blocking writer")
        .expect("pending intent");
    let blocker = store
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("reserve separate writer before dispatch");
    let captured_now = now_unix_ms();
    assert!(
        captured_now < lease.lease_expires_at_unix_ms,
        "test setup must leave a live lease at the dispatch call"
    );
    let frontier = Sha256Digest::for_bytes(b"writer-wait-frontier");
    let backend = Sha256Digest::for_bytes(b"writer-wait-backend");
    let result = {
        let dispatch = store.mark_publication_dispatched(
            &lease,
            &prepared.batch_id,
            &frontier,
            &backend,
            captured_now,
        );
        tokio::pin!(dispatch);
        // Poll the actual operation with the writer reservation still held.
        // Timing out this borrowed future does not drop or restart dispatch.
        assert!(
            tokio::time::timeout(Duration::from_millis(25), dispatch.as_mut())
                .await
                .is_err(),
            "dispatch must remain blocked while the separate writer is held"
        );
        assert!(
            now_unix_ms() < lease.lease_expires_at_unix_ms,
            "the operation must be polled while its captured lease is live"
        );
        // Do not infer expiry from a sleep alone. Observe the exact wall-clock
        // deadline under a bounded monotonic timeout before releasing the lock.
        tokio::time::timeout(Duration::from_secs(3), async {
            while now_unix_ms() < lease.lease_expires_at_unix_ms {
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        })
        .await
        .expect("host clock must cross the lease expiry within the test bound");
        blocker
            .rollback()
            .await
            .expect("release writer after expiry");
        tokio::time::timeout(Duration::from_secs(5), dispatch.as_mut())
            .await
            .expect("dispatch must finish after the writer is released")
    };
    let observed = store
        .publication_batch(&prepared.batch_id)
        .await
        .expect("read durable batch after writer wait")
        .expect("batch remains present");
    store.close().await;
    assert!(
        result.is_err(),
        "EXPIRED_PUBLICATION_DISPATCH_ACCEPTED: a pre-wait timestamp authorized a durable dispatch after lease expiry; durable state={:?}",
        observed.state
    );
    assert!(
        matches!(result, Err(EvidenceError::Unavailable(message)) if message.contains("expired")),
        "the owner-time fence must report lease expiry, not an unrelated storage failure"
    );
    assert_eq!(
        observed, prepared,
        "rejection must preserve the complete batch"
    );
}
