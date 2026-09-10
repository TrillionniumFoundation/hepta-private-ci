#![forbid(unsafe_code)]

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

const MAX_HOSTS: usize = 256;
const MAX_ACTIVE_GRANTS: usize = 16_384;

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct Resources {
    pub cpu_millis: u64,
    pub memory_bytes: u64,
    pub accelerator_millis: u64,
}

impl Resources {
    pub fn checked_add(self, other: Self) -> Result<Self, Error> {
        Ok(Self {
            cpu_millis: self
                .cpu_millis
                .checked_add(other.cpu_millis)
                .ok_or(Error::ArithmeticOverflow)?,
            memory_bytes: self
                .memory_bytes
                .checked_add(other.memory_bytes)
                .ok_or(Error::ArithmeticOverflow)?,
            accelerator_millis: self
                .accelerator_millis
                .checked_add(other.accelerator_millis)
                .ok_or(Error::ArithmeticOverflow)?,
        })
    }

    pub fn fits(self, capacity: Self) -> bool {
        self.cpu_millis <= capacity.cpu_millis
            && self.memory_bytes <= capacity.memory_bytes
            && self.accelerator_millis <= capacity.accelerator_millis
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HostObservation {
    pub host_id: String,
    pub failure_domain_id: String,
    pub generation: u64,
    pub observed_at_ms: u64,
    pub valid_until_ms: u64,
    pub capacity: Resources,
}

#[derive(Clone, Debug, Eq, PartialEq)]
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

#[derive(Debug)]
pub struct LeaseLedger {
    hosts: BTreeMap<String, HostObservation>,
    grants: BTreeMap<String, AllocationGrant>,
}

impl Default for LeaseLedger {
    fn default() -> Self {
        Self::new()
    }
}

impl LeaseLedger {
    pub fn new() -> Self {
        Self {
            hosts: BTreeMap::new(),
            grants: BTreeMap::new(),
        }
    }

    pub fn admit_host(&mut self, observation: HostObservation) -> Result<(), Error> {
        validate_identity(&observation.host_id, "host")?;
        validate_identity(&observation.failure_domain_id, "failure domain")?;
        if observation.generation == 0
            || observation.observed_at_ms >= observation.valid_until_ms
            || observation.capacity == Resources::default()
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
        if self.grants.len() >= MAX_ACTIVE_GRANTS {
            return Err(Error::GrantCapacityExceeded);
        }
        let committed = self.committed_resources(&grant.host_id, now_ms)?;
        if !committed.checked_add(grant.resources)?.fits(host.capacity) {
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
        if current.authority_epoch != authority_epoch || current.semantic_digest != semantic_digest {
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
                let host = self.hosts.get(&current.host_id).ok_or(Error::HostNotFound)?;
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

    fn committed_resources(&self, host_id: &str, now_ms: u64) -> Result<Resources, Error> {
        self.grants
            .values()
            .filter(|grant| {
                grant.host_id == host_id && !grant.revoked && grant.expires_at_ms > now_ms
            })
            .try_fold(Resources::default(), |sum, grant| {
                sum.checked_add(grant.resources)
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
        || !value.bytes().all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
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
    if grant.resources == Resources::default() {
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

fn main() {}

#[cfg(test)]
mod tests {
    use super::*;

    fn host() -> HostObservation {
        HostObservation {
            host_id: "host.1".to_string(),
            failure_domain_id: "rack.1".to_string(),
            generation: 1,
            observed_at_ms: 100,
            valid_until_ms: 1_000,
            capacity: Resources {
                cpu_millis: 1_000,
                memory_bytes: 4_096,
                accelerator_millis: 0,
            },
        }
    }

    fn grant(id: &str, cpu: u64) -> AllocationGrant {
        AllocationGrant {
            allocation_id: id.to_string(),
            request_id: format!("request.{id}"),
            principal_id: "principal.1".to_string(),
            host_id: "host.1".to_string(),
            failure_domain_id: "rack.1".to_string(),
            host_generation: 1,
            authority_epoch: 3,
            lease_generation: 1,
            expires_at_ms: 800,
            resources: Resources {
                cpu_millis: cpu,
                memory_bytes: 1_024,
                accelerator_millis: 0,
            },
            semantic_digest: "1".repeat(64),
            revoked: false,
        }
    }

    #[test]
    fn conserves_capacity_and_reuses_identical_grant() {
        let mut ledger = LeaseLedger::new();
        ledger.admit_host(host()).expect("host");
        let first = grant("one", 600);
        let receipt = ledger.issue(200, first.clone()).expect("grant");
        assert_eq!(receipt.outcome, LeaseOutcome::Issued);
        assert_eq!(
            ledger.issue(200, first).expect("identical").outcome,
            LeaseOutcome::Unchanged
        );
        assert_eq!(ledger.issue(200, grant("two", 500)), Err(Error::CapacityExceeded));
    }

    #[test]
    fn renewal_and_revocation_are_generation_fenced() {
        let mut ledger = LeaseLedger::new();
        ledger.admit_host(host()).expect("host");
        ledger.issue(200, grant("one", 500)).expect("grant");
        assert_eq!(
            ledger.renew_or_revoke(
                300,
                "one",
                2,
                3,
                &"1".repeat(64),
                LeaseDisposition::Revoke,
            ),
            Err(Error::StaleLease)
        );
        let revoked = ledger
            .renew_or_revoke(
                300,
                "one",
                1,
                3,
                &"1".repeat(64),
                LeaseDisposition::Revoke,
            )
            .expect("revoke");
        assert!(revoked.revoked);
        assert_eq!(revoked.lease_generation, 2);
        assert_eq!(
            ledger.renew_or_revoke(
                300,
                "one",
                2,
                3,
                &"1".repeat(64),
                LeaseDisposition::Renew { expires_at_ms: 900 },
            ),
            Err(Error::Revoked)
        );
    }
}
