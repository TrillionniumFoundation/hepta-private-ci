//! B4 local scheduler qualification seam.
//!
//! This module is compiled only for tests or the explicit
//! `authbus-local-qualification` feature (`lib.rs` gates it accordingly).  It
//! is deliberately not an AuthBus daemon, a provider adapter, or a product
//! scheduler.  The seam exists to exercise the B4
//! invariants against a deterministic in-memory model before a separate
//! `hepta-authbus-scheduler` crate is introduced:
//!
//! * every quota dimension is held atomically and unknown quota denies;
//! * a permit is bound to the resource's authority/owner/generation/fence;
//! * stale callbacks cannot mutate held/used counters;
//! * duplicate request/idempotency keys cannot mint another active permit;
//! * selection is weighted-fair across subjects and EDF within a subject;
//! * no method crosses a provider, socket, filesystem, or production flag
//!   boundary.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::collections::VecDeque;

use crate::Sha256Digest;
use crate::SubjectRef;

/// This qualification model never grants authority or executes an effect.
pub const AUTHBUS_B4_QUALIFICATION_ONLY: bool = true;
pub const AUTHBUS_B4_AUTHORITY: bool = false;
pub const AUTHBUS_B4_PRODUCTION_CALLER: bool = false;
pub const AUTHBUS_B4_PRODUCTION_WRITER: bool = false;
pub const AUTHBUS_B4_EFFECT_AUTHORITY: bool = false;
pub const AUTHBUS_B4_OPERATOR_ACCEPTANCE: bool = false;
pub const AUTHBUS_B4_PROMOTION: bool = false;
pub const AUTHBUS_B4_G5_ALLOWED: bool = false;
pub const AUTHBUS_B4_EXECUTE_ALLOWED: bool = false;

const _: () = {
    assert!(AUTHBUS_B4_QUALIFICATION_ONLY);
    assert!(!AUTHBUS_B4_AUTHORITY);
    assert!(!AUTHBUS_B4_PRODUCTION_CALLER);
    assert!(!AUTHBUS_B4_PRODUCTION_WRITER);
    assert!(!AUTHBUS_B4_EFFECT_AUTHORITY);
    assert!(!AUTHBUS_B4_OPERATOR_ACCEPTANCE);
    assert!(!AUTHBUS_B4_PROMOTION);
    assert!(!AUTHBUS_B4_G5_ALLOWED);
    assert!(!AUTHBUS_B4_EXECUTE_ALLOWED);
};

const FAIRNESS_SCALE: u64 = 1_000_000;

/// A non-negative integer quota vector.  `context` is included even though
/// the earlier B2 wire type only carried request/token/concurrency/day budget;
/// B4 uses the five-dimensional AUTHBUS.11 vector.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct QuotaVector {
    pub rpm: u64,
    pub tpm: u64,
    pub concurrency: u64,
    pub day_budget: u64,
    pub context: u64,
}

impl QuotaVector {
    pub const fn new(rpm: u64, tpm: u64, concurrency: u64, day_budget: u64, context: u64) -> Self {
        Self {
            rpm,
            tpm,
            concurrency,
            day_budget,
            context,
        }
    }

    fn is_zero(self) -> bool {
        self.rpm == 0
            && self.tpm == 0
            && self.concurrency == 0
            && self.day_budget == 0
            && self.context == 0
    }

    fn checked_add(self, other: Self) -> Option<Self> {
        Some(Self {
            rpm: self.rpm.checked_add(other.rpm)?,
            tpm: self.tpm.checked_add(other.tpm)?,
            concurrency: self.concurrency.checked_add(other.concurrency)?,
            day_budget: self.day_budget.checked_add(other.day_budget)?,
            context: self.context.checked_add(other.context)?,
        })
    }

    fn checked_sub(self, other: Self) -> Option<Self> {
        Some(Self {
            rpm: self.rpm.checked_sub(other.rpm)?,
            tpm: self.tpm.checked_sub(other.tpm)?,
            concurrency: self.concurrency.checked_sub(other.concurrency)?,
            day_budget: self.day_budget.checked_sub(other.day_budget)?,
            context: self.context.checked_sub(other.context)?,
        })
    }
}

/// `None` means the provider/domain did not expose a bounded value.  The
/// scheduler treats any unknown dimension as no-admission rather than as
/// unlimited capacity.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct QuotaLimits {
    pub rpm: Option<u64>,
    pub tpm: Option<u64>,
    pub concurrency: Option<u64>,
    pub day_budget: Option<u64>,
    pub context: Option<u64>,
}

impl QuotaLimits {
    pub const fn known(vector: QuotaVector) -> Self {
        Self {
            rpm: Some(vector.rpm),
            tpm: Some(vector.tpm),
            concurrency: Some(vector.concurrency),
            day_budget: Some(vector.day_budget),
            context: Some(vector.context),
        }
    }

    pub const fn unknown_rpm(vector: QuotaVector) -> Self {
        Self {
            rpm: None,
            tpm: Some(vector.tpm),
            concurrency: Some(vector.concurrency),
            day_budget: Some(vector.day_budget),
            context: Some(vector.context),
        }
    }

    fn can_ever_hold(self, estimate: QuotaVector, margin: QuotaVector) -> bool {
        let Some(total) = estimate.checked_add(margin) else {
            return false;
        };
        self.rpm.is_some_and(|limit| total.rpm <= limit)
            && self.tpm.is_some_and(|limit| total.tpm <= limit)
            && self
                .concurrency
                .is_some_and(|limit| total.concurrency <= limit)
            && self
                .day_budget
                .is_some_and(|limit| total.day_budget <= limit)
            && self.context.is_some_and(|limit| total.context <= limit)
    }

