//! One explicitly owned Agentd process-generation context-plan registry.
//!
//! This registry contains digests, not context text or credentials. Its leases
//! intentionally do not survive process restart. It authenticates prior local
//! issuance, not permission to perform effects. The serving path still checks
//! the cognitive owner, ranker and lifecycle immediately before final use.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_cognitive_read::ReadIdsResultV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_control_plane::ObservedContextV1;
use codex_hepta_control_plane::plan_observed_context;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::CognitiveContextPlan;
use crate::CognitiveContextSnapshot;

use super::CognitiveContextError;

const MAX_LIVE_CONTEXT_PLANS: usize = 256;
const CONTEXT_PLAN_TTL: Duration = Duration::from_secs(1);
const REQUEST_DOMAIN: &[u8] = b"hepta.agentd.context-plan-request.v1\0";

type RequestKey = (String, u64, u64);

pub(super) struct ContextPlanInput<'a> {
    pub owner: &'a AgentId,
    pub body_generation: u64,
    pub request_id: u64,
    pub query: &'a str,
    pub requested_limit: u16,
    pub selected_read: &'a ReadIdsResultV1,
    pub selected_read_binding: Digest32,
    pub response: &'a CognitiveContextSnapshot,
    pub retrieval_context_digest: Option<Digest32>,
    pub ranker_policy_digest: Option<Digest32>,
}

#[derive(Clone, Debug)]
struct IssuedPlan {
    request: RequestKey,
    request_binding: Digest32,
    final_context_digest: Digest32,
    retrieval_context_digest: Option<Digest32>,
    plan: CognitiveContextPlan,
    expires: Instant,
}

#[derive(Debug)]
pub(crate) struct ContextPlanningHostV1 {
    started: Instant,
    issued: BTreeMap<Digest32, IssuedPlan>,
    requests: BTreeMap<RequestKey, Digest32>,
}

impl Default for ContextPlanningHostV1 {
    fn default() -> Self {
        Self {
            started: Instant::now(),
            issued: BTreeMap::new(),
            requests: BTreeMap::new(),
        }
    }
}

impl ContextPlanningHostV1 {
    pub(super) fn plan(
        &mut self,
        input: ContextPlanInput<'_>,
    ) -> Result<CognitiveContextPlan, CognitiveContextError> {
        let now = Instant::now();
        self.prune(now);
        let count = validate_selected_read(&input)?;
        let encoded = encode_without_plan(input.response)?;
        let request_binding = request_binding(&input, Digest32::of_bytes(&encoded))?;
        let request = (
            input.owner.as_str().to_string(),
            input.body_generation,
            input.request_id,
        );
        if let Some(receipt) = self.requests.get(&request) {
            let existing = self.issued.get(receipt).ok_or_else(|| unavailable("plan registry conflict"))?;
            if existing.request_binding != request_binding {
                return Err(unavailable("request identity reused with different context semantics"));
            }
            return Ok(existing.plan.clone());
        }
        if self.issued.len() >= MAX_LIVE_CONTEXT_PLANS {
            return Err(unavailable("context plan lease capacity exhausted"));
        }
        let expires = now.checked_add(CONTEXT_PLAN_TTL)
            .ok_or_else(|| unavailable("monotonic context lease overflow"))?;
        let observed_at_micros = u64::try_from(now.duration_since(self.started).as_micros())
            .map_err(|_| unavailable("monotonic context clock overflow"))?;
        let expires_at_micros = observed_at_micros.checked_add(1_000_000)
            .ok_or_else(|| unavailable("monotonic context lease overflow"))?;
        let observed = plan_observed_context(ObservedContextV1 {
            owner_id: StableId::new(input.owner.as_str())
                .map_err(|_| unavailable("invalid context owner"))?,
            body_generation: Generation::new(input.body_generation)
                .map_err(|_| unavailable("invalid context generation"))?,
            source_snapshot_digest: input.selected_read.snapshot_digest(),
            // This support digest binds the canonical selected receipt plus the
            // request, query, retrieval policy and observed ranker policy.
            read_digest: request_binding,
            verified_item_count: count,
            encoded_context: &encoded,
            maximum_context_bytes: crate::MAX_COGNITIVE_CONTEXT_BYTES as u32,
            observed_at_micros,
            expires_at_micros,
        }).map_err(|_| unavailable("authenticated context planning failed"))?;
        let plan = CognitiveContextPlan {
            evaluated_context_digest: observed.context_digest.to_string(),
            plan_receipt_digest: observed.evaluation.plan.receipt_digest().to_string(),
            read_allowed: observed.read_allowed,
        };
        let mut final_response = CognitiveContextSnapshot {
            snapshot_digest: input.response.snapshot_digest.clone(),
            read_digest: input.response.read_digest.clone(),
            omitted_records: input.response.omitted_records,
            items: input.response.items.clone(),
            plan: None,
        };
        if !plan.read_allowed {
            final_response.items.clear();
        }
        let final_context_digest = Digest32::of_bytes(&encode_without_plan(&final_response)?);
        let receipt = observed.evaluation.plan.receipt_digest();
        if self.issued.contains_key(&receipt) {
            return Err(unavailable("context plan receipt identity conflict"));
        }
        self.issued.insert(receipt, IssuedPlan {
            request: request.clone(),
            request_binding,
            final_context_digest,
            retrieval_context_digest: input.retrieval_context_digest,
            plan: plan.clone(),
            expires,
        });
        self.requests.insert(request, receipt);
        Ok(plan)
    }

