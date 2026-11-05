//! Canonical pinned issuer dependencies without nested registry boundaries.
use super::*;

impl DeploymentFinalUseIssuer {
    pub(crate) fn with_live_issuer_writer_registration<T>(
        &self,
        registration: &HostAuthorityWriterRegistration,
        token_verifier: &AuthorityLeaseVerifier,
        dispatch: impl FnOnce(&AuthorityLease) -> io::Result<T>,
    ) -> io::Result<T> {
        registration.validate()?;
        let pinned = self
            .lease
            .as_ref()
            .ok_or_else(|| io::Error::other("protected issuer required"))?;
        let writer = &registration.authority_lease;
        let token = token_verifier
            .verify_use(&writer.lease_id, writer.revision, &writer.binding)
            .map_err(lease_error)?;
        pinned
            .verifier
            .with_pinned_issuer_dispatch_boundary(
                pinned.identity(),
                token,
                &writer.binding,
                |issuer, actual_writer, _| {
                    if actual_writer != writer {
                        return Err(io::Error::new(
                            io::ErrorKind::PermissionDenied,
                            "registered writer lease changed",
                        ));
                    }
                    dispatch(issuer)
                },
            )
            .map_err(lease_error)?
    }

    pub(crate) fn with_live_issuer_writer_effect<T>(
        &self,
        registration: &HostAuthorityWriterRegistration,
        effect: &AuthorityLease,
        effect_verifier: &AuthorityLeaseVerifier,
        dispatch: impl FnOnce(&AuthorityLease) -> io::Result<T>,
    ) -> io::Result<T> {
        registration.validate()?;
        let pinned = self
            .lease
            .as_ref()
            .ok_or_else(|| io::Error::other("protected issuer required"))?;
        let writer = &registration.authority_lease;
        let writer_token = pinned
            .verifier
            .verify_use(&writer.lease_id, writer.revision, &writer.binding)
            .map_err(lease_error)?;
        let effect_token = effect_verifier
            .verify_use(&effect.lease_id, effect.revision, &effect.binding)
            .map_err(lease_error)?;
        pinned
            .verifier
            .with_pinned_issuer_joint_dispatch_boundary(
                pinned.identity(),
                (writer_token, &writer.binding),
                (effect_token, &effect.binding),
                |issuer, actual_writer, actual_effect, _| {
                    if actual_writer != writer || actual_effect != effect {
                        return Err(io::Error::new(
                            io::ErrorKind::PermissionDenied,
                            "registered writer or effect lease changed",
                        ));
                    }
                    dispatch(issuer)
                },
            )
            .map_err(lease_error)?
    }

    pub(crate) fn validate_issuer_lease_time(
        issuer: &AuthorityLease,
        epoch: u64,
        now: u64,
    ) -> io::Result<()> {
        if issuer.authority_epoch != epoch
            || now < issuer.issued_at_unix_ms
            || now >= issuer.expires_at_unix_ms
        {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "original issuer expired or epoch changed",
            ));
        }
        Ok(())
    }
}
