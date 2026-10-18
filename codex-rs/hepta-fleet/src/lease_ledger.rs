#![forbid(unsafe_code)]

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::collections::VecDeque;
use std::fmt;
use std::sync::Arc;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::SystemAuthorityClock;

use crate::ResourceVectorV1;
pub use crate::lease_model::AllocationGrant;
pub use crate::lease_model::Error;
pub use crate::lease_model::HostObservation;
pub use crate::lease_model::LeaseDisposition;
pub use crate::lease_model::LeaseHistoryRecord;
pub use crate::lease_model::LeaseHistoryState;
pub use crate::lease_model::LeaseLedgerMetrics;
pub use crate::lease_model::LeaseOutcome;
pub use crate::lease_model::LeaseReceipt;
pub use crate::lease_model::MAX_ACTIVE_GRANTS;
pub use crate::lease_model::MAX_EXPIRED_PER_SWEEP;
pub use crate::lease_model::MAX_HOSTS;
pub use crate::lease_model::MAX_LEASE_HISTORY;
pub use crate::lease_model::Resources;

pub struct LeaseLedger {
    clock: Arc<dyn AuthorityClock>,
    last_now_ms: Option<u64>,
    hosts: BTreeMap<String, HostObservation>,
    active_grants: BTreeMap<String, AllocationGrant>,
    reserved: BTreeMap<String, ResourceVectorV1>,
    expiry_index: BTreeMap<u64, BTreeSet<String>>,
    history_order: VecDeque<String>,
    history: BTreeMap<String, LeaseHistoryRecord>,
    compacted_history: u64,
}

impl fmt::Debug for LeaseLedger {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("LeaseLedger")
            .field("last_now_ms", &self.last_now_ms)
            .field("hosts", &self.hosts)
            .field("active_grants", &self.active_grants)
            .field("reserved", &self.reserved)
            .field("expiry_index", &self.expiry_index)
            .field("history", &self.history)
            .field("compacted_history", &self.compacted_history)
            .finish_non_exhaustive()
    }
}

impl Default for LeaseLedger {
    fn default() -> Self {
        Self::new()
    }
}

impl LeaseLedger {
    /// Compatibility constructor backed by the system clock. Production owners
    /// use `with_clock` with their protected time projection.
    pub fn new() -> Self {
        Self::with_clock(Arc::new(SystemAuthorityClock))
    }

    pub fn with_clock(clock: Arc<dyn AuthorityClock>) -> Self {
        Self {
            clock,
            last_now_ms: None,
            hosts: BTreeMap::new(),
            active_grants: BTreeMap::new(),
            reserved: BTreeMap::new(),
            expiry_index: BTreeMap::new(),
            history_order: VecDeque::new(),
            history: BTreeMap::new(),
            compacted_history: 0,
        }
    }

    pub fn admit_host(&mut self, observation: HostObservation) -> Result<(), Error> {
        validate_identity(&observation.host_id, "host")?;
        validate_identity(&observation.failure_domain_id, "failure domain")?;
        observation.capacity.validate_nonzero()?;
        if observation.generation == 0 || observation.observed_at_ms >= observation.valid_until_ms {
            return Err(Error::HostCapacity);
        }
        let now_ms = self.owner_now_ms()?;
        if observation.observed_at_ms > now_ms || now_ms >= observation.valid_until_ms {
            return Err(Error::StaleHost);
        }

        let current = self.hosts.get(&observation.host_id).cloned();
        if let Some(current) = current {
            if observation.generation < current.generation {
                return Err(Error::InvalidGeneration);
            }
            if observation.generation == current.generation && observation != current {
                return Err(Error::Conflict);
            }
            if observation == current {
                return Ok(());
            }
            self.retire_prior_host_generation(
                &observation.host_id,
                observation.generation,
                now_ms,
            )?;
        } else if self.hosts.len() >= MAX_HOSTS {
            return Err(Error::CapacityExceeded);
        }
        self.hosts.insert(observation.host_id.clone(), observation);
        Ok(())
    }

