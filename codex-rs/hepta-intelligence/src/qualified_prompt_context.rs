use std::collections::BTreeMap;

use codex_hepta_context_compiler::CanonicalDeveloperPolicySerializerV2;
use codex_hepta_context_compiler::ContextAdmissionVerifierV2;
use codex_hepta_context_compiler::ContextCandidateV2;
use codex_hepta_context_compiler::ContextCompilationRequestV2;
use codex_hepta_context_compiler::ContextRealizedItemV2;
use codex_hepta_context_compiler::ContextRoleV2;
use codex_hepta_context_compiler::ContextSerializerV2;
use codex_hepta_context_compiler::ExactTokenCounterV2;
use codex_hepta_context_compiler::ExactTokenizerV2;
use codex_hepta_context_compiler::MandatoryContextGroupV2;
use codex_hepta_context_compiler::QualifiedExactTokenizerV2;
use codex_hepta_context_compiler::SignedAdmissionRecordV2;
use codex_hepta_context_compiler::SignedAdmissionVerifierV2;
use codex_hepta_context_compiler::TokenizationReceiptV2;
use codex_hepta_context_compiler::VerifiedSnapshotLineageV2;
use codex_hepta_context_compiler::build_attachment;
use codex_hepta_context_compiler::compile_v2;
use codex_hepta_context_compiler::record_serialization;
use codex_hepta_context_compiler::verify_admission_v2;
use codex_hepta_prompt_optimizer::canonical::PromptExerciseActionV1;
use codex_hepta_prompt_optimizer::canonical::PromptExerciseRequestV1;
use codex_hepta_prompt_optimizer::canonical::SelectedPromptPortfolioV1;
use codex_hepta_prompt_optimizer::canonical::exercise_v1;
use codex_hepta_prompt_registry::DurablePromptRegistry;
use codex_hepta_prompt_registry::DurableRegistryError;
use codex_hepta_prompt_registry::PromptRoleV2;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use super::PromptRegistryCompilationErrorV2;
use super::PromptRegistryCompilationRequestV2;
use super::PromptRegistryCompiledContextV2;

const QUALIFIED_SELECTED_GROUP_ID: &str = "prompt:qualified-exercise-selected-v3";