    fn can_hold(
        self,
        used: QuotaVector,
        held: QuotaVector,
        estimate: QuotaVector,
        margin: QuotaVector,
    ) -> bool {
        let Some(total) = estimate.checked_add(margin) else {
            return false;
        };
        fn dimension(limit: Option<u64>, used: u64, held: u64, needed: u64) -> bool {
            let Some(limit) = limit else {
                return false;
            };
            let Some(committed) = used.checked_add(held) else {
                return false;
            };
            let Some(available) = limit.checked_sub(committed) else {
                return false;
            };
            needed <= available
        }
        dimension(self.rpm, used.rpm, held.rpm, total.rpm)
            && dimension(self.tpm, used.tpm, held.tpm, total.tpm)
            && dimension(
                self.concurrency,
                used.concurrency,
                held.concurrency,
                total.concurrency,
            )
            && dimension(
                self.day_budget,
                used.day_budget,
                held.day_budget,
                total.day_budget,
            )
            && dimension(self.context, used.context, held.context, total.context)
    }
}

/// Resource lifecycle visible to the local scheduler.  Unknown and draining
/// states are intentionally non-admitting.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ResourceState {
    Available,
    Draining,
    Unavailable,
    Unknown,
}

/// Secret-free, host-owned scheduler resource head.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SchedulerResource {
    pub resource_id: String,
    pub resource_sha256: Sha256Digest,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub generation: u64,
    pub fencing_token_sha256: Sha256Digest,
    pub quota: QuotaLimits,
    pub state: ResourceState,
    pub cooldown_until_ms: u64,
}

impl SchedulerResource {
    pub fn validate(&self) -> Result<(), SchedulerError> {
        if self.resource_id.trim().is_empty()
            || self.resource_id.len() > 512
            || self.resource_id.as_bytes().contains(&0)
        {
            return Err(SchedulerError::InvalidRequest);
        }
        if self.authority_epoch == 0 || self.owner_epoch == 0 || self.generation == 0 {
            return Err(SchedulerError::StaleFence);
        }
        for digest in [&self.resource_sha256, &self.fencing_token_sha256] {
            Sha256Digest::parse(digest.as_str().to_string())
                .map_err(|_| SchedulerError::InvalidRequest)?;
        }
        Ok(())
    }
}

/// Request admitted to the deterministic local queue.  The fields mirror the
/// AUTHBUS.11 mutation/fence crosswalk; payload and policy are digests only.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SchedulerRequest {
    pub request_id: String,
    pub command_id: String,
    pub run_id: String,
    pub aggregate_id: String,
    pub idempotency_key: String,
    pub subject: SubjectRef,
    pub resource_sha256: Sha256Digest,
    pub payload_sha256: Sha256Digest,
    pub policy_sha256: Sha256Digest,
    pub expected_revision: u64,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub generation: u64,
    pub fencing_token_sha256: Sha256Digest,
    pub estimate: QuotaVector,
    pub safety_margin: QuotaVector,
    pub enqueued_at_ms: u64,
    pub deadline_ms: u64,
    pub weight: u32,
}

impl SchedulerRequest {
    fn validate(&self, resource: &SchedulerResource, revision: u64) -> Result<(), SchedulerError> {
        for value in [
            self.request_id.as_str(),
            self.command_id.as_str(),
            self.run_id.as_str(),
            self.aggregate_id.as_str(),
            self.idempotency_key.as_str(),
        ] {
            if value.trim().is_empty() || value.len() > 512 || value.as_bytes().contains(&0) {
                return Err(SchedulerError::InvalidRequest);
            }
        }
        self.subject
            .validate()
            .map_err(|_| SchedulerError::InvalidRequest)?;
        for digest in [
            &self.resource_sha256,
            &self.payload_sha256,
            &self.policy_sha256,
            &self.fencing_token_sha256,
        ] {
            Sha256Digest::parse(digest.as_str().to_string())
                .map_err(|_| SchedulerError::InvalidRequest)?;
        }
        if self.resource_sha256 != resource.resource_sha256
            || self.authority_epoch != resource.authority_epoch
            || self.owner_epoch != resource.owner_epoch
            || self.generation != resource.generation
            || self.fencing_token_sha256 != resource.fencing_token_sha256
        {
            return Err(SchedulerError::StaleFence);
        }
        if self.subject.generation != self.generation
            || self.expected_revision != revision
            || self.enqueued_at_ms == 0
            || self.deadline_ms <= self.enqueued_at_ms
            || self.weight == 0
            || self.estimate.is_zero()
        {
            return Err(SchedulerError::InvalidRequest);
        }
        if self.estimate.checked_add(self.safety_margin).is_none() {
            return Err(SchedulerError::QuotaExceeded);
        }
        Ok(())
    }

    fn subject_key(&self) -> String {
        format!(
            "{}\u{1f}{}\u{1f}{}\u{1f}{}\u{1f}{:020}",
            self.subject.tenant,
            self.subject.workspace,
            self.subject.agent,
            self.subject.service,
            self.subject.generation,
        )
    }
}

/// Permit returned by the local qualification scheduler.  It is an
/// observation of a held reservation, not an external credential.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SchedulerPermit {
    pub permit_id: String,
    pub request_id: String,
    pub command_id: String,
    pub idempotency_key: String,
    pub resource_id: String,
    pub resource_sha256: Sha256Digest,
    pub subject: SubjectRef,
    pub estimate: QuotaVector,
    pub safety_margin: QuotaVector,
    pub reserved: QuotaVector,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub generation: u64,
    pub fencing_token_sha256: Sha256Digest,
    pub issued_at_ms: u64,
    pub expires_at_ms: u64,
    pub authority: bool,
}

impl SchedulerPermit {
    fn identity_matches(&self, resource: &SchedulerResource) -> bool {
        self.authority_epoch == resource.authority_epoch
            && self.owner_epoch == resource.owner_epoch
            && self.generation == resource.generation
            && self.fencing_token_sha256 == resource.fencing_token_sha256
            && self.resource_sha256 == resource.resource_sha256
    }
}

