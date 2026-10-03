use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
use std::sync::Arc;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_contracts::authority_lease::AuthorityLeaseFrontier;
use codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry;
use pretty_assertions::assert_eq;

use super::*;
use crate::DurableLeaseDispositionV1;
use crate::HostObservation;
use crate::ResourceVectorV1;
use crate::durable_rows::encode_json;

#[derive(Debug)]
struct Clock;

impl AuthorityClock for Clock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(2_000)
    }
}

struct Fixture {
    _directory: tempfile::TempDir,
    database: PathBuf,
    store: DurableFleetStore,
    registry: AuthorityLeaseRegistry,
    authority: FleetAuthorityPort,
    issued: FleetOperationReceiptV1,
    context: FleetExecutionContextV1,
}

impl Fixture {
    async fn open() -> Result<Self, Box<dyn std::error::Error>> {
        let directory = tempfile::tempdir()?;
        let database = directory.path().join("fleet.sqlite3");
        let store = DurableFleetStore::open_with_clock(&database, Arc::new(Clock)).await?;
        let root = directory.path().join("authority");
        std::fs::create_dir(&root)?;
        std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700))?;
        let registry = AuthorityLeaseRegistry::open_state_dir_with_clock(
            &root,
            "resource-owner".into(),
            AuthorityLeaseFrontier::for_empty_epoch(/*authority_epoch*/ 7)?,
            Arc::new(Clock),
        )?;
        let authority = FleetAuthorityPort::new(registry.verifier());
        let resources = ResourceVectorV1 {
            cpu_millis: 1_000,
            memory_bytes: 1 << 20,
            concurrent_turns: 1,
            tool_processes: 1,
            turn_queue_slots: 1,
            ..ResourceVectorV1::default()
        };
        store
            .observe_host(
                &HostObservation {
                    host_id: "host".into(),
                    failure_domain_id: "rack".into(),
                    generation: 1,
                    observed_at_ms: 1_000,
                    valid_until_ms: 20_000,
                    capacity: resources,
                },
                "native-test-observer",
            )
            .await?;
        let grant = AllocationGrant {
            allocation_id: "allocation".into(),
            request_id: "request".into(),
            principal_id: "agent".into(),
            host_id: "host".into(),
            failure_domain_id: "rack".into(),
            host_generation: 1,
            authority_epoch: 7,
            lease_generation: 1,
            expires_at_ms: 10_000,
            resources,
            semantic_digest: "a".repeat(64),
            revoked: false,
        };
        put_lease(
            &registry,
            "issue",
            FleetAuthorityPort::binding_for_issue(&grant)?,
        )?;
        let issued = store
            .issue_authorized(
                &authority,
                "issue",
                /*expected_authority_revision*/ 1,
                grant.clone(),
            )
            .await?
            .operation;
        let context = FleetExecutionContextV1 {
            execution_id: "execution".into(),
            allocation_id: grant.allocation_id,
            principal_id: grant.principal_id,
            host_id: grant.host_id,
            host_generation: 1,
            lease_generation: 1,
            manifest_digest: grant.semantic_digest,
            resources,
            containment: "fixture-no-native-launch".into(),
        };
        // Only the SQLite transaction owner is exercised here. Physical PID/
        // cgroup preparation, bind and exit remain separate native host tests.
        sqlx::query("INSERT INTO fleet_execution_holds(execution_id, allocation_id, host_id, boot_identity, context_json, state, prepared_at_ms, containment_dev, containment_ino) VALUES('execution', 'allocation', 'host', 'fixture-boot', ?, 'running', 2000, 0, 0)")
            .bind(encode_json(&context)?).execute(&store.pool).await?;
        Ok(Self {
            _directory: directory,
            database,
            store,
            registry,
            authority,
            issued,
            context,
        })
    }

    async fn stage(
        &self,
        suffix: u64,
    ) -> Result<FleetOperationReceiptV1, Box<dyn std::error::Error>> {
        let grant = self
            .store
            .allocation_grant("allocation")
            .await?
            .ok_or("missing grant")?;
        let lease = format!("renew-{suffix}");
        put_lease(
            &self.registry,
            &lease,
            FleetAuthorityPort::binding_for_renew(&grant, /*expires_at_ms*/ 15_000)?,
        )?;
        Ok(self
            .store
            .stage_local_renewal_authorized(
                &self.authority,
                &lease,
                /*expected_authority_revision*/ 1,
                "execution",
                unobserved_request(&grant, /*expires_at_ms*/ 15_000),
            )
            .await?)
    }

    async fn receipt_count(&self) -> Result<i64, sqlx::Error> {
        sqlx::query_scalar("SELECT COUNT(*) FROM fleet_operation_receipts WHERE operation_id LIKE 'fleet:local_renew:%'")
            .fetch_one(&self.store.pool).await
    }
}

