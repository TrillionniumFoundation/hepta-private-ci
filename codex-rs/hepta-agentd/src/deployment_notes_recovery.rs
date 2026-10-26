//! Read-only original policy validation before any recovery CAS.
use super::*;

/// A retained validation result, not authority. Only its original coordinator
/// may recheck the same old/new policies under the same canonical writer fence.
pub(crate) struct NotesRecoveryPolicyCheck {
    writer: HostAuthorityWriterRegistration,
    previous: DeploymentGrantPolicy,
    next: DeploymentGrantPolicy,
}

enum PolicyRead {
    Predecessor,
    RetainedAttempt,
}

impl DeploymentFinalUseIssuer {
    pub(crate) fn prepare_notes_recovery_policy(
        &self,
        writer: &HostAuthorityWriterRegistration,
        previous_target: &NotesTargetIdentity,
        previous_lifetime_ms: u64,
        target: &NotesTargetIdentity,
        lifetime_ms: u64,
    ) -> io::Result<NotesRecoveryPolicyCheck> {
        previous_target.validate().map_err(io::Error::other)?;
        target.validate().map_err(io::Error::other)?;
        let checked = NotesRecoveryPolicyCheck {
            writer: writer.clone(),
            previous: notes_policy(writer, previous_target, previous_lifetime_ms),
            next: notes_policy(writer, target, lifetime_ms),
        };
        self.inspect_notes_recovery_policy(&checked, PolicyRead::Predecessor)?;
        Ok(checked)
    }

    pub(crate) fn recheck_notes_recovery_policy(
        &self,
        checked: &NotesRecoveryPolicyCheck,
        writer: &HostAuthorityWriterRegistration,
        target: &NotesTargetIdentity,
        lifetime_ms: u64,
    ) -> io::Result<()> {
        target.validate().map_err(io::Error::other)?;
        if writer != &checked.writer || notes_policy(writer, target, lifetime_ms) != checked.next {
            return Err(denied(
                "Notes recovery retry differs from its retained policy",
            ));
        }
        self.inspect_notes_recovery_policy(checked, PolicyRead::RetainedAttempt)
    }

    fn inspect_notes_recovery_policy(
        &self,
        checked: &NotesRecoveryPolicyCheck,
        expected: PolicyRead,
    ) -> io::Result<()> {
        // SAFETY: geteuid reads this process's actual kernel credential.
        if unsafe { libc::geteuid() } != 0 {
            return Err(denied(
                "Root Notes recovery policy check requires the trusted launcher",
            ));
        }
        let verifier = &self
            .lease
            .as_ref()
            .ok_or_else(|| denied("protected canonical issuer required"))?
            .verifier;
        checked.writer.with_live(verifier, |_| {
            let _guard = self
                .request_lock
                .lock()
                .map_err(|_| io::Error::other("issuer fenced"))?;
            let state = self.store.load(STATE_OWNER).map_err(io::Error::other)?;
            validate_notes_policy(&state, &checked.previous)?;
            validate_notes_policy(&state, &checked.next)?;
            let slot = notes_slot(&state.policies, &checked.next.subject_id)?;
            let matches = match expected {
                PolicyRead::Predecessor => state.policies[slot] == checked.previous,
                PolicyRead::RetainedAttempt => {
                    state.policies[slot] == checked.previous || state.policies[slot] == checked.next
                }
            };
            if !matches {
                return Err(denied(
                    "original Notes policy differs before recovery mutation",
                ));
            }
            writer::validate_writer_time(
                &checked.writer,
                state.head.authority_epoch,
                self.clock.now_unix_ms().map_err(io::Error::other)?,
            )
        })
    }
}