/// Outcome/error for local qualification operations.  Rejections are
/// side-effect free unless explicitly documented by the caller as queue
/// expiry; no error represents a provider or production effect.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SchedulerError {
    InvalidRequest,
    DuplicateRequest,
    DuplicateIdempotency,
    UnknownQuota,
    QuotaExceeded,
    ResourceUnavailable,
    StaleFence,
    UnknownPermit,
    UsageOverrun,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct Pending {
    request: SchedulerRequest,
    sequence: u64,
    wait_quanta: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct Active {
    permit: SchedulerPermit,
    reserved: QuotaVector,
}

/// Deterministic in-memory B4 scheduler.  It is intentionally restricted to
/// the test/qualification build and has no async/runtime dependency.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalScheduler {
    resource: SchedulerResource,
    revision: u64,
    next_sequence: u64,
    next_permit_nonce: u64,
    queues: BTreeMap<String, VecDeque<Pending>>,
    subject_order: Vec<String>,
    cursor: usize,
    seen_requests: BTreeSet<String>,
    seen_idempotency: BTreeMap<String, Sha256Digest>,
    active: BTreeMap<String, Active>,
    used: QuotaVector,
    held: QuotaVector,
    grants_by_subject: BTreeMap<String, u64>,
    max_wait_quanta: u64,
    stale_rejections: u64,
    expired_rejections: u64,
}

impl LocalScheduler {
    pub fn new(resource: SchedulerResource) -> Result<Self, SchedulerError> {
        resource.validate()?;
        Ok(Self {
            resource,
            revision: 1,
            next_sequence: 1,
            next_permit_nonce: 1,
            queues: BTreeMap::new(),
            subject_order: Vec::new(),
            cursor: 0,
            seen_requests: BTreeSet::new(),
            seen_idempotency: BTreeMap::new(),
            active: BTreeMap::new(),
            used: QuotaVector::default(),
            held: QuotaVector::default(),
            grants_by_subject: BTreeMap::new(),
            max_wait_quanta: 0,
            stale_rejections: 0,
            expired_rejections: 0,
        })
    }

    /// Run one local state transition as a transaction.  The inner methods
    /// still preflight their arithmetic, while this snapshot guard also
    /// covers expiry/selection bookkeeping that may have happened before an
    /// unexpected error.  It is intentionally viable here because the seam
    /// is an in-memory test reference model, not a production persistence
    /// implementation.
    fn transactional<T>(
        &mut self,
        operation: impl FnOnce(&mut Self) -> Result<T, SchedulerError>,
    ) -> Result<T, SchedulerError> {
        let before = self.clone();
        let result = operation(self);
        if result.is_err() {
            *self = before;
        }
        result
    }

    pub fn resource(&self) -> &SchedulerResource {
        &self.resource
    }

    pub fn revision(&self) -> u64 {
        self.revision
    }

    pub fn used(&self) -> QuotaVector {
        self.used
    }

    pub fn held(&self) -> QuotaVector {
        self.held
    }

    pub fn active_permit_count(&self) -> usize {
        self.active.len()
    }

    pub fn queued_request_count(&self) -> usize {
        self.queues.values().map(VecDeque::len).sum()
    }

    pub fn max_wait_quanta(&self) -> u64 {
        self.max_wait_quanta
    }

    pub fn stale_rejections(&self) -> u64 {
        self.stale_rejections
    }

    pub fn expired_rejections(&self) -> u64 {
        self.expired_rejections
    }

    pub fn grants_by_subject(&self) -> &BTreeMap<String, u64> {
        &self.grants_by_subject
    }

    pub fn enqueue(&mut self, request: SchedulerRequest) -> Result<(), SchedulerError> {
        self.transactional(|scheduler| scheduler.enqueue_inner(request))
    }

    fn enqueue_inner(&mut self, request: SchedulerRequest) -> Result<(), SchedulerError> {
        request.validate(&self.resource, self.revision)?;
        if self.resource.state != ResourceState::Available {
            return Err(SchedulerError::ResourceUnavailable);
        }
        if self.resource.quota.rpm.is_none()
            || self.resource.quota.tpm.is_none()
            || self.resource.quota.concurrency.is_none()
            || self.resource.quota.day_budget.is_none()
            || self.resource.quota.context.is_none()
        {
            return Err(SchedulerError::UnknownQuota);
        }
        if !self
            .resource
            .quota
            .can_ever_hold(request.estimate, request.safety_margin)
        {
            return Err(SchedulerError::QuotaExceeded);
        }
        if self.seen_requests.contains(&request.request_id) {
            return Err(SchedulerError::DuplicateRequest);
        }
        let payload_digest = request.payload_sha256.clone();
        if self.seen_idempotency.contains_key(&request.idempotency_key) {
            return Err(SchedulerError::DuplicateIdempotency);
        }
        let subject_key = request.subject_key();
        let next_sequence = self
            .next_sequence
            .checked_add(1)
            .ok_or(SchedulerError::InvalidRequest)?;
        // Compute every fallible counter before mutating the seen-key sets or
        // queue.  An exhausted revision must reject atomically as well; a
        // caller can retry after rebinding rather than observing a half
        // enqueued request.
        let next_revision = self
            .revision
            .checked_add(1)
            .ok_or(SchedulerError::InvalidRequest)?;
        self.seen_requests.insert(request.request_id.clone());
        self.seen_idempotency
            .insert(request.idempotency_key.clone(), payload_digest);
        if !self.queues.contains_key(&subject_key) {
            self.subject_order.push(subject_key.clone());
            self.grants_by_subject
                .entry(subject_key.clone())
                .or_default();
        }
        let pending = Pending {
            request,
            sequence: self.next_sequence,
            wait_quanta: 0,
        };
        self.next_sequence = next_sequence;
        let queue = self.queues.entry(subject_key).or_default();
        let insertion = queue.iter().position(|current| {
            (
                pending.request.deadline_ms,
                pending.request.enqueued_at_ms,
                pending.sequence,
            ) < (
                current.request.deadline_ms,
                current.request.enqueued_at_ms,
                current.sequence,
            )
        });
        if let Some(index) = insertion {
            queue.insert(index, pending);
        } else {
            queue.push_back(pending);
        }
        self.revision = next_revision;
        Ok(())
    }

