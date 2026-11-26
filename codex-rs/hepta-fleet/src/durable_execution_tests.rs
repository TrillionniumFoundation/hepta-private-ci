use std::os::unix::process::CommandExt;
use std::process::Command;
use std::sync::Arc;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;

use super::*;

#[derive(Debug)]
struct Clock;

impl AuthorityClock for Clock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(2_000)
    }
}

#[tokio::test]
async fn incarnation_is_ordered_not_hashed_and_rejects_retired_boot_replay() {
    let directory = tempfile::tempdir().expect("temporary database");
    let path = directory.path().join("fleet.sqlite3");
    let store = DurableFleetStore::open_with_clock(&path, Arc::new(Clock))
        .await
        .expect("open");
    assert_eq!(
        store
            .register_boot_identity("host", "zz-newer-hash")
            .await
            .expect("first"),
        1
    );
    assert_eq!(
        store
            .register_boot_identity("host", "aa-smaller-hash")
            .await
            .expect("second"),
        2
    );
    assert_eq!(
        store.register_boot_identity("host", "zz-newer-hash").await,
        Err(DurableFleetError::Stale)
    );
    store.close().await;
    let reopened = DurableFleetStore::open_with_clock(&path, Arc::new(Clock))
        .await
        .expect("reopen");
    assert_eq!(
        reopened
            .register_boot_identity("host", "aa-smaller-hash")
            .await
            .expect("same boot"),
        2
    );
    assert_eq!(
        reopened
            .register_boot_identity("host", "third")
            .await
            .expect("third"),
        3
    );
    reopened.close().await;
}

#[tokio::test]
async fn independent_connections_cannot_allocate_duplicate_incarnations() {
    let directory = tempfile::tempdir().expect("temporary database");
    let path = directory.path().join("fleet.sqlite3");
    let first = DurableFleetStore::open_with_clock(&path, Arc::new(Clock))
        .await
        .expect("first");
    let second = DurableFleetStore::open_with_clock(&path, Arc::new(Clock))
        .await
        .expect("second");
    let (one, two) = tokio::join!(
        first.register_boot_identity("host", "boot"),
        second.register_boot_identity("host", "boot")
    );
    assert_eq!(one.expect("first allocation"), 1);
    assert_eq!(two.expect("idempotent allocation"), 1);
    first.close().await;
    second.close().await;
}

#[tokio::test]
async fn native_boot_registration_survives_owner_restart() {
    let directory = tempfile::tempdir().expect("temporary database");
    let path = directory.path().join("fleet.sqlite3");
    let store = DurableFleetStore::open_with_clock(&path, Arc::new(Clock))
        .await
        .expect("open");
    let generation = store
        .register_local_boot("native-host")
        .await
        .expect("native boot");
    store.close().await;
    let reopened = DurableFleetStore::open_with_clock(&path, Arc::new(Clock))
        .await
        .expect("reopen");
    assert_eq!(
        reopened
            .register_local_boot("native-host")
            .await
            .expect("same native boot"),
        generation
    );
    reopened.close().await;
}

#[test]
fn capacity_pressure_is_not_a_fatal_integrity_failure() {
    assert_eq!(
        DurableFleetError::Capacity.disposition(),
        FleetFailureDispositionV1::RetryWithoutNewAdmissions
    );
    assert_eq!(
        DurableFleetError::ClockRollback.disposition(),
        FleetFailureDispositionV1::QuarantineOwner
    );
    assert_eq!(
        DurableFleetError::IndeterminateCommit {
            operation_id: "op".into(),
            subject_id: "grant".into(),
        }
        .disposition(),
        FleetFailureDispositionV1::ReconcileBeforeRetry
    );
}

#[test]
fn process_group_proof_does_not_confuse_leader_exit_with_empty_group() {
    let mut leader = Command::new("/bin/sleep")
        .arg("30")
        .process_group(0)
        .spawn()
        .expect("leader");
    let group = leader.id();
    let follower = Command::new("/bin/sleep")
        .arg("30")
        .process_group(i32::try_from(group).expect("native process group fits pid_t"))
        .spawn();
    let mut follower = match follower {
        Ok(child) => child,
        Err(error) => {
            let _ = leader.kill();
            let _ = leader.wait();
            panic!("group follower: {error}");
        }
    };
    let before = process_group_exists(u64::from(group));
    let _ = leader.kill();
    let _ = leader.wait();
    let after_leader = process_group_exists(u64::from(group));
    let _ = follower.kill();
    let _ = follower.wait();
    let after_all = process_group_exists(u64::from(group));
    assert!(before.expect("group while both processes live"));
    assert!(after_leader.expect("remaining group member"));
    assert!(!after_all.expect("fully reaped group"));
}

