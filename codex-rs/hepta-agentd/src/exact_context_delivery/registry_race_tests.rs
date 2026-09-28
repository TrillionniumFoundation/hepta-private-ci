//! Real registry-owner mutation at the tokenizer barrier. The child below is a
//! deterministic protocol fixture, not a qualified provider tokenizer.
#![cfg(unix)]

use super::*;
use codex_hepta_codex_adapter::{
    PromptRuntimeAttachmentV1, PromptRuntimeDeveloperFragmentV1, PromptRuntimeExactAttemptV2,
};
use codex_hepta_contracts::{
    FinalUseAuthority, FinalUseGrant, FinalUseRevocations, SignedFinalUseGrant,
};
use codex_hepta_intelligence::{
    PromptExactTokenizerV3, PromptExecutionProfileV3, PromptRegistryCompilationRequestV3,
    PromptTokenizerIdentityV3, compile_prompt_registry_v3,
};
use codex_hepta_prompt_optimizer::canonical::*;
use codex_hepta_prompt_registry::{
    FactorSource, Lifecycle, PromptFactor, PromptModelTupleV2, PromptRealizationBindingV2,
    PromptRoleV2, final_use_admission_binding, final_use_realization_binding,
    final_use_revoke_binding,
};
use codex_hepta_types::{AuthorityPosture, FixedQ32};
use ed25519_dalek::{Signer, SigningKey};
use std::os::unix::fs::PermissionsExt;

fn id(text: &str) -> StableId {
    StableId::new(text).expect("fixture id")
}

fn digest(text: &str) -> Digest32 {
    Digest32::of_bytes(text.as_bytes())
}

fn nonce(label: &str) -> [u8; 32] {
    digest(label).into_array()
}

fn sign(key: &SigningKey, grant: FinalUseGrant) -> SignedFinalUseGrant {
    SignedFinalUseGrant {
        signature: key
            .sign(&grant.signing_bytes().expect("signing bytes"))
            .to_bytes()
            .to_vec(),
        grant,
    }
}

#[derive(Clone)]
struct CompilationTokenizer {
    identity: PromptTokenizerIdentityV3,
}

impl PromptExactTokenizerV3 for CompilationTokenizer {
    fn identity(&self) -> PromptTokenizerIdentityV3 {
        self.identity.clone()
    }

    fn count_tokens(&self, bytes: &[u8]) -> Result<u64, String> {
        u64::try_from(bytes.len())
            .ok()
            .filter(|count| *count > 0)
            .ok_or_else(|| "invalid deterministic fixture length".to_owned())
    }
}

struct Fixture {
    directory: tempfile::TempDir,
    registry_path: PathBuf,
    runtime_path: PathBuf,
    owner: Arc<AgentdExactContextDeliveryOwner>,
    authority: FinalUseAuthority,
    key: SigningKey,
    request: PromptRuntimeFinalRequestV2,
    entered: PathBuf,
    release: PathBuf,
    now: u64,
}

