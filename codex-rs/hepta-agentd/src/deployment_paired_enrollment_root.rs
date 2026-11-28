//! Actual Root entry; the checked registration has an independent closed caller.

use super::*;
use std::time::Instant;

impl DeploymentFinalUseIssuer {
    pub(crate) fn register_original_paired_enrollment_once(
        &self,
        plan: &RootPairedTrainingPlanV1,
        registry: &AuthorityLeaseRegistry,
        writer: &HostAuthorityWriterRegistration,
        proof: &crate::HostSignedWriterAuthorizationV1,
        lifetime_ms: u64,
        end: Instant,
    ) -> io::Result<()> {
        // SAFETY: only observe the current kernel credentials.
        if unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0 {
            return Err(denied(
                "enrollment registration requires actual original Root",
            ));
        }
        self.register_paired_enrollment_checked(plan, registry, writer, proof, lifetime_ms, end)
    }
}
