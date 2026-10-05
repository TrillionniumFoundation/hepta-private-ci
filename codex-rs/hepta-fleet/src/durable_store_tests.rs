use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseFrontier;
use codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry;
use pretty_assertions::assert_eq;
use sha2::Digest;
use sha2::Sha256;

use super::*;
use crate::AllocationGrant;
use crate::DurableLeaseDispositionV1;
use crate::FleetAuthorityPort;
use crate::HostObservation;
use crate::ResourceVectorV1;

#[derive(Debug)]
struct ManualClock(AtomicU64);

impl ManualClock {
    fn new(now_ms: u64) -> Self {
        Self(AtomicU64::new(now_ms))
    }

    fn set(&self, now_ms: u64) {
        self.0.store(now_ms, Ordering::SeqCst);
    }
}

impl AuthorityClock for ManualClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(self.0.load(Ordering::SeqCst))
    }
}

fn host(generation: u64, observed_at_ms: u64) -> HostObservation {
    HostObservation {
        host_id: "host-one".into(),
        failure_domain_id: "rack-one".into(),
        generation,
        observed_at_ms,
        valid_until_ms: 10_000,
        capacity: ResourceVectorV1 {
            cpu_millis: 8_000,
            memory_bytes: 1 << 30,
            accelerator_millis: 0,
            concurrent_turns: 8,
            tool_processes: 32,
            turn_queue_slots: 512,
        },
    }
}

fn grant(id: &str, expires_at_ms: u64) -> AllocationGrant {
    AllocationGrant {
        allocation_id: id.into(),
        request_id: format!("request-{id}"),
        principal_id: "agent-one".into(),
        host_id: "host-one".into(),
        failure_domain_id: "rack-one".into(),
        host_generation: 1,
        authority_epoch: 7,
        lease_generation: 1,
        expires_at_ms,
        resources: ResourceVectorV1 {
            cpu_millis: 500,
            memory_bytes: 1 << 20,
            accelerator_millis: 0,
            concurrent_turns: 1,
            tool_processes: 2,
            turn_queue_slots: 16,
        },
        semantic_digest: format!("{:x}", Sha256::digest(id.as_bytes())),
        revoked: false,
    }
}

fn authority_registry(root: &Path, clock: Arc<ManualClock>) -> AuthorityLeaseRegistry {
    std::fs::create_dir_all(root).expect("authority root");
    std::fs::set_permissions(root, std::fs::Permissions::from_mode(0o700))
        .expect("authority permissions");
    AuthorityLeaseRegistry::open_state_dir_with_clock(
        root,
        "security-authority".into(),
        AuthorityLeaseFrontier::for_empty_epoch(7).expect("frontier"),
        clock,
    )
    .expect("authority registry")
}

fn put_lease(
    registry: &AuthorityLeaseRegistry,
    lease_id: &str,
    binding: codex_hepta_contracts::authority_lease::AuthorityLeaseBinding,
) {
    registry
        .put_lease(
            AuthorityLease {
                schema_version: 1,
                lease_id: lease_id.into(),
                authority_epoch: 7,
                revision: 1,
                binding,
                issued_at_unix_ms: 1_000,
                expires_at_unix_ms: 8_000,
            },
            /*expected_revision*/ 0,
        )
        .expect("put authority lease");
}

