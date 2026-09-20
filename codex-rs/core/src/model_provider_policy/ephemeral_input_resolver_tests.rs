use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_extension_api::EPHEMERAL_MODEL_INPUT_MAX_CONTENT_BYTES;
use codex_extension_api::EPHEMERAL_MODEL_INPUT_MAX_CONTENT_TOKENS;
use codex_extension_api::EphemeralModelInputContext;
use codex_extension_api::EphemeralModelInputContributor;
use codex_extension_api::EphemeralModelInputProposal;
use codex_extension_api::EphemeralModelInputSource;
use codex_extension_api::ExtensionData;
use codex_extension_api::ExtensionRegistry;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::ModelProviderPolicyContributor;
use codex_extension_api::ModelProviderPolicyError;
use codex_extension_api::ModelProviderPolicyFuture;
use codex_extension_api::ModelProviderRequestKind;
use codex_extension_api::ModelProviderTransport;

use super::super::binding::prepare_model_provider_attempt;
use super::super::lifecycle::active_model_provider_policies;
use super::ModelProviderAttemptEnvelope;
use super::ModelProviderPolicyContext;
use super::PreparedEphemeralModelInput;
use super::bytes_sha256;
use super::resolve_ephemeral_model_input as resolve_ephemeral_model_input_with_policies;
use crate::config::Config;

struct ActivePolicy;

impl ModelProviderPolicyContributor for ActivePolicy {}

struct ProposalContributor {
    calls: Arc<AtomicUsize>,
    content: Option<&'static str>,
    enabled: Option<Arc<AtomicBool>>,
    disable_on_contribute: Option<Arc<AtomicBool>>,
}

impl EphemeralModelInputContributor for ProposalContributor {
    fn is_active(&self, _thread_store: &ExtensionData, _turn_store: &ExtensionData) -> bool {
        self.enabled
            .as_ref()
            .is_none_or(|enabled| enabled.load(Ordering::SeqCst))
    }

    fn contribute<'a>(
        &'a self,
        input: EphemeralModelInputContext<'a>,
    ) -> ModelProviderPolicyFuture<'a, Option<EphemeralModelInputProposal>> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        if let Some(enabled) = &self.disable_on_contribute {
            enabled.store(false, Ordering::SeqCst);
        }
        assert_eq!(input.thread_id, "thread-1");
        assert_eq!(input.turn_id, "turn-1");
        assert_eq!(input.cwd, Path::new("/workspace"));
        assert_eq!(input.request_kind, ModelProviderRequestKind::Turn);
        assert_eq!(input.provider_id, "provider-1");
        assert_eq!(input.model, "model-1");
        assert_eq!(input.transport, ModelProviderTransport::Http);
        assert!(input.generate);
        assert_eq!(input.model_context_window, Some(128_000));
        assert_eq!(
            input.max_content_bytes,
            EPHEMERAL_MODEL_INPUT_MAX_CONTENT_BYTES
        );
        assert_eq!(
            input.max_content_tokens,
            EPHEMERAL_MODEL_INPUT_MAX_CONTENT_TOKENS
        );
        let result = (|| {
            let Some(content) = self.content else {
                return Ok(None);
            };
            Ok(Some(EphemeralModelInputProposal::new(
                EphemeralModelInputSource::parse("hepta_memory_same_thread_v1")?,
                input.attempt_id,
                input.base_logical_request_sha256.clone(),
                input.thread_id,
                input.turn_id,
                bytes_sha256(b"source-binding")?,
                bytes_sha256(content.as_bytes())?,
                content,
                3,
            )?))
        })();
        Box::pin(std::future::ready(result))
    }
}

fn stores() -> (ExtensionData, ExtensionData, ExtensionData) {
    (
        ExtensionData::new("session"),
        ExtensionData::new("thread-1"),
        ExtensionData::new("turn-1"),
    )
}

fn registry(
    contributors: &[Arc<ProposalContributor>],
    active_policy: bool,
) -> ExtensionRegistry<Config> {
    let mut builder = ExtensionRegistryBuilder::<Config>::new();
    for contributor in contributors {
        builder.ephemeral_model_input_contributor(contributor.clone());
    }
    if active_policy {
        builder.model_provider_policy_contributor(Arc::new(ActivePolicy));
    }
    builder.build()
}

