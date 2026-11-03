use super::*;

#[test]
fn reads_original_partition_and_digest_without_reselecting_context() {
    let id = |value| StableId::new(value).expect("fixture id");
    let digest = |value: &str| Digest32::of_bytes(value.as_bytes());
    let request = CompilationRequest { compilation_id: id("compiled"), run_snapshot_digest: digest("snapshot"),
        objective_digest: digest("objective"), token_budget: 4, items: vec![
            ContextItem { item_id: id("evidence.omitted"), role: ContextRole::UntrustedEvidence,
                content_digest: digest("large"), source_digest: digest("source.large"), token_count: 10, contains_secret: false },
            ContextItem { item_id: id("instructions"), role: ContextRole::TrustedInstruction,
                content_digest: digest("instructions"), source_digest: digest("source.instructions"), token_count: 2, contains_secret: false },
            ContextItem { item_id: id("evidence.included"), role: ContextRole::UntrustedEvidence,
                content_digest: digest("small"), source_digest: digest("source.small"), token_count: 2, contains_secret: false },
        ] };
    let receipt = compile(request.clone()).expect("original compilation");
    validate_retained_compilation_v1(&request, &receipt).expect("exact original receipt");
    let mut changed = receipt.clone(); changed.used_tokens -= 1;
    assert!(validate_retained_compilation_v1(&request, &changed).is_err());
    let mut changed = receipt.clone(); changed.omitted_ids.push(id("instructions"));
    assert!(validate_retained_compilation_v1(&request, &changed).is_err());
    let mut changed = request; changed.items[1].role = ContextRole::UntrustedEvidence;
    assert!(validate_retained_compilation_v1(&changed, &receipt).is_err());
}
