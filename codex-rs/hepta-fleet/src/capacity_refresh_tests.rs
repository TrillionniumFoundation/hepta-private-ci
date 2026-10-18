use super::*;
use crate::FleetExecutionContextV1;
use crate::LocalCapacityObserver;
use crate::LocalCapacityObserverConfig;
use crate::capacity_refresh::MAX_HOST_CAPACITY_SNAPSHOTS;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn same_boot_pressure_refresh_preserves_live_grants_and_exact_receipts_after_reload() {
    let directory = tempfile::tempdir().expect("directory");
    let path = directory.path().join("fleet.sqlite3");
    let clock = Arc::new(ManualClock::new(2_000));
    let store = DurableFleetStore::open_with_clock(&path, clock.clone())
        .await
        .expect("store");
    let generation = store.register_local_boot("host-one").await.expect("boot");
    let first = host(generation, 1_900);
    store
        .observe_host(&first, "pressure-owner")
        .await
        .expect("first snapshot");
    let registry = authority_registry(&directory.path().join("authority"), clock.clone());
    let held = grant("held", 7_000);
    put_lease(
        &registry,
        "issue-held",
        FleetAuthorityPort::binding_for_issue(&held).expect("binding"),
    );
    store
        .issue_authorized(
            &FleetAuthorityPort::new(registry.verifier()),
            "issue-held",
            1,
            held.clone(),
        )
        .await
        .expect("authorized grant");
    let mut latest = first;
    let mut last_receipt = None;
    for round in 0..8 {
        let now = 2_100 + round * 10;
        clock.set(now);
        latest.observed_at_ms = now;
        latest.capacity.cpu_millis = 100; // Pressure below the already reserved amount.
        let receipt = store
            .observe_host(&latest, "pressure-owner")
            .await
            .expect("refresh");
        assert!(receipt.authority_witness.is_none());
        assert_ne!(last_receipt.as_ref(), Some(&receipt));
        assert_eq!(
            store
                .observe_host(&latest, "pressure-owner")
                .await
                .expect("exact retry"),
            receipt
        );
        assert_eq!(
            store
                .register_local_boot("host-one")
                .await
                .expect("stable boot"),
            generation
        );
        assert_eq!(
            store.metrics().await.expect("metrics").host_resources[0].reserved,
            held.resources
        );
        store
            .verify_use(
                "held",
                "agent-one",
                "host-one",
                generation,
                1,
                &held.semantic_digest,
            )
            .await
            .expect("grant not fenced by sampling");
        last_receipt = Some(receipt);
    }
    let denied = grant("capacity-denied", 7_000);
    put_lease(
        &registry,
        "issue-denied",
        FleetAuthorityPort::binding_for_issue(&denied).expect("binding"),
    );
    assert_eq!(
        store
            .issue_authorized(
                &FleetAuthorityPort::new(registry.verifier()),
                "issue-denied",
                1,
                denied
            )
            .await,
        Err(DurableFleetError::Capacity)
    );
    let mut drift = latest.clone();
    drift.valid_until_ms += 1;
    assert!(matches!(
        store.observe_host(&drift, "pressure-owner").await,
        Err(DurableFleetError::Conflict(_))
    ));
    drift = latest.clone();
    drift.observed_at_ms -= 1;
    assert_eq!(
        store.observe_host(&drift, "pressure-owner").await,
        Err(DurableFleetError::Stale)
    );
    drift = latest.clone();
    drift.failure_domain_id = "another-rack".into();
    drift.observed_at_ms += 1;
    clock.set(drift.observed_at_ms);
    assert!(matches!(
        store.observe_host(&drift, "pressure-owner").await,
        Err(DurableFleetError::Conflict(_))
    ));
    store.close().await;
    let reopened = DurableFleetStore::open_with_clock(&path, clock)
        .await
        .expect("reopen");
    assert_eq!(
        reopened
            .observe_host(&latest, "pressure-owner")
            .await
            .expect("durable exact retry"),
        last_receipt.expect("receipt")
    );
    assert_eq!(
        reopened.metrics().await.expect("metrics").host_resources[0].reserved,
        held.resources
    );
    reopened.close().await;
}