fn context<'a>(
    registry: &'a ExtensionRegistry<Config>,
    stores: (&'a ExtensionData, &'a ExtensionData, &'a ExtensionData),
    request_kind: ModelProviderRequestKind,
    cwd: Option<PathBuf>,
) -> ModelProviderPolicyContext<'a> {
    ModelProviderPolicyContext {
        registry,
        session_store: stores.0,
        thread_store: stores.1,
        turn_store: stores.2,
        thread_id: "thread-1".to_string(),
        turn_id: "turn-1".to_string(),
        request_kind,
        ephemeral_input_cwd: cwd,
    }
}

fn attempt(
    context: &ModelProviderPolicyContext<'_>,
    generate: bool,
) -> ModelProviderAttemptEnvelope {
    prepare_model_provider_attempt(
        context,
        "provider-1",
        "model-1",
        ModelProviderTransport::Http,
        "https://example.test/v1/responses",
        &serde_json::json!({ "input": ["base"], "model": "model-1" }),
        None,
        generate,
    )
    .expect("attempt envelope")
}

async fn resolve_ephemeral_model_input(
    context: &ModelProviderPolicyContext<'_>,
    attempt: &ModelProviderAttemptEnvelope,
    model_context_window: Option<i64>,
) -> Result<Option<PreparedEphemeralModelInput>, ModelProviderPolicyError> {
    let active = active_model_provider_policies(context.registry, context.thread_store);
    resolve_ephemeral_model_input_with_policies(context, attempt, &active, model_context_window)
        .await
}

#[tokio::test]
async fn active_local_turn_resolves_one_fresh_attempt_input() {
    let calls = Arc::new(AtomicUsize::new(0));
    let contributor = Arc::new(ProposalContributor {
        calls: Arc::clone(&calls),
        content: Some("attempt-local-marker"),
        enabled: None,
        disable_on_contribute: None,
    });
    let registry = registry(&[contributor], true);
    let stores = stores();
    let context = context(
        &registry,
        (&stores.0, &stores.1, &stores.2),
        ModelProviderRequestKind::Turn,
        Some(PathBuf::from("/workspace")),
    );
    let attempt = attempt(&context, true);

    let prepared = resolve_ephemeral_model_input(&context, &attempt, Some(128_000))
        .await
        .expect("resolved input")
        .expect("one proposal");
    let (_item, binding) = prepared.into_parts();

    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(binding.input_sha256().as_str().len(), 64);
    assert_eq!(binding.authority_sha256().as_str().len(), 64);
}

#[tokio::test]
async fn inactive_and_excluded_scopes_never_invoke_proposers() {
    let calls = Arc::new(AtomicUsize::new(0));
    let contributor = Arc::new(ProposalContributor {
        calls: Arc::clone(&calls),
        content: Some("must-not-run"),
        enabled: None,
        disable_on_contribute: None,
    });
    let stores = stores();
    let inactive_registry = registry(&[Arc::clone(&contributor)], false);
    let inactive = context(
        &inactive_registry,
        (&stores.0, &stores.1, &stores.2),
        ModelProviderRequestKind::Turn,
        Some(PathBuf::from("/workspace")),
    );
    assert!(
        resolve_ephemeral_model_input(&inactive, &attempt(&inactive, true), Some(128_000))
            .await
            .expect("inactive resolution")
            .is_none()
    );

    let active_registry = registry(&[contributor], true);
    let mut excluded = context(
        &active_registry,
        (&stores.0, &stores.1, &stores.2),
        ModelProviderRequestKind::Prewarm,
        Some(PathBuf::from("/workspace")),
    );
    assert!(
        resolve_ephemeral_model_input(&excluded, &attempt(&excluded, true), Some(128_000))
            .await
            .expect("prewarm resolution")
            .is_none()
    );
    excluded.request_kind = ModelProviderRequestKind::Turn;
    assert!(
        resolve_ephemeral_model_input(&excluded, &attempt(&excluded, false), Some(128_000))
            .await
            .expect("non-generating resolution")
            .is_none()
    );
    excluded.ephemeral_input_cwd = None;
    assert!(
        resolve_ephemeral_model_input(&excluded, &attempt(&excluded, true), Some(128_000))
            .await
            .expect("non-local resolution")
            .is_none()
    );
    assert_eq!(calls.load(Ordering::SeqCst), 0);
}