impl Fixture {
    fn new() -> Self {
        let directory = tempfile::tempdir().expect("tempdir");
        let entered = directory.path().join("entered");
        let release = directory.path().join("release");
        let binary = directory.path().join("tokenizer.py");
        let vocabulary = directory.path().join("vocabulary");
        let script = format!(
            "#!/usr/bin/env python3\nimport sys,time,pathlib\nsys.stdin.buffer.read()\npathlib.Path({}).write_text('entered')\nwhile not pathlib.Path({}).exists(): time.sleep(0.005)\nprint(17)\n",
            serde_json::to_string(&entered.to_string_lossy()).expect("path"),
            serde_json::to_string(&release.to_string_lossy()).expect("path"),
        );
        std::fs::write(&binary, script).expect("fixture tokenizer");
        std::fs::set_permissions(&binary, std::fs::Permissions::from_mode(0o700)).expect("chmod");
        std::fs::write(&vocabulary, b"protocol-only fixture").expect("vocabulary");

        let registry_path = directory.path().join("registry");
        let mut registry =
            DurablePromptRegistry::open_state_dir(&registry_path, 64).expect("registry");
        let factor = PromptFactor {
            factor_id: id("factor:verify"),
            proposer_id: id("proposer:1"),
            semantic_version: id("v1"),
            semantic_purpose: "inspect evidence before mutation".into(),
            authority_class: "registered_prompt_factor".into(),
            eligible_objective_dimensions: vec![id("dimension:truth")],
            content_digest: digest("factor:verify"),
            source: FactorSource::GovernedInternal,
            lifecycle: Lifecycle::Draft,
        };
        registry
            .register_factor(factor.clone())
            .expect("register factor");
        let key = SigningKey::from_bytes(&[23; 32]);
        let authority = FinalUseAuthority::open_state_dir(
            &directory.path().join("authority"),
            "review-authority:prompt".into(),
            key.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 1,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )
        .expect("authority");
        let now = current_unix_ms().expect("clock");
        let scope = digest("scope:prompt");
        let evidence = digest("evidence:prompt");
        let grant = sign(
            &key,
            FinalUseGrant {
                schema_version: 1,
                signer_id: "review-authority:prompt".into(),
                authority_epoch: 1,
                grant_id: "admission:prompt:1".into(),
                nonce: nonce("admission:prompt:1"),
                binding: final_use_admission_binding(&factor, &id("reviewer:1"), scope, evidence)
                    .expect("binding"),
                not_before_unix_ms: now.saturating_sub(1000),
                expires_at_unix_ms: now + 30_000,
            },
        );
        registry
            .admit_factor_final_use(&authority, &grant, &factor.factor_id, scope, evidence)
            .expect("admission");
        let admitted_factor = registry
            .registry()
            .expect("view")
            .factor(&factor.factor_id)
            .cloned()
            .expect("factor");
        let tuple = PromptModelTupleV2 {
            model_id: id("model:hepta-test"),
            model_version: "2026-09-18".into(),
            model_digest: digest("model"),
            tokenizer_digest: digest("tokenizer"),
            template_digest: digest("template"),
            tool_schema_digest: digest("tool-schema"),
            context_profile_digest: digest("context-profile"),
            locale_id: id("locale:en-US"),
        };
        let payload = b"Inspect evidence before mutation.";
        let realization = PromptRealizationBindingV2 {
            realization_id: id("realization:verify"),
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
        let publisher = id("publisher:prompt");
        let publish_scope = digest("scope:realization");
        let grant = sign(
            &key,
            FinalUseGrant {
                schema_version: 1,
                signer_id: "review-authority:prompt".into(),
                authority_epoch: 1,
                grant_id: "realization:prompt:1".into(),
                nonce: nonce("realization:prompt:1"),
                binding: final_use_realization_binding(
                    &admitted_factor,
                    &publisher,
                    publish_scope,
                    &realization,
                    None,
                )
                .expect("binding"),
                not_before_unix_ms: now.saturating_sub(1000),
                expires_at_unix_ms: now + 30_000,
            },
        );
        registry
            .register_realization_payload_final_use_v2(
                &authority,
                &grant,
                &publisher,
                publish_scope,
                realization,
                payload.to_vec(),
                None,
            )
            .expect("realization");
        let candidates = enumerate_factors_v1(
            registry.registry().expect("view"),
            PromptEnumerationRequestV1 {
                set_id: id("set:canonical"),
                objective_digest: digest("objective"),
                state_digest: digest("state"),
                generation_vector_digest: digest("generation-vector"),
                model_tuple: tuple.clone(),
                now_unix_ms: now,
                required_factor_ids: vec![factor.factor_id],
                maximum_candidates: 8,
                selection_grammar_digest: digest("grammar"),
            },
        )
        .expect("enumeration");
        let portfolio = SelectedPromptPortfolioV1 {
            receipt: PromptPortfolioReceiptV1 {
                portfolio_id: id("portfolio:1"),
                candidate_set_digest: candidates.receipt.receipt_digest,
                factor_ids: vec![id("factor:verify")],
                interaction_digest: digest("interaction"),
                expected_utility_q32: FixedQ32::ONE,
                total_token_upper_bound: 4,
                valid_until_unix_ms: now + 30_000,
                receipt_digest: digest("portfolio-receipt"),
                authority: AuthorityPosture::DENY_ALL,
            },
            selected: candidates.candidates,
            objective_digest: digest("objective"),
            state_digest: digest("state"),
            model_tuple: tuple.clone(),
            model_tuple_digest: tuple.digest(),
            generation_vector_digest: digest("generation-vector"),
            pricing_set_digest: digest("pricing-set"),
            graph_generation_digest: digest("graph-generation"),
            selection_method: PromptSelectionMethodV1::GreedyPrerequisiteBundleV1,
            optimality: PromptOptimalityDisclosureV1::HeuristicNoCertificate,
        };
        let exercise = PromptExerciseRequestV1 {
            decision_boundary: PromptDecisionBoundaryV1::BeforeModelOrToolDispatch,
            current_state_digest: digest("state"),
            generation_vector_digest: digest("generation-vector"),
            model_tuple: tuple.clone(),
            now_unix_ms: now,
            wait_value_q32: FixedQ32::ZERO,
            policy_digest: digest("exercise-policy"),
        };
        let tokenizer_identity = PromptTokenizerIdentityV3 {
            tokenizer_digest: tuple.tokenizer_digest,
            binary_digest: hash_bounded_file(&binary).expect("binary pin"),
            vocabulary_digest: hash_bounded_file(&vocabulary).expect("vocabulary pin"),
            normalization_policy_digest: digest("none"),
            version: "fixture-v1".into(),
        };
        let execution_profile = PromptExecutionProfileV3 {
            provider_id: "provider".into(),
            provider_revision: "provider-v1".into(),
            provider_model: "model".into(),
            model_revision: tuple.model_version.clone(),
            tokenizer: tokenizer_identity.clone(),
            serializer_revision: "serializer-v3".into(),
            template_digest: tuple.template_digest,
            template_revision: "template-v1".into(),
            tool_schema_digest: tuple.tool_schema_digest,
            tool_schema_revision: "tool-schema-v1".into(),
            maximum_context_tokens: 1000,
        };
        let compiled = compile_prompt_registry_v3(
            &registry,
            &portfolio,
            &exercise,
            PromptRegistryCompilationRequestV3 {
                compilation_id: id("compilation:race"),
                serialization_id: id("serialization:race"),
                attachment_id: id("attachment:race"),
                registry_model_tuple: tuple.clone(),
                execution_profile,
                now_unix_ms: now,
                token_budget: 1000,
                truncation_policy_digest: digest("truncation"),
            },
            &CompilationTokenizer {
                identity: tokenizer_identity.clone(),
            },
        )
        .expect("compiled context");
        let context = String::from_utf8(compiled.payload().to_vec()).expect("context UTF-8");
        let attachment = PromptRuntimeAttachmentV1::new(
            compiled.compiled.receipt().compilation_id().clone(),
            compiled.attachment.attachment_digest(),
            compiled.attachment.payload_digest(),
            "model",
            now + 30_000,
            vec![PromptRuntimeDeveloperFragmentV1::new(context.clone()).expect("fragment")],
        )
        .expect("attachment");
        let canonical_request = serde_json::to_vec(&serde_json::json!({
            "model": "model",
            "input": [{
                "role": "developer",
                "content": [{"type": "input_text", "text": context}]
            }]
        }))
        .expect("request JSON");
        let request = PromptRuntimeFinalRequestV2 {
            attachment,
            attempt: PromptRuntimeExactAttemptV2 {
                thread_id: "thread-a".into(),
                turn_id: "turn-a".into(),
                attempt_id: "attempt-a".into(),
                request_binding_id: "binding-a".into(),
                request_kind: PromptRuntimeRequestKindV2::Turn,
                provider_id: "provider".into(),
                provider_config_digest: digest("provider-config"),
                model: "model".into(),
                transport: PromptRuntimeTransportV2::Http,
                endpoint_digest: digest("endpoint"),
                logical_request_digest: digest("logical"),
                provider_wire_semantic_digest: digest("wire"),
                ephemeral_input_digest: Some(Digest32::of_bytes(&canonical_request)),
                ephemeral_input_witness_digest: Some(digest("provider-input-witness")),
                previous_response_id_digest: None,
                generate: true,
            },
            canonical_request,
        };
        let runtime_path = directory.path().join("runtime");
        let owner = Arc::new(
            AgentdExactContextDeliveryOwner::open(&runtime_path, Arc::new(Mutex::new(registry)))
                .expect("owner"),
        );
        owner.stage("thread-a", "turn-a", compiled).expect("stage");
        let identity = FinalRequestTokenizerIdentityV2::new(
            digest("provider"),
            digest("model"),
            tuple.tokenizer_digest,
            tokenizer_identity.binary_digest,
            digest("fixture-v1"),
            tokenizer_identity.vocabulary_digest,
            tokenizer_identity.normalization_policy_digest,
        )
        .expect("identity");
        *owner.tokenizer.lock().expect("configuration") = Some(Arc::new(TokenizerRuntimeConfig {
            binary,
            vocabulary,
            provider_id: "provider".into(),
            model: "model".into(),
            version: "fixture-v1".into(),
            normalization: "none".into(),
            timeout: Duration::from_secs(5),
            identity,
        }));
        Self {
            directory,
            registry_path,
            runtime_path,
            owner,
            authority,
            key,
            request,
            entered,
            release,
            now,
        }
    }

    async fn wait_for_tokenizer(&self) {
        tokio::time::timeout(Duration::from_secs(3), async {
            while !self.entered.exists() {
                tokio::time::sleep(Duration::from_millis(5)).await;
            }
        })
        .await
        .expect("tokenizer barrier");
    }

    fn revoke(&self) {
        let mut registry = self.owner.registry.lock().expect("registry");
        let factor = registry
            .registry()
            .expect("view")
            .factor(&id("factor:verify"))
            .cloned()
            .expect("factor");
        let actor = id("revoker:test");
        let scope = digest("revoke-scope");
        let reason = digest("revoked-during-tokenization");
        let cutoff = current_unix_ms().expect("clock");
        let grant = sign(
            &self.key,
            FinalUseGrant {
                schema_version: 1,
                signer_id: "review-authority:prompt".into(),
                authority_epoch: 1,
                grant_id: "revoke:prompt:1".into(),
                nonce: nonce("revoke:prompt:1"),
                binding: final_use_revoke_binding(&factor, &actor, scope, reason, cutoff)
                    .expect("binding"),
                not_before_unix_ms: self.now.saturating_sub(1000),
                expires_at_unix_ms: self.now + 30_000,
            },
        );
        registry
            .revoke_factor_final_use(
                &self.authority,
                &grant,
                &factor.factor_id,
                &actor,
                scope,
                reason,
                cutoff,
            )
            .expect("revoke current registry");
    }
}

#[tokio::test]
async fn registry_revocation_during_tokenization_refuses_the_real_owner_send_gate() {
    let fixture = Fixture::new();
    let task =
        tokio::spawn(Arc::clone(&fixture.owner).observe_final_request(fixture.request.clone()));
    fixture.wait_for_tokenizer().await;
    fixture.revoke();
    std::fs::write(&fixture.release, b"release").expect("release barrier");
    assert_eq!(
        task.await.expect("join"),
        Err(ExactContextDeliveryError::AdmissionChanged)
    );
    assert!(
        fixture
            .owner
            .state
            .lock()
            .expect("state")
            .durable
            .pre_sends
            .is_empty()
    );
}

#[tokio::test]
async fn expiry_during_tokenization_refuses_the_real_owner_send_gate() {
    let mut fixture = Fixture::new();
    let old = &fixture.request.attachment;
    fixture.request.attachment = PromptRuntimeAttachmentV1::new(
        old.compilation_id.clone(),
        old.context_attachment_digest,
        old.context_payload_digest,
        old.model.clone(),
        current_unix_ms().expect("clock") + 500,
        old.developer_fragments.clone(),
    )
    .expect("short-lived attachment");
    let task =
        tokio::spawn(Arc::clone(&fixture.owner).observe_final_request(fixture.request.clone()));
    fixture.wait_for_tokenizer().await;
    tokio::time::sleep(Duration::from_millis(550)).await;
    std::fs::write(&fixture.release, b"release").expect("release barrier");
    assert_eq!(
        task.await.expect("join"),
        Err(ExactContextDeliveryError::Expired)
    );
    assert!(
        fixture
            .owner
            .state
            .lock()
            .expect("state")
            .durable
            .pre_sends
            .is_empty()
    );
}

#[tokio::test]
async fn concurrent_preparation_cannot_reserve_two_attempts_for_one_turn() {
    let fixture = Fixture::new();
    let task =
        tokio::spawn(Arc::clone(&fixture.owner).observe_final_request(fixture.request.clone()));
    fixture.wait_for_tokenizer().await;
    let result = Arc::clone(&fixture.owner)
        .observe_final_request(fixture.request.clone())
        .await;
    assert_eq!(result, Err(ExactContextDeliveryError::RecoveryRequired));
    task.abort();
    let _ = task.await;
    assert!(
        fixture
            .owner
            .state
            .lock()
            .expect("state")
            .preparing
            .is_empty()
    );
    assert!(
        fixture
            .owner
            .state
            .lock()
            .expect("state")
            .durable
            .pre_sends
            .is_empty()
    );
}

async fn wait_for_path(path: &Path) {
    tokio::time::timeout(Duration::from_secs(3), async {
        while !path.exists() {
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
    })
    .await
    .expect("fixture barrier");
}

fn terminal_for(
    request: &PromptRuntimeFinalRequestV2,
    terminal: PromptRuntimeProviderTerminalV2,
    observed_unix_ms: u64,
) -> PromptRuntimeFinalTerminalV2 {
    PromptRuntimeFinalTerminalV2 {
        attachment: request.attachment.clone(),
        attempt: request.attempt.clone(),
        terminal,
        observed_unix_ms,
    }
}

#[tokio::test]
async fn crash_reopen_reconciles_indeterminate_then_final_without_redispatch() {
    let Fixture {
        directory,
        registry_path,
        runtime_path,
        owner,
        request,
        entered,
        release,
        ..
    } = Fixture::new();
    let send = tokio::spawn(Arc::clone(&owner).observe_final_request(request.clone()));
    wait_for_path(&entered).await;
    std::fs::write(&release, b"release").expect("release tokenizer");
    assert_eq!(send.await.expect("join"), Ok(()));
    assert!(
        owner
            .state
            .lock()
            .expect("state")
            .durable
            .has_unresolved_attempt(&request.attempt.attempt_id)
    );
    drop(owner);

    let registry =
        DurablePromptRegistry::open_state_dir(&registry_path, 64).expect("reopen registry");
    let reopened = Arc::new(
        AgentdExactContextDeliveryOwner::open(&runtime_path, Arc::new(Mutex::new(registry)))
            .expect("reopen exact owner"),
    );
    let first_observed = current_unix_ms().expect("clock");
    reopened
        .observe_final_terminal(terminal_for(
            &request,
            PromptRuntimeProviderTerminalV2::Indeterminate {
                reason_code: "provider_pending".to_owned(),
                partial_response_digest: None,
            },
            first_observed,
        ))
        .await
        .expect("record recovered indeterminate");
    assert!(
        reopened
            .state
            .lock()
            .expect("state")
            .durable
            .has_unresolved_attempt(&request.attempt.attempt_id)
    );

    let final_observed = first_observed.saturating_add(1);
    let final_terminal = terminal_for(
        &request,
        PromptRuntimeProviderTerminalV2::CompletedUnary {
            response_items_digest: digest("recovered-response-items"),
        },
        final_observed,
    );
    reopened
        .observe_final_terminal(final_terminal.clone())
        .await
        .expect("reconcile recovered final");
    assert!(
        !reopened
            .state
            .lock()
            .expect("state")
            .durable
            .has_unresolved_attempt(&request.attempt.attempt_id)
    );
    reopened
        .observe_final_terminal(final_terminal)
        .await
        .expect("identical final is idempotent");

    let conflict = reopened
        .observe_final_terminal(terminal_for(
            &request,
            PromptRuntimeProviderTerminalV2::Rejected {
                reason_code: "different_terminal".to_owned(),
            },
            final_observed.saturating_add(1),
        ))
        .await;
    assert!(matches!(
        conflict,
        Err(ExactContextDeliveryError::Conflict(_))
    ));
    drop(reopened);
    drop(directory);
}

#[tokio::test]
async fn legacy_digest_only_pre_send_remains_non_recoverable() {
    let directory = tempfile::tempdir().expect("tempdir");
    let (store, mut state) = ExactDeliveryStore::open(directory.path()).expect("open");
    state.pre_sends.insert(
        "legacy-attempt".to_owned(),
        StoredPreSend {
            thread_id: "legacy-thread".to_owned(),
            turn_id: "legacy-turn".to_owned(),
            attempt_id: "legacy-attempt".to_owned(),
            provider_intent_digest: [1; 32],
            authority_snapshot_digest: [2; 32],
            preparation_binding_digest: [3; 32],
            preparation_digest: [4; 32],
            final_request_proof_digest: [5; 32],
            provider_request_digest: [6; 32],
            provider_wire_semantic_digest: [7; 32],
            tokenizer_identity_digest: [8; 32],
            tokenization_receipt_digest: [9; 32],
            token_count: 11,
            segment_map_digest: [10; 32],
            recorded_unix_ms: 12,
            recovery_binding_digest: [0; 32],
            recovery_archive: None,
        },
    );
    store.persist(&state).expect("persist legacy record");
    drop(store);
    let (_store, reopened) = ExactDeliveryStore::open(directory.path()).expect("reopen");
    let legacy = reopened
        .pre_sends
        .get("legacy-attempt")
        .expect("legacy record");
    assert!(legacy.recovery_archive.is_none());
    assert_eq!(legacy.recovery_binding_digest, [0; 32]);
    assert!(reopened.has_unresolved_attempt("legacy-attempt"));
}
