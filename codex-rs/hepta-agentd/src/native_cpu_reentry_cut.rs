//! Reopen the exact original physical cut after the failed child has retired.
//! An observation here is not a live writer, grant or replacement Current.

use super::*;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_memory::CognitiveCheckpointReceipt;
use codex_hepta_memory::VerifiedCognitiveMaterial;

impl Installation {
    pub(super) fn prepare_failed_activation(
        &mut self,
        deadline: u64,
    ) -> io::Result<serde_json::Value> {
        let (failed, lifecycle) = self.retired_failed_activation()?;
        let pending = self.activation.as_ref().unwrap();
        let spec = pending.spec.clone();
        let failed_peer = pending.peer.clone();
        let fault = pending.fault_observation.clone();
        // The preceding physical guard can still be held if failure occurred
        // before install. Release only that guard, then independently reopen
        // the archive selected by the original durable whole head.
        drop(self.recovery.take());
        let directory = RootAuthorityDirectory::open(&self.checkpoint).map_err(error)?;
        let observed = crate::HostCognitiveCheckpoint::retained_head_for_root(directory.clone())
            .map_err(error)?;
        let material = self.retained_activation_material(&observed)?;
        let retired = if observed.head.peer_lifetime.boot_id == failed_peer.boot_id {
            crate::RetiredCheckpointPublisher::observe(observed.head.peer_lifetime.clone())
                .map_err(error)?
        } else {
            let (actual, retired) = crate::HostCognitiveCheckpoint::observe_previous_boot_for_root(
                directory.clone(),
                &self.clock,
                &material,
            )
            .map_err(error)?;
            if actual != observed {
                return Err(invalid(
                    "previous boot head changed during failed activation reconciliation",
                ));
            }
            retired
        };
        let registered = crate::HostCognitiveCheckpointRegistration {
            owner_agent_id: observed.head.owner_agent_id.clone(),
            publisher_epoch: observed.head.publisher_epoch,
            writer_binding: observed.head.writer_binding.clone(),
            peer_lifetime: observed.head.peer_lifetime.clone(),
        };
        let previous = crate::HostCognitiveCheckpoint::read_retired_head_for_root(
            directory.clone(),
            &registered,
            &retired,
            &material,
        )
        .map_err(error)?;
        if previous != observed || previous.head.owner_agent_id != spec.agent_id {
            return Err(invalid(
                "actual failed activation changed the original protected cut",
            ));
        }
        let canonical = self.issuer.retained_writer_state_for_root()?;
        let writer = &canonical.registration;
        let binding = cold_open::writer_binding(&self.config, writer, &canonical.proof)?;
        let installed = binding == previous.head.writer_binding;
        let authorization = if installed {
            if writer.registered_agent_id != spec.agent_id
                || writer.spawn_generation > spec.generation
            {
                return Err(invalid(
                    "installed original proof differs from the failed Agent",
                ));
            }
            recovery::RecoveryAuthorization::Installed
        } else {
            let old = &previous.head;
            if writer.registered_agent_id != spec.agent_id
                || writer.spawn_generation != spec.generation
                || writer.local_lease_id != old.writer_binding.lease_id
                || old.writer_binding.generation.checked_add(1)
                    != Some(writer.local_lease_generation)
                || writer.authority_lease.authority_epoch != old.writer_binding.authority_epoch
                || writer.owner_epoch <= old.writer_binding.owner_epoch
                || failed_peer == old.peer_lifetime
                || failed_peer.uid != old.peer_lifetime.uid
            {
                return Err(invalid(
                    "canonical proof is not the exact unactivated successor",
                ));
            }
            recovery::RecoveryAuthorization::Unactivated { failed }
        };
        let policies = canonical
            .policies
            .iter()
            .filter(|policy| {
                policy.subject_id == spec.agent_id.as_str()
                    && policy.destination_id == codex_hepta_memory::HOS2_DESTINATION_V1
            })
            .collect::<Vec<_>>();
        if policies.len() != 2
            || policies.iter().any(|policy| policy.lifetime_ms != 5_000)
            || policies[0].scope_sha256 == policies[1].scope_sha256
        {
            return Err(invalid(
                "original finite CPU policy slots changed during reconciliation",
            ));
        }
        let scopes = [policies[0].scope_sha256, policies[1].scope_sha256];
        let before = self
            .leases
            .read_unretired_for_principal(
                spec.agent_id.as_str(),
                codex_hepta_contracts::authority_lease::MAX_AUTHORITY_LEASES,
            )
            .map_err(error)?;
        let mut revoked = Vec::new();
        for lease in &before.leases {
            remaining(deadline)?;
            let reason = Sha256::digest(
                serde_json::to_vec(&(
                    "native-root-failed-activation-retirement.v1",
                    &failed_peer,
                    &previous.token,
                    lease,
                ))
                .map_err(error)?,
            )
            .into();
            revoked.push(
                self.leases
                    .revoke(&lease.lease_id, lease.revision, reason)
                    .map_err(error)?,
            );
        }
        let after = self
            .leases
            .read_unretired_for_principal(
                spec.agent_id.as_str(),
                codex_hepta_contracts::authority_lease::MAX_AUTHORITY_LEASES,
            )
            .map_err(error)?;
        if !after.leases.is_empty() {
            return Err(invalid(
                "actual failed Agent still has unretired original authority",
            ));
        }
        let expiry = previous
            .head
            .writer_binding
            .expires_at_unix_seconds
            .checked_mul(1000)
            .ok_or_else(|| invalid("actual original local lease expiry overflow"))?;
        let expired_at = loop {
            remaining(deadline)?;
            let actual = self.clock.now_unix_ms().map_err(error)?;
            if actual >= expiry {
                break actual;
            }
            std::thread::sleep(Duration::from_millis(20));
        };
        let consumers = self
            .config
            .consumers
            .as_ref()
            .ok_or_else(|| invalid("original consumer registration absent"))?;
        let load = |slot: &crate::HostAuthorityConsumerConfig| -> io::Result<FinalUseFrontier> {
            HostAuthorityFrontierStore::<FinalUseFrontier>::open(
                RootAuthorityDirectory::open(&slot.state_dir).map_err(error)?,
                slot.owner_id.clone(),
            )
            .map_err(error)?
            .load(&slot.owner_id)
            .map_err(error)
        };
        let frontiers = [load(&consumers.device)?, load(&consumers.notes)?];
        if frontiers.iter().any(|frontier| {
            frontier.authority_epoch > canonical.revocations.authority_epoch
                || (frontier.authority_epoch == canonical.revocations.authority_epoch
                    && frontier.revocation_revision > canonical.revocations.revision)
        }) {
            return Err(invalid(
                "actual consumer frontier exceeds the original issuer head",
            ));
        }
        material.verify_unchanged().map_err(error)?;
        if self.issuer.retained_writer_state_for_root()? != canonical
            || crate::HostCognitiveCheckpoint::read_retired_head_for_root(
                directory,
                &registered,
                &retired,
                &material,
            )
            .map_err(error)?
                != previous
        {
            return Err(invalid(
                "original canonical proof or physical cut changed during reconciliation",
            ));
        }
        let observation = serde_json::json!({
            "failed_spawn_generation":spec.generation,"failed_peer":failed_peer,
            "fault":fault,
            "registry_failed":lifecycle,
            "mode":if installed {"installed"} else {"unactivated"},
            "previous":previous,"canonical_writer":canonical.registration,
            "canonical_proof_sha256":canonical.proof.sha256().map_err(error)?,
            "issuer_sequence":canonical.sequence,"registry_before":before,
            "revocations_applied":revoked,"registry_after":after,
            "observed_unix_ms":expired_at,"local_expiry_unix_ms":expiry,
            "device_frontier":frontiers[0],"notes_frontier":frontiers[1],
        });
        self.initial = previous.head.last_current.clone();
        self.config.writer = Some(canonical.registration.clone());
        self.scopes = scopes;
        self.recovery = Some(recovery::PreparedRecovery {
            authorization,
            previous,
            writer: canonical.registration,
            proof: canonical.proof,
            retired,
            material,
            frontiers,
        });
        self.activation = None;
        self.last_activation_reconciliation = Some(observation.clone());
        Ok(observation)
    }

    fn retained_activation_material(
        &self,
        head: &CognitiveCheckpointReceipt,
    ) -> io::Result<VerifiedCognitiveMaterial> {
        let digest = codex_hepta_contracts::Sha256Digest::for_bytes(
            &serde_json::to_vec(&head.head.last_current).map_err(error)?,
        );
        let image = HeptaFleetRoot::parse(self.archive.join(digest.as_str()))
            .map_err(error)?
            .layout()
            .agent(&head.head.owner_agent_id);
        runtime()?
            .block_on(CognitiveStore::verify_retained_root_material(
                &image,
                &head.head.last_current,
            ))
            .map_err(error)
    }
}
