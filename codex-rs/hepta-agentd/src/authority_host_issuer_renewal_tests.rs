//! Isolated original-registry tests, not actual Root or production qualification.
use super::*;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseBinding;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

struct Clock(AtomicU64);
impl AuthorityClock for Clock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(self.0.load(Ordering::SeqCst))
    }
}

struct Fixture {
    _root: tempfile::TempDir,
    clock: Arc<Clock>,
    leases: AuthorityLeaseRegistry,
    config: HostAuthorityServiceConfig,
    issuer: DeploymentFinalUseIssuer,
    issuer_path: std::path::PathBuf,
}

impl Fixture {
    fn new() -> Self {
        let root = tempfile::tempdir().unwrap();
        let clock = Arc::new(Clock(AtomicU64::new(10_000)));
        let leases = AuthorityLeaseRegistry::open_state_dir_with_clock(
            &root.path().join("leases"),
            "issuer-renewal-test".into(),
            AuthorityLeaseFrontier::for_empty_epoch(1).unwrap(),
            clock.clone(),
        )
        .unwrap();
        let old = AuthorityLease {
            schema_version: 1,
            lease_id: "original-issuer".into(),
            authority_epoch: 1,
            revision: 1,
            binding: AuthorityLeaseBinding {
                principal_id: "agent.local".into(),
                operation_class: "runtime.agentd.production_operation".into(),
                destination_id: "notes.local".into(),
                scope_sha256: [1; 32],
                payload_sha256: [2; 32],
            },
            issued_at_unix_ms: 10_000,
            expires_at_unix_ms: 20_000,
        };
        leases.put_lease(old, 0).unwrap();
        let issuer_path = root.path().join("issuer");
        let issuer = DeploymentFinalUseIssuer::create(
            &issuer_path,
            "original-issuer-key".into(),
            vec![DeploymentGrantPolicy {
                subject_id: "agent.local".into(),
                destination_id: "notes.local".into(),
                scope_sha256: [1; 32],
                lifetime_ms: 10_000,
            }],
            clock.clone(),
        )
        .unwrap();
        let key = issuer.trust_key().unwrap();
        let path = root.path().to_path_buf();
        let config = HostAuthorityServiceConfig {
            schema_version: 1,
            state_dir: path.clone(),
            required_bind: HostAuthorityBindIdentity {
                mountpoint: path.clone(),
                source_path: path.clone(),
                device: 0,
                inode: 0,
            },
            signer_id: key.key_id,
            expected_verifying_key: key.verifying_key,
            lease_id: "original-issuer".into(),
            lease_revision: 1,
            writer: None,
            checkpoint_state_dir: None,
            consumers: None,
            sockets: crate::HostAuthoritySocketPaths {
                observation: path.join("observation"),
                issuer: path.join("issuer-socket"),
                checkpoint: path.join("checkpoint"),
                device_frontier: None,
                notes_frontier: None,
            },
            peer_uid: 1000,
            peer_gid: 1000,
            timeout_ms: 1000,
            lifetime_ms: 30_000,
            issuer_record_profile: crate::HostIssuerRecordProfile::Standard,
        };
        Self {
            _root: root,
            clock,
            leases,
            config,
            issuer,
            issuer_path,
        }
    }

    fn plan(&self) -> HostIssuerLeaseRenewalPlan {
        self.clock.0.store(21_000, Ordering::SeqCst);
        prepare_existing(&self.config, &self.leases, 21_000, 30_000).unwrap()
    }

    fn no_commit(&self, plan: &HostIssuerLeaseRenewalPlan, now: u64) {
        let before = self.leases.frontier().unwrap();
        assert!(commit_existing(&self.config, &self.leases, plan, now).is_err());
        assert_eq!(self.leases.frontier().unwrap(), before);
    }
}

fn use_binding() -> FinalUseBinding {
    FinalUseBinding {
        subject_id: "agent.local".into(),
        destination_id: "notes.local".into(),
        scope_sha256: [1; 32],
        payload_sha256: [2; 32],
        request_sha256: [3; 32],
    }
}

