//! Same retained Root issuer; no peer route or replacement authority owner.
use super::*;
use codex_hepta_memory::NotesTargetIdentity;

impl HostAuthorityService {
    pub(crate) fn replace_notes_policy_for_registered_successor(
        &self,
        previous: &NotesTargetIdentity,
        previous_lifetime_ms: u64,
        target: &NotesTargetIdentity,
        lifetime_ms: u64,
    ) -> io::Result<()> {
        // SAFETY: observe actual credentials, never a serialized Root role.
        if unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0 || self.notes.is_some()
        {
            return Err(io::Error::other(
                "unregistered actual Root successor Notes route required",
            ));
        }
        let writer = self
            .writer
            .as_ref()
            .ok_or_else(|| io::Error::other("original registered writer required"))?;
        if writer.registration.local_lease_generation <= 1 {
            return Err(io::Error::other(
                "initial writer cannot replace the Notes policy",
            ));
        }
        self.issuer.replace_registered_notes_policy(
            &writer.registration,
            previous,
            previous_lifetime_ms,
            target,
            lifetime_ms,
        )
    }
}