    /// Grant at most one request.  The first eligible subject selected by
    /// weighted service debt wins; each subject's head is EDF ordered.
    pub fn grant_next(&mut self, now_ms: u64) -> Result<Option<SchedulerPermit>, SchedulerError> {
        self.transactional(|scheduler| scheduler.grant_next_inner(now_ms))
    }

    fn grant_next_inner(&mut self, now_ms: u64) -> Result<Option<SchedulerPermit>, SchedulerError> {
        self.expire_pending(now_ms);
        if self.resource.state != ResourceState::Available {
            return Ok(None);
        }
        if now_ms < self.resource.cooldown_until_ms {
            return Ok(None);
        }
        let Some(index) = self.select_subject(now_ms) else {
            return Ok(None);
        };
        let subject_key = self.subject_order[index].clone();
        // Inspect the head without removing it.  All fallible arithmetic is
        // preflighted while the queue and accounting state are untouched;
        // this is the reservation transaction's prepare phase.
        let (estimate, safety_margin) = {
            let queue = self
                .queues
                .get(&subject_key)
                .ok_or(SchedulerError::InvalidRequest)?;
            let pending = queue.front().ok_or(SchedulerError::InvalidRequest)?;
            (pending.request.estimate, pending.request.safety_margin)
        };
        let Some(reserved) = estimate.checked_add(safety_margin) else {
            return Err(SchedulerError::QuotaExceeded);
        };
        if !self
            .resource
            .quota
            .can_hold(self.used, self.held, estimate, safety_margin)
        {
            return Ok(None);
        }
        let next_permit_nonce = self
            .next_permit_nonce
            .checked_add(1)
            .ok_or(SchedulerError::InvalidRequest)?;
        let next_held = self
            .held
            .checked_add(reserved)
            .ok_or(SchedulerError::QuotaExceeded)?;
        let current_grants = self
            .grants_by_subject
            .get(&subject_key)
            .copied()
            .unwrap_or_default();
        let next_grants = current_grants
            .checked_add(1)
            .ok_or(SchedulerError::InvalidRequest)?;
        let next_revision = self
            .revision
            .checked_add(1)
            .ok_or(SchedulerError::InvalidRequest)?;

        let queue = self
            .queues
            .get_mut(&subject_key)
            .ok_or(SchedulerError::InvalidRequest)?;
        let pending = queue.pop_front().ok_or(SchedulerError::InvalidRequest)?;
        if queue.is_empty() {
            self.queues.remove(&subject_key);
        }
        let request = pending.request;
        debug_assert_eq!(request.estimate, estimate);
        debug_assert_eq!(request.safety_margin, safety_margin);
        let permit_nonce = self.next_permit_nonce;
        let permit_id = format!(
            "permit:{}",
            Sha256Digest::for_bytes(
                format!(
                    "{}:{}:{permit_nonce}",
                    request.request_id, self.resource.resource_id
                )
                .as_bytes(),
            )
            .as_str()
        );
        let permit = SchedulerPermit {
            permit_id: permit_id.clone(),
            request_id: request.request_id,
            command_id: request.command_id,
            idempotency_key: request.idempotency_key,
            resource_id: self.resource.resource_id.clone(),
            resource_sha256: self.resource.resource_sha256.clone(),
            subject: request.subject,
            estimate: request.estimate,
            safety_margin: request.safety_margin,
            reserved,
            authority_epoch: self.resource.authority_epoch,
            owner_epoch: self.resource.owner_epoch,
            generation: self.resource.generation,
            fencing_token_sha256: self.resource.fencing_token_sha256.clone(),
            issued_at_ms: now_ms,
            expires_at_ms: request.deadline_ms,
            authority: AUTHBUS_B4_AUTHORITY,
        };
        self.next_permit_nonce = next_permit_nonce;
        self.held = next_held;
        self.active.insert(
            permit_id,
            Active {
                permit: permit.clone(),
                reserved,
            },
        );
        self.grants_by_subject.insert(subject_key, next_grants);
        self.bump_wait_quanta(index);
        self.revision = next_revision;
        Ok(Some(permit))
    }

    /// Complete a permit with an integer final quantity.  Unused estimated
    /// units (including safety margin) are released exactly once.
    pub fn complete(
        &mut self,
        permit: &SchedulerPermit,
        actual: QuotaVector,
    ) -> Result<(), SchedulerError> {
        self.transactional(|scheduler| scheduler.complete_inner(permit, actual))
    }

    fn complete_inner(
        &mut self,
        permit: &SchedulerPermit,
        actual: QuotaVector,
    ) -> Result<(), SchedulerError> {
        let active = self
            .active
            .get(&permit.permit_id)
            .ok_or(SchedulerError::UnknownPermit)?;
        if active.permit != *permit || !permit.identity_matches(&self.resource) {
            return Err(SchedulerError::StaleFence);
        }
        if actual.rpm > permit.reserved.rpm
            || actual.tpm > permit.reserved.tpm
            || actual.concurrency > permit.reserved.concurrency
            || actual.day_budget > permit.reserved.day_budget
            || actual.context > permit.reserved.context
        {
            return Err(SchedulerError::UsageOverrun);
        }
        let active_reserved = active.reserved;
        let released = active_reserved
            .checked_sub(actual)
            .ok_or(SchedulerError::UsageOverrun)?;
        // Prepare every fallible accounting update before changing `held`,
        // `used`, or removing the active permit.  This keeps an exhausted
        // usage/revision counter from producing a half-completed callback.
        let next_held = self
            .held
            .checked_sub(active_reserved)
            .ok_or(SchedulerError::InvalidRequest)?;
        // Concurrency is a simultaneous-operation hold, not cumulative
        // provider usage.  Keep it out of `used` so every completed call
        // returns that slot to availability.
        let mut accounted = actual;
        accounted.concurrency = 0;
        let next_used = self
            .used
            .checked_add(accounted)
            .ok_or(SchedulerError::QuotaExceeded)?;
        let next_revision = self
            .revision
            .checked_add(1)
            .ok_or(SchedulerError::InvalidRequest)?;
        // Keep this explicit to make conservation auditable; `released` is
        // the amount returned to availability and is not provider usage.
        let _ = released;
        self.held = next_held;
        self.used = next_used;
        self.active.remove(&permit.permit_id);
        self.revision = next_revision;
        Ok(())
    }

