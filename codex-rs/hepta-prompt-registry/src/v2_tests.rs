use super::*;

use crate::FactorSource;
use crate::PromptFactor;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn registry() -> PromptRegistry {
    PromptRegistry::new(64).unwrap_or_else(|error| panic!("valid registry: {error}"))
}

fn factor() -> PromptFactor {
    PromptFactor {
        factor_id: id("factor:1"),
        proposer_id: id("proposer:1"),
        semantic_version: id("v1"),
        content_digest: digest("factor"),
        source: FactorSource::GovernedInternal,
        lifecycle: Lifecycle::Draft,
    }
}

fn model_tuple() -> PromptModelTupleV2 {
    PromptModelTupleV2 {
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
        locale_id: id("locale:en-US"),
    }
}

fn binding() -> PromptRealizationBindingV2 {
    PromptRealizationBindingV2 {
        realization_id: id("realization:1"),
        factor_id: id("factor:1"),
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
        locale_id: id("locale:en-US"),
        role: PromptRoleV2::DeveloperInstruction,
        payload_digest: digest("payload"),
        token_cost: 32,
        expires_unix_ms: Some(100),
    }
}

fn admitted_registry() -> PromptRegistry {
    let mut registry = registry();
    registry
        .register_factor(factor())
        .unwrap_or_else(|error| panic!("register factor: {error}"));
    registry
        .admit_factor(&id("factor:1"), &id("reviewer:1"), digest("evidence"))
        .unwrap_or_else(|error| panic!("admit factor: {error}"));
    registry
}

#[test]
fn every_state_change_allocates_one_revision_and_identical_retry_does_not() {
    let mut registry = registry();
    let initial = registry.revision();
    let inserted = registry
        .register_factor(factor())
        .unwrap_or_else(|error| panic!("register factor: {error}"));
    assert_eq!(inserted.revision, initial.next().expect("next revision"));

    let unchanged = registry
        .register_factor(factor())
        .unwrap_or_else(|error| panic!("idempotent factor: {error}"));
    assert_eq!(unchanged.revision, inserted.revision);

    let admitted = registry
        .admit_factor(&id("factor:1"), &id("reviewer:1"), digest("evidence"))
        .unwrap_or_else(|error| panic!("admit factor: {error}"));
    assert_eq!(
        admitted.revision,
        inserted.revision.next().expect("next revision")
    );

    let realized = registry
        .register_realization_v2(binding())
        .unwrap_or_else(|error| panic!("register realization: {error}"));
    assert_eq!(
        realized.revision,
        admitted.revision.next().expect("next revision")
    );
    let unchanged = registry
        .register_realization_v2(binding())
        .unwrap_or_else(|error| panic!("idempotent realization: {error}"));
    assert_eq!(unchanged.revision, realized.revision);
}

#[test]
fn exact_model_tuple_and_frozen_snapshot_gate_delivery() {
    let mut registry = admitted_registry();
    registry
        .register_realization_v2(binding())
        .unwrap_or_else(|error| panic!("register realization: {error}"));
    let tuple = model_tuple();
    let vector = digest("generation-vector");
    let snapshot = registry
        .snapshot_v2(vector, &tuple)
        .unwrap_or_else(|error| panic!("snapshot: {error}"));
    let compatible = registry
        .read_compatible_v2(
            &snapshot,
            vector,
            &tuple,
            10,
            vec![id("factor:1")],
            8,
        )
        .unwrap_or_else(|error| panic!("compatible read: {error}"));
    assert_eq!(compatible.bindings, vec![binding()]);
    compatible
        .validate()
        .unwrap_or_else(|error| panic!("valid compatible set: {error}"));

    let mut wrong_tuple = tuple.clone();
    wrong_tuple.tokenizer_digest = digest("wrong-tokenizer");
    assert_eq!(
        registry.read_compatible_v2(
            &snapshot,
            vector,
            &wrong_tuple,
            10,
            Vec::new(),
            8,
        ),
        Err(PromptRegistryV2Error::SnapshotStale)
    );
}

#[test]
fn revocation_invalidates_old_snapshot_and_disables_realization() {
    let mut registry = admitted_registry();
    registry
        .register_realization_v2(binding())
        .unwrap_or_else(|error| panic!("register realization: {error}"));
    let tuple = model_tuple();
    let vector = digest("generation-vector");
    let old_snapshot = registry
        .snapshot_v2(vector, &tuple)
        .unwrap_or_else(|error| panic!("old snapshot: {error}"));
    registry
        .revoke_factor(&id("factor:1"))
        .unwrap_or_else(|error| panic!("revoke: {error}"));
    assert!(registry.revocation_frontier() > 0);
    assert_eq!(
        registry.read_compatible_v2(
            &old_snapshot,
            vector,
            &tuple,
            10,
            Vec::new(),
            8,
        ),
        Err(PromptRegistryV2Error::SnapshotStale)
    );
    assert!(
        !registry
            .realization(&id("realization:1"))
            .expect("realization remains interpretable")
            .active
    );
}

#[test]
fn expired_or_missing_required_realization_fails_closed() {
    let mut registry = admitted_registry();
    registry
        .register_realization_v2(binding())
        .unwrap_or_else(|error| panic!("register realization: {error}"));
    let tuple = model_tuple();
    let vector = digest("generation-vector");
    let snapshot = registry
        .snapshot_v2(vector, &tuple)
        .unwrap_or_else(|error| panic!("snapshot: {error}"));
    assert_eq!(
        registry.read_compatible_v2(
            &snapshot,
            vector,
            &tuple,
            100,
            vec![id("factor:1")],
            8,
        ),
        Err(PromptRegistryV2Error::RequiredFactorUnavailable)
    );
}

#[test]
fn untrusted_external_factor_cannot_obtain_v2_realization() {
    let mut registry = registry();
    let mut external = factor();
    external.source = FactorSource::ExternalUntrusted;
    registry
        .register_factor(external)
        .unwrap_or_else(|error| panic!("register external draft: {error}"));
    assert_eq!(
        registry.register_realization_v2(binding()),
        Err(Error::FactorNotAdmitted("factor:1".to_string()))
    );
}
