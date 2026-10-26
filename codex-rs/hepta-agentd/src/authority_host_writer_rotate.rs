//! Explicit Root administrative composition of the ORIGINAL writer rotation.
//! There is no ordinary peer route and no Current/material adoption here.

use super::*;

/// Retire only the old expired canonical authority lease and authorize the
/// exact registered successor through the existing issuer/key/counter. A lost
/// result may reconcile that same new lease/proof; it cannot invent another
/// generation, restore bytes, or stand in for actual old-publisher retirement.
pub fn rotate_host_writer_authorization(
    config_file: &Path,
    predecessor: &crate::HostAuthorityWriterRegistration,
    predecessor_proof: &crate::HostSignedWriterAuthorizationV1,
) -> io::Result<crate::HostSignedWriterAuthorizationV1> {
    // SAFETY: actual process credentials are read without pointers or effects.
    if unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0 {
        return Err(io::Error::other("writer rotation requires actual Root"));
    }
    let config: HostAuthorityServiceConfig = read_root_json(config_file)?;
    let successor = config
        .writer
        .as_ref()
        .ok_or_else(|| io::Error::other("registered successor writer required"))?;
    let (clock, leases, issuer) = open_registered_issuer(&config)?;
    let now = clock.now_unix_ms().map_err(io::Error::other)?;
    if now < predecessor.authority_lease.expires_at_unix_ms
        || now < successor.authority_lease.issued_at_unix_ms
        || now >= successor.authority_lease.expires_at_unix_ms
    {
        return Err(io::Error::other(
            "original retired/live writer window is absent",
        ));
    }
    let old = leases
        .read_lease(&predecessor.authority_lease.lease_id)
        .map_err(io::Error::other)?;
    // Existing canonical predecessor bytes must still agree. A changed old
    // lease is not reconstructed from the serialized historical proof.
    if let Some(old) = old.as_ref()
        && old.lease != predecessor.authority_lease
        && old.lease != successor.authority_lease
    {
        return Err(io::Error::other("original predecessor lease changed"));
    }
    let existing = leases
        .read_lease(&successor.authority_lease.lease_id)
        .map_err(io::Error::other)?;
    match existing {
        Some(existing) if existing.lease == successor.authority_lease => {}
        Some(existing) if existing.lease == predecessor.authority_lease => {
            leases
                .put_lease(
                    successor.authority_lease.clone(),
                    predecessor.authority_lease.revision,
                )
                .map_err(io::Error::other)?;
        }
        None if predecessor.authority_lease.lease_id != successor.authority_lease.lease_id => {
            leases
                .put_lease(
                    successor.authority_lease.clone(),
                    /*expected_revision*/ 0,
                )
                .map_err(io::Error::other)?;
        }
        Some(_) | None => {
            return Err(io::Error::other(
                "exact original successor lease CAS is unavailable",
            ));
        }
    }
    issuer.rotate_writer_authorization(predecessor, predecessor_proof, successor)
}
