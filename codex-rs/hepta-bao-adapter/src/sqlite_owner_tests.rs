use super::*;
use crate::BaoConsumptionRecoveryActionV1;
use crate::BaoSecretReceipt;
use crate::LeaseOperationKindV1;
use crate::ProviderLeaseObservationV1;
use std::os::unix::fs::PermissionsExt;

fn private_database() -> (tempfile::TempDir, std::path::PathBuf) {
    let directory =
        tempfile::tempdir().unwrap_or_else(|error| panic!("temporary owner directory: {error}"));
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))
        .unwrap_or_else(|error| panic!("private owner directory: {error}"));
    let path = directory.path().join("bao-owner.sqlite");
    (directory, path)
}

fn consumption(operation_id: &str) -> BaoConsumptionOperationV1 {
    BaoConsumptionOperationV1 {
        operation_id: operation_id.to_owned(),
        semantic_sha256: [1; 32],
        effect_sha256: [2; 32],
        request_sha256: [3; 32],
        consumer_id: "runtime.agentd".to_owned(),
        consumer_configuration_sha256: [4; 32],
        amount: 5,
        reservation_id: None,
        state: BaoConsumptionStateV1::Claimed,
        receipt: None,
        created_revision: 0,
        updated_revision: 0,
        terminal_kind: None,
        terminal_code: None,
        terminal_evidence_sha256: None,
        terminal_observed_cost: None,
    }
}

fn receipt() -> BaoSecretReceipt {
    BaoSecretReceipt {
        request_sha256: [3; 32],
        response_sha256: [5; 32],
        secret_sha256: [6; 32],
        version: 7,
        secret_bytes: 8,
    }
}

fn prepared_issue(operation_id: &str) -> LeaseOperationV1 {
    LeaseOperationV1 {
        operation_id: operation_id.to_owned(),
        kind: LeaseOperationKindV1::Issue,
        semantic_sha256: [21; 32],
        lease_id: None,
        expected_generation: None,
        observed_at_unix_ms: None,
        resulting_generation: None,
        legacy_binding_incomplete: false,
        result_lease: None,
        result_observation: None,
        state: LeaseOperationStateV1::Prepared,
    }
}

fn prepared_mutation(
    operation_id: &str,
    kind: LeaseOperationKindV1,
    generation: u64,
) -> LeaseOperationV1 {
    LeaseOperationV1 {
        operation_id: operation_id.to_owned(),
        kind,
        semantic_sha256: [22; 32],
        lease_id: Some("lease:database:readonly".to_owned()),
        expected_generation: Some(generation),
        observed_at_unix_ms: None,
        resulting_generation: None,
        legacy_binding_incomplete: false,
        result_lease: None,
        result_observation: None,
        state: LeaseOperationStateV1::Prepared,
    }
}

fn active_lease(generation: u64, expires_at_unix_ms: u64) -> SecretLeaseMetadataV1 {
    SecretLeaseMetadataV1 {
        lease_id: "lease:database:readonly".to_owned(),
        secret_reference_id: "database:readonly".to_owned(),
        consumer_id: "runtime.agentd".to_owned(),
        scope_sha256: [23; 32],
        provider_metadata_sha256: [24; 32],
        issued_at_unix_ms: 1_000,
        expires_at_unix_ms,
        renewable: true,
        generation,
        state: SecretLeaseStateV1::Active,
    }
}

fn applied_issue(prepared: &LeaseOperationV1, lease: &SecretLeaseMetadataV1) -> LeaseOperationV1 {
    LeaseOperationV1 {
        operation_id: prepared.operation_id.clone(),
        kind: prepared.kind,
        semantic_sha256: prepared.semantic_sha256,
        lease_id: Some(lease.lease_id.clone()),
        expected_generation: None,
        observed_at_unix_ms: Some(2_000),
        resulting_generation: Some(lease.generation),
        legacy_binding_incomplete: false,
        result_lease: Some(lease.clone()),
        result_observation: Some(ProviderLeaseObservationV1::IssueApplied {
            lease: lease.clone(),
        }),
        state: LeaseOperationStateV1::Applied,
    }
}

