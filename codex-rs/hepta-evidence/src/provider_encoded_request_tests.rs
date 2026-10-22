use super::*;

#[tokio::test]
async fn encoded_request_rejects_sqlite_dynamic_type_substitution() {
    let temp = TempDir::new().expect("temp");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open");
    let intent = intent(118);
    store.claim_provider_intent(&intent).await.expect("claim");
    let digest = Sha256Digest::for_bytes(b"complete encoded body");
    let invalid_length = 1.5_f64;
    assert!(
        sqlx::query("INSERT INTO provider_encoded_requests_v1 VALUES (?, ?, ?)")
            .bind(intent.attempt_id.as_str())
            .bind(digest.as_str())
            .bind(invalid_length)
            .execute(&store.pool)
            .await
            .is_err()
    );
    let valid_length = 21_i64;
    assert!(
        sqlx::query("INSERT INTO provider_encoded_requests_v1 VALUES (?, ?, ?)")
            .bind(intent.attempt_id.as_str())
            .bind(vec![b'a'; 64])
            .bind(valid_length)
            .execute(&store.pool)
            .await
            .is_err()
    );
}

#[tokio::test]
async fn encoded_request_requires_exact_pending_intent_valid_length_and_immutable_bytes() {
    let temp = TempDir::new().expect("temp");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open");
    let intent = intent(117);
    let digest = Sha256Digest::for_bytes(b"complete encoded body");
    assert!(
        store
            .bind_provider_encoded_request_v1(&intent, &digest, 21)
            .await
            .is_err()
    );
    store.claim_provider_intent(&intent).await.expect("claim");
    for bytes in [0, u64::MAX] {
        assert!(
            store
                .bind_provider_encoded_request_v1(&intent, &digest, bytes)
                .await
                .is_err()
        );
    }
    let mut wrong = intent.clone();
    wrong.binding.turn_id = "wrong-turn".into();
    assert!(
        store
            .bind_provider_encoded_request_v1(&wrong, &digest, 21)
            .await
            .is_err()
    );
    assert_eq!(
        store
            .bind_provider_encoded_request_v1(&intent, &digest, 21)
            .await
            .expect("bind"),
        AppendDisposition::Inserted
    );
    assert_eq!(
        store
            .bind_provider_encoded_request_v1(&intent, &digest, 21)
            .await
            .expect("exact replay"),
        AppendDisposition::AlreadyPresent
    );
    assert!(
        store
            .bind_provider_encoded_request_v1(&intent, &Sha256Digest::for_bytes(b"changed"), 21)
            .await
            .is_err()
    );
    for sql in [
        "UPDATE provider_encoded_requests_v1 SET byte_length = 22",
        "DELETE FROM provider_encoded_requests_v1",
    ] {
        assert!(sqlx::query(sql).execute(&store.pool).await.is_err());
    }
    store
        .append_provider_receipt(&ProviderInvocationReceipt::new(
            intent.clone(),
            ProviderTerminal::NotDispatched {
                reason_code: "controlled_cancel".into(),
            },
        ))
        .await
        .expect("terminal");
    assert!(
        store
            .bind_provider_encoded_request_v1(&intent, &digest, 21)
            .await
            .is_err()
    );
    sqlx::query("DROP TRIGGER provider_encoded_requests_v1_no_update")
        .execute(&store.pool)
        .await
        .expect("controlled schema damage");
    store.close().await;
    assert!(
        HeptaEvidenceStore::open_existing_read_only(&sqlite_config(&temp))
            .await
            .is_err()
    );
}
