//! Adversarial regressions using actual owner-issued and signed inputs.

use super::*;
use super::tests::*;
use codex_hepta_kg::KnowledgeProjectionInputV2;
use codex_hepta_kg::build_complete_generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

#[test]
fn sealed_owner_projection_preserves_conflicts_after_bare_graph_rebuild() {
    use codex_hepta_prompt_registry::PromptFactorRelation;
    use codex_hepta_prompt_registry::PromptFactorRelationKind;
    use codex_hepta_prompt_registry::final_use_factor_relation_binding;

    let temp = tempfile::tempdir().expect("tempdir");
    let (mut registry, _, authority, key, now) = registry_fixture(&temp.path().join("registry"), &[1]);
    let (actor, scope) = register_second_realized_factor(&mut registry, &authority, &key, now);
    let relation = PromptFactorRelation {
        relation_id: id("relation:authentic-conflict"),
        left_factor_id: id("factor:a"), right_factor_id: id("factor:b"),
        kind: PromptFactorRelationKind::Conflicts, evidence_digest: digest("authentic-conflict-evidence"),
    };
    let grant = relation_grant(
        final_use_factor_relation_binding(registry.registry().expect("registry"), &actor, scope, &relation).expect("relation binding"),
        &key, now, "insert:authentic-conflict",
    );
    registry.register_factor_relation_final_use(&authority, &grant, &actor, scope, relation).expect("authentic conflict");
    let owner = registry.registry().expect("registry");
    let projection = owner_projection(owner);
    let graph = projection.generation();
    let forged = build_complete_generation(graph.generation, KnowledgeProjectionInputV2 {
        source_snapshot_digest: graph.source_snapshot_digest,
        generation_vector_digest: graph.generation_vector_digest,
        graph_profile_digest: graph.graph_profile_digest,
        complete_source_cut: true, nodes: graph.nodes.clone(), edges: Vec::new(),
    }).expect("public builder can relabel a relation-free graph");
    forged.validate().expect("structurally valid bare graph");
    assert_eq!(forged.source_snapshot_digest, projection.source_digest());
    assert_ne!(forged.generation_digest, graph.generation_digest);
    // The public selector requires the private owner-issued projection type;
    // this valid bare graph cannot be passed or substituted into its contents.
    assert_eq!(owner_projection(owner), projection);
    let priced = current_pair_pricing(owner);
    let selected = select_portfolio_v1(&priced, &projection, Vec::new(), &verifier(), selection_request(), 100).expect("sealed owner selection");
    assert_eq!(selected.receipt.factor_ids, vec![id("factor:a")]);
    assert_eq!(selected.graph_generation_digest, graph.generation_digest);
    assert_eq!(exercise_v1(owner, &selected, PromptExerciseRequestV1 {
        decision_boundary: PromptDecisionBoundaryV1::BeforeModelOrToolDispatch,
        current_state_digest: digest("state"), generation_vector_digest: digest("generation-vector"),
        model_tuple: model_tuple(), now_unix_ms: 200, wait_value_q32: FixedQ32::ZERO,
        policy_digest: digest("exercise-policy"),
    }).expect("live authentic portfolio").decision, PromptExerciseActionV1::Exercise);
}

#[test]
fn authentic_completeness_cannot_price_tampered_realization_contents() {
    let temp = tempfile::tempdir().expect("tempdir");
    let (registry, _, _, _, _) = registry_fixture(&temp.path().join("registry"), &[4]);
    let owner = registry.registry().expect("registry");
    let enumerated = current_enumeration(owner, vec![id("factor:a")]);
    let pricing = authenticated_pricing_inputs(&enumerated, verifier());
    let mut changed = enumerated.clone();
    changed.candidates[0].realization.token_cost = 1;
    assert_eq!(pricing.price(changed).expect_err("cached completeness cannot hide actual token mutation"), CanonicalPromptError::CandidateBindingMismatch);
    let mut oversize = enumeration_request();
    oversize.required_factor_ids = (0..=MAX_CANONICAL_PROMPT_FACTORS).map(|index| id(&format!("factor:oversize:{index}"))).collect();
    assert_eq!(enumerate_factors_v1(owner, oversize).expect_err("reject before registry collection/read"), CanonicalPromptError::CandidateLimit);
    enumerated.validate().expect("original enumeration remains valid");
}