fn applied_renew(
    prepared: &LeaseOperationV1,
    lease: &SecretLeaseMetadataV1,
    observed_at_unix_ms: u64,
) -> LeaseOperationV1 {
    LeaseOperationV1 {
        operation_id: prepared.operation_id.clone(),
        kind: prepared.kind,
        semantic_sha256: prepared.semantic_sha256,
        lease_id: prepared.lease_id.clone(),
        expected_generation: prepared.expected_generation,
        observed_at_unix_ms: Some(observed_at_unix_ms),
        resulting_generation: Some(lease.generation),
        legacy_binding_incomplete: false,
        result_lease: Some(lease.clone()),
        result_observation: Some(ProviderLeaseObservationV1::RenewApplied {
            lease_id: lease.lease_id.clone(),
            observed_at_unix_ms,
            expires_at_unix_ms: lease.expires_at_unix_ms,
            renewable: lease.renewable,
            provider_metadata_sha256: lease.provider_metadata_sha256,
        }),
        state: LeaseOperationStateV1::Applied,
    }
}

#[tokio::test]
async fn private_owner_opens_reopens_and_binds_external_checkpoint() {
    let (_directory, path) = private_database();
    let owner = SqliteBaoOwnerV1::open(&path, None).await.unwrap();
    let checkpoint = owner.checkpoint().await.unwrap();
    assert_eq!(checkpoint.generation, 1);
    assert_ne!(checkpoint.state_sha256, [0; 32]);
    owner.close().await;

    let reopened = SqliteBaoOwnerV1::open(&path, Some(checkpoint))
        .await
        .unwrap();
    assert_eq!(reopened.checkpoint().await.unwrap(), checkpoint);
    reopened.close().await;

    let mismatch = BaoOwnerCheckpointV1 {
        generation: checkpoint.generation,
        state_sha256: [99; 32],
    };
    assert!(matches!(
        SqliteBaoOwnerV1::open(&path, Some(mismatch)).await,
        Err(SqliteBaoOwnerErrorV1::RollbackDetected)
    ));
}

#[tokio::test]
async fn owner_rejects_non_private_parent() {
    let (directory, path) = private_database();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o755))
        .unwrap_or_else(|error| panic!("relax fixture permissions: {error}"));
    assert!(matches!(
        SqliteBaoOwnerV1::open(&path, None).await,
        Err(SqliteBaoOwnerErrorV1::UnsafeStorage(_))
    ));
}

#[tokio::test]
async fn success_path_reopens_archives_and_preserves_exact_retry_identity() {
    let (_directory, path) = private_database();
    let owner = SqliteBaoOwnerV1::open(&path, None).await.unwrap();
    let claimed = owner
        .claim_consumption(consumption("operation:success"), 1_000)
        .await
        .unwrap();
    assert!(claimed.inserted);
    assert_eq!(
        claimed.record.operation.created_revision,
        claimed.record.revision
    );

    let reserved = owner
        .mark_consumption_reserved(
            "operation:success",
            claimed.record.revision,
            "reservation:success".to_owned(),
            [10; 32],
            2_000,
        )
        .await
        .unwrap();
    let fenced = owner
        .mark_consumption_dispatch_fenced("operation:success", reserved.revision, [11; 32], 3_000)
        .await
        .unwrap();
    let prepared = owner
        .prepare_consumption_delivery(
            "operation:success",
            fenced.revision,
            receipt(),
            [12; 32],
            4_000,
        )
        .await
        .unwrap();
    let succeeded = owner
        .mark_consumption_succeeded("operation:success", prepared.revision, 5_000)
        .await
        .unwrap();
    let terminal = owner
        .settle_consumption_terminal("operation:success", succeeded.revision, 6_000)
        .await
        .unwrap();
    assert_eq!(terminal.operation.state, BaoConsumptionStateV1::Succeeded);
    assert_eq!(terminal.operation.receipt, Some(receipt()));

    // Direct deletion is rejected until the archive copy exists in the same transaction.
    assert!(
        sqlx::query("DELETE FROM bao_consumption WHERE operation_id = ?")
            .bind("operation:success")
            .execute(&owner.pool)
            .await
            .is_err()
    );

    assert_eq!(
        owner
            .archive_terminal_before(6_500, 16, 7_000)
            .await
            .unwrap(),
        1
    );
    let historical = owner.consumption_result("operation:success").await.unwrap();
    assert_eq!(historical.operation, terminal.operation);

    let exact_retry = owner
        .claim_consumption(consumption("operation:success"), 8_000)
        .await
        .unwrap();
    assert!(!exact_retry.inserted);
    assert_eq!(
        exact_retry.record.operation.state,
        BaoConsumptionStateV1::Succeeded
    );

    let mut drift = consumption("operation:success");
    drift.semantic_sha256 = [88; 32];
    assert!(matches!(
        owner.claim_consumption(drift, 8_000).await,
        Err(SqliteBaoOwnerErrorV1::OperationConflict)
    ));

    let metrics = owner.metrics(8_000).await.unwrap();
    assert_eq!(metrics.operation_count, 1);
    assert_eq!(metrics.active_consumption_count, 0);
    assert_eq!(metrics.terminal_archive_count, 1);
    assert_eq!(metrics.reconciliation_queue_count, 0);
    assert_eq!(metrics.pending_quota_amount, 0);
    assert!(metrics.database_bytes > 0);
    assert!(metrics.provider_dynamic_execution_blocked);
}

