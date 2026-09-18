#![forbid(unsafe_code)]

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use serde::Deserialize;
use serde::Serialize;

use crate::FleetResourceVectorV1;

pub const FLEET_LEASE_LEDGER_SCHEMA_VERSION: u32 = 1;
const MAX_HOSTS: usize = 256;
const MAX_ACTIVE_GRANTS: usize = 16_384;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostObservation {
    pub schema_version: u32,
    pub host_id: String,
    pub failure_domain_id: String,
    pub generation: u64,
    pub observation_revision: u64,
    pub observed_at_ms: u64,
    pub valid_until_ms: u64,
    pub capacity: FleetResourceVectorV1,
    pub semantic_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AllocationGrant {
    pub schema_version: u32,
    pub allocation_id: String,
    pub request_id: String,
    pub principal_id: String,
    pub host_id: String,
    pub failure_domain_id: String,
    pub host_generation: u64,
    pub host_observation_revision: u64,
    pub authority_epoch: u64,
    pub lease_generation: u64,
    pub predecessor_lease_generation: Option<u64>,
    pub issued_at_ms: u64,
    pub expires_at_ms: u64,
    pub resources: FleetResourceVectorV1,
    pub semantic_digest: String,
    pub revoked: bool,
    pub revoked_at_ms: Option<u64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LeaseDisposition {
    Renew { expires_at_ms: u64 },
    Revoke,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LeaseOutcome {
    Issued,
    Renewed,
    Revoked,
    Unchanged,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LeaseReceipt {
    pub allocation_id: String,
    pub lease_generation: u64,
    pub expires_at_ms: u64,
    pub revoked: bool,
    pub outcome: LeaseOutcome,
    pub semantic_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    InvalidIdentity(&'static str),
    InvalidDigest,
    InvalidTime,
    InvalidGeneration,
    InvalidObservationRevision,
    HostCapacity,
    CapacityExceeded,
    GrantCapacityExceeded,
    HostNotFound,
    AllocationNotFound,
    Conflict,
    StaleHost,
    StaleLease,
    Revoked,
    ArithmeticOverflow,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

#[derive(Clone, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LeaseLedger {
    hosts: BTreeMap<String, HostObservation>,
    grants: BTreeMap<String, AllocationGrant>,
}

impl LeaseLedger {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn admit_host(&mut self, observation: HostObservation) -> Result<(), Error> {
        validate_host(&observation)?;
        if let Some(current) = self.hosts.get(&observation.host_id) {
            if observation.generation < current.generation {
                return Err(Error::InvalidGeneration);
            }
            if observation.generation == current.generation {
                if observation.observation_revision < current.observation_revision {
                    return Err(Error::InvalidObservationRevision);
                }
                if observation.observation_revision == current.observation_revision {
                    return if observation == *current {
                        Ok(())
                    } else {
                        Err(Error::Conflict)
                    };
                }
                if observation.observed_at_ms < current.observed_at_ms {
                    return Err(Error::InvalidTime);
                }
            }
        } else if self.hosts.len() >= MAX_HOSTS {
            return Err(Error::CapacityExceeded);
        }
        self.hosts.insert(observation.host_id.clone(), observation);
        Ok(())
    }

    pub fn issue(
        &mut self,
        now_ms: u64,
        mut grant: AllocationGrant,
    ) -> Result<LeaseReceipt, Error> {
        validate_grant(&grant)?;
        let host = self.hosts.get(&grant.host_id).ok_or(Error::HostNotFound)?;
        validate_host_for_grant(host, &grant, now_ms)?;
        if let Some(current) = self.grants.get(&grant.allocation_id) {
            if equivalent(current, &grant) {
                return Ok(receipt(current, LeaseOutcome::Unchanged));
            }
            return Err(Error::Conflict);
        }
        if self.active_grant_count(now_ms) >= MAX_ACTIVE_GRANTS {
            return Err(Error::GrantCapacityExceeded);
        }
        let committed = self.committed_resources(&grant.host_id, now_ms)?;
        if !committed
            .checked_add(grant.resources)
            .map_err(|_| Error::ArithmeticOverflow)?
            .fits(host.capacity)
        {
            return Err(Error::CapacityExceeded);
        }
        grant.revoked = false;
        grant.revoked_at_ms = None;
        let result = receipt(&grant, LeaseOutcome::Issued);
        self.grants.insert(grant.allocation_id.clone(), grant);
        Ok(result)
    }

    pub fn renew_or_revoke(
        &mut self,
        now_ms: u64,
        allocation_id: &str,
        expected_lease_generation: u64,
        authority_epoch: u64,
        semantic_digest: &str,
        disposition: LeaseDisposition,
    ) -> Result<LeaseReceipt, Error> {
        validate_identity(allocation_id, "allocation")?;
        validate_digest(semantic_digest)?;
        let current = self
            .grants
            .get(allocation_id)
            .cloned()
            .ok_or(Error::AllocationNotFound)?;
        if current.lease_generation != expected_lease_generation {
            return Err(Error::StaleLease);
        }
        if current.authority_epoch != authority_epoch || current.semantic_digest != semantic_digest
        {
            return Err(Error::Conflict);
        }
        match disposition {
            LeaseDisposition::Revoke if current.revoked => {
                Ok(receipt(&current, LeaseOutcome::Unchanged))
            }
            LeaseDisposition::Revoke => {
                let grant = self
                    .grants
                    .get_mut(allocation_id)
                    .ok_or(Error::AllocationNotFound)?;
                let predecessor = grant.lease_generation;
                grant.revoked = true;
                grant.revoked_at_ms = Some(now_ms);
                grant.predecessor_lease_generation = Some(predecessor);
                grant.lease_generation = predecessor
                    .checked_add(1)
                    .ok_or(Error::ArithmeticOverflow)?;
                Ok(receipt(grant, LeaseOutcome::Revoked))
            }
            LeaseDisposition::Renew { .. } if current.revoked => Err(Error::Revoked),
            LeaseDisposition::Renew { expires_at_ms } => {
                let host = self
                    .hosts
                    .get(&current.host_id)
                    .ok_or(Error::HostNotFound)?;
                if now_ms < host.observed_at_ms
                    || now_ms >= host.valid_until_ms
                    || host.generation != current.host_generation
                    || host.observation_revision < current.host_observation_revision
                {
                    return Err(Error::StaleHost);
                }
                if expires_at_ms <= now_ms || expires_at_ms > host.valid_until_ms {
                    return Err(Error::InvalidTime);
                }
                if expires_at_ms == current.expires_at_ms {
                    return Ok(receipt(&current, LeaseOutcome::Unchanged));
                }
                let grant = self
                    .grants
                    .get_mut(allocation_id)
                    .ok_or(Error::AllocationNotFound)?;
                let predecessor = grant.lease_generation;
                grant.expires_at_ms = expires_at_ms;
                grant.predecessor_lease_generation = Some(predecessor);
                grant.lease_generation = predecessor
                    .checked_add(1)
                    .ok_or(Error::ArithmeticOverflow)?;
                Ok(receipt(grant, LeaseOutcome::Renewed))
            }
        }
    }

    pub fn get(&self, allocation_id: &str) -> Option<&AllocationGrant> {
        self.grants.get(allocation_id)
    }

    pub fn host(&self, host_id: &str) -> Option<&HostObservation> {
        self.hosts.get(host_id)
    }

    pub fn grants(&self) -> impl Iterator<Item = &AllocationGrant> {
        self.grants.values()
    }

    pub fn grant_for_principal(&self, principal_id: &str, now_ms: u64) -> Option<&AllocationGrant> {
        self.grants
            .values()
            .filter(|grant| {
                grant.principal_id == principal_id && !grant.revoked && grant.expires_at_ms > now_ms
            })
            .max_by_key(|grant| (grant.authority_epoch, grant.lease_generation))
    }

    pub fn active_grant_count(&self, now_ms: u64) -> usize {
        self.grants
            .values()
            .filter(|grant| !grant.revoked && grant.expires_at_ms > now_ms)
            .count()
    }

    pub fn revoke_principal(&mut self, principal_id: &str, now_ms: u64) -> Result<usize, Error> {
        validate_identity(principal_id, "principal")?;
        let ids: Vec<_> = self
            .grants
            .values()
            .filter(|grant| {
                grant.principal_id == principal_id && !grant.revoked && grant.expires_at_ms > now_ms
            })
            .map(|grant| grant.allocation_id.clone())
            .collect();
        for id in &ids {
            let grant = self.grants.get_mut(id).ok_or(Error::AllocationNotFound)?;
            let predecessor = grant.lease_generation;
            grant.revoked = true;
            grant.revoked_at_ms = Some(now_ms);
            grant.predecessor_lease_generation = Some(predecessor);
            grant.lease_generation = predecessor
                .checked_add(1)
                .ok_or(Error::ArithmeticOverflow)?;
        }
        Ok(ids.len())
    }

    /// Fences grants from an earlier supervisor/writer epoch after restart.
    pub fn fence_authority_epoch(
        &mut self,
        current_authority_epoch: u64,
        now_ms: u64,
    ) -> Result<usize, Error> {
        if current_authority_epoch == 0 {
            return Err(Error::InvalidGeneration);
        }
        let ids: Vec<_> = self
            .grants
            .values()
            .filter(|grant| {
                grant.authority_epoch != current_authority_epoch
                    && !grant.revoked
                    && grant.expires_at_ms > now_ms
            })
            .map(|grant| grant.allocation_id.clone())
            .collect();
        for id in &ids {
            let grant = self.grants.get_mut(id).ok_or(Error::AllocationNotFound)?;
            let predecessor = grant.lease_generation;
            grant.revoked = true;
            grant.revoked_at_ms = Some(now_ms);
            grant.predecessor_lease_generation = Some(predecessor);
            grant.lease_generation = predecessor
                .checked_add(1)
                .ok_or(Error::ArithmeticOverflow)?;
        }
        Ok(ids.len())
    }

    pub fn committed_resources(
        &self,
        host_id: &str,
        now_ms: u64,
    ) -> Result<FleetResourceVectorV1, Error> {
        self.grants
            .values()
            .filter(|grant| {
                grant.host_id == host_id && !grant.revoked && grant.expires_at_ms > now_ms
            })
            .try_fold(FleetResourceVectorV1::default(), |sum, grant| {
                sum.checked_add(grant.resources)
                    .map_err(|_| Error::ArithmeticOverflow)
            })
    }

    pub fn available_resources(
        &self,
        host_id: &str,
        now_ms: u64,
    ) -> Result<FleetResourceVectorV1, Error> {
        let host = self.hosts.get(host_id).ok_or(Error::HostNotFound)?;
        host.capacity
            .checked_sub(self.committed_resources(host_id, now_ms)?)
            .map_err(|_| Error::CapacityExceeded)
    }

    /// Removes only terminal history. Active leases are never pruned.
    pub fn prune_inactive(&mut self, now_ms: u64, retention_ms: u64) -> Result<usize, Error> {
        let before = self.grants.len();
        self.grants.retain(|_, grant| {
            if !grant.revoked && grant.expires_at_ms > now_ms {
                return true;
            }
            let terminal_at = grant.revoked_at_ms.unwrap_or(grant.expires_at_ms);
            terminal_at
                .checked_add(retention_ms)
                .is_some_and(|retain_until| retain_until > now_ms)
        });
        Ok(before - self.grants.len())
    }
}

fn validate_host(observation: &HostObservation) -> Result<(), Error> {
    validate_identity(&observation.host_id, "host")?;
    validate_identity(&observation.failure_domain_id, "failure domain")?;
    validate_digest(&observation.semantic_digest)?;
    if observation.schema_version != FLEET_LEASE_LEDGER_SCHEMA_VERSION
        || observation.generation == 0
        || observation.observation_revision == 0
        || observation.observed_at_ms >= observation.valid_until_ms
        || observation.capacity.is_zero()
    {
        return Err(Error::HostCapacity);
    }
    Ok(())
}

fn validate_host_for_grant(
    host: &HostObservation,
    grant: &AllocationGrant,
    now_ms: u64,
) -> Result<(), Error> {
    if now_ms < host.observed_at_ms || now_ms >= host.valid_until_ms {
        return Err(Error::StaleHost);
    }
    if grant.host_generation != host.generation
        || grant.host_observation_revision > host.observation_revision
        || grant.failure_domain_id != host.failure_domain_id
    {
        return Err(Error::StaleHost);
    }
    if grant.issued_at_ms > now_ms
        || grant.expires_at_ms <= now_ms
        || grant.expires_at_ms > host.valid_until_ms
    {
        return Err(Error::InvalidTime);
    }
    Ok(())
}

fn validate_identity(value: &str, field: &'static str) -> Result<(), Error> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        return Err(Error::InvalidIdentity(field));
    }
    Ok(())
}

fn validate_digest(value: &str) -> Result<(), Error> {
    if value.len() != 64
        || value.bytes().all(|byte| byte == b'0')
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return Err(Error::InvalidDigest);
    }
    Ok(())
}

fn validate_grant(grant: &AllocationGrant) -> Result<(), Error> {
    for (value, field) in [
        (&grant.allocation_id, "allocation"),
        (&grant.request_id, "request"),
        (&grant.principal_id, "principal"),
        (&grant.host_id, "host"),
        (&grant.failure_domain_id, "failure domain"),
    ] {
        validate_identity(value, field)?;
    }
    validate_digest(&grant.semantic_digest)?;
    if grant.schema_version != FLEET_LEASE_LEDGER_SCHEMA_VERSION
        || grant.host_generation == 0
        || grant.host_observation_revision == 0
        || grant.authority_epoch == 0
        || grant.lease_generation == 0
        || grant.predecessor_lease_generation.is_some()
        || grant.issued_at_ms >= grant.expires_at_ms
        || grant.resources.is_zero()
        || grant.revoked
        || grant.revoked_at_ms.is_some()
    {
        return Err(Error::InvalidGeneration);
    }
    Ok(())
}

fn equivalent(left: &AllocationGrant, right: &AllocationGrant) -> bool {
    let mut normalized = right.clone();
    normalized.revoked = left.revoked;
    normalized.revoked_at_ms = left.revoked_at_ms;
    normalized == *left
}

fn receipt(grant: &AllocationGrant, outcome: LeaseOutcome) -> LeaseReceipt {
    LeaseReceipt {
        allocation_id: grant.allocation_id.clone(),
        lease_generation: grant.lease_generation,
        expires_at_ms: grant.expires_at_ms,
        revoked: grant.revoked,
        outcome,
        semantic_digest: grant.semantic_digest.clone(),
    }
}

#[cfg(test)]
#[path = "lease_ledger_tests.rs"]
mod tests;
