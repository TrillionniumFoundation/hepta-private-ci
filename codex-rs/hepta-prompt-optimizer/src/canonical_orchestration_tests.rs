use super::*;
use std::sync::Arc;

#[path = "canonical_fixture.rs"]
mod fixture;

#[test]
fn orchestrator_reaches_verified_selection_with_real_owner_evidence() {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("temporary: {error}"));
    let (registry, tuple, _, _, _) = fixture::admitted_registry(
        &temporary.path().join("registry"), b"Verify evidence before acting.",
    );
    let registry = registry.registry().unwrap_or_else(|error| panic!("registry: {error}"));
    let enumeration = PromptEnumerationRequestV1 {
        set_id: fixture::id("set:orchestration"), objective_digest: fixture::digest("objective"),
        state_digest: fixture::digest("state"), generation_vector_digest: fixture::digest("generation-vector"),
        model_tuple: tuple, now_unix_ms: 100, required_factor_ids: vec![fixture::id("factor:verify")],
        maximum_candidates: 16, selection_grammar_digest: fixture::digest("grammar"),
    };
    let candidates = enumerate_factors_v1(registry, enumeration.clone())
        .unwrap_or_else(|error| panic!("enumerate: {error}"));
    let source = fixture::FixtureSource::for_candidates(&candidates);
    let (control, _, _) = fixture::select(candidates, 100);
    let selection = PromptPortfolioRequestV1 {
        portfolio_id: fixture::id("portfolio:orchestration"), graph_query_id: fixture::id("query:orchestration"),
        token_budget: 128, maximum_selected_factors: 16, requested_valid_until_unix_ms: 20_000,
    };
    let source: Arc<dyn PromptEvidenceSourceV1> = source;
    let selected = build_verified_prompt_portfolio_v1(registry, enumeration.clone(), selection.clone(), Arc::clone(&source), 100)
        .unwrap_or_else(|error| panic!("orchestration: {error}"));
    assert_eq!(selected.selected, control.selected);
    assert_eq!(selected.receipt.expected_utility_q32, control.receipt.expected_utility_q32);
    assert_eq!(selected.receipt.total_token_upper_bound, control.receipt.total_token_upper_bound);
    assert_eq!(selected.receipt.valid_until_unix_ms, 9_000);
    assert_eq!(selected.audit().audit_digest, selected.audit().compute_digest());
    assert!(!selected.receipt.authority.grants_any());
    assert_eq!(build_verified_prompt_portfolio_v1(registry, enumeration, selection, source, 101),
        Err(CanonicalPromptError::Integrity("enumeration clock")));
}
