//! Signed, leased context cache for the named Agentd retrieval caller.
//!
//! The frontier port must be the independent current owner, not a replayable
//! local file. Every observation carries a fresh OS-random challenge signed by
//! the pinned frontier key. Recovery starts empty and re-observes that owner.
//! This component grants no activation authority and supplies no vector encoder.

use std::fs::File;
use std::io::Read;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
use codex_hepta_memory::RetrievalExecutionContextV1;
use codex_hepta_types::Digest32;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;

use crate::CurrentMemoryRetrievalContext;

const MAX_LEASE_MS: u64 = 300_000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedMemoryRetrievalContextV1 {
    pub owner: AgentId,
    pub body_generation: u64,
    pub sequence: u64,
    pub not_before_unix_ms: u64,
    pub expires_unix_ms: u64,
    pub context: RetrievalExecutionContextV1,
    pub signature: [u8; 64],
}

impl SignedMemoryRetrievalContextV1 {
    #[must_use]
    pub fn signing_bytes(&self) -> Vec<u8> {
        let mut bytes = b"hepta.agentd.retrieval-publication.v1".to_vec();
        bind_owner(&mut bytes, &self.owner, self.body_generation);
        bytes.extend_from_slice(&self.context.generation_vector.authority_epoch.to_be_bytes());
        bytes.extend_from_slice(&self.sequence.to_be_bytes());
        bytes.extend_from_slice(&self.not_before_unix_ms.to_be_bytes());
        bytes.extend_from_slice(&self.expires_unix_ms.to_be_bytes());
        bytes.extend_from_slice(self.context.binding_digest().as_array());
        bytes
    }

