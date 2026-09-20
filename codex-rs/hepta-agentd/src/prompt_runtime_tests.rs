use super::*;

use std::collections::BTreeSet;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_context_compiler::ContextModelProfileV2;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_prompt_optimizer::PromptAuthenticationErrorV1;
use codex_hepta_prompt_optimizer::PromptCandidateEnumerationRequestV1;
use codex_hepta_prompt_optimizer::PromptCostBreakdownV1;
use codex_hepta_prompt_optimizer::PromptExerciseBoundaryV1;
use codex_hepta_prompt_optimizer::PromptExerciseRequestV1;
use codex_hepta_prompt_optimizer::PromptPortfolioSelectionRequestV1;
use codex_hepta_prompt_optimizer::PromptPricingEvidenceAuthenticatorV1;
use codex_hepta_prompt_optimizer::PromptPricingEvidenceV1;
use codex_hepta_prompt_optimizer::PromptRelationSourceAuthenticatorV1;
use codex_hepta_prompt_optimizer::PromptRelationSourceV1;
use codex_hepta_prompt_optimizer::enumerate_factors_v1;
use codex_hepta_prompt_optimizer::exercise_portfolio_v1;
use codex_hepta_prompt_optimizer::price_factors_v1;
use codex_hepta_prompt_optimizer::select_portfolio_v1;
use codex_hepta_prompt_registry::FactorSource;
use codex_hepta_prompt_registry::Lifecycle;
use codex_hepta_prompt_registry::PromptFactor;
use codex_hepta_prompt_registry::PromptModelTupleV2;
use codex_hepta_prompt_registry::PromptRealizationBindingV2;
use codex_hepta_prompt_registry::PromptRoleV2;
use codex_hepta_prompt_registry::final_use_admission_binding;
use codex_hepta_prompt_registry::final_use_realization_binding;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::PromptDeliveryObservationV1;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn attachment() -> PromptRuntimeAttachmentV1 {
    PromptRuntimeAttachmentV1::new(
        id("compilation:agentd-prompt"),
        digest("attachment"),
        digest("payload"),
        "gpt-test",
        10_000,
        vec![
            PromptRuntimeDeveloperFragmentV1::new("Verify before mutation.")
                .unwrap_or_else(|error| panic!("fragment: {error}")),
        ],
    )
    .unwrap_or_else(|error| panic!("attachment: {error}"))
}

fn stage_raw(
    owner: &AgentdPromptRuntimeOwner,
    thread_id: &str,
    turn_id: &str,
    value: PromptRuntimeAttachmentV1,
) {
    owner
        .commit_state(|state| {
            state.staged.insert(
                PromptRuntimeKey {
                    thread_id: thread_id.to_owned(),
                    turn_id: turn_id.to_owned(),
                },
                value,
            );
            Ok(())
        })
        .unwrap_or_else(|error| panic!("stage raw: {error}"));
}

fn dispatch(
    value: &PromptRuntimeAttachmentV1,
    thread_id: &str,
    turn_id: &str,
    attempt_id: &str,
    request_binding_id: &str,
    provider_request_digest: Digest32,
) -> PromptRuntimeDispatchRecordV1 {
    PromptRuntimeDispatchRecordV1 {
        compilation_id: value.compilation_id.clone(),
        context_attachment_digest: value.context_attachment_digest,
        context_payload_digest: value.context_payload_digest,
        source_binding_digest: value.source_binding_digest,
        thread_id: thread_id.to_owned(),
        turn_id: turn_id.to_owned(),
        attempt_id: attempt_id.to_owned(),
        request_binding_id: request_binding_id.to_owned(),
        provider_request_digest,
        dispatched_unix_ms: 5,
    }
}

