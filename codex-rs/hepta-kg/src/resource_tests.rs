use super::*;
use crate::KnowledgeProjectionInputV2;
use crate::build_complete_generation;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use std::sync::Arc;
use std::time::Duration;

fn generation(number: u64) -> KnowledgeGenerationV2 {
    let Ok(generation) = Generation::new(number) else {
        panic!("test generation must be valid");
    };
    let result = build_complete_generation(
        generation,
        KnowledgeProjectionInputV2 {
            source_snapshot_digest: Digest32::of_bytes(format!("snapshot:{number}").as_bytes()),
            generation_vector_digest: Digest32::of_bytes(format!("vector:{number}").as_bytes()),
            graph_profile_digest: Digest32::of_bytes(b"profile"),
            complete_source_cut: true,
            nodes: Vec::new(),
            edges: Vec::new(),
        },
    );
    let Ok(value) = result else {
        panic!("test generation must build");
    };
    value
}

fn stable_id(value: &str) -> StableId {
    let Ok(value) = StableId::new(value) else {
        panic!("test identifier must be stable");
    };
    value
}

#[test]
fn physical_limits_reject_bytes_independently_of_cardinality() {
    let generation = generation(1);
    let usage = measure_generation_v2(&generation);
    let result = validate_generation_physical_limits_v2(
        &generation,
        KnowledgePhysicalLimitsV2 {
            maximum_generation_bytes: usage.canonical_bytes.saturating_sub(1),
            ..KnowledgePhysicalLimitsV2::default()
        },
    );
    let Err(error) = result else {
        panic!("byte budget must be enforced");
    };
    assert_eq!(
        error.code,
        KnowledgeResourceErrorCodeV2::GenerationBytesExceeded
    );
}

#[test]
fn cancellation_and_deadline_have_distinct_codes() {
    let cancellation = KnowledgeCancellationV2::default();
    let guard = KnowledgeOperationGuardV2::unbounded(cancellation.clone());
    cancellation.cancel();
    let Err(cancelled) = guard.checkpoint() else {
        panic!("cancelled operation must fail");
    };
    assert_eq!(cancelled.code, KnowledgeResourceErrorCodeV2::Cancelled);

    let deadline =
        KnowledgeOperationGuardV2::with_timeout(Duration::ZERO, KnowledgeCancellationV2::default());
    let Err(expired) = deadline.checkpoint() else {
        panic!("expired operation must fail");
    };
    assert_eq!(expired.code, KnowledgeResourceErrorCodeV2::DeadlineExceeded);
}

#[test]
fn publication_limiter_is_global_and_tenant_bounded() {
    let limiter = KnowledgePublicationLimiterV2::new(2, 1);
    let tenant_a = stable_id("tenant:a");
    let tenant_b = stable_id("tenant:b");
    let Ok(permit_a) = limiter.try_acquire(&tenant_a) else {
        panic!("first permit must be admitted");
    };
    let Err(tenant_error) = limiter.try_acquire(&tenant_a) else {
        panic!("tenant limit must reject a second permit");
    };
    assert_eq!(
        tenant_error.code,
        KnowledgeResourceErrorCodeV2::TenantPublicationConcurrencyExceeded
    );
    let Ok(permit_b) = limiter.try_acquire(&tenant_b) else {
        panic!("second tenant must be admitted");
    };
    drop(permit_a);
    drop(permit_b);
    assert!(limiter.try_acquire(&tenant_a).is_ok());
}

#[test]
fn generation_cache_reuses_digest_bound_index() {
    let cache = KnowledgeGenerationCacheV2::new(
        2,
        MAX_KNOWLEDGE_GENERATION_BYTES_V2,
        KnowledgePhysicalLimitsV2::default(),
    );
    let Ok(first) = cache.get_or_insert(generation(1)) else {
        panic!("first cache view must build");
    };
    let Ok(second) = cache.get_or_insert(generation(1)) else {
        panic!("same cache view must resolve");
    };
    assert!(Arc::ptr_eq(&first, &second));
    assert_eq!(cache.len(), Ok(1));
}
