//! Final-use integrity wrapper for the canonical Agentd cognitive-context path.
//!
//! `cognitive_context_core.rs` retains the established store, ranking and
//! learning-ledger behavior.  This layer derives an authenticated control plan
//! from exact records, binds request/retrieval/ranker identity, and keeps a
//! bounded process-generation lease so a substituted plan receipt or expired
//! response fails closed before final use.

use std::collections::BTreeMap;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::OnceLock;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_cognitive_store::DurableCognitiveStore as CognitiveStore;
use codex_hepta_cognitive_store::DurableCognitiveStoreError as CognitiveStoreError;
use codex_hepta_contracts::AgentId;
use codex_hepta_control_plane::AuthenticatedContextRecordV1;
use codex_hepta_control_plane::AuthenticatedObservedContextV1;
use codex_hepta_control_plane::plan_authenticated_observed_context;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::CognitiveContextItem;
use crate::CognitiveContextPlan;
use crate::CognitiveContextRevalidation;
use crate::CognitiveContextSnapshot;
use crate::CognitiveRetrievalLearningSink;
use crate::CurrentMemoryRetrievalContext;
use crate::PinnedCognitiveRanker;

#[path = "cognitive_context_core.rs"]
mod core;

pub(crate) use core::CognitiveContextError;

const CONTEXT_PLAN_LEASE_CAPACITY: usize = 1024;
const CONTEXT_PLAN_LEASE_DURATION: Duration = Duration::from_secs(1);
const REQUEST_BINDING_DOMAIN: &[u8] = b"hepta.agentd.context-request-binding.v2\0";
const PLAN_LEASE_KEY_DOMAIN: &[u8] = b"hepta.agentd.context-plan-lease-key.v1\0";

#[derive(Clone, Debug)]
struct ContextPlanLeaseV1 {
    wire_receipt_digest: String,
    authenticated_receipt_digest: Digest32,
    request_binding_digest: Digest32,
    retrieval_context_digest: Option<Digest32>,
    ranker_policy_digest: Option<Digest32>,
    expires_at: Instant,
}

static CONTEXT_PLAN_LEASES: OnceLock<Mutex<BTreeMap<String, ContextPlanLeaseV1>>> = OnceLock::new();
static MONOTONIC_ORIGIN: OnceLock<Instant> = OnceLock::new();

#[cfg(test)]
pub(crate) async fn read(
    store: &CognitiveStore,
    owner: &AgentId,
    body_generation: u64,
    query: &str,
    limit: u16,
    ranker: Option<&Arc<PinnedCognitiveRanker>>,
) -> Result<CognitiveContextSnapshot, CognitiveContextError> {
    read_with_retrieval_context_and_learning(
        store,
        owner,
        body_generation,
        query,
        limit,
        ranker,
        None,
        None,
        None,
    )
    .await
}

#[cfg(test)]
pub(crate) async fn read_with_retrieval_context(
    store: &CognitiveStore,
    owner: &AgentId,
    body_generation: u64,
    query: &str,
    limit: u16,
    ranker: Option<&Arc<PinnedCognitiveRanker>>,
    current_retrieval: Option<&Arc<dyn CurrentMemoryRetrievalContext>>,
) -> Result<CognitiveContextSnapshot, CognitiveContextError> {
    read_with_retrieval_context_and_learning(
        store,
        owner,
        body_generation,
        query,
        limit,
        ranker,
        current_retrieval,
        None,
        None,
    )
    .await
}

