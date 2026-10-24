//! Explicit continuation of an unused original Root installation.
//! The retained bootstrap, original clock and exact issued lease are inputs;
//! this path cannot reset a runtime owner or manufacture a lost clock floor.

use super::*;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::authority_lease::AuthorityLeaseInitialization;
use sha2::Digest;
use sha2::Sha256;
use std::os::unix::fs::OpenOptionsExt;

pub(crate) fn resume_host_authority_initialization(
    state: &Path,
    bootstrap_file: &Path,
) -> io::Result<HostAuthorityInitialized> {
    let root = HostAuthorityService::current_root_lifetime_for_admin()?;
    let bootstrap: HostAuthorityBootstrap = read_root_json(bootstrap_file)?;
    if bootstrap.schema_version != 1 || !(1..=86_400_000).contains(&bootstrap.lease_lifetime_ms) {
        return Err(io::Error::other("invalid retained initialization"));
    }
    bootstrap.required_bind.verify()?;
    if !state.starts_with(&bootstrap.required_bind.mountpoint)
        || state == bootstrap.required_bind.mountpoint
    {
        return Err(io::Error::other(
            "original state is not a required-bind child",
        ));
    }
    let expected = serde_json::to_vec(&bootstrap)?;
    let initialized = resume_stores(state, &bootstrap)?;
    let observed: HostAuthorityBootstrap = read_root_json(bootstrap_file)?;
    observed.required_bind.verify()?;
    if serde_json::to_vec(&observed)? != expected
        || HostAuthorityService::current_root_lifetime_for_admin()? != root
    {
        return Err(io::Error::other(
            "original initialization input or actual Root changed",
        ));
    }
    Ok(initialized)
}

