//! Closed internal borrow of the already-open Root service. This lets one
//! retained task custody serve the original five lanes without reopening its
//! issuer, clock, checkpoint, lease registry or original writer proof.

use super::*;

pub(crate) struct OriginalTaskHostLanes<'a> {
    service: &'a HostAuthorityService,
    config: &'a HostAuthorityServiceConfig,
    registration: &'a HostAuthorityRegistration,
    owner: &'a OwnedFd,
    bound: super::super::listeners::BoundLanes,
}

impl PreparedHostAuthoritySession {
    pub(crate) fn bind_original_task_host_lanes(&self) -> io::Result<OriginalTaskHostLanes<'_>> {
        if rustix::process::getuid().as_raw() != 0 || rustix::process::geteuid().as_raw() != 0 {
            return Err(io::Error::other("same actual Root service required"));
        }
        // Those optional services have their own consuming original serving
        // APIs. This bounded composition never silently drops either owner.
        if self.root_admin.is_some() || self.learning.is_some() {
            return Err(io::Error::other("original task host cannot discard optional retained lanes"));
        }
        let bound = super::super::listeners::bind_runtime_lanes(&self.config, || Ok(()))?;
        Ok(OriginalTaskHostLanes { service: &self.service, config: &self.config,
            registration: &self.registration, owner: &self.owner_pidfd, bound })
    }
}

impl OriginalTaskHostLanes<'_> {
    pub(crate) fn serve(self) -> io::Result<()> {
        super::super::listeners::serve_bound_lanes(self.service, self.config,
            self.registration, self.owner, self.bound)
    }
}
