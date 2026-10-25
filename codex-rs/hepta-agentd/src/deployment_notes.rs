//! Root-installed delegation for one actual Notes application incarnation.
//! Original lease registry and canonical issuer only; no operation ledger.

use super::*;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_contracts::authority_lease::AuthorityLeaseError;
use codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry;
use codex_hepta_memory::NotesTargetIdentity;

/// Trusted launcher capability, never accepted from a wire request. The Root
/// launcher must obtain the target from its actual Session Reserved capability
/// before installation. Text/schema validation remains delegated to the fixed
/// trusted Host compiler and original Notes destination, not inferred from hashes.
pub struct RootNotesGrantAdmission {
    registry: Arc<AuthorityLeaseRegistry>,
    writer: HostAuthorityWriterRegistration,
    proof: crate::HostSignedWriterAuthorizationV1,
    policy: DeploymentGrantPolicy,
}

impl RootNotesGrantAdmission {
    pub fn from_registered_notes(
        issuer: &DeploymentFinalUseIssuer,
        registry: Arc<AuthorityLeaseRegistry>,
        writer: HostAuthorityWriterRegistration,
        target: &NotesTargetIdentity,
        lifetime_ms: u64,
    ) -> io::Result<Self> {
        // SAFETY: geteuid has no arguments or borrowed memory.
        if unsafe { libc::geteuid() } != 0 {
            return Err(denied("Root Notes admission requires the trusted launcher"));
        }
        Self::open(issuer, registry, writer, target, lifetime_ms)
    }