fn delivered_terminal(
    value: &PromptRuntimeAttachmentV1,
    attempt_id: &str,
    request_binding_id: &str,
    provider_request_digest: Digest32,
    observed_unix_ms: u64,
) -> PromptRuntimeTerminalRecordV1 {
    let observation = PromptDeliveryObservationV1 {
        compilation_id: value.compilation_id.clone(),
        provider_request_digest,
        delivered: true,
        rejected_reason: None,
        observed_token_positions: None,
        truncation_observed: false,
    };
    observation
        .validate()
        .unwrap_or_else(|error| panic!("observation: {error}"));
    PromptRuntimeTerminalRecordV1 {
        compilation_id: value.compilation_id.clone(),
        context_attachment_digest: value.context_attachment_digest,
        context_payload_digest: value.context_payload_digest,
        source_binding_digest: value.source_binding_digest,
        thread_id: "thread:one".to_owned(),
        turn_id: "turn:one".to_owned(),
        attempt_id: attempt_id.to_owned(),
        request_binding_id: request_binding_id.to_owned(),
        provider_request_digest,
        outcome: PromptRuntimeTerminalOutcomeV1::Delivered,
        end_turn: Some(true),
        terminal_reason_code: None,
        delivery_observation: Some(observation),
        observed_unix_ms,
    }
}

#[test]
fn staged_attachment_is_bound_to_exact_thread_and_turn() {
    let owner = AgentdPromptRuntimeOwner::new();
    stage_raw(&owner, "thread:one", "turn:one", attachment());

    let exact = owner
        .prepare(PromptRuntimePrepareRequest {
            thread_id: "thread:one".to_owned(),
            turn_id: "turn:one".to_owned(),
            model_context_window: Some(4096),
        })
        .unwrap_or_else(|error| panic!("prepare: {error}"));
    assert!(exact.is_some());

    let wrong_thread = owner
        .prepare(PromptRuntimePrepareRequest {
            thread_id: "thread:two".to_owned(),
            turn_id: "turn:one".to_owned(),
            model_context_window: Some(4096),
        })
        .unwrap_or_else(|error| panic!("prepare: {error}"));
    assert!(wrong_thread.is_none());
}

#[test]
fn non_dispatch_terminal_is_idempotent_and_retains_stage_for_retry() {
    let owner = AgentdPromptRuntimeOwner::new();
    let value = attachment();
    stage_raw(&owner, "thread:one", "turn:one", value.clone());
    let provider_request_digest = digest("provider-request");
    owner
        .record_dispatch(dispatch(
            &value,
            "thread:one",
            "turn:one",
            "attempt:one",
            "request:one",
            provider_request_digest,
        ))
        .unwrap_or_else(|error| panic!("dispatch: {error}"));
    let record = PromptRuntimeTerminalRecordV1 {
        compilation_id: value.compilation_id.clone(),
        context_attachment_digest: value.context_attachment_digest,
        context_payload_digest: value.context_payload_digest,
        source_binding_digest: value.source_binding_digest,
        thread_id: "thread:one".to_owned(),
        turn_id: "turn:one".to_owned(),
        attempt_id: "attempt:one".to_owned(),
        request_binding_id: "request:one".to_owned(),
        provider_request_digest,
        outcome: PromptRuntimeTerminalOutcomeV1::NotDispatched,
        end_turn: None,
        terminal_reason_code: Some("cancelled_before_send".to_owned()),
        delivery_observation: None,
        observed_unix_ms: 10,
    };
    owner
        .record(record.clone())
        .unwrap_or_else(|error| panic!("record: {error}"));
    owner
        .record(record.clone())
        .unwrap_or_else(|error| panic!("idempotent record: {error}"));
    assert_eq!(
        owner
            .terminal_record("attempt:one")
            .unwrap_or_else(|error| panic!("terminal lookup: {error}")),
        Some(record)
    );
    assert_eq!(
        owner
            .staged_count()
            .unwrap_or_else(|error| panic!("staged count: {error}")),
        1
    );
    assert!(
        owner
            .prepare(PromptRuntimePrepareRequest {
                thread_id: "thread:one".to_owned(),
                turn_id: "turn:one".to_owned(),
                model_context_window: Some(4096),
            })
            .unwrap_or_else(|error| panic!("retry prepare: {error}"))
            .is_some()
    );
}

