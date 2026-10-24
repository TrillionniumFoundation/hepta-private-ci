//! Explicit Root completion of an original lease publication before cold open.
//! Ordinary runtime open is unchanged and never performs this administration.

use super::*;

pub(crate) fn resume_registered_issuer_for_root(
    config: &HostAuthorityServiceConfig,
) -> io::Result<(
    Arc<HostAuthorityClock>,
    AuthorityLeaseRegistry,
    Arc<DeploymentFinalUseIssuer>,
)> {
    let actual_root = HostAuthorityService::current_root_lifetime_for_admin()?;
    if config.schema_version != 1 || config.lease_revision == 0 {
        return Err(io::Error::other("invalid retained service config"));
    }
    config.required_bind.verify()?;
    if !config
        .state_dir
        .starts_with(&config.required_bind.mountpoint)
        || config.state_dir == config.required_bind.mountpoint
    {
        return Err(io::Error::other(
            "retained original state outside required bind",
        ));
    }
    let root = RootAuthorityDirectory::open(&config.state_dir).map_err(io::Error::other)?;
    let clock = Arc::new(
        HostAuthorityClock::open(root.clone(), CLOCK_OWNER.into()).map_err(io::Error::other)?,
    );
    let frontier = Arc::new(
        HostAuthorityFrontierStore::<AuthorityLeaseFrontier>::open(root, LEASE_OWNER.into())
            .map_err(io::Error::other)?,
    );
    let completed = AuthorityLeaseRegistry::resume_prepared_state_with_trust(
        &config.state_dir.join("leases"),
        LEASE_OWNER.into(),
        clock,
        frontier,
    )
    .map_err(io::Error::other)?;
    // The same original store retains its exclusive file lock. Release this
    // administration handle before the ordinary pinned runtime factory opens.
    drop(completed);
    if HostAuthorityService::current_root_lifetime_for_admin()? != actual_root {
        return Err(io::Error::other(
            "actual Root changed during publication completion",
        ));
    }
    open_registered_issuer(config)
}
