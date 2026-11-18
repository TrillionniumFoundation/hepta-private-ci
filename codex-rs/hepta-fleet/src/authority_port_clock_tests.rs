use super::FleetAuthorityError;
use super::FleetAuthorityPort;
use crate::lease_ledger::AllocationGrant;
use crate::lease_ledger::Error as LeaseLedgerError;
use crate::lease_ledger::HostObservation;
use crate::lease_ledger::LeaseLedger;
use crate::lease_ledger::Resources;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseFrontier;
use codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry;
use pretty_assertions::assert_eq;
use sha2::Digest;
use sha2::Sha256;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;

#[derive(Debug)]
struct FixedClock {
    now_unix_ms: u64,
}

impl AuthorityClock for FixedClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(self.now_unix_ms)
    }
}

#[test]
fn caller_clock_cannot_backdate_an_expired_allocation() -> Result<(), Box<dyn std::error::Error>> {
    let directory = tempfile::tempdir()?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    let authority_epoch = 7;
    let lease_revision = 1;
    let registry = AuthorityLeaseRegistry::open_state_dir_with_clock(
        directory.path(),
        "security-authority".into(),
        AuthorityLeaseFrontier::for_empty_epoch(authority_epoch)?,
        Arc::new(FixedClock { now_unix_ms: 9_500 }),
    )?;
    let grant = AllocationGrant {
        allocation_id: "expired-allocation".into(),
        request_id: "request-one".into(),
        principal_id: "agent-one".into(),
        host_id: "host-one".into(),
        failure_domain_id: "rack-one".into(),
        host_generation: 1,
        authority_epoch,
        lease_generation: 1,
        expires_at_ms: 9_000,
        resources: Resources {
            cpu_millis: 100,
            memory_bytes: 1024,
            accelerator_millis: 0,
        },
        semantic_digest: format!("{:x}", Sha256::digest(b"expired-allocation")),
        revoked: false,
    };
    let binding = FleetAuthorityPort::binding_for_issue(&grant)?;
    registry.put_lease(
        AuthorityLease {
            schema_version: 1,
            lease_id: "fleet-expired-allocation".into(),
            authority_epoch,
            revision: lease_revision,
            binding,
            issued_at_unix_ms: 1_000,
            expires_at_unix_ms: 9_800,
        },
        /*expected_revision*/ 0,
    )?;
    let mut ledger = LeaseLedger::new();
    ledger.admit_host(HostObservation {
        host_id: "host-one".into(),
        failure_domain_id: "rack-one".into(),
        generation: 1,
        observed_at_ms: 1_000,
        valid_until_ms: 10_000,
        capacity: Resources {
            cpu_millis: 1_000,
            memory_bytes: 1 << 20,
            accelerator_millis: 1_000,
        },
    })?;
    let port = FleetAuthorityPort::new(registry.verifier());
    let untrusted_caller_now_ms = 2_000;
    assert_eq!(
        port.issue(
            &mut ledger,
            "fleet-expired-allocation",
            lease_revision,
            untrusted_caller_now_ms,
            grant,
        ),
        Err(FleetAuthorityError::Fleet(LeaseLedgerError::InvalidTime))
    );
    Ok(())
}
