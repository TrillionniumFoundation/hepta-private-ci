use super::*;

use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_prompt_registry::final_use_realization_binding;
use ed25519_dalek::Signer;
use pretty_assertions::assert_eq;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid fixture id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

#[test]
fn cheaper_selected_role_is_preserved_when_another_role_sorts_first() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let root = temporary.path().join("prompt-registry-multirole");
    let (mut registry, tuple, authority, signing_key, grant_now) =
        tests::admitted_registry(&root, b"Inspect evidence before mutation.");
    let factor = registry
        .registry()
        .expect("registry")
        .factor(&id("factor:verify"))
        .cloned()
        .expect("admitted factor");
    let developer_binding = registry
        .registry()
        .expect("registry")
        .realization_binding(&id("realization:verify"))
        .cloned()
        .expect("developer realization");
    let payload = b"Validate exact authority before execution.";
    let mut system_binding = developer_binding.clone();
    system_binding.realization_id = id("realization:aaa");
    system_binding.role = PromptRoleV2::SystemInstruction;
    system_binding.payload_digest = Digest32::of_bytes(payload);
    system_binding.token_cost = 8;
    let actor = id("publisher:multirole");
    let scope = digest("scope:multirole");
    let binding = final_use_realization_binding(
        &factor,
        &actor,
        scope,
        &system_binding,
        /*supersedes_realization_id*/ None,
    )
    .expect("realization binding");
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "review-authority:prompt".to_owned(),
        authority_epoch: 1,
        grant_id: "realization:prompt:multirole".to_owned(),
        nonce: [25; 32],
        binding,
        not_before_unix_ms: grant_now.saturating_sub(1_000),
        expires_at_unix_ms: grant_now + 30_000,
    };
    let signed = SignedFinalUseGrant {
        signature: signing_key
            .sign(&grant.signing_bytes().expect("signing bytes"))
            .to_bytes()
            .to_vec(),
        grant,
    };
    registry
        .register_realization_payload_final_use_v2(
            &authority,
            &signed,
            &actor,
            scope,
            system_binding,
            payload.to_vec(),
            /*supersedes_realization_id*/ None,
        )
        .expect("publish alternate role");

    // Enumeration selects the cheaper developer realization even though a
    // bounded registry read returns the lexicographically earlier system role.
    let selection = tests::canonical_selection(&registry, &tuple, /*now*/ 100);
    assert_eq!(
        selection.portfolio.selected[0].realization,
        developer_binding
    );
    let snapshot = registry
        .snapshot_v2(digest("generation-vector"), &tuple)
        .expect("snapshot");
    let truncated = registry
        .read_compatible_v2(
            &snapshot,
            digest("generation-vector"),
            &tuple,
            /*now_unix_ms*/ 100,
            vec![factor.factor_id],
            /*maximum_results*/ 1,
        )
        .expect("bounded compatible read");
    assert_eq!(
        truncated.bindings[0].realization_id,
        id("realization:aaa")
    );

    let output = compile_prompt_registry_v2(
        &registry,
        &selection.portfolio,
        &selection.exercise_request,
        PromptRegistryCompilationRequestV2 {
            compilation_id: id("compilation:multirole"),
            serialization_id: id("serialization:multirole"),
            attachment_id: id("attachment:multirole"),
            registry_model_tuple: tuple.clone(),
            context_model_profile: ContextModelProfileV2 {
                model_digest: tuple.model_digest,
                provider_id_digest: digest("provider"),
                provider_model_digest: tuple.model_digest,
                tokenizer_digest: tuple.tokenizer_digest,
                serializer_digest: digest("serializer"),
                template_digest: tuple.template_digest,
                tool_schema_digest: tuple.tool_schema_digest,
                maximum_context_tokens: 128,
            },
            now_unix_ms: 100,
            token_budget: 128,
            truncation_policy_digest: digest("truncation"),
        },
    )
    .expect("compile the exact exercised role");
    output.validate().expect("valid compiled output");
    assert_eq!(output.compatible.bindings, vec![developer_binding.clone()]);
    assert_eq!(output.selected_deliveries[0].binding, developer_binding);
}