#[tokio::test]
async fn same_state_recovery_observation_does_not_break_exact_transition_retry() {
    let (_directory, path) = private_database();
    let owner = SqliteBaoOwnerV1::open(&path, None).await.unwrap();
    let claim = owner
        .claim_consumption(consumption("operation:recovery"), 1_000)
        .await
        .unwrap();
    let reserved = owner
        .mark_consumption_reserved(
            "operation:recovery",
            claim.record.revision,
            "reservation:recovery".to_owned(),
            [31; 32],
            2_000,
        )
        .await
        .unwrap();
    let observed = owner
        .record_reconciliation_failure(
            "operation:recovery",
            reserved.revision,
            3_000,
            5_000,
            [32; 32],
        )
        .await
        .unwrap();

    let retry = owner
        .mark_consumption_reserved(
            "operation:recovery",
            observed.revision,
            "reservation:recovery".to_owned(),
            [31; 32],
            4_000,
        )
        .await
        .unwrap();
    assert_eq!(retry.revision, observed.revision);
    assert!(matches!(
        owner
            .mark_consumption_reserved(
                "operation:recovery",
                observed.revision,
                "reservation:recovery".to_owned(),
                [33; 32],
                4_000,
            )
            .await,
        Err(SqliteBaoOwnerErrorV1::ObservationMismatch)
    ));
    assert!(owner.due_reconciliation(4_999, 8).await.unwrap().is_empty());
    assert_eq!(owner.due_reconciliation(5_000, 8).await.unwrap().len(), 1);
}

#[tokio::test]
async fn provider_terminal_metrics_distinguish_settlement_from_observation_work() {
    let (_directory, path) = private_database();
    let owner = SqliteBaoOwnerV1::open(&path, None).await.unwrap();
    let claim = owner
        .claim_consumption(consumption("operation:provider-failed"), 1_000)
        .await
        .unwrap();
    let reserved = owner
        .mark_consumption_reserved(
            "operation:provider-failed",
            claim.record.revision,
            "reservation:provider-failed".to_owned(),
            [41; 32],
            2_000,
        )
        .await
        .unwrap();
    let fenced = owner
        .mark_consumption_dispatch_fenced(
            "operation:provider-failed",
            reserved.revision,
            [42; 32],
            3_000,
        )
        .await
        .unwrap();
    let failed = owner
        .mark_consumption_provider_failed(
            "operation:provider-failed",
            fenced.revision,
            "provider_denied".to_owned(),
            [43; 32],
            5,
            4_000,
        )
        .await
        .unwrap();

    let metrics = owner.metrics(6_000).await.unwrap();
    assert_eq!(metrics.pending_quota_amount, 5);
    assert_eq!(metrics.post_dispatch_without_receipt, 1);
    assert_eq!(metrics.observer_pending, 0);
    assert_eq!(metrics.settlement_pending, 1);
    assert_eq!(
        metrics
            .pending_by_recovery_action
            .get(&BaoConsumptionRecoveryActionV1::SettleTerminalEvidence),
        Some(&1)
    );
    assert_eq!(metrics.oldest_pending_age_ms, Some(2_000));

    owner
        .settle_consumption_terminal("operation:provider-failed", failed.revision, 7_000)
        .await
        .unwrap();
    let terminal = owner.metrics(8_000).await.unwrap();
    assert_eq!(terminal.pending_quota_amount, 0);
    assert_eq!(terminal.settlement_pending, 0);
    assert!(terminal.pending_by_state.is_empty());
}

