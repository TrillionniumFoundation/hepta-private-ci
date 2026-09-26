use super::*;

use tempfile::TempDir;

fn database_url(temp: &TempDir) -> String {
    format!("sqlite://{}", temp.path().join("compact.db").display())
}

fn digest(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}

#[tokio::test]
async fn exact_schema_opens_and_reopens_with_integrity_verification() {
    let temp = TempDir::new().expect("tempdir");
    let url = database_url(&temp);
    let store = DurableCompactionStoreV1::open(&url, "agent-owner")
        .await
        .expect("open store");
    store.verify_integrity().await.expect("verify store");
    drop(store);

    let reopened = DurableCompactionStoreV1::open(&url, "agent-owner")
        .await
        .expect("reopen store");
    reopened.verify_integrity().await.expect("verify reopened store");
}

#[tokio::test]
async fn claimed_outbox_is_reconciled_after_restart_and_completed_once() {
    let temp = TempDir::new().expect("tempdir");
    let url = database_url(&temp);
    let store = DurableCompactionStoreV1::open(&url, "agent-owner")
        .await
        .expect("open store");
    let publication = digest("publication");
    let mut connection = store.pool.acquire().await.expect("connection");
    sqlx::query("BEGIN IMMEDIATE")
        .execute(&mut *connection)
        .await
        .expect("begin");
    insert_outbox_raw(
        &mut *connection,
        store.owner_id(),
        &publication.to_string(),
        "checkpoint-published",
        b"event".to_vec(),
        10,
    )
    .await
    .expect("insert outbox");
    sqlx::query("COMMIT")
        .execute(&mut *connection)
        .await
        .expect("commit");
    drop(connection);

    let claimed = store
        .claim_next_outbox(10, "claim-1")
        .await
        .expect("claim")
        .expect("event");
    drop(store);

    let reopened = DurableCompactionStoreV1::open(&url, "agent-owner")
        .await
        .expect("reopen");
    assert_eq!(reopened.reconcile_claims(11).await.expect("reconcile"), 1);
    let reclaimed = reopened
        .claim_next_outbox(11, "claim-2")
        .await
        .expect("reclaim")
        .expect("event");
    assert_eq!(claimed.event_id, reclaimed.event_id);
    assert_eq!(reclaimed.attempt_count, 2);
    reopened
        .complete_outbox(&reclaimed, 12)
        .await
        .expect("complete");
    assert!(
        reopened
            .claim_next_outbox(12, "claim-3")
            .await
            .expect("empty claim")
            .is_none()
    );
}

#[tokio::test]
async fn trust_revocation_is_one_way_and_epoch_scoped() {
    let temp = TempDir::new().expect("tempdir");
    let store = DurableCompactionStoreV1::open(&database_url(&temp), "agent-owner")
        .await
        .expect("open store");
    sqlx::query(
        "INSERT INTO compaction_trust_registry
         (owner_id, role, key_id, trust_epoch, valid_from_unix_seconds,
          valid_until_unix_seconds, predecessor_key_digest, implementation_digest,
          attestation_digest, key_digest, verifying_key, enrollment_digest,
          enrolled_at_unix_seconds, revoked_at_unix_seconds)
         VALUES (?, 'evaluator', 'eval-key', 7, 1, 100, NULL, ?, ?, ?, ?, ?, 2, NULL)",
    )
    .bind(store.owner_id())
    .bind(digest("implementation").to_string())
    .bind(digest("attestation").to_string())
    .bind(digest("key").to_string())
    .bind(vec![7_u8; 32])
    .bind(digest("enrollment").to_string())
    .execute(&store.pool)
    .await
    .expect("insert trust");
    let key_id = StableId::new("eval-key".to_string()).expect("key id");
    store
        .revoke_trust(CompactionTrustRoleV1::Evaluator, &key_id, 7, 50)
        .await
        .expect("revoke");
    assert!(matches!(
        store
            .revoke_trust(CompactionTrustRoleV1::Evaluator, &key_id, 7, 51)
            .await,
        Err(DurableCompactionError::Conflict(_))
    ));
}

#[tokio::test]
async fn immutable_candidate_rows_reject_semantic_drift() {
    let temp = TempDir::new().expect("tempdir");
    let store = DurableCompactionStoreV1::open(&database_url(&temp), "agent-owner")
        .await
        .expect("open store");
    let payload = b"payload".to_vec();
    let payload_digest = Digest32::of_bytes(&payload);
    sqlx::query(
        "INSERT INTO compaction_payloads
         (owner_id, payload_digest, payload_bytes, payload_bytes_digest,
          encoded_bytes, token_count, generator_key_id, generator_trust_epoch,
          tokenizer_key_id, tokenizer_trust_epoch, created_at_unix_seconds)
         VALUES (?, ?, ?, ?, ?, 1, 'generator', 1, 'tokenizer', 1, 1)",
    )
    .bind(store.owner_id())
    .bind(payload_digest.to_string())
    .bind(&payload)
    .bind(payload_digest.to_string())
    .bind(i64::try_from(payload.len()).expect("length"))
    .execute(&store.pool)
    .await
    .expect("insert payload");
    sqlx::query(
        "INSERT INTO compaction_candidates
         (owner_id, idempotency_key, scope_id, purpose_id, generation,
          predecessor_checkpoint_digest, source_snapshot_digest,
          source_memory_snapshot_digest, source_retention_fence_digest,
          retain_source_until_unix_seconds, policy_digest, candidate_digest,
          candidate_image, candidate_image_digest, payload_digest,
          selector_key_id, selector_trust_epoch, generator_key_id,
          generator_trust_epoch, tokenizer_key_id, tokenizer_trust_epoch,
          accepted_at_unix_seconds)
         VALUES (?, 'idempotency', 'scope', 'purpose', 1, NULL, ?, ?, ?, 10, ?, ?, ?, ?, ?,
                 'selector', 1, 'generator', 1, 'tokenizer', 1, 1)",
    )
    .bind(store.owner_id())
    .bind(digest("snapshot").to_string())
    .bind(digest("memory").to_string())
    .bind(digest("retention").to_string())
    .bind(digest("policy").to_string())
    .bind(digest("candidate").to_string())
    .bind(b"candidate".to_vec())
    .bind(Digest32::of_bytes(b"candidate").to_string())
    .bind(payload_digest.to_string())
    .execute(&store.pool)
    .await
    .expect("insert candidate");
    assert!(
        sqlx::query(
            "UPDATE compaction_candidates SET policy_digest = ?
             WHERE owner_id = ? AND candidate_digest = ?",
        )
        .bind(digest("drift").to_string())
        .bind(store.owner_id())
        .bind(digest("candidate").to_string())
        .execute(&store.pool)
        .await
        .is_err()
    );
}

#[test]
fn artifact_limits_cover_the_production_ceiling() {
    let images = CompactionArtifactImagesV1 {
        candidate_image: vec![0_u8; MAX_DURABLE_COMPACTION_ARTIFACT_BYTES],
        evaluation_image: vec![1],
        proof_image: vec![2],
        checkpoint_image: vec![3],
    };
    images.validate().expect("64 MiB ceiling accepted");
    let oversized = CompactionArtifactImagesV1 {
        candidate_image: vec![0_u8; MAX_DURABLE_COMPACTION_ARTIFACT_BYTES + 1],
        evaluation_image: vec![1],
        proof_image: vec![2],
        checkpoint_image: vec![3],
    };
    assert!(oversized.validate().is_err());
}