impl PromptRegistryCompilationRequestV2 {
    /// Compile the selected portfolio through the canonical V3 source path.
    ///
    /// Unlike `compile_prompt_registry_v2`, this entrypoint accepts only an
    /// independently signed admission authority, a typed predecessor-checked
    /// snapshot lineage, the canonical developer-policy serializer and an
    /// injected exact provider/model tokenizer capability. Registry token-cost
    /// declarations are never reused as tokenization observations.
    #[allow(clippy::too_many_arguments)]
    pub fn compile_qualified_v3<T: ExactTokenCounterV2>(
        self,
        registry: &DurablePromptRegistry,
        portfolio: &SelectedPromptPortfolioV1,
        exercise_request: &PromptExerciseRequestV1,
        lineage: &VerifiedSnapshotLineageV2,
        admission_verifier: &SignedAdmissionVerifierV2,
        signed_admissions: Vec<SignedAdmissionRecordV2>,
        serializer: &CanonicalDeveloperPolicySerializerV2,
        tokenizer: &QualifiedExactTokenizerV2<T>,
    ) -> Result<PromptRegistryCompiledContextV2, PromptRegistryCompilationErrorV2> {
        self.validate_qualified_profile(
            portfolio,
            exercise_request,
            lineage,
            serializer,
            tokenizer,
        )?;
        if portfolio.selected.is_empty() {
            return Err(PromptRegistryCompilationErrorV2::EmptySelection);
        }

        let registry_view = registry
            .registry()
            .map_err(PromptRegistryCompilationErrorV2::Registry)?;
        let exercise = exercise_v1(registry_view, portfolio, exercise_request.clone())
            .map_err(|error| PromptRegistryCompilationErrorV2::Optimizer(error.to_string()))?;
        if exercise.decision != PromptExerciseActionV1::Exercise {
            return Err(PromptRegistryCompilationErrorV2::ExerciseRejected(
                exercise.decision,
            ));
        }

        let registry_snapshot = registry
            .snapshot_v2(portfolio.generation_vector_digest, &portfolio.model_tuple)
            .map_err(PromptRegistryCompilationErrorV2::Registry)?;
        let compatible = registry
            .read_compatible_v2(
                &registry_snapshot,
                portfolio.generation_vector_digest,
                &portfolio.model_tuple,
                self.now_unix_ms,
                portfolio.receipt.factor_ids.clone(),
                u32::try_from(portfolio.selected.len())
                    .map_err(|_| PromptRegistryCompilationErrorV2::Integrity)?,
            )
            .map_err(PromptRegistryCompilationErrorV2::Registry)?;
        if compatible.omitted_count != 0 {
            return Err(PromptRegistryCompilationErrorV2::IncompleteRegistryRead(
                compatible.omitted_count,
            ));
        }

        let mut materialized = Vec::with_capacity(portfolio.selected.len());
        for selected in &portfolio.selected {
            let delivery = registry
                .dereference_realization_v2(
                    &selected.realization.realization_id,
                    &registry_snapshot,
                    portfolio.generation_vector_digest,
                    &portfolio.model_tuple,
                    self.now_unix_ms,
                )
                .map_err(PromptRegistryCompilationErrorV2::Registry)?;
            if delivery.binding != selected.realization
                || delivery.binding.digest() != selected.binding_digest
                || delivery.binding.payload_digest != Digest32::of_bytes(&delivery.payload)
            {
                return Err(PromptRegistryCompilationErrorV2::Integrity);
            }
            if delivery.binding.role != PromptRoleV2::DeveloperInstruction {
                return Err(PromptRegistryCompilationErrorV2::UnsupportedPromptRole(
                    delivery.binding.realization_id.to_string(),
                ));
            }
            delivery
                .validate()
                .map_err(DurableRegistryError::Read)
                .map_err(PromptRegistryCompilationErrorV2::Registry)?;
            materialized.push((selected, delivery));
        }

        let mut records = BTreeMap::new();
        for signed in signed_admissions {
            let record = signed.record().clone();
            let item_id = record.item_id.clone();
            if records.insert(item_id.clone(), record).is_some() {
                return Err(PromptRegistryCompilationErrorV2::DuplicateAdmission(
                    item_id.to_string(),
                ));
            }
        }
        if records.len() != materialized.len() {
            return Err(PromptRegistryCompilationErrorV2::AdmissionSetMismatch);
        }

        let current_snapshot = lineage.current();
        let model_profile = self.context_model_profile.clone();
        let mut candidates = Vec::with_capacity(materialized.len());
        for (selected, delivery) in &materialized {
            let item_id = &delivery.binding.realization_id;
            let record = records.remove(item_id).ok_or_else(|| {
                PromptRegistryCompilationErrorV2::MissingAdmission(item_id.to_string())
            })?;
            if record.role != ContextRoleV2::TrustedInstruction
                || record.content_digest != delivery.binding.payload_digest
                || record.source_digest != selected.binding_digest
                || record.generation_vector_digest != portfolio.generation_vector_digest
                || record.scope_digest != current_snapshot.scope_digest()
                || record.authority_domain_digest != current_snapshot.authority_domain_digest()
            {
                return Err(PromptRegistryCompilationErrorV2::AdmissionBindingMismatch(
                    item_id.to_string(),
                ));
            }
            let admission = verify_admission_v2(record, current_snapshot, admission_verifier)
                .map_err(PromptRegistryCompilationErrorV2::Context)?;
            let tokenization = TokenizationReceiptV2::from_exact_bytes(
                item_id.clone(),
                &delivery.payload,
                tokenizer,
            )
            .map_err(PromptRegistryCompilationErrorV2::Context)?;
            candidates.push(ContextCandidateV2 {
                item_id: item_id.clone(),
                role: ContextRoleV2::TrustedInstruction,
                content_digest: delivery.binding.payload_digest,
                source_digest: selected.binding_digest,
                generation_vector_digest: portfolio.generation_vector_digest,
                tokenization,
                expected_value: FixedQ32::ONE,
                admission,
            });
        }
        if !records.is_empty() {
            return Err(PromptRegistryCompilationErrorV2::AdmissionSetMismatch);
        }

        let mandatory_ids = candidates
            .iter()
            .map(|candidate| candidate.item_id.clone())
            .collect::<Vec<_>>();
        let compiled = compile_v2(ContextCompilationRequestV2 {
            compilation_id: self.compilation_id,
            objective_digest: portfolio.objective_digest,
            prompt_portfolio_digest: portfolio.receipt.receipt_digest,
            generation_vector_digest: portfolio.generation_vector_digest,
            scope_digest: current_snapshot.scope_digest(),
            authority_domain_digest: current_snapshot.authority_domain_digest(),
            admission_verifier_digest: admission_verifier.verifier_digest(),
            model_profile: model_profile.clone(),
            token_budget: self.token_budget,
            truncation_policy_digest: self.truncation_policy_digest,
            candidates,
            mandatory_groups: vec![MandatoryContextGroupV2 {
                group_id: StableId::new(QUALIFIED_SELECTED_GROUP_ID)
                    .map_err(|_| PromptRegistryCompilationErrorV2::Integrity)?,
                item_ids: mandatory_ids,
                reason_digest: portfolio.receipt.receipt_digest,
            }],
        })
        .map_err(PromptRegistryCompilationErrorV2::Context)?;

        if compiled.receipt().selected_item_ids().len() != materialized.len()
            || !compiled.receipt().omitted_item_ids().is_empty()
        {
            return Err(PromptRegistryCompilationErrorV2::Integrity);
        }
        let delivery_by_id = materialized
            .into_iter()
            .map(|(_, delivery)| (delivery.binding.realization_id.clone(), delivery))
            .collect::<BTreeMap<_, _>>();
        let selected_deliveries = compiled
            .receipt()
            .selected_item_ids()
            .iter()
            .map(|item_id| {
                delivery_by_id
                    .get(item_id)
                    .cloned()
                    .ok_or(PromptRegistryCompilationErrorV2::Integrity)
            })
            .collect::<Result<Vec<_>, _>>()?;
        let realizations = selected_deliveries
            .iter()
            .map(|delivery| ContextRealizedItemV2 {
                item_id: delivery.binding.realization_id.clone(),
                role: ContextRoleV2::TrustedInstruction,
                content: delivery.payload.clone(),
            })
            .collect::<Vec<_>>();

        let serialized_context = record_serialization(
            &compiled,
            &model_profile,
            self.serialization_id,
            realizations,
            serializer,
            tokenizer,
        )
        .map_err(PromptRegistryCompilationErrorV2::Context)?;
        std::str::from_utf8(serialized_context.payload())
            .map_err(|_| PromptRegistryCompilationErrorV2::SerializedPayloadNotUtf8)?;
        let serialization = serialized_context.receipt().clone();
        let attachment = build_attachment(
            &compiled,
            &serialized_context,
            &model_profile,
            current_snapshot,
            self.attachment_id,
        )
        .map_err(PromptRegistryCompilationErrorV2::Context)?;

        let mut output = PromptRegistryCompiledContextV2 {
            compatible,
            exercise_receipt_digest: exercise.receipt_digest,
            portfolio_receipt_digest: portfolio.receipt.receipt_digest,
            compiled,
            model_profile,
            selected_deliveries,
            serialized_payload: serialized_context.payload().to_vec(),
            serialization,
            serialized_context,
            attachment,
            delivery_set_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        output.delivery_set_digest = output.compute_delivery_set_digest();
        output.validate()?;
        Ok(output)
    }

    fn validate_qualified_profile<T: ExactTokenCounterV2>(
        &self,
        portfolio: &SelectedPromptPortfolioV1,
        exercise_request: &PromptExerciseRequestV1,
        lineage: &VerifiedSnapshotLineageV2,
        serializer: &CanonicalDeveloperPolicySerializerV2,
        tokenizer: &QualifiedExactTokenizerV2<T>,
    ) -> Result<(), PromptRegistryCompilationErrorV2> {
        self.context_model_profile
            .validate()
            .map_err(PromptRegistryCompilationErrorV2::Context)?;
        let profile = &self.context_model_profile;
        let tuple = &portfolio.model_tuple;
        if self.registry_model_tuple != *tuple
            || exercise_request.model_tuple != *tuple
            || self.now_unix_ms != exercise_request.now_unix_ms
            || self.now_unix_ms == 0
            || lineage.current().observed_unix_ms() > self.now_unix_ms
            || profile.model_digest != tuple.model_digest
            || profile.tokenizer_digest != tuple.tokenizer_digest
            || profile.template_digest != tuple.template_digest
            || profile.tool_schema_digest != tuple.tool_schema_digest
            || profile.digest() != tuple.context_profile_digest
            || profile.tokenizer_digest != tokenizer.tokenizer_digest()
            || profile.serializer_digest != serializer.serializer_digest()
            || profile.template_digest != serializer.template_digest()
            || profile.tool_schema_digest != serializer.tool_schema_digest()
            || tokenizer.identity().model_digest != profile.model_digest
            || tokenizer.identity().provider_id_digest != profile.provider_id_digest
            || tokenizer.identity().provider_model_digest != profile.provider_model_digest
            || serializer.identity().model_digest != profile.model_digest
            || serializer.identity().provider_id_digest != profile.provider_id_digest
            || serializer.identity().provider_model_digest != profile.provider_model_digest
        {
            return Err(PromptRegistryCompilationErrorV2::ProfileMismatch);
        }
        Ok(())
    }
}
