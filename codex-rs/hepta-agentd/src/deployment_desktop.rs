//! Atomic Notes/Calculator policy succession in the original issuer state.
//! A policy transition carries no authority or effect permission. The trusted
//! launcher must first retire the old publisher, rotate the original writer
//! authorization and adopt the actual protected Current.

use super::*;
use codex_hepta_memory::CalculatorTargetIdentity;
use codex_hepta_memory::NotesTargetIdentity;

/// Exact two-application metadata captured from one original Session.
/// A predecessor is historical metadata; the successor must come from the
/// credential-checked new Session reservation, never an ordinary peer request.
pub struct RootDesktopPolicy<'a> {
    pub notes: &'a NotesTargetIdentity,
    pub calculator: &'a CalculatorTargetIdentity,
    pub grant_lifetime_ms: u64,
}

impl RootDesktopPolicy<'_> {
    fn policies(&self, subject_id: &str) -> io::Result<[DeploymentGrantPolicy; 2]> {
        self.notes.validate().map_err(io::Error::other)?;
        self.calculator.validate().map_err(io::Error::other)?;
        if self.notes.session_instance != self.calculator.session_instance
            || self.notes.task_id == self.calculator.task_id
            || self.notes.incarnation == self.calculator.incarnation
            || !(1..=30_000).contains(&self.grant_lifetime_ms)
        {
            return Err(denied(
                "Desktop policy must bind one distinct bounded application pair",
            ));
        }
        Ok([
            DeploymentGrantPolicy {
                subject_id: subject_id.into(),
                destination_id: self.notes.destination_id(),
                scope_sha256: self.notes.scope_digest().into_array(),
                lifetime_ms: self.grant_lifetime_ms,
            },
            DeploymentGrantPolicy {
                subject_id: subject_id.into(),
                destination_id: self.calculator.destination_id(),
                scope_sha256: self.calculator.scope_digest().into_array(),
                lifetime_ms: self.grant_lifetime_ms,
            },
        ])
    }
}

impl DeploymentFinalUseIssuer {
    /// Replace both exact policy slots in ONE original issuer-state CAS.
    /// No key, counter, revocation frontier, writer proof, operation or receipt
    /// is replaced. This route is reserved for the actual Root launcher after
    /// original writer succession and protected Current recovery.
    ///
    /// Errors may follow durable publication. Reconcile only the same complete
    /// successor pair; neither one successful slot nor a fresh retry target is
    /// evidence that this transition completed.
    pub fn replace_registered_desktop_policy(
        &self,
        registration: &HostAuthorityWriterRegistration,
        previous: RootDesktopPolicy<'_>,
        next: RootDesktopPolicy<'_>,
    ) -> io::Result<()> {
        // SAFETY: observe actual kernel credentials without dereferencing memory.
        if unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0 {
            return Err(denied("Desktop policy succession requires actual Root"));
        }
        self.replace_desktop_policy(registration, previous, next)
    }

    fn replace_desktop_policy(
        &self,
        registration: &HostAuthorityWriterRegistration,
        previous: RootDesktopPolicy<'_>,
        next: RootDesktopPolicy<'_>,
    ) -> io::Result<()> {
        let previous_policies = previous.policies(registration.registered_agent_id.as_str())?;
        let next_policies = next.policies(registration.registered_agent_id.as_str())?;
        if registration.local_lease_generation <= 1
            || previous.notes.session_instance == next.notes.session_instance
            || previous.notes.incarnation == next.notes.incarnation
            || previous.calculator.incarnation == next.calculator.incarnation
        {
            return Err(denied(
                "Desktop succession requires a new writer and actual Session pair",
            ));
        }
        self.with_live_writer(registration, |issuer_lease| {
            let proof = self.retained_writer_authorization(registration)?;
            let _guard = self
                .request_lock
                .lock()
                .map_err(|_| io::Error::other("issuer fenced"))?;
            let state = self.store.load(STATE_OWNER).map_err(io::Error::other)?;
            if state.writer_authorization.as_ref() != Some(&proof) {
                return Err(denied("registered writer proof changed"));
            }
            let subject = registration.registered_agent_id.as_str();
            let slots = [
                notes::notes_slot(&state.policies, subject)?,
                calculator::calculator_slot(&state.policies, subject)?,
            ];
            for next in &next_policies {
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
                    expires_at_unix_ms: 1 + next.lifetime_ms,
                }
                .signing_bytes()
                .map_err(io::Error::other)?;
            }
            // Waiting for the issuer lock and loading its durable state can
            // consume either lease. Check again immediately before the CAS.
            let validate_time = |now| {
                if issuer_lease.authority_epoch != state.head.authority_epoch
                    || now < issuer_lease.issued_at_unix_ms
                    || now >= issuer_lease.expires_at_unix_ms
                {
                    return Err(denied("original issuer lease expired or epoch changed"));
                }
                writer::validate_writer_time(registration, state.head.authority_epoch, now)
            };
            validate_time(self.clock.now_unix_ms().map_err(io::Error::other)?)?;
            let current = [&state.policies[slots[0]], &state.policies[slots[1]]];
            if current != [&next_policies[0], &next_policies[1]] {
                if current != [&previous_policies[0], &previous_policies[1]] {
                    return Err(denied("original complete Desktop policy CAS mismatch"));
                }
                let mut changed = state.clone();
                for (slot, policy) in slots.into_iter().zip(next_policies) {
                    changed.policies[slot] = policy;
                }
                self.store
                    .compare_and_set(STATE_OWNER, &state, &changed)
                    .map_err(io::Error::other)?;
            }
            let after = self.clock.now_unix_ms().map_err(io::Error::other)?;
            validate_time(after)
        })
    }
}

fn denied(message: &'static str) -> io::Error {
    io::Error::new(io::ErrorKind::PermissionDenied, message)
}

#[cfg(test)]
#[path = "deployment_desktop_tests.rs"]
mod tests;

#[cfg(test)]
pub(super) use tests::original_calculator_issuer_fixture;
