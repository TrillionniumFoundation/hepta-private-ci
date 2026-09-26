//! Atomic product reader/control capabilities. No storage or release authority.
//!
//! Recovery requires an independently current witness from the trusted owner.
//! The witness adapter and durable checkpoint publication must be composed by
//! that owner; this in-process provider is not itself a durable registry.

use std::sync::Arc;
use std::sync::RwLock;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
use codex_hepta_memory::RetrievalExecutionContextV1;
use codex_hepta_types::Digest32;

use super::CurrentMemoryRetrievalContext;

const PRODUCT_CONTEXT_DOMAIN: &[u8] = b"hepta.agentd.product-retrieval-context.v2";
const MAX_LEASE_MS: u64 = 300_000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductRetrievalContextSnapshotV1 {
    pub owner: AgentId,
    pub body_generation: u64,
    pub epoch: u64,
    pub lease_expires_unix_ms: u64,
    pub context: Option<RetrievalExecutionContextV1>,
    pub revoked: bool,
    pub state_digest: Digest32,
}

impl ProductRetrievalContextSnapshotV1 {
    pub fn validate(&self) -> Result<(), String> {
        if self.body_generation == 0 || self.epoch == 0 {
            return Err("invalid product generation".to_string());
        }
        if self.revoked != self.context.is_none()
            || (self.revoked && self.lease_expires_unix_ms != 0)
            || (!self.revoked && self.lease_expires_unix_ms == 0)
        {
            return Err("invalid product lifecycle state".to_string());
        }
        if let Some(context) = &self.context {
            context.validate().map_err(|error| error.to_string())?;
        }
        if self.state_digest != self.compute_state_digest() {
            return Err("product state digest mismatch".to_string());
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_state_digest(&self) -> Digest32 {
        let mut bytes = PRODUCT_CONTEXT_DOMAIN.to_vec();
        let owner = self.owner.as_str().as_bytes();
        bytes.extend_from_slice(&u64::try_from(owner.len()).unwrap_or(u64::MAX).to_be_bytes());
        bytes.extend_from_slice(owner);
        bytes.extend_from_slice(&self.body_generation.to_be_bytes());
        bytes.extend_from_slice(&self.epoch.to_be_bytes());
        bytes.extend_from_slice(&self.lease_expires_unix_ms.to_be_bytes());
        bytes.push(u8::from(self.revoked));
        match &self.context {
            Some(context) => {
                bytes.push(1);
                bytes.extend_from_slice(context.binding_digest().as_array());
            }
            None => bytes.push(0),
        }
        Digest32::of_bytes(&bytes)
    }
}

/// Trusted composition boundary, not authentication by a caller-supplied hash.
/// Implementations must read a separately protected, current durable owner state.
pub trait RetrievalRecoveryWitnessV1: Send + Sync {
    fn latest_state(
        &self,
        owner: &AgentId,
        body_generation: u64,
    ) -> Result<(u64, Digest32), String>;
}

struct ProductState {
    snapshot: ProductRetrievalContextSnapshotV1,
    acquired_wall_ms: u64,
    monotonic_deadline: Instant,
}

pub(super) struct ProductMemoryRetrievalContextV1 {
    state: RwLock<ProductState>,
}

/// Unforgeable by struct literal: its provider field is private. Keep this at
/// the protected composition root; request handlers receive only the reader.
pub struct ProductRetrievalContextControlV1 {
    provider: Arc<ProductMemoryRetrievalContextV1>,
}

impl ProductRetrievalContextControlV1 {
    pub(super) fn from_provider(provider: Arc<ProductMemoryRetrievalContextV1>) -> Self {
        Self { provider }
    }

    pub fn snapshot(&self) -> Result<ProductRetrievalContextSnapshotV1, String> {
        self.provider.snapshot()
    }

    pub fn rotate(
        &self,
        expected_epoch: u64,
        context: RetrievalExecutionContextV1,
        lease_expires_unix_ms: u64,
    ) -> Result<u64, String> {
        context.validate().map_err(|error| error.to_string())?;
        let mut state = self
            .provider
            .state
            .write()
            .map_err(|_| "poisoned provider lock")?;
        require_live(&state)?;
        require_epoch(&state, expected_epoch)?;
        let previous = state.snapshot.context.as_ref().ok_or("revoked context")?;
        if context.generation_vector.authority_epoch < previous.generation_vector.authority_epoch {
            return Err("authority epoch regression".to_string());
        }
        let (wall, deadline) = lease_window(lease_expires_unix_ms)?;
        let next = state
            .snapshot
            .epoch
            .checked_add(1)
            .ok_or("epoch overflow")?;
        state.snapshot.context = Some(context);
        state.snapshot.epoch = next;
        state.snapshot.lease_expires_unix_ms = lease_expires_unix_ms;
        state.snapshot.state_digest = state.snapshot.compute_state_digest();
        state.acquired_wall_ms = wall;
        state.monotonic_deadline = deadline;
        Ok(next)
    }

    pub fn renew(&self, expected_epoch: u64, lease_expires_unix_ms: u64) -> Result<u64, String> {
        let mut state = self
            .provider
            .state
            .write()
            .map_err(|_| "poisoned provider lock")?;
        require_live(&state)?;
        require_epoch(&state, expected_epoch)?;
        let (wall, deadline) = lease_window(lease_expires_unix_ms)?;
        let next = state
            .snapshot
            .epoch
            .checked_add(1)
            .ok_or("epoch overflow")?;
        state.snapshot.epoch = next;
        state.snapshot.lease_expires_unix_ms = lease_expires_unix_ms;
        state.snapshot.state_digest = state.snapshot.compute_state_digest();
        state.acquired_wall_ms = wall;
        state.monotonic_deadline = deadline;
        Ok(next)
    }

    pub fn revoke(&self, expected_epoch: u64) -> Result<u64, String> {
        let mut state = self
            .provider
            .state
            .write()
            .map_err(|_| "poisoned provider lock")?;
        state.snapshot.validate()?;
        if state.snapshot.revoked
            && (expected_epoch == state.snapshot.epoch
                || expected_epoch.checked_add(1) == Some(state.snapshot.epoch))
        {
            return Ok(state.snapshot.epoch);
        }
        require_epoch(&state, expected_epoch)?;
        let next = state
            .snapshot
            .epoch
            .checked_add(1)
            .ok_or("epoch overflow")?;
        state.snapshot.epoch = next;
        state.snapshot.lease_expires_unix_ms = 0;
        state.snapshot.context = None;
        state.snapshot.revoked = true;
        state.snapshot.state_digest = state.snapshot.compute_state_digest();
        state.monotonic_deadline = Instant::now();
        Ok(next)
    }
}

impl ProductMemoryRetrievalContextV1 {
    pub(super) fn new(
        owner: AgentId,
        body_generation: u64,
        context: RetrievalExecutionContextV1,
        lease_expires_unix_ms: u64,
    ) -> Result<Self, String> {
        let mut snapshot = ProductRetrievalContextSnapshotV1 {
            owner,
            body_generation,
            epoch: 1,
            lease_expires_unix_ms,
            context: Some(context),
            revoked: false,
            state_digest: Digest32::ZERO,
        };
        snapshot.state_digest = snapshot.compute_state_digest();
        snapshot.validate()?;
        let (acquired_wall_ms, monotonic_deadline) = lease_window(lease_expires_unix_ms)?;
        Ok(Self {
            state: RwLock::new(ProductState {
                snapshot,
                acquired_wall_ms,
                monotonic_deadline,
            }),
        })
    }

    pub(super) fn recover(
        snapshot: ProductRetrievalContextSnapshotV1,
        witness: &dyn RetrievalRecoveryWitnessV1,
    ) -> Result<Self, String> {
        snapshot.validate()?;
        let latest = witness.latest_state(&snapshot.owner, snapshot.body_generation)?;
        if latest != (snapshot.epoch, snapshot.state_digest) {
            return Err("checkpoint is not the independently current owner state".to_string());
        }
        let (acquired_wall_ms, monotonic_deadline) = if snapshot.revoked {
            (now_unix_ms()?, Instant::now())
        } else {
            lease_window(snapshot.lease_expires_unix_ms)?
        };
        Ok(Self {
            state: RwLock::new(ProductState {
                snapshot,
                acquired_wall_ms,
                monotonic_deadline,
            }),
        })
    }

    fn snapshot(&self) -> Result<ProductRetrievalContextSnapshotV1, String> {
        let state = self.state.read().map_err(|_| "poisoned provider lock")?;
        state.snapshot.validate()?;
        Ok(state.snapshot.clone())
    }
}

impl CurrentMemoryRetrievalContext for ProductMemoryRetrievalContextV1 {
    fn current(
        &self,
        owner: &AgentId,
        body_generation: u64,
    ) -> Result<RetrievalExecutionContextV1, String> {
        self.acquire_context(owner, body_generation)
            .map(|(context, _, _)| context)
    }

    fn acquire_context(
        &self,
        owner: &AgentId,
        body_generation: u64,
    ) -> Result<(RetrievalExecutionContextV1, Digest32, Option<u64>), String> {
        let state = self.state.read().map_err(|_| "poisoned provider lock")?;
        if owner != &state.snapshot.owner || body_generation != state.snapshot.body_generation {
            return Err("retrieval owner/body mismatch".to_string());
        }
        require_live(&state)?;
        let context = state.snapshot.context.clone().ok_or("revoked context")?;
        Ok((
            context,
            state.snapshot.state_digest,
            Some(state.snapshot.lease_expires_unix_ms),
        ))
    }

    fn lifecycle_epoch(&self) -> Result<u64, String> {
        self.snapshot().map(|snapshot| snapshot.epoch)
    }

    fn lease_expires_unix_ms(&self) -> Result<u64, String> {
        self.snapshot()
            .map(|snapshot| snapshot.lease_expires_unix_ms)
    }

    fn context_state_digest(&self) -> Result<Digest32, String> {
        self.snapshot().map(|snapshot| snapshot.state_digest)
    }

    fn revoked(&self) -> Result<bool, String> {
        self.snapshot().map(|snapshot| snapshot.revoked)
    }
}

fn require_epoch(state: &ProductState, expected: u64) -> Result<(), String> {
    if state.snapshot.epoch != expected {
        return Err("retrieval lifecycle epoch mismatch".to_string());
    }
    Ok(())
}

fn require_live(state: &ProductState) -> Result<(), String> {
    state.snapshot.validate()?;
    if state.snapshot.revoked {
        return Err("retrieval context revoked".to_string());
    }
    let now = now_unix_ms()?;
    if now < state.acquired_wall_ms
        || now >= state.snapshot.lease_expires_unix_ms
        || Instant::now() >= state.monotonic_deadline
    {
        return Err("retrieval lease expired or clock regressed".to_string());
    }
    Ok(())
}

fn lease_window(expires: u64) -> Result<(u64, Instant), String> {
    let now = now_unix_ms()?;
    let duration = expires
        .checked_sub(now)
        .ok_or("lease is not in the future")?;
    if duration == 0 || duration > MAX_LEASE_MS {
        return Err("lease is outside the bounded product window".to_string());
    }
    let deadline = Instant::now()
        .checked_add(Duration::from_millis(duration))
        .ok_or("lease overflow")?;
    Ok((now, deadline))
}

fn now_unix_ms() -> Result<u64, String> {
    let duration = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| "invalid wall clock")?;
    u64::try_from(duration.as_millis()).map_err(|_| "wall clock overflow".to_string())
}

#[cfg(test)]
#[path = "product_retrieval_context_tests.rs"]
mod tests;