#[test]
fn authenticated_prices_cannot_be_reblessed_after_token_or_utility_mutation() {
    let temp = tempfile::tempdir().expect("tempdir");
    let (registry, _, _, _, _) = registry_fixture(&temp.path().join("registry"), &[4]);
    let owner = registry.registry().expect("registry");
    let enumerated = current_enumeration(owner, vec![id("factor:a")]);
    let priced = authenticated_pricing_inputs(&enumerated, verifier()).price(enumerated).expect("authentic pricing");
    let projection = owner_projection(owner);
    let mut request = selection_request();
    request.token_budget = 1;
    assert!(select_portfolio_v1(&priced, &projection, Vec::new(), &verifier(), request.clone(), 100).expect("original cost exceeds budget").selected.is_empty());
    let mut changed = priced.clone();
    changed.rows[0].pricing.token_cost = 1;
    assert_eq!(select_portfolio_v1(&changed, &projection, Vec::new(), &verifier(), request, 100).expect_err("public token field cannot bypass budget"), CanonicalPromptError::PricingBindingMismatch);
    let mut changed = priced;
    let row = &mut changed.rows[0];
    row.net_utility_q32 = FixedQ32::ONE;
    row.pricing.expected_utility_q32 = FixedQ32::ONE;
    row.pricing.receipt_digest = digest_pricing_receipt(
        &row.pricing.factor_id, row.pricing.state_digest, row.pricing.expected_utility_q32,
        row.pricing.downside_q32, row.pricing.token_cost, row.pricing.latency_cost_micros,
        row.pricing.interference_ppm, &row.pricing.confidence_interval, changed.pricing_policy_digest,
        row.binding.binding_digest,
    );
    changed.pricing_set_digest = digest_pricing_set(&changed.rows, changed.pricing_policy_digest);
    assert_eq!(select_portfolio_v1(&changed, &projection, Vec::new(), &verifier(), selection_request(), 100).expect_err("recomputed public receipts cannot mint an authenticated pricing seal"), CanonicalPromptError::PricingBindingMismatch);
}

#[test]
fn pricing_and_selection_bind_the_authenticated_objective() {
    let temp = tempfile::tempdir().expect("tempdir");
    let (registry, _, _, _, _) = registry_fixture(&temp.path().join("registry"), &[4]);
    let owner = registry.registry().expect("registry");
    let original = current_enumeration(owner, vec![id("factor:a")]);
    let mut other_request = enumeration_request();
    other_request.objective_digest = digest("objective:other");
    let other = enumerate_factors_v1(owner, other_request).expect("genuine enumeration for another objective");
    assert_eq!(authenticated_pricing_inputs(&original, verifier()).price(other).expect_err("objective A signatures cannot price objective B enumeration"), CanonicalPromptError::ObjectiveMismatch);
    let priced = authenticated_pricing_inputs(&original, verifier()).price(original).expect("authentic objective A pricing");
    let mut trust = learning_trust();
    trust.objective_digest = digest("objective:other");
    let other_verifier = LearningEvidenceVerifierV1::new(trust).expect("host-owned objective B verifier");
    assert_eq!(select_portfolio_v1(&priced, &owner_projection(owner), Vec::new(), &other_verifier, selection_request(), 100).expect_err("selector verifier must match priced objective"), CanonicalPromptError::ObjectiveMismatch);
}

