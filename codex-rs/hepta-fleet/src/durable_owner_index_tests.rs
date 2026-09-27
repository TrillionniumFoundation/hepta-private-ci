use super::*;
use crate::CapacityObservationError;
use crate::ResourceVectorV1;
use crate::TrustedCapacityObservationV1;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseFrontier;
use codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry;
use sha2::Digest;
use sha2::Sha256;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

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

impl FleetClock for ManualClock {
    fn now_unix_ms(&self) -> Result<u64, crate::FleetClockError> {
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
            observer_id: "index-test-observer".into(),
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

fn grant() -> AllocationGrant {
    AllocationGrant {
        allocation_id: "allocation-one".into(),
        request_id: "request-one".into(),
        principal_id: "agent-one".into(),
        host_id: "host-one".into(),
        failure_domain_id: "rack-one".into(),
        host_generation: 1,
        authority_epoch: 7,
        lease_generation: 1,
        expires_at_ms: 9_000,
        resources: ResourceVectorV1::physical(100, 1_024, 0),
        semantic_digest: format!("{:x}", Sha256::digest(b"indexed-allocation-one")),
        revoked: false,
    }
}

#[cfg(unix)]
fn state_root(directory: &tempfile::TempDir) -> PathBuf {
    use std::os::unix::fs::PermissionsExt;

    let root = directory.path().join("state");
    std::fs::create_dir(&root).expect("state root");
    std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700))
        .expect("state permissions");
    root
}

#[cfg(unix)]
fn authority_port(
    directory: &tempfile::TempDir,
    clock: Arc<ManualClock>,
    grant: &AllocationGrant,
) -> FleetAuthorityPort {
    use std::os::unix::fs::PermissionsExt;

    let authority_root = directory.path().join("authority-index-tests");
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
fn replay_returns_the_original_committed_state_digest_after_later_mutations() {
    let directory = tempfile::tempdir().expect("tempdir");
    let state_root = state_root(&directory);
    let clock = Arc::new(ManualClock::new(2_000));
    let mut owner = DurableFleetOwner::open_supervisor_state_root(&state_root, clock.clone())
        .expect("owner");

    let first = owner
        .refresh_capacity("capacity-original", &FixedObserver)
        .expect("first capacity");
    clock.set(2_100);
    owner
        .refresh_capacity("capacity-later", &FixedObserver)
        .expect("later capacity");
    let replay = owner
        .refresh_capacity("capacity-original", &FixedObserver)
        .expect("indexed replay");

    assert_eq!(replay.generation, first.generation);
    assert_eq!(replay.state_sha256, first.state_sha256);
    assert_ne!(replay.state_sha256, owner.state().content_sha256);
}

#[cfg(unix)]
#[test]
fn allocation_identity_is_one_shot_across_operation_ids_and_reopen() {
    let directory = tempfile::tempdir().expect("tempdir");
    let state_root = state_root(&directory);
    let clock = Arc::new(ManualClock::new(2_000));
    let grant = grant();
    let port = authority_port(&directory, clock.clone(), &grant);
    let mut owner = DurableFleetOwner::open_supervisor_state_root(&state_root, clock.clone())
        .expect("owner");
    owner
        .refresh_capacity("capacity-one", &FixedObserver)
        .expect("capacity");
    owner
        .issue_with_authority(
            "issue-original",
            &port,
            "fleet-issue-one",
            1,
            grant.clone(),
        )
        .expect("issue");
    drop(owner);

    let mut reopened = DurableFleetOwner::open_supervisor_state_root(&state_root, clock)
        .expect("reopen");
    assert!(matches!(
        reopened.issue_with_authority(
            "issue-reused-id",
            &port,
            "fleet-issue-one",
            1,
            grant,
        ),
        Err(DurableFleetError::OperationConflict(identity)) if identity == "allocation-one"
    ));
}

#[cfg(unix)]
#[test]
fn a_proven_post_link_commit_is_recovered_and_indexed_before_return() {
    let directory = tempfile::tempdir().expect("tempdir");
    let state_root = state_root(&directory);
    let clock = Arc::new(ManualClock::new(2_000));
    let mut owner = DurableFleetOwner::open_supervisor_state_root(&state_root, clock)
        .expect("owner");

    core::fail_next_commit_after_state_link();
    let recovered = owner
        .refresh_capacity("capacity-indeterminate", &FixedObserver)
        .expect("wrapper proves committed generation");
    assert_eq!(recovered.generation, 1);

    let replay = owner
        .refresh_capacity("capacity-indeterminate", &FixedObserver)
        .expect("indexed replay");
    assert_eq!(replay, recovered);
}
