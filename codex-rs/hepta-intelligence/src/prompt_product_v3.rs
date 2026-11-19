//! Canonical product composition for registry-owned prompt context.
//!
//! V3 removes the two provisional adapters used by the compatibility path:
//! token counts are obtained from a qualified tokenizer over the actual bytes,
//! and serialization is a crate-owned canonical function of the typed selected
//! items.  Admission evidence is issued only by the durable prompt registry's
//! opaque context authority snapshot.  The physical provider effect remains in
//! runtime.codex; this module prepares and observes the exact V2 compiler proof
//! objects without minting provider authority.

use std::collections::BTreeMap;
use std::fmt;

use codex_hepta_context_compiler::CompiledContextV2;
use codex_hepta_context_compiler::ContextAdmissionBindingV2;
use codex_hepta_context_compiler::ContextAdmissionRecordV2;
use codex_hepta_context_compiler::ContextAdmissionSnapshotV2;
use codex_hepta_context_compiler::ContextAdmissionVerifierV2;
use codex_hepta_context_compiler::ContextAttachmentV2;
use codex_hepta_context_compiler::ContextCandidateV2;
use codex_hepta_context_compiler::ContextCompilationRequestV2;
use codex_hepta_context_compiler::ContextCompilerV2Error;
use codex_hepta_context_compiler::ContextDeliveryPreparationV2;
use codex_hepta_context_compiler::ContextDeliveryReceiptV2;
use codex_hepta_context_compiler::ContextModelProfileV2;
use codex_hepta_context_compiler::ContextProviderDeliveryVerifierV2;
use codex_hepta_context_compiler::ContextRealizedItemV2;
use codex_hepta_context_compiler::ContextRoleV2;
use codex_hepta_context_compiler::ContextSerializerV2;
use codex_hepta_context_compiler::ExactTokenizerV2;
use codex_hepta_context_compiler::MandatoryContextGroupV2;
use codex_hepta_context_compiler::SerializedContextV2;
use codex_hepta_context_compiler::TokenizationReceiptV2;
use codex_hepta_context_compiler::VerifiedAdmissionSnapshotV2;
use codex_hepta_context_compiler::build_attachment;
use codex_hepta_context_compiler::compile_v2;
use codex_hepta_context_compiler::observe_delivery;
use codex_hepta_context_compiler::prepare_delivery_v2;
use codex_hepta_context_compiler::record_serialization;
use codex_hepta_context_compiler::verify_admission_snapshot_successor_v2;
use codex_hepta_context_compiler::verify_admission_snapshot_v2;
use codex_hepta_context_compiler::verify_admission_v2;
use codex_hepta_contracts::ProviderInvocationReceipt;
use codex_hepta_prompt_optimizer::canonical::PromptExerciseActionV1;
use codex_hepta_prompt_optimizer::canonical::PromptExerciseRequestV1;
use codex_hepta_prompt_optimizer::canonical::SelectedPromptPortfolioV1;
use codex_hepta_prompt_optimizer::canonical::exercise_v1;
use codex_hepta_prompt_registry::DurablePromptRegistry;
use codex_hepta_prompt_registry::PromptContextAuthorityAdmissionV3;
use codex_hepta_prompt_registry::PromptContextAuthoritySnapshotV3;
use codex_hepta_prompt_registry::PromptContextAuthoritySuccessorV3;
use codex_hepta_prompt_registry::PromptModelTupleV2;
use codex_hepta_prompt_registry::PromptRoleV2;
use codex_hepta_prompt_registry::RealizationDeliveryV2;
use codex_hepta_prompt_registry::prompt_context_authority_verifier_digest_v3;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use serde::Serialize;

const SCOPE_DOMAIN: &[u8] = b"hepta.prompt-product.context-scope.v3";
const AUTHORITY_DOMAIN: &[u8] = b"hepta.prompt-product.authority-domain.v3";
const PROFILE_DOMAIN: &[u8] = b"hepta.prompt-product.execution-profile.v3";
const TOKENIZER_IDENTITY_DOMAIN: &[u8] = b"hepta.prompt-product.tokenizer-identity.v3";
const SERIALIZER_DOMAIN: &[u8] = b"hepta.prompt-product.canonical-serializer.v3";
const TRUNCATION_PROFILE_DOMAIN: &[u8] = b"hepta.prompt-product.truncation-profile.v3";
const SOURCE_BINDING_DOMAIN: &[u8] = b"hepta.prompt-product.source-binding.v3";
const TOKENIZATION_PROOF_DOMAIN: &[u8] = b"hepta.prompt-product.tokenization-proof.v3";
const SELECTED_PROMPT_GROUP_ID: &str = "prompt:exercise-selected:v3";
const CANONICAL_BUNDLE_SCHEMA: &str = "hepta.prompt-context.v3";

/// Full tokenizer identity used to qualify an exact model tokenizer.
/// `tokenizer_digest` is the digest registered in the prompt model tuple; the
/// other fields prevent two binaries or vocabularies from reusing that label in
/// the V3 execution profile.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptTokenizerIdentityV3 {
    pub tokenizer_digest: Digest32,
    pub binary_digest: Digest32,
    pub vocabulary_digest: Digest32,
    pub normalization_policy_digest: Digest32,
    pub version: String,
}

impl PromptTokenizerIdentityV3 {
    pub fn validate(&self) -> Result<(), PromptProductV3Error> {
        for digest in [
            self.tokenizer_digest,
            self.binary_digest,
            self.vocabulary_digest,
            self.normalization_policy_digest,
        ] {
            ensure_digest(digest)?;
        }
        validate_revision(&self.version)?;
        Ok(())
    }