#[test]
fn final_delivered_terminal_releases_staged_turn() {
    let owner = AgentdPromptRuntimeOwner::new();
    let value = attachment();
    stage_raw(&owner, "thread:one", "turn:one", value.clone());
    let provider_request_digest = digest("provider-request-final");
    owner
        .record_dispatch(dispatch(
            &value,
            "thread:one",
            "turn:one",
            "attempt:final",
            "request:final",
            provider_request_digest,
        ))
        .unwrap_or_else(|error| panic!("dispatch: {error}"));
    owner
        .record(delivered_terminal(
            &value,
            "attempt:final",
            "request:final",
            provider_request_digest,
            11,
        ))
        .unwrap_or_else(|error| panic!("record: {error}"));
    assert_eq!(
        owner
            .staged_count()
            .unwrap_or_else(|error| panic!("staged count: {error}")),
        0
    );
}

#[test]
fn not_dispatched_retry_then_final_delivery_reopens_without_stale_stage_requirement() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let root = temporary.path().join("prompt-runtime");
    let value = attachment();
    let first_digest = digest("provider-request-not-dispatched");
    let second_digest = digest("provider-request-retry-final");
    {
        let owner = AgentdPromptRuntimeOwner::open_state_dir(&root).expect("open owner");
        stage_raw(&owner, "thread:one", "turn:one", value.clone());
        owner
            .record_dispatch(dispatch(
                &value,
                "thread:one",
                "turn:one",
                "attempt:first",
                "request:first",
                first_digest,
            ))
            .unwrap_or_else(|error| panic!("first dispatch: {error}"));
        owner
            .record(PromptRuntimeTerminalRecordV1 {
                compilation_id: value.compilation_id.clone(),
                context_attachment_digest: value.context_attachment_digest,
                context_payload_digest: value.context_payload_digest,
                source_binding_digest: value.source_binding_digest,
                thread_id: "thread:one".to_owned(),
                turn_id: "turn:one".to_owned(),
                attempt_id: "attempt:first".to_owned(),
                request_binding_id: "request:first".to_owned(),
                provider_request_digest: first_digest,
                outcome: PromptRuntimeTerminalOutcomeV1::NotDispatched,
                end_turn: None,
                terminal_reason_code: Some("pre_send_cancel".to_owned()),
                delivery_observation: None,
                observed_unix_ms: 10,
            })
            .unwrap_or_else(|error| panic!("not-dispatched record: {error}"));
        owner
            .record_dispatch(dispatch(
                &value,
                "thread:one",
                "turn:one",
                "attempt:second",
                "request:second",
                second_digest,
            ))
            .unwrap_or_else(|error| panic!("second dispatch: {error}"));
        owner
            .record(delivered_terminal(
                &value,
                "attempt:second",
                "request:second",
                second_digest,
                11,
            ))
            .unwrap_or_else(|error| panic!("delivered record: {error}"));
        assert_eq!(owner.staged_count().expect("staged count"), 0);
    }

    let reopened = AgentdPromptRuntimeOwner::open_state_dir(&root).expect("reopen owner");
    assert_eq!(reopened.staged_count().expect("staged count"), 0);
    assert_eq!(
        reopened
            .terminal_record("attempt:first")
            .expect("first terminal")
            .map(|record| record.outcome),
        Some(PromptRuntimeTerminalOutcomeV1::NotDispatched)
    );
    assert_eq!(
        reopened
            .terminal_record("attempt:second")
            .expect("second terminal")
            .map(|record| record.outcome),
        Some(PromptRuntimeTerminalOutcomeV1::Delivered)
    );
}