#[test]
fn missing_or_unprotected_containment_is_not_stop_evidence() {
    for path in ["", "../escape", "/absolute", "missing-fleet-containment"] {
        assert!(native_containment(path).is_err());
    }
}

#[tokio::test]
async fn prepared_launch_keeps_capacity_after_expiry_and_reopen() {
    let directory = tempfile::tempdir().expect("temporary database");
    let path = directory.path().join("fleet.sqlite3");
    let store = DurableFleetStore::open_with_clock(&path, Arc::new(Clock))
        .await
        .expect("open");
    let resource = ResourceVectorV1 {
        cpu_millis: 1,
        memory_bytes: 1,
        ..ResourceVectorV1::default()
    };
    store
        .observe_host(
            &crate::HostObservation {
                host_id: "host".into(),
                failure_domain_id: "rack".into(),
                generation: 1,
                observed_at_ms: 1_000,
                valid_until_ms: 5_000,
                capacity: resource,
            },
            "test-observer",
        )
        .await
        .expect("host");
    // Transaction fixture, not generic-authority or product acceptance evidence.
    sqlx::query(
        "INSERT INTO fleet_grants VALUES('allocation', 'request', 'principal', 'host', 'rack',
         1, 1, 1, 1999, 1, 1, 0, 0, 0, 0, 'resource', ?, '{}', 1000, 1000)",
    )
    .bind("a".repeat(64))
    .execute(&store.pool)
    .await
    .expect("grant fixture");
    sqlx::query("UPDATE fleet_resource_totals SET cpu_millis = 1, memory_bytes = 1")
        .execute(&store.pool)
        .await
        .expect("reserve fixture");
    let context = FleetExecutionContextV1 {
        execution_id: "execution".into(),
        allocation_id: "allocation".into(),
        principal_id: "principal".into(),
        host_id: "host".into(),
        host_generation: 1,
        lease_generation: 1,
        manifest_digest: "a".repeat(64),
        resources: resource,
        containment: "missing-fleet-containment".into(),
    };
    sqlx::query(
        "INSERT INTO fleet_execution_holds(execution_id, allocation_id, host_id, boot_identity,
         context_json, state, prepared_at_ms, containment_dev, containment_ino)
         VALUES('execution', 'allocation', 'host', ?, ?, 'prepared', 1000, 0, 0)",
    )
    .bind(native_boot_identity().expect("boot"))
    .bind(encode_json(&context).expect("context"))
    .execute(&store.pool)
    .await
    .expect("launch fixture");
    assert_eq!(store.collect_expired().await.expect("expiry"), 1);
    store.close().await;
    let reopened = DurableFleetStore::open_with_clock(&path, Arc::new(Clock))
        .await
        .expect("reopen");
    let pending = reopened
        .pending_executions()
        .await
        .expect("durable stop obligation");
    assert_eq!(pending.len(), 1);
    assert_eq!(pending[0].state, "stop_requested");
    assert!(reopened.confirm_local_exit("execution").await.is_err());
    let metrics = reopened.metrics().await.expect("metrics");
    assert_eq!(metrics.active_grants, 0);
    assert_eq!(metrics.host_resources[0].reserved, resource);
    reopened.close().await;
}

#[tokio::test]
async fn unobserved_gauges_remain_unknown_and_zero_requires_an_observation() {
    let directory = tempfile::tempdir().expect("temporary database");
    let store = DurableFleetStore::open_with_clock(
        &directory.path().join("fleet.sqlite3"),
        Arc::new(Clock),
    )
    .await
    .expect("open");
    let before = store.metrics().await.expect("metrics");
    assert_eq!(before.registry_conflicts, None);
    assert_eq!(before.indeterminate_commits, None);
    assert_eq!(before.staging_debris, None);
    assert_eq!(before.revocation_lag_ms, None);
    store
        .set_operational_gauge("registry", "staging_debris", 0)
        .await
        .expect("observed zero");
    assert_eq!(
        store.metrics().await.expect("metrics").staging_debris,
        Some(0)
    );
    assert!(
        store
            .set_operational_gauge("unregistered", "label", 0)
            .await
            .is_err()
    );
    store.close().await;
}
