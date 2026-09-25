use super::*;
use codex_hepta_prompt_optimizer::canonical::*;
use codex_hepta_types::AuthorityPosture;

use std::collections::BTreeSet;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_context_compiler::ContextModelProfileV2;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
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
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("tempdir: {error}"));
    let root = temporary.path().join("prompt-runtime");
    let value = attachment();
    let first_digest = digest("provider-request-not-dispatched");
    let second_digest = digest("provider-request-retry-final");
    {
        let owner = AgentdPromptRuntimeOwner::open_state_dir(&root)
            .unwrap_or_else(|error| panic!("open owner: {error}"));
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
        assert_eq!(
            owner
                .staged_count()
                .unwrap_or_else(|error| panic!("staged count: {error}")),
            0
        );
    }

    let reopened = AgentdPromptRuntimeOwner::open_state_dir(&root)
        .unwrap_or_else(|error| panic!("reopen owner: {error}"));
    assert_eq!(
        reopened
            .staged_count()
            .unwrap_or_else(|error| panic!("staged count: {error}")),
        0
    );
    assert_eq!(
        reopened
            .terminal_record("attempt:first")
            .unwrap_or_else(|error| panic!("first terminal: {error}"))
            .map(|record| record.outcome),
        Some(PromptRuntimeTerminalOutcomeV1::NotDispatched)
    );
    assert_eq!(
        reopened
            .terminal_record("attempt:second")
            .unwrap_or_else(|error| panic!("second terminal: {error}"))
            .map(|record| record.outcome),
        Some(PromptRuntimeTerminalOutcomeV1::Delivered)
    );
}

#[test]
fn dispatch_without_terminal_reopens_as_unknown_and_blocks_blind_retry() {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("tempdir: {error}"));
    let root = temporary.path().join("prompt-runtime");
    let value = attachment();
    {
        let owner = AgentdPromptRuntimeOwner::open_state_dir(&root)
            .unwrap_or_else(|error| panic!("open owner: {error}"));
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

    let reopened = AgentdPromptRuntimeOwner::open_state_dir(&root)
        .unwrap_or_else(|error| panic!("reopen owner: {error}"));
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
            .unwrap_or_else(|error| panic!("dispatch lookup: {error}"))
            .is_some()
    );
    assert!(
        reopened
            .terminal_record("attempt:unknown")
            .unwrap_or_else(|error| panic!("terminal lookup: {error}"))
            .is_none()
    );
}

#[test]
fn indeterminate_terminal_reopens_blocked_and_reconciles_monotonically() {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("tempdir: {error}"));
    let root = temporary.path().join("prompt-runtime");
    let value = attachment();
    let provider_request_digest = digest("provider-request-indeterminate");
    {
        let owner = AgentdPromptRuntimeOwner::open_state_dir(&root)
            .unwrap_or_else(|error| panic!("open owner: {error}"));
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

    let reopened = AgentdPromptRuntimeOwner::open_state_dir(&root)
        .unwrap_or_else(|error| panic!("reopen owner: {error}"));
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
    assert_eq!(
        reopened
            .staged_count()
            .unwrap_or_else(|error| panic!("staged count: {error}")),
        0
    );
    assert_eq!(
        reopened
            .terminal_record("attempt:indeterminate")
            .unwrap_or_else(|error| panic!("terminal: {error}"))
            .map(|record| record.outcome),
        Some(PromptRuntimeTerminalOutcomeV1::Delivered)
    );
}