fn unobserved_request(
    expected_grant: &AllocationGrant,
    expires_at_ms: u64,
) -> LocalRenewalRequestV1<'_> {
    LocalRenewalRequestV1 {
        expected_grant,
        expires_at_ms,
        observed_pending: None,
    }
}

fn put_lease(
    registry: &AuthorityLeaseRegistry,
    id: &str,
    binding: AuthorityLeaseBinding,
) -> Result<(), Box<dyn std::error::Error>> {
    registry.put_lease(
        AuthorityLease {
            schema_version: 1,
            lease_id: id.into(),
            authority_epoch: 7,
            revision: 1,
            binding,
            issued_at_unix_ms: 1_000,
            expires_at_unix_ms: 20_000,
        },
        /*expected_revision*/ 0,
    )?;
    Ok(())
}

#[tokio::test]
async fn commit_before_observation_survives_reopen_and_blocks_next_renewal()
-> Result<(), Box<dyn std::error::Error>> {
    let mut fixture = Fixture::open().await?;
    let original = fixture.stage(/*suffix*/ 0).await?;
    fixture.store.close().await;
    fixture.store = DurableFleetStore::open_with_clock(&fixture.database, Arc::new(Clock)).await?;
    let current = fixture
        .store
        .allocation_grant("allocation")
        .await?
        .ok_or("missing grant")?;
    assert_eq!(current.lease_generation, 2);
    assert_eq!(
        fixture
            .store
            .stage_local_renewal_authorized(
                &fixture.authority,
                "not-authorized",
                /*expected_authority_revision*/ 1,
                "execution",
                unobserved_request(&current, /*expires_at_ms*/ 16_000)
            )
            .await,
        Err(DurableFleetError::IndeterminateCommit {
            operation_id: original.operation_id.clone(),
            subject_id: "allocation".into()
        })
    );
    let observed = fixture
        .store
        .pending_local_renewal("execution")
        .await?
        .ok_or("missing original")?;
    assert_eq!(observed, original);
    // A valid observation followed by failed new authority must roll back the
    // acknowledgement too; the original unknown obligation cannot disappear.
    let failed = fixture
        .store
        .stage_local_renewal_authorized(
            &fixture.authority,
            "not-authorized",
            /*expected_authority_revision*/ 1,
            "execution",
            LocalRenewalRequestV1 {
                expected_grant: &current,
                expires_at_ms: 16_000,
                observed_pending: Some(&observed),
            },
        )
        .await;
    assert!(matches!(failed, Err(DurableFleetError::Authority(_))));
    assert_eq!(
        fixture.store.pending_local_renewal("execution").await?,
        Some(original.clone())
    );
    let mut substituted = observed.clone();
    substituted.committed_at_ms += 1;
    assert_eq!(
        fixture
            .store
            .acknowledge_local_renewal("execution", &substituted)
            .await,
        Err(DurableFleetError::Conflict(original.operation_id.clone()))
    );
    assert_eq!(
        fixture.store.pending_local_renewal("execution").await?,
        Some(original.clone())
    );
    fixture
        .store
        .acknowledge_local_renewal("execution", &observed)
        .await?;
    fixture
        .store
        .acknowledge_local_renewal("execution", &observed)
        .await?;
    assert_eq!(
        fixture.store.pending_local_renewal("execution").await?,
        None
    );
    let next = fixture.stage(/*suffix*/ 1).await?;
    assert_eq!(fixture.receipt_count().await?, 2);
    assert_eq!(
        fixture
            .store
            .operation_receipt(&original.operation_id)
            .await?,
        Some(original)
    );
    fixture
        .store
        .acknowledge_local_renewal("execution", &next)
        .await?;
    assert_eq!(fixture.receipt_count().await?, 1);
    Ok(())
}