#[test]
fn selection_revalidates_proof_expiry_rotation_and_scheduled_revocation() {
    let temp = tempfile::tempdir().expect("tempdir");
    let (registry, _, _, _, _) = registry_fixture(&temp.path().join("registry"), &[4]);
    let owner = registry.registry().expect("registry");
    let enumerated = current_enumeration(owner, vec![id("factor:a")]);
    let projection = owner_projection(owner);
    let mut fixture = authenticated_pricing_inputs(&enumerated, verifier());
    fixture.completeness_evidence.expires_at = 150;
    fixture.completeness_evidence.signature = SigningKey::from_bytes(&[8; 32]).sign(&fixture.completeness_evidence.signing_bytes()).to_bytes();
    let priced = fixture.price(enumerated.clone()).expect("authentic short-lived completeness");
    assert_eq!(select_portfolio_v1(&priced, &projection, Vec::new(), &verifier(), selection_request(), 200).expect_err("expiry cannot be washed into a new selection seal"), CanonicalPromptError::PricingAdmissionExpired);
    assert_eq!(select_portfolio_v1(&priced, &projection, Vec::new(), &verifier(), selection_request(), 90).expect_err("selection cannot predate pricing admission"), CanonicalPromptError::InvalidTime);
    let selected = select_portfolio_v1(&priced, &projection, Vec::new(), &verifier(), selection_request(), 100).expect("valid short interval");
    assert_eq!(selected.receipt.valid_until_unix_ms, 150);
    for now in [50, 150] {
        assert_eq!(exercise_v1(owner, &selected, PromptExerciseRequestV1 {
            decision_boundary: PromptDecisionBoundaryV1::BeforeModelOrToolDispatch,
            current_state_digest: digest("state"), generation_vector_digest: digest("generation-vector"),
            model_tuple: model_tuple(), now_unix_ms: now, wait_value_q32: FixedQ32::ZERO,
            policy_digest: digest("exercise-policy"),
        }).expect("closed selection interval").decision, PromptExerciseActionV1::RejectStale);
    }
    let priced = authenticated_pricing_inputs(&enumerated, verifier()).price(enumerated.clone()).expect("authentic pricing");
    let mut rotated_trust = learning_trust();
    rotated_trust.signers[0].principal.credential_chain_digest = digest("rotated-credential");
    let rotated = LearningEvidenceVerifierV1::new(rotated_trust).expect("rotated host trust");
    assert_eq!(select_portfolio_v1(&priced, &projection, Vec::new(), &rotated, selection_request(), 100).expect_err("current trust snapshot must match pricing admission"), CanonicalPromptError::PricingTrustMismatch);
    let mut scheduled_trust = learning_trust();
    scheduled_trust.signers[0].revoked_at = Some(250);
    let scheduled = LearningEvidenceVerifierV1::new(scheduled_trust).expect("known scheduled revocation");
    let priced = authenticated_pricing_inputs(&enumerated, scheduled).price(enumerated).expect("pricing before known revocation");
    let mut scheduled_trust = learning_trust();
    scheduled_trust.signers[0].revoked_at = Some(250);
    let scheduled = LearningEvidenceVerifierV1::new(scheduled_trust).expect("same scheduled trust snapshot");
    for now in [100, 300] {
        assert_eq!(select_portfolio_v1(&priced, &projection, Vec::new(), &scheduled, selection_request(), now).expect_err("known revocation must fail at current time or conservative endpoint"), CanonicalPromptError::LearningEvidence("Revoked".to_owned()));
    }
    let mut short_request = selection_request();
    short_request.requested_valid_until_unix_ms = 200;
    select_portfolio_v1(&priced, &projection, Vec::new(), &scheduled, short_request, 100).expect("interval ending before revocation stays valid");
}

#[test]
fn authentic_signatures_require_independent_generator_and_evaluator() {
    let temp = tempfile::tempdir().expect("tempdir");
    let (registry, _, _, _, _) = registry_fixture(&temp.path().join("registry"), &[4]);
    let enumerated = current_enumeration(registry.registry().expect("registry"), vec![id("factor:a")]);
    for same_actor in [true, false] {
        let mut trust = learning_trust();
        if same_actor {
            trust.signers.truncate(1);
            trust.signers[0].roles.push(LearningEvidenceRoleV1::Generator);
        } else {
            trust.signers[1].controller_id = trust.signers[0].controller_id.clone();
        }
        let current = LearningEvidenceVerifierV1::new(trust).expect("legitimate multi-role or shared-controller trust");
        let mut fixture = authenticated_pricing_inputs(&enumerated, current);
        if same_actor {
            fixture.completeness_evidence.principal_id = id("evaluator");
            fixture.completeness_evidence.signature = SigningKey::from_bytes(&[7; 32]).sign(&fixture.completeness_evidence.signing_bytes()).to_bytes();
        }
        fixture.verifier.verify(LearningEvidenceRoleV1::Generator, &fixture.completeness_evidence, &candidate_completeness_signing_payload_v1(&fixture.completeness).expect("payload"), 100).expect("genuine generator signature");
        fixture.verifier.verify(LearningEvidenceRoleV1::Evaluator, &fixture.evidence[0].evidence, &pricing_evidence_signing_payload_v1(&fixture.evidence[0]), 100).expect("genuine evaluator signature");
        let expected = if same_actor { "Principal(RoleCollision(\"principal\"))" } else { "ControllerCollision" };
        assert_eq!(fixture.price(enumerated.clone()).expect_err("independent evidence cannot be self-certified"), CanonicalPromptError::LearningEvidence(expected.to_owned()));
    }
}