#[test]
fn post_rename_ack_loss_poison_reopens_to_dispatch_claim_not_absent() {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("tempdir: {error}"));
    let root = temporary.path().join("prompt-runtime");
    let value = attachment();
    {
        let owner = AgentdPromptRuntimeOwner::open_state_dir(&root)
            .unwrap_or_else(|error| panic!("open owner: {error}"));
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

    let reopened = AgentdPromptRuntimeOwner::open_state_dir(&root)
        .unwrap_or_else(|error| panic!("reopen owner: {error}"));
    assert!(
        reopened
            .dispatch_record("attempt:ack-loss")
            .unwrap_or_else(|error| panic!("dispatch lookup: {error}"))
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

// A signed-registry fixture for send/recovery boundary tests, not an independent
// Generator/Evaluator selection or real provider execution qualification.
fn staged_pipeline_fixture() -> (
    tempfile::TempDir,
    Arc<AgentdPromptPipelineOwner>,
    FinalUseAuthority,
    SigningKey,
) {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("tempdir: {error}"));
    let registry_root = temporary.path().join("prompt-registry");
    let runtime_root = temporary.path().join("prompt-runtime");
    let authority_root = temporary.path().join("prompt-authority");
    let checkpoint = temporary
        .path()
        .join("prompt-witness")
        .join("registry.json");
    let pipeline = AgentdPromptPipelineOwner::open_state_dirs(
        &registry_root,
        Some(&checkpoint),
        "agent:test:prompt.registry",
        &runtime_root,
        64,
    )
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
                realization.clone(),
                payload.to_vec(),
                None,
            )
            .unwrap_or_else(|error| panic!("register realization: {error}"));
    }

    let logical_now = current_unix_ms().unwrap_or_else(|error| panic!("clock: {error}"));
    let candidates = pipeline
        .enumerate_candidates(PromptEnumerationRequestV1 {
            set_id: id("enumeration:agentd-product"),
            objective_digest: digest("objective:agentd-product"),
            state_digest: digest("state:agentd-product"),
            generation_vector_digest: digest("generation:agentd-product"),
            model_tuple: tuple.clone(),
            now_unix_ms: logical_now,
            required_factor_ids: vec![factor.factor_id.clone()],
            maximum_candidates: 8,
            selection_grammar_digest: digest("grammar:agentd-product"),
        })
        .unwrap_or_else(|error| panic!("enumerate: {error}"));
    assert_eq!(candidates.candidates[0].realization, realization);
    let portfolio = SelectedPromptPortfolioV1 {
        receipt: PromptPortfolioReceiptV1 {
            portfolio_id: id("portfolio:agentd-product"),
            candidate_set_digest: candidates.receipt.receipt_digest,
            factor_ids: vec![factor.factor_id],
            interaction_digest: digest("interaction"),
            expected_utility_q32: FixedQ32::ONE,
            total_token_upper_bound: 4,
            valid_until_unix_ms: logical_now + 60_000,
            receipt_digest: digest("portfolio-receipt"),
            authority: AuthorityPosture::DENY_ALL,
        },
        selected: candidates.candidates,
        objective_digest: digest("objective:agentd-product"),
        state_digest: digest("state:agentd-product"),
        model_tuple: tuple.clone(),
        model_tuple_digest: tuple.digest(),
        generation_vector_digest: digest("generation:agentd-product"),
        pricing_set_digest: digest("pricing-set"),
        graph_generation_digest: digest("graph-generation"),
        selection_method: PromptSelectionMethodV1::GreedyPrerequisiteBundleV1,
        optimality: PromptOptimalityDisclosureV1::HeuristicNoCertificate,
    };
    let exercise_request = PromptExerciseRequestV1 {
        decision_boundary: PromptDecisionBoundaryV1::BeforeModelOrToolDispatch,
        current_state_digest: portfolio.state_digest,
        generation_vector_digest: portfolio.generation_vector_digest,
        model_tuple: tuple.clone(),
        now_unix_ms: logical_now,
        wait_value_q32: FixedQ32::ZERO,
        policy_digest: digest("exercise-policy"),
    };

    let disposition = pipeline
        .compile_and_stage(
            "thread:product",
            "turn:product",
            "gpt-test",
            wall_now + 60_000,
            &portfolio,
            &exercise_request,
            codex_hepta_intelligence::PromptRegistryCompilationRequestV2 {
                compilation_id: id("compilation:agentd-product"),
                serialization_id: id("serialization:agentd-product"),
                attachment_id: id("attachment:agentd-product"),
                registry_model_tuple: tuple.clone(),
                context_model_profile: ContextModelProfileV2 {
                    model_digest: tuple.model_digest,
                    provider_id_digest: digest("provider:agentd-product"),
                    provider_model_digest: tuple.model_digest,
                    tokenizer_digest: tuple.tokenizer_digest,
                    serializer_digest: digest("serializer:agentd-product"),
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

    let staged = pipeline
        .prepare_for_provider(PromptRuntimePrepareRequest {
            thread_id: "thread:product".to_owned(),
            turn_id: "turn:product".to_owned(),
            model_context_window: Some(128),
        })
        .unwrap_or_else(|error| panic!("prepare staged product prompt: {error}"))
        .unwrap_or_else(|| panic!("staged attachment missing"));
    assert_eq!(staged.developer_fragments.len(), 1);
    assert_eq!(staged.developer_fragments[0].text.as_bytes(), payload);
    (temporary, Arc::new(pipeline), authority, signing_key)
}

#[test]
fn named_agentd_pipeline_stages_exact_registry_bytes_for_app_server_host() {
    let (_temporary, pipeline, _authority, _key) = staged_pipeline_fixture();
    let staged = pipeline
        .prepare_for_provider(product_prepare())
        .unwrap_or_else(|error| panic!("guarded preparation: {error}"));
    assert!(staged.is_some());
}

#[test]
fn owner_remains_send_sync_with_fault_injection() {
    fn assert_send_sync<T: Send + Sync>() {}
    assert_send_sync::<super::AgentdPromptRuntimeOwner>();
}

fn product_prepare() -> PromptRuntimePrepareRequest {
    PromptRuntimePrepareRequest {
        thread_id: "thread:product".to_owned(),
        turn_id: "turn:product".to_owned(),
        model_context_window: Some(128),
    }
}

fn revoke_product_factor(
    pipeline: &AgentdPromptPipelineOwner,
    authority: &FinalUseAuthority,
    signing_key: &SigningKey,
) {
    let mut registry = pipeline
        .registry
        .lock()
        .unwrap_or_else(PoisonError::into_inner);
    let factor = registry
        .registry()
        .unwrap_or_else(|error| panic!("registry: {error}"))
        .factor(&id("factor:agentd-product"))
        .cloned()
        .unwrap_or_else(|| panic!("factor"));
    let actor = id("operator:prompt-revocation");
    let scope = digest("scope:prompt-revocation");
    let reason = digest("reason:prompt-revocation");
    let now = current_unix_ms().unwrap_or_else(|error| panic!("clock: {error}"));
    let binding =
        codex_hepta_prompt_registry::final_use_revoke_binding(&factor, &actor, scope, reason, now)
            .unwrap_or_else(|error| panic!("binding: {error}"));
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "review-authority:agentd-prompt".to_owned(),
        authority_epoch: 1,
        grant_id: "grant:agentd-prompt-revocation".to_owned(),
        nonce: [64; 32],
        binding,
        not_before_unix_ms: now.saturating_sub(1000),
        expires_at_unix_ms: now + 60_000,
    };
    let signed = SignedFinalUseGrant {
        signature: signing_key
            .sign(
                &grant
                    .signing_bytes()
                    .unwrap_or_else(|error| panic!("sign: {error}")),
            )
            .to_bytes()
            .to_vec(),
        grant,
    };
    registry
        .revoke_factor_final_use(
            authority,
            &signed,
            &factor.factor_id,
            &actor,
            scope,
            reason,
            now,
        )
        .unwrap_or_else(|error| panic!("durable revocation: {error}"));
}

#[test]
fn revocation_after_staging_blocks_prepare_and_dispatch_after_full_reopen() {
    let (temporary, pipeline, authority, key) = staged_pipeline_fixture();
    let attachment = pipeline
        .prepare_for_provider(product_prepare())
        .unwrap_or_else(|error| panic!("prepare: {error}"))
        .unwrap_or_else(|| panic!("attachment"));
    let mut claim = dispatch(
        &attachment,
        "thread:product",
        "turn:product",
        "attempt:revoked",
        "request:revoked",
        digest("wire:revoked"),
    );
    claim.dispatched_unix_ms = current_unix_ms().unwrap_or_else(|error| panic!("clock: {error}"));
    revoke_product_factor(&pipeline, &authority, &key);
    assert!(pipeline.prepare_for_provider(product_prepare()).is_err());
    assert!(pipeline.admit_provider_dispatch(claim.clone()).is_err());
    assert!(
        pipeline
            .runtime
            .dispatch_record(&claim.attempt_id)
            .unwrap_or_else(|error| panic!("lookup: {error}"))
            .is_none()
    );
    drop(pipeline);
    let reopened = AgentdPromptPipelineOwner::open_state_dirs(
        &temporary.path().join("prompt-registry"),
        Some(
            &temporary
                .path()
                .join("prompt-witness")
                .join("registry.json"),
        ),
        "agent:test:prompt.registry",
        &temporary.path().join("prompt-runtime"),
        64,
    )
    .unwrap_or_else(|error| panic!("reopen: {error}"));
    assert!(reopened.prepare_for_provider(product_prepare()).is_err());
    assert!(reopened.admit_provider_dispatch(claim).is_err());
}

#[test]
fn send_revalidation_uses_current_time_not_prequeue_dispatch_time() {
    let (_temporary, pipeline, _authority, _key) = staged_pipeline_fixture();
    let mut attachment = pipeline
        .prepare_for_provider(product_prepare())
        .unwrap_or_else(|error| panic!("prepare: {error}"))
        .unwrap_or_else(|| panic!("attachment"));
    let now = current_unix_ms().unwrap_or_else(|error| panic!("clock: {error}"));
    attachment.deadline_ms = now.saturating_sub(1);
    attachment.source_binding_digest = attachment.compute_binding_digest();
    pipeline
        .runtime
        .commit_state(|state| {
            let key = PromptRuntimeKey {
                thread_id: "thread:product".into(),
                turn_id: "turn:product".into(),
            };
            let lease = state
                .registry_leases
                .get_mut(&key)
                .ok_or(AgentdPromptRuntimeError::CorruptState)?;
            lease.valid_until_unix_ms = attachment.deadline_ms;
            lease.attachment_source_binding_digest = attachment.source_binding_digest;
            lease.lease_digest = lease.compute_digest();
            state.staged.insert(key, attachment.clone());
            Ok(())
        })
        .unwrap_or_else(|error| panic!("simulate elapsed queue deadline: {error}"));
    let mut claim = dispatch(
        &attachment,
        "thread:product",
        "turn:product",
        "attempt:expired",
        "request:expired",
        digest("wire:expired"),
    );
    claim.dispatched_unix_ms = now.saturating_sub(1000);
    assert!(pipeline.admit_provider_dispatch(claim.clone()).is_err());
    assert!(
        pipeline
            .runtime
            .dispatch_record(&claim.attempt_id)
            .unwrap_or_else(|error| panic!("lookup: {error}"))
            .is_none()
    );
}

#[test]
fn missing_source_lease_cannot_be_sent_through_product_host() {
    let (_temporary, pipeline, _authority, _key) = staged_pipeline_fixture();
    pipeline
        .runtime
        .commit_state(|state| {
            state.registry_leases.clear();
            Ok(())
        })
        .unwrap_or_else(|error| panic!("legacy stage: {error}"));
    assert!(pipeline.prepare_for_provider(product_prepare()).is_err());
}

#[test]
fn accepted_dispatch_reopens_indeterminate_and_cannot_be_blindly_sent_again() {
    let (temporary, pipeline, _authority, _key) = staged_pipeline_fixture();
    let attachment = pipeline
        .prepare_for_provider(product_prepare())
        .unwrap_or_else(|error| panic!("prepare: {error}"))
        .unwrap_or_else(|| panic!("attachment"));
    let mut claim = dispatch(
        &attachment,
        "thread:product",
        "turn:product",
        "attempt:crash",
        "request:crash",
        digest("wire:crash"),
    );
    claim.dispatched_unix_ms = current_unix_ms().unwrap_or_else(|error| panic!("clock: {error}"));
    pipeline
        .admit_provider_dispatch(claim.clone())
        .unwrap_or_else(|error| panic!("admit: {error}"));
    assert!(
        pipeline.admit_provider_dispatch(claim.clone()).is_err(),
        "durable claim retry is not a fresh send permission"
    );
    drop(pipeline);
    let reopened = AgentdPromptPipelineOwner::open_state_dirs(
        &temporary.path().join("prompt-registry"),
        Some(
            &temporary
                .path()
                .join("prompt-witness")
                .join("registry.json"),
        ),
        "agent:test:prompt.registry",
        &temporary.path().join("prompt-runtime"),
        64,
    )
    .unwrap_or_else(|error| panic!("reopen: {error}"));
    assert!(reopened.prepare_for_provider(product_prepare()).is_err());
    assert_eq!(
        reopened
            .runtime
            .dispatch_record(&claim.attempt_id)
            .unwrap_or_else(|error| panic!("lookup: {error}")),
        Some(claim)
    );
}

#[test]
fn extra_staging_cannot_consume_reserved_terminal_capacity() {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("temp: {error}"));
    let path = temporary.path().join("runtime");
    let owner = AgentdPromptRuntimeOwner::open_state_dir(&path)
        .unwrap_or_else(|error| panic!("owner: {error}"));
    let value = attachment();
    stage_raw(&owner, "thread:one", "turn:one", value.clone());
    let wire = digest("capacity:wire");
    owner
        .record_dispatch(dispatch(
            &value,
            "thread:one",
            "turn:one",
            "attempt:capacity",
            "request:capacity",
            wire,
        ))
        .unwrap_or_else(|error| panic!("dispatch: {error}"));
    let current = owner
        .state
        .lock()
        .unwrap_or_else(PoisonError::into_inner)
        .clone();
    let before =
        std::fs::read(path.join(STATE_FILE)).unwrap_or_else(|error| panic!("manifest: {error}"));
    let limit = before.len() as u64
        + capacity::reserved_bytes(&current).unwrap_or_else(|error| panic!("reserve: {error}"));
    owner
        .store
        .as_ref()
        .unwrap_or_else(|| panic!("store"))
        .metadata_limit
        .store(limit, Ordering::Release);
    let rejected = owner.commit_state(|state| {
        state.staged.insert(
            PromptRuntimeKey {
                thread_id: "thread:extra".into(),
                turn_id: "turn:extra".into(),
            },
            value.clone(),
        );
        Ok(())
    });
    assert!(matches!(
        rejected,
        Err(AgentdPromptRuntimeError::CapacityExceeded)
    ));
    assert_eq!(
        std::fs::read(path.join(STATE_FILE)).unwrap_or_else(|error| panic!("unchanged: {error}")),
        before
    );
    let mut terminal = delivered_terminal(&value, "attempt:capacity", "request:capacity", wire, 11);
    terminal.end_turn = Some(false); // Keep the stage: the reserve, not deletion, must make room.
    terminal
        .delivery_observation
        .as_mut()
        .unwrap_or_else(|| panic!("observation"))
        .observed_token_positions = Some(
        (0..codex_hepta_types::MAX_PROMPT_TOKEN_POSITIONS_V1)
            .map(|n| u32::MAX - (codex_hepta_types::MAX_PROMPT_TOKEN_POSITIONS_V1 - 1 - n) as u32)
            .collect(),
    );
    terminal
        .validate()
        .unwrap_or_else(|error| panic!("maximum legal terminal: {error}"));
    owner
        .record(terminal.clone())
        .unwrap_or_else(|error| panic!("reserved terminal: {error}"));
    drop(owner);
    let reopened = AgentdPromptRuntimeOwner::open_state_dir(&path)
        .unwrap_or_else(|error| panic!("reopen: {error}"));
    assert_eq!(
        reopened
            .terminal_record("attempt:capacity")
            .unwrap_or_else(|error| panic!("lookup: {error}")),
        Some(terminal)
    );
}

