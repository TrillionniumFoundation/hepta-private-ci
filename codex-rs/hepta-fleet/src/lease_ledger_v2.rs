#![forbid(unsafe_code)]

use crate::ResourceVectorError;
use crate::ResourceVectorV1;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::collections::VecDeque;
use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

pub const MAX_HOSTS: usize = 256;
pub const MAX_ACTIVE_GRANTS: usize = 16_384;
pub const MAX_GRANT_HISTORY: usize = 32_768;

pub trait FleetClock: fmt::Debug + Send + Sync {
    fn now_unix_ms(&self) -> Result<u64, FleetClockError>;
}

#[derive(Clone, Copy, Debug, Default)]
pub struct SystemFleetClock;

impl FleetClock for SystemFleetClock {
    fn now_unix_ms(&self) -> Result<u64, FleetClockError> {
        let duration = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| FleetClockError::BeforeUnixEpoch)?;
        u64::try_from(duration.as_millis()).map_err(|_| FleetClockError::OutOfRange)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FleetClockError {
    BeforeUnixEpoch,
    OutOfRange,
    Unavailable,
}

impl fmt::Display for FleetClockError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for FleetClockError {}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostObservation {
    pub host_id: String,
    pub failure_domain_id: String,
    pub generation: u64,
    pub observed_at_ms: u64,
    pub valid_until_ms: u64,
    pub capacity: ResourceVectorV1,
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
    pub resources: ResourceVectorV1,
    pub semantic_digest: String,
    pub revoked: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LeaseDisposition {
    Renew { expires_at_ms: u64 },
    Revoke,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LeaseOutcome {
    Issued,
    Renewed,
    Revoked,
    Unchanged,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LeaseReceipt {
    pub allocation_id: String,
    pub lease_generation: u64,
    pub expires_at_ms: u64,
    pub revoked: bool,
    pub outcome: LeaseOutcome,
    pub semantic_digest: String,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum GrantTerminalReason {
    Revoked,
    Expired,
    HostGenerationReplaced,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct GrantHistoryRecord {
    pub grant: AllocationGrant,
    pub terminal_reason: GrantTerminalReason,
    pub terminal_at_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct GrantUseWitnessV1 {
    pub allocation_id: String,
    pub principal_id: String,
    pub host_id: String,
    pub host_generation: u64,
    pub lease_generation: u64,
    pub authority_epoch: u64,
    pub verified_at_ms: u64,
    pub expires_at_ms: u64,
    pub semantic_digest: String,
    pub resource_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LeaseLedgerSnapshot {
    pub hosts: BTreeMap<String, HostObservation>,
    pub active_grants: BTreeMap<String, AllocationGrant>,
    pub history: VecDeque<GrantHistoryRecord>,
    pub compacted_history_records: u64,
    pub compacted_history_sha256: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LeaseLedgerMetrics {
    pub active_grants: usize,
    pub expired_uncollected_grants: usize,
    pub revoked_uncompacted_grants: usize,
    pub history_records: usize,
    pub compacted_history_records: u64,
    pub reserved_by_host: BTreeMap<String, ResourceVectorV1>,
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
    Clock(FleetClockError),
    Resource(ResourceVectorError),
    CorruptSnapshot,
    ArithmeticOverflow,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

impl From<FleetClockError> for Error {
    fn from(value: FleetClockError) -> Self {
        Self::Clock(value)
    }
}

impl From<ResourceVectorError> for Error {
    fn from(value: ResourceVectorError) -> Self {
        Self::Resource(value)
    }
}

pub struct LeaseLedger {
    clock: Arc<dyn FleetClock>,
    hosts: BTreeMap<String, HostObservation>,
    active_grants: BTreeMap<String, AllocationGrant>,
    expiry_index: BTreeMap<u64, BTreeSet<String>>,
    committed_by_host: BTreeMap<String, ResourceVectorV1>,
    history: VecDeque<GrantHistoryRecord>,
    compacted_history_records: u64,
    compacted_history_sha256: String,
}

impl fmt::Debug for LeaseLedger {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("LeaseLedger")
            .field("hosts", &self.hosts.len())
            .field("active_grants", &self.active_grants.len())
            .field("history", &self.history.len())
            .field("compacted_history_records", &self.compacted_history_records)
            .finish()
    }
}

impl Default for LeaseLedger {
    fn default() -> Self {
        Self::new()
    }
}

impl LeaseLedger {
    pub fn new() -> Self {
        Self::with_clock(Arc::new(SystemFleetClock))
    }

    pub fn with_clock(clock: Arc<dyn FleetClock>) -> Self {
        Self {
            clock,
            hosts: BTreeMap::new(),
            active_grants: BTreeMap::new(),
            expiry_index: BTreeMap::new(),
            committed_by_host: BTreeMap::new(),
            history: VecDeque::new(),
            compacted_history_records: 0,
            compacted_history_sha256: empty_history_digest(),
        }
    }

    pub fn from_snapshot(
        clock: Arc<dyn FleetClock>,
        snapshot: LeaseLedgerSnapshot,
    ) -> Result<Self, Error> {
        validate_digest(&snapshot.compacted_history_sha256)?;
        if snapshot.hosts.len() > MAX_HOSTS
            || snapshot.active_grants.len() > MAX_ACTIVE_GRANTS
            || snapshot.history.len() > MAX_GRANT_HISTORY
        {
            return Err(Error::CorruptSnapshot);
        }
        let mut ledger = Self {
            clock,
            hosts: snapshot.hosts,
            active_grants: snapshot.active_grants,
            expiry_index: BTreeMap::new(),
            committed_by_host: BTreeMap::new(),
            history: snapshot.history,
            compacted_history_records: snapshot.compacted_history_records,
            compacted_history_sha256: snapshot.compacted_history_sha256,
        };
        for host in ledger.hosts.values() {
            validate_host(host)?;
        }
        validate_history(&ledger.history, &ledger.active_grants)?;
        let grants = ledger.active_grants.values().cloned().collect::<Vec<_>>();
        for grant in grants {
            validate_grant(&grant)?;
            let host = ledger
                .hosts
                .get(&grant.host_id)
                .cloned()
                .ok_or(Error::CorruptSnapshot)?;
            if grant.revoked
                || grant.host_generation != host.generation
                || grant.failure_domain_id != host.failure_domain_id
            {
                return Err(Error::CorruptSnapshot);
            }
            let committed = ledger
                .committed_by_host
                .get(&grant.host_id)
                .copied()
                .unwrap_or_default()
                .checked_add(grant.resources)?;
            if !committed.fits(host.capacity) {
                return Err(Error::CorruptSnapshot);
            }
            ledger.insert_expiry(&grant);
            ledger
                .committed_by_host
                .insert(grant.host_id.clone(), committed);
        }
        Ok(ledger)
    }

    pub fn snapshot(&self) -> LeaseLedgerSnapshot {
        LeaseLedgerSnapshot {
            hosts: self.hosts.clone(),
            active_grants: self.active_grants.clone(),
            history: self.history.clone(),
            compacted_history_records: self.compacted_history_records,
            compacted_history_sha256: self.compacted_history_sha256.clone(),
        }
    }

    pub fn admit_host(&mut self, observation: HostObservation) -> Result<(), Error> {
        let now_ms = self.clock.now_unix_ms()?;
        validate_host(&observation)?;
        if observation.observed_at_ms > now_ms || observation.valid_until_ms <= now_ms {
            return Err(Error::InvalidTime);
        }
        if let Some(current) = self.hosts.get(&observation.host_id).cloned() {
            if observation.generation < current.generation {
                return Err(Error::InvalidGeneration);
            }
            if observation.generation == current.generation && observation != current {
                return Err(Error::Conflict);
            }
            if observation == current {
                return Ok(());
            }
            self.retire_host_generation(&observation.host_id, now_ms)?;
        } else if self.hosts.len() >= MAX_HOSTS {
            return Err(Error::CapacityExceeded);
        }
        self.hosts.insert(observation.host_id.clone(), observation);
        Ok(())
    }

    pub fn issue(&mut self, mut grant: AllocationGrant) -> Result<LeaseReceipt, Error> {
        let now_ms = self.clock.now_unix_ms()?;
        self.collect_expired_at(now_ms)?;
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
        if let Some(current) = self.active_grants.get(&grant.allocation_id) {
            if equivalent(current, &grant) {
                return Ok(receipt(current, LeaseOutcome::Unchanged));
            }
            return Err(Error::Conflict);
        }
        if self
            .history
            .iter()
            .any(|record| record.grant.allocation_id == grant.allocation_id)
        {
            return Err(Error::Conflict);
        }
        if self.active_grants.len() >= MAX_ACTIVE_GRANTS {
            return Err(Error::GrantCapacityExceeded);
        }
        let committed = self
            .committed_by_host
            .get(&grant.host_id)
            .copied()
            .unwrap_or_default()
            .checked_add(grant.resources)?;
        if !committed.fits(host.capacity) {
            return Err(Error::CapacityExceeded);
        }
        grant.revoked = false;
        let result = receipt(&grant, LeaseOutcome::Issued);
        self.insert_expiry(&grant);
        self.committed_by_host
            .insert(grant.host_id.clone(), committed);
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
        let now_ms = self.clock.now_unix_ms()?;
        self.collect_expired_at(now_ms)?;
        validate_identity(allocation_id, "allocation")?;
        validate_digest(semantic_digest)?;
        let current = self
            .active_grants
            .get(allocation_id)
            .cloned()
            .ok_or_else(|| self.terminal_lookup_error(allocation_id))?;
        if current.lease_generation != expected_lease_generation {
            return Err(Error::StaleLease);
        }
        if current.authority_epoch != authority_epoch || current.semantic_digest != semantic_digest
        {
            return Err(Error::Conflict);
        }
        match disposition {
            LeaseDisposition::Revoke => self.revoke(current, now_ms),
            LeaseDisposition::Renew { expires_at_ms } => {
                self.renew(current, expires_at_ms, now_ms)
            }
        }
    }

    pub fn collect_expired(&mut self) -> Result<usize, Error> {
        let now_ms = self.clock.now_unix_ms()?;
        self.collect_expired_at(now_ms)
    }

    pub fn verify_use(
        &self,
        allocation_id: &str,
        expected_lease_generation: u64,
        expected_host_id: &str,
        expected_host_generation: u64,
        semantic_digest: &str,
    ) -> Result<GrantUseWitnessV1, Error> {
        let now_ms = self.clock.now_unix_ms()?;
        let grant = self
            .active_grants
            .get(allocation_id)
            .ok_or_else(|| self.terminal_lookup_error(allocation_id))?;
        if grant.lease_generation != expected_lease_generation {
            return Err(Error::StaleLease);
        }
        if grant.host_id != expected_host_id
            || grant.host_generation != expected_host_generation
            || grant.semantic_digest != semantic_digest
        {
            return Err(Error::Conflict);
        }
        let host = self.hosts.get(&grant.host_id).ok_or(Error::HostNotFound)?;
        if now_ms >= grant.expires_at_ms
            || now_ms >= host.valid_until_ms
            || host.generation != grant.host_generation
        {
            return Err(Error::StaleLease);
        }
        Ok(GrantUseWitnessV1 {
            allocation_id: grant.allocation_id.clone(),
            principal_id: grant.principal_id.clone(),
            host_id: grant.host_id.clone(),
            host_generation: grant.host_generation,
            lease_generation: grant.lease_generation,
            authority_epoch: grant.authority_epoch,
            verified_at_ms: now_ms,
            expires_at_ms: grant.expires_at_ms,
            semantic_digest: grant.semantic_digest.clone(),
            resource_digest: grant.resources.semantic_digest()?,
        })
    }

    pub fn compact_history(&mut self, retain: usize) -> Result<usize, Error> {
        let retain = retain.min(MAX_GRANT_HISTORY);
        let mut compacted = 0;
        while self.history.len() > retain {
            let record = self.history.pop_front().ok_or(Error::CorruptSnapshot)?;
            let encoded = serde_json::to_vec(&record).map_err(|_| Error::CorruptSnapshot)?;
            let mut digest = Sha256::new();
            digest.update(b"hepta.runtime.fleet.grant-history.v1\0");
            digest.update(self.compacted_history_sha256.as_bytes());
            digest.update(encoded);
            self.compacted_history_sha256 = format!("{:x}", digest.finalize());
            self.compacted_history_records = self
                .compacted_history_records
                .checked_add(1)
                .ok_or(Error::ArithmeticOverflow)?;
            compacted += 1;
        }
        Ok(compacted)
    }

    pub fn get(&self, allocation_id: &str) -> Option<&AllocationGrant> {
        self.active_grants.get(allocation_id)
    }

    pub fn metrics(&self) -> Result<LeaseLedgerMetrics, Error> {
        let now_ms = self.clock.now_unix_ms()?;
        Ok(LeaseLedgerMetrics {
            active_grants: self.active_grants.len(),
            expired_uncollected_grants: self
                .active_grants
                .values()
                .filter(|grant| grant.expires_at_ms <= now_ms)
                .count(),
            revoked_uncompacted_grants: self
                .history
                .iter()
                .filter(|record| record.terminal_reason == GrantTerminalReason::Revoked)
                .count(),
            history_records: self.history.len(),
            compacted_history_records: self.compacted_history_records,
            reserved_by_host: self.committed_by_host.clone(),
        })
    }

    fn renew(
        &mut self,
        current: AllocationGrant,
        expires_at_ms: u64,
        now_ms: u64,
    ) -> Result<LeaseReceipt, Error> {
        let host = self
            .hosts
            .get(&current.host_id)
            .cloned()
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
        self.remove_expiry(&current);
        let grant = self
            .active_grants
            .get_mut(&current.allocation_id)
            .ok_or(Error::AllocationNotFound)?;
        grant.expires_at_ms = expires_at_ms;
        grant.lease_generation = grant
            .lease_generation
            .checked_add(1)
            .ok_or(Error::ArithmeticOverflow)?;
        let updated = grant.clone();
        let result = receipt(&updated, LeaseOutcome::Renewed);
        self.insert_expiry(&updated);
        Ok(result)
    }

    fn revoke(
        &mut self,
        current: AllocationGrant,
        now_ms: u64,
    ) -> Result<LeaseReceipt, Error> {
        let mut grant = self
            .active_grants
            .remove(&current.allocation_id)
            .ok_or(Error::AllocationNotFound)?;
        self.remove_expiry(&grant);
        self.release_resources(&grant)?;
        grant.revoked = true;
        grant.lease_generation = grant
            .lease_generation
            .checked_add(1)
            .ok_or(Error::ArithmeticOverflow)?;
        let result = receipt(&grant, LeaseOutcome::Revoked);
        self.archive(grant, GrantTerminalReason::Revoked, now_ms)?;
        Ok(result)
    }

    fn collect_expired_at(&mut self, now_ms: u64) -> Result<usize, Error> {
        let deadlines = self
            .expiry_index
            .range(..=now_ms)
            .map(|(deadline, _)| *deadline)
            .collect::<Vec<_>>();
        let mut expired = 0;
        for deadline in deadlines {
            let allocation_ids = self.expiry_index.remove(&deadline).unwrap_or_default();
            for allocation_id in allocation_ids {
                let grant = self
                    .active_grants
                    .remove(&allocation_id)
                    .ok_or(Error::CorruptSnapshot)?;
                self.release_resources(&grant)?;
                self.archive(grant, GrantTerminalReason::Expired, now_ms)?;
                expired += 1;
            }
        }
        Ok(expired)
    }

    fn retire_host_generation(&mut self, host_id: &str, now_ms: u64) -> Result<(), Error> {
        let allocation_ids = self
            .active_grants
            .values()
            .filter(|grant| grant.host_id == host_id)
            .map(|grant| grant.allocation_id.clone())
            .collect::<Vec<_>>();
        for allocation_id in allocation_ids {
            let grant = self
                .active_grants
                .remove(&allocation_id)
                .ok_or(Error::CorruptSnapshot)?;
            self.remove_expiry(&grant);
            self.release_resources(&grant)?;
            self.archive(
                grant,
                GrantTerminalReason::HostGenerationReplaced,
                now_ms,
            )?;
        }
        Ok(())
    }

    fn archive(
        &mut self,
        grant: AllocationGrant,
        terminal_reason: GrantTerminalReason,
        terminal_at_ms: u64,
    ) -> Result<(), Error> {
        self.history.push_back(GrantHistoryRecord {
            grant,
            terminal_reason,
            terminal_at_ms,
        });
        self.compact_history(MAX_GRANT_HISTORY)?;
        Ok(())
    }

    fn insert_expiry(&mut self, grant: &AllocationGrant) {
        self.expiry_index
            .entry(grant.expires_at_ms)
            .or_default()
            .insert(grant.allocation_id.clone());
    }

    fn remove_expiry(&mut self, grant: &AllocationGrant) {
        let remove_deadline = self
            .expiry_index
            .get_mut(&grant.expires_at_ms)
            .is_some_and(|entries| {
                entries.remove(&grant.allocation_id);
                entries.is_empty()
            });
        if remove_deadline {
            self.expiry_index.remove(&grant.expires_at_ms);
        }
    }

    fn release_resources(&mut self, grant: &AllocationGrant) -> Result<(), Error> {
        let committed = self
            .committed_by_host
            .get(&grant.host_id)
            .copied()
            .ok_or(Error::CorruptSnapshot)?
            .checked_sub(grant.resources)?;
        if committed.is_empty() {
            self.committed_by_host.remove(&grant.host_id);
        } else {
            self.committed_by_host
                .insert(grant.host_id.clone(), committed);
        }
        Ok(())
    }

    fn terminal_lookup_error(&self, allocation_id: &str) -> Error {
        self.history
            .iter()
            .rev()
            .find(|record| record.grant.allocation_id == allocation_id)
            .map_or(Error::AllocationNotFound, |record| match record.terminal_reason {
                GrantTerminalReason::Revoked => Error::Revoked,
                GrantTerminalReason::Expired | GrantTerminalReason::HostGenerationReplaced => {
                    Error::StaleLease
                }
            })
    }
}

fn validate_history(
    history: &VecDeque<GrantHistoryRecord>,
    active: &BTreeMap<String, AllocationGrant>,
) -> Result<(), Error> {
    let mut identities = BTreeSet::new();
    for record in history {
        validate_grant(&record.grant)?;
        if record.terminal_at_ms == 0
            || active.contains_key(&record.grant.allocation_id)
            || !identities.insert(record.grant.allocation_id.as_str())
            || (record.terminal_reason == GrantTerminalReason::Revoked && !record.grant.revoked)
            || (record.terminal_reason != GrantTerminalReason::Revoked && record.grant.revoked)
        {
            return Err(Error::CorruptSnapshot);
        }
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

fn validate_host(observation: &HostObservation) -> Result<(), Error> {
    validate_identity(&observation.host_id, "host")?;
    validate_identity(&observation.failure_domain_id, "failure domain")?;
    observation.capacity.validate()?;
    if observation.generation == 0
        || observation.observed_at_ms >= observation.valid_until_ms
        || observation.capacity.is_empty()
    {
        return Err(Error::HostCapacity);
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
    grant.resources.validate()?;
    if grant.host_generation == 0 || grant.authority_epoch == 0 || grant.lease_generation == 0 {
        return Err(Error::InvalidGeneration);
    }
    if grant.resources.is_empty() {
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

fn empty_history_digest() -> String {
    format!("{:x}", Sha256::digest(b"hepta.runtime.fleet.empty-history.v1"))
}

#[cfg(test)]
#[path = "lease_ledger_tests.rs"]
mod tests;
