//! Signature handoff and admission through the existing selection owner. Its
//! opaque tokens stay in process; only original canonical materials are emitted.
use std::path::Path;

use anyhow::{Result, ensure};
use codex_hepta_intelligence_eval as eval;
use codex_hepta_learning_ledger as ledger;
use serde_json::{Value, json};

use crate::cognitive_process_bootstrap::{FileAccess, open_bounded_regular};
use crate::cognitive_process_evaluation::{SelfEvolutionSelectionRequestV1Raw, SelfEvolutionSelectionPolicyV1Raw};
use crate::cognitive_process_evidence::{DatasetSnapshotReceiptV3Raw, SignedLearningEvidenceV1Raw};
use crate::cognitive_qualification_wire::*;

pub(super) struct SelectionContextV1<'a> {
    pub qualification: &'a eval::ProductQualificationReceiptV1,
    pub policy: &'a eval::SelfEvolutionSelectionPolicyV1,
    pub bundle: &'a eval::IndependentEvaluationBundleV1,
    pub metric_roles: &'a [eval::MetricRoleContractV2],
    pub evidence: &'a eval::SignedEvaluationEvidenceV1,
    pub timing: &'a eval::LongitudinalTimeEvidenceV1,
    pub verifier: &'a ledger::LearningEvidenceVerifierV1,
    pub now: u64,
    pub forbidden_roots: [&'a Path; 3],
}

pub(super) fn select(context: SelectionContextV1<'_>, stage: CognitiveQualificationSelectionStageV1) -> Result<Value> {
    if let CognitiveQualificationSelectionStageV1::CandidateBindingStatement { request } = stage {
        let request = request.into();
        let payload = eval::product_candidate_binding_payload_v1(&request, context.qualification)?;
        return Ok(json!({"state":"awaiting_candidate_binding_signature", "authority_granted":false,
            "selection_request":SelfEvolutionSelectionRequestV1Raw::from(request),
            "candidate_binding_signing_payload_hex":super::cognitive_qualification::hex(&payload)}));
    }
    let (inputs, selector) = match stage {
        CognitiveQualificationSelectionStageV1::CandidateBindingStatement { .. } => unreachable!("binding statement returned above"),
        CognitiveQualificationSelectionStageV1::SelectorStatement { inputs } => (inputs, None),
        CognitiveQualificationSelectionStageV1::Admit { inputs, selector } => (inputs, Some(selector)),
    };
    for root in context.forbidden_roots {
        ensure!(!inputs.ledger.path.starts_with(root), "selection ledger owner must remain outside Agent-owned paths");
    }
    ensure!(inputs.ledger.anchor_sequence > 0, "selection requires an independently retained ledger anchor");
    let file = open_bounded_regular(&inputs.ledger.path, 8 * 1024 * 1024, FileAccess::Recover)?;
    let ledger = ledger::DurableLedger::recover(file, inputs.ledger.binding.0, inputs.ledger.max_records,
        ledger::LedgerRecovery::Acknowledged(ledger::LedgerAnchor {
            sequence: inputs.ledger.anchor_sequence, chain_digest: inputs.ledger.anchor_chain_digest.0,
        }))?;
    let snapshot = ledger.snapshot()?;
    let dataset: ledger::DatasetSnapshotReceiptV3 = inputs.dataset_receipt.into();
    let request: eval::SelfEvolutionSelectionRequestV1 = inputs.request.into();
    let binding: ledger::SignedLearningEvidenceV1 = inputs.candidate_binding.into();
    let prepared = eval::prepare_self_evolution_product_selection_v1(
        context.qualification, &binding, context.policy, request.clone(), context.bundle.clone(),
        context.metric_roles.to_vec(), context.evidence, context.timing, &dataset, &snapshot, context.verifier, context.now,
    )?;
    let payload = eval::selection_signing_payload_v1(prepared.receipt())?;
    let mut output = json!({"state":"awaiting_selector_signature", "authority_granted":false,
        "selector_signing_payload_hex":super::cognitive_qualification::hex(&payload),
        "materials":{"policy":SelfEvolutionSelectionPolicyV1Raw::from(context.policy.clone()),
            "selection_request":SelfEvolutionSelectionRequestV1Raw::from(request),
            "product_candidate_binding_evidence":SignedLearningEvidenceV1Raw::from(binding),
            "dataset_receipt":DatasetSnapshotReceiptV3Raw::from(dataset),
            "ledger":{"path":inputs.ledger.path,"binding":inputs.ledger.binding.0.to_string(),
                "max_records":inputs.ledger.max_records,"anchor_sequence":inputs.ledger.anchor_sequence,
                "anchor_chain_digest":inputs.ledger.anchor_chain_digest.0.to_string()}}});
    if let Some(selector) = selector {
        let selector = selector.into();
        let selected = eval::admit_self_evolution_selection_v1(prepared, &selector, context.verifier, context.now)?;
        output["state"] = json!("selected");
        output["selection_sha256"] = json!(selected.selection_digest().to_string());
        output["materials"]["selector_evidence"] = serde_json::to_value(SignedLearningEvidenceV1Raw::from(selector))?;
    }
    Ok(output)
}
