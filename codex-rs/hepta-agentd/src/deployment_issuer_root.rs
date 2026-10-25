//! Root service factory for the existing single issuer/key/head/counter.
//! No consumer nonce journal, writer genesis or publisher activation is created.

use super::*;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_contracts::authority_lease::AuthorityLeaseError;
use codex_hepta_contracts::authority_lease::AuthorityLeaseVerifier;

pub(super) struct ProtectedLease {
    verifier: AuthorityLeaseVerifier,
    id: String,
    revision: u64,
}

impl ProtectedLease {
    pub(super) fn new(
        verifier: AuthorityLeaseVerifier,
        id: String,
        revision: u64,
    ) -> io::Result<Self> {
        if id.is_empty() || id.len() > 128 || revision == 0 {
            return Err(io::Error::other("invalid pinned original lease"));
        }
        Ok(Self {
            verifier,
            id,
            revision,
        })
    }

    pub(super) fn with_binding<T>(
        &self,
        binding: &FinalUseBinding,
        dispatch: impl FnOnce(u64, u64) -> io::Result<T>,
    ) -> io::Result<T> {
        let lease = self
            .verifier
            .read_lease(&self.id)
            .map_err(lease_error)?
            .ok_or_else(|| {
                io::Error::new(io::ErrorKind::PermissionDenied, "original lease missing")
            })?
            .lease;
        // Never use the expiry from an older clone when a concurrent admin
        // installs the requested newer revision before verify_use/fencing.
        if lease.revision != self.revision {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "original lease revision mismatch",
            ));
        }
        let expected = AuthorityLeaseBinding {
            principal_id: binding.subject_id.clone(),
            operation_class: "runtime.agentd.production_operation".into(),
            destination_id: binding.destination_id.clone(),
            scope_sha256: binding.scope_sha256,
            payload_sha256: binding.payload_sha256,
        };
        let token = self
            .verifier
            .verify_use(&self.id, self.revision, &expected)
            .map_err(lease_error)?;
        self.verifier
            .with_dispatch_boundary(token, &expected, || {
                dispatch(lease.authority_epoch, lease.expires_at_unix_ms)
            })
            .map_err(lease_error)?
    }
}

pub(super) fn lease_error(error: AuthorityLeaseError) -> io::Error {
    match error {
        AuthorityLeaseError::LeaseNotFound
        | AuthorityLeaseError::Revoked
        | AuthorityLeaseError::BindingMismatch
        | AuthorityLeaseError::RevisionMismatch
        | AuthorityLeaseError::EpochMismatch
        | AuthorityLeaseError::NotYetValid
        | AuthorityLeaseError::Expired => io::Error::new(io::ErrorKind::PermissionDenied, error),
        _ => io::Error::other(error),
    }
}

impl DeploymentFinalUseIssuer {
    /// Observe only under the same original pinned lease/revocation fence used
    /// by issuance. The callback must check its final post-I/O observation
    /// against this lease's expiry before publishing a feed response.
    pub(crate) fn with_live_lease<T>(
        &self,
        observe: impl FnOnce(&AuthorityLease) -> io::Result<T>,
    ) -> io::Result<T> {
        let pinned = self
            .lease
            .as_ref()
            .ok_or_else(|| io::Error::other("no protected lease"))?;
        let lease = pinned
            .verifier
            .read_lease(&pinned.id)
            .map_err(lease_error)?
            .ok_or_else(|| {
                io::Error::new(io::ErrorKind::PermissionDenied, "original lease missing")
            })?
            .lease;
        // As for issuance, never use an older clone after the requested newer
        // revision becomes installed between read and the original token check.
        if lease.revision != pinned.revision {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "original lease revision mismatch",
            ));
        }
        let token = pinned
            .verifier
            .verify_use(&pinned.id, pinned.revision, &lease.binding)
            .map_err(lease_error)?;
        pinned
            .verifier
            .with_dispatch_boundary(token, &lease.binding, || observe(&lease))
            .map_err(lease_error)?
    }

    /// Explicitly create one new root-owned issuer. Existing/partial paths are
    /// never reset. The supplied clock and lease verifier are original trusted
    /// owners, not constructed from peer request fields.
    pub fn create_protected(
        directory: &Path,
        signer_id: String,
        policies: Vec<DeploymentGrantPolicy>,
        clock: Arc<dyn AuthorityClock>,
        leases: AuthorityLeaseVerifier,
        lease_id: String,
        lease_revision: u64,
    ) -> io::Result<Self> {
        let lease = ProtectedLease::new(leases, lease_id, lease_revision)?;
        let mut issuer = Self::create_inner(directory, signer_id, policies, clock, true)?;
        issuer.lease = Some(lease);
        Ok(issuer)
    }

    /// Runtime open is read/open-only; missing or wrong identity is never
    /// converted into initialization. The loader separately pins the public key.
    pub fn open_protected(
        directory: &Path,
        clock: Arc<dyn AuthorityClock>,
        leases: AuthorityLeaseVerifier,
        lease_id: String,
        lease_revision: u64,
    ) -> io::Result<Self> {
        let lease = ProtectedLease::new(leases, lease_id, lease_revision)?;
        Self::open_inner(directory, clock, true, Some(lease))
    }
}

impl DeploymentIssuerObserver {
    pub fn open_protected(directory: &Path) -> io::Result<Self> {
        let observer = Self {
            store: DeploymentFrontierStore::open_protected(directory)?,
        };
        observer.revocations()?;
        Ok(observer)
    }
}

#[cfg(test)]
#[path = "deployment_issuer_root_tests.rs"]
mod tests;
