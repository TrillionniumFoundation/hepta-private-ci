//! Trusted native Root installation of one existing HOS2 namespace policy.
//! Exact request leases and signing reuse the original Notes effect-admission
//! mechanism; no nonce journal, key, sequence or lease registry is introduced.
use super::writer::WriterRegistrationExt;
use super::*;
use codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry;

pub(crate) struct RootNativeCpuGrantAdmission {
    registry: Arc<AuthorityLeaseRegistry>,
    writer: HostAuthorityWriterRegistration,
    proof: crate::HostSignedWriterAuthorizationV1,
    policy: Option<DeploymentGrantPolicy>,
}
fn denied(message: &'static str) -> io::Error {
    io::Error::new(io::ErrorKind::PermissionDenied, message)
}
impl RootNativeCpuGrantAdmission {
    pub(crate) fn from_registered_namespace(
        issuer: &DeploymentFinalUseIssuer,
        registry: Arc<AuthorityLeaseRegistry>,
        writer: HostAuthorityWriterRegistration,
        scope: [u8; 32],
        lifetime_ms: u64,
    ) -> io::Result<Self> {
        if unsafe { libc::geteuid() } != 0
            || std::process::id() != 1
            || scope == [0; 32]
            || !(1..=30_000).contains(&lifetime_ms)
        {
            return Err(denied(
                "actual native Root and finite namespace policy required",
            ));
        }
        writer.validate()?;
        let policy = DeploymentGrantPolicy {
            subject_id: writer.registered_agent_id.to_string(),
            destination_id: codex_hepta_memory::HOS2_DESTINATION_V1.into(),
            scope_sha256: scope,
            lifetime_ms,
        };
        let canonical = &issuer
            .lease
            .as_ref()
            .ok_or_else(|| denied("protected canonical issuer required"))?
            .verifier;
        let actual = registry
            .read_lease(&writer.authority_lease.lease_id)
            .map_err(root::lease_error)?
            .ok_or_else(|| denied("registered writer missing"))?;
        if actual.lease != writer.authority_lease {
            return Err(denied("registered writer changed"));
        }
        let token = registry
            .verifier()
            .verify_use(
                &actual.lease.lease_id,
                actual.lease.revision,
                &actual.lease.binding,
            )
            .map_err(root::lease_error)?;
        let proof = canonical
            .with_dispatch_boundary(token, &actual.lease.binding, || {
                let state = issuer.store.load(STATE_OWNER).map_err(io::Error::other)?;
                if state
                    .policies
                    .iter()
                    .filter(|entry| **entry == policy)
                    .count()
                    != 1
                {
                    return Err(denied(
                        "one exact registered native namespace policy required",
                    ));
                }
                issuer.retained_writer_authorization(&writer)
            })
            .map_err(root::lease_error)??;
        Ok(Self {
            registry,
            writer,
            proof,
            policy: Some(policy),
        })
    }
    pub(crate) fn from_registered_history(
        issuer: &DeploymentFinalUseIssuer,
        registry: Arc<AuthorityLeaseRegistry>,
        writer: HostAuthorityWriterRegistration,
        image: &codex_hepta_supervisor::KernelSuccessorImage,
    ) -> io::Result<Self> {
        if unsafe { libc::geteuid() } != 0
            || std::process::id() != 1
            || image.role() != codex_hepta_supervisor::KernelSuccessorRole::HistoryOnly
            || image.launch().mode() != codex_hepta_supervisor::KernelLaunchMode::HistoryOnly
            || image.launch().history_pid() != Some(image.pid())
        {
            return Err(denied("actual Root history-only final image required"));
        }
        image
            .durable_observation()
            .verify_durable()
            .map_err(io::Error::other)?;
        let canonical = &issuer
            .lease
            .as_ref()
            .ok_or_else(|| denied("protected canonical issuer required"))?
            .verifier;
        let proof =
            writer.with_live(canonical, |_| issuer.retained_writer_authorization(&writer))?;
        // Keep the original registered writer/checkpoint and consumer feeds,
        // but provide no effect policy and never fall through to generic issue.
        Ok(Self {
            registry,
            writer,
            proof,
            policy: None,
        })
    }
    pub(crate) fn matches_writer(
        &self,
        writer: &HostAuthorityWriterRegistration,
        proof: &crate::HostSignedWriterAuthorizationV1,
    ) -> bool {
        self.writer == *writer && self.proof == *proof
    }
    pub(crate) fn issue(
        &self,
        issuer: &DeploymentFinalUseIssuer,
        binding: &FinalUseBinding,
    ) -> io::Result<Option<SignedFinalUseGrant>> {
        let Some(policy) = &self.policy else {
            return Ok(None);
        };
        let bytes = serde_json::to_vec(&(
            "runtime.hos2.effect-lease.v1",
            self.proof.sha256()?,
            binding,
        ))?;
        let lease_id = format!(
            "hos2-effect.{}",
            codex_hepta_contracts::Sha256Digest::for_bytes(&bytes).as_str()
        );
        super::registered_effect::issue(
            issuer,
            &self.registry,
            &self.writer,
            &self.proof,
            policy,
            lease_id,
            binding,
        )
    }
}

