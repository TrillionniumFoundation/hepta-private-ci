use std::collections::BTreeMap;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::OnceLock;
use std::time::Instant;

use codex_hepta_cognitive_read::MAX_ENCODED_READ_RESULT_BYTES_V2;
use codex_hepta_cognitive_read::ReadFieldV1;
use codex_hepta_cognitive_read::ReadIdsError;
use codex_hepta_cognitive_read::ReadIdsRequestV1;
use codex_hepta_cognitive_read::ReadIdsResultV1;
use codex_hepta_cognitive_store::DurableCognitiveStore as CognitiveStore;
use codex_hepta_cognitive_store::DurableCognitiveStoreError as CognitiveStoreError;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::DurableCognitiveSnapshot;
use codex_hepta_memory::RetrievalExecutionContextV1;
use codex_hepta_types::Digest32;

use super::CognitiveContextError;
use super::legacy;
use crate::CognitiveContextItem;
use crate::CognitiveContextPlan;
use crate::CognitiveContextRevalidation;
use crate::CognitiveContextSnapshot;
use crate::CurrentMemoryRetrievalContext;
use crate::PinnedCognitiveRanker;

mod helpers;
mod read;
mod verify;

pub(crate) use read::read_with_retrieval_context_and_learning;
pub(crate) use verify::revalidate_with_retrieval_context;

#[cfg(test)]
pub(crate) use read::read;
#[cfg(test)]
pub(crate) use read::read_with_retrieval_context;
#[cfg(test)]
pub(crate) use verify::revalidate;

const MAX_CONTEXT_JSON_BYTES: usize = crate::MAX_COGNITIVE_CONTEXT_BYTES;
const MAX_ISSUED_CONTEXT_SEALS: usize = 4096;
const CONTEXT_LEASE_MICROS: u64 = 1_000_000;
const CONTEXT_READ_BINDING_DOMAIN: &[u8] = b"hepta.agentd.cognitive-context-read.v1";
const CONTEXT_RECORD_SET_DOMAIN: &[u8] = b"hepta.agentd.cognitive-context-record-set.v2";
const CONTEXT_REQUEST_BINDING_DOMAIN: &[u8] =
    b"hepta.agentd.cognitive-context-request-binding.v2";
const CONTEXT_DELIVERY_SEAL_DOMAIN: &[u8] = b"hepta.agentd.cognitive-context-delivery-seal.v2";
const CONTEXT_PLAN_PREFIX: &str = "context-plan-v2";

static MONOTONIC_ORIGIN: OnceLock<Instant> = OnceLock::new();
static ISSUED_CONTEXT_SEALS: OnceLock<Mutex<BTreeMap<Digest32, IssuedContextSealV2>>> =
    OnceLock::new();

#[derive(Clone, Debug, Eq, PartialEq)]
struct IssuedContextSealV2 {
    owner: AgentId,
    body_generation: u64,
    snapshot_digest: Digest32,
    read_binding_digest: Digest32,
    evaluated_context_digest: Digest32,
    raw_plan_receipt_digest: Digest32,
    request_binding_digest: Digest32,
    retrieval_context_digest: Option<Digest32>,
    ranker_policy_digest: Option<Digest32>,
    record_set_digest: Digest32,
    visible_record_count: u16,
    issued_at_micros: u64,
    expires_at_micros: u64,
    read_allowed: bool,
    query: String,
}

impl IssuedContextSealV2 {
    fn digest(&self) -> Digest32 {
        let mut bytes = CONTEXT_DELIVERY_SEAL_DOMAIN.to_vec();
        helpers::push_bytes(&mut bytes, self.owner.as_str().as_bytes());
        bytes.extend_from_slice(&self.body_generation.to_be_bytes());
        helpers::push_digest(&mut bytes, self.snapshot_digest);
        helpers::push_digest(&mut bytes, self.read_binding_digest);
        helpers::push_digest(&mut bytes, self.evaluated_context_digest);
        helpers::push_digest(&mut bytes, self.raw_plan_receipt_digest);
        helpers::push_digest(&mut bytes, self.request_binding_digest);
        helpers::push_optional_digest(&mut bytes, self.retrieval_context_digest);
        helpers::push_optional_digest(&mut bytes, self.ranker_policy_digest);
        helpers::push_digest(&mut bytes, self.record_set_digest);
        bytes.extend_from_slice(&self.visible_record_count.to_be_bytes());
        bytes.extend_from_slice(&self.issued_at_micros.to_be_bytes());
        bytes.extend_from_slice(&self.expires_at_micros.to_be_bytes());
        bytes.push(u8::from(self.read_allowed));
        helpers::push_bytes(&mut bytes, self.query.as_bytes());
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct AuthenticatedPacketV2 {
    snapshot_digest: Digest32,
    read_binding_digest: Digest32,
    record_set_digest: Digest32,
    record_count: u16,
}

#[cfg(test)]
mod tests {
    use super::CONTEXT_PLAN_PREFIX;
    use super::helpers::encode_plan_binding;
    use super::helpers::parse_plan_binding;
    use codex_hepta_types::Digest32;

    #[test]
    fn plan_binding_round_trips_and_rejects_substitution() {
        let raw = Digest32::of_bytes(b"raw-plan");
        let seal = Digest32::of_bytes(b"seal");
        let encoded = encode_plan_binding(raw, seal);
        assert_eq!(parse_plan_binding(&encoded).expect("binding"), (raw, seal));
        assert!(parse_plan_binding(&format!("{CONTEXT_PLAN_PREFIX}:{raw}")).is_err());
        assert!(parse_plan_binding(&format!("legacy:{raw}:{seal}")).is_err());
        assert!(parse_plan_binding(&format!("{encoded}:trailing")).is_err());
    }
}
