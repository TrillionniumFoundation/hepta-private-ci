//! Concrete kernel.authority consumer for the runtime.fleet allocation owner.
//!
//! This port does not accept an arbitrary effect closure. It computes the exact
//! authority binding from one `AllocationGrant`, revalidates the live generic
//! authority lease at the final owner boundary, and only then calls
//! `LeaseLedger::issue`.

use codex_hepta_contracts::VerifiedUseTokenWitnessV1;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_contracts::authority_lease::AuthorityLeaseError;
use codex_hepta_contracts::authority_lease::AuthorityLeaseVerifier;
use codex_hepta_contracts::authority_lease::dispatch_authority_lease_with_witness;
use sha2::Digest;
use sha2::Sha256;
use std::fmt;

use crate::lease_ledger::AllocationGrant;
use crate::lease_ledger::Error as LeaseLedgerError;
use crate::lease_ledger::GrantUseWitnessV1;
use crate::lease_ledger::LeaseLedger;
use crate::lease_ledger::LeaseReceipt;

/// Read/verify-only kernel.authority composition for concrete fleet mutations.
#[derive(Clone, Debug)]
pub struct FleetAuthorityPort {
    verifier: AuthorityLeaseVerifier,
}

impl FleetAuthorityPort {
    pub fn new(verifier: AuthorityLeaseVerifier) -> Self {
        Self { verifier }
    }

    /// Issue one fleet allocation under the exact current generic authority
    /// lease. The binding is computed from the allocation rather than supplied
    /// by the caller, preventing a caller from verifying one scope and mutating
    /// another.
    pub fn issue(
        &self,
        ledger: &mut LeaseLedger,
        lease_id: &str,
        expected_lease_revision: u64,
        grant: AllocationGrant,
    ) -> Result<LeaseReceipt, FleetAuthorityError> {
        self.issue_with_witness(ledger, lease_id, expected_lease_revision, grant)
            .map(|(receipt, _witness)| receipt)
    }

    /// Same concrete owner mutation as `issue`, but returns the canonical
    /// non-authorizing audit witness for durable evidence composition.
    pub fn issue_with_witness(
        &self,
        ledger: &mut LeaseLedger,
        lease_id: &str,
        expected_lease_revision: u64,
        grant: AllocationGrant,
    ) -> Result<(LeaseReceipt, VerifiedUseTokenWitnessV1), FleetAuthorityError> {
        let binding = allocation_binding(&grant)?;
        let token = self
            .verifier
            .verify_use(lease_id, expected_lease_revision, &binding)
            .map_err(FleetAuthorityError::Authority)?;
        let (result, witness) =
            dispatch_authority_lease_with_witness(&self.verifier, token, &binding, |_| {
                ledger.issue(grant)
            })
            .map_err(FleetAuthorityError::Authority)?;
        let receipt = result.map_err(FleetAuthorityError::Fleet)?;
        Ok((receipt, witness))
    }

    pub fn binding_for_issue(
        grant: &AllocationGrant,
    ) -> Result<AuthorityLeaseBinding, FleetAuthorityError> {
        allocation_binding(grant)
    }

    pub fn verify_final_use(
        ledger: &LeaseLedger,
        allocation_id: &str,
        expected_lease_generation: u64,
        expected_host_id: &str,
        expected_host_generation: u64,
        semantic_digest: &str,
    ) -> Result<GrantUseWitnessV1, FleetAuthorityError> {
        ledger
            .verify_use(
                allocation_id,
                expected_lease_generation,
                expected_host_id,
                expected_host_generation,
                semantic_digest,
            )
            .map_err(FleetAuthorityError::Fleet)
    }
}

fn allocation_binding(
    grant: &AllocationGrant,
) -> Result<AuthorityLeaseBinding, FleetAuthorityError> {
    let payload_sha256 = parse_sha256(&grant.semantic_digest)?;
    let resource_digest = grant
        .resources
        .semantic_digest()
        .map_err(|_| FleetAuthorityError::InvalidResourceVector)?;
    let mut scope = Sha256::new();
    scope.update(b"hepta.kernel.authority.runtime-fleet.issue.v2\0");
    hash_text(&mut scope, &grant.allocation_id);
    hash_text(&mut scope, &grant.request_id);
    hash_text(&mut scope, &grant.host_id);
    hash_text(&mut scope, &grant.failure_domain_id);
    hash_u64(&mut scope, grant.host_generation);
    hash_u64(&mut scope, grant.authority_epoch);
    hash_u64(&mut scope, grant.lease_generation);
    hash_u64(&mut scope, grant.expires_at_ms);
    hash_text(&mut scope, &resource_digest);
    Ok(AuthorityLeaseBinding {
        principal_id: grant.principal_id.clone(),
        operation_class: "fleet.allocate".into(),
        destination_id: "runtime.fleet".into(),
        scope_sha256: scope.finalize().into(),
        payload_sha256,
    })
}