    pub fn release(&mut self, permit: &SchedulerPermit) -> Result<(), SchedulerError> {
        self.transactional(|scheduler| scheduler.release_inner(permit))
    }

    fn release_inner(&mut self, permit: &SchedulerPermit) -> Result<(), SchedulerError> {
        let active = self
            .active
            .get(&permit.permit_id)
            .ok_or(SchedulerError::UnknownPermit)?;
        if active.permit != *permit || !permit.identity_matches(&self.resource) {
            return Err(SchedulerError::StaleFence);
        }
        let active_reserved = active.reserved;
        let next_held = self
            .held
            .checked_sub(active_reserved)
            .ok_or(SchedulerError::InvalidRequest)?;
        let next_revision = self
            .revision
            .checked_add(1)
            .ok_or(SchedulerError::InvalidRequest)?;
        self.held = next_held;
        self.active.remove(&permit.permit_id);
        self.revision = next_revision;
        Ok(())
    }

    pub fn set_cooldown(&mut self, cooldown_until_ms: u64) {
        self.resource.cooldown_until_ms = cooldown_until_ms;
    }

    /// Rotate the owner fence.  Existing permits remain held until a verified
    /// owner-side reconcile; stale callbacks are rejected without changing
    /// counters.  Queued requests carrying the old fence are dropped by the
    /// next selection pass.
    pub fn rebind(
        &mut self,
        authority_epoch: u64,
        owner_epoch: u64,
        generation: u64,
        fencing_token_sha256: Sha256Digest,
    ) -> Result<(), SchedulerError> {
        if authority_epoch < self.resource.authority_epoch
            || owner_epoch <= self.resource.owner_epoch
            || generation <= self.resource.generation
        {
            return Err(SchedulerError::StaleFence);
        }
        Sha256Digest::parse(fencing_token_sha256.as_str().to_string())
            .map_err(|_| SchedulerError::InvalidRequest)?;
        if fencing_token_sha256 == self.resource.fencing_token_sha256 {
            return Err(SchedulerError::StaleFence);
        }
        let next_revision = self
            .revision
            .checked_add(1)
            .ok_or(SchedulerError::InvalidRequest)?;
        self.resource.authority_epoch = authority_epoch;
        self.resource.owner_epoch = owner_epoch;
        self.resource.generation = generation;
        self.resource.fencing_token_sha256 = fencing_token_sha256;
        self.revision = next_revision;
        Ok(())
    }

    fn expire_pending(&mut self, now_ms: u64) {
        for queue in self.queues.values_mut() {
            let mut retained = VecDeque::with_capacity(queue.len());
            while let Some(pending) = queue.pop_front() {
                if pending.request.deadline_ms <= now_ms {
                    self.expired_rejections = self.expired_rejections.saturating_add(1);
                } else if pending.request.owner_epoch != self.resource.owner_epoch
                    || pending.request.generation != self.resource.generation
                    || pending.request.authority_epoch != self.resource.authority_epoch
                    || pending.request.fencing_token_sha256 != self.resource.fencing_token_sha256
                {
                    self.stale_rejections = self.stale_rejections.saturating_add(1);
                } else {
                    retained.push_back(pending);
                }
            }
            *queue = retained;
        }
        self.queues.retain(|_, queue| !queue.is_empty());
    }

    fn select_subject(&mut self, now_ms: u64) -> Option<usize> {
        let mut selected: Option<usize> = None;
        for offset in 0..self.subject_order.len() {
            let index = (self.cursor + offset) % self.subject_order.len();
            let key = &self.subject_order[index];
            let Some(queue) = self.queues.get(key) else {
                continue;
            };
            let Some(head) = queue.front() else {
                continue;
            };
            if head.request.deadline_ms <= now_ms
                || head.request.owner_epoch != self.resource.owner_epoch
                || head.request.generation != self.resource.generation
                || head.request.authority_epoch != self.resource.authority_epoch
                || head.request.fencing_token_sha256 != self.resource.fencing_token_sha256
            {
                continue;
            }
            if !self.resource.quota.can_hold(
                self.used,
                self.held,
                head.request.estimate,
                head.request.safety_margin,
            ) {
                continue;
            }
            selected = match selected {
                None => Some(index),
                Some(previous) => {
                    let previous_key = &self.subject_order[previous];
                    let previous_head = self.queues.get(previous_key)?.front()?;
                    let lhs =
                        u128::from(self.grants_by_subject.get(key).copied().unwrap_or_default())
                            * u128::from(previous_head.request.weight);
                    let rhs = u128::from(
                        self.grants_by_subject
                            .get(previous_key)
                            .copied()
                            .unwrap_or_default(),
                    ) * u128::from(head.request.weight);
                    if lhs < rhs
                        || (lhs == rhs
                            && (head.request.deadline_ms, offset)
                                < (
                                    previous_head.request.deadline_ms,
                                    (previous + self.subject_order.len() - self.cursor)
                                        % self.subject_order.len(),
                                ))
                    {
                        Some(index)
                    } else {
                        Some(previous)
                    }
                }
            };
        }
        selected
    }

