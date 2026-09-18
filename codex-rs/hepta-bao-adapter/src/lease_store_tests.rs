use super::*;
use tempfile::TempDir;

fn metadata(lease_id: &str, request_byte: u8) -> SecretLeaseMetadataV1 {
    SecretLeaseMetadataV1 {
        schema_version: SECRET_LEASE_SCHEMA_VERSION_V1,
        lease_id: lease_id.to_owned(),
        provider_mount: "database".to_owned(),
        namespace: "team-a".to_owned(),
        consumer_id: "model-provider".to_owned(),
        scope_sha256: [7; 32],
        request_sha256: [request_byte; 32],
        fingerprint_key_id: "receipt-key-1".to_owned(),
        secret_fingerprint: [9; 32],
        renewable: true,
        issued_at_ms: 1_000,
        expires_at_ms: 61_000,
        rotation_generation: 1,
        state: SecretLeaseStateV1::Active,
        revision: 1,
    }
}

async fn opened() -> (TempDir, SecretLeaseStore) {
    let directory = tempfile::tempdir().unwrap();
    let store = SecretLeaseStore::open(directory.path()).await.unwrap();
    (directory, store)
}

#[tokio::test]
async fn operation_identity_is_idempotent_but_semantic_drift_conflicts() {
    let (_directory, store) = opened().await;
    let first = store
        .prepare_operation(
            "issue-1",
            SecretLeaseOperationKindV1::Issue,
            None,
            [1; 32],
            10,
        )
        .await
        .unwrap();
    assert_eq!(first, SecretLeaseOperationAdmissionV1::Prepared);
    let retry = store
        .prepare_operation(
            "issue-1",
            SecretLeaseOperationKindV1::Issue,
            None,
            [1; 32],
            11,
        )
        .await
        .unwrap();
    assert_eq!(retry, SecretLeaseOperationAdmissionV1::AlreadyPrepared);
    assert_eq!(
        store
            .prepare_operation(
                "issue-1",
                SecretLeaseOperationKindV1::Issue,
                None,
                [2; 32],
                12,
            )
            .await,
        Err(SecretLeaseStoreError::Conflict)
    );
}

#[tokio::test]
async fn dispatching_operation_survives_restart_and_is_not_reissued() {
    let (directory, store) = opened().await;
    store
        .prepare_operation(
            "issue-2",
            SecretLeaseOperationKindV1::Issue,
            None,
            [3; 32],
            20,
        )
        .await
        .unwrap();
    assert!(store.claim_dispatch("issue-2", 21).await.unwrap());
    store.close().await;

    let reopened = SecretLeaseStore::open(directory.path()).await.unwrap();
    let operation = reopened.operation("issue-2").await.unwrap().unwrap();
    assert_eq!(operation.state, SecretLeaseOperationStateV1::Dispatching);
    let admission = reopened
        .prepare_operation(
            "issue-2",
            SecretLeaseOperationKindV1::Issue,
            None,
            [3; 32],
            22,
        )
        .await
        .unwrap();
    assert_eq!(admission, SecretLeaseOperationAdmissionV1::Dispatching);
    assert!(!reopened.claim_dispatch("issue-2", 23).await.unwrap());
    let uncertain = reopened.indeterminate_operations(10).await.unwrap();
    assert_eq!(uncertain.len(), 1);
    assert_eq!(uncertain[0].operation_id, "issue-2");
}

#[tokio::test]
async fn issuance_allocates_monotone_rotation_generation_per_scope() {
    let (_directory, store) = opened().await;
    for (operation_id, lease_id, digest) in [
        ("issue-a", "database/creds/role/a", 4_u8),
        ("issue-b", "database/creds/role/b", 5_u8),
    ] {
        store
            .prepare_operation(
                operation_id,
                SecretLeaseOperationKindV1::Issue,
                None,
                [digest; 32],
                100,
            )
            .await
            .unwrap();
        assert!(store.claim_dispatch(operation_id, 101).await.unwrap());
        let stored = store
            .commit_issue(
                operation_id,
                &metadata(lease_id, digest),
                [digest + 20; 32],
                102,
            )
            .await
            .unwrap();
        let expected_generation = if operation_id == "issue-a" { 1 } else { 2 };
        assert_eq!(stored.rotation_generation, expected_generation);
    }
}