#[tokio::test]
async fn durable_grant_survives_reopen_and_revoke_releases_capacity() {
    let directory = tempfile::tempdir().expect("tempdir");
    let database = directory.path().join("supervisor.sqlite3");
    let clock = Arc::new(ManualClock::new(2_000));
    let store = DurableFleetStore::open_with_clock(&database, clock.clone())
        .await
        .expect("store");
    store
        .observe_host(
            &host(/*generation*/ 1, /*observed_at_ms*/ 1_500),
            "test-observer",
        )
        .await
        .expect("host");

    let registry = authority_registry(&directory.path().join("authority"), clock.clone());
    let grant = grant("allocation-one", 7_000);
    put_lease(
        &registry,
        "issue-one",
        FleetAuthorityPort::binding_for_issue(&grant).expect("issue binding"),
    );
    let authority = FleetAuthorityPort::new(registry.verifier());
    let issued = store
        .issue_authorized(&authority, "issue-one", 1, grant.clone())
        .await
        .expect("issue");
    assert_eq!(issued.grant, grant);
    assert_eq!(
        store
            .verify_use(
                "allocation-one",
                "agent-one",
                "host-one",
                /*host_generation*/ 1,
                /*expected_lease_generation*/ 1,
                &grant.semantic_digest,
            )
            .await
            .expect("permit")
            .resources,
        grant.resources
    );
    store.close().await;

    let reopened = DurableFleetStore::open_with_clock(&database, clock.clone())
        .await
        .expect("reopen");
    reopened
        .verify_use(
            "allocation-one",
            "agent-one",
            "host-one",
            /*host_generation*/ 1,
            /*expected_lease_generation*/ 1,
            &grant.semantic_digest,
        )
        .await
        .expect("persisted permit");
    put_lease(
        &registry,
        "revoke-one",
        FleetAuthorityPort::binding_for_revoke(&grant).expect("revoke binding"),
    );
    reopened
        .mutate_lease_authorized(
            &authority,
            "revoke-one",
            1,
            "allocation-one",
            1,
            7,
            &grant.semantic_digest,
            DurableLeaseDispositionV1::Revoke,
        )
        .await
        .expect("revoke");
    assert!(matches!(
        reopened
            .verify_use(
                "allocation-one",
                "agent-one",
                "host-one",
                1,
                2,
                &grant.semantic_digest,
            )
            .await,
        Err(DurableFleetError::Stale)
    ));
    let metrics = reopened.metrics().await.expect("metrics");
    assert_eq!(metrics.active_grants, 0);
    assert_eq!(
        metrics.host_resources[0].reserved,
        ResourceVectorV1::default()
    );
}

#[tokio::test]
async fn expiry_and_host_generation_fence_are_durable() {
    let directory = tempfile::tempdir().expect("tempdir");
    let database = directory.path().join("supervisor.sqlite3");
    let clock = Arc::new(ManualClock::new(2_000));
    let store = DurableFleetStore::open_with_clock(&database, clock.clone())
        .await
        .expect("store");
    store
        .observe_host(&host(1, 1_500), "test-observer")
        .await
        .expect("host");
    let registry = authority_registry(&directory.path().join("authority"), clock.clone());
    let grant = grant("expires", 2_500);
    put_lease(
        &registry,
        "issue-expires",
        FleetAuthorityPort::binding_for_issue(&grant).expect("binding"),
    );
    store
        .issue_authorized(
            &FleetAuthorityPort::new(registry.verifier()),
            "issue-expires",
            1,
            grant.clone(),
        )
        .await
        .expect("issue");
    clock.set(2_501);
    assert_eq!(store.collect_expired().await.expect("expire"), 1);
    assert_eq!(store.metrics().await.expect("metrics").active_grants, 0);

    clock.set(3_000);
    store
        .observe_host(&host(2, 3_000), "test-observer")
        .await
        .expect("next host generation");
    store.close().await;
    DurableFleetStore::open_with_clock(&database, clock)
        .await
        .expect("durable reopen")
        .close()
        .await;
}

#[tokio::test]
async fn workspace_overlap_and_clock_rollback_fail_closed() {
    let directory = tempfile::tempdir().expect("tempdir");
    let workspace = tempfile::tempdir().expect("workspace");
    let child = workspace.path().join("child");
    std::fs::create_dir(&child).expect("child workspace");
    let clock = Arc::new(ManualClock::new(2_000));
    let store = DurableFleetStore::open_with_clock(
        &directory.path().join("supervisor.sqlite3"),
        clock.clone(),
    )
    .await
    .expect("store");
    store
        .reserve_workspace("agent-one", workspace.path())
        .await
        .expect("reservation");
    assert!(matches!(
        store.reserve_workspace("agent-two", &child).await,
        Err(DurableFleetError::Conflict(_))
    ));
    clock.set(1_999);
    assert_eq!(
        store.metrics().await.expect_err("rollback"),
        DurableFleetError::ClockRollback
    );
}

#[cfg(target_os = "linux")]
#[path = "capacity_refresh_tests.rs"]
mod capacity_refresh_tests;