#[tokio::test]
async fn concurrent_cas_allows_only_one_changed_reservation_identity() {
    let (_directory, path) = private_database();
    let owner = SqliteBaoOwnerV1::open(&path, None).await.unwrap();
    let claim = owner
        .claim_consumption(consumption("operation:cas"), 1_000)
        .await
        .unwrap();
    let first = owner.clone();
    let second = owner.clone();
    let revision = claim.record.revision;
    let (left, right) = tokio::join!(
        first.mark_consumption_reserved(
            "operation:cas",
            revision,
            "reservation:cas:left".to_owned(),
            [51; 32],
            2_000,
        ),
        second.mark_consumption_reserved(
            "operation:cas",
            revision,
            "reservation:cas:right".to_owned(),
            [52; 32],
            2_000,
        )
    );
    let successes = usize::from(left.is_ok()) + usize::from(right.is_ok());
    assert_eq!(successes, 1);
    let failure = if left.is_err() { left } else { right };
    assert!(matches!(
        failure,
        Err(SqliteBaoOwnerErrorV1::RevisionConflict)
            | Err(SqliteBaoOwnerErrorV1::OperationConflict)
    ));
}

#[tokio::test]
async fn lease_issue_retry_and_generation_cas_preserve_original_result() {
    let (_directory, path) = private_database();
    let owner = SqliteBaoOwnerV1::open(&path, None).await.unwrap();
    let prepared = prepared_issue("operation:lease:issue");
    let claimed = owner
        .claim_lease_operation(prepared.clone(), 1_000)
        .await
        .unwrap();
    let unknown = owner
        .mark_lease_operation_unknown(&prepared.operation_id, claimed.revision, [61; 32], 1_500)
        .await
        .unwrap();
    let retried = owner
        .claim_lease_operation(prepared.clone(), 1_600)
        .await
        .unwrap();
    assert_eq!(retried.operation.state, LeaseOperationStateV1::Unknown);

    let lease_v1 = active_lease(1, 60_000);
    let applied = applied_issue(&prepared, &lease_v1);
    let result = owner
        .apply_lease_operation(
            applied.clone(),
            Some(lease_v1.clone()),
            unknown.revision,
            [62; 32],
            2_000,
        )
        .await
        .unwrap();
    assert_eq!(result.operation.state, LeaseOperationStateV1::Applied);
    assert_eq!(
        owner.lease(&lease_v1.lease_id).await.unwrap(),
        Some(lease_v1.clone())
    );

    let historical_retry = owner.claim_lease_operation(prepared, 2_100).await.unwrap();
    assert_eq!(historical_retry.operation, applied);

    let renew = prepared_mutation("operation:lease:renew", LeaseOperationKindV1::Renew, 1);
    let renew_claim = owner
        .claim_lease_operation(renew.clone(), 3_000)
        .await
        .unwrap();
    let lease_v2 = active_lease(2, 120_000);
    let renewed = owner
        .apply_lease_operation(
            applied_renew(&renew, &lease_v2, 4_000),
            Some(lease_v2.clone()),
            renew_claim.revision,
            [63; 32],
            4_000,
        )
        .await
        .unwrap();
    assert_eq!(renewed.operation.resulting_generation, Some(2));
    assert_eq!(
        owner.lease(&lease_v2.lease_id).await.unwrap(),
        Some(lease_v2)
    );

    let stale = prepared_mutation("operation:lease:stale", LeaseOperationKindV1::Renew, 1);
    let stale_claim = owner
        .claim_lease_operation(stale.clone(), 5_000)
        .await
        .unwrap();
    assert!(matches!(
        owner
            .apply_lease_operation(
                applied_renew(&stale, &active_lease(2, 180_000), 6_000),
                Some(active_lease(2, 180_000)),
                stale_claim.revision,
                [64; 32],
                6_000,
            )
            .await,
        Err(SqliteBaoOwnerErrorV1::ObservationMismatch)
    ));
}

#[tokio::test]
async fn live_schema_tampering_is_rejected_on_reopen() {
    let (_directory, path) = private_database();
    let owner = SqliteBaoOwnerV1::open(&path, None).await.unwrap();
    owner.close().await;
    let pool = codex_state_sqlite::open_durable_authority_pool(&path)
        .await
        .unwrap();
    sqlx::query("CREATE TABLE rogue_table(value INTEGER NOT NULL) STRICT")
        .execute(&pool)
        .await
        .unwrap();
    pool.close().await;
    assert!(matches!(
        SqliteBaoOwnerV1::open(&path, None).await,
        Err(SqliteBaoOwnerErrorV1::CorruptState(
            "live owner schema differs from compiled migrations"
        ))
    ));
}

