//! Aggregate-only owner diagnostics and bounded recovery pagination. These are
//! projections, never authority or a reason to delete deduplication identities.
use super::*;
use std::ops::Bound::{Excluded, Unbounded};

#[derive(Default)]
pub(super) struct OwnerCounters {
    pub commit_attempts: u64,
    pub commits_confirmed: u64,
    pub encoded_bytes_submitted: u64,
    pub commit_nanoseconds: u64,
    pub writer_fencing_events: u64,
    pub lock_wait_nanoseconds: u64,
    pub lock_hold_nanoseconds: u64,
}

#[derive(Clone, Debug, Serialize, Eq, PartialEq)]
pub struct BaoOwnerDiagnostics {
    pub schema_version: u32,
    pub revision: u64,
    pub owner_available: bool,
    pub consumption_count: usize,
    pub terminal_count: usize,
    pub waiting_admission: usize,
    pub waiting_reservation: usize,
    pub waiting_observation: usize,
    pub waiting_settlement: usize,
    pub waiting_legacy_requalification: usize,
    pub post_dispatch_without_receipt: usize,
    pub unsettled_reserved_amount: u64,
    pub oldest_pending_age_ms: Option<u64>,
    pub pending_age_unknown: usize,
    pub future_dated_pending: usize,
    pub encoded_store_bytes: usize,
    pub consumption_result_reserve_bytes: usize,
    pub store_limit_bytes: usize,
    pub commit_attempts: u64,
    pub commits_confirmed: u64,
    /// Bytes submitted to the snapshot writer, NOT device write amplification.
    pub encoded_bytes_submitted: u64,
    pub commit_nanoseconds: u64,
    pub writer_fencing_events: u64,
    pub lock_wait_nanoseconds: u64,
    pub lock_hold_nanoseconds: u64,
}

/// Sensitive owner-only cursor/identities. Debug deliberately hides all IDs.
pub struct BaoRecoveryPage {
    pub operation_ids: Vec<String>,
    pub next_after: Option<String>,
    pub scanned: usize,
}
impl std::fmt::Debug for BaoRecoveryPage {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("BaoRecoveryPage").field("count", &self.operation_ids.len())
            .field("scanned", &self.scanned).field("has_more", &self.next_after.is_some()).finish()
    }
}

impl DurableLeaseRegistryV1 {
    /// Host-supplied diagnostic time cannot mutate the authority time frontier.
    /// Unknown legacy ages and future observations are counted, not fabricated.
    pub fn diagnostics(&self, now_unix_ms: u64) -> Result<BaoOwnerDiagnostics, LeaseRegistryErrorV1> {
        let mut result = BaoOwnerDiagnostics {
            schema_version: self.state.schema_version, revision: self.state.revision,
            owner_available: self.ensure_writable().is_ok(), consumption_count: self.state.consumptions.len(),
            terminal_count: 0, waiting_admission: 0, waiting_reservation: 0, waiting_observation: 0,
            waiting_settlement: 0, waiting_legacy_requalification: 0, post_dispatch_without_receipt: 0,
            unsettled_reserved_amount: 0, oldest_pending_age_ms: None, pending_age_unknown: 0,
            future_dated_pending: 0, encoded_store_bytes: serde_json::to_vec(&self.state)
                .map_err(|_| LeaseRegistryErrorV1::Unavailable)?.len(),
            consumption_result_reserve_bytes: 0, store_limit_bytes: MAX_STORE_BYTES,
            commit_attempts: self.counters.commit_attempts, commits_confirmed: self.counters.commits_confirmed,
            encoded_bytes_submitted: self.counters.encoded_bytes_submitted,
            commit_nanoseconds: self.counters.commit_nanoseconds, writer_fencing_events: self.counters.writer_fencing_events,
            lock_wait_nanoseconds: self.counters.lock_wait_nanoseconds, lock_hold_nanoseconds: self.counters.lock_hold_nanoseconds,
        };
        for row in self.state.consumptions.values() {
            match row.state.phase() {
                BaoConsumptionPhase::Unreserved => result.waiting_admission += 1,
                BaoConsumptionPhase::Reserved => result.waiting_reservation += 1,
                BaoConsumptionPhase::Fenced => {
                    result.waiting_observation += 1;
                    if row.receipt.is_none() && row.state != BaoConsumptionStateV1::DispatchAttempted {
                        result.post_dispatch_without_receipt += 1;
                    }
                }
                BaoConsumptionPhase::AwaitingSettlement => result.waiting_settlement += 1,
                BaoConsumptionPhase::LegacyRequalification => result.waiting_legacy_requalification += 1,
                BaoConsumptionPhase::Terminal => { result.terminal_count += 1; continue; }
            }
            result.consumption_result_reserve_bytes += 4096;
            if row.reservation_id.is_some() {
                result.unsettled_reserved_amount = result.unsettled_reserved_amount.saturating_add(row.amount);
            }
            match row.created_at_unix_ms {
                Some(created) if created <= now_unix_ms => {
                    let age = now_unix_ms - created;
                    result.oldest_pending_age_ms = Some(result.oldest_pending_age_ms.unwrap_or(0).max(age));
                }
                Some(_) => result.future_dated_pending += 1,
                None => result.pending_age_unknown += 1,
            }
        }
        Ok(result)
    }

