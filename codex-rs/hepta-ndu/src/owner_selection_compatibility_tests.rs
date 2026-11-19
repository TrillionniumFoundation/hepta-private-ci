use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

use super::Fixture;
use super::NduOwnerError;
use super::NduOwnerMutationV1;
use super::append_mutation;
use super::digest;
use super::fixture;
use super::must;

fn legacy_selection(label: &str, projection: codex_hepta_types::Digest32) -> NduOwnerMutationV1 {
    NduOwnerMutationV1::SelectProjection {
        identity_digest: digest(label),
        objective_digest: digest("objective"),
        subject_digest: digest("subject"),
        projection_digest: projection,
    }
}

fn commit(fixture: &mut Fixture, mutation: NduOwnerMutationV1, grant_id: &str) {
    let grant = fixture.sign(&mutation, grant_id);
    must(fixture.owner.apply_mutation(&grant, mutation));
}

#[test]
fn legacy_selection_binding_rejects_value_level_aba() {
    let mut fixture = fixture();
    commit(&mut fixture, append_mutation("legacy-a"), "append-a");
    commit(&mut fixture, append_mutation("legacy-b"), "append-b");
    let projection_a = digest("legacy-a-projection");
    let projection_b = digest("legacy-b-projection");
    commit(
        &mut fixture,
        legacy_selection("initial-a", projection_a),
        "initial-a",
    );
    let delayed = legacy_selection("delayed-b", projection_b);
    let stale = fixture.sign(&delayed, "delayed-b-before-aba");

    commit(
        &mut fixture,
        legacy_selection("transition-b", projection_b),
        "transition-b",
    );
    commit(
        &mut fixture,
        legacy_selection("transition-a", projection_a),
        "transition-a",
    );
    assert_eq!(
        must(
            fixture
                .owner
                .selected_projection_digest(digest("objective"), digest("subject"))
        ),
        Some(projection_a)
    );
    assert!(matches!(
        fixture.owner.apply_mutation(&stale, delayed.clone()),
        Err(NduOwnerError::Authority(
            codex_hepta_contracts::FinalUseError::BindingMismatch
        ))
    ));
    commit(&mut fixture, delayed, "delayed-b-fresh-binding");
    assert_eq!(
        must(
            fixture
                .owner
                .selected_projection_digest(digest("objective"), digest("subject"))
        ),
        Some(projection_b)
    );
}

#[test]
fn previously_issued_v1_selection_payload_requires_a_fresh_issuer_binding() {
    let mut fixture = fixture();
    commit(&mut fixture, append_mutation("legacy-a"), "append-a");
    let selection = legacy_selection("legacy-select-a", digest("legacy-a-projection"));
    let current = must(fixture.owner.final_use_binding(&selection));
    let mut historical = current.clone();
    // This is the unchanged original V1 preimage function, before the new
    // explicitly versioned journal-head binding performed by the owner.
    historical.payload_sha256 = *super::super::mutation_payload_digest(
        &selection,
        fixture.owner.production_policy_digest(),
    )
    .as_array();
    assert_ne!(historical.payload_sha256, current.payload_sha256);
    let old_grant = fixture.sign_binding(historical, "original-v1-selection");
    assert!(matches!(
        fixture.owner.apply_mutation(&old_grant, selection.clone()),
        Err(NduOwnerError::Authority(
            codex_hepta_contracts::FinalUseError::BindingMismatch
        ))
    ));
    commit(&mut fixture, selection, "fresh-v2-selection");
    assert_eq!(
        must(
            fixture
                .owner
                .selected_projection_digest(digest("objective"), digest("subject"))
        ),
        Some(digest("legacy-a-projection"))
    );
}
