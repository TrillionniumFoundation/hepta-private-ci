use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::VerifiedUseAuthorityRefV1;
use codex_hepta_contracts::VerifiedUseBoundaryV1;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseFrontier;
use codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry;
use pretty_assertions::assert_eq;
use sha2::Digest;

use super::*;
use crate::ResourceVectorV1;
use crate::lease_ledger::HostObservation;

#[derive(Debug)]
struct FixedClock(u64);

impl AuthorityClock for FixedClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(self.0)
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
        resources: ResourceVectorV1 {
            cpu_millis: 100,
            memory_bytes: 1_024,
            accelerator_millis: 0,
            concurrent_turns: 1,
            tool_processes: 2,
            turn_queue_slots: 8,
        },
        semantic_digest: format!("{:x}", Sha256::digest(b"fleet-allocation-one")),
        revoked: false,
    }
}

fn ledger(clock: Arc<FixedClock>) -> LeaseLedger {
    let mut ledger = LeaseLedger::with_clock(clock);
    ledger
        .admit_host(HostObservation {
            host_id: "host-one".into(),
            failure_domain_id: "rack-one".into(),
            generation: 1,
            observed_at_ms: 1_000,
            valid_until_ms: 10_000,
            capacity: ResourceVectorV1 {
                cpu_millis: 1_000,
                memory_bytes: 1 << 20,
                accelerator_millis: 0,
                concurrent_turns: 8,
                tool_processes: 16,
                turn_queue_slots: 256,
            },
        })
        .expect("host");
    ledger
}

#[test]
fn allocation_issue_consumes_exact_live_kernel_authority_lease() {
    let directory = tempfile::tempdir().expect("authority directory");
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))
        .expect("private authority directory");
    let clock = Arc::new(FixedClock(2_000));
    let registry = AuthorityLeaseRegistry::open_state_dir_with_clock(
        directory.path(),
        "security-authority".into(),
        AuthorityLeaseFrontier::for_empty_epoch(7).expect("frontier"),
        clock.clone(),
    )
    .expect("authority registry");
    let grant = grant();
    let binding = FleetAuthorityPort::binding_for_issue(&grant).expect("binding");
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
            /*expected_revision*/ 0,
        )
        .expect("put lease");
    let port = FleetAuthorityPort::new(registry.verifier());
    let mut ledger = ledger(clock);
    let (receipt, witness) = port
        .issue_with_witness(&mut ledger, "fleet-issue-one", 1, grant.clone())
        .expect("issue");
    assert_eq!(receipt.allocation_id, "allocation-one");
    assert_eq!(witness.boundary, VerifiedUseBoundaryV1::DispatchEntry);
    assert_eq!(witness.authority_epoch, 7);
    match witness.authority_ref {
        VerifiedUseAuthorityRefV1::AuthorityLease(reference) => {
            assert_eq!(reference.owner_id, "security-authority");
            assert_eq!(reference.lease_id, "fleet-issue-one");
            assert_eq!(reference.lease_revision, 1);
            assert_ne!(reference.binding_sha256, [0; 32]);
        }
        other => panic!("unexpected authority witness: {other:?}"),
    }

    registry
        .revoke("fleet-issue-one", /*expected_revision*/ 1, [9; 32])
        .expect("revoke authority lease");
    assert_eq!(
        port.issue(&mut ledger, "fleet-issue-one", 2, grant)
            .expect_err("revoked lease must fail"),
        FleetAuthorityError::Authority(AuthorityLeaseError::Revoked)
    );
}

#[test]
fn allocation_binding_changes_for_every_resource_axis() {
    let first = grant();
    let first_binding = FleetAuthorityPort::binding_for_issue(&first).expect("binding");
    let mutations: [fn(&mut AllocationGrant); 6] = [
        |grant: &mut AllocationGrant| grant.resources.cpu_millis += 1,
        |grant: &mut AllocationGrant| grant.resources.memory_bytes += 1,
        |grant: &mut AllocationGrant| grant.resources.accelerator_millis += 1,
        |grant: &mut AllocationGrant| grant.resources.concurrent_turns += 1,
        |grant: &mut AllocationGrant| grant.resources.tool_processes += 1,
        |grant: &mut AllocationGrant| grant.resources.turn_queue_slots += 1,
    ];
    for mutate in mutations {
        let mut changed = first.clone();
        mutate(&mut changed);
        let changed_binding = FleetAuthorityPort::binding_for_issue(&changed).expect("binding");
        assert_ne!(first_binding.scope_sha256, changed_binding.scope_sha256);
        assert_eq!(first_binding.payload_sha256, changed_binding.payload_sha256);
    }
}