#[test]
fn secret_digests_are_not_rendered_by_debug() {
    let request = consumption("operation:debug");
    let rendered = format!("{request:?}");
    assert!(rendered.contains("[SENSITIVE DIGEST]"));
    assert!(!rendered.contains("1, 1, 1"));
    let rendered_receipt = format!("{:?}", receipt());
    assert!(rendered_receipt.contains("[SENSITIVE DIGEST]"));
    assert!(!rendered_receipt.contains("6, 6, 6"));
}

#[tokio::test]
async fn reference_snapshot_import_is_atomic_idempotent_and_preserves_legacy_history() {
    let (_directory, path) = private_database();
    let owner = SqliteBaoOwnerV1::open(&path, None).await.unwrap();
    let lease = active_lease(1, 60_000);
    let legacy_operation = LeaseOperationV1 {
        operation_id: "operation:legacy:issue".to_owned(),
        kind: LeaseOperationKindV1::Issue,
        semantic_sha256: [71; 32],
        lease_id: Some(lease.lease_id.clone()),
        expected_generation: None,
        observed_at_unix_ms: None,
        resulting_generation: None,
        legacy_binding_incomplete: true,
        result_lease: None,
        result_observation: None,
        state: LeaseOperationStateV1::Applied,
    };
    let mut pending = consumption("operation:import:pending");
    pending.created_revision = 7;
    pending.updated_revision = 7;
    let snapshot = LeaseRegistryMigrationSnapshotV1 {
        schema_version: 4,
        revision: 7,
        time_frontier_unix_ms: 900,
        operations: vec![legacy_operation.clone()],
        leases: vec![lease.clone()],
        consumptions: vec![pending.clone()],
    };

    let receipt = owner
        .import_reference_snapshot(&snapshot, 1_000)
        .await
        .unwrap();
    assert_eq!(receipt.source_revision, 7);
    assert_ne!(receipt.source_sha256, [0; 32]);
    assert_eq!(receipt.imported_at_unix_ms, 1_000);
    assert_eq!(owner.lease(&lease.lease_id).await.unwrap(), Some(lease));
    assert_eq!(
        owner
            .consumption_result(&pending.operation_id)
            .await
            .unwrap()
            .operation
            .state,
        BaoConsumptionStateV1::Claimed
    );
    let imported_legacy: Vec<u8> =
        sqlx::query_scalar("SELECT row_json FROM bao_lease_operation WHERE operation_id = ?")
            .bind(&legacy_operation.operation_id)
            .fetch_one(&owner.pool)
            .await
            .unwrap();
    assert_eq!(
        serde_json::from_slice::<LeaseOperationV1>(&imported_legacy).unwrap(),
        legacy_operation
    );

    let retry = owner
        .import_reference_snapshot(&snapshot, 2_000)
        .await
        .unwrap();
    assert_eq!(retry, receipt);

    let mut drift = snapshot.clone();
    drift.revision = 8;
    assert!(matches!(
        owner.import_reference_snapshot(&drift, 2_000).await,
        Err(SqliteBaoOwnerErrorV1::MigrationConflict)
    ));

    let rendered = format!("{receipt:?}");
    assert!(rendered.contains("[SENSITIVE DIGEST]"));
    assert!(!rendered.contains("71, 71, 71"));
}