    pub fn issue(&mut self, mut grant: AllocationGrant) -> Result<LeaseReceipt, Error> {
        validate_grant(&grant)?;
        let now_ms = self.owner_now_ms()?;
        self.collect_expired_at(now_ms, MAX_EXPIRED_PER_SWEEP)?;
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
        if let Some(current) = self.active_grants.get(&grant.allocation_id) {
            if equivalent(current, &grant) {
                return Ok(receipt(current, LeaseOutcome::Unchanged));
            }
            return Err(Error::Conflict);
        }
        if self.history.contains_key(&grant.allocation_id) {
            return Err(Error::Conflict);
        }
        if self.active_grants.len() >= MAX_ACTIVE_GRANTS {
            return Err(Error::GrantCapacityExceeded);
        }
        let committed = self
            .reserved
            .get(&grant.host_id)
            .copied()
            .unwrap_or_default();
        let next = committed.checked_add(grant.resources)?;
        grant.resources.compatible_with(host.capacity)?;
        if !next.fits(host.capacity) {
            return Err(Error::CapacityExceeded);
        }

        grant.revoked = false;
        let result = receipt(&grant, LeaseOutcome::Issued);
        self.reserved.insert(grant.host_id.clone(), next);
        self.expiry_index
            .entry(grant.expires_at_ms)
            .or_default()
            .insert(grant.allocation_id.clone());
        self.active_grants
            .insert(grant.allocation_id.clone(), grant);
        Ok(result)
    }

