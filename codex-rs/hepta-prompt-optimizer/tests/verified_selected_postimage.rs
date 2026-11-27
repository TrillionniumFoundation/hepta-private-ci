use std::collections::BTreeSet;
use std::error::Error;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_kg::KnowledgeNodeV2;
use codex_hepta_kg::KnowledgeProjectionInputV2;
use codex_hepta_kg::KnowledgeSupportV2;
use codex_hepta_kg::build_complete_generation;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_prompt_optimizer::canonical::PromptEnumerationRequestV1;
use codex_hepta_prompt_optimizer::canonical::PromptPortfolioRequestV1;
use codex_hepta_prompt_optimizer::canonical::PromptPricingEvidenceV1;
use codex_hepta_prompt_optimizer::canonical::PromptPricingPolicyV1;
use codex_hepta_prompt_optimizer::canonical::SelectedPromptPortfolioV1;
use codex_hepta_prompt_optimizer::canonical::candidate_completeness_signing_payload_v1;
use codex_hepta_prompt_optimizer::canonical::pricing_evidence_signing_payload_v1;
use codex_hepta_prompt_optimizer::verified::BoundPromptPricingEvidenceV2;
use codex_hepta_prompt_optimizer::verified::VerifiedPromptErrorV2;
use codex_hepta_prompt_optimizer::verified::VerifiedSelectedPromptPortfolioV2;
use codex_hepta_prompt_optimizer::verified::enumerate_verified_factors_v2;
use codex_hepta_prompt_optimizer::verified::price_verified_factors_v2;
use codex_hepta_prompt_optimizer::verified::select_verified_portfolio_v2;
use codex_hepta_prompt_optimizer::verified::verify_selected_prompt_portfolio_v2;
use codex_hepta_prompt_registry::DurablePromptRegistry;
use codex_hepta_prompt_registry::FactorSource;
use codex_hepta_prompt_registry::Lifecycle;
use codex_hepta_prompt_registry::PromptFactor;
use codex_hepta_prompt_registry::PromptModelTupleV2;
use codex_hepta_prompt_registry::PromptRealizationBindingV2;
use codex_hepta_prompt_registry::PromptRoleV2;
use codex_hepta_prompt_registry::final_use_admission_binding;
use codex_hepta_prompt_registry::final_use_realization_binding;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

type TestResult<T = ()> = Result<T, Box<dyn Error>>;

const CLOCK_MARGIN_MS: u64 = 1_000;
const GRANT_LIFETIME_MS: u64 = 30_000;
const EVIDENCE_LIFETIME_MS: u64 = 10_000;
const SELECTION_LIFETIME_MS: u64 = 8_000;

