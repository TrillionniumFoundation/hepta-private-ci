//! Private storage DTOs. Deserializing these fields alone grants no sealed
//! preparation; only the enclosing original-journal read path may import them.

use super::*;
use codex_hepta_intelligence::{AdvisoryDecisionReceiptV1, AdvisoryDecisionV1, CanonicalBudgetV1,
    CanonicalSnapshotRequestV1, CanonicalStageTraceV1, LegalActionCandidateSetRequestV1,
    LegalActionCandidateV1, OwnerBindingV1};
use codex_hepta_types::ProbabilityQ32;
use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Payload {
    pub schema: String,
    pub request: Request,
    pub envelope: Envelope,
    pub dispatch_proposal_digest: String,
    pub run: crate::RunSnapshot,
    pub attachment: Attachment,
    pub context: Context,
    pub materials: Vec<Material>,
    pub rendered_context: Vec<serde_json::Value>,
    pub rendered_context_digest: String,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Request { run_id: String, snapshot: Snapshot, legal: Legal, budget: [u64; 8] }
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Snapshot { objective_digest: String, authority_epoch: u64, body_generation: u64,
    configuration_digest: String, revocation_frontier_digest: String, owners: Vec<Owner> }
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Owner { owner_id: String, generation: u64, implementation_digest: String, key_digest: String, key_epoch: u64 }
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Legal { candidate_set_id: String, state_digest: String, generator_id: String, grammar_digest: String,
    candidates: Vec<(String, String)>, support_floor_ppm: u32 }
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Envelope { run_id: String, snapshot_digest: String, objective_digest: String,
    candidate_set_digest: String, utility_receipt_digest: String, neural_receipt_digest: String,
    prompt_receipt_digest: String, decision: Decision, context_receipt_digest: String,
    context_binding_digest: String, evaluation_receipt_digest: String, trace_digest: String,
    stage_trace: Vec<Trace>, envelope_digest: String, authority_denied: bool }
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Decision { run_id: String, candidate_set_digest: String, intuition_receipt_digest: String,
    candidate_id: String, propensity: u64, decision_digest: String, authority_denied: bool }
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Trace { stage: u8, producer: String, predecessor_digest: String, output_digest: String }
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Attachment { pub revision: u64, pub run: crate::RunSnapshot, pub context_digest: String, pub compilation_receipt_digest: String }
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Context { compilation_id: String, run_snapshot_digest: String, objective_digest: String,
    token_budget: u64, items: Vec<Item>, receipt: Receipt }
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Item { item_id: String, role: u8, content_digest: String, source_digest: String, token_count: u64, contains_secret: bool }
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Receipt { compilation_id: String, trusted_instruction_ids: Vec<String>, untrusted_evidence_ids: Vec<String>,
    omitted_ids: Vec<String>, used_tokens: u64, context_digest: String, authority_denied: bool }
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Material { item_id: String, source_digest: String, content: Vec<u8> }

#[path = "canonical_prepared_request.rs"]
mod request;
#[path = "canonical_prepared_envelope.rs"]
mod envelope;
#[path = "canonical_prepared_context.rs"]
mod context;

impl Material {
    pub(super) fn capture(value: &NativeContextMaterialV1) -> Self {
        Self { item_id: value.item_id.to_string(), source_digest: value.source_digest.to_string(), content: value.content.clone() }
    }
    pub(super) fn restore(self) -> anyhow::Result<NativeContextMaterialV1> {
        Ok(NativeContextMaterialV1 { item_id: StableId::new(self.item_id)?, source_digest: self.source_digest.parse()?, content: self.content })
    }
}
