use super::*;
use crate::ContextRole;
use crate::MandatoryContextGroup;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture identifier is valid")
}

fn item(name: &str, tokens: u64) -> ContextItem {
    ContextItem {
        item_id: id(name),
        role: ContextRole::UntrustedEvidence,
        content_digest: Digest32::of_bytes(name.as_bytes()),
        source_digest: Digest32::of_bytes(b"source"),
        token_count: tokens,
        contains_secret: false,
    }
}

fn request(items: Vec<ContextItem>) -> CompilationRequest {
    CompilationRequest {
        compilation_id: id("compile:bound"),
        run_snapshot_digest: Digest32::of_bytes(b"snapshot"),
        objective_digest: Digest32::of_bytes(b"objective"),
        token_budget: 8,
        items,
    }
}

#[test]
fn omitted_content_is_bound_without_changing_legacy_compilation() {
    let first_request = request(vec![item("evidence:a", 8), item("evidence:tail", 8)]);
    let mut second_request = first_request.clone();
    second_request.items[1].content_digest = Digest32::of_bytes(b"changed tail");

    let first_legacy = compile(first_request.clone()).expect("legacy compilation succeeds");
    let second_legacy = compile(second_request.clone()).expect("legacy compilation succeeds");
    assert_eq!(first_legacy, second_legacy);

    let first = compile_candidate_bound(first_request).expect("bound compilation succeeds");
    let second = compile_candidate_bound(second_request).expect("bound compilation succeeds");
    assert_ne!(
        first.caller_candidate_set_digest,
        second.caller_candidate_set_digest
    );
    assert_ne!(first.binding_digest, second.binding_digest);
    assert_eq!(first.compilation, first_legacy);
    assert!(!first.authority.grants_any());
    assert_eq!(
        first.caller_candidate_set_digest.to_string(),
        "5b9307710ea9a68de217592d23166b18b1fd5274c5f455094a9da27eb379397e"
    );
    assert_eq!(
        first.binding_digest.to_string(),
        "910d049f44cc7486cf701c256cd7ece067c082d47e84a5f933a453cbb83181ca"
    );
}

#[test]
fn input_permutation_has_one_candidate_binding() {
    let mut first_request = request(vec![
        item("evidence:c", 3),
        item("evidence:a", 3),
        item("evidence:b", 3),
    ]);
    let mut second_request = first_request.clone();
    second_request.items.reverse();

    let first = compile_candidate_bound(first_request.clone()).expect("first succeeds");
    let second = compile_candidate_bound(second_request).expect("second succeeds");
    assert_eq!(first, second);

    first_request.items.rotate_left(1);
    let third = compile_candidate_bound(first_request).expect("third succeeds");
    assert_eq!(first, third);
}

#[test]
fn candidate_identity_and_omitted_tail_are_in_the_binding() {
    let first = compile_candidate_bound(request(vec![
        item("evidence:head", 8),
        item("evidence:tail-a", 8),
    ]))
    .expect("first succeeds");
    let second = compile_candidate_bound(request(vec![
        item("evidence:head", 8),
        item("evidence:tail-b", 8),
    ]))
    .expect("second succeeds");

    assert_eq!(
        first.compilation.context_digest,
        second.compilation.context_digest
    );
    assert_ne!(
        first.compilation.omitted_ids,
        second.compilation.omitted_ids
    );
    assert_ne!(
        first.caller_candidate_set_digest,
        second.caller_candidate_set_digest
    );
    assert_ne!(first.binding_digest, second.binding_digest);
}

#[test]
fn mandatory_requirements_remain_bound_and_authority_free() {
    let required = item("evidence:required", 8);
    let optional = item("evidence:optional", 8);
    let request = request(vec![optional, required.clone()]);
    let requirements = CompilationRequirementsV1 {
        run_snapshot_digest: request.run_snapshot_digest,
        objective_digest: request.objective_digest,
        mandatory_groups: vec![MandatoryContextGroup {
            group_id: id("required-provenance"),
            items: vec![required],
        }],
    };
    let receipt = compile_candidate_bound_with_requirements(request, requirements)
        .expect("required compilation succeeds");

    assert_eq!(
        receipt.compilation.untrusted_evidence_ids,
        vec![id("evidence:required")]
    );
    assert_eq!(
        receipt.compilation.omitted_ids,
        vec![id("evidence:optional")]
    );
    assert_eq!(receipt.caller_candidate_count, 2);
    assert!(!receipt.compilation.authority.grants_any());
    assert!(!receipt.authority.grants_any());
}

#[test]
fn legacy_validation_errors_are_preserved() {
    let invalid = request(vec![item("evidence:a", 8), item("evidence:a", 8)]);
    assert_eq!(
        compile_candidate_bound(invalid),
        Err(Error::DuplicateItem("evidence:a".to_owned()))
    );
}