#[test]
fn dispatch_without_terminal_reopens_as_unknown_and_blocks_blind_retry() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let root = temporary.path().join("prompt-runtime");
    let value = attachment();
    {
        let owner = AgentdPromptRuntimeOwner::open_state_dir(&root).expect("open owner");
        stage_raw(&owner, "thread:one", "turn:one", value.clone());
        owner
            .record_dispatch(dispatch(
                &value,
                "thread:one",
                "turn:one",
                "attempt:unknown",
                "request:unknown",
                digest("provider-request-unknown"),
            ))
            .unwrap_or_else(|error| panic!("dispatch: {error}"));
    }

    let reopened = AgentdPromptRuntimeOwner::open_state_dir(&root).expect("reopen owner");
    assert!(
        reopened
            .prepare(PromptRuntimePrepareRequest {
                thread_id: "thread:one".to_owned(),
                turn_id: "turn:one".to_owned(),
                model_context_window: Some(4096),
            })
            .is_err()
    );
    assert!(
        reopened
            .dispatch_record("attempt:unknown")
            .expect("dispatch lookup")
            .is_some()
    );
    assert!(
        reopened
            .terminal_record("attempt:unknown")
            .expect("terminal lookup")
            .is_none()
    );
}

#[test]
fn indeterminate_terminal_reopens_blocked_and_reconciles_monotonically() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let root = temporary.path().join("prompt-runtime");
    let value = attachment();
    let provider_request_digest = digest("provider-request-indeterminate");
    {
        let owner = AgentdPromptRuntimeOwner::open_state_dir(&root).expect("open owner");
        stage_raw(&owner, "thread:one", "turn:one", value.clone());
        owner
            .record_dispatch(dispatch(
                &value,
                "thread:one",
                "turn:one",
                "attempt:indeterminate",
                "request:indeterminate",
                provider_request_digest,
            ))
            .unwrap_or_else(|error| panic!("dispatch: {error}"));
        owner
            .record(PromptRuntimeTerminalRecordV1 {
                compilation_id: value.compilation_id.clone(),
                context_attachment_digest: value.context_attachment_digest,
                context_payload_digest: value.context_payload_digest,
                source_binding_digest: value.source_binding_digest,
                thread_id: "thread:one".to_owned(),
                turn_id: "turn:one".to_owned(),
                attempt_id: "attempt:indeterminate".to_owned(),
                request_binding_id: "request:indeterminate".to_owned(),
                provider_request_digest,
                outcome: PromptRuntimeTerminalOutcomeV1::Indeterminate,
                end_turn: None,
                terminal_reason_code: Some("ack_lost".to_owned()),
                delivery_observation: None,
                observed_unix_ms: 10,
            })
            .unwrap_or_else(|error| panic!("indeterminate record: {error}"));
    }

    let reopened = AgentdPromptRuntimeOwner::open_state_dir(&root).expect("reopen owner");
    assert!(
        reopened
            .prepare(PromptRuntimePrepareRequest {
                thread_id: "thread:one".to_owned(),
                turn_id: "turn:one".to_owned(),
                model_context_window: Some(4096),
            })
            .is_err()
    );
    reopened
        .record(delivered_terminal(
            &value,
            "attempt:indeterminate",
            "request:indeterminate",
            provider_request_digest,
            11,
        ))
        .unwrap_or_else(|error| panic!("reconcile delivered: {error}"));
    assert_eq!(reopened.staged_count().expect("staged count"), 0);
    assert_eq!(
        reopened
            .terminal_record("attempt:indeterminate")
            .expect("terminal")
            .map(|record| record.outcome),
        Some(PromptRuntimeTerminalOutcomeV1::Delivered)
    );
}

#[test]
fn post_rename_ack_loss_poison_reopens_to_dispatch_claim_not_absent() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let root = temporary.path().join("prompt-runtime");
    let value = attachment();
    {
        let owner = AgentdPromptRuntimeOwner::open_state_dir(&root).expect("open owner");
        stage_raw(&owner, "thread:one", "turn:one", value.clone());
        owner.fail_directory_sync_after_rename_once();
        assert!(
            owner
                .record_dispatch(dispatch(
                    &value,
                    "thread:one",
                    "turn:one",
                    "attempt:ack-loss",
                    "request:ack-loss",
                    digest("provider-request-ack-loss"),
                ))
                .is_err()
        );
        assert!(owner.requires_reopen());
    }

    let reopened = AgentdPromptRuntimeOwner::open_state_dir(&root).expect("reopen owner");
    assert!(
        reopened
            .dispatch_record("attempt:ack-loss")
            .expect("dispatch lookup")
            .is_some()
    );
    assert!(
        reopened
            .prepare(PromptRuntimePrepareRequest {
                thread_id: "thread:one".to_owned(),
                turn_id: "turn:one".to_owned(),
                model_context_window: Some(4096),
            })
            .is_err()
    );
}