fn resume_stores(
    state: &Path,
    bootstrap: &HostAuthorityBootstrap,
) -> io::Result<HostAuthorityInitialized> {
    let root = RootAuthorityDirectory::open(state).map_err(io::Error::other)?;
    let directory = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(state)?;
    let lock: File = rustix::fs::openat(
        &directory,
        "original-initialization.lock",
        rustix::fs::OFlags::RDWR
            | rustix::fs::OFlags::CREATE
            | rustix::fs::OFlags::NOFOLLOW
            | rustix::fs::OFlags::CLOEXEC
            | rustix::fs::OFlags::NONBLOCK,
        rustix::fs::Mode::RUSR | rustix::fs::Mode::WUSR,
    )?
    .into();
    let metadata = lock.metadata()?;
    if !metadata.is_file()
        || metadata.uid() != 0
        || metadata.mode() & 0o777 != 0o600
        || metadata.nlink() != 1
    {
        return Err(io::Error::other(
            "original initialization lock is not private Root state",
        ));
    }
    lock.try_lock()?;
    let named = rustix::fs::statat(
        &directory,
        "original-initialization.lock",
        rustix::fs::AtFlags::SYMLINK_NOFOLLOW,
    )?;
    if named.st_dev != metadata.dev() || named.st_ino != metadata.ino() {
        return Err(io::Error::other(
            "original initialization lock inode changed",
        ));
    }
    // Opening renews from the exact retained original highwater. Absence,
    // partial or corrupt clock material never permits a new genesis sample.
    let clock = Arc::new(
        HostAuthorityClock::open(root.clone(), CLOCK_OWNER.into()).map_err(io::Error::other)?,
    );
    let name = format!(
        "frontier-v1-{:x}.json",
        Sha256::digest(LEASE_OWNER.as_bytes())
    );
    let frontier = if entry_exists(&directory, &name)? {
        HostAuthorityFrontierStore::<AuthorityLeaseFrontier>::open(root, LEASE_OWNER.into())
            .map_err(io::Error::other)?
    } else {
        // The original clock precedes both lease and issuer directories.
        // Their presence makes a missing lease frontier a loss, not genesis.
        if entry_exists(&directory, "leases")? || entry_exists(&directory, "issuer")? {
            return Err(io::Error::other(
                "missing original lease frontier after later initialization",
            ));
        }
        HostAuthorityFrontierStore::resume_initialization(
            root,
            LEASE_OWNER.into(),
            AuthorityLeaseFrontier::for_empty_epoch(1).map_err(io::Error::other)?,
        )
        .map_err(io::Error::other)?
    };
    let frontier = Arc::new(frontier);
    if !entry_exists(&directory, "leases")? {
        if frontier.load(LEASE_OWNER).map_err(io::Error::other)?
            != AuthorityLeaseFrontier::for_empty_epoch(1).map_err(io::Error::other)?
            || entry_exists(&directory, "issuer")?
        {
            return Err(io::Error::other(
                "missing original lease directory is not empty initialization",
            ));
        }
        std::fs::DirBuilder::new()
            .mode(0o700)
            .create(state.join("leases"))?;
        directory.sync_all()?;
    }
    let leases = AuthorityLeaseRegistry::resume_initialization_with_trust(
        &state.join("leases"),
        LEASE_OWNER.into(),
        &AuthorityLeaseInitialization {
            lease_id: bootstrap.lease_id.clone(),
            binding: bootstrap.lease_binding.clone(),
            lifetime_ms: bootstrap.lease_lifetime_ms,
        },
        clock.clone(),
        frontier,
    )
    .map_err(io::Error::other)?;
    let issued = match leases
        .read_lease(&bootstrap.lease_id)
        .map_err(io::Error::other)?
    {
        Some(value) => value.lease,
        None => {
            // Only the original verified empty genesis reaches this branch.
            // Its staged publication retains these exact first issue times
            // before the independent protected frontier can commit them.
            let now = clock.now_unix_ms().map_err(io::Error::other)?;
            let issued = AuthorityLease {
                schema_version: 1,
                lease_id: bootstrap.lease_id.clone(),
                authority_epoch: 1,
                revision: 1,
                binding: bootstrap.lease_binding.clone(),
                issued_at_unix_ms: now,
                expires_at_unix_ms: now
                    .checked_add(bootstrap.lease_lifetime_ms)
                    .ok_or_else(|| io::Error::other("initial lease expiry overflow"))?,
            };
            leases
                .put_lease(issued.clone(), 0)
                .map_err(io::Error::other)?;
            issued
        }
    };
    let issuer = if entry_exists(&directory, "issuer")? {
        DeploymentFinalUseIssuer::resume_protected_initialization(
            &state.join("issuer"),
            bootstrap.signer_id.clone(),
            bootstrap.policies.clone(),
            clock.clone(),
            leases.verifier(),
            issued.lease_id.clone(),
            issued.revision,
        )?
    } else {
        DeploymentFinalUseIssuer::create_protected(
            &state.join("issuer"),
            bootstrap.signer_id.clone(),
            bootstrap.policies.clone(),
            clock.clone(),
            leases.verifier(),
            issued.lease_id.clone(),
            issued.revision,
        )?
    };
    if leases
        .read_lease(&issued.lease_id)
        .map_err(io::Error::other)?
        .map(|value| value.lease)
        != Some(issued.clone())
    {
        return Err(io::Error::other(
            "original initialization changed its retained lease",
        ));
    }
    clock.now_unix_ms().map_err(io::Error::other)?;
    Ok(HostAuthorityInitialized {
        schema_version: 1,
        signer_id: bootstrap.signer_id.clone(),
        verifying_key: issuer.trust_key()?.verifying_key,
        lease_id: issued.lease_id,
        lease_revision: issued.revision,
        production_ready: false,
    })
}

fn entry_exists(directory: &File, name: &str) -> io::Result<bool> {
    match rustix::fs::statat(directory, name, rustix::fs::AtFlags::SYMLINK_NOFOLLOW) {
        Ok(_) => Ok(true),
        Err(rustix::io::Errno::NOENT) => Ok(false),
        Err(error) => Err(error.into()),
    }
}

#[cfg(test)]
#[path = "authority_host_runtime_initialization_tests.rs"]
mod tests;
