use super::*;

use std::collections::BTreeSet;

use crate::FactorSource;
use crate::PromptFactor;
use crate::TestMust;

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
        semantic_purpose: "verify before mutating".to_owned(),
        authority_class: "registered_prompt_factor".to_owned(),
        eligible_objective_dimensions: vec![id("dimension:truth")],
        content_digest: digest("factor"),
        source: FactorSource::GovernedInternal,
        lifecycle: Lifecycle::Draft,
    }
}

fn model_tuple() -> PromptModelTupleV2 {
    PromptModelTupleV2 {
        model_id: id("model:hepta-test"),
        model_version: "2026-09-18".to_owned(),
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
        context_profile_digest: digest("context-profile"),
        locale_id: id("locale:en-US"),
    }
}

fn binding() -> PromptRealizationBindingV2 {
    PromptRealizationBindingV2 {
        realization_id: id("realization:1"),
        factor_id: id("factor:1"),
        model_id: id("model:hepta-test"),
        model_version: "2026-09-18".to_owned(),
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
        context_profile_digest: digest("context-profile"),
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

fn compatible_set() -> CompatibleRealizationSetV2 {
    let mut registry = admitted_registry();
    registry
        .register_realization_v2(binding())
        .must("register realization");
    let tuple = model_tuple();
    let vector = digest("generation-vector");
    let snapshot = registry.snapshot_v2(vector, &tuple).must("snapshot");
    registry
        .read_compatible_v2(
            &snapshot,
            vector,
            &tuple,
            /*now_unix_ms*/ 10,
            vec![id("factor:1")],
            /*maximum_results*/ 8,
        )
        .must("compatible set")
}

#[test]
fn every_state_change_allocates_one_revision_and_identical_retry_does_not() {
    let mut registry = registry();
    let initial = registry.revision();
    let inserted = registry
        .register_factor(factor())
        .unwrap_or_else(|error| panic!("register factor: {error}"));
    assert_eq!(inserted.revision, initial.next().must("next revision"));

    let unchanged = registry
        .register_factor(factor())
        .unwrap_or_else(|error| panic!("idempotent factor: {error}"));
    assert_eq!(unchanged.revision, inserted.revision);

    let admitted = registry
        .admit_factor(&id("factor:1"), &id("reviewer:1"), digest("evidence"))
        .unwrap_or_else(|error| panic!("admit factor: {error}"));
    assert_eq!(
        admitted.revision,
        inserted.revision.next().must("next revision")
    );

    let realized = registry
        .register_realization_v2(binding())
        .unwrap_or_else(|error| panic!("register realization: {error}"));
    assert_eq!(
        realized.revision,
        admitted.revision.next().must("next revision")
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
        .read_compatible_v2(&snapshot, vector, &tuple, 10, vec![id("factor:1")], 8)
        .unwrap_or_else(|error| panic!("compatible read: {error}"));
    assert_eq!(compatible.bindings, vec![binding()]);
    compatible
        .validate()
        .unwrap_or_else(|error| panic!("valid compatible set: {error}"));

    let mut wrong_tuple = tuple;
    wrong_tuple.tokenizer_digest = digest("wrong-tokenizer");
    assert_eq!(
        registry.read_compatible_v2(&snapshot, vector, &wrong_tuple, 10, Vec::new(), 8,),
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
        registry.read_compatible_v2(&old_snapshot, vector, &tuple, 10, Vec::new(), 8,),
        Err(PromptRegistryV2Error::SnapshotStale)
    );
    assert!(
        !registry
            .realization(&id("realization:1"))
            .must("realization remains interpretable")
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
        registry.read_compatible_v2(&snapshot, vector, &tuple, 100, vec![id("factor:1")], 8,),
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

#[test]
fn required_factors_are_not_starved_by_other_roles() {
    let mut registry = admitted_registry();
    let mut factor_two = factor();
    factor_two.factor_id = id("factor:2");
    factor_two.proposer_id = id("proposer:2");
    factor_two.content_digest = digest("factor:2");
    registry
        .register_factor(factor_two)
        .unwrap_or_else(|error| panic!("register factor two: {error}"));
    registry
        .admit_factor(&id("factor:2"), &id("reviewer:2"), digest("evidence:2"))
        .unwrap_or_else(|error| panic!("admit factor two: {error}"));

    let first = binding();
    registry
        .register_realization_v2(first)
        .unwrap_or_else(|error| panic!("first realization: {error}"));

    let mut schema = binding();
    schema.realization_id = id("realization:2");
    schema.role = PromptRoleV2::ToolSchemaFragment;
    schema.payload_digest = digest("payload:2");
    registry
        .register_realization_v2(schema)
        .unwrap_or_else(|error| panic!("second role: {error}"));

    let mut other = binding();
    other.realization_id = id("realization:3");
    other.factor_id = id("factor:2");
    other.payload_digest = digest("payload:3");
    registry
        .register_realization_v2(other)
        .unwrap_or_else(|error| panic!("other factor: {error}"));

    let tuple = model_tuple();
    let vector = digest("generation-vector");
    let snapshot = registry
        .snapshot_v2(vector, &tuple)
        .unwrap_or_else(|error| panic!("snapshot: {error}"));
    let result = registry
        .read_compatible_v2(
            &snapshot,
            vector,
            &tuple,
            10,
            vec![id("factor:2"), id("factor:1")],
            2,
        )
        .unwrap_or_else(|error| panic!("required factors must fit: {error}"));
    assert_eq!(
        result.required_factor_ids,
        vec![id("factor:1"), id("factor:2")]
    );
    assert_eq!(
        result
            .bindings
            .iter()
            .map(|binding| binding.factor_id.clone())
            .collect::<BTreeSet<_>>(),
        BTreeSet::from([id("factor:1"), id("factor:2")])
    );
}

#[test]
fn equivalent_required_factor_order_has_one_canonical_digest() {
    let mut registry = admitted_registry();
    registry
        .register_realization_v2(binding())
        .unwrap_or_else(|error| panic!("register realization: {error}"));

    let mut factor_two = factor();
    factor_two.factor_id = id("factor:2");
    factor_two.proposer_id = id("proposer:2");
    factor_two.content_digest = digest("factor:2");
    registry
        .register_factor(factor_two)
        .unwrap_or_else(|error| panic!("register factor two: {error}"));
    registry
        .admit_factor(&id("factor:2"), &id("reviewer:2"), digest("evidence:2"))
        .unwrap_or_else(|error| panic!("admit factor two: {error}"));
    let mut second = binding();
    second.realization_id = id("realization:2");
    second.factor_id = id("factor:2");
    second.payload_digest = digest("payload:2");
    registry
        .register_realization_v2(second)
        .unwrap_or_else(|error| panic!("register second realization: {error}"));

    let tuple = model_tuple();
    let vector = digest("generation-vector");
    let snapshot = registry
        .snapshot_v2(vector, &tuple)
        .unwrap_or_else(|error| panic!("snapshot: {error}"));
    let left = registry
        .read_compatible_v2(
            &snapshot,
            vector,
            &tuple,
            10,
            vec![id("factor:1"), id("factor:2")],
            8,
        )
        .unwrap_or_else(|error| panic!("left: {error}"));
    let right = registry
        .read_compatible_v2(
            &snapshot,
            vector,
            &tuple,
            10,
            vec![id("factor:2"), id("factor:1")],
            8,
        )
        .unwrap_or_else(|error| panic!("right: {error}"));
    assert_eq!(left.set_digest, right.set_digest);
    assert_eq!(left.required_factor_ids, right.required_factor_ids);
    assert_eq!(left.bindings, right.bindings);
}

#[test]
fn active_realization_profile_requires_explicit_supersession() {
    let mut registry = admitted_registry();
    registry
        .register_realization_v2(binding())
        .unwrap_or_else(|error| panic!("register realization: {error}"));
    let mut competing = binding();
    competing.realization_id = id("realization:2");
    competing.payload_digest = digest("payload:2");
    assert_eq!(
        registry.register_realization_v2(competing),
        Err(Error::RealizationProfileConflict("factor:1".to_string()))
    );
}

#[test]
fn payload_registration_supersedes_and_dereferences_exact_bytes() {
    let mut registry = admitted_registry();
    let payload = b"developer instruction v1".to_vec();
    let mut first = binding();
    first.payload_digest = Digest32::of_bytes(&payload);
    first.expires_unix_ms = None;
    registry
        .register_realization_payload_v2(first.clone(), payload, None)
        .unwrap_or_else(|error| panic!("payload register: {error}"));

    let next_payload = b"developer instruction v2".to_vec();
    let mut next = first.clone();
    next.realization_id = id("realization:2");
    next.payload_digest = Digest32::of_bytes(&next_payload);
    registry
        .register_realization_payload_v2(
            next.clone(),
            next_payload.clone(),
            Some(first.realization_id.clone()),
        )
        .unwrap_or_else(|error| panic!("supersede: {error}"));
    assert!(
        !registry
            .realization(&first.realization_id)
            .must("predecessor")
            .active
    );
    assert_eq!(
        registry.realization_predecessor(&next.realization_id),
        Some(&first.realization_id)
    );

    let tuple = model_tuple();
    let vector = digest("generation-vector");
    let snapshot = registry
        .snapshot_v2(vector, &tuple)
        .unwrap_or_else(|error| panic!("snapshot: {error}"));
    let delivery = registry
        .dereference_realization_v2(&next.realization_id, &snapshot, vector, &tuple, 10)
        .unwrap_or_else(|error| panic!("dereference: {error}"));
    assert_eq!(delivery.payload, next_payload);
    delivery
        .validate()
        .unwrap_or_else(|error| panic!("delivery validates: {error}"));
}

#[test]
fn payload_ceiling_rejects_atomically() {
    let mut registry = admitted_registry();
    let before = registry.clone();
    let payload = vec![b'x'; crate::MAX_REALIZATION_PAYLOAD_BYTES + 1];
    let mut oversized = binding();
    oversized.payload_digest = Digest32::of_bytes(&payload);
    oversized.expires_unix_ms = None;

    assert_eq!(
        registry.register_realization_payload_v2(oversized, payload, None),
        Err(Error::PayloadTooLarge)
    );
    assert_eq!(registry, before);
}

#[test]
fn compatible_set_rejects_invalid_bindings_even_with_recomputed_digest() {
    let original = compatible_set();
    let mut cases = Vec::new();
    let mut zero_tokens = original.clone();
    zero_tokens.bindings[0].token_cost = 0;
    cases.push((zero_tokens, PromptRegistryV2Error::ZeroTokenCost));
    let mut zero_payload = original.clone();
    zero_payload.bindings[0].payload_digest = Digest32::ZERO;
    cases.push((zero_payload, PromptRegistryV2Error::EmptyDigest("payload")));
    let mut oversized_version = original.clone();
    oversized_version.bindings[0].model_version = "x".repeat(257);
    cases.push((
        oversized_version,
        PromptRegistryV2Error::InvalidModelVersion,
    ));
    let mut invalid_expiry = original;
    invalid_expiry.bindings[0].expires_unix_ms = Some(0);
    cases.push((invalid_expiry, PromptRegistryV2Error::InvalidExpiry));

    for (mut set, expected_error) in cases {
        set.set_digest = set.compute_set_digest();
        assert_eq!(set.validate(), Err(expected_error));
    }
}

#[test]
fn compatible_set_binds_every_model_tuple_field() {
    let original = compatible_set();
    let mut alternatives = vec![binding(); 8];
    alternatives[0].model_id = id("model:other");
    alternatives[1].model_version = "other-version".to_owned();
    alternatives[2].model_digest = digest("other-model");
    alternatives[3].tokenizer_digest = digest("other-tokenizer");
    alternatives[4].template_digest = digest("other-template");
    alternatives[5].tool_schema_digest = digest("other-tools");
    alternatives[6].context_profile_digest = digest("other-context");
    alternatives[7].locale_id = id("locale:zh-CN");
    for alternative in alternatives {
        let mut set = original.clone();
        set.bindings = vec![alternative];
        set.set_digest = set.compute_set_digest();
        assert_eq!(
            set.validate(),
            Err(PromptRegistryV2Error::DigestMismatch("model_tuple"))
        );
    }
}

#[test]
fn compatible_set_cannot_omit_a_required_factor() {
    let mut set = compatible_set();
    set.bindings.clear();
    set.set_digest = set.compute_set_digest();
    assert_eq!(
        set.validate(),
        Err(PromptRegistryV2Error::RequiredFactorUnavailable)
    );
}

#[test]
fn compatible_set_rejects_duplicate_identity_and_active_profile() {
    let original = compatible_set();
    let mut duplicate_identity = original.clone();
    let mut second_factor = binding();
    second_factor.factor_id = id("factor:2");
    duplicate_identity.bindings.push(second_factor);
    duplicate_identity.set_digest = duplicate_identity.compute_set_digest();
    assert_eq!(
        duplicate_identity.validate(),
        Err(PromptRegistryV2Error::NonCanonicalBindings)
    );

    let mut duplicate_profile = original;
    let mut second_identity = binding();
    second_identity.realization_id = id("realization:2");
    duplicate_profile.bindings.push(second_identity);
    duplicate_profile.set_digest = duplicate_profile.compute_set_digest();
    assert_eq!(
        duplicate_profile.validate(),
        Err(PromptRegistryV2Error::NonCanonicalBindings)
    );
}

#[test]
fn required_factor_filters_are_bounded_before_selection() {
    let mut set = compatible_set();
    let required = (0..=MAX_COMPATIBLE_REALIZATIONS_V2)
        .map(|index| id(&format!("factor:{index:03}")))
        .collect::<Vec<_>>();
    set.required_factor_ids = required.clone();
    set.set_digest = set.compute_set_digest();
    assert_eq!(
        set.validate(),
        Err(PromptRegistryV2Error::ReadLimitExceeded)
    );

    let registry = admitted_registry();
    let tuple = model_tuple();
    let vector = digest("generation-vector");
    let snapshot = registry.snapshot_v2(vector, &tuple).must("snapshot");
    assert_eq!(
        registry.read_compatible_v2(
            &snapshot, vector, &tuple, /*now_unix_ms*/ 10, required,
            /*maximum_results*/ 128,
        ),
        Err(PromptRegistryV2Error::ReadLimitExceeded)
    );
}