    fn open(
        issuer: &DeploymentFinalUseIssuer,
        registry: Arc<AuthorityLeaseRegistry>,
        writer: HostAuthorityWriterRegistration,
        target: &NotesTargetIdentity,
        lifetime_ms: u64,
    ) -> io::Result<Self> {
        target.validate().map_err(io::Error::other)?;
        writer.validate()?;
        let policy = DeploymentGrantPolicy {
            subject_id: writer.registered_agent_id.as_str().into(),
            destination_id: target.destination_id(),
            scope_sha256: target.scope_digest().into_array(),
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
        // An opaque token from the supplied administrative owner must also be
        // accepted by the issuer's pinned verifier. Equal serialized copies in
        // another registry cannot authorize this installation.
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
                let slot = notes_slot(&state.policies, &policy.subject_id)?;
                if state.policies[slot] != policy || lifetime_ms == 0 {
                    return Err(denied("exact Notes policy slot required"));
                }
                issuer.retained_writer_authorization(&writer)
            })
            .map_err(root::lease_error)??;
        Ok(Self {
            registry,
            writer,
            proof,
            policy,
        })
    }

    pub(crate) fn matches_writer(
        &self,
        registration: &HostAuthorityWriterRegistration,
        proof: &crate::HostSignedWriterAuthorizationV1,
    ) -> bool {
        self.writer == *registration && self.proof == *proof
    }

    /// Preserve the original issuer's other registered routes. This Notes
    /// destination always enters its fixed delegation, including requests with
    /// the wrong subject or scope; a Notes denial must never fall through.
    pub(crate) fn issue_registered_route(
        &self,
        issuer: &DeploymentFinalUseIssuer,
        binding: &FinalUseBinding,
    ) -> io::Result<Option<SignedFinalUseGrant>> {
        if binding.destination_id == self.policy.destination_id {
            self.issue(issuer, binding)
        } else {
            issuer.issue(binding)
        }
    }

    /// Register one short exact original lease, then enter the original joint
    /// writer/effect boundary. Repeated requests can reuse the retained lease
    /// while live, but never renew, replace, reset or resurrect its ID.
    pub(crate) fn issue(
        &self,
        issuer: &DeploymentFinalUseIssuer,
        binding: &FinalUseBinding,
    ) -> io::Result<Option<SignedFinalUseGrant>> {
        if binding.subject_id != self.policy.subject_id
            || binding.destination_id != self.policy.destination_id
            || binding.scope_sha256 != self.policy.scope_sha256
            || binding.request_sha256 == [0; 32]
            || binding.payload_sha256 == [0; 32]
        {
            return Ok(None);
        }
        let canonical = &issuer
            .lease
            .as_ref()
            .ok_or_else(|| denied("protected canonical issuer required"))?
            .verifier;
        self.writer.with_live(canonical, |_| {
            if issuer.retained_writer_authorization(&self.writer)? != self.proof {
                return Err(denied("registered writer proof changed"));
            }
            Ok(())
        })?;
        let lease_id = self.lease_id(binding)?;
        let expected = AuthorityLeaseBinding {
            principal_id: binding.subject_id.clone(),
            operation_class: "runtime.agentd.production_operation".into(),
            destination_id: binding.destination_id.clone(),
            scope_sha256: binding.scope_sha256,
            payload_sha256: binding.payload_sha256,
        };
        // Mutation is outside the joint owner lock. Its completion may consume
        // the writer lifetime, so fresh opaque tokens are checked afterward.
        let read = match self
            .registry
            .read_lease(&lease_id)
            .map_err(root::lease_error)?
        {
            Some(read) => read,
            None => {
                let now = issuer.clock.now_unix_ms().map_err(io::Error::other)?;
                let lease = AuthorityLease {
                    schema_version: 1,
                    lease_id: lease_id.clone(),
                    revision: 1,
                    authority_epoch: self.writer.authority_lease.authority_epoch,
                    binding: expected.clone(),
                    issued_at_unix_ms: now,
                    expires_at_unix_ms: now
                        .checked_add(self.policy.lifetime_ms)
                        .ok_or_else(|| io::Error::other("Notes lease clock overflow"))?
                        .min(self.writer.authority_lease.expires_at_unix_ms),
                };
                match self.registry.put_lease(lease, 0) {
                    Ok(read) => read,
                    // Another concurrent exact request may have won CAS. Read
                    // that original full record; a pruned ID stays refused.
                    Err(AuthorityLeaseError::RevisionMismatch) => self
                        .registry
                        .read_lease(&lease_id)
                        .map_err(root::lease_error)?
                        .ok_or_else(|| denied("retired Notes lease cannot be recreated"))?,
                    Err(error) => return Err(root::lease_error(error)),
                }
            }
        };
        let effect = read.lease;
        if effect.schema_version != 1
            || effect.lease_id != lease_id
            || effect.revision != 1
            || effect.authority_epoch != self.writer.authority_lease.authority_epoch
            || effect.binding != expected
            || effect.issued_at_unix_ms < self.writer.authority_lease.issued_at_unix_ms
            || effect.expires_at_unix_ms > self.writer.authority_lease.expires_at_unix_ms
            || effect
                .expires_at_unix_ms
                .checked_sub(effect.issued_at_unix_ms)
                .is_none_or(|duration| duration == 0 || duration > self.policy.lifetime_ms)
        {
            return Err(denied("retained Notes lease differs from its registration"));
        }
        let writer = &self.writer.authority_lease;
        let writer_token = canonical
            .verify_use(&writer.lease_id, writer.revision, &writer.binding)
            .map_err(root::lease_error)?;
        let effect_token = self
            .registry
            .verifier()
            .verify_use(&effect.lease_id, effect.revision, &expected)
            .map_err(root::lease_error)?;
        canonical
            .with_joint_dispatch_boundary(
                writer_token,
                &writer.binding,
                effect_token,
                &expected,
                |actual_writer, actual_effect, _| {
                    if actual_writer != writer || actual_effect != &effect {
                        return Err(denied("Notes signing boundary changed"));
                    }
                    issuer.issue_registered_final_use(
                        binding,
                        &self.writer,
                        &self.proof,
                        writer.expires_at_unix_ms.min(effect.expires_at_unix_ms),
                    )
                },
            )
            .map_err(root::lease_error)?
    }

    fn lease_id(&self, binding: &FinalUseBinding) -> io::Result<String> {
        let bytes = serde_json::to_vec(&(
            "runtime.notes.effect-lease.v1",
            self.proof.sha256()?,
            binding,
        ))?;
        Ok(format!(
            "notes-effect.{}",
            Sha256Digest::for_bytes(&bytes).as_str()
        ))
    }
}

fn denied(message: &'static str) -> io::Error {
    io::Error::new(io::ErrorKind::PermissionDenied, message)
}

fn notes_slot(policies: &[DeploymentGrantPolicy], subject: &str) -> io::Result<usize> {
    let mut slots = policies.iter().enumerate().filter(|(_, policy)| {
        policy.subject_id == subject && policy.destination_id.starts_with("trill.notes:")
    });
    let slot = slots
        .next()
        .map(|(index, _)| index)
        .ok_or_else(|| denied("registered Notes policy missing"))?;
    if slots.next().is_some() {
        return Err(denied("registered Notes policy is ambiguous"));
    }
    Ok(slot)
}