#[allow(clippy::too_many_arguments)]
pub(crate) async fn read_with_retrieval_context_and_learning(
    store: &CognitiveStore,
    owner: &AgentId,
    body_generation: u64,
    query: &str,
    limit: u16,
    ranker: Option<&Arc<PinnedCognitiveRanker>>,
    current_retrieval: Option<&Arc<dyn CurrentMemoryRetrievalContext>>,
    learning_sink: Option<&Arc<CognitiveRetrievalLearningSink>>,
    request_id: Option<u64>,
) -> Result<CognitiveContextSnapshot, CognitiveContextError> {
    let response = core::read_with_retrieval_context_and_learning(
        store,
        owner,
        body_generation,
        query,
        limit,
        ranker,
        current_retrieval,
        learning_sink,
        request_id,
    )
    .await?;

    let retrieval_context_digest =
        current_retrieval_digest(current_retrieval, owner, body_generation).await?;
    let ranker_policy_digest = current_ranker_policy_digest(ranker, owner, body_generation).await?;
    let request_binding_digest = request_binding_digest(
        owner,
        body_generation,
        query,
        limit,
        request_id,
        &response.snapshot_digest,
        &response.read_digest,
        retrieval_context_digest,
        ranker_policy_digest,
    );

    let plan = response.plan.as_ref().ok_or_else(|| {
        conflict("canonical cognitive context response is missing its control plan")
    })?;
    let records = authenticated_records(&response.items)?;
    let mut pre_plan = response.clone();
    pre_plan.plan = None;
    let encoded_context = serde_json::to_vec(&pre_plan)
        .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
    let observed_at_micros = monotonic_now_micros()?;
    let expires_at_micros = observed_at_micros
        .checked_add(1_000_000)
        .ok_or_else(|| conflict("context plan monotonic expiry overflow"))?;
    let authenticated = plan_authenticated_observed_context(AuthenticatedObservedContextV1 {
        owner_id: StableId::new(owner.as_str())
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?,
        body_generation: Generation::new(body_generation)
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?,
        source_snapshot_digest: response.snapshot_digest.parse().map_err(|error| {
            CognitiveStoreError::Invalid(format!("invalid context snapshot digest: {error}"))
        })?,
        read_digest: response.read_digest.parse().map_err(|error| {
            CognitiveStoreError::Invalid(format!("invalid context read digest: {error}"))
        })?,
        request_binding_digest,
        records: &records,
        encoded_context: &encoded_context,
        maximum_context_bytes: crate::MAX_COGNITIVE_CONTEXT_BYTES as u32,
        observed_at_micros,
        expires_at_micros,
    })
    .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))?;

    if authenticated.read_allowed != plan.read_allowed
        || authenticated.context_digest.to_string() != plan.evaluated_context_digest
    {
        return Err(conflict(
            "authenticated context plan disagrees with the published compatibility plan",
        ));
    }

    register_plan_lease(
        owner,
        body_generation,
        &response,
        ContextPlanLeaseV1 {
            wire_receipt_digest: plan.plan_receipt_digest.clone(),
            authenticated_receipt_digest: authenticated.evaluation.plan.receipt_digest(),
            request_binding_digest,
            retrieval_context_digest,
            ranker_policy_digest,
            expires_at: Instant::now()
                .checked_add(CONTEXT_PLAN_LEASE_DURATION)
                .ok_or_else(|| conflict("context plan lease expiry overflow"))?,
        },
    )?;
    Ok(response)
}

#[cfg(test)]
pub(crate) async fn revalidate(
    store: &CognitiveStore,
    owner: &AgentId,
    snapshot_digest: &str,
    read_digest: &str,
    omitted_records: u64,
    items: &[CognitiveContextItem],
    plan: Option<&CognitiveContextPlan>,
    ranker: Option<&Arc<PinnedCognitiveRanker>>,
) -> Result<CognitiveContextRevalidation, CognitiveContextError> {
    revalidate_with_retrieval_context(
        store,
        owner,
        snapshot_digest,
        read_digest,
        omitted_records,
        items,
        plan,
        ranker,
        1,
        None,
    )
    .await
}

#[allow(clippy::too_many_arguments)]
pub(crate) async fn revalidate_with_retrieval_context(
    store: &CognitiveStore,
    owner: &AgentId,
    snapshot_digest: &str,
    read_digest: &str,
    omitted_records: u64,
    items: &[CognitiveContextItem],
    plan: Option<&CognitiveContextPlan>,
    ranker: Option<&Arc<PinnedCognitiveRanker>>,
    body_generation: u64,
    current_retrieval: Option<&Arc<dyn CurrentMemoryRetrievalContext>>,
) -> Result<CognitiveContextRevalidation, CognitiveContextError> {
    let plan = plan.ok_or_else(|| conflict("cognitive context final use requires a plan"))?;
    let retrieval_context_digest =
        current_retrieval_digest(current_retrieval, owner, body_generation).await?;
    let ranker_policy_digest = current_ranker_policy_digest(ranker, owner, body_generation).await?;
    validate_plan_lease(
        owner,
        body_generation,
        snapshot_digest,
        read_digest,
        omitted_records,
        items,
        plan,
        retrieval_context_digest,
        ranker_policy_digest,
    )?;
    core::revalidate_with_retrieval_context(
        store,
        owner,
        snapshot_digest,
        read_digest,
        omitted_records,
        items,
        Some(plan),
        ranker,
        body_generation,
        current_retrieval,
    )
    .await
}

fn authenticated_records(
    items: &[CognitiveContextItem],
) -> Result<Vec<AuthenticatedContextRecordV1>, CognitiveContextError> {
    items
        .iter()
        .map(|item| {
            Ok(AuthenticatedContextRecordV1 {
                record_id: StableId::new(item.memory_id.as_str())
                    .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?,
                revision: item.revision,
                content_digest: item.content_sha256.parse().map_err(|error| {
                    CognitiveStoreError::Invalid(format!(
                        "invalid cognitive content digest: {error}"
                    ))
                })?,
            })
        })
        .collect()
}

