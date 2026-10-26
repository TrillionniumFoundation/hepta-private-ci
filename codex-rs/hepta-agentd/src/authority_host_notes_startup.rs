//! Root startup changes only an explicitly named original Notes policy slot.
//! The successor identity comes from the actual Session reservation, never the
//! profile. The same retained issuer, Registry and writer perform admission.

use super::*;
use codex_hepta_memory::NotesTargetIdentity;

/// Administrative predecessor metadata from the original Root-owned profile.
/// It supplies no successor target, signer, writer, grant or peer authority.
#[derive(Debug, Deserialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
pub(crate) struct ExpectedNotesPolicy {
    pub(crate) target: NotesTargetIdentity,
    pub(crate) lifetime_ms: u64,
}

impl ExpectedNotesPolicy {
    pub(crate) fn validate(&self, successor_lifetime_ms: u64) -> io::Result<()> {
        self.target.validate().map_err(io::Error::other)?;
        if !(1..=300_000).contains(&self.lifetime_ms)
            || !(1..=self.lifetime_ms).contains(&successor_lifetime_ms)
        {
            return Err(io::Error::other(
                "Notes policy replacement must preserve its bounded original lifetime",
            ));
        }
        Ok(())
    }
}

impl HostAuthorityService {
    pub(crate) fn with_notes_from_original_session(
        self,
        target: &NotesTargetIdentity,
        lifetime_ms: u64,
        expected_notes_policy: Option<&ExpectedNotesPolicy>,
    ) -> io::Result<Self> {
        if self.notes.is_some() {
            return Err(io::Error::other(
                "the original Notes route is already registered",
            ));
        }
        let registry = self.root_registry.as_ref().ok_or_else(|| {
            io::Error::other("retained original Root Registry required for Notes")
        })?;
        let writer = self
            .writer
            .as_ref()
            .ok_or_else(|| io::Error::other("original registered writer required"))?;
        if let Some(previous) = expected_notes_policy {
            previous.validate(lifetime_ms)?;
            target.validate().map_err(io::Error::other)?;
            if previous.target == *target {
                return Err(io::Error::other(
                    "Notes startup replacement requires its distinct actual Session target",
                ));
            }
            if self
                .issuer
                .retained_writer_authorization(&writer.registration)?
                != writer.proof
            {
                return Err(io::Error::other("original registered writer proof changed"));
            }
            // This is the original Root-only full-state CAS. Failure here or
            // below may follow its durable update. Never roll it back, reopen
            // another owner, or choose another target to retry an unknown cut.
            self.issuer.replace_registered_notes_policy(
                &writer.registration,
                &previous.target,
                previous.lifetime_ms,
                target,
                lifetime_ms,
            )?;
        }
        let notes = crate::RootNotesGrantAdmission::from_registered_notes(
            &self.issuer,
            Arc::clone(registry),
            writer.registration.clone(),
            target,
            lifetime_ms,
        )?;
        self.with_registered_notes(notes)
    }
}