fn id(value: &str) -> TestResult<StableId> {
    Ok(StableId::new(value)?)
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn sign_grant(grant: FinalUseGrant, key: &SigningKey) -> TestResult<SignedFinalUseGrant> {
    Ok(SignedFinalUseGrant {
        signature: key.sign(&grant.signing_bytes()?).to_bytes().to_vec(),
        grant,
    })
}

fn attest(
    verifier: &LearningEvidenceVerifierV1,
    key: &SigningKey,
    principal: &str,
    role: LearningEvidenceRoleV1,
    evidence_id: &str,
    payload: &[u8],
    now: u64,
) -> TestResult<SignedLearningEvidenceV1> {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(evidence_id)?,
        principal_id: id(principal)?,
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: verifier.scope_digest(),
        objective_digest: verifier.objective_digest(),
        authority_epoch: verifier.authority_epoch(),
        issued_at: now,
        expires_at: now
            .checked_add(EVIDENCE_LIFETIME_MS)
            .ok_or("evidence expiry overflow")?,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    Ok(evidence)
}

// The only sealed value in this fixture is returned by the public selection API.
// Registry mutation uses signed final-use grants; pricing has distinct, signed
// generator/evaluator principals and controllers. No private context is minted.
fn selected() -> TestResult<VerifiedSelectedPromptPortfolioV2> {
    let directory = tempfile::tempdir()?;
    let root = directory.path().canonicalize()?;
    let capacity = 64;
    let mut registry = DurablePromptRegistry::open_state_dir(&root.join("registry"), capacity)?;
    let authority_key = SigningKey::from_bytes(&[23; 32]);
    let authority = FinalUseAuthority::open_state_dir(
        &root.join("authority"),
        "review-authority:prompt".to_owned(),
        authority_key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )?;
    let now = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
    let not_before_unix_ms = now.saturating_sub(CLOCK_MARGIN_MS);
    let grant_expiry = now
        .checked_add(GRANT_LIFETIME_MS)
        .ok_or("grant expiry overflow")?;
    let tuple = PromptModelTupleV2 {
        model_id: id("model:test")?,
        model_version: "2026-09-21".to_owned(),
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tools"),
        context_profile_digest: digest("context-profile"),
        locale_id: id("locale:en-US")?,
    };
    let factor_ids = [id("factor:a")?, id("factor:b")?];
    let reviewer = id("reviewer:prompt")?;
    let publisher = id("publisher:prompt")?;
    let scope = digest("scope:prompt");
    let admission_evidence = digest("evidence:prompt");
    for (index, factor_id) in factor_ids.iter().enumerate() {
        let factor = PromptFactor {
            factor_id: factor_id.clone(),
            proposer_id: id("proposer:prompt")?,
            semantic_version: id("version:1")?,
            semantic_purpose: "inspect evidence before mutation".to_owned(),
            authority_class: "registered_prompt_factor".to_owned(),
            eligible_objective_dimensions: vec![id("dimension:truth")?],
            content_digest: Digest32::of_bytes(factor_id.as_str().as_bytes()),
            source: FactorSource::GovernedInternal,
            lifecycle: Lifecycle::Draft,
        };
        registry.register_factor(factor.clone())?;
        let binding = final_use_admission_binding(&factor, &reviewer, scope, admission_evidence)?;
        let admission = sign_grant(
            FinalUseGrant {
                schema_version: 1,
                signer_id: "review-authority:prompt".to_owned(),
                authority_epoch: 1,
                grant_id: format!("admission:{factor_id}"),
                nonce: [u8::try_from(index + 1)?; 32],
                binding,
                not_before_unix_ms,
                expires_at_unix_ms: grant_expiry,
            },
            &authority_key,
        )?;
        registry.admit_factor_final_use(
            &authority,
            &admission,
            factor_id,
            scope,
            admission_evidence,
        )?;
        let admitted = registry
            .registry()?
            .factor(factor_id)
            .cloned()
            .ok_or("admitted factor missing")?;
        let payload = format!("payload:{factor_id}").into_bytes();
        let realization = PromptRealizationBindingV2 {
            realization_id: id(&format!("realization:{index}"))?,
            factor_id: factor_id.clone(),
            model_id: tuple.model_id.clone(),
            model_version: tuple.model_version.clone(),
            model_digest: tuple.model_digest,
            tokenizer_digest: tuple.tokenizer_digest,
            template_digest: tuple.template_digest,
            tool_schema_digest: tuple.tool_schema_digest,
            context_profile_digest: tuple.context_profile_digest,
            locale_id: tuple.locale_id.clone(),
            role: PromptRoleV2::DeveloperInstruction,
            payload_digest: Digest32::of_bytes(&payload),
            token_cost: 4,
            expires_unix_ms: None,
        };
        let previous: Option<StableId> = None;
        let binding = final_use_realization_binding(
            &admitted,
            &publisher,
            scope,
            &realization,
            previous.as_ref(),
        )?;
        let registration = sign_grant(
            FinalUseGrant {
                schema_version: 1,
                signer_id: "review-authority:prompt".to_owned(),
                authority_epoch: 1,
                grant_id: format!("realization:{factor_id}"),
                nonce: [u8::try_from(index + 3)?; 32],
                binding,
                not_before_unix_ms,
                expires_at_unix_ms: grant_expiry,
            },
            &authority_key,
        )?;
        registry.register_realization_payload_final_use_v2(
            &authority,
            &registration,
            &publisher,
            scope,
            realization,
            payload,
            previous,
        )?;
    }

    let candidates = enumerate_verified_factors_v2(
        registry.registry()?,
        PromptEnumerationRequestV1 {
            set_id: id("set:public")?,
            objective_digest: digest("objective"),
            state_digest: digest("state"),
            generation_vector_digest: digest("generation-vector"),
            model_tuple: tuple,
            now_unix_ms: now,
            required_factor_ids: factor_ids.to_vec(),
            maximum_candidates: 2,
            selection_grammar_digest: digest("grammar"),
        },
    )?;
    let generator_key = SigningKey::from_bytes(&[31; 32]);
    let evaluator_key = SigningKey::from_bytes(&[47; 32]);
    let mut signers = Vec::new();
    for (principal_id, role, key) in [
        (
            "prompt.optimizer",
            LearningEvidenceRoleV1::Generator,
            &generator_key,
        ),
        (
            "principal:evaluator",
            LearningEvidenceRoleV1::Evaluator,
            &evaluator_key,
        ),
    ] {
        let verifying_key = key.verifying_key().to_bytes();
        signers.push(TrustedLearningSignerV1 {
            principal: AuthenticatedPrincipalV1 {
                principal_id: id(principal_id)?,
                credential_chain_digest: digest(&format!("credential:{principal_id}")),
                signing_key_digest: Digest32::of_bytes(&verifying_key),
                scope_digest: candidates.scope_digest(),
                authority_epoch: 1,
                authenticated_at: now,
                expires_at: grant_expiry,
            },
            controller_id: id(&format!("controller:{principal_id}"))?,
            verifying_key,
            roles: vec![role],
            revoked_at: None,
        });
    }
    let raw = candidates.canonical();
    let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: candidates.scope_digest(),
        objective_digest: raw.receipt.objective_digest,
        authority_epoch: 1,
        signers,
    })?;
    let completeness = CandidateSetCompletenessReceiptV1 {
        set_id: raw.receipt.set_id.clone(),
        state_digest: raw.receipt.state_digest,
        generator_id: id("prompt.optimizer")?,
        generator_code_digest: digest("generator-code"),
        grammar_digest: raw.receipt.selection_grammar_digest,
        hard_filter_digest: digest("hard-filter"),
        truncation_digest: digest("truncation"),
        candidates_digest: raw.candidates_digest,
        candidate_count: u32::try_from(raw.candidates.len())?,
        omitted_count_bound: raw.omitted_count,
        canonical_order_digest: raw.canonical_order_digest,
        complete_for_generator: true,
    };
    let completeness_evidence = attest(
        &verifier,
        &generator_key,
        "prompt.optimizer",
        LearningEvidenceRoleV1::Generator,
        "evidence:completeness",
        &candidate_completeness_signing_payload_v1(&completeness)?,
        now,
    )?;
    let policy = PromptPricingPolicyV1 {
        policy_id: id("policy:pricing")?,
        token_cost_per_token_q32: FixedQ32::ZERO,
        latency_cost_per_micro_q32: FixedQ32::ZERO,
        interference_cost_per_ppm_q32: FixedQ32::ZERO,
        downside_weight_q32: FixedQ32::ZERO,
        minimum_support_count: 1,
        maximum_interference_ppm: 0,
    };
    let utility_raw = 100;
    let utility = FixedQ32::from_raw(utility_raw);
    let mut rows = Vec::new();
    for candidate in &raw.candidates {
        let evidence_id = format!("evidence:{}", candidate.factor_id);
        let mut evidence = PromptPricingEvidenceV1 {
            factor_id: candidate.factor_id.clone(),
            state_digest: raw.receipt.state_digest,
            model_tuple_digest: raw.model_tuple.digest(),
            expected_incremental_utility_q32: utility,
            downside_q32: FixedQ32::ZERO,
            confidence_lower_q32: utility,
            confidence_upper_q32: utility,
            support_count: 1,
            latency_cost_micros: 0,
            interference_ppm: 0,
            context_crowding_cost_q32: FixedQ32::ZERO,
            privacy_cost_q32: FixedQ32::ZERO,
            instability_cost_q32: FixedQ32::ZERO,
            future_context_option_cost_q32: FixedQ32::ZERO,
            support_audit_digest: digest("support-audit"),
            evidence: attest(
                &verifier,
                &evaluator_key,
                "principal:evaluator",
                LearningEvidenceRoleV1::Evaluator,
                &evidence_id,
                &[],
                now,
            )?,
        };
        evidence.evidence = attest(
            &verifier,
            &evaluator_key,
            "principal:evaluator",
            LearningEvidenceRoleV1::Evaluator,
            &evidence_id,
            &pricing_evidence_signing_payload_v1(&evidence),
            now,
        )?;
        rows.push(BoundPromptPricingEvidenceV2 {
            candidate_set_digest: raw.candidates_digest,
            registry_snapshot_digest: raw.registry_snapshot.snapshot_digest,
            generation_vector_digest: raw.generation_vector_digest,
            realization_id: candidate.realization.realization_id.clone(),
            realization_binding_digest: candidate.binding_digest,
            pricing_policy_digest: policy.digest()?,
            evidence,
        });
    }

    let mut nodes = Vec::new();
    let revision_value = 1;
    for factor_id in &factor_ids {
        nodes.push(KnowledgeNodeV2 {
            node_id: factor_id.clone(),
            node_kind_id: id("kind:prompt-factor")?,
            payload_digest: digest(&format!("node:{factor_id}")),
            supports: vec![KnowledgeSupportV2 {
                source_id: id(&format!("support:{factor_id}"))?,
                source_revision: Revision::new(revision_value)?,
                source_fact_digest: digest(&format!("fact:{factor_id}")),
                validity_digest: digest(&format!("validity:{factor_id}")),
                valid_from_unix_seconds: None,
                valid_to_unix_seconds: None,
                tombstoned: false,
            }],
        });
    }
    let generation_value = 1;
    let graph = build_complete_generation(
        Generation::new(generation_value)?,
        KnowledgeProjectionInputV2 {
            source_snapshot_digest: digest("graph-source"),
            generation_vector_digest: raw.generation_vector_digest,
            graph_profile_digest: digest("graph-profile"),
            complete_source_cut: true,
            nodes,
            edges: Vec::new(),
        },
    )?;
    let priced = price_verified_factors_v2(
        candidates,
        &completeness,
        &completeness_evidence,
        rows,
        &verifier,
        &policy,
        now,
    )?;
    let selected = select_verified_portfolio_v2(
        &priced,
        &graph,
        Vec::new(),
        &verifier,
        PromptPortfolioRequestV1 {
            portfolio_id: id("portfolio:public")?,
            graph_query_id: id("query:public")?,
            token_budget: 8,
            maximum_selected_factors: 2,
            requested_valid_until_unix_ms: now
                .checked_add(SELECTION_LIFETIME_MS)
                .ok_or("selection expiry overflow")?,
        },
        now,
    )?;
    assert_eq!(selected.canonical().receipt.factor_ids, factor_ids.to_vec());
    assert_eq!(
        selected.canonical().receipt.authority,
        AuthorityPosture::DENY_ALL
    );
    Ok(selected)
}

