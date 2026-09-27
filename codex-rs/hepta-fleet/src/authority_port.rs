//! Concrete kernel.authority consumer for the runtime.fleet allocation owner.
//!
//! The binding is derived from the complete allocation mutation. Callers cannot
//! verify one scope and then substitute a different grant at the owner boundary.

use std::fmt;

use codex_hepta_contracts::VerifiedUseTokenWitnessV1;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_contracts::authority_lease::AuthorityLeaseError;
use codex_hepta_contracts::authority_lease::AuthorityLeaseVerifier;
use codex_hepta_contracts::authority_lease::dispatch_authority_lease_with_witness;
use sha2::Digest;
use sha2::Sha256;

use crate::RESOURCE_VECTOR_SCHEMA_VERSION;
use crate::lease_ledger::AllocationGrant;
use crate::lease_ledger::Error as LeaseLedgerError;
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

    /// Revalidates the exact issue binding and returns a non-authorizing audit
    /// witness. Durable owners call this immediately before their transaction
    /// and persist the witness in the same operation receipt as the grant.
    pub fn verify_issue_witness(
        &self,
        lease_id: &str,
        expected_lease_revision: u64,
        grant: &AllocationGrant,
    ) -> Result<VerifiedUseTokenWitnessV1, FleetAuthorityError> {
        let binding = allocation_binding(grant)?;
        let token = self
            .verifier
            .verify_use(lease_id, expected_lease_revision, &binding)
            .map_err(FleetAuthorityError::Authority)?;
        let (_, witness) =
            dispatch_authority_lease_with_witness(&self.verifier, token, &binding, |_| ())
                .map_err(FleetAuthorityError::Authority)?;
        Ok(witness)
    }

    pub fn verify_renew_witness(
        &self,
        lease_id: &str,
        expected_lease_revision: u64,
        grant: &AllocationGrant,
        expires_at_ms: u64,
    ) -> Result<VerifiedUseTokenWitnessV1, FleetAuthorityError> {
        let binding = lease_mutation_binding(grant, "fleet.renew", expires_at_ms, false)?;
        self.verify_binding_witness(lease_id, expected_lease_revision, &binding)
    }

    pub fn verify_revoke_witness(
        &self,
        lease_id: &str,
        expected_lease_revision: u64,
        grant: &AllocationGrant,
    ) -> Result<VerifiedUseTokenWitnessV1, FleetAuthorityError> {
        let binding = lease_mutation_binding(grant, "fleet.revoke", grant.expires_at_ms, true)?;
        self.verify_binding_witness(lease_id, expected_lease_revision, &binding)
    }

    pub fn binding_for_issue(
        grant: &AllocationGrant,
    ) -> Result<AuthorityLeaseBinding, FleetAuthorityError> {
        allocation_binding(grant)
    }

    pub fn binding_for_renew(
        grant: &AllocationGrant,
        expires_at_ms: u64,
    ) -> Result<AuthorityLeaseBinding, FleetAuthorityError> {
        lease_mutation_binding(grant, "fleet.renew", expires_at_ms, false)
    }

    pub fn binding_for_revoke(
        grant: &AllocationGrant,
    ) -> Result<AuthorityLeaseBinding, FleetAuthorityError> {
        lease_mutation_binding(grant, "fleet.revoke", grant.expires_at_ms, true)
    }

    fn verify_binding_witness(
        &self,
        lease_id: &str,
        expected_lease_revision: u64,
        binding: &AuthorityLeaseBinding,
    ) -> Result<VerifiedUseTokenWitnessV1, FleetAuthorityError> {
        let token = self
            .verifier
            .verify_use(lease_id, expected_lease_revision, binding)
            .map_err(FleetAuthorityError::Authority)?;
        let (_, witness) =
            dispatch_authority_lease_with_witness(&self.verifier, token, binding, |_| ())
                .map_err(FleetAuthorityError::Authority)?;
        Ok(witness)
    }
}

fn allocation_binding(
    grant: &AllocationGrant,
) -> Result<AuthorityLeaseBinding, FleetAuthorityError> {
    let payload_sha256 = parse_sha256(&grant.semantic_digest)?;
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
    hash_u64(&mut scope, u64::from(RESOURCE_VECTOR_SCHEMA_VERSION));
    hash_u64(&mut scope, grant.resources.cpu_millis);
    hash_u64(&mut scope, grant.resources.memory_bytes);
    hash_u64(&mut scope, grant.resources.accelerator_millis);
    hash_u64(&mut scope, grant.resources.concurrent_turns);
    hash_u64(&mut scope, grant.resources.tool_processes);
    hash_u64(&mut scope, grant.resources.turn_queue_slots);
    Ok(AuthorityLeaseBinding {
        principal_id: grant.principal_id.clone(),
        operation_class: "fleet.allocate".into(),
        destination_id: "runtime.fleet".into(),
        scope_sha256: scope.finalize().into(),
        payload_sha256,
    })
}

fn lease_mutation_binding(
    grant: &AllocationGrant,
    operation_class: &str,
    target_expires_at_ms: u64,
    target_revoked: bool,
) -> Result<AuthorityLeaseBinding, FleetAuthorityError> {
    let payload_sha256 = parse_sha256(&grant.semantic_digest)?;
    let mut scope = Sha256::new();
    scope.update(b"hepta.kernel.authority.runtime-fleet.lease-mutation.v1\0");
    hash_text(&mut scope, operation_class);
    hash_text(&mut scope, &grant.allocation_id);
    hash_text(&mut scope, &grant.request_id);
    hash_text(&mut scope, &grant.principal_id);
    hash_text(&mut scope, &grant.host_id);
    hash_text(&mut scope, &grant.failure_domain_id);
    hash_u64(&mut scope, grant.host_generation);
    hash_u64(&mut scope, grant.authority_epoch);
    hash_u64(&mut scope, grant.lease_generation);
    hash_u64(&mut scope, grant.expires_at_ms);
    hash_u64(&mut scope, target_expires_at_ms);
    scope.update([u8::from(target_revoked)]);
    hash_u64(&mut scope, u64::from(RESOURCE_VECTOR_SCHEMA_VERSION));
    for value in [
        grant.resources.cpu_millis,
        grant.resources.memory_bytes,
        grant.resources.accelerator_millis,
        grant.resources.concurrent_turns,
        grant.resources.tool_processes,
        grant.resources.turn_queue_slots,
    ] {
        hash_u64(&mut scope, value);
    }
    Ok(AuthorityLeaseBinding {
        principal_id: grant.principal_id.clone(),
        operation_class: operation_class.to_string(),
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
    Authority(AuthorityLeaseError),
    Fleet(LeaseLedgerError),
}

impl fmt::Display for FleetAuthorityError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for FleetAuthorityError {}

#[cfg(all(test, unix))]
#[path = "authority_port_tests.rs"]
mod tests;
