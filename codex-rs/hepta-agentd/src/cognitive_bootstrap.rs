//! Complete, opt-in bootstrap of the ordinary cognitive ranking consumer.
//!
//! Inputs are original owner material, never a deserialized opaque selection
//! receipt. The original dataset, canonical product selection and independent
//! selector factories run at the installation clock before the published
//! source is loaded. Product qualification must already come from the original
//! runner and its real durable evidence sink.

use std::fs::File;
use std::sync::Arc;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_bellman_operator::TabularPayloadPinV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_intelligence_eval::IndependentEvaluationBundleV1;
use codex_hepta_intelligence_eval::LongitudinalTimeEvidenceV1;
use codex_hepta_intelligence_eval::MetricRoleContractV2;
use codex_hepta_intelligence_eval::ProductQualificationReceiptV1;
use codex_hepta_intelligence_eval::SelfEvolutionSelectionPolicyV1;
use codex_hepta_intelligence_eval::SelfEvolutionSelectionRequestV1;
use codex_hepta_intelligence_eval::SignedEvaluationEvidenceV1;
use codex_hepta_intelligence_eval::admit_self_evolution_selection_v1;
use codex_hepta_intelligence_eval::prepare_self_evolution_product_selection_v1;
use codex_hepta_learning_artifacts::LearningArtifactManifestV2;
use codex_hepta_learning_artifacts::PinnedCandidateSpec;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::LedgerSnapshot;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;

use crate::CurrentCognitiveRegistry;
use crate::PinnedCognitiveRanker;

/// Fully supplied host inputs for one independently selected published model.
/// Artifact CURRENT uses Unix seconds; longitudinal evidence uses Unix micros.
/// Supplying these inputs does not train, publish, or select a replacement.
pub struct EvaluatedCognitiveBootstrapV1 {
    pub snapshot: File,
    pub payload: File,
    pub selected: PinnedCandidateSpec,
    pub model_pin: TabularPayloadPinV1,
    pub source_manifest: LearningArtifactManifestV2,
    pub current: Arc<dyn CurrentCognitiveRegistry>,
    pub policy: SelfEvolutionSelectionPolicyV1,
    pub selection_request: SelfEvolutionSelectionRequestV1,
    pub evaluation_bundle: IndependentEvaluationBundleV1,
    pub metric_roles: Vec<MetricRoleContractV2>,
    pub evaluation_evidence: SignedEvaluationEvidenceV1,
    pub longitudinal_time: LongitudinalTimeEvidenceV1,
    pub dataset_receipt: DatasetSnapshotReceiptV3,
    pub ledger_snapshot: LedgerSnapshot,
    pub verifier: LearningEvidenceVerifierV1,
    pub selector_evidence: SignedLearningEvidenceV1,
    pub product_qualification: ProductQualificationReceiptV1,
    pub product_candidate_binding_evidence: SignedLearningEvidenceV1,
}

pub(crate) fn load_evaluated_cognitive_bootstrap_v1(
    owner: AgentId,
    generation: u64,
    input: EvaluatedCognitiveBootstrapV1,
) -> Result<Arc<PinnedCognitiveRanker>, String> {
    let now = u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|error| error.to_string())?
            .as_micros(),
    )
    .map_err(|error| error.to_string())?;
    let prepared = prepare_self_evolution_product_selection_v1(
        &input.product_qualification,
        &input.product_candidate_binding_evidence,
        &input.policy,
        input.selection_request,
        input.evaluation_bundle,
        input.metric_roles,
        &input.evaluation_evidence,
        &input.longitudinal_time,
        &input.dataset_receipt,
        &input.ledger_snapshot,
        &input.verifier,
        now,
    )
    .map_err(|error| error.to_string())?;
    let selection =
        admit_self_evolution_selection_v1(prepared, &input.selector_evidence, &input.verifier, now)
            .map_err(|error| error.to_string())?;
    PinnedCognitiveRanker::load_evaluated_published(
        owner,
        generation,
        input.snapshot,
        input.payload,
        input.selected,
        input.model_pin,
        input.source_manifest,
        input.current,
        &selection,
    )
    .map(Arc::new)
}
