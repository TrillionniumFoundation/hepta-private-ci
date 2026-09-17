//! Named composition path for the canonical prompt policy.
//!
//! `intelligence.control` sequences owner-native, authority-free modules. It does
//! not become the owner of prompt registry facts, optimizer receipts, context
//! compilation facts or runtime delivery observations.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_context_compiler::CompiledContextV2;
use codex_hepta_context_compiler::ContextCandidateV2;
use codex_hepta_context_compiler::ContextCanonicalV1Error;
use codex_hepta_context_compiler::ContextCompilationReceiptV1;
use codex_hepta_context_compiler::ContextCompilationRequestV2;
use codex_hepta_context_compiler::ContextCompilerV2Error;
use codex_hepta_context_compiler::ContextModelProfileV2;
use codex_hepta_context_compiler::ContextRoleV2;
use codex_hepta_context_compiler::MandatoryContextGroupV2;
use codex_hepta_context_compiler::TokenizationReceiptV2;
use codex_hepta_context_compiler::compile_v2;
use codex_hepta_prompt_optimizer::canonical_v1::CandidateEnumerationRequestV1;
use codex_hepta_prompt_optimizer::canonical_v1::CanonicalPromptError;
use codex_hepta_prompt_optimizer::canonical_v1::EnumeratedPromptCandidatesV1;
use codex_hepta_prompt_optimizer::canonical_v1::ExerciseDispositionV1;
use codex_hepta_prompt_optimizer::canonical_v1::ExerciseRequestV1;
use codex_hepta_prompt_optimizer::canonical_v1::PortfolioSelectionRequestV1;
use codex_hepta_prompt_optimizer::canonical_v1::PromptExerciseResultV1;
use codex_hepta_prompt_optimizer::canonical_v1::PromptPortfolioBundleV1;
use codex_hepta_prompt_optimizer::canonical_v1::PromptPricingPolicyV1;
use codex_hepta_prompt_optimizer::canonical_v1::PromptPricingSetV1;
use codex_hepta_prompt_optimizer::canonical_v1::VerifiedPromptPricingEvidenceV1;
use codex_hepta_prompt_optimizer::canonical_v1::enumerate_factors_v1;
use codex_hepta_prompt_optimizer::canonical_v1::exercise_v1;
use codex_hepta_prompt_optimizer::canonical_v1::price_factors_v1;
use codex_hepta_prompt_optimizer::canonical_v1::select_portfolio_v1;
use codex_hepta_prompt_registry::PromptModelTupleV2;
use codex_hepta_prompt_registry::PromptRegistry;
use codex_hepta_prompt_registry::PromptRoleV2;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPolicyContextRequestV1 {
    pub compilation_id: StableId,
    pub model_profile: ContextModelProfileV2,
    pub token_budget: u64,
    pub truncation_policy_digest: Digest32,
    pub additional_candidates: Vec<ContextCandidateV2>,
    pub mandatory_groups: Vec<MandatoryContextGroupV2>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalPromptPolicyRequestV1 {
    pub enumeration: CandidateEnumerationRequestV1,
    pub pricing_evidence: Vec<VerifiedPromptPricingEvidenceV1>,
    pub pricing_policy: PromptPricingPolicyV1,
    pub portfolio: PortfolioSelectionRequestV1,
    pub exercise: ExerciseRequestV1,
    pub context: PromptPolicyContextRequestV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalPromptPolicyReceiptV1 {
    pub candidates: EnumeratedPromptCandidatesV1,
    pub pricing: PromptPricingSetV1,
    pub portfolio: PromptPortfolioBundleV1,
    pub exercise: PromptExerciseResultV1,
    pub compiled_context: Option<CompiledContextV2>,
    pub canonical_context: Option<ContextCompilationReceiptV1>,
    pub trace_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PromptPolicyErrorV1 {
    Optimizer(CanonicalPromptError),
    Context(ContextCompilerV2Error),
    ContextCanonical(ContextCanonicalV1Error),
    ContextModelTupleMismatch,
    MissingSelectedPrice(String),
    Arithmetic,
}

impl fmt::Display for PromptPolicyErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PromptPolicyErrorV1 {}

impl From<CanonicalPromptError> for PromptPolicyErrorV1 {
    fn from(value: CanonicalPromptError) -> Self {
        Self::Optimizer(value)
    }
}

impl From<ContextCompilerV2Error> for PromptPolicyErrorV1 {
    fn from(value: ContextCompilerV2Error) -> Self {
        Self::Context(value)
    }
}

impl From<ContextCanonicalV1Error> for PromptPolicyErrorV1 {
    fn from(value: ContextCanonicalV1Error) -> Self {
        Self::ContextCanonical(value)
    }
}

/// Run the canonical prompt policy and, unless delivery-boundary revalidation
/// rejects the proposal, compile the selected prompt realizations into the
/// existing Context V2 chain plus its registered V1 cross-module receipt.
///
/// A `Wait` decision still compiles the caller's non-prompt context with no
/// prompt realization added. A `Reject` decision does not compile at all: the
/// caller must obtain a fresh snapshot instead of attaching stale context.
pub fn run_canonical_prompt_policy_v1(
    registry: &PromptRegistry,
    request: CanonicalPromptPolicyRequestV1,
) -> Result<CanonicalPromptPolicyReceiptV1, PromptPolicyErrorV1> {
    let CanonicalPromptPolicyRequestV1 {
        enumeration,
        pricing_evidence,
        pricing_policy,
        portfolio: portfolio_request,
        exercise: exercise_request,
        context,
    } = request;

    let candidates = enumerate_factors_v1(registry, enumeration)?;
    let pricing = price_factors_v1(&candidates, pricing_evidence, &pricing_policy)?;
    let portfolio = select_portfolio_v1(&pricing, portfolio_request)?;
    let exercise = exercise_v1(
        registry,
        &candidates,
        &pricing,
        &portfolio,
        exercise_request,
    )?;

    let compiled_context = if exercise.receipt.decision == ExerciseDispositionV1::Reject {
        None
    } else {
        ensure_context_profile_matches(&candidates.model_tuple, &context.model_profile)?;
        let mut context_candidates = context.additional_candidates;
        if exercise.receipt.decision == ExerciseDispositionV1::Exercise {
            append_prompt_candidates(
                &mut context_candidates,
                &candidates,
                &pricing,
                &portfolio,
            )?;
        }
        Some(compile_v2(ContextCompilationRequestV2 {
            compilation_id: context.compilation_id,
            objective_digest: candidates.receipt.objective_digest,
            prompt_portfolio_digest: portfolio.receipt.receipt_digest,
            generation_vector_digest: candidates.registry_snapshot.generation_vector_digest,
            model_profile: context.model_profile,
            token_budget: context.token_budget,
            truncation_policy_digest: context.truncation_policy_digest,
            candidates: context_candidates,
            mandatory_groups: context.mandatory_groups,
        })?)
    };
    let canonical_context = compiled_context
        .as_ref()
        .map(|compiled| {
            ContextCompilationReceiptV1::from_compiled_v2(
                compiled,
                candidates.model_tuple.digest(),
            )
        })
        .transpose()?;

    let mut bytes = b"hepta.intelligence.canonical-prompt-policy.v1".to_vec();
    for digest in [
        candidates.receipt.receipt_digest,
        candidates.completeness_digest,
        pricing.set_digest,
        portfolio.receipt.receipt_digest,
        exercise.receipt.receipt_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    match &canonical_context {
        Some(receipt) => {
            bytes.push(1);
            bytes.extend_from_slice(receipt.receipt_digest.as_array());
        }
        None => bytes.push(0),
    }

    Ok(CanonicalPromptPolicyReceiptV1 {
        candidates,
        pricing,
        portfolio,
        exercise,
        compiled_context,
        canonical_context,
        trace_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn ensure_context_profile_matches(
    model_tuple: &PromptModelTupleV2,
    profile: &ContextModelProfileV2,
) -> Result<(), PromptPolicyErrorV1> {
    profile.validate()?;
    if model_tuple.model_digest != profile.model_digest
        || model_tuple.tokenizer_digest != profile.tokenizer_digest
        || model_tuple.template_digest != profile.template_digest
        || model_tuple.tool_schema_digest != profile.tool_schema_digest
    {
        return Err(PromptPolicyErrorV1::ContextModelTupleMismatch);
    }
    Ok(())
}

fn append_prompt_candidates(
    output: &mut Vec<ContextCandidateV2>,
    candidates: &EnumeratedPromptCandidatesV1,
    pricing: &PromptPricingSetV1,
    portfolio: &PromptPortfolioBundleV1,
) -> Result<(), PromptPolicyErrorV1> {
    for factor_id in &portfolio.receipt.factor_ids {
        let Some(priced) = pricing.price_for(factor_id) else {
            return Err(PromptPolicyErrorV1::MissingSelectedPrice(
                factor_id.to_string(),
            ));
        };
        let expected_value = priced
            .receipt
            .expected_utility_q32
            .clamp(FixedQ32::ZERO, FixedQ32::ONE)
            .map_err(|_| PromptPolicyErrorV1::Arithmetic)?;
        let role = match priced.realization.role {
            PromptRoleV2::ToolSchemaFragment => ContextRoleV2::Schema,
            PromptRoleV2::SystemInstruction
            | PromptRoleV2::DeveloperInstruction
            | PromptRoleV2::UserTemplate => ContextRoleV2::TrustedInstruction,
        };
        let tokenization = TokenizationReceiptV2::new(
            priced.realization.realization_id.clone(),
            priced.realization.payload_digest,
            priced.realization.tokenizer_digest,
            u64::from(priced.realization.token_cost),
        )?;
        output.push(ContextCandidateV2 {
            item_id: priced.realization.realization_id.clone(),
            role,
            content_digest: priced.realization.payload_digest,
            source_digest: priced.receipt.receipt_digest,
            generation_vector_digest: candidates.registry_snapshot.generation_vector_digest,
            tokenization,
            expected_value,
            trusted_admission_digest: Some(candidates.registry_snapshot.snapshot_digest),
            contains_secret: false,
        });
    }
    Ok(())
}