    /// Examine at most `scan_limit` records (including terminal rows). Advancing
    /// the returned cursor prevents one permanently pending operation from
    /// starving later identities. End of a sweep returns no cursor.
    pub fn pending_consumptions(&self, after: Option<&str>, scan_limit: usize) -> Result<BaoRecoveryPage, LeaseRegistryErrorV1> {
        self.ensure_writable()?;
        if !(1..=256).contains(&scan_limit) || after.is_some_and(|id| !identifier(id)) {
            return Err(LeaseRegistryErrorV1::InvalidInput);
        }
        let lower = after.map_or(Unbounded, Excluded);
        let mut iter = self.state.consumptions.range::<str, _>((lower, Unbounded));
        let mut page = BaoRecoveryPage { operation_ids: Vec::new(), next_after: None, scanned: 0 };
        let mut last = None;
        for (id, row) in iter.by_ref().take(scan_limit) {
            page.scanned += 1;
            last = Some(id.clone());
            if !row.state.is_terminal() { page.operation_ids.push(id.clone()); }
        }
        if iter.next().is_some() { page.next_after = last; }
        Ok(page)
    }
}


pub(crate) struct OwnerGuard<'a> {
    owner: std::sync::MutexGuard<'a, DurableLeaseRegistryV1>,
    acquired: std::time::Instant,
}
impl std::ops::Deref for OwnerGuard<'_> {
    type Target = DurableLeaseRegistryV1;
    fn deref(&self) -> &Self::Target { &self.owner }
}
impl std::ops::DerefMut for OwnerGuard<'_> {
    fn deref_mut(&mut self) -> &mut Self::Target { &mut self.owner }
}
impl Drop for OwnerGuard<'_> {
    fn drop(&mut self) {
        self.owner.counters.lock_hold_nanoseconds = self.owner.counters.lock_hold_nanoseconds
            .saturating_add(self.acquired.elapsed().as_nanos().min(u128::from(u64::MAX)) as u64);
    }
}
pub(crate) fn lock_owner(registry: &std::sync::Mutex<DurableLeaseRegistryV1>) -> Result<OwnerGuard<'_>, LeaseRegistryErrorV1> {
    let started = std::time::Instant::now();
    let mut owner = registry.lock().map_err(|_| LeaseRegistryErrorV1::Fenced)?;
    owner.counters.lock_wait_nanoseconds = owner.counters.lock_wait_nanoseconds
        .saturating_add(started.elapsed().as_nanos().min(u128::from(u64::MAX)) as u64);
    Ok(OwnerGuard { owner, acquired: std::time::Instant::now() })
}