#[allow(clippy::too_many_arguments)]
fn request_binding_digest(
    owner: &AgentId,
    body_generation: u64,
    query: &str,
    limit: u16,
    request_id: Option<u64>,
    snapshot_digest: &str,
    read_digest: &str,
    retrieval_context_digest: Option<Digest32>,
    ranker_policy_digest: Option<Digest32>,
) -> Digest32 {
    let mut bytes = REQUEST_BINDING_DOMAIN.to_vec();
    push_bytes(&mut bytes, owner.as_str().as_bytes());
    bytes.extend_from_slice(&body_generation.to_be_bytes());
    push_bytes(&mut bytes, query.as_bytes());
    bytes.extend_from_slice(&limit.to_be_bytes());
    match request_id {
        Some(request_id) => {
            bytes.push(1);
            bytes.extend_from_slice(&request_id.to_be_bytes());
        }
        None => bytes.push(0),
    }
    push_bytes(&mut bytes, snapshot_digest.as_bytes());
    push_bytes(&mut bytes, read_digest.as_bytes());
    push_optional_digest(&mut bytes, retrieval_context_digest);
    push_optional_digest(&mut bytes, ranker_policy_digest);
    Digest32::of_bytes(&bytes)
}

fn plan_lease_key(
    owner: &AgentId,
    body_generation: u64,
    snapshot_digest: &str,
    read_digest: &str,
    omitted_records: u64,
    items: &[CognitiveContextItem],
    plan: &CognitiveContextPlan,
) -> String {
    let mut bytes = PLAN_LEASE_KEY_DOMAIN.to_vec();
    push_bytes(&mut bytes, owner.as_str().as_bytes());
    bytes.extend_from_slice(&body_generation.to_be_bytes());
    push_bytes(&mut bytes, snapshot_digest.as_bytes());
    push_bytes(&mut bytes, read_digest.as_bytes());
    bytes.extend_from_slice(&omitted_records.to_be_bytes());
    push_bytes(&mut bytes, plan.evaluated_context_digest.as_bytes());
    bytes.push(u8::from(plan.read_allowed));
    bytes.extend_from_slice(&(items.len() as u64).to_be_bytes());
    for item in items {
        push_bytes(&mut bytes, item.memory_id.as_bytes());
        bytes.extend_from_slice(&item.revision.to_be_bytes());
        push_bytes(&mut bytes, item.content_sha256.as_bytes());
    }
    Digest32::of_bytes(&bytes).to_string()
}