#[test]
fn retired_agent_generation_cannot_admit_still_live_registry_payload() {
    let (_temporary, pipeline, _authority, _key) = staged_pipeline_fixture();
    let attachment = pipeline
        .prepare_for_provider(product_prepare())
        .unwrap_or_else(|error| panic!("prepare: {error}"))
        .unwrap_or_else(|| panic!("attachment"));
    let mut claim = dispatch(
        &attachment,
        "thread:product",
        "turn:product",
        "attempt:fenced",
        "request:fenced",
        digest("wire:fenced"),
    );
    claim.dispatched_unix_ms = current_unix_ms().unwrap_or_else(|error| panic!("clock: {error}"));
    assert!(
        pipeline
            .admit_provider_dispatch_with_fence(claim.clone(), || Err(
                AgentdPromptRuntimeError::GenerationFenced
            ))
            .is_err()
    );
    assert!(
        pipeline
            .runtime
            .dispatch_record(&claim.attempt_id)
            .unwrap_or_else(|error| panic!("lookup: {error}"))
            .is_none()
    );
}

#[test]
fn cleared_not_dispatched_turn_reopens_without_forgetting_its_attempt() {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("temp: {error}"));
    let root = temporary.path().join("runtime");
    let owner = AgentdPromptRuntimeOwner::open_state_dir(&root)
        .unwrap_or_else(|error| panic!("owner: {error}"));
    let value = attachment();
    stage_raw(&owner, "thread:one", "turn:one", value.clone());
    let wire = digest("wire:cancelled");
    let claim = dispatch(
        &value,
        "thread:one",
        "turn:one",
        "attempt:cancelled",
        "request:cancelled",
        wire,
    );
    owner
        .record_dispatch(claim.clone())
        .unwrap_or_else(|error| panic!("claim: {error}"));
    let mut terminal =
        delivered_terminal(&value, "attempt:cancelled", "request:cancelled", wire, 11);
    terminal.outcome = PromptRuntimeTerminalOutcomeV1::NotDispatched;
    terminal.end_turn = None;
    terminal.terminal_reason_code = Some("before_send_cancelled".to_owned());
    terminal.delivery_observation = None;
    owner
        .record(terminal.clone())
        .unwrap_or_else(|error| panic!("not dispatched: {error}"));
    assert!(
        owner
            .clear_turn("thread:one", "turn:one")
            .unwrap_or_else(|error| panic!("clear: {error}"))
    );
    drop(owner);
    let reopened = AgentdPromptRuntimeOwner::open_state_dir(&root)
        .unwrap_or_else(|error| panic!("reopen: {error}"));
    assert_eq!(
        reopened
            .dispatch_record(&claim.attempt_id)
            .unwrap_or_else(|error| panic!("dispatch: {error}")),
        Some(claim)
    );
    assert_eq!(
        reopened
            .terminal_record(&terminal.attempt_id)
            .unwrap_or_else(|error| panic!("terminal: {error}")),
        Some(terminal)
    );
    assert!(
        reopened
            .prepare(PromptRuntimePrepareRequest {
                thread_id: "thread:one".into(),
                turn_id: "turn:one".into(),
                model_context_window: None
            })
            .is_err()
    );
    assert_eq!(
        reopened
            .staged_count()
            .unwrap_or_else(|error| panic!("count: {error}")),
        0
    );
}