    pub(super) fn revalidate(
        &mut self,
        owner: &AgentId,
        body_generation: u64,
        response: &CognitiveContextSnapshot,
        retrieval_context_digest: Option<Digest32>,
    ) -> Result<(), CognitiveContextError> {
        let now = Instant::now();
        self.prune(now);
        let plan = response.plan.as_ref().ok_or_else(|| unavailable("missing context plan"))?;
        let receipt: Digest32 = plan.plan_receipt_digest.parse()
            .map_err(|_| unavailable("invalid context plan receipt"))?;
        if receipt.is_zero() {
            return Err(unavailable("empty context plan receipt"));
        }
        let issued = self.issued.get(&receipt)
            .ok_or_else(|| unavailable("context plan was not issued by this live generation or expired"))?;
        if issued.request.0 != owner.as_str()
            || issued.request.1 != body_generation
            || issued.expires <= now
            || issued.retrieval_context_digest != retrieval_context_digest
            || issued.plan.evaluated_context_digest != plan.evaluated_context_digest
            || issued.plan.plan_receipt_digest != plan.plan_receipt_digest
            || issued.plan.read_allowed != plan.read_allowed
            || issued.final_context_digest != Digest32::of_bytes(&encode_without_plan(response)?)
        {
            return Err(unavailable("context plan binding changed before final use"));
        }
        Ok(())
    }

    fn prune(&mut self, now: Instant) {
        self.issued.retain(|_, entry| entry.expires > now);
        self.requests.retain(|_, receipt| self.issued.contains_key(receipt));
    }
}

fn validate_selected_read(input: &ContextPlanInput<'_>) -> Result<u32, CognitiveContextError> {
    if input.query.is_empty() || input.query.len() > 2048
        || !(1..=4).contains(&input.requested_limit)
        || input.response.plan.is_some()
        || input.response.items.len() > usize::from(input.requested_limit)
        || input.response.snapshot_digest != input.selected_read.snapshot_digest().to_string()
        || input.response.read_digest != input.selected_read_binding.to_string()
        || !input.selected_read.missing_ids().is_empty()
        || input.selected_read.records().len() != input.response.items.len()
    {
        return Err(unavailable("context is not the exact canonical selected read"));
    }
    let mut identities = BTreeSet::new();
    for item in &input.response.items {
        if !identities.insert((&item.memory_id, item.revision)) {
            return Err(unavailable("duplicate selected context identity"));
        }
        let expected: Digest32 = item.content_sha256.parse()
            .map_err(|_| unavailable("invalid selected content digest"))?;
        if Digest32::of_bytes(item.content.as_bytes()) != expected {
            return Err(unavailable("selected context content changed"));
        }
        let present = input.selected_read.records().iter().any(|record| {
            record.record_id.as_str() == item.memory_id
                && record.revision.get() == item.revision
                && record.is_live()
                && record.content_digest == Some(expected)
        });
        if !present {
            return Err(unavailable("context record is absent from the canonical owner receipt"));
        }
    }
    // Derive the utility count exclusively from the sealed exact-ID owner
    // result after checking one-to-one correspondence, not a host scalar.
    u32::try_from(input.selected_read.records().len())
        .map_err(|_| unavailable("selected context count overflow"))
}

fn request_binding(
    input: &ContextPlanInput<'_>,
    context_digest: Digest32,
) -> Result<Digest32, CognitiveContextError> {
    let mut bytes = REQUEST_DOMAIN.to_vec();
    let owner = input.owner.as_str().as_bytes();
    let length = u32::try_from(owner.len()).map_err(|_| unavailable("owner identity too large"))?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(owner);
    bytes.extend_from_slice(&input.body_generation.to_be_bytes());
    bytes.extend_from_slice(&input.request_id.to_be_bytes());
    bytes.extend_from_slice(Digest32::of_bytes(input.query.as_bytes()).as_array());
    bytes.extend_from_slice(&input.requested_limit.to_be_bytes());
    bytes.extend_from_slice(input.selected_read.snapshot_digest().as_array());
    bytes.extend_from_slice(input.selected_read.receipt_digest().as_array());
    bytes.extend_from_slice(input.selected_read_binding.as_array());
    bytes.extend_from_slice(context_digest.as_array());
    bytes.extend_from_slice(Digest32::of_bytes(b"hepta.agentd.context-retrieval-profile.v1").as_array());
    for optional in [input.retrieval_context_digest, input.ranker_policy_digest] {
        match optional {
            Some(digest) => {
                if digest.is_zero() {
                    return Err(unavailable("empty selected context policy digest"));
                }
                bytes.push(1);
                bytes.extend_from_slice(digest.as_array());
            }
            None => bytes.push(0),
        }
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn encode_without_plan(response: &CognitiveContextSnapshot) -> Result<Vec<u8>, CognitiveContextError> {
    let canonical = CognitiveContextSnapshot {
        snapshot_digest: response.snapshot_digest.clone(),
        read_digest: response.read_digest.clone(),
        omitted_records: response.omitted_records,
        items: response.items.clone(),
        plan: None,
    };
    let encoded = serde_json::to_vec(&canonical)
        .map_err(|_| unavailable("context canonical encoding failed"))?;
    if encoded.len() > crate::MAX_COGNITIVE_CONTEXT_BYTES {
        return Err(unavailable("canonical context exceeds the host response budget"));
    }
    Ok(encoded)
}

fn unavailable(reason: &str) -> CognitiveContextError {
    CognitiveContextError::ReadUnavailable(reason.to_string())
}