// Reproduce the public V1 receipt format as an external attacker can. This must
// match a genuine receipt before any mutation, so a negative result cannot be
// attributed to a bogus digest helper.
fn receipt_digest(value: &SelectedPromptPortfolioV1) -> TestResult<Digest32> {
    let receipt = &value.receipt;
    let mut bytes = b"hepta.prompt-optimizer.portfolio-receipt.v1".to_vec();
    let portfolio_id = receipt.portfolio_id.as_str().as_bytes();
    bytes.extend_from_slice(&u64::try_from(portfolio_id.len())?.to_be_bytes());
    bytes.extend_from_slice(portfolio_id);
    for digest in [
        receipt.candidate_set_digest,
        receipt.interaction_digest,
        value.pricing_set_digest,
        value.graph_generation_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&u64::try_from(receipt.factor_ids.len())?.to_be_bytes());
    for factor_id in &receipt.factor_ids {
        let bytes_id = factor_id.as_str().as_bytes();
        bytes.extend_from_slice(&u64::try_from(bytes_id.len())?.to_be_bytes());
        bytes.extend_from_slice(bytes_id);
    }
    bytes.extend_from_slice(&receipt.expected_utility_q32.raw().to_be_bytes());
    bytes.extend_from_slice(&receipt.total_token_upper_bound.to_be_bytes());
    bytes.extend_from_slice(&receipt.valid_until_unix_ms.to_be_bytes());
    bytes.extend_from_slice(&[0, 0]);
    Ok(Digest32::of_bytes(&bytes))
}