    #[must_use]
    pub fn identity_digest(&self) -> Digest32 {
        let mut bytes = TOKENIZER_IDENTITY_DOMAIN.to_vec();
        for digest in [
            self.tokenizer_digest,
            self.binary_digest,
            self.vocabulary_digest,
            self.normalization_policy_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        push_text(&mut bytes, &self.version);
        Digest32::of_bytes(&bytes)
    }
}

/// Host-supplied exact tokenizer.  Implementations must execute the tokenizer
/// identified by `identity` over the bytes supplied to `count_tokens`; lookup
/// tables keyed by a pre-recorded digest are not valid V3 implementations.
pub trait PromptExactTokenizerV3: Send + Sync {
    fn identity(&self) -> PromptTokenizerIdentityV3;

    fn count_tokens(&self, bytes: &[u8]) -> Result<u64, String>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptExecutionProfileV3 {
    pub provider_id: String,
    pub provider_revision: String,
    pub provider_model: String,
    pub model_revision: String,
    pub tokenizer: PromptTokenizerIdentityV3,
    pub serializer_revision: String,
    pub template_digest: Digest32,
    pub template_revision: String,
    pub tool_schema_digest: Digest32,
    pub tool_schema_revision: String,
    pub maximum_context_tokens: u64,
}

impl PromptExecutionProfileV3 {
    pub fn validate_for(
        &self,
        tuple: &PromptModelTupleV2,
    ) -> Result<(), PromptProductV3Error> {
        tuple
            .validate()
            .map_err(|error| PromptProductV3Error::Registry(error.to_string()))?;
        validate_revision(&self.provider_id)?;
        validate_revision(&self.provider_revision)?;
        validate_revision(&self.provider_model)?;
        validate_revision(&self.model_revision)?;
        validate_revision(&self.serializer_revision)?;
        validate_revision(&self.template_revision)?;
        validate_revision(&self.tool_schema_revision)?;
        self.tokenizer.validate()?;
        ensure_digest(self.template_digest)?;
        ensure_digest(self.tool_schema_digest)?;
        if self.model_revision != tuple.model_version
            || self.tokenizer.tokenizer_digest != tuple.tokenizer_digest
            || self.template_digest != tuple.template_digest
            || self.tool_schema_digest != tuple.tool_schema_digest
            || self.maximum_context_tokens == 0
            || self.maximum_context_tokens > codex_hepta_context_compiler::MAX_CONTEXT_TOKENS_V2
        {
            return Err(PromptProductV3Error::ProfileMismatch);
        }
        Ok(())
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = PROFILE_DOMAIN.to_vec();
        for value in [
            &self.provider_id,
            &self.provider_revision,
            &self.provider_model,
            &self.model_revision,
            &self.serializer_revision,
            &self.template_revision,
            &self.tool_schema_revision,
        ] {
            push_text(&mut bytes, value);
        }
        bytes.extend_from_slice(self.tokenizer.identity_digest().as_array());
        bytes.extend_from_slice(self.template_digest.as_array());
        bytes.extend_from_slice(self.tool_schema_digest.as_array());
        bytes.extend_from_slice(&self.maximum_context_tokens.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }

    #[must_use]
    pub fn serializer_digest(&self) -> Digest32 {
        let mut bytes = SERIALIZER_DOMAIN.to_vec();
        bytes.extend_from_slice(self.digest().as_array());
        push_text(&mut bytes, &self.serializer_revision);
        Digest32::of_bytes(&bytes)
    }

    fn context_model_profile(&self, tuple: &PromptModelTupleV2) -> ContextModelProfileV2 {
        ContextModelProfileV2 {
            model_digest: tuple.model_digest,
            provider_id_digest: Digest32::of_bytes(self.provider_id.as_bytes()),
            provider_model_digest: Digest32::of_bytes(self.provider_model.as_bytes()),
            tokenizer_digest: self.tokenizer.tokenizer_digest,
            serializer_digest: self.serializer_digest(),
            template_digest: self.template_digest,
            tool_schema_digest: self.tool_schema_digest,
            maximum_context_tokens: self.maximum_context_tokens,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRegistryCompilationRequestV3 {
    pub compilation_id: StableId,
    pub serialization_id: StableId,
    pub attachment_id: StableId,
    pub registry_model_tuple: PromptModelTupleV2,
    pub execution_profile: PromptExecutionProfileV3,
    pub now_unix_ms: u64,
    pub token_budget: u64,
    pub truncation_policy_digest: Digest32,
}

#[derive(Clone, Eq, PartialEq)]
pub struct PromptRegistryCompiledContextV3 {
    pub compiled: CompiledContextV2,
    pub model_profile: ContextModelProfileV2,
    pub execution_profile: PromptExecutionProfileV3,
    pub selected_deliveries: Vec<RealizationDeliveryV2>,
    pub serialized_context: SerializedContextV2,
    pub attachment: ContextAttachmentV2,
    authority_snapshot: PromptContextAuthoritySnapshotV3,
    verified_snapshot: VerifiedAdmissionSnapshotV2,
    model_tuple: PromptModelTupleV2,
    generation_vector_digest: Digest32,
    exercise_receipt_digest: Digest32,
    portfolio_receipt_digest: Digest32,
    portfolio_valid_until_unix_ms: u64,
    source_binding_digest: Digest32,
    tokenization_proof_digest: Digest32,
    authority: AuthorityPosture,
}

impl PromptRegistryCompiledContextV3 {
    #[must_use]
    pub fn payload(&self) -> &[u8] {
        self.serialized_context.payload()
    }

    #[must_use]
    pub const fn source_binding_digest(&self) -> Digest32 {
        self.source_binding_digest
    }

    #[must_use]
    pub const fn tokenization_proof_digest(&self) -> Digest32 {
        self.tokenization_proof_digest
    }

    #[must_use]
    pub const fn execution_profile_digest(&self) -> Digest32 {
        self.source_binding_digest
    }

    #[must_use]
    pub const fn portfolio_valid_until_unix_ms(&self) -> u64 {
        self.portfolio_valid_until_unix_ms
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }

    pub fn validate(&self) -> Result<(), PromptProductV3Error> {
        self.compiled
            .validate()
            .map_err(PromptProductV3Error::Context)?;
        self.execution_profile.validate_for(&self.model_tuple)?;
        self.serialized_context
            .validate_for(&self.compiled, &self.model_profile)
            .map_err(PromptProductV3Error::Context)?;
        self.attachment
            .validate_for(&self.compiled, &self.serialized_context, &self.model_profile)
            .map_err(PromptProductV3Error::Context)?;
        self.authority_snapshot
            .validate()
            .map_err(|error| PromptProductV3Error::Registry(error.to_string()))?;
        if self.selected_deliveries.is_empty()
            || self.selected_deliveries.len()
                != self.compiled.receipt().selected_item_ids().len()
            || self.authority.grants_any()
            || self.exercise_receipt_digest.is_zero()
            || self.portfolio_receipt_digest.is_zero()
            || self.source_binding_digest.is_zero()
            || self.tokenization_proof_digest.is_zero()
            || self.portfolio_valid_until_unix_ms <= self.authority_snapshot.observed_unix_ms()
        {
            return Err(PromptProductV3Error::Integrity);
        }
        for delivery in &self.selected_deliveries {
            delivery
                .validate()
                .map_err(|error| PromptProductV3Error::Registry(error.to_string()))?;
        }
        if self.source_binding_digest != compute_source_binding_digest(self)
            || self.tokenization_proof_digest != compute_tokenization_proof_digest(self)
        {
            return Err(PromptProductV3Error::Integrity);
        }
        Ok(())
    }
}

impl fmt::Debug for PromptRegistryCompiledContextV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PromptRegistryCompiledContextV3")
            .field(
                "compilation_id",
                self.compiled.receipt().compilation_id(),
            )
            .field("selected_count", &self.selected_deliveries.len())
            .field(
                "payload_digest",
                &self.serialized_context.receipt().payload_digest(),
            )
            .field(
                "serialized_payload_bytes",
                &self.serialized_context.receipt().serialized_payload_bytes(),
            )
            .field(
                "serialized_token_count",
                &self.serialized_context.receipt().serialized_token_count(),
            )
            .field("source_binding_digest", &self.source_binding_digest)
            .field(
                "tokenization_proof_digest",
                &self.tokenization_proof_digest,
            )
            .finish()
    }
}

#[derive(Clone, Eq, PartialEq)]
pub struct PreparedPromptDeliveryV3 {
    pub preparation: ContextDeliveryPreparationV2,
    authority_successor: PromptContextAuthoritySuccessorV3,
    verified_snapshot: VerifiedAdmissionSnapshotV2,
    preparation_binding_digest: Digest32,
    authority: AuthorityPosture,
}

impl PreparedPromptDeliveryV3 {
    #[must_use]
    pub const fn preparation_binding_digest(&self) -> Digest32 {
        self.preparation_binding_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }
}

impl fmt::Debug for PreparedPromptDeliveryV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PreparedPromptDeliveryV3")
            .field(
                "preparation_digest",
                &self.preparation.preparation_digest(),
            )
            .field(
                "current_authority_snapshot",
                &self.authority_successor.current().snapshot_digest(),
            )
            .field(
                "preparation_binding_digest",
                &self.preparation_binding_digest,
            )
            .finish()
    }
}

#[derive(Debug)]
pub enum PromptProductV3Error {
    InvalidTime,
    EmptySelection,
    ProfileMismatch,
    UnsupportedPromptRole,
    NonUtf8Payload,
    ExerciseRejected(PromptExerciseActionV1),
    Registry(String),
    Optimizer(String),
    Tokenizer,
    Context(ContextCompilerV2Error),
    SelectionDrift,
    PortfolioExpired,
    Integrity,
    Arithmetic,
}

impl PromptProductV3Error {
    #[must_use]
    pub const fn code(&self) -> &'static str {
        match self {
            Self::InvalidTime => "prompt_product_v3_invalid_time",
            Self::EmptySelection => "prompt_product_v3_empty_selection",
            Self::ProfileMismatch => "prompt_product_v3_profile_mismatch",
            Self::UnsupportedPromptRole => "prompt_product_v3_unsupported_role",
            Self::NonUtf8Payload => "prompt_product_v3_non_utf8_payload",
            Self::ExerciseRejected(_) => "prompt_product_v3_exercise_rejected",
            Self::Registry(_) => "prompt_product_v3_registry",
            Self::Optimizer(_) => "prompt_product_v3_optimizer",
            Self::Tokenizer => "prompt_product_v3_tokenizer",
            Self::Context(_) => "prompt_product_v3_context",
            Self::SelectionDrift => "prompt_product_v3_selection_drift",
            Self::PortfolioExpired => "prompt_product_v3_portfolio_expired",
            Self::Integrity => "prompt_product_v3_integrity",
            Self::Arithmetic => "prompt_product_v3_arithmetic",
        }
    }
}

impl fmt::Display for PromptProductV3Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}", self.code())
    }
}