    #[must_use]
    pub fn publication_digest(&self) -> Digest32 {
        Digest32::of_bytes(&self.signing_bytes())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryRetrievalFrontierV1 {
    pub owner: AgentId,
    pub body_generation: u64,
    pub authority_epoch: u64,
    pub sequence: u64,
    /// None is an explicit revocation. Revocation must advance the sequence.
    pub publication_digest: Option<Digest32>,
    pub expires_unix_ms: u64,
    pub challenge: [u8; 32],
    pub signature: [u8; 64],
}

impl MemoryRetrievalFrontierV1 {
    #[must_use]
    pub fn signing_bytes(&self) -> Vec<u8> {
        let mut bytes = b"hepta.agentd.retrieval-frontier.v1".to_vec();
        bind_owner(&mut bytes, &self.owner, self.body_generation);
        bytes.extend_from_slice(&self.authority_epoch.to_be_bytes());
        bytes.extend_from_slice(&self.sequence.to_be_bytes());
        match self.publication_digest {
            Some(digest) => {
                bytes.push(1);
                bytes.extend_from_slice(digest.as_array());
            }
            None => bytes.push(0),
        }
        bytes.extend_from_slice(&self.expires_unix_ms.to_be_bytes());
        bytes.extend_from_slice(&self.challenge);
        bytes
    }
}

/// Owner transport, not an authority credential. The provider verifies each
/// response with its pinned key. Implementations must bound blocking I/O and
/// obtain the current frontier outside the Agent home's rollback domain.
pub trait MemoryRetrievalFrontierOwnerV1: Send + Sync {
    fn observe(
        &self,
        owner: &AgentId,
        body_generation: u64,
        challenge: [u8; 32],
    ) -> Result<MemoryRetrievalFrontierV1, String>;
}

struct PinnedContext {
    publication: SignedMemoryRetrievalContextV1,
    installed_at: Instant,
    remaining: Duration,
}

#[derive(Default)]
struct ProviderState {
    floor: Option<(u64, u64, Option<Digest32>)>,
    pinned: Option<PinnedContext>,
    last_wall_ms: u64,
}

/// Concrete host-composable provider. Keys are immutable startup pins. Key
/// rotation requires a newly authorized host configuration, not a request field.
pub struct LeasedMemoryRetrievalProviderV1 {
    owner: AgentId,
    body_generation: u64,
    context_key: VerifyingKey,
    frontier_key: VerifyingKey,
    frontier_owner: Arc<dyn MemoryRetrievalFrontierOwnerV1>,
    maximum_lease_ms: u64,
    state: Mutex<ProviderState>,
}

impl LeasedMemoryRetrievalProviderV1 {
    pub fn new(
        owner: AgentId,
        body_generation: u64,
        context_public_key: [u8; 32],
        frontier_public_key: [u8; 32],
        frontier_owner: Arc<dyn MemoryRetrievalFrontierOwnerV1>,
        maximum_lease_ms: u64,
    ) -> Result<Self, String> {
        if body_generation == 0 || !(1..=MAX_LEASE_MS).contains(&maximum_lease_ms) {
            return Err("invalid retrieval provider identity or lease bound".to_string());
        }
        let context_key = VerifyingKey::from_bytes(&context_public_key)
            .map_err(|_| "invalid retrieval context key".to_string())?;
        let frontier_key = VerifyingKey::from_bytes(&frontier_public_key)
            .map_err(|_| "invalid retrieval frontier key".to_string())?;
        if context_key.is_weak() || frontier_key.is_weak() {
            return Err("weak retrieval authority key".to_string());
        }
        Ok(Self {
            owner,
            body_generation,
            context_key,
            frontier_key,
            frontier_owner,
            maximum_lease_ms,
            state: Mutex::new(ProviderState::default()),
        })
    }

    /// Installation is atomic and idempotent. Reinstalling an identical
    /// publication never renews its monotonic lease.
    pub fn install(&self, publication: SignedMemoryRetrievalContextV1) -> Result<(), String> {
        if publication.owner != self.owner
            || publication.body_generation != self.body_generation
            || publication.sequence == 0
        {
            return Err("retrieval publication owner/body/sequence mismatch".to_string());
        }
        publication.context.validate().map_err(|error| error.to_string())?;
        let now = now_ms()?;
        let duration = publication.expires_unix_ms
            .checked_sub(publication.not_before_unix_ms)
            .ok_or_else(|| "invalid retrieval publication interval".to_string())?;
        if duration == 0 || duration > self.maximum_lease_ms
            || now < publication.not_before_unix_ms || now >= publication.expires_unix_ms
        {
            return Err("retrieval publication is outside its bounded lease".to_string());
        }
        self.context_key.verify_strict(
            &publication.signing_bytes(), &Signature::from_bytes(&publication.signature),
        ).map_err(|_| "invalid retrieval publication signature".to_string())?;
        let frontier = self.observe_frontier()?;
        let expected = (
            publication.context.generation_vector.authority_epoch,
            publication.sequence,
            Some(publication.publication_digest()),
        );
        if frontier != expected {
            return Err("retrieval publication is not the current owner frontier".to_string());
        }
        let mut state = self.state.lock().map_err(|_| "retrieval provider poisoned".to_string())?;
        let now = check_clock(&mut state)?;
        if state.floor != Some(expected) || now >= publication.expires_unix_ms {
            return Err("retrieval frontier changed during installation".to_string());
        }
        if let Some(pinned) = &state.pinned
            && pinned.publication.publication_digest() == publication.publication_digest()
        {
            return Ok(());
        }
        let remaining = Duration::from_millis(publication.expires_unix_ms - now);
        state.pinned = Some(PinnedContext { publication, installed_at: Instant::now(), remaining });
        Ok(())
    }

    fn observe_frontier(&self) -> Result<(u64, u64, Option<Digest32>), String> {
        let mut challenge = [0_u8; 32];
        File::open("/dev/urandom").and_then(|mut file| file.read_exact(&mut challenge))
            .map_err(|_| "retrieval frontier entropy unavailable".to_string())?;
        let response = self.frontier_owner.observe(&self.owner, self.body_generation, challenge)?;
        if response.owner != self.owner || response.body_generation != self.body_generation
            || response.challenge != challenge || response.authority_epoch == 0 || response.sequence == 0
            || response.publication_digest.is_some_and(|digest| digest.is_zero())
        {
            return Err("retrieval frontier identity/challenge mismatch".to_string());
        }
        self.frontier_key.verify_strict(
            &response.signing_bytes(), &Signature::from_bytes(&response.signature),
        ).map_err(|_| "invalid retrieval frontier signature".to_string())?;
        let mut state = self.state.lock().map_err(|_| "retrieval provider poisoned".to_string())?;
        let now = check_clock(&mut state)?;
        if response.expires_unix_ms <= now
            || response.expires_unix_ms - now > self.maximum_lease_ms
        {
            return Err("retrieval frontier is expired or exceeds its lease".to_string());
        }
        let observed = (response.authority_epoch, response.sequence, response.publication_digest);
        if let Some(previous) = state.floor {
            if (observed.0, observed.1) < (previous.0, previous.1)
                || ((observed.0, observed.1) == (previous.0, previous.1) && observed.2 != previous.2)
            {
                return Err("retrieval frontier rollback or same-sequence drift".to_string());
            }
        }
        if state.floor != Some(observed) {
            state.pinned = None;
            state.floor = Some(observed);
        }
        Ok(observed)
    }
}

impl CurrentMemoryRetrievalContext for LeasedMemoryRetrievalProviderV1 {
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
        if owner != &self.owner || body_generation != self.body_generation {
            return Err("retrieval provider owner/body mismatch".to_string());
        }
        let frontier = self.observe_frontier()?;
        let mut state = self.state.lock().map_err(|_| "retrieval provider poisoned".to_string())?;
        let now = check_clock(&mut state)?;
        if state.floor != Some(frontier) || frontier.2.is_none() {
            return Err("retrieval context was rotated or revoked".to_string());
        }
        let pinned = state.pinned.as_ref().ok_or_else(|| "retrieval provider requires a current signed publication".to_string())?;
        if now >= pinned.publication.expires_unix_ms
            || pinned.installed_at.elapsed() >= pinned.remaining
            || Some(pinned.publication.publication_digest()) != frontier.2
        {
            return Err("retrieval context lease expired or changed".to_string());
        }
        // One mutex-protected observation: never combine one publication's
        // context with a separately sampled successor's epoch or lease.
        Ok((
            pinned.publication.context.clone(),
            pinned.publication.publication_digest(),
            Some(pinned.publication.expires_unix_ms),
        ))
    }
}

fn check_clock(state: &mut ProviderState) -> Result<u64, String> {
    let now = now_ms()?;
    if now < state.last_wall_ms {
        state.pinned = None;
        return Err("retrieval provider wall clock moved backwards".to_string());
    }
    state.last_wall_ms = now;
    Ok(now)
}

fn now_ms() -> Result<u64, String> {
    let elapsed = SystemTime::now().duration_since(UNIX_EPOCH)
        .map_err(|_| "retrieval clock is before epoch".to_string())?;
    u64::try_from(elapsed.as_millis()).map_err(|_| "retrieval clock overflow".to_string())
}

fn bind_owner(bytes: &mut Vec<u8>, owner: &AgentId, body_generation: u64) {
    let owner = owner.as_str().as_bytes();
    bytes.extend_from_slice(&u64::try_from(owner.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(owner);
    bytes.extend_from_slice(&body_generation.to_be_bytes());
}

#[cfg(test)]
#[path = "cognitive_retrieval_provider_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "cognitive_retrieval_signed_delivery_tests.rs"]
mod signed_delivery_tests;
