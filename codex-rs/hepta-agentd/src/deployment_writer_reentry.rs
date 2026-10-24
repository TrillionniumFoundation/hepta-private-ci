//! Replace an original authorization whose writer was never installed.
//! The original local generation is not skipped or assigned to two live peers.

use super::*;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_memory::CognitiveCheckpointReceipt;
use codex_hepta_memory::VerifiedCognitiveMaterial;

impl DeploymentFinalUseIssuer {
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
