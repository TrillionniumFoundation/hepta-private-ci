use std::collections::BTreeSet;

use super::*;

use crate::FactorSource;
use crate::Lifecycle;
use crate::PromptRegistry;
use crate::test_support::TestAuthority;
use crate::test_support::admit;
use crate::test_support::digest;
use crate::test_support::factor_with_id;
use crate::test_support::id;
use crate::test_support::registry;

fn model_tuple() -> PromptModelTupleV2 {
    PromptModelTupleV2 {
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
        context_profile_digest: digest("context-profile"),
        locale_id: id("locale:en-US"),
    }
}

fn payload(value: &str) -> Vec<u8> {
    value.as_bytes().to_vec()
}

fn binding_for(
    realization_id: &str,
    factor_id: &str,
    role: PromptRoleV2,
    payload_value: &str,
) -> PromptRealizationBindingV2 {
    PromptRealizationBindingV2 {
        realization_id: id(realization_id),
        factor_id: id(factor_id),
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
        context_profile_digest: digest("context-profile"),
        locale_id: id("locale:en-US"),
        role,
        payload_digest: Digest32::of_bytes(payload_value.as_bytes()),
        token_cost: 32,
        expires_unix_ms: Some(100),
        predecessor_realization_id: None,
    }
}

fn admitted_registry() -> (PromptRegistry, TestAuthority) {
    let mut registry = registry();
    registry
        .register_factor(factor_with_id("factor:1", FactorSource::GovernedInternal))
        .expect("register factor");
    let authority = TestAuthority::new();
    admit(&mut registry, &authority, "factor:1", 21);
    (registry, authority)
}

#[test]
fn every_state_change_allocates_one_revision_and_identical_retry_does_not() {
    let mut registry = registry();
    let initial = registry.revision();
    let inserted = registry
        .register_factor(factor_with_id("factor:1", FactorSource::GovernedInternal))
        .expect("register factor");
    assert_eq!(inserted.revision, initial.next().expect("next revision"));
    let unchanged = registry
        .register_factor(factor_with_id("factor:1", FactorSource::GovernedInternal))
        .expect("idempotent factor");
    assert_eq!(unchanged.revision, inserted.revision);

    let authority = TestAuthority::new();
    let admitted = admit(&mut registry, &authority, "factor:1", 22);
    assert_eq!(
        admitted.revision,
        inserted.revision.next().expect("next revision")
    );

    let binding = binding_for(
        "realization:1",
        "factor:1",
        PromptRoleV2::DeveloperInstruction,
        "payload-one",
    );
    let realized = registry
        .register_realization_v2(binding.clone(), payload("payload-one"))
        .expect("register realization");
    assert_eq!(
        realized.revision,
        admitted.revision.next().expect("next revision")
    );
    let unchanged = registry
        .register_realization_v2(binding, payload("payload-one"))
        .expect("idempotent realization");
    assert_eq!(unchanged.revision, realized.revision);
}

#[test]
fn exact_model_tuple_context_profile_and_frozen_snapshot_gate_delivery() {
    let (mut registry, _authority) = admitted_registry();
    registry
        .register_realization_v2(
            binding_for(
                "realization:1",
                "factor:1",
                PromptRoleV2::DeveloperInstruction,
                "payload-one",
            ),
            payload("payload-one"),
        )
        .expect("register realization");
    let tuple = model_tuple();
    let vector = digest("generation-vector");
    let snapshot = registry.snapshot_v2(vector, &tuple).expect("snapshot");
    let compatible = registry
        .read_compatible_v2(&snapshot, vector, &tuple, 10, vec![id("factor:1")], 8)
        .expect("compatible read");
    assert_eq!(compatible.bindings.len(), 1);

    let mut wrong_tuple = tuple.clone();
    wrong_tuple.context_profile_digest = digest("wrong-context-profile");
    assert_eq!(
        registry.read_compatible_v2(&snapshot, vector, &wrong_tuple, 10, Vec::new(), 8),
        Err(PromptRegistryV2Error::SnapshotStale)
    );
    let wrong_snapshot = registry
        .snapshot_v2(vector, &wrong_tuple)
        .expect("wrong profile snapshot");
    assert_eq!(
        registry.read_compatible_v2(
            &wrong_snapshot,
            vector,
            &wrong_tuple,
            10,
            vec![id("factor:1")],
            8,
        ),
        Err(PromptRegistryV2Error::RequiredFactorUnavailable)
    );
}

