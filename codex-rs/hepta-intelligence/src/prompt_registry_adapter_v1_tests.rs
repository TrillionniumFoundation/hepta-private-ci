use super::*;
use codex_hepta_prompt_registry::PromptRealizationBindingV2;
use codex_hepta_prompt_registry::PromptRoleV2;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Revision;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("test identifier")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn owner_view(
    expires_unix_ms: Option<u64>,
) -> (
    PromptRegistrySnapshotV2,
    CompatibleRealizationSetV2,
    PromptModelTupleV2,
) {
    let model = PromptModelTupleV2 {
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tools"),
        locale_id: id("en-US"),
    };
    let mut snapshot = PromptRegistrySnapshotV2 {
        revision: Revision::new(4).expect("revision"),
        registry_digest: digest("registry"),
        lifecycle_frontier: 4,
        revocation_frontier: 3,
        generation_vector_digest: digest("generation"),
        model_tuple_digest: model.digest(),
        snapshot_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    snapshot.snapshot_digest = snapshot.compute_snapshot_digest();
    let binding = PromptRealizationBindingV2 {
        realization_id: id("realization:001"),
        factor_id: id("factor:001"),
        model_digest: model.model_digest,
        tokenizer_digest: model.tokenizer_digest,
        template_digest: model.template_digest,
        tool_schema_digest: model.tool_schema_digest,
        locale_id: model.locale_id.clone(),
        role: PromptRoleV2::DeveloperInstruction,
        payload_digest: digest("payload"),
        token_cost: 17,
        expires_unix_ms,
    };
    let mut compatible = CompatibleRealizationSetV2 {
        snapshot_digest: snapshot.snapshot_digest,
        model_tuple_digest: model.digest(),
        required_factor_ids: vec![id("factor:001")],
        bindings: vec![binding],
        omitted_count: 2,
        set_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    compatible.set_digest = compatible.compute_set_digest();
    (snapshot, compatible, model)
}

#[test]
fn owner_registry_view_maps_exactly_into_optimizer_source_and_authenticates_it() {
    let (snapshot, compatible, model) = owner_view(Some(1_000));
    let adapter =
        PromptRegistryCandidateAdapterV1::from_owner_view(&snapshot, &compatible, &model, 100)
            .expect("owner view adapts");
    let source = adapter.source();

    assert_eq!(source.registry_snapshot_digest, snapshot.snapshot_digest);
    assert_eq!(source.registry_revision, 4);
    assert_eq!(source.revocation_frontier, 3);
    assert_eq!(source.generation_vector_digest, digest("generation"));
    assert_eq!(source.omitted_count, 2);
    assert_eq!(source.bindings.len(), 1);
    assert_eq!(source.bindings[0].candidate_id, id("realization:001"));
    assert_eq!(
        source.bindings[0].role,
        PromptCandidateRoleV1::DeveloperInstruction
    );
    assert_eq!(
        source.bindings[0].admission_digest,
        compatible.bindings[0].digest()
    );
    assert_eq!(source.bindings[0].support_digest, compatible.set_digest);
    adapter
        .authenticate_candidate_source(source, digest("objective"), 100)
        .expect("exact owner-derived source authenticates");
}

#[test]
fn changed_source_or_model_tuple_cannot_reuse_owner_adapter() {
    let (snapshot, compatible, model) = owner_view(Some(1_000));
    let adapter =
        PromptRegistryCandidateAdapterV1::from_owner_view(&snapshot, &compatible, &model, 100)
            .expect("owner view adapts");
    let mut changed = adapter.source().clone();
    changed.omitted_count += 1;
    changed.source_digest = changed.compute_source_digest();
    assert_eq!(
        adapter.authenticate_candidate_source(&changed, digest("objective"), 100),
        Err(PromptAuthenticationErrorV1::Rejected)
    );

    let mut wrong_model = model.clone();
    wrong_model.template_digest = digest("other-template");
    assert_eq!(
        PromptRegistryCandidateAdapterV1::from_owner_view(
            &snapshot,
            &compatible,
            &wrong_model,
            100,
        ),
        Err(PromptRegistryAdapterErrorV1::InvalidOwnerView)
    );
}

#[test]
fn expired_owner_realization_is_rejected_before_enumeration() {
    let (snapshot, compatible, model) = owner_view(Some(50));
    assert_eq!(
        PromptRegistryCandidateAdapterV1::from_owner_view(&snapshot, &compatible, &model, 100),
        Err(PromptRegistryAdapterErrorV1::ExpiredRealization(
            "realization:001".to_string()
        ))
    );
}