impl std::error::Error for PromptProductV3Error {}

struct QualifiedTokenizer<'a, T: PromptExactTokenizerV3> {
    tokenizer: &'a T,
    identity: PromptTokenizerIdentityV3,
}

impl<T: PromptExactTokenizerV3> ExactTokenizerV2 for QualifiedTokenizer<'_, T> {
    fn tokenizer_digest(&self) -> Digest32 {
        self.identity.tokenizer_digest
    }

    fn count_tokens(&self, bytes: &[u8]) -> Result<u64, ContextCompilerV2Error> {
        self.tokenizer
            .count_tokens(bytes)
            .map_err(|_| ContextCompilerV2Error::InvalidSerializedTokenCount)
    }
}

struct RegistryAuthorityVerifier<'a> {
    authority: &'a PromptContextAuthoritySnapshotV3,
    expected_predecessor: Option<Digest32>,
}

impl ContextAdmissionVerifierV2 for RegistryAuthorityVerifier<'_> {
    fn verifier_digest(&self) -> Digest32 {
        prompt_context_authority_verifier_digest_v3()
    }

    fn verify_record(&self, record: &ContextAdmissionRecordV2) -> bool {
        self.authority.admissions().iter().any(|admission| {
            record.admission_id == *admission.admission_id()
                && record.item_id == *admission.realization_id()
                && record.role == context_role(admission.role()).ok().unwrap_or(ContextRoleV2::Schema)
                && record.content_digest == admission.content_digest()
                && record.source_digest == admission.source_digest()
                && record.generation_vector_digest == admission.generation_vector_digest()
                && record.scope_digest == admission.scope_digest()
                && record.authority_domain_digest == admission.authority_domain_digest()
                && !record.contains_secret
                && record.issued_unix_ms == admission.issued_unix_ms()
                && record.expires_unix_ms == admission.expires_unix_ms()
                && record.validate_shape().is_ok()
        })
    }

    fn verify_snapshot(&self, snapshot: &ContextAdmissionSnapshotV2) -> bool {
        snapshot.scope_digest == self.authority.scope_digest()
            && snapshot.authority_domain_digest == self.authority.authority_domain_digest()
            && snapshot.observed_unix_ms == self.authority.observed_unix_ms()
            && snapshot.revocation_epoch == self.authority.revocation_frontier()
            && snapshot.revoked_admission_ids.is_empty()
            && snapshot.revocation_set_complete
            && snapshot.predecessor_snapshot_digest == self.expected_predecessor
            && snapshot.validate_shape().is_ok()
    }
}

