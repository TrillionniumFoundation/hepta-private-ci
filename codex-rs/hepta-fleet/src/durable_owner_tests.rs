use super::*;
use crate::FleetCapacityObserverV1;
use crate::ResourceVectorV1;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseFrontier;
use codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry;
use pretty_assertions::assert_eq;
use sha2::Digest;
use sha2::Sha256;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

#[derive(Debug)]
struct ManualClock(AtomicU64);

impl ManualClock {
    fn new(now: u64) -> Self {
        Self(AtomicU64::new(now))
    }

    fn set(&self, now: u64) {
        self.0.store(now, Ordering::SeqCst);
    }
}

impl FleetClock for ManualClock {
    fn now_unix_ms(&self) -> Result<u64, FleetClockError> {
        Ok(self.0.load(Ordering::SeqCst))
    }
}

impl AuthorityClock for ManualClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(self.0.load(Ordering::SeqCst))
    }
}

#[derive(Debug)]
struct FixedObserver;

impl FleetCapacityObserverV1 for FixedObserver {
    fn observe(
        &self,
        now_ms: u64,
    ) -> Result<TrustedCapacityObservationV1, CapacityObservationError> {
        Ok(TrustedCapacityObservationV1 {
            schema_version: crate::CAPACITY_OBSERVATION_SCHEMA_VERSION,
            observer_id: "test-observer".into(),
            host_id: "host-one".into(),
            failure_domain_id: "rack-one".into(),
            host_generation: 1,
            observed_at_ms: now_ms,
            valid_until_ms: now_ms + 10_000,
            memory_pressure_basis_points: 0,
            capacity: ResourceVectorV1::physical(1_000, 1 << 20, 0),
        })
    }
}

fn grant(expires_at_ms: u64) -> AllocationGrant {
    AllocationGrant {
        allocation_id: "allocation-one".into(),
        request_id: "request-one".into(),
        principal_id: "agent-one".into(),
        host_id: "host-one".into(),
        failure_domain_id: "rack-one".into(),
        host_generation: 1,
        authority_epoch: 7,
        lease_generation: 1,
        expires_at_ms,
        resources: ResourceVectorV1::physical(100, 1_024, 0),
        semantic_digest: format!("{:x}", Sha256::digest(b"fleet-allocation-one")),
        revoked: false,
    }
}

#[cfg(unix)]
fn authority_port(
    directory: &tempfile::TempDir,
    name: &str,
    clock: Arc<ManualClock>,
    grant: &AllocationGrant,
) -> FleetAuthorityPort {
    use std::os::unix::fs::PermissionsExt;

    let authority_root = directory.path().join(name);
    std::fs::create_dir(&authority_root).expect("authority root");
    std::fs::set_permissions(&authority_root, std::fs::Permissions::from_mode(0o700))
        .expect("authority permissions");
    let registry = AuthorityLeaseRegistry::open_state_dir_with_clock(
        &authority_root,
        "security-authority".into(),
        AuthorityLeaseFrontier::for_empty_epoch(7).expect("frontier"),
        clock,
    )
    .expect("authority registry");
    let binding = FleetAuthorityPort::binding_for_issue(grant).expect("binding");
    registry
        .put_lease(
            AuthorityLease {
                schema_version: 1,
                lease_id: "fleet-issue-one".into(),
                authority_epoch: 7,
                revision: 1,
                binding,
                issued_at_unix_ms: 1_000,
                expires_at_unix_ms: 8_000,
            },
            0,
        )
        .expect("lease");
    FleetAuthorityPort::new(registry.verifier())
}

#[cfg(unix)]
#[test]
fn issue_is_atomic_with_witness_and_survives_reopen() {
    use std::os::unix::fs::PermissionsExt;

    let directory = tempfile::tempdir().expect("tempdir");
    let state_root = directory.path().join("state");
    std::fs::create_dir(&state_root).expect("state root");
    std::fs::set_permissions(&state_root, std::fs::Permissions::from_mode(0o700))
        .expect("permissions");
    let clock = Arc::new(ManualClock::new(2_000));
    let mut owner =
        DurableFleetOwner::open_supervisor_state_root(&state_root, clock.clone())
            .expect("owner");
    owner
        .refresh_capacity("capacity-one", &FixedObserver)
        .expect("capacity");

    let grant = grant(9_000);
    let port = authority_port(&directory, "authority-one", clock.clone(), &grant);
    let issued = owner
        .issue_with_authority(
            "operation-one",
            &port,
            "fleet-issue-one",
            1,
            grant.clone(),
        )
        .expect("issue");
    assert_eq!(issued.lease.outcome, LeaseOutcome::Issued);
    assert_eq!(issued.generation, 2);

    drop(owner);
    let mut reopened =
        DurableFleetOwner::open_supervisor_state_root(&state_root, clock.clone())
            .expect("reopen");
    let witness = reopened
        .verify_final_use(
            "allocation-one",
            1,
            "host-one",
            1,
            &grant.semantic_digest,
        )
        .expect("final use");
    assert_eq!(witness.allocation_id, "allocation-one");
    let duplicate = reopened
        .issue_with_authority(
            "operation-one",
            &port,
            "fleet-issue-one",
            1,
            grant,
        )
        .expect("idempotent duplicate");
    assert_eq!(duplicate.generation, issued.generation);
}

#[cfg(unix)]
#[test]
fn expiry_reconciliation_releases_durable_capacity() {
    let directory = tempfile::tempdir().expect("tempdir");
    let state_root = directory.path().join("state");
    std::fs::create_dir(&state_root).expect("state root");
    let clock = Arc::new(ManualClock::new(2_000));
    let mut owner =
        DurableFleetOwner::open_supervisor_state_root(&state_root, clock.clone())
            .expect("owner");
    owner
        .refresh_capacity("capacity-one", &FixedObserver)
        .expect("capacity");
    let expiring = grant(2_500);
    let port = authority_port(&directory, "authority-expiry", clock.clone(), &expiring);
    owner
        .issue_with_authority(
            "issue-expiring",
            &port,
            "fleet-issue-one",
            1,
            expiring,
        )
        .expect("issue expiring grant");

    clock.set(2_500);
    owner
        .reconcile_expired("expiry-one")
        .expect("reconcile expiry");
    assert_eq!(
        owner.metrics().expect("operational metrics").fleet_active_grants,
        0
    );
}

#[test]
fn post_link_failure_is_indeterminate_and_recoverable_by_operation_id() {
    let directory = tempfile::tempdir().expect("tempdir");
    let state_root = directory.path().join("state");
    std::fs::create_dir(&state_root).expect("state root");
    let clock = Arc::new(ManualClock::new(2_000));
    let mut owner =
        DurableFleetOwner::open_supervisor_state_root(&state_root, clock.clone())
            .expect("owner");
    fail_next_commit_after_state_link();
    let error = owner
        .refresh_capacity("capacity-indeterminate", &FixedObserver)
        .expect_err("indeterminate commit");
    assert!(matches!(
        error,
        DurableFleetError::IndeterminateCommit {
            operation_id,
            generation: 1,
            ..
        } if operation_id == "capacity-indeterminate"
    ));

    let mut reopened = DurableFleetOwner::open_supervisor_state_root(&state_root, clock)
        .expect("reopen committed generation");
    let duplicate = reopened
        .refresh_capacity("capacity-indeterminate", &FixedObserver)
        .expect("idempotent recovery");
    assert_eq!(duplicate.generation, 1);
}