#[tokio::test]
async fn reconciliation_claims_are_cross_process_fenced_expiring_and_observable() {
    let (_directory, path) = private_database();
    let owner = SqliteBaoOwnerV1::open(&path, None).await.unwrap();
    let claimed = owner
        .claim_consumption(consumption("operation:recovery-claim"), 1_000)
        .await
        .unwrap();
    let checkpoint_before_claim = owner.checkpoint().await.unwrap();

    let first = owner
        .claim_due_reconciliation("worker:first", 1_000, 100, 8)
        .await
        .unwrap();
    assert_eq!(first.len(), 1);
    assert_eq!(first[0].claim_generation, 1);
    assert_eq!(first[0].claim_until_unix_ms, 1_100);
    assert!(
        owner
            .claim_due_reconciliation("worker:second", 1_050, 100, 8)
            .await
            .unwrap()
            .is_empty()
    );
    assert!(matches!(
        owner
            .record_reconciliation_failure(
                "operation:recovery-claim",
                claimed.record.revision,
                1_050,
                2_000,
                [72; 32],
            )
            .await,
        Err(SqliteBaoOwnerErrorV1::WriterBusy)
    ));
    assert!(matches!(
        owner
            .record_claimed_reconciliation_failure(
                &SqliteReconciliationClaimV1 {
                    worker_id: "worker:second".to_owned(),
                    ..first[0].clone()
                },
                1_050,
                2_000,
                [72; 32],
            )
            .await,
        Err(SqliteBaoOwnerErrorV1::WriterBusy)
    ));

    let rescheduled = owner
        .record_claimed_reconciliation_failure(&first[0], 1_050, 2_000, [72; 32])
        .await
        .unwrap();
    assert_eq!(rescheduled.operation.state, BaoConsumptionStateV1::Claimed);
    let metrics = owner.metrics(1_500).await.unwrap();
    assert_eq!(metrics.claimed_reconciliation_count, 0);
    assert_eq!(metrics.oldest_due_reconciliation_age_ms, None);
    assert_eq!(metrics.max_reconciliation_attempts, 1);
    assert!(metrics.runtime.confirmed_transactions >= 3);

    let checkpoint_before_second_claim = owner.checkpoint().await.unwrap();
    let second = owner
        .claim_due_reconciliation("worker:second", 2_000, 100, 8)
        .await
        .unwrap();
    assert_eq!(second.len(), 1);
    assert_eq!(second[0].claim_generation, 2);
    assert!(matches!(
        owner
            .release_reconciliation_claim(
                "worker:first",
                "operation:recovery-claim",
                first[0].claim_generation,
            )
            .await,
        Err(SqliteBaoOwnerErrorV1::WriterBusy)
    ));
    owner
        .release_reconciliation_claim(
            "worker:second",
            "operation:recovery-claim",
            second[0].claim_generation,
        )
        .await
        .unwrap();

    // Claim ownership is operational coordination, not an authoritative fact.
    assert_ne!(checkpoint_before_second_claim, checkpoint_before_claim);
    assert_eq!(
        owner.checkpoint().await.unwrap(),
        checkpoint_before_second_claim
    );
}

#[tokio::test]
async fn checkpoint_publication_is_cas_bound_and_failure_fences_the_writer() {
    let (_directory, path) = private_database();
    let owner = SqliteBaoOwnerV1::open(&path, None).await.unwrap();
    let expected = owner.checkpoint().await.unwrap();
    let published = owner
        .publish_checkpoint_with(Some(expected), |previous, current| async move {
            assert_eq!(previous, Some(expected));
            assert_eq!(current, expected);
            Ok::<(), ()>(())
        })
        .await
        .unwrap();
    assert_eq!(published, expected);
    assert!(!owner.is_fenced());

    let failure = owner
        .publish_checkpoint_with(Some(expected), |_previous, _current| async {
            Err::<(), ()>(())
        })
        .await;
    assert!(matches!(
        failure,
        Err(SqliteBaoOwnerErrorV1::ExternalCheckpointUnavailable)
    ));
    assert!(owner.is_fenced());
    assert!(matches!(
        owner
            .claim_consumption(consumption("operation:fenced"), 2_000)
            .await,
        Err(SqliteBaoOwnerErrorV1::Fenced)
    ));
    let metrics = owner.metrics(2_000).await.unwrap();
    assert!(metrics.runtime.writer_fence_events >= 1);
}

#[tokio::test]
async fn compiled_schema_is_v2_and_contains_recovery_claims_and_import_receipt() {
    let (_directory, path) = private_database();
    let owner = SqliteBaoOwnerV1::open(&path, None).await.unwrap();
    let schema_version: i64 =
        sqlx::query_scalar("SELECT schema_version FROM bao_owner_meta WHERE singleton = 1")
            .fetch_one(&owner.pool)
            .await
            .unwrap();
    assert_eq!(schema_version, 2);
    let claim_generation_column: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM pragma_table_info('bao_reconciliation_queue')
         WHERE name = 'claim_generation'",
    )
    .fetch_one(&owner.pool)
    .await
    .unwrap();
    assert_eq!(claim_generation_column, 1);
    let receipt_table: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM sqlite_schema WHERE type = 'table' AND name = 'bao_reference_import'",
    )
    .fetch_one(&owner.pool)
    .await
    .unwrap();
    assert_eq!(receipt_table, 1);
}