impl DeploymentFinalUseIssuer {
    /// Trusted Root launcher only: move the one exact Notes policy slot after
    /// obtaining its actual new Session Reserved target. The launcher must
    /// separately finish publisher quiescence, writer rotation and Current
    /// adoption. Existing signed grants remain evidence for old reconciliation;
    /// replacing this policy grants no permission to dispatch old operations.
    ///
    /// An error may follow durable CAS. Reconcile the exact desired policy on
    /// retry; never reinitialize the issuer, key, epoch, revocations or sequence.
    pub fn replace_registered_notes_policy(
        &self,
        writer: &HostAuthorityWriterRegistration,
        previous_target: &NotesTargetIdentity,
        previous_lifetime_ms: u64,
        target: &NotesTargetIdentity,
        lifetime_ms: u64,
    ) -> io::Result<()> {
        // SAFETY: geteuid has no arguments or borrowed memory.
        if unsafe { libc::geteuid() } != 0 {
            return Err(denied(
                "Root Notes policy replacement requires the trusted launcher",
            ));
        }
        self.replace_notes_policy(
            writer,
            previous_target,
            previous_lifetime_ms,
            target,
            lifetime_ms,
        )
    }

    fn replace_notes_policy(
        &self,
        registration: &HostAuthorityWriterRegistration,
        previous_target: &NotesTargetIdentity,
        previous_lifetime_ms: u64,
        target: &NotesTargetIdentity,
        lifetime_ms: u64,
    ) -> io::Result<()> {
        previous_target.validate().map_err(io::Error::other)?;
        target.validate().map_err(io::Error::other)?;
        let policy = |target: &NotesTargetIdentity, lifetime_ms| DeploymentGrantPolicy {
            subject_id: registration.registered_agent_id.as_str().into(),
            destination_id: target.destination_id(),
            scope_sha256: target.scope_digest().into_array(),
            lifetime_ms,
        };
        let previous = policy(previous_target, previous_lifetime_ms);
        let next = policy(target, lifetime_ms);
        let verifier = &self
            .lease
            .as_ref()
            .ok_or_else(|| denied("protected canonical issuer required"))?
            .verifier;
        registration.with_live(verifier, |_| {
            let proof = self.retained_writer_authorization(registration)?;
            let _guard = self
                .request_lock
                .lock()
                .map_err(|_| io::Error::other("issuer fenced"))?;
            let state = self.store.load(STATE_OWNER).map_err(io::Error::other)?;
            if state.writer_authorization.as_ref() != Some(&proof) {
                return Err(denied("registered writer proof changed"));
            }
            // Use the original grant validation before retaining a new policy.
            FinalUseGrant {
                schema_version: 1,
                signer_id: state.signer_id.clone(),
                authority_epoch: state.head.authority_epoch,
                grant_id: "policy-validation".into(),
                nonce: [1; 32],
                binding: FinalUseBinding {
                    subject_id: next.subject_id.clone(),
                    destination_id: next.destination_id.clone(),
                    scope_sha256: next.scope_sha256,
                    payload_sha256: [1; 32],
                    request_sha256: [1; 32],
                },
                not_before_unix_ms: 1,
                expires_at_unix_ms: 1_u64
                    .checked_add(lifetime_ms)
                    .ok_or_else(|| io::Error::other("invalid Notes lifetime"))?,
            }
            .signing_bytes()
            .map_err(io::Error::other)?;
            let slot = notes_slot(&state.policies, &next.subject_id)?;
            if state.policies[slot] == next {
                let after = self.clock.now_unix_ms().map_err(io::Error::other)?;
                return writer::validate_writer_time(
                    registration,
                    state.head.authority_epoch,
                    after,
                );
            }
            if state.policies[slot] != previous {
                return Err(denied("original Notes policy CAS mismatch"));
            }
            let mut changed = state.clone();
            // Preserve every original Objective and other installed route at
            // its exact position under the full original issuer-state CAS.
            changed.policies[slot] = next;
            self.store
                .compare_and_set(STATE_OWNER, &state, &changed)
                .map_err(io::Error::other)?;
            let after = self.clock.now_unix_ms().map_err(io::Error::other)?;
            writer::validate_writer_time(registration, state.head.authority_epoch, after)
        })
    }
}

#[cfg(test)]
#[path = "deployment_notes_tests.rs"]
mod tests;
