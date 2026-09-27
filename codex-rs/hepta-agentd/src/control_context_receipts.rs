//! Receipt admission owned by one authenticated Agentd control listener.
//!
//! This is deliberately not a process-global cache and not an authority issuer.
//! The exact native plan digest stays unchanged on the wire. A final-use request
//! must match a receipt actually produced by this host, with the complete ordered
//! response, current lifecycle generation and independently current profiles.
//! Rebinding the listener or restarting the process forgets all leases and thus
//! rejects old responses. No raw query or context body is retained here.

use std::collections::BTreeMap;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_types::Digest32;

use crate::AgentdError;
use crate::AgentdMethod;
use crate::AgentdPayload;
use crate::AgentdResponse;
use crate::AgentdState;
use crate::CognitiveContextSnapshot;

const MAX_RECEIPTS: usize = 1024;
const CONTEXT_LEASE: Duration = Duration::from_secs(1);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct Profiles {
    retrieval: Option<Digest32>,
    ranker: Option<Digest32>,
}

#[derive(Clone)]
struct Entry {
    request_binding: Digest32,
    response_binding: Digest32,
    profiles: Profiles,
    lifecycle_generation: u64,
    issued: Instant,
    expires: Instant,
}

impl Entry {
    fn binding(&self, plan: Digest32) -> Digest32 {
        let mut bytes = b"hepta.agentd.context-plan-lease.v1\0".to_vec();
        bytes.extend_from_slice(plan.as_array());
        bytes.extend_from_slice(self.request_binding.as_array());
        bytes.extend_from_slice(self.response_binding.as_array());
        bytes.extend_from_slice(&self.lifecycle_generation.to_be_bytes());
        for profile in [self.profiles.retrieval, self.profiles.ranker] {
            match profile {
                Some(digest) => {
                    bytes.push(1);
                    bytes.extend_from_slice(digest.as_array());
                }
                None => bytes.push(0),
            }
        }
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Default)]
pub(super) struct ContextPlanReceipts {
    entries: Mutex<BTreeMap<Digest32, Entry>>,
}

impl ContextPlanReceipts {
    fn publish(&self, plan: Digest32, entry: Entry, now: Instant) -> Result<(), AgentdError> {
        if now < entry.issued || now >= entry.expires {
            return Err(closed("context plan expired before publication"));
        }
        let mut entries = self.entries.lock().map_err(|_| closed("context receipt lock"))?;
        entries.retain(|_, existing| now < existing.expires);
        // Never replace an existing plan identity with another request or extend
        // an existing lease on replay, even when both responses have equal text.
        if let Some(existing) = entries.get(&plan) {
            return if existing.binding(plan) == entry.binding(plan) {
                Ok(())
            } else {
                Err(closed("context plan identity conflicts with an issued request"))
            };
        }
        if entries.len() >= MAX_RECEIPTS {
            return Err(closed("context receipt capacity exhausted"));
        }
        entries.insert(plan, entry);
        Ok(())
    }

    fn require(
        &self,
        plan: Digest32,
        response_binding: Digest32,
        profiles: Profiles,
        generation: u64,
        now: Instant,
    ) -> Result<Digest32, AgentdError> {
        let entries = self.entries.lock().map_err(|_| closed("context receipt lock"))?;
        let entry = entries.get(&plan).ok_or_else(|| closed("context plan was not issued by this host"))?;
        if now < entry.issued
            || now >= entry.expires
            || entry.response_binding != response_binding
            || entry.profiles != profiles
            || entry.lifecycle_generation != generation
        {
            return Err(closed("context receipt, generation, profile or monotonic lease changed"));
        }
        Ok(entry.binding(plan))
    }