#[test]
fn expired_original_preparation_is_read_only_and_preserves_identity() {
    let fixture = Fixture::new();
    let before = fixture.leases.frontier().unwrap();
    let plan = fixture.plan();
    assert_eq!(fixture.leases.frontier().unwrap(), before);
    assert_eq!(plan.renewed_lease.revision, 2);
    assert_eq!(plan.renewed_lease.issued_at_unix_ms, 21_000);
    assert_eq!(plan.renewed_lease.expires_at_unix_ms, 51_000);
    assert_eq!(plan.previous_lease.binding, plan.renewed_lease.binding);
    assert_eq!(plan.previous_lease.lease_id, plan.renewed_lease.lease_id);
    assert_eq!(
        plan.previous_lease.authority_epoch,
        plan.renewed_lease.authority_epoch
    );
    assert_eq!(
        plan.verifying_key,
        fixture.issuer.trust_key().unwrap().verifying_key
    );
}

#[test]
fn exact_postimage_retry_does_not_advance_frontier_or_extend_deadline() {
    let fixture = Fixture::new();
    let first_grant = fixture.issuer.issue(&use_binding()).unwrap().unwrap();
    let plan = fixture.plan();
    let before = fixture.leases.frontier().unwrap();
    let renewed = commit_existing(&fixture.config, &fixture.leases, &plan, 21_000).unwrap();
    let committed = fixture.leases.frontier().unwrap();
    assert_eq!(committed.store_revision, before.store_revision + 1);
    assert_eq!(renewed, plan.renewed_lease);
    assert_eq!(
        commit_existing(&fixture.config, &fixture.leases, &plan, 22_000).unwrap(),
        renewed
    );
    assert_eq!(fixture.leases.frontier().unwrap(), committed);
    let verifier = fixture.leases.verifier();
    assert!(
        verifier
            .verify_use(&renewed.lease_id, 1, &renewed.binding)
            .is_err()
    );
    assert!(
        verifier
            .verify_use(&renewed.lease_id, 2, &renewed.binding)
            .is_ok()
    );
    let reopened =
        DeploymentFinalUseIssuer::open(&fixture.issuer_path, fixture.clock.clone()).unwrap();
    assert_eq!(
        reopened.trust_key().unwrap().key_id,
        fixture.issuer.trust_key().unwrap().key_id
    );
    assert_eq!(
        reopened.trust_key().unwrap().verifying_key,
        fixture.issuer.trust_key().unwrap().verifying_key
    );
    let second_grant = reopened.issue(&use_binding()).unwrap().unwrap();
    assert_eq!(first_grant.grant.grant_id, "original-issuer-key:1:1");
    assert_eq!(second_grant.grant.grant_id, "original-issuer-key:1:2");
    fixture.no_commit(&plan, 51_000);
}

#[test]
fn changed_plan_fields_never_mutate_the_original_registry() {
    let fixture = Fixture::new();
    let plan = fixture.plan();
    let mut cases = Vec::new();
    let mut bad = plan.clone();
    bad.schema_version = 2;
    cases.push(bad);
    let mut bad = plan.clone();
    bad.signer_id.push_str("-other");
    cases.push(bad);
    let mut bad = plan.clone();
    bad.verifying_key[0] ^= 1;
    cases.push(bad);
    let mut bad = plan.clone();
    bad.renewed_lease.lease_id.push_str("-other");
    cases.push(bad);
    let mut bad = plan.clone();
    bad.renewed_lease.authority_epoch += 1;
    cases.push(bad);
    let mut bad = plan.clone();
    bad.renewed_lease.binding.payload_sha256 = [9; 32];
    cases.push(bad);
    let mut bad = plan.clone();
    bad.renewed_lease.revision += 1;
    cases.push(bad);
    let mut bad = plan.clone();
    bad.renewed_lease.expires_at_unix_ms = 321_001;
    cases.push(bad);
    let mut bad = plan.clone();
    bad.previous_lease.binding.scope_sha256 = [9; 32];
    bad.renewed_lease.binding.scope_sha256 = [9; 32];
    cases.push(bad);
    for bad in cases {
        fixture.no_commit(&bad, 21_000);
    }
    fixture.no_commit(&plan, 20_999);
}

