use super::*;
use crate::PromptCandidateBindingV1;
use crate::PromptCandidateRoleV1;
use crate::PromptCandidateEnumerationRequestV1;
use crate::PromptCandidateSourceAuthenticatorV1;
use crate::PromptCandidateSourceV1;
use crate::PromptModelProfileV1;
use crate::enumerate_factors_v1;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("test identifier")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

struct AcceptSource;

impl PromptCandidateSourceAuthenticatorV1 for AcceptSource {
    fn authenticate_candidate_source(
        &self,
        _source: &PromptCandidateSourceV1,
        _objective_digest: Digest32,
        _now_unix_ms: u64,
    ) -> Result<(), PromptAuthenticationErrorV1> {
        Ok(())
    }
}

fn candidate_set(count: usize) -> PromptCandidateSetReceiptV1 {
    let mut bindings = (0..count)
        .map(|index| PromptCandidateBindingV1 {
            candidate_id: id(&format!("candidate:{index:03}")),
            factor_id: id(&format!("factor:{index:03}")),
            realization_id: id(&format!("realization:{index:03}")),
            role: PromptCandidateRoleV1::DeveloperInstruction,
            payload_digest: digest(&format!("payload:{index}")),
            admission_digest: digest(&format!("admission:{index}")),
            support_digest: digest(&format!("support:{index}")),
            token_cost: 1,
            expires_unix_ms: Some(10_000),
            binding_digest: Digest32::ZERO,
        })
        .collect::<Vec<_>>();
    for binding in &mut bindings {
        binding.binding_digest = binding.compute_binding_digest();
    }
    let mut source = PromptCandidateSourceV1 {
        owner_id: id("prompt.registry"),
        registry_snapshot_digest: digest("registry"),
        registry_revision: 2,
        revocation_frontier: 1,
        generation_vector_digest: digest("generation"),
        model_profile: PromptModelProfileV1 {
            model_digest: digest("model"),
            tokenizer_digest: digest("tokenizer"),
            template_digest: digest("template"),
            tool_schema_digest: digest("tools"),
            locale_id: id("en-US"),
        },
        bindings,
        omitted_count: 0,
        source_digest: Digest32::ZERO,
    };
    source.source_digest = source.compute_source_digest();
    enumerate_factors_v1(
        PromptCandidateEnumerationRequestV1 {
            enumeration_id: id("enumeration:relations"),
            objective_digest: digest("objective"),
            state_digest: digest("state"),
            maximum_candidates: count,
            now_unix_ms: 100,
            source,
        },
        &AcceptSource,
    )
    .expect("candidate set")
}

fn relations(set: &PromptCandidateSetReceiptV1) -> PromptRelationSourceV1 {
    PromptRelationSourceV1 {
        producer_id: id("knowledge.graph"),
        candidate_set_digest: set.candidate_set_digest,
        generation_vector_digest: set.generation_vector_digest,
        hard_constraint_completeness_digest: digest("hard-constraint-completeness"),
        interactions: Vec::new(),
        hard_constraints: Vec::new(),
        source_digest: Digest32::ZERO,
    }
}

fn seal(mut source: PromptRelationSourceV1) -> PromptRelationSourceV1 {
    source.source_digest = source.compute_source_digest();
    source
}

#[test]
fn sparse_pair_support_does_not_require_a_complete_n_squared_graph() {
    let set = candidate_set(33);
    let mut source = relations(&set);
    source.interactions.push(PromptPairInteractionV1 {
        left_candidate_id: id("candidate:000"),
        right_candidate_id: id("candidate:001"),
        marginal_net_utility: FixedQ32::ZERO,
        support_digest: digest("pair:0:1"),
    });
    seal(source)
        .validate_for(&set, /*now_unix_ms*/ 100)
        .expect("sparse support is structurally valid");
}

#[test]
fn dependency_cycles_fail_closed() {
    let set = candidate_set(2);
    let mut source = relations(&set);
    source.hard_constraints = vec![
        PromptHardConstraintV1::Requires {
            candidate_id: id("candidate:000"),
            prerequisite_candidate_id: id("candidate:001"),
            support_digest: digest("requires:0:1"),
        },
        PromptHardConstraintV1::Requires {
            candidate_id: id("candidate:001"),
            prerequisite_candidate_id: id("candidate:000"),
            support_digest: digest("requires:1:0"),
        },
    ];
    assert_eq!(
        seal(source).validate_for(&set, /*now_unix_ms*/ 100),
        Err(PromptRelationErrorV1::DependencyCycle)
    );
}

#[test]
fn unknown_relation_endpoints_and_missing_completeness_proof_are_rejected() {
    let set = candidate_set(1);
    let mut unknown = relations(&set);
    unknown.interactions.push(PromptPairInteractionV1 {
        left_candidate_id: id("candidate:000"),
        right_candidate_id: id("candidate:999"),
        marginal_net_utility: FixedQ32::ZERO,
        support_digest: digest("pair"),
    });
    assert_eq!(
        seal(unknown).validate_for(&set, /*now_unix_ms*/ 100),
        Err(PromptRelationErrorV1::InvalidRelationEndpoint)
    );

    let mut incomplete = relations(&set);
    incomplete.hard_constraint_completeness_digest = Digest32::ZERO;
    incomplete = seal(incomplete);
    assert_eq!(
        incomplete.validate_for(&set, /*now_unix_ms*/ 100),
        Err(PromptRelationErrorV1::EmptyDigest("relation source"))
    );
}