    pub fn renew_or_revoke(
        &mut self,
        allocation_id: &str,
        expected_lease_generation: u64,
        authority_epoch: u64,
        semantic_digest: &str,
        disposition: LeaseDisposition,
    ) -> Result<LeaseReceipt, Error> {
        validate_identity(allocation_id, "allocation")?;
        validate_digest(semantic_digest)?;
        let now_ms = self.owner_now_ms()?;
        self.collect_expired_at(now_ms, MAX_EXPIRED_PER_SWEEP)?;
        let Some(current) = self.active_grants.get(allocation_id).cloned() else {
            return self.retired_disposition(
                allocation_id,
                expected_lease_generation,
                authority_epoch,
                semantic_digest,
                disposition,
            );
        };
        if current.lease_generation != expected_lease_generation {
            return Err(Error::StaleLease);
        }
        if current.authority_epoch != authority_epoch || current.semantic_digest != semantic_digest
        {
            return Err(Error::Conflict);
        }
        match disposition {
            LeaseDisposition::Revoke => {
                let mut retired = self.remove_active(allocation_id)?;
                retired.revoked = true;
                retired.lease_generation = retired
                    .lease_generation
                    .checked_add(1)
                    .ok_or(Error::ArithmeticOverflow)?;
                let result = receipt(&retired, LeaseOutcome::Revoked);
                self.append_history(retired, LeaseHistoryState::Revoked, now_ms);
                Ok(result)
            }
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
                remove_expiry_entry(&mut self.expiry_index, current.expires_at_ms, allocation_id);
                let grant = self
                    .active_grants
                    .get_mut(allocation_id)
                    .ok_or(Error::AllocationNotFound)?;
                grant.expires_at_ms = expires_at_ms;
                grant.lease_generation = grant
                    .lease_generation
                    .checked_add(1)
                    .ok_or(Error::InvalidGeneration)?;
                self.expiry_index
                    .entry(expires_at_ms)
                    .or_default()
                    .insert(allocation_id.to_string());
                Ok(receipt(grant, LeaseOutcome::Renewed))
            }
        }
    }

    pub fn collect_expired(&mut self) -> Result<usize, Error> {
        let now_ms = self.owner_now_ms()?;
        self.collect_expired_at(now_ms, MAX_EXPIRED_PER_SWEEP)
    }

    pub fn get(&self, allocation_id: &str) -> Option<&AllocationGrant> {
        self.active_grants.get(allocation_id)
    }

    pub fn history(&self, allocation_id: &str) -> Option<&LeaseHistoryRecord> {
        self.history.get(allocation_id)
    }

    pub fn reserved_for_host(&self, host_id: &str) -> ResourceVectorV1 {
        self.reserved.get(host_id).copied().unwrap_or_default()
    }

    pub fn metrics(&self) -> LeaseLedgerMetrics {
        LeaseLedgerMetrics {
            hosts: self.hosts.len(),
            active_grants: self.active_grants.len(),
            retained_history: self.history.len(),
            compacted_history: self.compacted_history,
        }
    }

    fn owner_now_ms(&mut self) -> Result<u64, Error> {
        let now_ms = self
            .clock
            .now_unix_ms()
            .map_err(|_| Error::ClockUnavailable)?;
        if self.last_now_ms.is_some_and(|last| now_ms < last) {
            return Err(Error::ClockRollback);
        }
        self.last_now_ms = Some(now_ms);
        Ok(now_ms)
    }

    fn collect_expired_at(&mut self, now_ms: u64, limit: usize) -> Result<usize, Error> {
        let mut retired = 0;
        while retired < limit {
            let Some((&expires_at_ms, _)) = self.expiry_index.first_key_value() else {
                break;
            };
            if expires_at_ms > now_ms {
                break;
            }
            let allocation_ids = self
                .expiry_index
                .remove(&expires_at_ms)
                .ok_or(Error::Conflict)?;
            let mut unprocessed = BTreeSet::new();
            for allocation_id in allocation_ids {
                if retired >= limit {
                    unprocessed.insert(allocation_id);
                    continue;
                }
                let Some(grant) = self.active_grants.get(&allocation_id) else {
                    continue;
                };
                if grant.expires_at_ms > now_ms {
                    unprocessed.insert(allocation_id);
                    continue;
                }
                let expired = self.remove_active(&allocation_id)?;
                self.append_history(expired, LeaseHistoryState::Expired, now_ms);
                retired += 1;
            }
            if !unprocessed.is_empty() {
                self.expiry_index.insert(expires_at_ms, unprocessed);
            }
        }
        Ok(retired)
    }

    fn retire_prior_host_generation(
        &mut self,
        host_id: &str,
        generation: u64,
        now_ms: u64,
    ) -> Result<(), Error> {
        let allocation_ids = self
            .active_grants
            .values()
            .filter(|grant| grant.host_id == host_id && grant.host_generation < generation)
            .map(|grant| grant.allocation_id.clone())
            .collect::<Vec<_>>();
        for allocation_id in allocation_ids {
            let grant = self.remove_active(&allocation_id)?;
            self.append_history(grant, LeaseHistoryState::HostGenerationFenced, now_ms);
        }
        Ok(())
    }

    fn remove_active(&mut self, allocation_id: &str) -> Result<AllocationGrant, Error> {
        let grant = self
            .active_grants
            .remove(allocation_id)
            .ok_or(Error::AllocationNotFound)?;
        remove_expiry_entry(&mut self.expiry_index, grant.expires_at_ms, allocation_id);
        let committed = self
            .reserved
            .get(&grant.host_id)
            .copied()
            .ok_or(Error::Conflict)?;
        let next = committed.checked_sub(grant.resources)?;
        if next.is_zero() {
            self.reserved.remove(&grant.host_id);
        } else {
            self.reserved.insert(grant.host_id.clone(), next);
        }
        Ok(grant)
    }

    fn append_history(
        &mut self,
        grant: AllocationGrant,
        state: LeaseHistoryState,
        retired_at_ms: u64,
    ) {
        while self.history.len() >= MAX_LEASE_HISTORY {
            let Some(oldest) = self.history_order.pop_front() else {
                break;
            };
            if self.history.remove(&oldest).is_some() {
                self.compacted_history = self.compacted_history.saturating_add(1);
            }
        }
        self.history_order.push_back(grant.allocation_id.clone());
        self.history.insert(
            grant.allocation_id.clone(),
            LeaseHistoryRecord {
                grant,
                state,
                retired_at_ms,
            },
        );
    }

    fn retired_disposition(
        &self,
        allocation_id: &str,
        expected_lease_generation: u64,
        authority_epoch: u64,
        semantic_digest: &str,
        disposition: LeaseDisposition,
    ) -> Result<LeaseReceipt, Error> {
        let retired = self
            .history
            .get(allocation_id)
            .ok_or(Error::AllocationNotFound)?;
        if retired.grant.lease_generation != expected_lease_generation {
            return Err(Error::StaleLease);
        }
        if retired.grant.authority_epoch != authority_epoch
            || retired.grant.semantic_digest != semantic_digest
        {
            return Err(Error::Conflict);
        }
        match (retired.state, disposition) {
            (LeaseHistoryState::Revoked, LeaseDisposition::Revoke) => {
                Ok(receipt(&retired.grant, LeaseOutcome::Unchanged))
            }
            (LeaseHistoryState::Revoked, LeaseDisposition::Renew { .. }) => Err(Error::Revoked),
            (
                LeaseHistoryState::Expired | LeaseHistoryState::HostGenerationFenced,
                LeaseDisposition::Renew { .. } | LeaseDisposition::Revoke,
            ) => Err(Error::StaleLease),
        }
    }
}

fn remove_expiry_entry(
    index: &mut BTreeMap<u64, BTreeSet<String>>,
    expires_at_ms: u64,
    allocation_id: &str,
) {
    let remove_key = index.get_mut(&expires_at_ms).is_some_and(|entries| {
        entries.remove(allocation_id);
        entries.is_empty()
    });
    if remove_key {
        index.remove(&expires_at_ms);
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
    grant.resources.validate_nonzero()?;
    if grant.host_generation == 0 || grant.authority_epoch == 0 || grant.lease_generation == 0 {
        return Err(Error::InvalidGeneration);
    }
    if grant.revoked {
        return Err(Error::Revoked);
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