struct AcceptPricingEvidence;

impl PromptPricingEvidenceAuthenticatorV1 for AcceptPricingEvidence {
    fn authenticate_pricing_evidence(
        &self,
        _evidence: &PromptPricingEvidenceV1,
        _now_unix_ms: u64,
    ) -> Result<(), PromptAuthenticationErrorV1> {
        Ok(())
    }
}

struct AcceptPromptRelations;

impl PromptRelationSourceAuthenticatorV1 for AcceptPromptRelations {
    fn authenticate_relation_source(
        &self,
        _source: &PromptRelationSourceV1,
        _objective_digest: Digest32,
        _now_unix_ms: u64,
    ) -> Result<(), PromptAuthenticationErrorV1> {
        Ok(())
    }
}

#[test]
fn named_agentd_pipeline_stages_exact_registry_bytes_for_app_server_host() {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("tempdir: {error}"));
    let registry_root = temporary.path().join("prompt-registry");
    let runtime_root = temporary.path().join("prompt-runtime");
    let authority_root = temporary.path().join("prompt-authority");
    let pipeline = AgentdPromptPipelineOwner::open_state_dirs(&registry_root, &runtime_root, 64)
        .unwrap_or_else(|error| panic!("pipeline owner: {error}"));
    let payload = b"Inspect evidence before mutation.";
    let factor = PromptFactor {
        factor_id: id("factor:agentd-product"),
        proposer_id: id("proposer:agentd-product"),
        semantic_version: id("v1"),
        semantic_purpose: "inspect evidence before mutation".to_owned(),
        authority_class: "registered_prompt_factor".to_owned(),
        eligible_objective_dimensions: vec![id("dimension:truth")],
        content_digest: digest("factor:agentd-product"),
        source: FactorSource::GovernedInternal,
        lifecycle: Lifecycle::Draft,
    };
    let signing_key = SigningKey::from_bytes(&[61; 32]);
    let authority = FinalUseAuthority::open_state_dir(
        &authority_root,
        "review-authority:agentd-prompt".to_owned(),
        signing_key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .unwrap_or_else(|error| panic!("authority: {error}"));
    let wall_now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_else(|error| panic!("clock: {error}"))
        .as_millis() as u64;
    let reviewer = id("reviewer:agentd-prompt");
    let admission_scope = digest("scope:agentd-prompt-admission");
    let admission_evidence = digest("evidence:agentd-prompt");
    let admission_binding =
        final_use_admission_binding(&factor, &reviewer, admission_scope, admission_evidence)
            .unwrap_or_else(|error| panic!("admission binding: {error}"));
    let admission_grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "review-authority:agentd-prompt".to_owned(),
        authority_epoch: 1,
        grant_id: "grant:agentd-prompt-admission".to_owned(),
        nonce: [62; 32],
        binding: admission_binding,
        not_before_unix_ms: wall_now.saturating_sub(1_000),
        expires_at_unix_ms: wall_now + 30_000,
    };
    let signed_admission = SignedFinalUseGrant {
        signature: signing_key
            .sign(
                &admission_grant
                    .signing_bytes()
                    .unwrap_or_else(|error| panic!("admission signing bytes: {error}")),
            )
            .to_bytes()
            .to_vec(),
        grant: admission_grant,
    };

    let tuple = PromptModelTupleV2 {
        model_id: id("model:agentd-product"),
        model_version: "2026-09-20".to_owned(),
        model_digest: digest("model:agentd-product"),
        tokenizer_digest: digest("tokenizer:agentd-product"),
        template_digest: digest("template:agentd-product"),
        tool_schema_digest: digest("tool-schema:agentd-product"),
        context_profile_digest: digest("context-profile:agentd-product"),
        locale_id: id("locale:en-US"),
    };
    let realization = PromptRealizationBindingV2 {
        realization_id: id("realization:agentd-product"),
        factor_id: factor.factor_id.clone(),
        model_id: tuple.model_id.clone(),
        model_version: tuple.model_version.clone(),
        model_digest: tuple.model_digest,
        tokenizer_digest: tuple.tokenizer_digest,
        template_digest: tuple.template_digest,
        tool_schema_digest: tuple.tool_schema_digest,
        context_profile_digest: tuple.context_profile_digest,
        locale_id: tuple.locale_id.clone(),
        role: PromptRoleV2::DeveloperInstruction,
        payload_digest: Digest32::of_bytes(payload),
        token_cost: 4,
        expires_unix_ms: None,
    };
    let publisher = id("publisher:agentd-prompt");
    let realization_scope = digest("scope:agentd-prompt-realization");

    {
        let mut registry = pipeline
            .registry
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        registry
            .register_factor(factor.clone())
            .unwrap_or_else(|error| panic!("register factor: {error}"));
        registry
            .admit_factor_final_use(
                &authority,
                &signed_admission,
                &factor.factor_id,
                admission_scope,
                admission_evidence,
            )
            .unwrap_or_else(|error| panic!("admit factor: {error}"));
        let admitted_factor = registry
            .registry()
            .unwrap_or_else(|error| panic!("registry read: {error}"))
            .factor(&factor.factor_id)
            .cloned()
            .unwrap_or_else(|| panic!("admitted factor missing"));
        let realization_binding = final_use_realization_binding(
            &admitted_factor,
            &publisher,
            realization_scope,
            &realization,
            None,
        )
        .unwrap_or_else(|error| panic!("realization binding: {error}"));
        let realization_grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "review-authority:agentd-prompt".to_owned(),
            authority_epoch: 1,
            grant_id: "grant:agentd-prompt-realization".to_owned(),
            nonce: [63; 32],
            binding: realization_binding,
            not_before_unix_ms: wall_now.saturating_sub(1_000),
            expires_at_unix_ms: wall_now + 30_000,
        };
        let signed_realization = SignedFinalUseGrant {
            signature: signing_key
                .sign(
                    &realization_grant
                        .signing_bytes()
                        .unwrap_or_else(|error| panic!("realization signing bytes: {error}")),
                )
                .to_bytes()
                .to_vec(),
            grant: realization_grant,
        };
        registry
            .register_realization_payload_final_use_v2(
                &authority,
                &signed_realization,
                &publisher,
                realization_scope,
                realization,
                payload.to_vec(),
                None,
            )
            .unwrap_or_else(|error| panic!("register realization: {error}"));
    }

    let logical_now = 100_u64;
    let adapter = pipeline
        .candidate_adapter(
            digest("generation:agentd-product"),
            &tuple,
            logical_now,
            vec![factor.factor_id.clone()],
            8,
        )
        .unwrap_or_else(|error| panic!("candidate adapter: {error}"));
    let candidate_set = enumerate_factors_v1(
        PromptCandidateEnumerationRequestV1 {
            enumeration_id: id("enumeration:agentd-product"),
            objective_digest: digest("objective:agentd-product"),
            state_digest: digest("state:agentd-product"),
            maximum_candidates: 8,
            now_unix_ms: logical_now,
            source: adapter.source().clone(),
        },
        &adapter,
    )
    .unwrap_or_else(|error| panic!("enumerate: {error}"));
    let candidate = candidate_set
        .candidates
        .first()
        .unwrap_or_else(|| panic!("candidate missing"));
    let mut evidence = PromptPricingEvidenceV1 {
        candidate_id: candidate.candidate_id.clone(),
        candidate_binding_digest: candidate.binding_digest,
        objective_digest: candidate_set.objective_digest,
        state_digest: candidate_set.state_digest,
        model_profile_digest: candidate_set.model_profile_digest,
        causal_incremental_utility: FixedQ32::ONE,
        confidence: FixedQ32::ONE,
        costs: PromptCostBreakdownV1 {
            tokens: FixedQ32::ZERO,
            latency: FixedQ32::ZERO,
            context_crowding: FixedQ32::ZERO,
            instruction_interference: FixedQ32::ZERO,
            privacy: FixedQ32::ZERO,
            instability: FixedQ32::ZERO,
            future_context_option_value: FixedQ32::ZERO,
        },
        utility_unit_digest: digest("utility-unit:agentd"),
        cost_profile_digest: digest("cost-profile:agentd"),
        support_digest: digest("support:agentd"),
        valid_until_unix_ms: logical_now + 10_000,
        evidence_digest: Digest32::ZERO,
    };
    evidence.evidence_digest = evidence.compute_evidence_digest();
    let pricing = price_factors_v1(
        &candidate_set,
        vec![evidence],
        logical_now,
        &AcceptPricingEvidence,
    )
    .unwrap_or_else(|error| panic!("price: {error}"));

    let mut relations = PromptRelationSourceV1 {
        producer_id: id("knowledge.graph"),
        candidate_set_digest: candidate_set.candidate_set_digest,
        generation_vector_digest: candidate_set.generation_vector_digest,
        hard_constraint_completeness_digest: digest("constraints:complete"),
        interactions: Vec::new(),
        hard_constraints: Vec::new(),
        source_digest: Digest32::ZERO,
    };
    relations.source_digest = relations.compute_source_digest();
    let portfolio = select_portfolio_v1(
        &candidate_set,
        &pricing,
        PromptPortfolioSelectionRequestV1 {
            selection_id: id("selection:agentd-product"),
            token_budget: 128,
            maximum_selected_factors: 1,
            maximum_steps: 8,
            now_unix_ms: logical_now,
            relations: relations.clone(),
        },
        &AcceptPromptRelations,
    )
    .unwrap_or_else(|error| panic!("select: {error}"));
    let exercise_request = PromptExerciseRequestV1 {
        exercise_id: id("exercise:agentd-product"),
        boundary: PromptExerciseBoundaryV1::BeforeModelOrToolDispatch,
        current_state_digest: candidate_set.state_digest,
        now_unix_ms: logical_now,
        current_source: adapter.source().clone(),
    };
    let exercise = exercise_portfolio_v1(
        &candidate_set,
        &pricing,
        &relations,
        &portfolio,
        exercise_request.clone(),
        &adapter,
    )
    .unwrap_or_else(|error| panic!("exercise: {error}"));

    let disposition = pipeline
        .compile_and_stage(
            "thread:product",
            "turn:product",
            "gpt-test",
            wall_now + 60_000,
            &adapter,
            &candidate_set,
            &pricing,
            &relations,
            &portfolio,
            &exercise,
            &exercise_request,
            codex_hepta_intelligence::PromptRegistryCompilationRequestV2 {
                compilation_id: id("compilation:agentd-product"),
                serialization_id: id("serialization:agentd-product"),
                attachment_id: id("attachment:agentd-product"),
                registry_model_tuple: tuple.clone(),
                context_model_profile: ContextModelProfileV2 {
                    model_digest: tuple.model_digest,
                    tokenizer_digest: tuple.tokenizer_digest,
                    template_digest: tuple.template_digest,
                    tool_schema_digest: tuple.tool_schema_digest,
                    maximum_context_tokens: 128,
                },
                now_unix_ms: logical_now,
                token_budget: 128,
                truncation_policy_digest: digest("truncation:agentd-product"),
            },
        )
        .unwrap_or_else(|error| panic!("compile and stage: {error}"));
    assert_eq!(disposition, PromptRuntimeStageDisposition::Inserted);

    let runtime = pipeline.runtime_owner();
    let staged = runtime
        .prepare(PromptRuntimePrepareRequest {
            thread_id: "thread:product".to_owned(),
            turn_id: "turn:product".to_owned(),
            model_context_window: Some(128),
        })
        .unwrap_or_else(|error| panic!("prepare staged product prompt: {error}"))
        .unwrap_or_else(|| panic!("staged attachment missing"));
    assert_eq!(staged.developer_fragments.len(), 1);
    assert_eq!(staged.developer_fragments[0].text.as_bytes(), payload);
}