#[test]
fn revocation_invalidates_old_snapshot_disables_realization_and_payload() {
    let (mut registry, _authority) = admitted_registry();
    registry
        .register_realization_v2(
            binding_for(
                "realization:1",
                "factor:1",
                PromptRoleV2::DeveloperInstruction,
                "payload-one",
            ),
            payload("payload-one"),
        )
        .expect("register realization");
    let tuple = model_tuple();
    let vector = digest("generation-vector");
    let old_snapshot = registry.snapshot_v2(vector, &tuple).expect("snapshot");
    registry
        .revoke_factor_with_reason(
            &id("factor:1"),
            &id("operator:1"),
            digest("revocation-reason"),
            50,
        )
        .expect("revoke");
    assert!(registry.revocation_frontier() > 0);
    assert_eq!(
        registry.factor(&id("factor:1")).expect("factor").lifecycle,
        Lifecycle::Revoked
    );
    assert_eq!(
        registry.read_compatible_v2(&old_snapshot, vector, &tuple, 10, Vec::new(), 8),
        Err(PromptRegistryV2Error::SnapshotStale)
    );
    assert!(
        !registry
            .realization(&id("realization:1"))
            .expect("realization")
            .active
    );
}

#[test]
fn expired_or_missing_required_realization_fails_closed() {
    let (mut registry, _authority) = admitted_registry();
    registry
        .register_realization_v2(
            binding_for(
                "realization:1",
                "factor:1",
                PromptRoleV2::DeveloperInstruction,
                "payload-one",
            ),
            payload("payload-one"),
        )
        .expect("register realization");
    let tuple = model_tuple();
    let vector = digest("generation-vector");
    let snapshot = registry.snapshot_v2(vector, &tuple).expect("snapshot");
    assert_eq!(
        registry.read_compatible_v2(&snapshot, vector, &tuple, 100, vec![id("factor:1")], 8),
        Err(PromptRegistryV2Error::RequiredFactorUnavailable)
    );
}

#[test]
fn untrusted_external_factor_cannot_obtain_v2_realization() {
    let mut registry = registry();
    registry
        .register_factor(factor_with_id("factor:1", FactorSource::ExternalUntrusted))
        .expect("register external draft");
    assert_eq!(
        registry.register_realization_v2(
            binding_for(
                "realization:1",
                "factor:1",
                PromptRoleV2::DeveloperInstruction,
                "payload-one",
            ),
            payload("payload-one"),
        ),
        Err(crate::Error::FactorNotAdmitted("factor:1".to_string()))
    );
}

#[test]
fn required_factors_are_reserved_before_result_truncation() {
    let mut registry = registry();
    let authority = TestAuthority::new();
    for (factor_id, nonce) in [("factor:a", 31), ("factor:b", 32)] {
        registry
            .register_factor(factor_with_id(factor_id, FactorSource::GovernedInternal))
            .expect("register factor");
        admit(&mut registry, &authority, factor_id, nonce);
    }
    for (realization_id, factor_id, role, value) in [
        (
            "realization:a-system",
            "factor:a",
            PromptRoleV2::SystemInstruction,
            "a-system",
        ),
        (
            "realization:a-developer",
            "factor:a",
            PromptRoleV2::DeveloperInstruction,
            "a-dev",
        ),
        (
            "realization:b-developer",
            "factor:b",
            PromptRoleV2::DeveloperInstruction,
            "b-dev",
        ),
    ] {
        registry
            .register_realization_v2(
                binding_for(realization_id, factor_id, role, value),
                payload(value),
            )
            .expect("register realization");
    }
    let tuple = model_tuple();
    let vector = digest("generation-vector");
    let snapshot = registry.snapshot_v2(vector, &tuple).expect("snapshot");
    let result = registry
        .read_compatible_v2(
            &snapshot,
            vector,
            &tuple,
            10,
            vec![id("factor:a"), id("factor:b")],
            2,
        )
        .expect("required factors remain deliverable");
    let returned = result
        .bindings
        .iter()
        .map(|binding| binding.factor_id.clone())
        .collect::<BTreeSet<_>>();
    assert_eq!(returned, BTreeSet::from([id("factor:a"), id("factor:b")]));
    assert_eq!(result.omitted_count, 1);
}

