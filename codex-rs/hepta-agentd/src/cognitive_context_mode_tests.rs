use super::*;
use crate::CognitiveRetrievalMode;
use crate::retrieval_product_mode::delivers_hnmf;
use crate::retrieval_product_mode::route;

struct Unavailable;
impl CurrentMemoryRetrievalContext for Unavailable {
    fn current(
        &self,
        _owner: &AgentId,
        _generation: u64,
    ) -> Result<RetrievalExecutionContextV1, String> {
        Err("injected unavailable or revoked provider".to_string())
    }
}

fn reader(
    owner: &AgentId,
    context: RetrievalExecutionContextV1,
) -> Arc<dyn CurrentMemoryRetrievalContext> {
    Arc::new(SwitchingContext {
        owner: owner.clone(),
        generation: 1,
        first: context.clone(),
        later: context,
        switch_after_first: false,
        calls: Arc::new(AtomicUsize::new(0)),
    })
}

#[tokio::test]
async fn shadow_executes_selection_but_preserves_actual_compatibility_delivery() {
    let (_temp, store, owner, context, first_id) = fixture(401).await;
    let calls = Arc::new(AtomicUsize::new(0));
    let provider: Arc<dyn CurrentMemoryRetrievalContext> = Arc::new(SwitchingContext {
        owner: owner.clone(),
        generation: 1,
        first: context.clone(),
        later: context,
        switch_after_first: false,
        calls: Arc::clone(&calls),
    });
    let shadow = route(CognitiveRetrievalMode::HnmfShadow, provider);
    let result = read_with_retrieval_context(&store, &owner, 1, "lemon", 4, None, Some(&shadow))
        .await
        .expect("shadow delivery");
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(result.items.len(), 2);
    assert!(result.items.iter().any(|item| item.memory_id == first_id));
    // The unused shadow owner must not become a dependency of final use.
    let unavailable = route(CognitiveRetrievalMode::HnmfShadow, Arc::new(Unavailable));
    crate::cognitive_context::revalidate_with_retrieval_context(
        &store,
        &owner,
        &result.snapshot_digest,
        &result.read_digest,
        result.omitted_records,
        &result.items,
        result.plan.as_ref(),
        None,
        1,
        Some(&unavailable),
    )
    .await
    .expect("compatibility final use after shadow provider failure");
}

#[tokio::test]
async fn shadow_provider_failure_isolated_but_required_failure_is_closed() {
    let (_temp, store, owner, _context, _) = fixture(402).await;
    let shadow = route(CognitiveRetrievalMode::HnmfShadow, Arc::new(Unavailable));
    let result = read_with_retrieval_context(&store, &owner, 1, "lemon", 4, None, Some(&shadow))
        .await
        .expect("compatibility response");
    assert_eq!(result.items.len(), 2);
    let required = route(CognitiveRetrievalMode::HnmfRequired, Arc::new(Unavailable));
    assert!(matches!(
        read_with_retrieval_context(&store, &owner, 1, "lemon", 4, None, Some(&required)).await,
        Err(CognitiveContextError::RetrievalContextUnavailable)
    ));
}

#[tokio::test]
async fn unused_shadow_generation_drift_cannot_poison_compatibility_results() {
    let (_temp, store, owner, mut context, _) = fixture(403).await;
    context.generation_vector.memory_ledger_frontier += 1;
    // Payload is now internally inconsistent and must not be used as evidence.
    let shadow = route(CognitiveRetrievalMode::HnmfShadow, reader(&owner, context));
    let result = read_with_retrieval_context(&store, &owner, 1, "lemon", 4, None, Some(&shadow))
        .await
        .expect("compatibility despite unusable shadow");
    assert_eq!(result.items.len(), 2);
}

#[tokio::test]
async fn required_to_shadow_mode_change_invalidates_previously_treated_final_use() {
    let (_temp, store, owner, context, _) = fixture(404).await;
    let provider = reader(&owner, context);
    let required = route(CognitiveRetrievalMode::HnmfRequired, Arc::clone(&provider));
    let result = read_with_retrieval_context(&store, &owner, 1, "lemon", 4, None, Some(&required))
        .await
        .expect("required response");
    assert_eq!(result.items.len(), 1);
    let shadow = route(CognitiveRetrievalMode::HnmfShadow, provider);
    assert!(
        crate::cognitive_context::revalidate_with_retrieval_context(
            &store,
            &owner,
            &result.snapshot_digest,
            &result.read_digest,
            result.omitted_records,
            &result.items,
            result.plan.as_ref(),
            None,
            1,
            Some(&shadow),
        )
        .await
        .is_err()
    );
}

#[tokio::test]
async fn canary_routes_real_owner_reads_to_stable_treatment_and_control_arms() {
    let mut treated = None;
    let mut control = None;
    for suffix in 500..1500_u16 {
        let owner = AgentId::parse(format!("00000000-0000-4000-8000-{suffix:012}")).expect("owner");
        let arm = delivers_hnmf(CognitiveRetrievalMode::HnmfCanary, &owner);
        assert_eq!(
            arm,
            delivers_hnmf(CognitiveRetrievalMode::HnmfCanary, &owner)
        );
        if arm {
            treated.get_or_insert(suffix);
        } else {
            control.get_or_insert(suffix);
        }
        if treated.is_some() && control.is_some() {
            break;
        }
    }
    for (suffix, count) in [
        (treated.expect("treatment owner"), 1),
        (control.expect("control owner"), 2),
    ] {
        let (_temp, store, owner, context, _) = fixture(suffix).await;
        let canary = route(CognitiveRetrievalMode::HnmfCanary, reader(&owner, context));
        let result =
            read_with_retrieval_context(&store, &owner, 1, "lemon", 4, None, Some(&canary))
                .await
                .expect("canary delivery");
        assert_eq!(result.items.len(), count);
    }
}

#[test]
fn all_hnmf_product_modes_require_an_explicit_host_provider() {
    assert!(!CognitiveRetrievalMode::Compatibility.requires_current_context());
    for mode in [
        CognitiveRetrievalMode::HnmfShadow,
        CognitiveRetrievalMode::HnmfCanary,
        CognitiveRetrievalMode::HnmfRequired,
    ] {
        assert!(mode.requires_current_context());
    }
}