#[tokio::test]
async fn boot_change_fences_grant_but_never_releases_unconfirmed_execution_occupancy() {
    let directory = tempfile::tempdir().expect("directory");
    let clock = Arc::new(ManualClock::new(2_000));
    let store =
        DurableFleetStore::open_with_clock(&directory.path().join("fleet.sqlite3"), clock.clone())
            .await
            .expect("store");
    let old_generation = store.register_local_boot("host-one").await.expect("boot");
    store
        .observe_host(&host(old_generation, 1_900), "pressure-owner")
        .await
        .expect("host");
    let registry = authority_registry(&directory.path().join("authority"), clock);
    let held = grant("held", 7_000);
    put_lease(
        &registry,
        "issue-held",
        FleetAuthorityPort::binding_for_issue(&held).expect("binding"),
    );
    store
        .issue_authorized(
            &FleetAuthorityPort::new(registry.verifier()),
            "issue-held",
            1,
            held.clone(),
        )
        .await
        .expect("grant");
    let context = FleetExecutionContextV1 {
        execution_id: "prepared-execution".into(),
        allocation_id: held.allocation_id.clone(),
        principal_id: held.principal_id.clone(),
        host_id: held.host_id.clone(),
        host_generation: old_generation,
        lease_generation: 1,
        manifest_digest: held.semantic_digest.clone(),
        resources: held.resources,
        containment: "prepared-owner-context".into(),
    };
    // Durable crash fixture at the already-prepared cut. It is not native
    // launch/stop evidence and has no process identity to assert as exited.
    sqlx::query(
        "INSERT INTO fleet_execution_holds(execution_id, allocation_id, host_id,
        boot_identity, context_json, state, prepared_at_ms, containment_dev, containment_ino)
        VALUES(?, ?, ?, ?, ?, 'prepared', 2000, 1, 1)",
    )
    .bind(&context.execution_id)
    .bind(&context.allocation_id)
    .bind(&context.host_id)
    .bind(crate::durable_execution::native_boot_identity().expect("native boot"))
    .bind(serde_json::to_string(&context).expect("context"))
    .execute(&store.pool)
    .await
    .expect("prepared crash cut");
    assert_eq!(
        store
            .register_boot_identity("host-one", "next-real-boot-fixture")
            .await
            .expect("boot transition"),
        old_generation + 1
    );
    assert_eq!(
        store
            .verify_use(
                "held",
                "agent-one",
                "host-one",
                old_generation,
                1,
                &held.semantic_digest
            )
            .await,
        Err(DurableFleetError::Stale)
    );
    assert_eq!(
        store
            .execution_hold(&context.execution_id)
            .await
            .expect("hold")
            .expect("retained")
            .state,
        "stop_requested"
    );
    let metrics = store.metrics().await.expect("metrics");
    assert_eq!(metrics.active_grants, 0);
    assert_eq!(metrics.host_resources[0].reserved, held.resources);
    store.close().await;
}

#[tokio::test]
async fn actual_local_observer_renews_one_registered_boot_and_rejects_generation_drift() {
    let directory = tempfile::tempdir().expect("directory");
    let clock = Arc::new(ManualClock::new(2_000));
    let store =
        DurableFleetStore::open_with_clock(&directory.path().join("fleet.sqlite3"), clock.clone())
            .await
            .expect("store");
    let mut config =
        LocalCapacityObserverConfig::for_local_supervisor(directory.path(), 1).expect("config");
    config.generation = store
        .register_local_boot(&config.host_id)
        .await
        .expect("boot");
    let observer = LocalCapacityObserver::new(config.clone()).expect("observer");
    let first = store
        .observe_local_capacity(&observer)
        .await
        .expect("first");
    clock.set(2_010);
    let second = store
        .observe_local_capacity(&observer)
        .await
        .expect("refresh");
    assert_eq!(first.0.host.generation, second.0.host.generation);
    assert!(second.0.host.observed_at_ms > first.0.host.observed_at_ms);
    assert_ne!(first.1.operation_id, second.1.operation_id);
    assert!(second.1.authority_witness.is_none());
    config.generation += 1;
    assert_eq!(
        store
            .refresh_local_capacity(&LocalCapacityObserver::new(config).expect("drift observer"))
            .await,
        Err(DurableFleetError::Stale)
    );
    store.close().await;
}

