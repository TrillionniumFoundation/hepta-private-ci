use std::str::FromStr;

use super::*;
use crate::Lifecycle;
use crate::PromptRoleV2;
use crate::TestMust;

fn id(value: &str) -> StableId {
    StableId::new(value).must("bounded identifier")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn bounded_factor(last_dimension_bytes: usize) -> PromptFactor {
    let dimensions = (0..63)
        .map(|index| {
            let mut value = format!("dimension:{index:03}");
            let bytes = if index == 62 {
                last_dimension_bytes
            } else {
                128
            };
            value.push_str(&"x".repeat(bytes - value.len()));
            id(&value)
        })
        .collect();
    PromptFactor {
        factor_id: id("factor:bounded"),
        proposer_id: id("proposer:bounded"),
        semantic_version: id("semantic:v1"),
        semantic_purpose: "p".repeat(4_096),
        authority_class: "registered_prompt_factor".to_owned(),
        eligible_objective_dimensions: dimensions,
        content_digest: digest("content"),
        source: FactorSource::GovernedInternal,
        lifecycle: Lifecycle::Admitted,
    }
}

fn binding() -> PromptRealizationBindingV2 {
    PromptRealizationBindingV2 {
        realization_id: id("realization:bounded"),
        factor_id: id("factor:bounded"),
        model_id: id("model:bounded"),
        model_version: "v1".to_owned(),
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
        context_profile_digest: digest("context-profile"),
        locale_id: id("locale:en"),
        role: PromptRoleV2::DeveloperInstruction,
        payload_digest: digest("payload"),
        token_cost: 1,
        expires_unix_ms: None,
    }
}

fn public_bindings(factor: &PromptFactor) -> [Result<FinalUseBinding, AdmissionError>; 4] {
    let reviewer = id("reviewer:bounded");
    let scope = digest("scope");
    [
        final_use_admission_binding(factor, &reviewer, scope, digest("evidence")),
        final_use_realization_binding(
            factor,
            &reviewer,
            scope,
            &binding(),
            /*supersedes_realization_id*/ None,
        ),
        final_use_retire_binding(factor, &reviewer, scope, digest("reason")),
        final_use_revoke_binding(
            factor,
            &reviewer,
            scope,
            digest("reason"),
            /*cutoff_unix_ms*/ 1,
        ),
    ]
}

#[test]
fn public_final_use_binding_helpers_reject_oversized_factor_fields() {
    let mut purpose = bounded_factor(/*last_dimension_bytes*/ 66);
    purpose.semantic_purpose.push('p');
    let mut authority_class = bounded_factor(/*last_dimension_bytes*/ 66);
    authority_class.authority_class = "a".repeat(65);
    let dimensions = bounded_factor(/*last_dimension_bytes*/ 67);
    let expected: [Result<FinalUseBinding, AdmissionError>; 4] =
        std::array::from_fn(|_| Err(AdmissionError::InvalidGrant));
    for factor in [purpose, authority_class, dimensions] {
        assert_eq!(public_bindings(&factor), expected);
    }
}

#[test]
fn public_final_use_binding_helpers_preserve_exact_boundary_request_bytes() {
    let factor = bounded_factor(/*last_dimension_bytes*/ 66);
    let dimensions = serde_json::to_vec(
        &factor
            .eligible_objective_dimensions
            .iter()
            .map(StableId::as_str)
            .collect::<Vec<_>>(),
    )
    .must("canonical dimensions");
    assert_eq!(dimensions.len(), 8_192);
    let expected: [Result<FinalUseBinding, AdmissionError>; 4] = [
        (
            "admission",
            "2c7f29e2e397e166efc0c825dc1f58e6787e8b484c7a928e5e8ae9523e9f7103",
            "ee8250fb76e094b34b471f13a73dbbe51d1ae142e9df59d7c0d31ec20f0a0a8e",
        ),
        (
            "realization",
            "5bb5eaf90028a87d8e47ae8b9c886b66b40da6f568ae362dc57d0afacb5be047",
            "239f59ed55e737c77147cf55ad0c1b030b6d7ee748a7426952f9b852d5a935e5",
        ),
        (
            "retire",
            "50a217947e01a01c3930ac83e922e1571b661e004c99542a6b2706ea95a458a5",
            "72c0ca08c5746f3207151a53047afdf7c73fe81afbe495eb779759ee96d3bd9f",
        ),
        (
            "revoke",
            "7aa9d0d066c9ada874e112d8dfc9731717c88fba83075f785a44d89076193efb",
            "dff6a414a97b4efb8cbbb1c3cfacc7c620b76c3df67e8d1d522cb98eb7be8391",
        ),
    ]
    .map(|(destination, request, payload)| {
        Ok(FinalUseBinding {
            subject_id: "reviewer:bounded".to_owned(),
            destination_id: format!("prompt.registry:{destination}"),
            request_sha256: Digest32::from_str(request)
                .must("request golden")
                .into_array(),
            scope_sha256: digest("scope").into_array(),
            payload_sha256: Digest32::from_str(payload)
                .must("payload golden")
                .into_array(),
        })
    });
    assert_eq!(public_bindings(&factor), expected);
}

#[test]
fn public_final_use_binding_bounds_preserve_existing_rejection_priority() {
    let mut factor = bounded_factor(/*last_dimension_bytes*/ 67);
    let reviewer = id("reviewer:bounded");
    let scope = digest("scope");
    factor.source = FactorSource::ExternalUntrusted;
    assert_eq!(
        final_use_admission_binding(&factor, &reviewer, scope, digest("evidence")),
        Err(AdmissionError::UntrustedFactor)
    );
    factor.source = FactorSource::GovernedInternal;
    assert_eq!(
        final_use_admission_binding(&factor, &factor.proposer_id, scope, digest("evidence")),
        Err(AdmissionError::SelfReview)
    );
    assert_eq!(
        final_use_admission_binding(&factor, &reviewer, Digest32::ZERO, digest("evidence")),
        Err(AdmissionError::ScopeMismatch)
    );
    factor.lifecycle = Lifecycle::Draft;
    assert_eq!(
        final_use_realization_binding(
            &factor,
            &reviewer,
            scope,
            &binding(),
            /*supersedes_realization_id*/ None
        ),
        Err(AdmissionError::ScopeMismatch)
    );
    assert_eq!(
        final_use_retire_binding(&factor, &reviewer, Digest32::ZERO, digest("reason")),
        Err(AdmissionError::ScopeMismatch)
    );
    assert_eq!(
        final_use_revoke_binding(
            &factor,
            &reviewer,
            Digest32::ZERO,
            digest("reason"),
            /*cutoff_unix_ms*/ 1,
        ),
        Err(AdmissionError::ScopeMismatch)
    );
    assert_eq!(
        final_use_revoke_binding(
            &factor,
            &reviewer,
            scope,
            digest("reason"),
            /*cutoff_unix_ms*/ 0
        ),
        Err(AdmissionError::InvalidGrant)
    );
}
