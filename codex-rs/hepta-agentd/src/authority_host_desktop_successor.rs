//! Same original Root issuer and writer; one atomic policy-pair transition.
use super::*;

impl HostAuthorityService {
    pub(crate) fn replace_desktop_policy_for_registered_successor(
        &self,
        previous: crate::RootDesktopPolicy<'_>,
        next: crate::RootDesktopPolicy<'_>,
    ) -> io::Result<()> {
        // SAFETY: observe actual credentials, never a serialized Root role.
        if unsafe { libc::getuid() } != 0
            || unsafe { libc::geteuid() } != 0
            || self.notes.is_some()
            || self.calculator.is_some()
        {
            return Err(io::Error::other(
                "unregistered actual Root successor joint route required",
            ));
        }
        let writer = self
            .writer
            .as_ref()
            .ok_or_else(|| io::Error::other("original registered writer required"))?;
        if writer.registration.local_lease_generation <= 1 {
            return Err(io::Error::other(
                "initial writer cannot replace the joint policies",
            ));
        }
        self.issuer
            .replace_registered_desktop_policy(&writer.registration, previous, next)
    }
}