#[test]
fn required_factor_order_is_canonical_and_digest_stable() {
    let mut registry = registry();
    let authority = TestAuthority::new();
    for (factor_id, nonce, value) in [("factor:a", 41, "payload-a"), ("factor:b", 42, "payload-b")]
    {
        registry
            .register_factor(factor_with_id(factor_id, FactorSource::GovernedInternal))
            .expect("register factor");
        admit(&mut registry, &authority, factor_id, nonce);
        registry
            .register_realization_v2(
                binding_for(
                    &format!("realization:{factor_id}"),
                    factor_id,
                    PromptRoleV2::DeveloperInstruction,
                    value,
                ),
                payload(value),
            )
            .expect("register realization");
    }
    let tuple = model_tuple();
    let vector = digest("generation-vector");
    let snapshot = registry.snapshot_v2(vector, &tuple).expect("snapshot");
    let left = registry
        .read_compatible_v2(
            &snapshot,
            vector,
            &tuple,
            10,
            vec![id("factor:b"), id("factor:a")],
            4,
        )
        .expect("canonical read");
    let right = registry
        .read_compatible_v2(
            &snapshot,
            vector,
            &tuple,
            10,
            vec![id("factor:a"), id("factor:b")],
            4,
        )
        .expect("canonical read");
    assert_eq!(
        left.required_factor_ids,
        vec![id("factor:a"), id("factor:b")]
    );
    assert_eq!(left, right);
    assert_eq!(
        registry.read_compatible_v2(
            &snapshot,
            vector,
            &tuple,
            10,
            vec![id("factor:a"), id("factor:a")],
            4,
        ),
        Err(PromptRegistryV2Error::DuplicateFactorFilter(
            "factor:a".to_string()
        ))
    );
}

#[test]
fn active_realization_replacement_requires_exact_predecessor() {
    let (mut registry, _authority) = admitted_registry();
    let first = binding_for(
        "realization:1",
        "factor:1",
        PromptRoleV2::DeveloperInstruction,
        "payload-one",
    );
    registry
        .register_realization_v2(first.clone(), payload("payload-one"))
        .expect("first realization");
    let role_drift = binding_for(
        "realization:role-drift",
        "factor:1",
        PromptRoleV2::ToolSchemaFragment,
        "payload-role-drift",
    );
    assert_eq!(
        registry.register_realization_v2(role_drift, payload("payload-role-drift")),
        Err(crate::Error::ActiveRealizationConflict(
            "realization:1".to_string()
        ))
    );
    let second = binding_for(
        "realization:2",
        "factor:1",
        PromptRoleV2::DeveloperInstruction,
        "payload-two",
    );
    assert_eq!(
        registry.register_realization_v2(second.clone(), payload("payload-two")),
        Err(crate::Error::ActiveRealizationConflict(
            "realization:1".to_string()
        ))
    );
    let mut replacement = second;
    replacement.predecessor_realization_id = Some(first.realization_id.clone());
    registry
        .register_realization_v2(replacement, payload("payload-two"))
        .expect("explicit supersession");
    assert!(
        !registry
            .realization(&id("realization:1"))
            .expect("first")
            .active
    );
    assert!(
        registry
            .realization(&id("realization:2"))
            .expect("second")
            .active
    );
    registry.validate_integrity().expect("registry integrity");
}

#[test]
fn actual_payload_resolution_revalidates_snapshot_profile_and_digest() {
    let (mut registry, _authority) = admitted_registry();
    let binding = binding_for(
        "realization:1",
        "factor:1",
        PromptRoleV2::DeveloperInstruction,
        "exact instruction bytes",
    );
    registry
        .register_realization_v2(binding.clone(), payload("exact instruction bytes"))
        .expect("register realization");
    let tuple = model_tuple();
    let vector = digest("generation-vector");
    let snapshot = registry.snapshot_v2(vector, &tuple).expect("snapshot");
    let resolved = registry
        .resolve_payload_v2(&snapshot, vector, &tuple, 10, &binding.realization_id)
        .expect("resolve payload");
    assert_eq!(resolved.payload, payload("exact instruction bytes"));
    assert_eq!(resolved.payload_digest, binding.payload_digest);
    resolved.validate().expect("resolution receipt");
}

#[test]
fn payload_bytes_are_mandatory_bounded_and_digest_bound() {
    let (mut registry, _authority) = admitted_registry();
    let binding = binding_for(
        "realization:1",
        "factor:1",
        PromptRoleV2::DeveloperInstruction,
        "payload-one",
    );
    assert_eq!(
        registry.register_realization_v2(binding.clone(), Vec::new()),
        Err(crate::Error::PayloadRequired)
    );
    assert_eq!(
        registry.register_realization_v2(binding.clone(), payload("wrong")),
        Err(crate::Error::PayloadDigestMismatch)
    );
    assert_eq!(
        registry.register_realization_v2(binding, vec![b'x'; MAX_REALIZATION_PAYLOAD_BYTES + 1],),
        Err(crate::Error::PayloadTooLarge)
    );
}