struct CanonicalPromptSerializerV3 {
    profile_digest: Digest32,
    serializer_digest: Digest32,
    template_digest: Digest32,
    tool_schema_digest: Digest32,
}

impl ContextSerializerV2 for CanonicalPromptSerializerV3 {
    fn serializer_digest(&self) -> Digest32 {
        self.serializer_digest
    }

    fn template_digest(&self) -> Digest32 {
        self.template_digest
    }

    fn tool_schema_digest(&self) -> Digest32 {
        self.tool_schema_digest
    }

    fn serialize(
        &self,
        items: &[ContextRealizedItemV2],
    ) -> Result<Vec<u8>, ContextCompilerV2Error> {
        let mut encoded = Vec::with_capacity(items.len());
        for item in items {
            if item.role != ContextRoleV2::TrustedInstruction {
                return Err(ContextCompilerV2Error::RealizedRoleMismatch(
                    item.item_id.to_string(),
                ));
            }
            let content = std::str::from_utf8(&item.content)
                .map_err(|_| ContextCompilerV2Error::SerializationMismatch)?;
            encoded.push(CanonicalPromptItemV3 {
                item_id: item.item_id.as_str(),
                role: "developer_instruction",
                content,
            });
        }
        serde_json::to_vec(&CanonicalPromptBundleV3 {
            schema: CANONICAL_BUNDLE_SCHEMA,
            execution_profile_digest: self.profile_digest.to_string(),
            items: encoded,
        })
        .map_err(|_| ContextCompilerV2Error::SerializationMismatch)
    }
}

#[derive(Serialize)]
struct CanonicalPromptBundleV3<'a> {
    schema: &'static str,
    execution_profile_digest: String,
    items: Vec<CanonicalPromptItemV3<'a>>,
}

#[derive(Serialize)]
struct CanonicalPromptItemV3<'a> {
    item_id: &'a str,
    role: &'static str,
    content: &'a str,
}

