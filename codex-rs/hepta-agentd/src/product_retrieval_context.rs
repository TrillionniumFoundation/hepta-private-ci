//! Product-owned currentness, lease, rotation, revocation and recovery for
//! generation-bound memory retrieval contexts.
//!
//! This provider owns no model or memory data. It seals an externally composed
//! `RetrievalExecutionContextV1` to one Agent/body generation and exposes it
//! through the `CurrentMemoryRetrievalContext` capability. Every read validates
//! the lease and the full context binding again, so rotation and revocation fail
//! closed for in-flight requests.

use std::error::Error as StdError;
use std::fmt;
use std::sync::RwLock;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
use codex_hepta_memory::RetrievalExecutionContextV1;
use codex_hepta_types::Digest32;

use crate::CurrentMemoryRetrievalContext;

const PRODUCT_CONTEXT_DOMAIN: &[u8] = b"hepta.agentd.product-retrieval-context.v1";

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
    pub fn validate(&self) -> Result<(), ProductRetrievalContextErrorV1> {
        if self.body_generation == 0 || self.epoch == 0 {
            return Err(ProductRetrievalContextErrorV1::InvalidGeneration);
        }
        if self.revoked != self.context.is_none() {
            return Err(ProductRetrievalContextErrorV1::InvalidState);
        }
        if let Some(context) = &self.context {
            context
                .validate()
                .map_err(|error| ProductRetrievalContextErrorV1::InvalidContext(error.to_string()))?;
        }
        if self.state_digest != self.compute_state_digest() {
            return Err(ProductRetrievalContextErrorV1::DigestMismatch);
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_state_digest(&self) -> Digest32 {
        state_digest(
            &self.owner,
            self.body_generation,
            self.epoch,
            self.lease_expires_unix_ms,
            self.context.as_ref(),
            self.revoked,
        )
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct ProductRetrievalContextStateV1 {
    epoch: u64,
    lease_expires_unix_ms: u64,
    context: Option<RetrievalExecutionContextV1>,
    revoked: bool,
    state_digest: Digest32,
}

pub struct ProductMemoryRetrievalContextV1 {
    owner: AgentId,
    body_generation: u64,
    state: RwLock<ProductRetrievalContextStateV1>,
}

impl ProductMemoryRetrievalContextV1 {
    pub fn new(
        owner: AgentId,
        body_generation: u64,
        context: RetrievalExecutionContextV1,
        lease_expires_unix_ms: u64,
    ) -> Result<Self, ProductRetrievalContextErrorV1> {
        if body_generation == 0 {
            return Err(ProductRetrievalContextErrorV1::InvalidGeneration);
        }
        context
            .validate()
            .map_err(|error| ProductRetrievalContextErrorV1::InvalidContext(error.to_string()))?;
        require_future_lease(lease_expires_unix_ms)?;
        let epoch = 1;
        let state_digest = state_digest(
            &owner,
            body_generation,
            epoch,
            lease_expires_unix_ms,
            Some(&context),
            false,
        );
        Ok(Self {
            owner,
            body_generation,
            state: RwLock::new(ProductRetrievalContextStateV1 {
                epoch,
                lease_expires_unix_ms,
                context: Some(context),
                revoked: false,
                state_digest,
            }),
        })
    }

    pub fn recover(
        snapshot: ProductRetrievalContextSnapshotV1,
    ) -> Result<Self, ProductRetrievalContextErrorV1> {
        snapshot.validate()?;
        if !snapshot.revoked {
            require_future_lease(snapshot.lease_expires_unix_ms)?;
        }
        Ok(Self {
            owner: snapshot.owner,
            body_generation: snapshot.body_generation,
            state: RwLock::new(ProductRetrievalContextStateV1 {
                epoch: snapshot.epoch,
                lease_expires_unix_ms: snapshot.lease_expires_unix_ms,
                context: snapshot.context,
                revoked: snapshot.revoked,
                state_digest: snapshot.state_digest,
            }),
        })
    }

    pub fn rotate(
        &self,
        expected_epoch: u64,
        context: RetrievalExecutionContextV1,
        lease_expires_unix_ms: u64,
    ) -> Result<u64, ProductRetrievalContextErrorV1> {
        context
            .validate()
            .map_err(|error| ProductRetrievalContextErrorV1::InvalidContext(error.to_string()))?;
        require_future_lease(lease_expires_unix_ms)?;
        let mut state = self
            .state
            .write()
            .map_err(|_| ProductRetrievalContextErrorV1::LockPoisoned)?;
        verify_locked_state(&self.owner, self.body_generation, &state)?;
        if state.epoch != expected_epoch {
            return Err(ProductRetrievalContextErrorV1::EpochMismatch {
                expected: expected_epoch,
                actual: state.epoch,
            });
        }
        if state.revoked {
            return Err(ProductRetrievalContextErrorV1::Revoked);
        }
        let next_epoch = state
            .epoch
            .checked_add(1)
            .ok_or(ProductRetrievalContextErrorV1::EpochOverflow)?;
        state.epoch = next_epoch;
        state.lease_expires_unix_ms = lease_expires_unix_ms;
        state.context = Some(context);
        state.state_digest = state_digest(
            &self.owner,
            self.body_generation,
            state.epoch,
            state.lease_expires_unix_ms,
            state.context.as_ref(),
            false,
        );
        Ok(next_epoch)
    }

    pub fn renew(
        &self,
        expected_epoch: u64,
        lease_expires_unix_ms: u64,
    ) -> Result<u64, ProductRetrievalContextErrorV1> {
        require_future_lease(lease_expires_unix_ms)?;
        let context = {
            let state = self
                .state
                .read()
                .map_err(|_| ProductRetrievalContextErrorV1::LockPoisoned)?;
            verify_locked_state(&self.owner, self.body_generation, &state)?;
            if state.epoch != expected_epoch {
                return Err(ProductRetrievalContextErrorV1::EpochMismatch {
                    expected: expected_epoch,
                    actual: state.epoch,
                });
            }
            state
                .context
                .clone()
                .ok_or(ProductRetrievalContextErrorV1::Revoked)?
        };
        self.rotate(expected_epoch, context, lease_expires_unix_ms)
    }

    pub fn revoke(
        &self,
        expected_epoch: u64,
    ) -> Result<u64, ProductRetrievalContextErrorV1> {
        let mut state = self
            .state
            .write()
            .map_err(|_| ProductRetrievalContextErrorV1::LockPoisoned)?;
        verify_locked_state(&self.owner, self.body_generation, &state)?;
        if state.epoch != expected_epoch {
            return Err(ProductRetrievalContextErrorV1::EpochMismatch {
                expected: expected_epoch,
                actual: state.epoch,
            });
        }
        let next_epoch = state
            .epoch
            .checked_add(1)
            .ok_or(ProductRetrievalContextErrorV1::EpochOverflow)?;
        state.epoch = next_epoch;
        state.lease_expires_unix_ms = 0;
        state.context = None;
        state.revoked = true;
        state.state_digest = state_digest(
            &self.owner,
            self.body_generation,
            state.epoch,
            state.lease_expires_unix_ms,
            None,
            true,
        );
        Ok(next_epoch)
    }

    pub fn snapshot(
        &self,
    ) -> Result<ProductRetrievalContextSnapshotV1, ProductRetrievalContextErrorV1> {
        let state = self
            .state
            .read()
            .map_err(|_| ProductRetrievalContextErrorV1::LockPoisoned)?;
        verify_locked_state(&self.owner, self.body_generation, &state)?;
        Ok(ProductRetrievalContextSnapshotV1 {
            owner: self.owner.clone(),
            body_generation: self.body_generation,
            epoch: state.epoch,
            lease_expires_unix_ms: state.lease_expires_unix_ms,
            context: state.context.clone(),
            revoked: state.revoked,
            state_digest: state.state_digest,
        })
    }

    #[must_use]
    pub fn owner(&self) -> &AgentId {
        &self.owner
    }

    #[must_use]
    pub const fn body_generation(&self) -> u64 {
        self.body_generation
    }
}

impl CurrentMemoryRetrievalContext for ProductMemoryRetrievalContextV1 {
    fn current(
        &self,
        owner: &AgentId,
        body_generation: u64,
    ) -> Result<RetrievalExecutionContextV1, String> {
        if owner != &self.owner || body_generation != self.body_generation {
            return Err(ProductRetrievalContextErrorV1::IdentityMismatch.to_string());
        }
        let state = self
            .state
            .read()
            .map_err(|_| ProductRetrievalContextErrorV1::LockPoisoned.to_string())?;
        verify_locked_state(&self.owner, self.body_generation, &state)
            .map_err(|error| error.to_string())?;
        if state.revoked {
            return Err(ProductRetrievalContextErrorV1::Revoked.to_string());
        }
        let now = now_unix_ms().map_err(|error| error.to_string())?;
        if now >= state.lease_expires_unix_ms {
            return Err(ProductRetrievalContextErrorV1::LeaseExpired.to_string());
        }
        let context = state
            .context
            .clone()
            .ok_or_else(|| ProductRetrievalContextErrorV1::InvalidState.to_string())?;
        context
            .validate()
            .map_err(|error| ProductRetrievalContextErrorV1::InvalidContext(error.to_string()).to_string())?;
        Ok(context)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProductRetrievalContextErrorV1 {
    InvalidGeneration,
    InvalidState,
    InvalidContext(String),
    IdentityMismatch,
    LeaseExpired,
    LeaseNotFuture,
    Revoked,
    EpochMismatch { expected: u64, actual: u64 },
    EpochOverflow,
    DigestMismatch,
    Clock,
    LockPoisoned,
}

impl fmt::Display for ProductRetrievalContextErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ProductRetrievalContextErrorV1 {}

fn verify_locked_state(
    owner: &AgentId,
    body_generation: u64,
    state: &ProductRetrievalContextStateV1,
) -> Result<(), ProductRetrievalContextErrorV1> {
    if state.epoch == 0 || state.revoked != state.context.is_none() {
        return Err(ProductRetrievalContextErrorV1::InvalidState);
    }
    let expected = state_digest(
        owner,
        body_generation,
        state.epoch,
        state.lease_expires_unix_ms,
        state.context.as_ref(),
        state.revoked,
    );
    if expected != state.state_digest {
        return Err(ProductRetrievalContextErrorV1::DigestMismatch);
    }
    Ok(())
}

fn require_future_lease(lease_expires_unix_ms: u64) -> Result<(), ProductRetrievalContextErrorV1> {
    if lease_expires_unix_ms <= now_unix_ms()? {
        return Err(ProductRetrievalContextErrorV1::LeaseNotFuture);
    }
    Ok(())
}

fn now_unix_ms() -> Result<u64, ProductRetrievalContextErrorV1> {
    u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| ProductRetrievalContextErrorV1::Clock)?
            .as_millis(),
    )
    .map_err(|_| ProductRetrievalContextErrorV1::Clock)
}

fn state_digest(
    owner: &AgentId,
    body_generation: u64,
    epoch: u64,
    lease_expires_unix_ms: u64,
    context: Option<&RetrievalExecutionContextV1>,
    revoked: bool,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(PRODUCT_CONTEXT_DOMAIN);
    push_bytes(&mut bytes, owner.as_str().as_bytes());
    bytes.extend_from_slice(&body_generation.to_be_bytes());
    bytes.extend_from_slice(&epoch.to_be_bytes());
    bytes.extend_from_slice(&lease_expires_unix_ms.to_be_bytes());
    bytes.push(u8::from(revoked));
    match context {
        Some(context) => {
            bytes.push(1);
            bytes.extend_from_slice(context.binding_digest().as_array());
        }
        None => bytes.push(0),
    }
    Digest32::of_bytes(&bytes)
}

fn push_bytes(bytes: &mut Vec<u8>, value: &[u8]) {
    bytes.extend_from_slice(&u64::try_from(value.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(value);
}
