//! Regression at the public SQLite recovery runtime boundary: queued work
//! receives its recovery lease only when the serial worker can process it.

use super::*;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseApprovalVerifier;
use codex_hepta_contracts::FinalUseRevocationFeedVerifier;
use pretty_assertions::assert_eq;
use sqlx::Row;

struct AdvancingRecoveryClock(AtomicU64);

impl AuthorityClock for AdvancingRecoveryClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        // Each observed step consumes part of a 100 ms lease. Two serial
        // reschedules cannot share a lease issued before the first step.
        Ok(self.0.fetch_add(60, Ordering::SeqCst))
    }
}

#[tokio::test]
async fn serial_recovery_gives_each_operation_a_fresh_lease()
-> Result<(), Box<dyn std::error::Error>> {
    let certificate = rcgen::generate_simple_self_signed(vec!["localhost".into()]).unwrap();
    let client = BaoClient::new(
        "https://localhost/",
        certificate.cert.pem().as_bytes(),
        BaoToken::new("fixture-recovery-token".into()).unwrap(),
        Duration::from_secs(2),
    )
    .unwrap();
    let request = read_request();
    let (_authbus_db, _checkpoint, authbus, mut evidence, _admission) =
        authbus_host(&client, &request, 2_000).await.unwrap();
    let (authority, _grant, _authority_root) = grant(&client, &request).unwrap();
    let host = Arc::new(
        crate::BaoFinalUseHost::new(
            authority,
            FinalUseApprovalVerifier::new(
                "bao-recovery-approver".into(),
                SigningKey::from_bytes(&[91; 32]).verifying_key().to_bytes(),
            )
            .unwrap(),
            FinalUseRevocationFeedVerifier::new(
                "bao-recovery-distributor".into(),
                SigningKey::from_bytes(&[92; 32]).verifying_key().to_bytes(),
            )
            .unwrap(),
            Arc::new(AdvancingRecoveryClock(AtomicU64::new(2_000))),
            [crate::RegisteredBaoConsumer::for_operations(
                "model-provider".into(),
                [93; 32],
                Arc::new(|_, _, _| panic!("recovery must never re-enter a consumer")),
                Arc::new(|_, _| Ok(crate::BaoConsumerObservationV1::Unknown)),
            )
            .unwrap()],
        )
        .unwrap(),
    );
    let owner_root = tempfile::tempdir().unwrap();
    std::fs::set_permissions(owner_root.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let path = owner_root.path().join("recovery-owner.sqlite");
    let owner = Arc::new(crate::SqliteBaoOwnerV1::open(&path, None).await.unwrap());
    for operation_id in ["operation:recovery-first", "operation:recovery-second"] {
        owner
            .claim_consumption(
                crate::BaoConsumptionOperationV1 {
                    operation_id: operation_id.to_owned(),
                    semantic_sha256: [1; 32],
                    effect_sha256: [2; 32],
                    request_sha256: [3; 32],
                    // A temporarily unavailable enrollment is a recoverable product
                    // condition; preserve both operations and release their claims.
                    consumer_id: "temporarily-unregistered-consumer".into(),
                    consumer_configuration_sha256: [4; 32],
                    amount: 1,
                    reservation_id: None,
                    state: crate::BaoConsumptionStateV1::Claimed,
                    receipt: None,
                    created_revision: 0,
                    updated_revision: 0,
                    terminal_kind: None,
                    terminal_code: None,
                    terminal_evidence_sha256: None,
                    terminal_observed_cost: None,
                },
                2_000,
            )
            .await
            .unwrap();
    }
    let runtime = crate::SqliteBaoProductRuntimeV1::new(
        host,
        Arc::clone(&owner),
        crate::BaoSqliteProductRuntimeConfigV1 {
            recovery_lease_ms: 100,
            recovery_batch_limit: 2,
            ..Default::default()
        },
    )
    .unwrap();

    assert_eq!(
        runtime
            .reconcile_due(&authbus, &mut evidence)
            .await
            .unwrap(),
        crate::BaoRecoveryBatchReportV1 {
            claimed: 2,
            succeeded: 0,
            terminal_failed: 0,
            rescheduled: 2,
        },
    );
    for operation_id in ["operation:recovery-first", "operation:recovery-second"] {
        let operation = owner
            .consumption_result(operation_id)
            .await
            .unwrap()
            .operation;
        assert_eq!(
            (
                operation.state,
                operation.reservation_id,
                operation.receipt,
                operation.terminal_code
            ),
            (crate::BaoConsumptionStateV1::Claimed, None, None, None),
        );
    }
    let projection = codex_state::SqliteConfig::from_sqlite_home(
        codex_utils_absolute_path::AbsolutePathBuf::try_from(
            path.parent()
                .ok_or(std::io::Error::new(
                    std::io::ErrorKind::InvalidInput,
                    "owner parent",
                ))?
                .to_path_buf(),
        )?,
    )
    .open_durable_evidence_pool(&path)
    .await
    .expect("the registered SQLite shim opens the recovery test projection");
    let rows = sqlx::query(
        "SELECT claim_owner, claim_generation, attempt_count FROM bao_reconciliation_queue ORDER BY operation_id",
    ).fetch_all(&projection).await.unwrap();
    let observed = rows
        .iter()
        .map(|row| {
            (
                row.try_get::<Option<String>, _>("claim_owner").unwrap(),
                row.try_get::<Vec<u8>, _>("claim_generation").unwrap(),
                row.try_get::<Vec<u8>, _>("attempt_count").unwrap(),
            )
        })
        .collect::<Vec<_>>();
    assert_eq!(
        observed,
        vec![
            (
                None,
                1_u64.to_be_bytes().to_vec(),
                1_u64.to_be_bytes().to_vec()
            );
            2
        ]
    );
    projection.close().await;
    Ok(())
}