#[tokio::test]
async fn inactive_contributors_and_zero_claimants_return_none() {
    let disabled_calls = Arc::new(AtomicUsize::new(0));
    let empty_calls = Arc::new(AtomicUsize::new(0));
    let registry = registry(
        &[
            Arc::new(ProposalContributor {
                calls: Arc::clone(&disabled_calls),
                content: Some("disabled"),
                enabled: Some(Arc::new(AtomicBool::new(false))),
                disable_on_contribute: None,
            }),
            Arc::new(ProposalContributor {
                calls: Arc::clone(&empty_calls),
                content: None,
                enabled: None,
                disable_on_contribute: None,
            }),
        ],
        true,
    );
    let stores = stores();
    let context = context(
        &registry,
        (&stores.0, &stores.1, &stores.2),
        ModelProviderRequestKind::Turn,
        Some(PathBuf::from("/workspace")),
    );

    assert!(
        resolve_ephemeral_model_input(&context, &attempt(&context, true), Some(128_000))
            .await
            .expect("zero-claim resolution")
            .is_none()
    );
    assert_eq!(disabled_calls.load(Ordering::SeqCst), 0);
    assert_eq!(empty_calls.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn context_drift_fails_before_invoking_contributors() {
    let calls = Arc::new(AtomicUsize::new(0));
    let contributor = Arc::new(ProposalContributor {
        calls: Arc::clone(&calls),
        content: Some("must-not-run"),
        enabled: None,
        disable_on_contribute: None,
    });
    let registry = registry(&[contributor], true);
    let stores = stores();
    let mut context = context(
        &registry,
        (&stores.0, &stores.1, &stores.2),
        ModelProviderRequestKind::Turn,
        Some(PathBuf::from("/workspace")),
    );
    let attempt = attempt(&context, true);
    context.turn_id = "drifted-turn".to_string();

    let error = match resolve_ephemeral_model_input(&context, &attempt, Some(128_000)).await {
        Ok(_) => panic!("drifted context unexpectedly resolved"),
        Err(error) => error,
    };
    assert_eq!(error.reason_code(), "ephemeral_model_input_scope_invalid");
    assert_eq!(calls.load(Ordering::SeqCst), 0);
}

#[tokio::test]
async fn multiple_claimants_fail_before_request_finalization() {
    let first_calls = Arc::new(AtomicUsize::new(0));
    let second_calls = Arc::new(AtomicUsize::new(0));
    let second_enabled = Arc::new(AtomicBool::new(true));
    let registry = registry(
        &[
            Arc::new(ProposalContributor {
                calls: Arc::clone(&first_calls),
                content: Some("first"),
                enabled: None,
                disable_on_contribute: Some(Arc::clone(&second_enabled)),
            }),
            Arc::new(ProposalContributor {
                calls: Arc::clone(&second_calls),
                content: Some("second"),
                enabled: Some(second_enabled),
                disable_on_contribute: None,
            }),
        ],
        true,
    );
    let stores = stores();
    let context = context(
        &registry,
        (&stores.0, &stores.1, &stores.2),
        ModelProviderRequestKind::Turn,
        Some(PathBuf::from("/workspace")),
    );
    let result =
        resolve_ephemeral_model_input(&context, &attempt(&context, true), Some(128_000)).await;
    let error = match result {
        Ok(_) => panic!("multiple claimants unexpectedly succeeded"),
        Err(error) => error,
    };

    assert_eq!(
        error.reason_code(),
        "ephemeral_model_input_multiple_claimants"
    );
    assert_eq!(first_calls.load(Ordering::SeqCst), 1);
    assert_eq!(second_calls.load(Ordering::SeqCst), 1);
}
