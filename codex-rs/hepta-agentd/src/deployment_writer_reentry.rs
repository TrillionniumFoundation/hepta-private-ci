//! Replace an original authorization whose writer was never installed.
//! The original local generation is not skipped or assigned to two live peers.

use super::*;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_memory::CognitiveCheckpointReceipt;
use codex_hepta_memory::VerifiedCognitiveMaterial;

/// Read-only original canonical metadata for trusted Root reconciliation.
/// There is no verified-use token, live lease assertion or signing operation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct RetainedWriterStateForRoot {
    pub(crate) registration: HostAuthorityWriterRegistration,
    pub(crate) proof: HostSignedWriterAuthorizationV1,
    pub(crate) policies: Vec<DeploymentGrantPolicy>,
    pub(crate) revocations: FinalUseRevocations,
    pub(crate) sequence: u64,
}

impl DeploymentFinalUseIssuer {
    /// Observe the exact original signed identity even after its time-limited
    /// runtime authorization ended. The protected factory must already have
    /// checked the independently installed public-key pin. This read neither
    /// retires a registry lease nor admits a successor or checkpoint.
    pub(crate) fn retained_writer_state_for_root(&self) -> io::Result<RetainedWriterStateForRoot> {
        if unsafe { libc::geteuid() } != 0 || self.lease.is_none() {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "actual Root and protected canonical issuer required",
            ));
        }
        let _guard = self
            .request_lock
            .lock()
            .map_err(|_| io::Error::other("issuer fenced"))?;
        let state = self.store.load(STATE_OWNER).map_err(io::Error::other)?;
        let proof = state
            .writer_authorization
            .as_ref()
            .ok_or_else(|| io::Error::other("original retained writer absent"))?;
        let claims = &proof.claims;
        let registration = HostAuthorityWriterRegistration {
            registered_agent_id: claims.registered_agent_id.clone(),
            spawn_generation: claims.spawn_generation,
            owner_epoch: claims.owner_epoch,
            local_lease_id: claims.local_lease_id.clone(),
            local_lease_generation: claims.local_lease_generation,
            authority_lease: claims.authority_lease.clone(),
        };
        // This is the same strict signature/identity verifier used by original
        // retired-predecessor rotation. Do not call its runtime time verifier,
        // and do not turn this observation into a verified-use capability.
        self.validate_writer_proof_identity(&state, &registration, proof)?;
        let result = RetainedWriterStateForRoot {
            registration,
            proof: proof.clone(),
            policies: state.policies.clone(),
            revocations: state.head.clone(),
            sequence: state.sequence,
        };
        if self.store.load(STATE_OWNER).map_err(io::Error::other)? != state {
            return Err(io::Error::other(
                "canonical issuer changed during Root observation",
            ));
        }
        Ok(result)
    }

    /// Trusted Root only. A failed launch can leave its signed authorization
    /// durable while the complete checkpoint still names the retired original
    /// predecessor. Retire that failed lease, then replace its proof under the
    /// same registry, checkpoint publication lock and issuer CAS.
    ///
    /// A different actual spawn, owner epoch and authority-lease ID receive
    /// the SAME next local generation, which has not entered the checkpoint.
    /// Ordinary successful writer rotation retains its strict generation +1.
    /// No caller can substitute a serialized observation for the held original
    /// directory, material or actual retired/live publisher objects.
    pub(crate) fn replace_unactivated_writer_authorization(
        &self,
        failed: &HostAuthorityWriterRegistration,
        failed_proof: &HostSignedWriterAuthorizationV1,
        replacement: &HostAuthorityWriterRegistration,
        checkpoint: Arc<RootAuthorityDirectory>,
        previous: &CognitiveCheckpointReceipt,
        predecessor: &crate::RetiredCheckpointPublisher,
        failed_publisher: &crate::RetiredCheckpointPublisher,
        successor: &crate::RetainedCheckpointPublisher,
        material: &VerifiedCognitiveMaterial,
    ) -> io::Result<HostSignedWriterAuthorizationV1> {
        if unsafe { libc::geteuid() } != 0 {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "actual Root required",
            ));
        }
        failed.validate()?;
        replacement.validate()?;
        if failed.registered_agent_id != replacement.registered_agent_id
            || failed.local_lease_id != replacement.local_lease_id
            || failed.local_lease_generation != replacement.local_lease_generation
            || failed.spawn_generation >= replacement.spawn_generation
            || failed.owner_epoch >= replacement.owner_epoch
            || failed.authority_lease.lease_id == replacement.authority_lease.lease_id
            || failed.authority_lease.binding.principal_id
                != replacement.authority_lease.binding.principal_id
            || failed.authority_lease.binding.operation_class
                != replacement.authority_lease.binding.operation_class
            || failed.authority_lease.binding.destination_id
                != replacement.authority_lease.binding.destination_id
            || failed.authority_lease.binding.scope_sha256
                != replacement.authority_lease.binding.scope_sha256
            || failed.authority_lease.authority_epoch != replacement.authority_lease.authority_epoch
        {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "invalid unactivated writer replacement",
            ));
        }
        let verifier = &self
            .lease
            .as_ref()
            .ok_or_else(|| io::Error::other("protected canonical issuer required"))?
            .verifier;
        let lease = &replacement.authority_lease;
        let token = verifier
            .verify_use(&lease.lease_id, lease.revision, &lease.binding)
            .map_err(root::lease_error)?;
        verifier
            .with_retired_predecessor_boundary(
                &failed.authority_lease,
                token,
                &lease.binding,
                |actual, _, _| {
                    // Original registry -> checkpoint -> canonical issuer. The
                    // callback never re-enters either held original owner lock.
                    if actual != lease {
                        return Err(io::Error::new(
                            io::ErrorKind::PermissionDenied,
                            "replacement writer lease changed",
                        ));
                    }
                    let proof =
                        crate::HostCognitiveCheckpoint::with_unactivated_writer_cut_for_root(
                            checkpoint,
                            previous,
                            predecessor,
                            failed,
                            failed_publisher,
                            successor,
                            material,
                            || {
                                let _guard = self
                                    .request_lock
                                    .lock()
                                    .map_err(|_| io::Error::other("issuer fenced"))?;
                                let state =
                                    self.store.load(STATE_OWNER).map_err(io::Error::other)?;
                                self.validate_writer_proof_identity(&state, failed, failed_proof)?;
                                let retained = state
                                    .writer_authorization
                                    .as_ref()
                                    .ok_or_else(|| io::Error::other("writer not provisioned"))?;
                                if retained != failed_proof {
                                    // Only the exact already-retained replacement may
                                    // reconcile a lost reply; no new sequence is spent.
                                    self.validate_writer_proof(&state, replacement, retained)?;
                                    return Ok(retained.clone());
                                }
                                let now = self.clock.now_unix_ms().map_err(io::Error::other)?;
                                validate_writer_time(replacement, state.head.authority_epoch, now)?;
                                self.retain_writer_authorization(&state, replacement, now)
                            },
                        )?;
                    // Material, actual retirement and durable readback are all
                    // finished before the original final clock and held pidfd.
                    let now = self.clock.now_unix_ms().map_err(io::Error::other)?;
                    validate_writer_time(
                        replacement,
                        replacement.authority_lease.authority_epoch,
                        now,
                    )?;
                    successor.check_alive_for_root().map_err(io::Error::other)?;
                    Ok(proof)
                },
            )
            .map_err(root::lease_error)?
    }
}