#[tokio::test]
async fn legacy_mixed_snapshot_generations_recover_once_without_adopting_old_grants() {
    let directory = tempfile::tempdir().expect("directory");
    let clock = Arc::new(ManualClock::new(2_000));
    let store = DurableFleetStore::open_with_clock(&directory.path().join("fleet.sqlite3"), clock)
        .await
        .expect("store");
    store.register_local_boot("host-one").await.expect("boot");
    store
        .observe_host(&host(1, 1_900), "pressure-owner")
        .await
        .expect("snapshot");
    // Predecessor schema/data is unchanged; only its independent generation
    // increment is reproduced to exercise the actual upgrade transaction.
    sqlx::query("UPDATE fleet_hosts SET generation = 7 WHERE host_id = 'host-one'")
        .execute(&store.pool)
        .await
        .expect("legacy mixed cut");
    assert_eq!(
        store
            .register_local_boot("host-one")
            .await
            .expect("recover fence"),
        8
    );
    assert_eq!(
        store
            .register_local_boot("host-one")
            .await
            .expect("stable fence"),
        8
    );
    assert_eq!(
        store.observe_host(&host(7, 1_950), "pressure-owner").await,
        Err(DurableFleetError::Stale)
    );
    store
        .observe_host(&host(8, 1_960), "pressure-owner")
        .await
        .expect("fresh matching snapshot");
    store.close().await;
}

#[tokio::test]
async fn recent_snapshot_retention_keeps_current_receipt_and_excludes_effect_receipts() {
    let directory = tempfile::tempdir().expect("directory");
    let clock = Arc::new(ManualClock::new(2_000));
    let store =
        DurableFleetStore::open_with_clock(&directory.path().join("fleet.sqlite3"), clock.clone())
            .await
            .expect("store");
    let latest = host(1, 1_900);
    let first = store
        .observe_host(&latest, "pressure-owner")
        .await
        .expect("snapshot");
    let registry = authority_registry(&directory.path().join("authority"), clock.clone());
    let held = grant("retained-effect", 7_000);
    put_lease(
        &registry,
        "issue-retained",
        FleetAuthorityPort::binding_for_issue(&held).expect("binding"),
    );
    let issued = store
        .issue_authorized(
            &FleetAuthorityPort::new(registry.verifier()),
            "issue-retained",
            1,
            held,
        )
        .await
        .expect("effect receipt");
    // Seed the recoverable predecessor observation window in one transaction;
    // the production refresh below performs the real bounded retention.
    let mut tx = store
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("fixture transaction");
    for offset in 0..MAX_HOST_CAPACITY_SNAPSHOTS + 5 {
        let mut historical = latest.clone();
        historical.observed_at_ms = u64::try_from(1_500 + offset).expect("timestamp");
        let mut receipt = first.clone();
        receipt.operation_id = format!("historical-capacity-{offset}");
        receipt.semantic_digest = crate::durable_rows::content_digest(&historical).expect("digest");
        receipt.committed_at_ms = historical.observed_at_ms;
        crate::durable_receipt::insert_receipt_tx(&mut tx, &receipt)
            .await
            .expect("historical observation receipt");
        sqlx::query(
            "INSERT INTO fleet_capacity_observations SELECT host_id, generation, ?,
            valid_until_ms, source_id, cpu_millis, memory_bytes, accelerator_millis,
            concurrent_turns, tool_processes, turn_queue_slots, capacity_digest
            FROM fleet_capacity_observations WHERE host_id = 'host-one' AND observed_at_ms = 1900",
        )
        .bind(1_500 + offset)
        .execute(&mut *tx)
        .await
        .expect("older snapshot");
    }
    tx.commit().await.expect("fixture committed");
    clock.set(2_100);
    let mut next = latest.clone();
    next.observed_at_ms = 2_100;
    let current = store
        .observe_host(&next, "pressure-owner")
        .await
        .expect("bounded refresh");
    let rows: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM fleet_capacity_observations WHERE host_id = 'host-one'",
    )
    .fetch_one(&store.pool)
    .await
    .expect("count");
    assert_eq!(rows, MAX_HOST_CAPACITY_SNAPSHOTS);
    let receipts: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM fleet_operation_receipts WHERE subject_id = 'host-one' AND operation_kind = 'host_observation'").fetch_one(&store.pool).await.expect("receipt count");
    assert_eq!(receipts, MAX_HOST_CAPACITY_SNAPSHOTS);
    assert_eq!(
        store
            .operation_receipt(&issued.operation.operation_id)
            .await
            .expect("effect receipt not pruned"),
        Some(issued.operation)
    );
    assert_eq!(
        store
            .observe_host(&next, "pressure-owner")
            .await
            .expect("current retry"),
        current
    );
    assert_eq!(
        store.observe_host(&latest, "pressure-owner").await,
        Err(DurableFleetError::Stale)
    );
    assert_eq!(
        store
            .operation_receipt(&first.operation_id)
            .await
            .expect("retained earlier receipt"),
        Some(first)
    );
    store.close().await;
}
