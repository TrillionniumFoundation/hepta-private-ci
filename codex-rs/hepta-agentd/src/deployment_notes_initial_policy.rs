//! The first actual reserved Notes target, without a placeholder incarnation.
use super::*;

impl DeploymentFinalUseIssuer {
    /// Trusted Root administration only, after the actual Session reserves its
    /// first target. Existing Objective and Device policies keep their exact
    /// bytes. No key, proof, epoch, revocation head or sequence is replaced.
    ///
    /// The initial issuer can contain its real Objective route before a Session
    /// exists. This method adds its first Notes route; later incarnations use
    /// the original exact-predecessor replacement API. An error after CAS must
    /// be reconciled against this same retained issuer, never fresh genesis.
    pub fn install_registered_notes_policy(
        &self,
        writer: &HostAuthorityWriterRegistration,
        actual_reserved_target: &NotesTargetIdentity,
        lifetime_ms: u64,
    ) -> io::Result<()> {
        // SAFETY: geteuid reads only the actual caller's effective identity.
        if unsafe { libc::geteuid() } != 0 {
            return Err(denied("Root Notes policy installation requires the trusted launcher"));
        }
        self.install_first_notes_policy(writer, actual_reserved_target, lifetime_ms)
    }

    pub(super) fn install_first_notes_policy(
        &self,
        registration: &HostAuthorityWriterRegistration,
        target: &NotesTargetIdentity,
        lifetime_ms: u64,
    ) -> io::Result<()> {
        target.validate().map_err(io::Error::other)?;
        let next = DeploymentGrantPolicy {
            subject_id: registration.registered_agent_id.as_str().into(),
            destination_id: target.destination_id(),
            scope_sha256: target.scope_digest().into_array(),
            lifetime_ms,
        };
        let verifier = &self.lease.as_ref()
            .ok_or_else(|| denied("protected canonical issuer required"))?.verifier;
        registration.with_live(verifier, |_| {
            let proof = self.retained_writer_authorization(registration)?;
            let _guard = self.request_lock.lock().map_err(|_| io::Error::other("issuer fenced"))?;
            let state = self.store.load(STATE_OWNER).map_err(io::Error::other)?;
            if state.writer_authorization.as_ref() != Some(&proof) {
                return Err(denied("registered writer proof changed"));
            }
            // Reuse original grant shape validation, without signing/spending.
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
                expires_at_unix_ms: 1_u64.checked_add(lifetime_ms)
                    .ok_or_else(|| io::Error::other("invalid Notes lifetime"))?,
            }.signing_bytes().map_err(io::Error::other)?;
            let slots: Vec<_> = state.policies.iter().filter(|policy| {
                policy.subject_id == next.subject_id && policy.destination_id.starts_with("trill.notes:")
            }).collect();
            match slots.as_slice() {
                [] if state.policies.len() < 16 => {
                    let mut changed = state.clone();
                    changed.policies.push(next);
                    self.store.compare_and_set(STATE_OWNER, &state, &changed).map_err(io::Error::other)?;
                }
                [retained] if **retained == next => {}
                _ => return Err(denied("first Notes policy requires an absent or exact retained slot")),
            }
            let after = self.clock.now_unix_ms().map_err(io::Error::other)?;
            writer::validate_writer_time(registration, state.head.authority_epoch, after)
        })
    }
}