impl DeploymentFinalUseIssuer {
    /// The original Root factory supplies this non-forgeable actual image and
    /// its retained, durably saved launch/retirement observation. Replace only
    /// the exact two preceding HOS2 policy slots after that kernel cut. This
    /// never changes a key, issuer head, sequence, writer proof or consumer.
    pub(crate) fn replace_native_cpu_namespaces(
        &self,
        registration: &HostAuthorityWriterRegistration,
        image: &codex_hepta_supervisor::KernelSuccessorImage,
        expected_scopes: [[u8; 32]; 2],
    ) -> io::Result<[[u8; 32]; 2]> {
        if unsafe { libc::geteuid() } != 0
            || std::process::id() != 1
            || image.role() != codex_hepta_supervisor::KernelSuccessorRole::Manager
        {
            return Err(denied(
                "actual Root manager activation required for namespace replacement",
            ));
        }
        let launch = image.launch();
        let retirement = image.retirement();
        if launch.mode() != codex_hepta_supervisor::KernelLaunchMode::ManagerRecovery
            || launch.generation() == 0
            || launch.generation() != retirement.generation()
            || launch.boot_id() != retirement.boot_id()
            || !retirement.policy_retired()
            || launch.manager_pid() != Some(image.pid())
        {
            return Err(denied(
                "actual fresh pair and preceding policy retirement required",
            ));
        }
        // KernelSuccessorImage can only be constructed by the original driver
        // after save_and_acknowledge returned. Recheck the same held inode/full
        // bytes before installing an exact new policy; this record grants no
        // authority by itself and can never revive an old boot or namespace.
        image
            .durable_observation()
            .verify_durable()
            .map_err(io::Error::other)?;
        let scopes = |spaces: [[u8; 16]; 2]| -> io::Result<[[u8; 32]; 2]> {
            let one = |space| -> io::Result<[u8; 32]> {
                let request = codex_hepta_memory::Hos2InstallBudgetV1 {
                    schema_version: 1,
                    delivery: codex_hepta_memory::Hos2DeliveryId::new(launch.boot_id(), space, 1)
                        .map_err(io::Error::other)?,
                    manage_slot: 2,
                    manage_generation: 1,
                    expected_revision: 1,
                    period_ns: codex_hepta_memory::HOS2_CPU_PERIOD_NS,
                    cap_ns: 50_000_000,
                };
                Ok(request.scope_digest().into_array())
            };
            Ok([one(spaces[0])?, one(spaces[1])?])
        };
        if scopes(retirement.previous_history_spaces())? != expected_scopes {
            return Err(denied(
                "old CPU policy differs from the actual retired namespaces",
            ));
        }
        let next_scopes = scopes(launch.history_spaces())?;
        if next_scopes[0] == next_scopes[1]
            || next_scopes
                .iter()
                .any(|scope| expected_scopes.contains(scope))
        {
            return Err(denied(
                "fresh kernel namespaces reused an old exact CPU scope",
            ));
        }
        let policy = |scope| DeploymentGrantPolicy {
            subject_id: registration.registered_agent_id.to_string(),
            destination_id: codex_hepta_memory::HOS2_DESTINATION_V1.into(),
            scope_sha256: scope,
            lifetime_ms: 5_000,
        };
        let old_policies = expected_scopes.map(policy);
        let new_policies = next_scopes.map(policy);
        let verifier = &self
            .lease
            .as_ref()
            .ok_or_else(|| denied("protected original issuer required"))?
            .verifier;
        registration.with_live(verifier, |_| {
            let proof = self.retained_writer_authorization(registration)?;
            let _guard = self
                .request_lock
                .lock()
                .map_err(|_| io::Error::other("issuer fenced"))?;
            let state = self.store.load(STATE_OWNER).map_err(io::Error::other)?;
            if state.writer_authorization.as_ref() != Some(&proof) {
                return Err(denied(
                    "canonical writer proof changed before CPU policy replacement",
                ));
            }
            let indices: Vec<_> = state
                .policies
                .iter()
                .enumerate()
                .filter_map(|(index, entry)| {
                    (entry.subject_id == registration.registered_agent_id.as_str()
                        && entry.destination_id == codex_hepta_memory::HOS2_DESTINATION_V1)
                        .then_some(index)
                })
                .collect();
            if indices.len() != 2 {
                return Err(denied("exact two original CPU policy slots required"));
            }
            let actual = [&state.policies[indices[0]], &state.policies[indices[1]]];
            if actual == [&new_policies[0], &new_policies[1]] {
                // Exact already-retained result after a lost administrative
                // response; no new CAS, key or sequence is manufactured.
            } else {
                if actual != [&old_policies[0], &old_policies[1]] {
                    return Err(denied("CPU policy exact predecessor changed"));
                }
                let mut changed = state.clone();
                changed.policies[indices[0]] = new_policies[0].clone();
                changed.policies[indices[1]] = new_policies[1].clone();
                self.store
                    .compare_and_set(STATE_OWNER, &state, &changed)
                    .map_err(io::Error::other)?;
            }
            writer::validate_writer_time(
                registration,
                state.head.authority_epoch,
                self.clock.now_unix_ms().map_err(io::Error::other)?,
            )
        })?;
        Ok(next_scopes)
    }
}
