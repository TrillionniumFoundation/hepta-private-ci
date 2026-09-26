//! Native consumer tests obtain actual sealed qualifications through the runner.
use super::AgentdEvaluationBindingV1;
use super::digest;
use super::id;
use codex_hepta_intelligence_eval::ProductQualificationReceiptV1;
use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use ed25519_dalek::SigningKey;
#[allow(dead_code)]
#[path = "../../hepta-intelligence-eval/tests/support/product_qualification_fixture.rs"]
mod product;

pub(super) fn qualify(
    binding: &AgentdEvaluationBindingV1,
    trust: &ActivatedLearningTrustV1,
    generator: AuthenticatedPrincipalV1,
    evaluator: AuthenticatedPrincipalV1,
    keys: (&SigningKey, &SigningKey),
    now: u64,
) -> ProductQualificationReceiptV1 {
    product::qualify(
        product::QualificationCase {
            objective: binding.objective_digest,
            dataset: digest("dataset"),
            candidate: binding.selected_candidate_id.clone(),
            baseline: id("baseline"),
            snapshot_ids: vec![id("snapshot-1")],
        },
        trust.verifier(),
        generator,
        evaluator,
        keys,
        now,
    )
    .receipt
}