#[tokio::test]
async fn renewal_ambiguity_fences_use_until_lookup_reconciles() {
    let (_directory, store) = opened().await;
    store
        .prepare_operation(
            "issue-c",
            SecretLeaseOperationKindV1::Issue,
            None,
            [6; 32],
            200,
        )
        .await
        .unwrap();
    store.claim_dispatch("issue-c", 201).await.unwrap();
    let lease = store
        .commit_issue(
            "issue-c",
            &metadata("database/creds/role/c", 6),
            [26; 32],
            202,
        )
        .await
        .unwrap();

    store
        .prepare_operation(
            "renew-c",
            SecretLeaseOperationKindV1::Renew,
            Some(&lease.lease_id),
            [8; 32],
            300,
        )
        .await
        .unwrap();
    store.claim_dispatch("renew-c", 301).await.unwrap();
    store
        .mark_lease_indeterminate(
            "renew-c",
            &lease.lease_id,
            SecretLeaseStateV1::RenewIndeterminate,
            None,
            302,
        )
        .await
        .unwrap();
    let fenced = store.lease(&lease.lease_id).await.unwrap().unwrap();
    assert!(!fenced.is_usable_at(303));

    let reconciled = store
        .reconcile_known_active(
            "renew-c",
            &lease.lease_id,
            true,
            90_000,
            [30; 32],
            304,
        )
        .await
        .unwrap();
    assert_eq!(reconciled.state, SecretLeaseStateV1::Active);
    assert_eq!(reconciled.expires_at_ms, 90_000);
    assert_eq!(
        store.operation("renew-c").await.unwrap().unwrap().state,
        SecretLeaseOperationStateV1::Applied
    );
}

#[tokio::test]
async fn revoke_ambiguity_is_terminally_fenced_when_lookup_reports_absent() {
    let (_directory, store) = opened().await;
    store
        .prepare_operation(
            "issue-d",
            SecretLeaseOperationKindV1::Issue,
            None,
            [10; 32],
            400,
        )
        .await
        .unwrap();
    store.claim_dispatch("issue-d", 401).await.unwrap();
    let lease = store
        .commit_issue(
            "issue-d",
            &metadata("database/creds/role/d", 10),
            [31; 32],
            402,
        )
        .await
        .unwrap();

    store
        .prepare_operation(
            "revoke-d",
            SecretLeaseOperationKindV1::Revoke,
            Some(&lease.lease_id),
            [11; 32],
            500,
        )
        .await
        .unwrap();
    store.claim_dispatch("revoke-d", 501).await.unwrap();
    store
        .mark_lease_indeterminate(
            "revoke-d",
            &lease.lease_id,
            SecretLeaseStateV1::RevokeIndeterminate,
            None,
            502,
        )
        .await
        .unwrap();

    let reconciled = store
        .reconcile_known_absent("revoke-d", &lease.lease_id, [32; 32], 503)
        .await
        .unwrap();
    assert_eq!(reconciled.state, SecretLeaseStateV1::Revoked);
    assert_eq!(
        store.operation("revoke-d").await.unwrap().unwrap().state,
        SecretLeaseOperationStateV1::Applied
    );
}

#[tokio::test]
async fn issue_ambiguity_requires_explicit_trusted_observation() {
    let (_directory, store) = opened().await;
    store
        .prepare_operation(
            "issue-e",
            SecretLeaseOperationKindV1::Issue,
            None,
            [12; 32],
            600,
        )
        .await
        .unwrap();
    store.claim_dispatch("issue-e", 601).await.unwrap();
    store
        .mark_issue_indeterminate("issue-e", None, 602)
        .await
        .unwrap();
    assert_eq!(
        store
            .prepare_operation(
                "issue-e",
                SecretLeaseOperationKindV1::Issue,
                None,
                [12; 32],
                603,
            )
            .await
            .unwrap(),
        SecretLeaseOperationAdmissionV1::Indeterminate
    );

    assert_eq!(
        store
            .reconcile_issue_observation(
                "issue-e",
                SecretLeaseIssueObservationV1::NotApplied,
                [33; 32],
                604,
            )
            .await
            .unwrap(),
        None
    );
    assert_eq!(
        store.operation("issue-e").await.unwrap().unwrap().state,
        SecretLeaseOperationStateV1::NotApplied
    );
}