#[test]
fn fence_after_dispatch_persistence_records_not_dispatched_and_denies_send() {
    let (temporary, pipeline, _authority, _key) = staged_pipeline_fixture();
    let attachment = pipeline
        .prepare_for_provider(product_prepare())
        .unwrap_or_else(|error| panic!("prepare: {error}"))
        .unwrap_or_else(|| panic!("attachment"));
    let mut claim = dispatch(
        &attachment,
        "thread:product",
        "turn:product",
        "attempt:late-fence",
        "request:late-fence",
        digest("wire:late-fence"),
    );
    claim.dispatched_unix_ms = current_unix_ms().unwrap_or_else(|error| panic!("clock: {error}"));
    let calls = std::sync::atomic::AtomicUsize::new(0);
    assert!(
        pipeline
            .admit_provider_dispatch_with_fence(claim.clone(), || {
                if calls.fetch_add(1, Ordering::SeqCst) == 0 {
                    Ok(())
                } else {
                    Err(AgentdPromptRuntimeError::GenerationFenced)
                }
            })
            .is_err()
    );
    assert_eq!(calls.load(Ordering::SeqCst), 2);
    let terminal = pipeline
        .runtime
        .terminal_record(&claim.attempt_id)
        .unwrap_or_else(|error| panic!("lookup: {error}"))
        .unwrap_or_else(|| panic!("durable local terminal"));
    assert_eq!(
        terminal.outcome,
        PromptRuntimeTerminalOutcomeV1::NotDispatched
    );
    assert!(terminal.delivery_observation.is_none());
    assert!(pipeline.admit_provider_dispatch(claim.clone()).is_err());
    drop(pipeline);
    let reopened = AgentdPromptPipelineOwner::open_state_dirs(
        &temporary.path().join("prompt-registry"),
        Some(
            &temporary
                .path()
                .join("prompt-witness")
                .join("registry.json"),
        ),
        "agent:test:prompt.registry",
        &temporary.path().join("prompt-runtime"),
        64,
    )
    .unwrap_or_else(|error| panic!("reopen: {error}"));
    assert_eq!(
        reopened
            .runtime
            .terminal_record(&claim.attempt_id)
            .unwrap_or_else(|error| panic!("lookup after reopen: {error}")),
        Some(terminal)
    );
}