fn hash_text(hash: &mut Sha256, value: &str) {
    hash.update((value.len() as u64).to_be_bytes());
    hash.update(value.as_bytes());
}

fn hash_u64(hash: &mut Sha256, value: u64) {
    hash.update(value.to_be_bytes());
}

fn parse_sha256(value: &str) -> Result<[u8; 32], FleetAuthorityError> {
    if value.len() != 64 || value.bytes().all(|byte| byte == b'0') {
        return Err(FleetAuthorityError::InvalidSemanticDigest);
    }
    let mut digest = [0_u8; 32];
    for (index, pair) in value.as_bytes().chunks_exact(2).enumerate() {
        digest[index] = (hex(pair[0])? << 4) | hex(pair[1])?;
    }
    Ok(digest)
}

fn hex(value: u8) -> Result<u8, FleetAuthorityError> {
    match value {
        b'0'..=b'9' => Ok(value - b'0'),
        b'a'..=b'f' => Ok(value - b'a' + 10),
        _ => Err(FleetAuthorityError::InvalidSemanticDigest),
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FleetAuthorityError {
    InvalidSemanticDigest,
    InvalidResourceVector,
    Authority(AuthorityLeaseError),
    Fleet(LeaseLedgerError),
}

impl fmt::Display for FleetAuthorityError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}

impl std::error::Error for FleetAuthorityError {}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use crate::ResourceVectorV1;
    use crate::lease_ledger::FleetClock;
    use crate::lease_ledger::FleetClockError;
    use crate::lease_ledger::HostObservation;
    use codex_hepta_contracts::AuthorityClock;
    use codex_hepta_contracts::AuthorityTrustError;
    use codex_hepta_contracts::VerifiedUseAuthorityRefV1;
    use codex_hepta_contracts::VerifiedUseBoundaryV1;
    use codex_hepta_contracts::authority_lease::AuthorityLease;
    use codex_hepta_contracts::authority_lease::AuthorityLeaseFrontier;
    use codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry;
    use sha2::Digest;
    use std::os::unix::fs::PermissionsExt;
    use std::sync::Arc;

    #[derive(Debug)]
    struct FixedClock(u64);

    impl AuthorityClock for FixedClock {
        fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
            Ok(self.0)
        }
    }

    impl FleetClock for FixedClock {
        fn now_unix_ms(&self) -> Result<u64, FleetClockError> {
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
            resources: ResourceVectorV1::physical(100, 1024, 0),
            semantic_digest: format!("{:x}", Sha256::digest(b"fleet-allocation-one")),
            revoked: false,
        }
    }

    fn ledger() -> LeaseLedger {
        let mut ledger = LeaseLedger::with_clock(Arc::new(FixedClock(2_000)));
        ledger
            .admit_host(HostObservation {
                host_id: "host-one".into(),
                failure_domain_id: "rack-one".into(),
                generation: 1,
                observed_at_ms: 1_000,
                valid_until_ms: 10_000,
                capacity: ResourceVectorV1::physical(1_000, 1 << 20, 1_000),
            })
            .unwrap();
        ledger
    }

    #[test]
    fn allocation_issue_consumes_exact_live_kernel_authority_lease() {
        let directory = tempfile::tempdir().unwrap();
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        let registry = AuthorityLeaseRegistry::open_state_dir_with_clock(
            directory.path(),
            "security-authority".into(),
            AuthorityLeaseFrontier::for_empty_epoch(7).unwrap(),
            Arc::new(FixedClock(2_000)),
        )
        .unwrap();
        let grant = grant();
        let binding = FleetAuthorityPort::binding_for_issue(&grant).unwrap();
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
            .unwrap();
        let port = FleetAuthorityPort::new(registry.verifier());
        let mut ledger = ledger();
        let (receipt, witness) = port
            .issue_with_witness(&mut ledger, "fleet-issue-one", 1, grant.clone())
            .unwrap();
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

        registry.revoke("fleet-issue-one", 1, [9; 32]).unwrap();
        assert_eq!(
            port.issue(&mut ledger, "fleet-issue-one", 2, grant)
                .unwrap_err(),
            FleetAuthorityError::Authority(AuthorityLeaseError::Revoked)
        );
    }

    #[test]
    fn allocation_binding_changes_when_owner_mutation_semantics_change() {
        let first = grant();
        let first_binding = FleetAuthorityPort::binding_for_issue(&first).unwrap();
        let mut changed = first;
        changed.resources.cpu_millis += 1;
        let changed_binding = FleetAuthorityPort::binding_for_issue(&changed).unwrap();
        assert_ne!(first_binding.scope_sha256, changed_binding.scope_sha256);
        assert_eq!(first_binding.payload_sha256, changed_binding.payload_sha256);
    }
}
