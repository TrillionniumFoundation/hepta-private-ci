#![forbid(unsafe_code)]

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use serde::Deserialize;
use serde::Serialize;

use crate::FleetResourceVectorV1;

const MAX_HOSTS: usize = 256;
const MAX_ACTIVE_GRANTS: usize = 16_384;
const MAX_RETAINED_GRANTS: usize = 32_768;

pub type Resources = FleetResourceVectorV1;

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
pub struct HostObservation {
    pub host_id: String,
    pub failure_domain_id: String,
    pub generation: u64,
    pub observed_at_ms: u64,
    pub valid_until_ms: u64,
    pub capacity: FleetResourceVectorV1,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
pub struct AllocationGrant {
    pub allocation_id: String,
    pub request_id: String,
    pub principal_id: String,
    pub host_id: String,
    pub failure_domain_id: String,
    pub host_generation: u64,
    pub authority_epoch: u64,
    pub lease_generation: u64,
    pub expires_at_ms: u64,
    pub resources: FleetResourceVectorV1,
    pub semantic_digest: String,
    pub revoked: bool,
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

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
pub struct LeaseLedger {
    hosts: BTreeMap<String, HostObservation>,
    grants: BTreeMap<String, AllocationGrant>,
}

impl LeaseLedger {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn hosts(&self) -> impl Iterator<Item = &HostObservation> {
        self.hosts.values()
    }

    pub fn grants(&self) -> impl Iterator<Item = &AllocationGrant> {
        self.grants.values()
    }

    pub fn admit_host(&mut self, observation: HostObservation) -> Result<(), Error> {
        validate_identity(&observation.host_id, "host")?;
        validate_identity(&observation.failure_domain_id, "failure domain")?;
        if observation.generation == 0
            || observation.observed_at_ms >= observation.valid_until_ms
            || observation.capacity.is_zero()
        {
            return Err(Error::HostCapacity);
        }
        if let Some(current) = self.hosts.get(&observation.host_id) {
            if observation.generation < current.generation {
                return Err(Error::InvalidGeneration);
            }
            if observation.generation == current.generation && observation != *current {
                return Err(Error::Conflict);
            }
            if observation == *current {
                return Ok(());
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
        self.prune_expired(now_ms);
        validate_grant(&grant)?;
        let host = self.hosts.get(&grant.host_id).ok_or(Error::HostNotFound)?;
        if now_ms < host.observed_at_ms || now_ms >= host.valid_until_ms {
            return Err(Error::StaleHost);
        }
        if grant.host_generation != host.generation
            || grant.failure_domain_id != host.failure_domain_id
        {
            return Err(Error::StaleHost);
        }
        if grant.expires_at_ms <= now_ms || grant.expires_at_ms > host.valid_until_ms {
            return Err(Error::InvalidTime);
        }
        if let Some(current) = self.grants.get(&grant.allocation_id) {
            if equivalent(current, &grant) {
                return Ok(receipt(current, LeaseOutcome::Unchanged));
            }
            return Err(Error::Conflict);
        }
        let active_grants = self
            .grants
            .values()
            .filter(|current| !current.revoked && current.expires_at_ms > now_ms)
            .count();
        if active_grants >= MAX_ACTIVE_GRANTS || self.grants.len() >= MAX_RETAINED_GRANTS {
            return Err(Error::GrantCapacityExceeded);
        }
        let committed = self.committed_resources(&grant.host_id, now_ms)?;
        let Some(total) = committed.checked_add(grant.resources) else {
            return Err(Error::ArithmeticOverflow);
        };
        if !total.fits(host.capacity) {
            return Err(Error::CapacityExceeded);
        }
        grant.revoked = false;
        let result = receipt(&grant, LeaseOutcome::Issued);
        self.grants.insert(grant.allocation_id.clone(), grant);
        Ok(result)
    }

    pub fn issue_batch(
        &mut self,
        now_ms: u64,
        grants: Vec<AllocationGrant>,
    ) -> Result<Vec<LeaseReceipt>, Error> {
        let mut candidate = self.clone();
        let mut receipts = Vec::with_capacity(grants.len());
        for grant in grants {
            receipts.push(candidate.issue(now_ms, grant)?);
        }
        *self = candidate;
        Ok(receipts)
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
        self.prune_expired(now_ms);
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
                grant.revoked = true;
                grant.lease_generation = grant
                    .lease_generation
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
                if now_ms >= host.valid_until_ms || host.generation != current.host_generation {
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
                grant.expires_at_ms = expires_at_ms;
                grant.lease_generation = grant
                    .lease_generation
                    .checked_add(1)
                    .ok_or(Error::ArithmeticOverflow)?;
                Ok(receipt(grant, LeaseOutcome::Renewed))
            }
        }
    }

    pub fn get(&self, allocation_id: &str) -> Option<&AllocationGrant> {
        self.grants.get(allocation_id)
    }

    pub fn available_resources(
        &self,
        host_id: &str,
        now_ms: u64,
    ) -> Result<FleetResourceVectorV1, Error> {
        let host = self.hosts.get(host_id).ok_or(Error::HostNotFound)?;
        if now_ms < host.observed_at_ms || now_ms >= host.valid_until_ms {
            return Err(Error::StaleHost);
        }
        let committed = self.committed_resources(host_id, now_ms)?;
        host.capacity
            .checked_sub(committed)
            .ok_or(Error::ArithmeticOverflow)
    }

    pub fn enforce(
        &self,
        now_ms: u64,
        allocation_id: &str,
        host_id: &str,
        principal_id: &str,
        lease_generation: u64,
    ) -> Result<&AllocationGrant, Error> {
        let grant = self.grants.get(allocation_id).ok_or(Error::AllocationNotFound)?;
        if grant.revoked || grant.expires_at_ms <= now_ms {
            return Err(Error::Revoked);
        }
        if grant.host_id != host_id || grant.principal_id != principal_id {
            return Err(Error::Conflict);
        }
        if grant.lease_generation != lease_generation {
            return Err(Error::StaleLease);
        }
        Ok(grant)
    }

    pub fn prune_expired(&mut self, now_ms: u64) -> usize {
        let before = self.grants.len();
        self.grants.retain(|_, grant| grant.expires_at_ms > now_ms);
        before - self.grants.len()
    }

    fn committed_resources(
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
                sum.checked_add(grant.resources).ok_or(Error::ArithmeticOverflow)
            })
    }
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
    if grant.host_generation == 0 || grant.authority_epoch == 0 || grant.lease_generation == 0 {
        return Err(Error::InvalidGeneration);
    }
    if grant.resources.is_zero() {
        return Err(Error::HostCapacity);
    }
    Ok(())
}

fn equivalent(left: &AllocationGrant, right: &AllocationGrant) -> bool {
    left.allocation_id == right.allocation_id
        && left.request_id == right.request_id
        && left.principal_id == right.principal_id
        && left.host_id == right.host_id
        && left.failure_domain_id == right.failure_domain_id
        && left.host_generation == right.host_generation
        && left.authority_epoch == right.authority_epoch
        && left.lease_generation == right.lease_generation
        && left.expires_at_ms == right.expires_at_ms
        && left.resources == right.resources
        && left.semantic_digest == right.semantic_digest
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