pub fn compile_prompt_registry_v3<T: PromptExactTokenizerV3>(
    registry: &DurablePromptRegistry,
    portfolio: &SelectedPromptPortfolioV1,
    exercise_request: &PromptExerciseRequestV1,
    request: PromptRegistryCompilationRequestV3,
    tokenizer: &T,
) -> Result<PromptRegistryCompiledContextV3, PromptProductV3Error> {
    if request.now_unix_ms == 0 || request.now_unix_ms != exercise_request.now_unix_ms {
        return Err(PromptProductV3Error::InvalidTime);
    }
    if portfolio.selected.is_empty() {
        return Err(PromptProductV3Error::EmptySelection);
    }
    if request.registry_model_tuple != portfolio.model_tuple
        || portfolio.model_tuple_digest != portfolio.model_tuple.digest()
    {
        return Err(PromptProductV3Error::ProfileMismatch);
    }
    request
        .execution_profile
        .validate_for(&request.registry_model_tuple)?;
    ensure_digest(request.truncation_policy_digest)?;

    let tokenizer_identity = tokenizer.identity();
    tokenizer_identity.validate()?;
    if tokenizer_identity != request.execution_profile.tokenizer {
        return Err(PromptProductV3Error::ProfileMismatch);
    }
    let qualified_tokenizer = QualifiedTokenizer {
        tokenizer,
        identity: tokenizer_identity,
    };

    let exercise = exercise_v1(
        registry
            .registry()
            .map_err(|error| PromptProductV3Error::Registry(error.to_string()))?,
        portfolio,
        exercise_request.clone(),
    )
    .map_err(|error| PromptProductV3Error::Optimizer(error.to_string()))?;
    if exercise.decision != PromptExerciseActionV1::Exercise {
        return Err(PromptProductV3Error::ExerciseRejected(exercise.decision));
    }
    if request.now_unix_ms >= portfolio.receipt.valid_until_unix_ms {
        return Err(PromptProductV3Error::PortfolioExpired);
    }

    let scope_digest = product_scope_digest(portfolio, exercise.receipt_digest);
    let authority_domain_digest = product_authority_domain_digest(
        &request.execution_profile,
        &request.registry_model_tuple,
    );
    let realization_ids = portfolio
        .selected
        .iter()
        .map(|selected| selected.realization.realization_id.clone())
        .collect::<Vec<_>>();
    let authority_snapshot = registry
        .context_authority_snapshot_v3(
            portfolio.generation_vector_digest,
            &request.registry_model_tuple,
            scope_digest,
            authority_domain_digest,
            request.now_unix_ms,
            &realization_ids,
        )
        .map_err(|error| PromptProductV3Error::Registry(error.to_string()))?;
    let verifier = RegistryAuthorityVerifier {
        authority: &authority_snapshot,
        expected_predecessor: None,
    };
    let raw_snapshot = context_snapshot(&authority_snapshot, None)?;
    let verified_snapshot = verify_admission_snapshot_v2(raw_snapshot, &verifier)
        .map_err(PromptProductV3Error::Context)?;

    let registry_snapshot = authority_snapshot.registry_snapshot();
    let mut selected_deliveries = Vec::with_capacity(portfolio.selected.len());
    let mut candidates = Vec::with_capacity(portfolio.selected.len());
    for (selected, admission) in portfolio
        .selected
        .iter()
        .zip(authority_snapshot.admissions())
    {
        if selected.realization.realization_id != *admission.realization_id()
            || selected.realization.digest() != selected.binding_digest
        {
            return Err(PromptProductV3Error::SelectionDrift);
        }
        let delivery = registry
            .dereference_realization_v2(
                &selected.realization.realization_id,
                registry_snapshot,
                portfolio.generation_vector_digest,
                &request.registry_model_tuple,
                request.now_unix_ms,
            )
            .map_err(|error| PromptProductV3Error::Registry(error.to_string()))?;
        if delivery.binding != selected.realization
            || delivery.binding.digest() != selected.binding_digest
            || delivery.binding.payload_digest != admission.content_digest()
        {
            return Err(PromptProductV3Error::SelectionDrift);
        }
        let role = context_role(delivery.binding.role)?;
        let tokenization = TokenizationReceiptV2::from_exact_bytes(
            delivery.binding.realization_id.clone(),
            &delivery.payload,
            &qualified_tokenizer,
        )
        .map_err(PromptProductV3Error::Context)?;
        let admission_record = ContextAdmissionRecordV2::new(
            admission.admission_id().clone(),
            ContextAdmissionBindingV2 {
                item_id: admission.realization_id().clone(),
                role,
                content_digest: admission.content_digest(),
                source_digest: admission.source_digest(),
                generation_vector_digest: admission.generation_vector_digest(),
                scope_digest: admission.scope_digest(),
                authority_domain_digest: admission.authority_domain_digest(),
                contains_secret: false,
            },
            admission.issued_unix_ms(),
            admission.expires_unix_ms(),
        )
        .map_err(PromptProductV3Error::Context)?;
        let verified_admission = verify_admission_v2(
            admission_record,
            &verified_snapshot,
            &verifier,
        )
        .map_err(PromptProductV3Error::Context)?;
        candidates.push(ContextCandidateV2 {
            item_id: delivery.binding.realization_id.clone(),
            role,
            content_digest: delivery.binding.payload_digest,
            source_digest: delivery.binding.digest(),
            generation_vector_digest: portfolio.generation_vector_digest,
            tokenization,
            expected_value: FixedQ32::ONE,
            admission: verified_admission,
        });
        selected_deliveries.push(delivery);
    }

    let model_profile = request
        .execution_profile
        .context_model_profile(&request.registry_model_tuple);
    let compiled = compile_v2(ContextCompilationRequestV2 {
        compilation_id: request.compilation_id,
        objective_digest: portfolio.objective_digest,
        prompt_portfolio_digest: portfolio.receipt.receipt_digest,
        generation_vector_digest: portfolio.generation_vector_digest,
        scope_digest,
        authority_domain_digest,
        admission_verifier_digest: prompt_context_authority_verifier_digest_v3(),
        model_profile: model_profile.clone(),
        token_budget: request.token_budget,
        truncation_policy_digest: profiled_truncation_digest(
            request.truncation_policy_digest,
            request.execution_profile.digest(),
        ),
        candidates,
        mandatory_groups: vec![MandatoryContextGroupV2 {
            group_id: StableId::new(SELECTED_PROMPT_GROUP_ID)
                .map_err(|_| PromptProductV3Error::Integrity)?,
            item_ids: realization_ids,
            reason_digest: portfolio.receipt.receipt_digest,
        }],
    })
    .map_err(PromptProductV3Error::Context)?;

    let realizations = selected_deliveries
        .iter()
        .map(|delivery| {
            Ok(ContextRealizedItemV2 {
                item_id: delivery.binding.realization_id.clone(),
                role: context_role(delivery.binding.role)?,
                content: delivery.payload.clone(),
            })
        })
        .collect::<Result<Vec<_>, PromptProductV3Error>>()?;
    let serializer = CanonicalPromptSerializerV3 {
        profile_digest: request.execution_profile.digest(),
        serializer_digest: request.execution_profile.serializer_digest(),
        template_digest: request.execution_profile.template_digest,
        tool_schema_digest: request.execution_profile.tool_schema_digest,
    };
    let serialized_context = record_serialization(
        &compiled,
        &model_profile,
        request.serialization_id,
        realizations,
        &serializer,
        &qualified_tokenizer,
    )
    .map_err(PromptProductV3Error::Context)?;
    let attachment = build_attachment(
        &compiled,
        &serialized_context,
        &model_profile,
        &verified_snapshot,
        request.attachment_id,
    )
    .map_err(PromptProductV3Error::Context)?;

    let mut output = PromptRegistryCompiledContextV3 {
        compiled,
        model_profile,
        execution_profile: request.execution_profile,
        selected_deliveries,
        serialized_context,
        attachment,
        authority_snapshot,
        verified_snapshot,
        model_tuple: request.registry_model_tuple,
        generation_vector_digest: portfolio.generation_vector_digest,
        exercise_receipt_digest: exercise.receipt_digest,
        portfolio_receipt_digest: portfolio.receipt.receipt_digest,
        portfolio_valid_until_unix_ms: portfolio.receipt.valid_until_unix_ms,
        source_binding_digest: Digest32::ZERO,
        tokenization_proof_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    output.source_binding_digest = compute_source_binding_digest(&output);
    output.tokenization_proof_digest = compute_tokenization_proof_digest(&output);
    output.validate()?;
    Ok(output)
}

pub fn prepare_prompt_delivery_v3(
    registry: &DurablePromptRegistry,
    compiled: &PromptRegistryCompiledContextV3,
    observed_unix_ms: u64,
    preparation_id: StableId,
) -> Result<PreparedPromptDeliveryV3, PromptProductV3Error> {
    compiled.validate()?;
    if observed_unix_ms == 0 {
        return Err(PromptProductV3Error::InvalidTime);
    }
    if observed_unix_ms >= compiled.portfolio_valid_until_unix_ms {
        return Err(PromptProductV3Error::PortfolioExpired);
    }
    let authority_successor = registry
        .context_authority_successor_v3(&compiled.authority_snapshot, observed_unix_ms)
        .map_err(|error| PromptProductV3Error::Registry(error.to_string()))?;
    let verifier = RegistryAuthorityVerifier {
        authority: authority_successor.current(),
        expected_predecessor: Some(compiled.verified_snapshot.snapshot_digest()),
    };
    let raw_snapshot = context_snapshot(
        authority_successor.current(),
        Some(compiled.verified_snapshot.snapshot_digest()),
    )?;
    let verified_snapshot = verify_admission_snapshot_successor_v2(
        raw_snapshot,
        &compiled.verified_snapshot,
        &verifier,
    )
    .map_err(PromptProductV3Error::Context)?;
    let preparation = prepare_delivery_v2(
        &compiled.compiled,
        &compiled.serialized_context,
        &compiled.attachment,
        &compiled.model_profile,
        &verified_snapshot,
        preparation_id,
    )
    .map_err(PromptProductV3Error::Context)?;
    let preparation_binding_digest = preparation_binding_digest(
        &preparation,
        authority_successor.lineage_digest(),
        compiled.source_binding_digest,
        compiled.tokenization_proof_digest,
    );
    Ok(PreparedPromptDeliveryV3 {
        preparation,
        authority_successor,
        verified_snapshot,
        preparation_binding_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

pub fn observe_prompt_delivery_v3(
    compiled: &PromptRegistryCompiledContextV3,
    prepared: &PreparedPromptDeliveryV3,
    delivery_id: StableId,
    provider_receipt: &ProviderInvocationReceipt,
    delivery_verifier: &impl ContextProviderDeliveryVerifierV2,
    observed_unix_ms: u64,
) -> Result<ContextDeliveryReceiptV2, PromptProductV3Error> {
    compiled.validate()?;
    if prepared.authority.grants_any()
        || prepared.preparation_binding_digest.is_zero()
        || prepared.verified_snapshot.snapshot_digest()
            != prepared.authority_successor.current().snapshot_digest()
    {
        return Err(PromptProductV3Error::Integrity);
    }
    observe_delivery(
        &prepared.preparation,
        &compiled.attachment,
        &compiled.serialized_context,
        &compiled.model_profile,
        delivery_id,
        provider_receipt,
        delivery_verifier,
        observed_unix_ms,
    )
    .map_err(PromptProductV3Error::Context)
}

fn context_snapshot(
    authority: &PromptContextAuthoritySnapshotV3,
    predecessor: Option<Digest32>,
) -> Result<ContextAdmissionSnapshotV2, PromptProductV3Error> {
    let id = StableId::new(format!(
        "context-snapshot:v3:{}",
        authority.snapshot_digest()
    ))
    .map_err(|_| PromptProductV3Error::Integrity)?;
    ContextAdmissionSnapshotV2::new(
        id,
        authority.scope_digest(),
        authority.authority_domain_digest(),
        authority.observed_unix_ms(),
        authority.revocation_frontier(),
        Vec::new(),
        true,
        predecessor,
    )
    .map_err(PromptProductV3Error::Context)
}

fn context_role(role: PromptRoleV2) -> Result<ContextRoleV2, PromptProductV3Error> {
    match role {
        PromptRoleV2::DeveloperInstruction => Ok(ContextRoleV2::TrustedInstruction),
        PromptRoleV2::SystemInstruction
        | PromptRoleV2::UserTemplate
        | PromptRoleV2::ToolSchemaFragment => Err(PromptProductV3Error::UnsupportedPromptRole),
    }
}

fn product_scope_digest(
    portfolio: &SelectedPromptPortfolioV1,
    exercise_receipt_digest: Digest32,
) -> Digest32 {
    let mut bytes = SCOPE_DOMAIN.to_vec();
    bytes.extend_from_slice(portfolio.receipt.receipt_digest.as_array());
    bytes.extend_from_slice(portfolio.generation_vector_digest.as_array());
    bytes.extend_from_slice(exercise_receipt_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn product_authority_domain_digest(
    profile: &PromptExecutionProfileV3,
    tuple: &PromptModelTupleV2,
) -> Digest32 {
    let mut bytes = AUTHORITY_DOMAIN.to_vec();
    bytes.extend_from_slice(profile.digest().as_array());
    bytes.extend_from_slice(tuple.digest().as_array());
    bytes.extend_from_slice(prompt_context_authority_verifier_digest_v3().as_array());
    Digest32::of_bytes(&bytes)
}

fn profiled_truncation_digest(policy: Digest32, profile: Digest32) -> Digest32 {
    let mut bytes = TRUNCATION_PROFILE_DOMAIN.to_vec();
    bytes.extend_from_slice(policy.as_array());
    bytes.extend_from_slice(profile.as_array());
    Digest32::of_bytes(&bytes)
}

fn compute_source_binding_digest(output: &PromptRegistryCompiledContextV3) -> Digest32 {
    let mut bytes = SOURCE_BINDING_DOMAIN.to_vec();
    bytes.extend_from_slice(output.exercise_receipt_digest.as_array());
    bytes.extend_from_slice(output.portfolio_receipt_digest.as_array());
    bytes.extend_from_slice(output.authority_snapshot.snapshot_digest().as_array());
    bytes.extend_from_slice(output.execution_profile.digest().as_array());
    bytes.extend_from_slice(output.compiled.receipt().receipt_digest().as_array());
    bytes.extend_from_slice(output.serialized_context.receipt().receipt_digest().as_array());
    bytes.extend_from_slice(output.attachment.attachment_digest().as_array());
    bytes.extend_from_slice(&output.portfolio_valid_until_unix_ms.to_be_bytes());
    for delivery in &output.selected_deliveries {
        bytes.extend_from_slice(delivery.delivery_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn compute_tokenization_proof_digest(output: &PromptRegistryCompiledContextV3) -> Digest32 {
    let mut bytes = TOKENIZATION_PROOF_DOMAIN.to_vec();
    bytes.extend_from_slice(output.execution_profile.tokenizer.identity_digest().as_array());
    bytes.extend_from_slice(output.execution_profile.digest().as_array());
    bytes.extend_from_slice(output.serialized_context.receipt().payload_digest().as_array());
    bytes.extend_from_slice(
        &output
            .serialized_context
            .receipt()
            .serialized_token_count()
            .to_be_bytes(),
    );
    bytes.extend_from_slice(
        &output
            .serialized_context
            .receipt()
            .serialized_payload_bytes()
            .to_be_bytes(),
    );
    Digest32::of_bytes(&bytes)
}

fn preparation_binding_digest(
    preparation: &ContextDeliveryPreparationV2,
    lineage_digest: Digest32,
    source_binding_digest: Digest32,
    tokenization_proof_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.prompt-product.preparation-binding.v3".to_vec();
    bytes.extend_from_slice(preparation.preparation_digest().as_array());
    bytes.extend_from_slice(lineage_digest.as_array());
    bytes.extend_from_slice(source_binding_digest.as_array());
    bytes.extend_from_slice(tokenization_proof_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn ensure_digest(digest: Digest32) -> Result<(), PromptProductV3Error> {
    if digest.is_zero() {
        return Err(PromptProductV3Error::Integrity);
    }
    Ok(())
}

fn validate_revision(value: &str) -> Result<(), PromptProductV3Error> {
    if value.is_empty() || value.len() > 256 || value.as_bytes().contains(&0) {
        return Err(PromptProductV3Error::ProfileMismatch);
    }
    Ok(())
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&u64::try_from(value.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::prompt_delivery::tests::admitted_registry;
    use crate::prompt_delivery::tests::canonical_selection;
    use crate::prompt_delivery::tests::revoke_registry;

    struct ByteExactTokenizer {
        identity: PromptTokenizerIdentityV3,
    }

    impl PromptExactTokenizerV3 for ByteExactTokenizer {
        fn identity(&self) -> PromptTokenizerIdentityV3 {
            self.identity.clone()
        }

        fn count_tokens(&self, bytes: &[u8]) -> Result<u64, String> {
            u64::try_from(bytes.len()).map_err(|_| "token_count_overflow".to_owned())
        }
    }

    fn id(value: &str) -> StableId {
        StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn tokenizer(tuple: &PromptModelTupleV2) -> ByteExactTokenizer {
        ByteExactTokenizer {
            identity: PromptTokenizerIdentityV3 {
                tokenizer_digest: tuple.tokenizer_digest,
                binary_digest: digest("tokenizer-binary:v1"),
                vocabulary_digest: digest("tokenizer-vocabulary:v1"),
                normalization_policy_digest: digest("tokenizer-normalization:v1"),
                version: "byte-exact-test-v1".to_owned(),
            },
        }
    }

    fn profile(tuple: &PromptModelTupleV2) -> PromptExecutionProfileV3 {
        PromptExecutionProfileV3 {
            provider_id: "provider:test".to_owned(),
            provider_revision: "provider-revision:v1".to_owned(),
            provider_model: tuple.model_id.as_str().to_owned(),
            model_revision: tuple.model_version.clone(),
            tokenizer: tokenizer(tuple).identity(),
            serializer_revision: "canonical-json:v3".to_owned(),
            template_digest: tuple.template_digest,
            template_revision: "template:v1".to_owned(),
            tool_schema_digest: tuple.tool_schema_digest,
            tool_schema_revision: "tool-schema:v1".to_owned(),
            maximum_context_tokens: 16_384,
        }
    }

    fn request(
        tuple: &PromptModelTupleV2,
        token_budget: u64,
    ) -> PromptRegistryCompilationRequestV3 {
        PromptRegistryCompilationRequestV3 {
            compilation_id: id("compilation:prompt:v3"),
            serialization_id: id("serialization:prompt:v3"),
            attachment_id: id("attachment:prompt:v3"),
            registry_model_tuple: tuple.clone(),
            execution_profile: profile(tuple),
            now_unix_ms: 100,
            token_budget,
            truncation_policy_digest: digest("truncation:v3"),
        }
    }

    #[test]
    fn canonical_product_counts_actual_final_payload_bytes() {
        let temporary = tempfile::tempdir().expect("tempdir");
        let root = temporary.path().join("registry");
        let raw = b"Inspect evidence before mutation.";
        let (registry, tuple, _authority, _key, _grant_now) = admitted_registry(&root, raw);
        let selected = canonical_selection(&registry, &tuple, 100);
        let output = compile_prompt_registry_v3(
            &registry,
            &selected.portfolio,
            &selected.exercise_request,
            request(&tuple, 16_384),
            &tokenizer(&tuple),
        )
        .expect("canonical V3 compilation");

        assert_eq!(
            output.serialized_context.receipt().serialized_token_count(),
            u64::try_from(output.payload().len()).expect("payload length")
        );
        assert!(
            output.serialized_context.receipt().serialized_token_count()
                > u64::from(selected.portfolio.selected[0].realization.token_cost)
        );
        let text = std::str::from_utf8(output.payload()).expect("canonical UTF-8");
        assert!(text.contains(CANONICAL_BUNDLE_SCHEMA));
        assert!(text.contains("developer_instruction"));
        assert!(text.contains("Inspect evidence before mutation."));
        output.validate().expect("valid output");
    }

    #[test]
    fn final_canonical_framing_must_fit_real_budget() {
        let temporary = tempfile::tempdir().expect("tempdir");
        let root = temporary.path().join("registry-budget");
        let raw = b"Bound instruction";
        let (registry, tuple, _authority, _key, _grant_now) = admitted_registry(&root, raw);
        let selected = canonical_selection(&registry, &tuple, 100);
        let error = compile_prompt_registry_v3(
            &registry,
            &selected.portfolio,
            &selected.exercise_request,
            request(&tuple, u64::try_from(raw.len()).expect("length")),
            &tokenizer(&tuple),
        )
        .expect_err("canonical framing must exceed raw-only budget");
        assert!(matches!(
            error,
            PromptProductV3Error::Context(
                ContextCompilerV2Error::SerializedTokenBudgetExceeded { .. }
            )
        ));
    }

    #[test]
    fn revocation_between_attachment_and_send_prevents_preparation() {
        let temporary = tempfile::tempdir().expect("tempdir");
        let root = temporary.path().join("registry-revoke");
        let (mut registry, tuple, authority, key, grant_now) =
            admitted_registry(&root, b"Bound instruction");
        let selected = canonical_selection(&registry, &tuple, 100);
        let output = compile_prompt_registry_v3(
            &registry,
            &selected.portfolio,
            &selected.exercise_request,
            request(&tuple, 16_384),
            &tokenizer(&tuple),
        )
        .expect("canonical V3 compilation");
        revoke_registry(&mut registry, &authority, &key, grant_now);

        let error = prepare_prompt_delivery_v3(
            &registry,
            &output,
            200,
            id("preparation:prompt:v3"),
        )
        .expect_err("revoked selection must not prepare");
        assert!(matches!(error, PromptProductV3Error::Registry(_)));
    }

    #[test]
    fn debug_output_redacts_raw_prompt_bytes() {
        let temporary = tempfile::tempdir().expect("tempdir");
        let root = temporary.path().join("registry-debug");
        let secret_marker = "DO_NOT_RENDER_RAW_PROMPT";
        let (registry, tuple, _authority, _key, _grant_now) =
            admitted_registry(&root, secret_marker.as_bytes());
        let selected = canonical_selection(&registry, &tuple, 100);
        let output = compile_prompt_registry_v3(
            &registry,
            &selected.portfolio,
            &selected.exercise_request,
            request(&tuple, 16_384),
            &tokenizer(&tuple),
        )
        .expect("canonical V3 compilation");
        assert!(!format!("{output:?}").contains(secret_marker));
    }
}
