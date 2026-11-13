//! Explicit Root renewal of the ORIGINAL issuer lease through its existing CAS.
//! Plans are inert administrative records, never peer inputs or use authority.

use super::*;

const MAX_ISSUER_RENEWAL_MS: u64 = 300_000;

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct HostIssuerLeaseRenewalPlan {
    pub schema_version: u32,
    pub signer_id: String,
    pub verifying_key: [u8; 32],
    pub previous_lease: AuthorityLease,
    pub renewed_lease: AuthorityLease,
}

/// Read the original protected owner and prepare one bounded, fixed postimage.
/// An expired, unrevoked canonical lease may be renewed only by explicit Root.
pub fn prepare_host_issuer_lease_renewal(
    config_file: &Path,
    lifetime_ms: u64,
) -> io::Result<HostIssuerLeaseRenewalPlan> {
    require_actual_root()?;
    let config: HostAuthorityServiceConfig = read_root_json(config_file)?;
    let (clock, leases, _issuer) = open_registered_issuer(&config)?;
    let now = clock.now_unix_ms().map_err(io::Error::other)?;
    prepare_existing(&config, &leases, now, lifetime_ms)
}

/// Commit or reconcile this exact Root-prepared postimage; retries do not
/// regenerate timestamps or extend the lifetime again. Keep the predecessor
/// config until this call succeeds, then reopen the SAME issuer with the new
/// revision. The returned canonical record is not a final-use token.
pub fn commit_host_issuer_lease_renewal(
    config_file: &Path,
    plan: &HostIssuerLeaseRenewalPlan,
) -> io::Result<AuthorityLease> {
    require_actual_root()?;
    let config: HostAuthorityServiceConfig = read_root_json(config_file)?;
    let (clock, leases, _issuer) = open_registered_issuer(&config)?;
    let now = clock.now_unix_ms().map_err(io::Error::other)?;
    commit_existing(&config, &leases, plan, now)
}

fn require_actual_root() -> io::Result<()> {
    // SAFETY: read actual process credentials without pointers or mutation.
    if unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0 {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "issuer renewal requires actual Root",
        ));
    }
    Ok(())
}

fn prepare_existing(
    config: &HostAuthorityServiceConfig,
    leases: &AuthorityLeaseRegistry,
    now: u64,
    lifetime_ms: u64,
) -> io::Result<HostIssuerLeaseRenewalPlan> {
    if !(1..=MAX_ISSUER_RENEWAL_MS).contains(&lifetime_ms) {
        return Err(io::Error::other("invalid issuer renewal lifetime"));
    }
    let previous = leases
        .read_lease(&config.lease_id)
        .map_err(io::Error::other)?
        .ok_or_else(|| io::Error::other("original canonical issuer lease missing"))?
        .lease;
    if previous.revision != config.lease_revision {
        return Err(io::Error::other("original issuer revision differs"));
    }
    ensure_current_epoch_unrevoked(leases, &previous)?;
    let revision = previous
        .revision
        .checked_add(1)
        .ok_or_else(|| io::Error::other("issuer revision overflow"))?;
    let expiry = now
        .checked_add(lifetime_ms)
        .ok_or_else(|| io::Error::other("issuer expiry overflow"))?;
    let renewed = AuthorityLease {
        revision,
        issued_at_unix_ms: now,
        expires_at_unix_ms: expiry,
        ..previous.clone()
    };
    let plan = HostIssuerLeaseRenewalPlan {
        schema_version: 1,
        signer_id: config.signer_id.clone(),
        verifying_key: config.expected_verifying_key,
        previous_lease: previous,
        renewed_lease: renewed,
    };
    validate_plan(config, &plan, now)?;
    Ok(plan)
}

fn validate_plan(
    config: &HostAuthorityServiceConfig,
    plan: &HostIssuerLeaseRenewalPlan,
    now: u64,
) -> io::Result<()> {
    let old = &plan.previous_lease;
    let new = &plan.renewed_lease;
    old.validate().map_err(io::Error::other)?;
    new.validate().map_err(io::Error::other)?;
    if config.schema_version != 1
        || plan.schema_version != 1
        || plan.signer_id != config.signer_id
        || plan.verifying_key != config.expected_verifying_key
        || old.lease_id != config.lease_id
        || old.revision != config.lease_revision
        || new.lease_id != old.lease_id
        || new.authority_epoch != old.authority_epoch
        || new.binding != old.binding
        || Some(new.revision) != old.revision.checked_add(1)
        || new.issued_at_unix_ms < old.issued_at_unix_ms
        || new.expires_at_unix_ms <= old.expires_at_unix_ms
        || new.expires_at_unix_ms - new.issued_at_unix_ms > MAX_ISSUER_RENEWAL_MS
        || now < new.issued_at_unix_ms
        || now >= new.expires_at_unix_ms
    {
        return Err(io::Error::other(
            "issuer renewal plan differs or is not live",
        ));
    }
    Ok(())
}

fn ensure_current_epoch_unrevoked(
    leases: &AuthorityLeaseRegistry,
    lease: &AuthorityLease,
) -> io::Result<()> {
    if leases.frontier().map_err(io::Error::other)?.authority_epoch != lease.authority_epoch
        || leases
            .read_revocation(&lease.lease_id)
            .map_err(io::Error::other)?
            .is_some()
    {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "original issuer epoch changed or lease was revoked",
        ));
    }
    Ok(())
}

fn commit_existing(
    config: &HostAuthorityServiceConfig,
    leases: &AuthorityLeaseRegistry,
    plan: &HostIssuerLeaseRenewalPlan,
    now: u64,
) -> io::Result<AuthorityLease> {
    validate_plan(config, plan, now)?;
    ensure_current_epoch_unrevoked(leases, &plan.previous_lease)?;
    let current = leases
        .read_lease(&plan.previous_lease.lease_id)
        .map_err(io::Error::other)?
        .ok_or_else(|| io::Error::other("original canonical issuer lease missing"))?
        .lease;
    if current != plan.previous_lease && current != plan.renewed_lease {
        return Err(io::Error::other("original issuer lease changed"));
    }
    // The ORIGINAL registry locks and rechecks epoch/revocation/revision even
    // for an exact existing postimage. A lost acknowledgement never bypasses
    // revocation, restores a pruned lease, or increments the store twice.
    let observed = leases
        .put_lease(plan.renewed_lease.clone(), plan.previous_lease.revision)
        .map_err(io::Error::other)?;
    if observed.lease != plan.renewed_lease {
        return Err(io::Error::other("original issuer CAS postimage differs"));
    }
    Ok(observed.lease)
}

#[cfg(test)]
#[path = "authority_host_issuer_renewal_tests.rs"]
mod tests;
