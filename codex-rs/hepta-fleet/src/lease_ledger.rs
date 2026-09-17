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
const MAX_CONSUMPTION_OBSERVATION_AGE_MS: u64 = 30_000;

/// Compatibility name retained for existing lease-ledger callers.
pub type Resources = FleetResourceVectorV1;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostObservation {
    pub host_id: String,
    pub failure_domain_id: String,
    pub generation: u64,
    pub observed_at_ms: u64,
    pub valid_until_ms: u64,
    pub capacity: Resources,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
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
    pub resources: Resources,
    pub semantic_digest: String,
    pub revoked: bool,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetConsumptionObservationV1 {
    pub allocation_id: String,
    pub lease_generation: u64,
    pub authority_epoch: u64,
    pub semantic_digest: String,
    pub observed_at_ms: u64,
    pub holder_present: bool,
    pub resources_in_use: Resources,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FleetReconciliationOutcomeV1 {
    Confirmed,
    Released,
    Quarantined,
    Unchanged,
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

#[derive(Clone, Debug, Default)]
pub struct LeaseLedger {
    hosts: BTreeMap<String, HostObservation>,
    grants: BTreeMap<String, AllocationGrant>,
    holder_observations: BTreeMap<String, FleetConsumptionObservationV1>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct LeaseLedgerStateV1 {
    hosts: BTreeMap<String, HostObservation>,
    grants: BTreeMap<String, AllocationGrant>,
    #[serde(default)]
    holder_observations: BTreeMap<String, FleetConsumptionObservationV1>,
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
            if observation.generation == current.generation && observation != *current {
                return Err(Error::Conflict);
            }
            if observation == *current {
                return Ok(());
            }
            if observation.generation > current.generation {
                self.fence_host_generation(&observation.host_id)?;
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
        let host = self
            .hosts
            .get(&grant.host_id)
            .cloned()
            .ok_or(Error::HostNotFound)?;
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
        if self.active_grant_count(now_ms) >= MAX_ACTIVE_GRANTS {
            return Err(Error::GrantCapacityExceeded);
        }
        if self.grants.len() >= MAX_RETAINED_GRANTS {
            self.prune_terminal(now_ms);
            if self.grants.len() >= MAX_RETAINED_GRANTS {
                return Err(Error::GrantCapacityExceeded);
            }
        }
        let committed = self.reserved_resources_for_placement(&grant.host_id, now_ms)?;
        let total = committed
            .checked_add(grant.resources)
            .ok_or(Error::ArithmeticOverflow)?;
        if !total.fits(host.capacity) {
            return Err(Error::CapacityExceeded);
        }
        grant.revoked = false;
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

    pub fn reconcile_consumption(
        &mut self,
        now_ms: u64,
        observation: FleetConsumptionObservationV1,
    ) -> Result<FleetReconciliationOutcomeV1, Error> {
        validate_identity(&observation.allocation_id, "allocation")?;
        validate_digest(&observation.semantic_digest)?;
        if observation.lease_generation == 0
            || observation.authority_epoch == 0
            || observation.observed_at_ms == 0
            || observation.observed_at_ms > now_ms
            || now_ms.saturating_sub(observation.observed_at_ms)
                > MAX_CONSUMPTION_OBSERVATION_AGE_MS
        {
            return Err(Error::InvalidTime);
        }
        if observation.holder_present == observation.resources_in_use.is_zero() {
            return Err(Error::HostCapacity);
        }
        let grant = self
            .grants
            .get(&observation.allocation_id)
            .ok_or(Error::AllocationNotFound)?;
        if grant.authority_epoch != observation.authority_epoch
            || grant.semantic_digest != observation.semantic_digest
        {
            return Err(Error::Conflict);
        }
        if observation.lease_generation > grant.lease_generation {
            return Err(Error::StaleLease);
        }
        if let Some(previous) = self.holder_observations.get(&observation.allocation_id) {
            if previous == &observation {
                return Ok(FleetReconciliationOutcomeV1::Unchanged);
            }
            if observation.observed_at_ms <= previous.observed_at_ms {
                return Err(Error::Conflict);
            }
        }
        let outcome = if !observation.holder_present {
            FleetReconciliationOutcomeV1::Released
        } else if observation.lease_generation != grant.lease_generation
            || grant.revoked
            || grant.expires_at_ms <= now_ms
            || !observation.resources_in_use.fits(grant.resources)
        {
            FleetReconciliationOutcomeV1::Quarantined
        } else {
            FleetReconciliationOutcomeV1::Confirmed
        };
        self.holder_observations
            .insert(observation.allocation_id.clone(), observation);
        Ok(outcome)
    }

    pub fn get(&self, allocation_id: &str) -> Option<&AllocationGrant> {
        self.grants.get(allocation_id)
    }

    pub fn last_consumption_observation(
        &self,
        allocation_id: &str,
    ) -> Option<&FleetConsumptionObservationV1> {
        self.holder_observations.get(allocation_id)
    }

    /// Remove terminal grants only after an observed holder release. Expiry or
    /// revocation alone cannot prove that physical resources are free to reuse.
    pub fn prune_terminal(&mut self, now_ms: u64) -> usize {
        let removable: Vec<_> = self
            .grants
            .values()
            .filter(|grant| grant.revoked || grant.expires_at_ms <= now_ms)
            .filter(|grant| {
                self.holder_observations
                    .get(&grant.allocation_id)
                    .is_some_and(|observation| !observation.holder_present)
            })
            .map(|grant| grant.allocation_id.clone())
            .collect();
        for allocation_id in &removable {
            self.grants.remove(allocation_id);
            self.holder_observations.remove(allocation_id);
        }
        removable.len()
    }

    pub(crate) fn snapshot_state(&self) -> LeaseLedgerStateV1 {
        LeaseLedgerStateV1 {
            hosts: self.hosts.clone(),
            grants: self.grants.clone(),
            holder_observations: self.holder_observations.clone(),
        }
    }

    pub(crate) fn restore_state(state: LeaseLedgerStateV1, now_ms: u64) -> Result<Self, Error> {
        let ledger = Self {
            hosts: state.hosts,
            grants: state.grants,
            holder_observations: state.holder_observations,
        };
        ledger.validate_recovered(now_ms)?;
        Ok(ledger)
    }

    pub(crate) fn validate_recovered(&self, now_ms: u64) -> Result<(), Error> {
        if self.hosts.len() > MAX_HOSTS {
            return Err(Error::CapacityExceeded);
        }
        if self.grants.len() > MAX_RETAINED_GRANTS {
            return Err(Error::GrantCapacityExceeded);
        }
        for host in self.hosts.values() {
            validate_host(host)?;
        }
        for grant in self.grants.values() {
            validate_grant(grant)?;
            let host = self.hosts.get(&grant.host_id).ok_or(Error::HostNotFound)?;
            if grant.failure_domain_id != host.failure_domain_id
                || grant.host_generation > host.generation
            {
                return Err(Error::StaleHost);
            }
            if !grant.revoked && grant.expires_at_ms > now_ms {
                if grant.host_generation != host.generation
                    || now_ms < host.observed_at_ms
                    || now_ms >= host.valid_until_ms
                    || grant.expires_at_ms > host.valid_until_ms
                {
                    return Err(Error::StaleHost);
                }
            }
        }
        for (allocation_id, observation) in &self.holder_observations {
            if allocation_id != &observation.allocation_id {
                return Err(Error::Conflict);
            }
            validate_digest(&observation.semantic_digest)?;
            let grant = self.grants.get(allocation_id).ok_or(Error::AllocationNotFound)?;
            if observation.authority_epoch != grant.authority_epoch
                || observation.semantic_digest != grant.semantic_digest
                || observation.lease_generation == 0
                || observation.lease_generation > grant.lease_generation
                || observation.observed_at_ms == 0
                || observation.holder_present == observation.resources_in_use.is_zero()
            {
                return Err(Error::Conflict);
            }
        }
        if self.active_grant_count(now_ms) > MAX_ACTIVE_GRANTS {
            return Err(Error::GrantCapacityExceeded);
        }
        for host_id in self.hosts.keys() {
            let reserved = self.reserved_resources_for_placement(host_id, now_ms)?;
            let capacity = self.hosts.get(host_id).ok_or(Error::HostNotFound)?.capacity;
            if !reserved.fits(capacity) {
                return Err(Error::CapacityExceeded);
            }
        }
        Ok(())
    }

    pub(crate) fn hosts(&self) -> &BTreeMap<String, HostObservation> {
        &self.hosts
    }

    pub(crate) fn grants(&self) -> &BTreeMap<String, AllocationGrant> {
        &self.grants
    }

    pub(crate) fn reserved_resources_for_placement(
        &self,
        host_id: &str,
        now_ms: u64,
    ) -> Result<Resources, Error> {
        self.grants
            .values()
            .filter(|grant| grant.host_id == host_id)
            .try_fold(Resources::default(), |sum, grant| {
                let active = !grant.revoked && grant.expires_at_ms > now_ms;
                let released = self
                    .holder_observations
                    .get(&grant.allocation_id)
                    .is_some_and(|observation| !observation.holder_present);
                if !active && released {
                    return Ok(sum);
                }
                if let Some(observation) = self.holder_observations.get(&grant.allocation_id)
                    && observation.holder_present
                    && !observation.resources_in_use.fits(grant.resources)
                {
                    return Err(Error::CapacityExceeded);
                }
                sum.checked_add(grant.resources)
                    .ok_or(Error::ArithmeticOverflow)
            })
    }

    fn fence_host_generation(&mut self, host_id: &str) -> Result<(), Error> {
        if self
            .grants
            .values()
            .any(|grant| grant.host_id == host_id && !grant.revoked && grant.lease_generation == u64::MAX)
        {
            return Err(Error::ArithmeticOverflow);
        }
        for grant in self
            .grants
            .values_mut()
            .filter(|grant| grant.host_id == host_id && !grant.revoked)
        {
            grant.revoked = true;
            grant.lease_generation += 1;
        }
        Ok(())
    }

    fn active_grant_count(&self, now_ms: u64) -> usize {
        self.grants
            .values()
            .filter(|grant| !grant.revoked && grant.expires_at_ms > now_ms)
            .count()
    }
}

fn validate_host(observation: &HostObservation) -> Result<(), Error> {
    validate_identity(&observation.host_id, "host")?;
    validate_identity(&observation.failure_domain_id, "failure domain")?;
    if observation.generation == 0
        || observation.observed_at_ms >= observation.valid_until_ms
        || observation.capacity.is_zero()
    {
        return Err(Error::HostCapacity);
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