fn register_plan_lease(
    owner: &AgentId,
    body_generation: u64,
    response: &CognitiveContextSnapshot,
    lease: ContextPlanLeaseV1,
) -> Result<(), CognitiveContextError> {
    if lease.authenticated_receipt_digest.is_zero() || lease.request_binding_digest.is_zero() {
        return Err(conflict(
            "authenticated context plan lease contains an empty digest",
        ));
    }
    let plan = response.plan.as_ref().ok_or_else(|| {
        conflict("canonical cognitive context response is missing its control plan")
    })?;
    let key = plan_lease_key(
        owner,
        body_generation,
        &response.snapshot_digest,
        &response.read_digest,
        response.omitted_records,
        &response.items,
        plan,
    );
    let now = Instant::now();
    let mut leases = CONTEXT_PLAN_LEASES
        .get_or_init(|| Mutex::new(BTreeMap::new()))
        .lock()
        .map_err(|_| conflict("context plan lease registry lock poisoned"))?;
    leases.retain(|_, value| value.expires_at > now);
    if leases.len() >= CONTEXT_PLAN_LEASE_CAPACITY {
        if let Some(oldest) = leases
            .iter()
            .min_by_key(|(_, value)| value.expires_at)
            .map(|(key, _)| key.clone())
        {
            leases.remove(&oldest);
        }
    }
    leases.insert(key, lease);
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn validate_plan_lease(
    owner: &AgentId,
    body_generation: u64,
    snapshot_digest: &str,
    read_digest: &str,
    omitted_records: u64,
    items: &[CognitiveContextItem],
    plan: &CognitiveContextPlan,
    retrieval_context_digest: Option<Digest32>,
    ranker_policy_digest: Option<Digest32>,
) -> Result<(), CognitiveContextError> {
    let key = plan_lease_key(
        owner,
        body_generation,
        snapshot_digest,
        read_digest,
        omitted_records,
        items,
        plan,
    );
    let now = Instant::now();
    let leases = CONTEXT_PLAN_LEASES
        .get_or_init(|| Mutex::new(BTreeMap::new()))
        .lock()
        .map_err(|_| conflict("context plan lease registry lock poisoned"))?;
    let lease = leases
        .get(&key)
        .ok_or_else(|| conflict("context plan is unknown to this Agent generation"))?;
    if lease.expires_at <= now {
        return Err(conflict("context plan monotonic lease expired"));
    }
    if lease.wire_receipt_digest != plan.plan_receipt_digest {
        return Err(conflict("context plan receipt changed before final use"));
    }
    if lease.retrieval_context_digest != retrieval_context_digest {
        return Err(conflict(
            "context retrieval profile changed before final use",
        ));
    }
    if lease.ranker_policy_digest != ranker_policy_digest {
        return Err(conflict("context ranker policy changed before final use"));
    }
    if lease.authenticated_receipt_digest.is_zero() || lease.request_binding_digest.is_zero() {
        return Err(conflict(
            "context plan lease lost its authenticated binding",
        ));
    }
    Ok(())
}

async fn current_retrieval_digest(
    current: Option<&Arc<dyn CurrentMemoryRetrievalContext>>,
    owner: &AgentId,
    body_generation: u64,
) -> Result<Option<Digest32>, CognitiveContextError> {
    let Some(current) = current else {
        return Ok(None);
    };
    let current = Arc::clone(current);
    let owner = owner.clone();
    let context = tokio::task::spawn_blocking(move || current.current(&owner, body_generation))
        .await
        .map_err(|_| CognitiveContextError::RetrievalContextUnavailable)?
        .map_err(|_| CognitiveContextError::RetrievalContextUnavailable)?;
    context
        .validate()
        .map_err(|_| CognitiveContextError::RetrievalContextUnavailable)?;
    Ok(Some(context.binding_digest()))
}

async fn current_ranker_policy_digest(
    ranker: Option<&Arc<PinnedCognitiveRanker>>,
    owner: &AgentId,
    body_generation: u64,
) -> Result<Option<Digest32>, CognitiveContextError> {
    let Some(ranker) = ranker else {
        return Ok(None);
    };
    let ranker = Arc::clone(ranker);
    let owner = owner.clone();
    let observation = tokio::task::spawn_blocking(move || {
        let mut no_items = Vec::new();
        ranker.rank(
            &owner,
            body_generation,
            "control-runtime-policy-revalidation",
            &mut no_items,
        )
    })
    .await
    .map_err(|_| CognitiveContextError::RankerUnavailable)?
    .map_err(|_| CognitiveContextError::RankerUnavailable)?;
    Ok(Some(observation.policy_digest))
}

fn monotonic_now_micros() -> Result<u64, CognitiveContextError> {
    let micros = MONOTONIC_ORIGIN
        .get_or_init(Instant::now)
        .elapsed()
        .as_micros();
    u64::try_from(micros)
        .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()).into())
}

fn push_bytes(bytes: &mut Vec<u8>, value: &[u8]) {
    bytes.extend_from_slice(&u64::try_from(value.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(value);
}

fn push_optional_digest(bytes: &mut Vec<u8>, value: Option<Digest32>) {
    match value {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(value.as_array());
        }
        None => bytes.push(0),
    }
}

fn conflict(message: &str) -> CognitiveContextError {
    CognitiveStoreError::Conflict(message.to_string()).into()
}

#[cfg(test)]
mod integrity_tests {
    use super::*;

    fn owner() -> AgentId {
        AgentId::parse("00000000-0000-4000-8000-000000000199").unwrap()
    }

    fn plan(receipt: &str) -> CognitiveContextPlan {
        CognitiveContextPlan {
            evaluated_context_digest: Digest32::of_bytes(b"context").to_string(),
            plan_receipt_digest: receipt.to_string(),
            read_allowed: true,
        }
    }

    #[test]
    fn substituted_plan_receipt_is_rejected_by_generation_lease() {
        let owner = owner();
        let original = plan(&Digest32::of_bytes(b"receipt").to_string());
        let response = CognitiveContextSnapshot {
            snapshot_digest: Digest32::of_bytes(b"snapshot").to_string(),
            read_digest: Digest32::of_bytes(b"read").to_string(),
            omitted_records: 0,
            items: vec![],
            plan: Some(original.clone()),
        };
        register_plan_lease(
            &owner,
            1,
            &response,
            ContextPlanLeaseV1 {
                wire_receipt_digest: original.plan_receipt_digest.clone(),
                authenticated_receipt_digest: Digest32::of_bytes(b"authenticated"),
                request_binding_digest: Digest32::of_bytes(b"request"),
                retrieval_context_digest: None,
                ranker_policy_digest: None,
                expires_at: Instant::now() + Duration::from_secs(1),
            },
        )
        .unwrap();
        let mut substituted = original;
        substituted.plan_receipt_digest = Digest32::of_bytes(b"substituted").to_string();
        assert!(
            validate_plan_lease(
                &owner,
                1,
                &response.snapshot_digest,
                &response.read_digest,
                0,
                &[],
                &substituted,
                None,
                None,
            )
            .is_err()
        );
    }
}