fn assert_postimage_rejected(
    selected: &VerifiedSelectedPromptPortfolioV2,
    mut forged: SelectedPromptPortfolioV1,
) -> TestResult {
    assert_eq!(
        receipt_digest(selected.canonical())?,
        selected.canonical().receipt.receipt_digest
    );
    forged.receipt.receipt_digest = receipt_digest(&forged)?;
    assert_eq!(
        verify_selected_prompt_portfolio_v2(forged, selected.context().clone()),
        Err(VerifiedPromptErrorV2::IdentityMismatch(
            "selected portfolio postimage"
        ))
    );
    Ok(())
}

#[test]
fn genuine_public_selection_reopens_with_its_immutable_context() -> TestResult {
    let selected = selected()?;
    assert_eq!(
        receipt_digest(selected.canonical())?,
        selected.canonical().receipt.receipt_digest
    );
    assert_eq!(
        verify_selected_prompt_portfolio_v2(
            selected.canonical().clone(),
            selected.context().clone()
        )?,
        selected
    );
    Ok(())
}

#[test]
fn recomputing_receipt_hash_cannot_change_utility() -> TestResult {
    let selected = selected()?;
    let mut forged = selected.canonical().clone();
    let increment = 1;
    let raw = forged
        .receipt
        .expected_utility_q32
        .raw()
        .checked_add(increment)
        .ok_or("utility overflow")?;
    forged.receipt.expected_utility_q32 = FixedQ32::from_raw(raw);
    assert_postimage_rejected(&selected, forged)
}