#[tokio::test]
async fn acknowledged_upkeep_is_bounded_and_generic_receipts_survive_retirement()
-> Result<(), Box<dyn std::error::Error>> {
    let fixture = Fixture::open().await?;
    let grant = fixture
        .store
        .allocation_grant("allocation")
        .await?
        .ok_or("grant")?;
    put_lease(
        &fixture.registry,
        "external-renew",
        FleetAuthorityPort::binding_for_renew(&grant, /*expires_at_ms*/ 12_000)?,
    )?;
    let generic = fixture
        .store
        .mutate_lease_authorized(
            &fixture.authority,
            "external-renew",
            /*expected_authority_revision*/ 1,
            "allocation",
            grant.lease_generation,
            /*authority_epoch*/ 7,
            &grant.semantic_digest,
            DurableLeaseDispositionV1::Renew {
                expires_at_ms: 12_000,
            },
        )
        .await?;
    for generation in 0..96 {
        let observed = fixture.store.pending_local_renewal("execution").await?;
        let grant = fixture
            .store
            .allocation_grant("allocation")
            .await?
            .ok_or("grant")?;
        let lease = format!("steady-renew-{generation}");
        put_lease(
            &fixture.registry,
            &lease,
            FleetAuthorityPort::binding_for_renew(&grant, /*expires_at_ms*/ 15_000)?,
        )?;
        fixture
            .store
            .stage_local_renewal_authorized(
                &fixture.authority,
                &lease,
                /*expected_authority_revision*/ 1,
                "execution",
                LocalRenewalRequestV1 {
                    expected_grant: &grant,
                    expires_at_ms: 15_000,
                    observed_pending: observed.as_ref(),
                },
            )
            .await?;
        assert!(fixture.receipt_count().await? <= 2);
    }
    let pending = fixture
        .store
        .pending_local_renewal("execution")
        .await?
        .ok_or("pending")?;
    let grant = fixture
        .store
        .allocation_grant("allocation")
        .await?
        .ok_or("grant")?;
    put_lease(
        &fixture.registry,
        "revoke",
        FleetAuthorityPort::binding_for_revoke(&grant)?,
    )?;
    let revoked = fixture
        .store
        .mutate_lease_authorized(
            &fixture.authority,
            "revoke",
            /*expected_authority_revision*/ 1,
            "allocation",
            grant.lease_generation,
            /*authority_epoch*/ 7,
            &grant.semantic_digest,
            DurableLeaseDispositionV1::Revoke,
        )
        .await?;
    assert_eq!(
        fixture.store.pending_local_renewal("execution").await?,
        Some(pending.clone())
    );
    assert_eq!(
        fixture.store.pending_executions().await?[0].state,
        "stop_requested"
    );
    let resources = fixture.store.metrics().await?.host_resources;
    assert_eq!(resources[0].reserved, fixture.context.resources);
    for receipt in [&fixture.issued, &generic, &revoked] {
        assert_eq!(
            fixture
                .store
                .operation_receipt(&receipt.operation_id)
                .await?,
            Some(receipt.clone())
        );
    }
    fixture
        .store
        .acknowledge_local_renewal("execution", &pending)
        .await?;
    assert_eq!(fixture.receipt_count().await?, 1);
    assert_eq!(
        fixture.store.pending_executions().await?[0].state,
        "stop_requested"
    );
    Ok(())
}

#[tokio::test]
async fn v2_active_hold_migrates_additively_without_losing_identity_or_receipts()
-> Result<(), Box<dyn std::error::Error>> {
    let mut fixture = Fixture::open().await?;
    let before = fixture.store.pending_executions().await?;
    sqlx::query("ALTER TABLE fleet_execution_holds DROP COLUMN local_renewal_pending_operation_id")
        .execute(&fixture.store.pool)
        .await?;
    sqlx::query(
        "ALTER TABLE fleet_execution_holds DROP COLUMN local_renewal_confirmed_operation_id",
    )
    .execute(&fixture.store.pool)
    .await?;
    sqlx::query("UPDATE fleet_schema SET schema_version = 2")
        .execute(&fixture.store.pool)
        .await?;
    fixture.store.close().await;
    fixture.store = DurableFleetStore::open_with_clock(&fixture.database, Arc::new(Clock)).await?;
    assert_eq!(fixture.store.pending_executions().await?, before);
    assert_eq!(
        fixture
            .store
            .operation_receipt(&fixture.issued.operation_id)
            .await?,
        Some(fixture.issued.clone())
    );
    assert_eq!(
        fixture.store.pending_local_renewal("execution").await?,
        None
    );
    let observed = fixture.stage(/*suffix*/ 0).await?;
    fixture
        .store
        .acknowledge_local_renewal("execution", &observed)
        .await?;
    Ok(())
}