    fn bump_wait_quanta(&mut self, selected: usize) {
        for (index, key) in self.subject_order.iter().enumerate() {
            if index == selected {
                continue;
            }
            let Some(queue) = self.queues.get_mut(key) else {
                continue;
            };
            let Some(head) = queue.front_mut() else {
                continue;
            };
            head.wait_quanta = head.wait_quanta.saturating_add(1);
            self.max_wait_quanta = self.max_wait_quanta.max(head.wait_quanta);
        }
        if !self.subject_order.is_empty() {
            self.cursor = (selected + 1) % self.subject_order.len();
        }
    }
}

/// Exact integer Jain fairness in parts-per-million.  A value of 1,000,000
/// is perfect fairness; no floating-point rounding enters a receipt.
pub fn jain_fairness_ppm(counts: impl IntoIterator<Item = u64>) -> u64 {
    let counts: Vec<u128> = counts.into_iter().map(u128::from).collect();
    if counts.is_empty() {
        return FAIRNESS_SCALE;
    }
    let sum: u128 = counts.iter().sum();
    if sum == 0 {
        return 0;
    }
    let sum_squares: u128 = counts
        .iter()
        .map(|count| count.saturating_mul(*count))
        .sum();
    if sum_squares == 0 {
        return 0;
    }
    let numerator = sum
        .saturating_mul(sum)
        .saturating_mul(u128::from(FAIRNESS_SCALE));
    let denominator = u128::try_from(counts.len())
        .unwrap_or(u128::MAX)
        .saturating_mul(sum_squares);
    u64::try_from(numerator / denominator).unwrap_or(FAIRNESS_SCALE)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn digest(label: &str) -> Sha256Digest {
        Sha256Digest::for_bytes(label.as_bytes())
    }

    fn resource(quota: QuotaLimits) -> SchedulerResource {
        SchedulerResource {
            resource_id: "synthetic-resource".to_string(),
            resource_sha256: digest("resource"),
            authority_epoch: 3,
            owner_epoch: 7,
            generation: 11,
            fencing_token_sha256: digest("fence-7"),
            quota,
            state: ResourceState::Available,
            cooldown_until_ms: 0,
        }
    }

    fn subject(agent: &str, generation: u64) -> SubjectRef {
        SubjectRef::new("tenant", "workspace", agent, "inferd", generation).expect("subject")
    }

    fn request(
        scheduler: &LocalScheduler,
        id: &str,
        agent: &str,
        deadline_ms: u64,
    ) -> SchedulerRequest {
        let generation = scheduler.resource.generation;
        SchedulerRequest {
            request_id: id.to_string(),
            command_id: format!("command-{id}"),
            run_id: format!("run-{id}"),
            aggregate_id: "aggregate-resource".to_string(),
            idempotency_key: format!("idem-{id}"),
            subject: subject(agent, generation),
            resource_sha256: scheduler.resource.resource_sha256.clone(),
            payload_sha256: digest(&format!("payload-{id}")),
            policy_sha256: digest("policy"),
            expected_revision: scheduler.revision,
            authority_epoch: scheduler.resource.authority_epoch,
            owner_epoch: scheduler.resource.owner_epoch,
            generation,
            fencing_token_sha256: scheduler.resource.fencing_token_sha256.clone(),
            estimate: QuotaVector::new(1, 1, 1, 1, 1),
            safety_margin: QuotaVector::new(0, 0, 0, 0, 0),
            enqueued_at_ms: 1,
            deadline_ms,
            weight: 1,
        }
    }

    #[test]
    fn b4_default_denies_unknown_quota_without_mutating_head() {
        let mut scheduler = LocalScheduler::new(resource(QuotaLimits::unknown_rpm(
            QuotaVector::new(10, 10, 2, 10, 10),
        )))
        .expect("scheduler");
        assert_eq!(scheduler.resource().resource_id, "synthetic-resource");
        let revision = scheduler.revision();
        let held = scheduler.held();
        assert_eq!(
            scheduler.enqueue(request(&scheduler, "unknown", "agent", 100)),
            Err(SchedulerError::UnknownQuota)
        );
        assert_eq!(scheduler.revision(), revision);
        assert_eq!(scheduler.held(), held);
        assert_eq!(scheduler.queued_request_count(), 0);
    }

    #[test]
    fn b4_atomic_hold_and_release_prevent_oversell() {
        let mut scheduler = LocalScheduler::new(resource(QuotaLimits::known(QuotaVector::new(
            2, 2, 1, 2, 2,
        ))))
        .expect("scheduler");
        scheduler
            .enqueue(request(&scheduler, "a", "a", 100))
            .expect("enqueue a");
        let permit = scheduler.grant_next(2).expect("tick").expect("permit");
        assert_eq!(scheduler.active_permit_count(), 1);
        assert_eq!(scheduler.held(), QuotaVector::new(1, 1, 1, 1, 1));
        let mut second = request(&scheduler, "b", "b", 100);
        second.expected_revision = scheduler.revision();
        assert_eq!(scheduler.enqueue(second), Ok(()));
        assert_eq!(scheduler.grant_next(3).expect("tick"), None);
        assert_eq!(scheduler.active_permit_count(), 1);
        scheduler.release(&permit).expect("release");
        let next = scheduler
            .grant_next(4)
            .expect("tick")
            .expect("second permit");
        assert_ne!(next.permit_id, permit.permit_id);
        assert_eq!(scheduler.active_permit_count(), 1);
    }

    #[test]
    fn b4_safety_margin_is_counted_once_and_payload_conflict_is_non_mutating() {
        let mut scheduler = LocalScheduler::new(resource(QuotaLimits::known(QuotaVector::new(
            10, 10, 2, 10, 10,
        ))))
        .expect("scheduler");
        let mut first = request(&scheduler, "margin-a", "a", 100);
        first.estimate = QuotaVector::new(5, 5, 1, 5, 5);
        first.safety_margin = QuotaVector::new(2, 2, 0, 2, 2);
        scheduler.enqueue(first).expect("enqueue margin");
        let permit = scheduler.grant_next(2).expect("tick").expect("permit");
        assert_eq!(permit.reserved, QuotaVector::new(7, 7, 1, 7, 7));
        let held_before_conflict = scheduler.held();
        let revision_before_conflict = scheduler.revision();
        let mut conflict = request(&scheduler, "margin-b", "b", 100);
        conflict.expected_revision = scheduler.revision();
        conflict.idempotency_key = permit.idempotency_key.clone();
        assert_eq!(
            scheduler.enqueue(conflict),
            Err(SchedulerError::DuplicateIdempotency)
        );
        assert_eq!(scheduler.held(), held_before_conflict);
        assert_eq!(scheduler.revision(), revision_before_conflict);
        scheduler.release(&permit).expect("release");
        let mut second = request(&scheduler, "margin-c", "c", 100);
        second.expected_revision = scheduler.revision();
        second.estimate = QuotaVector::new(8, 8, 1, 8, 8);
        second.safety_margin = QuotaVector::new(2, 2, 0, 2, 2);
        assert_eq!(scheduler.enqueue(second), Ok(()));
    }

    #[test]
    fn b4_duplicate_and_stale_callbacks_are_side_effect_free() {
        let mut scheduler = LocalScheduler::new(resource(QuotaLimits::known(QuotaVector::new(
            10, 10, 2, 10, 10,
        ))))
        .expect("scheduler");
        let first = request(&scheduler, "same", "a", 100);
        scheduler.enqueue(first.clone()).expect("enqueue");
        let mut duplicate = first;
        duplicate.expected_revision = scheduler.revision();
        assert_eq!(
            scheduler.enqueue(duplicate),
            Err(SchedulerError::DuplicateRequest)
        );
        let permit = scheduler.grant_next(2).expect("tick").expect("permit");
        let held_before = scheduler.held();
        scheduler
            .rebind(3, 8, 12, digest("fence-8"))
            .expect("rebind");
        assert_eq!(scheduler.release(&permit), Err(SchedulerError::StaleFence));
        assert_eq!(scheduler.held(), held_before);
        assert_eq!(scheduler.active_permit_count(), 1);
        assert_eq!(scheduler.stale_rejections(), 0);
    }

    #[test]
    fn b4_edf_within_subject_and_jain_fairness_are_deterministic() {
        let mut scheduler = LocalScheduler::new(resource(QuotaLimits::known(QuotaVector::new(
            32, 32, 1, 32, 32,
        ))))
        .expect("scheduler");
        for index in 0..12 {
            let agent = ["a", "b", "c"][index % 3];
            let id = format!("r-{index}");
            let mut item = request(&scheduler, &id, agent, 100 + (index as u64));
            item.expected_revision = scheduler.revision();
            item.enqueued_at_ms = 1 + index as u64;
            scheduler.enqueue(item).expect("enqueue");
        }
        let mut grants = Vec::new();
        for now in 2..14 {
            let permit = scheduler.grant_next(now).expect("tick").expect("permit");
            grants.push(permit);
            let actual = QuotaVector::new(1, 1, 1, 1, 1);
            scheduler
                .complete(&grants[grants.len() - 1], actual)
                .expect("complete");
        }
        let counts = scheduler
            .grants_by_subject()
            .values()
            .copied()
            .collect::<Vec<_>>();
        assert_eq!(counts, vec![4, 4, 4]);
        let by_subject =
            grants
                .iter()
                .fold(BTreeMap::<String, Vec<String>>::new(), |mut acc, permit| {
                    acc.entry(permit.subject.agent.clone())
                        .or_default()
                        .push(permit.request_id.clone());
                    acc
                });
        assert_eq!(by_subject["a"], ["r-0", "r-3", "r-6", "r-9"]);
        assert_eq!(by_subject["b"], ["r-1", "r-4", "r-7", "r-10"]);
        assert_eq!(by_subject["c"], ["r-2", "r-5", "r-8", "r-11"]);
        assert!(jain_fairness_ppm(counts) >= 950_000);
        assert!(scheduler.max_wait_quanta() <= 3);
        assert_eq!(scheduler.held(), QuotaVector::default());
        assert_eq!(scheduler.used(), QuotaVector::new(12, 12, 0, 12, 12));
    }

    #[test]
    fn b4_cooldown_deadline_and_unavailable_states_fail_closed() {
        let mut scheduler = LocalScheduler::new(resource(QuotaLimits::known(QuotaVector::new(
            10, 10, 2, 10, 10,
        ))))
        .expect("scheduler");
        scheduler.set_cooldown(10);
        scheduler
            .enqueue(request(&scheduler, "cooldown", "a", 100))
            .expect("enqueue");
        assert_eq!(scheduler.grant_next(9).expect("tick"), None);
        assert!(scheduler.grant_next(10).expect("tick").is_some());

        let mut expired = request(&scheduler, "expired", "b", 20);
        expired.expected_revision = scheduler.revision();
        expired.enqueued_at_ms = 11;
        scheduler.enqueue(expired).expect("enqueue expired");
        assert_eq!(scheduler.grant_next(20).expect("tick"), None);
        assert_eq!(scheduler.expired_rejections(), 1);

        scheduler.resource.state = ResourceState::Draining;
        let mut denied = request(&scheduler, "draining", "c", 100);
        denied.expected_revision = scheduler.revision();
        assert_eq!(
            scheduler.enqueue(denied),
            Err(SchedulerError::ResourceUnavailable)
        );
    }

    #[test]
    fn b4_enqueue_counter_overflow_is_transactional() {
        let mut revision_exhausted = LocalScheduler::new(resource(QuotaLimits::known(
            QuotaVector::new(10, 10, 2, 10, 10),
        )))
        .expect("scheduler");
        revision_exhausted.revision = u64::MAX;
        let revision_request = request(&revision_exhausted, "revision-max", "a", 100);
        let before_revision = revision_exhausted.clone();
        assert_eq!(
            revision_exhausted.enqueue(revision_request),
            Err(SchedulerError::InvalidRequest)
        );
        assert_eq!(revision_exhausted, before_revision);

        let mut sequence_exhausted = LocalScheduler::new(resource(QuotaLimits::known(
            QuotaVector::new(10, 10, 2, 10, 10),
        )))
        .expect("scheduler");
        sequence_exhausted.next_sequence = u64::MAX;
        let sequence_request = request(&sequence_exhausted, "sequence-max", "a", 100);
        let before_sequence = sequence_exhausted.clone();
        assert_eq!(
            sequence_exhausted.enqueue(sequence_request),
            Err(SchedulerError::InvalidRequest)
        );
        assert_eq!(sequence_exhausted, before_sequence);
    }

    #[test]
    fn b4_grant_counter_overflow_is_transactional() {
        let mut nonce_exhausted = LocalScheduler::new(resource(QuotaLimits::known(
            QuotaVector::new(10, 10, 2, 10, 10),
        )))
        .expect("scheduler");
        nonce_exhausted
            .enqueue(request(&nonce_exhausted, "nonce-max", "a", 100))
            .expect("enqueue");
        nonce_exhausted.next_permit_nonce = u64::MAX;
        let before_nonce = nonce_exhausted.clone();
        assert_eq!(
            nonce_exhausted.grant_next(2),
            Err(SchedulerError::InvalidRequest)
        );
        assert_eq!(nonce_exhausted, before_nonce);

        let mut revision_exhausted = LocalScheduler::new(resource(QuotaLimits::known(
            QuotaVector::new(10, 10, 2, 10, 10),
        )))
        .expect("scheduler");
        revision_exhausted
            .enqueue(request(&revision_exhausted, "grant-revision-max", "a", 100))
            .expect("enqueue");
        revision_exhausted.revision = u64::MAX;
        let before_revision = revision_exhausted.clone();
        assert_eq!(
            revision_exhausted.grant_next(2),
            Err(SchedulerError::InvalidRequest)
        );
        assert_eq!(revision_exhausted, before_revision);

        let mut grants_exhausted = LocalScheduler::new(resource(QuotaLimits::known(
            QuotaVector::new(10, 10, 2, 10, 10),
        )))
        .expect("scheduler");
        let grant_request = request(&grants_exhausted, "grant-count-max", "a", 100);
        let subject_key = grant_request.subject_key();
        grants_exhausted.enqueue(grant_request).expect("enqueue");
        grants_exhausted
            .grants_by_subject
            .insert(subject_key, u64::MAX);
        let before_grants = grants_exhausted.clone();
        assert_eq!(
            grants_exhausted.grant_next(2),
            Err(SchedulerError::InvalidRequest)
        );
        assert_eq!(grants_exhausted, before_grants);
    }

    #[test]
    fn b4_completion_and_release_overflow_are_transactional() {
        let mut usage_exhausted = LocalScheduler::new(resource(QuotaLimits::known(
            QuotaVector::new(10, 10, 2, 10, 10),
        )))
        .expect("scheduler");
        usage_exhausted
            .enqueue(request(&usage_exhausted, "usage-max", "a", 100))
            .expect("enqueue");
        let usage_permit = usage_exhausted
            .grant_next(2)
            .expect("tick")
            .expect("permit");
        usage_exhausted.used.rpm = u64::MAX;
        let before_usage = usage_exhausted.clone();
        assert_eq!(
            usage_exhausted.complete(&usage_permit, QuotaVector::new(1, 0, 0, 0, 0),),
            Err(SchedulerError::QuotaExceeded)
        );
        assert_eq!(usage_exhausted, before_usage);

        let mut completion_revision_exhausted = LocalScheduler::new(resource(QuotaLimits::known(
            QuotaVector::new(10, 10, 2, 10, 10),
        )))
        .expect("scheduler");
        completion_revision_exhausted
            .enqueue(request(
                &completion_revision_exhausted,
                "completion-revision-max",
                "a",
                100,
            ))
            .expect("enqueue");
        let completion_permit = completion_revision_exhausted
            .grant_next(2)
            .expect("tick")
            .expect("permit");
        completion_revision_exhausted.revision = u64::MAX;
        let before_completion_revision = completion_revision_exhausted.clone();
        assert_eq!(
            completion_revision_exhausted.complete(&completion_permit, QuotaVector::default()),
            Err(SchedulerError::InvalidRequest)
        );
        assert_eq!(completion_revision_exhausted, before_completion_revision);

        let mut release_revision_exhausted = LocalScheduler::new(resource(QuotaLimits::known(
            QuotaVector::new(10, 10, 2, 10, 10),
        )))
        .expect("scheduler");
        release_revision_exhausted
            .enqueue(request(
                &release_revision_exhausted,
                "release-revision-max",
                "a",
                100,
            ))
            .expect("enqueue");
        let release_permit = release_revision_exhausted
            .grant_next(2)
            .expect("tick")
            .expect("permit");
        release_revision_exhausted.revision = u64::MAX;
        let before_release_revision = release_revision_exhausted.clone();
        assert_eq!(
            release_revision_exhausted.release(&release_permit),
            Err(SchedulerError::InvalidRequest)
        );
        assert_eq!(release_revision_exhausted, before_release_revision);
    }

    #[test]
    fn b4_authority_flags_and_resource_states_are_explicitly_non_production() {
        for state in [
            ResourceState::Draining,
            ResourceState::Unavailable,
            ResourceState::Unknown,
        ] {
            let mut scheduler = LocalScheduler::new(resource(QuotaLimits::known(
                QuotaVector::new(1, 1, 1, 1, 1),
            )))
            .expect("scheduler");
            scheduler.resource.state = state;
            let request = request(&scheduler, "state", "agent", 100);
            assert_eq!(
                scheduler.enqueue(request),
                Err(SchedulerError::ResourceUnavailable)
            );
        }
    }
}