#[test]
fn revoked_predecessor_or_committed_postimage_cannot_be_renewed() {
    let fixture = Fixture::new();
    let plan = fixture.plan();
    fixture
        .leases
        .revoke(&plan.previous_lease.lease_id, 1, [7; 32])
        .unwrap();
    let before = fixture.leases.frontier().unwrap();
    assert!(prepare_existing(&fixture.config, &fixture.leases, 21_000, 30_000).is_err());
    fixture.no_commit(&plan, 21_000);
    assert_eq!(fixture.leases.frontier().unwrap(), before);

    let fixture = Fixture::new();
    let plan = fixture.plan();
    commit_existing(&fixture.config, &fixture.leases, &plan, 21_000).unwrap();
    fixture
        .leases
        .revoke(&plan.renewed_lease.lease_id, 2, [8; 32])
        .unwrap();
    fixture.no_commit(&plan, 22_000);
}

#[test]
fn concurrent_canonical_revision_or_epoch_change_is_not_overwritten() {
    let fixture = Fixture::new();
    let plan = fixture.plan();
    let mut concurrent = plan.renewed_lease.clone();
    concurrent.expires_at_unix_ms += 1;
    fixture.leases.put_lease(concurrent, 1).unwrap();
    fixture.no_commit(&plan, 21_000);

    let fixture = Fixture::new();
    let plan = fixture.plan();
    let frontier = fixture.leases.frontier().unwrap();
    fixture
        .leases
        .advance_epoch(frontier.store_revision, 2)
        .unwrap();
    fixture.no_commit(&plan, 21_000);
    assert!(
        fixture
            .leases
            .read_lease(&plan.previous_lease.lease_id)
            .unwrap()
            .is_none()
    );
}

#[test]
fn pruned_original_cannot_be_recreated_from_the_plan() {
    let fixture = Fixture::new();
    let plan = fixture.plan();
    assert_eq!(fixture.leases.prune_expired_leases(1).unwrap(), 1);
    fixture.no_commit(&plan, 21_000);
}

#[test]
fn preparation_rejects_invalid_lifetime_revision_and_time() {
    let fixture = Fixture::new();
    let before = fixture.leases.frontier().unwrap();
    for lifetime in [0, 300_001] {
        assert!(prepare_existing(&fixture.config, &fixture.leases, 21_000, lifetime).is_err());
    }
    assert!(prepare_existing(&fixture.config, &fixture.leases, u64::MAX, 30_000).is_err());
    assert!(prepare_existing(&fixture.config, &fixture.leases, 9_999, 30_000).is_err());
    let mut wrong = fixture.config.clone();
    wrong.lease_revision = 2;
    assert!(prepare_existing(&wrong, &fixture.leases, 21_000, 30_000).is_err());
    assert_eq!(fixture.leases.frontier().unwrap(), before);
}

#[test]
fn unknown_plan_fields_are_rejected() {
    let fixture = Fixture::new();
    let mut value = serde_json::to_value(fixture.plan()).unwrap();
    value["peer_authorized"] = serde_json::json!(true);
    assert!(serde_json::from_value::<HostIssuerLeaseRenewalPlan>(value).is_err());
}

#[test]
fn ordinary_process_is_rejected_before_opening_config() {
    // SAFETY: actual credential observation without mutation.
    if unsafe { libc::getuid() } == 0 && unsafe { libc::geteuid() } == 0 {
        return;
    }
    let fixture = Fixture::new();
    let missing = fixture._root.path().join("does-not-exist");
    assert_eq!(
        prepare_host_issuer_lease_renewal(&missing, 30_000)
            .unwrap_err()
            .kind(),
        io::ErrorKind::PermissionDenied
    );
    assert_eq!(
        commit_host_issuer_lease_renewal(&missing, &fixture.plan())
            .unwrap_err()
            .kind(),
        io::ErrorKind::PermissionDenied
    );
    assert!(!missing.exists());
}