#[tokio::test]
async fn independent_connections_cannot_overwrite_a_pending_obligation()
-> Result<(), Box<dyn std::error::Error>> {
    let fixture = Fixture::open().await?;
    let other = DurableFleetStore::open_with_clock(&fixture.database, Arc::new(Clock)).await?;
    let current = fixture
        .store
        .allocation_grant("allocation")
        .await?
        .ok_or("grant")?;
    put_lease(
        &fixture.registry,
        "race",
        FleetAuthorityPort::binding_for_renew(&current, /*expires_at_ms*/ 15_000)?,
    )?;
    let (one, two) = tokio::join!(
        fixture.store.stage_local_renewal_authorized(
            &fixture.authority,
            "race",
            /*expected_authority_revision*/ 1,
            "execution",
            unobserved_request(&current, /*expires_at_ms*/ 15_000)
        ),
        other.stage_local_renewal_authorized(
            &fixture.authority,
            "race",
            /*expected_authority_revision*/ 1,
            "execution",
            unobserved_request(&current, /*expires_at_ms*/ 15_000)
        ),
    );
    let original = match (one, two) {
        (Ok(receipt), Err(DurableFleetError::IndeterminateCommit { operation_id, .. }))
        | (Err(DurableFleetError::IndeterminateCommit { operation_id, .. }), Ok(receipt)) => {
            assert_eq!(operation_id, receipt.operation_id);
            receipt
        }
        outcomes => return Err(format!("unexpected concurrent outcomes: {outcomes:?}").into()),
    };
    assert_eq!(
        other.pending_local_renewal("execution").await?,
        Some(original.clone())
    );
    assert_eq!(fixture.receipt_count().await?, 1);
    let (one, two) = tokio::join!(
        fixture
            .store
            .acknowledge_local_renewal("execution", &original),
        other.acknowledge_local_renewal("execution", &original)
    );
    one?;
    two?;
    Ok(())
}

#[tokio::test]
async fn corrupt_original_receipt_keeps_pending_id_and_fails_closed()
-> Result<(), Box<dyn std::error::Error>> {
    let fixture = Fixture::open().await?;
    let original = fixture.stage(/*suffix*/ 0).await?;
    sqlx::query("UPDATE fleet_execution_holds SET local_renewal_confirmed_operation_id = ?")
        .bind(&original.operation_id)
        .execute(&fixture.store.pool)
        .await?;
    assert!(matches!(
        fixture
            .store
            .acknowledge_local_renewal("execution", &original)
            .await,
        Err(DurableFleetError::Corrupt(_))
    ));
    assert_eq!(
        fixture
            .store
            .operation_receipt(&original.operation_id)
            .await?,
        Some(original.clone())
    );
    sqlx::query("UPDATE fleet_execution_holds SET local_renewal_confirmed_operation_id = NULL")
        .execute(&fixture.store.pool)
        .await?;
    sqlx::query("DELETE FROM fleet_operation_receipts WHERE operation_id = ?")
        .bind(&original.operation_id)
        .execute(&fixture.store.pool)
        .await?;
    assert!(matches!(
        fixture.store.pending_local_renewal("execution").await,
        Err(DurableFleetError::Corrupt(_))
    ));
    assert!(matches!(
        fixture
            .store
            .acknowledge_local_renewal("execution", &original)
            .await,
        Err(DurableFleetError::Corrupt(_))
    ));
    let current = fixture
        .store
        .allocation_grant("allocation")
        .await?
        .ok_or("grant")?;
    assert_eq!(
        fixture
            .store
            .stage_local_renewal_authorized(
                &fixture.authority,
                "missing",
                /*expected_authority_revision*/ 1,
                "execution",
                unobserved_request(&current, /*expires_at_ms*/ 16_000)
            )
            .await,
        Err(DurableFleetError::IndeterminateCommit {
            operation_id: original.operation_id,
            subject_id: "allocation".into()
        })
    );
    Ok(())
}