    pub(super) async fn response(
        &self,
        state: &AgentdState,
        request_id: u64,
        spawn_generation: u64,
        method: AgentdMethod,
    ) -> Result<AgentdResponse, AgentdError> {
        if spawn_generation != state.identity().spawn_generation {
            return Err(closed("context request belongs to another process generation"));
        }
        match &method {
            AgentdMethod::CognitiveContext { query, limit } => {
                if query.is_empty() || query.len() > 2048 || !(1..=4).contains(limit) {
                    return Err(closed("context request outside bounded profile"));
                }
                let issued = Instant::now();
                let expires = issued.checked_add(CONTEXT_LEASE)
                    .ok_or_else(|| closed("monotonic context lease overflow"))?;
                let generation = state.current_generation()?;
                let before = current_profiles(state).await?;
                let mut request = b"hepta.agentd.context-plan-request.v1\0".to_vec();
                request.extend_from_slice(
                    Digest32::of_bytes(state.identity().agent_id.as_str().as_bytes()).as_array(),
                );
                request.extend_from_slice(&spawn_generation.to_be_bytes());
                request.extend_from_slice(&request_id.to_be_bytes());
                request.extend_from_slice(Digest32::of_bytes(query.as_bytes()).as_array());
                request.extend_from_slice(&limit.to_be_bytes());
                let request_binding = Digest32::of_bytes(&request);
                let response = state.response(request_id, spawn_generation, method).await?;
                if let AgentdPayload::CognitiveContext(snapshot) = &response.payload {
                    if state.current_generation()? != generation
                        || response.current_generation != generation
                        || current_profiles(state).await? != before
                    {
                        return Err(closed("context owner profile changed during read"));
                    }
                    let plan = plan_identity(snapshot)?;
                    self.publish(plan, Entry {
                        request_binding,
                        response_binding: snapshot_binding(snapshot)?,
                        profiles: before,
                        lifecycle_generation: generation,
                        issued,
                        expires,
                    }, Instant::now())?;
                }
                Ok(response)
            }
            AgentdMethod::CognitiveContextRevalidate {
                snapshot_digest,
                read_digest,
                omitted_records,
                items,
                plan,
            } => {
                let snapshot = CognitiveContextSnapshot {
                    snapshot_digest: snapshot_digest.clone(),
                    read_digest: read_digest.clone(),
                    omitted_records: *omitted_records,
                    items: items.clone(),
                    plan: plan.clone(),
                };
                let plan = plan_identity(&snapshot)?;
                let response_binding = snapshot_binding(&snapshot)?;
                let generation = state.current_generation()?;
                let before = current_profiles(state).await?;
                let binding = self.require(plan, response_binding, before, generation, Instant::now())?;
                // Canonical owner-cut, item revision/content and ranker checks
                // remain mandatory. Host receipt membership never replaces them.
                let response = state.response(request_id, spawn_generation, method).await?;
                let after = current_profiles(state).await?;
                let final_binding = self.require(
                    plan, response_binding, after, state.current_generation()?, Instant::now(),
                )?;
                if binding != final_binding {
                    return Err(closed("context receipt changed during final-use revalidation"));
                }
                Ok(response)
            }
            _ => state.response(request_id, spawn_generation, method).await,
        }
    }
}

async fn current_profiles(state: &AgentdState) -> Result<Profiles, AgentdError> {
    let retrieval = state.cognitive_retrieval_context.get().cloned();
    let ranker = state.cognitive_ranker.get().cloned();
    let owner = state.identity().agent_id.clone();
    let generation = state.identity().spawn_generation;
    tokio::task::spawn_blocking(move || {
        let retrieval = retrieval.map(|current| {
            let context = current.current(&owner, generation).map_err(|_| closed("retrieval profile unavailable"))?;
            context.validate().map_err(|_| closed("retrieval profile invalid"))?;
            Ok::<_, AgentdError>(context.binding_digest())
        }).transpose()?;
        let ranker = ranker.map(|ranker| {
            ranker.current_policy_digest(&owner, generation)
                .map_err(|_| closed("ranker policy unavailable"))
        }).transpose()?;
        Ok(Profiles { retrieval, ranker })
    }).await.map_err(|_| closed("context profile worker failed"))?
}

fn plan_identity(snapshot: &CognitiveContextSnapshot) -> Result<Digest32, AgentdError> {
    let plan = snapshot.plan.as_ref().ok_or_else(|| closed("context plan receipt missing"))?;
    let digest: Digest32 = plan.plan_receipt_digest.parse()
        .map_err(|_| closed("context plan receipt encoding"))?;
    if digest.is_zero() || digest.to_string() != plan.plan_receipt_digest {
        return Err(closed("noncanonical context plan receipt"));
    }
    Ok(digest)
}

fn snapshot_binding(snapshot: &CognitiveContextSnapshot) -> Result<Digest32, AgentdError> {
    if snapshot.items.len() > 4 {
        return Err(closed("context receipt item bound"));
    }
    let bytes = serde_json::to_vec(snapshot)?;
    if bytes.len() > crate::MAX_COGNITIVE_CONTEXT_BYTES {
        return Err(closed("context receipt byte bound"));
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn closed(message: &str) -> AgentdError {
    AgentdError::Protocol(message.to_string())
}

#[cfg(test)]
#[path = "control_context_receipts_tests.rs"]
mod tests;
