//! Explicit trusted-launcher rotation in the one canonical issuer frontier.
use super::*;

impl DeploymentFinalUseIssuer {
    /// Replace exactly one retained writer after its original registry lease
    /// is retired and the complete successor is live under the same owner.
    /// This administrative API is never exposed on an ordinary peer lane.
    /// The launcher must separately retain and prove old publisher quiescence;
    /// lease retirement alone does not prove process exit or checkpoint safety.
    /// The successor is supplied from the trusted launcher's captured exact
    /// registered identity/peer, including its actual Fleet spawn generation.
    /// Failed starts may skip spawn values; never infer spawn from local lease
    /// generation, and never deserialize this admission from a peer request.
    ///
    /// A lost ACK may reconcile only the exact successor already retained here.
    /// Any error may follow a durable counter reservation or proof replacement:
    /// do not roll back either store or invent another generation on retry.
    /// Checkpoint adoption is a separate CAS; cross-store disagreement refuses
    /// runtime opening until exact trusted reconciliation, never fresh genesis.
    pub fn rotate_writer_authorization(
        &self,
        predecessor: &HostAuthorityWriterRegistration,
        predecessor_proof: &HostSignedWriterAuthorizationV1,
        successor: &HostAuthorityWriterRegistration,
    ) -> io::Result<HostSignedWriterAuthorizationV1> {
        // Use the verifier retained by the canonical protected factory, never
        // a caller-supplied lookalike owner with equal serialized lease data.
        let verifier = &self
            .lease
            .as_ref()
            .ok_or_else(|| io::Error::other("protected issuer required"))?
            .verifier;
        predecessor.validate()?;
        successor.validate()?;
        if predecessor.registered_agent_id != successor.registered_agent_id
            || predecessor.local_lease_id != successor.local_lease_id
            || predecessor.local_lease_generation.checked_add(1)
                != Some(successor.local_lease_generation)
            || predecessor.spawn_generation >= successor.spawn_generation
            || predecessor.owner_epoch >= successor.owner_epoch
            || predecessor.authority_lease.binding.principal_id
                != successor.authority_lease.binding.principal_id
            || predecessor.authority_lease.binding.operation_class
                != successor.authority_lease.binding.operation_class
            || predecessor.authority_lease.binding.destination_id
                != successor.authority_lease.binding.destination_id
            || predecessor.authority_lease.binding.scope_sha256
                != successor.authority_lease.binding.scope_sha256
            || predecessor.authority_lease.authority_epoch
                != successor.authority_lease.authority_epoch
        {
            return Err(io::Error::other("invalid writer successor"));
        }
        let lease = &successor.authority_lease;
        let token = verifier
            .verify_use(&lease.lease_id, lease.revision, &lease.binding)
            .map_err(root::lease_error)?;
        verifier
            .with_retired_predecessor_boundary(
                &predecessor.authority_lease,
                token,
                &lease.binding,
                |actual, _, _| {
                    // The original owner mutex remains held. Do not reenter
                    // read/verify/with_live/with_binding on this registry.
                    if actual != lease {
                        return Err(io::Error::other("successor lease changed"));
                    }
                    let _guard = self
                        .request_lock
                        .lock()
                        .map_err(|_| io::Error::other("issuer fenced"))?;
                    let state = self.store.load(STATE_OWNER).map_err(io::Error::other)?;
                    self.validate_writer_proof_identity(&state, predecessor, predecessor_proof)?;
                    let retained = state
                        .writer_authorization
                        .as_ref()
                        .ok_or_else(|| io::Error::other("writer not provisioned"))?;
                    if retained != predecessor_proof {
                        // Exact lost-ACK reconciliation: no fresh sequence and
                        // no acceptance of an unrelated retained registration.
                        self.validate_writer_proof(&state, successor, retained)?;
                        return Ok(retained.clone());
                    }
                    let now = self.clock.now_unix_ms().map_err(io::Error::other)?;
                    validate_writer_time(successor, state.head.authority_epoch, now)?;
                    self.retain_writer_authorization(&state, successor, now)
                },
            )
            .map_err(root::lease_error)?
    }
}

#[path = "deployment_writer_reentry.rs"]
mod reentry;