#[test]
fn recomputing_receipt_hash_cannot_change_interactions() -> TestResult {
    let selected = selected()?;
    let mut forged = selected.canonical().clone();
    forged.receipt.interaction_digest = digest("forged interaction");
    assert_postimage_rejected(&selected, forged)
}

#[test]
fn recomputing_receipt_hash_cannot_extend_expiry() -> TestResult {
    let selected = selected()?;
    let mut forged = selected.canonical().clone();
    let increment = 1;
    forged.receipt.valid_until_unix_ms = forged
        .receipt
        .valid_until_unix_ms
        .checked_add(increment)
        .ok_or("expiry overflow")?;
    assert_postimage_rejected(&selected, forged)
}

#[test]
fn self_consistent_realization_replacement_cannot_change_selected_entries() -> TestResult {
    let selected = selected()?;
    let mut forged = selected.canonical().clone();
    let first = forged
        .selected
        .first_mut()
        .ok_or("selected entry missing")?;
    first.realization.payload_digest = digest("forged realization payload");
    first.binding_digest = first.realization.digest();
    assert_postimage_rejected(&selected, forged)
}

#[test]
fn self_consistent_subset_cannot_drop_selected_entries() -> TestResult {
    let selected = selected()?;
    let mut forged = selected.canonical().clone();
    forged.selected.pop().ok_or("selected entry missing")?;
    forged.receipt.factor_ids = forged
        .selected
        .iter()
        .map(|entry| entry.factor_id.clone())
        .collect();
    forged.receipt.total_token_upper_bound = forged
        .selected
        .iter()
        .try_fold(/*init*/ 0_u32, |total, entry| {
            total.checked_add(entry.realization.token_cost)
        })
        .ok_or("selected token total overflow")?;
    assert_postimage_rejected(&selected, forged)
}

#[test]
fn reordered_entries_keep_the_original_order_error() -> TestResult {
    let selected = selected()?;
    let mut forged = selected.canonical().clone();
    forged.selected.reverse();
    forged.receipt.factor_ids.reverse();
    forged.receipt.receipt_digest = receipt_digest(&forged)?;
    assert_eq!(
        verify_selected_prompt_portfolio_v2(forged, selected.context().clone()),
        Err(VerifiedPromptErrorV2::NonCanonicalOrder(
            "selected factor order"
        ))
    );
    Ok(())
}

#[test]
fn missing_recomputed_hash_keeps_the_original_digest_error() -> TestResult {
    let selected = selected()?;
    let mut forged = selected.canonical().clone();
    forged.receipt.interaction_digest = digest("forged interaction");
    assert_eq!(
        verify_selected_prompt_portfolio_v2(forged, selected.context().clone()),
        Err(VerifiedPromptErrorV2::DigestMismatch("portfolio receipt"))
    );
    Ok(())
}

#[test]
fn shorter_expiry_keeps_the_original_context_error() -> TestResult {
    let selected = selected()?;
    let mut forged = selected.canonical().clone();
    let decrement = 1;
    forged.receipt.valid_until_unix_ms = selected
        .context()
        .valid_until_unix_ms()
        .checked_sub(decrement)
        .ok_or("expiry underflow")?;
    forged.receipt.receipt_digest = receipt_digest(&forged)?;
    assert_eq!(
        verify_selected_prompt_portfolio_v2(forged, selected.context().clone()),
        Err(VerifiedPromptErrorV2::IdentityMismatch(
            "portfolio verification context"
        ))
    );
    Ok(())
}
