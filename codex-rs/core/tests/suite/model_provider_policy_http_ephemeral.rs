use anyhow::Result;
use codex_core::config::Config;
use codex_extension_api::EphemeralModelInputContext;
use codex_extension_api::EphemeralModelInputContributor;
use codex_extension_api::EphemeralModelInputProposal;
use codex_extension_api::EphemeralModelInputSource;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::ModelProviderPolicyFuture;
use codex_extension_api::ModelProviderSha256Digest;
use codex_extension_api::ModelProviderTransport;
use core_test_support::responses::ev_completed;
use core_test_support::responses::ev_response_created;
use core_test_support::responses::mount_response_once;
use core_test_support::responses::mount_response_sequence;
use core_test_support::responses::mount_sse_once;
use core_test_support::responses::sse;
use core_test_support::responses::start_mock_server;
use core_test_support::test_codex::test_codex;
use sha2::Digest as _;
use sha2::Sha256;
use std::future::Future;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use wiremock::ResponseTemplate;
use wiremock::http::Method;

use super::model_provider_policy::ProviderPolicyState;
use super::model_provider_policy::TestDecision;
use super::model_provider_policy::test_provider_policy;

pub(super) const MARKER_PREFIX: &str = "ephemeral-http-secret";
const HTTP_POLICY_TEST_STACK_SIZE_BYTES: usize = 16 * 1024 * 1024;

pub(super) fn run_http_policy_test(test: impl Future<Output = Result<()>>) -> Result<()> {
    tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .thread_stack_size(HTTP_POLICY_TEST_STACK_SIZE_BYTES)
        .enable_all()
        .build()?
        .block_on(test)
}

#[derive(Clone, Debug)]
pub(super) struct InputObservation {
    pub(super) attempt_id: String,
    pub(super) base_logical_request_sha256: String,
    pub(super) marker: String,
    pub(super) model_context_window: Option<i64>,
}

pub(super) struct TestEphemeralInput {
    calls: AtomicUsize,
    observations: Mutex<Vec<InputObservation>>,
    policy: Arc<ProviderPolicyState>,
    deactivate_policy: bool,
}

impl TestEphemeralInput {
    pub(super) fn new(policy: Arc<ProviderPolicyState>, deactivate_policy: bool) -> Arc<Self> {
        Arc::new(Self {
            calls: AtomicUsize::new(0),
            observations: Mutex::new(Vec::new()),
            policy,
            deactivate_policy,
        })
    }

    pub(super) fn calls(&self) -> usize {
        self.calls.load(Ordering::SeqCst)
    }

    pub(super) fn observations(&self) -> Vec<InputObservation> {
        self.observations
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone()
    }
}

impl EphemeralModelInputContributor for TestEphemeralInput {
    fn contribute<'a>(
        &'a self,
        input: EphemeralModelInputContext<'a>,
    ) -> ModelProviderPolicyFuture<'a, Option<EphemeralModelInputProposal>> {
        let call = self.calls.fetch_add(1, Ordering::SeqCst) + 1;
        let marker = format!("{MARKER_PREFIX}-{call}");
        self.observations
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .push(InputObservation {
                attempt_id: input.attempt_id.to_string(),
                base_logical_request_sha256: input.base_logical_request_sha256.as_str().to_string(),
                marker: marker.clone(),
                model_context_window: input.model_context_window,
            });
        if self.deactivate_policy {
            self.policy.set_active(false);
        }
        let proposal = (|| {
            Ok(Some(EphemeralModelInputProposal::new(
                EphemeralModelInputSource::parse("hepta_memory_same_thread_v1")?,
                input.attempt_id,
                input.base_logical_request_sha256.clone(),
                input.thread_id,
                input.turn_id,
                digest(b"test-source-binding"),
                digest(marker.as_bytes()),
                marker,
                3,
            )?))
        })();
        Box::pin(std::future::ready(proposal))
    }
}

pub(super) fn extensions(
    policy: Arc<ProviderPolicyState>,
    inputs: &[Arc<TestEphemeralInput>],
) -> Arc<codex_extension_api::ExtensionRegistry<Config>> {
    let mut builder = ExtensionRegistryBuilder::<Config>::new();
    builder.model_provider_policy_contributor(test_provider_policy(policy));
    for input in inputs {
        builder.ephemeral_model_input_contributor(input.clone());
    }
    Arc::new(builder.build())
}

fn digest(bytes: &[u8]) -> ModelProviderSha256Digest {
    ModelProviderSha256Digest::parse(format!("{:x}", Sha256::digest(bytes))).expect("test digest")
}

#[test]
fn attached_http_send_changes_only_the_physical_request() -> Result<()> {
    run_http_policy_test(async {
        let server = start_mock_server().await;
        let response = mount_sse_once(
            &server,
            sse(vec![ev_response_created("resp-1"), ev_completed("resp-1")]),
        )
        .await;
        let policy = ProviderPolicyState::new(true, TestDecision::Allow);
        policy.terminal_release.add_permits(4);
        let input = TestEphemeralInput::new(Arc::clone(&policy), false);
        let test = test_codex()
            .with_model_info_override("gpt-5.5", |model| {
                model.context_window = Some(10_000);
                model.effective_context_window_percent = 80;
            })
            .with_extensions(extensions(Arc::clone(&policy), &[Arc::clone(&input)]))
            .build(&server)
            .await?;

        test.submit_turn("base conversation must remain durable")
            .await?;
        let request = response.single_request();
        let body = request.body_json();
        let wire = serde_json::to_string(&body)?;
        assert_eq!(wire.matches(MARKER_PREFIX).count(), 1);
        assert_eq!(wire.matches("<hepta_memory_reference").count(), 1);
        assert!(body.get("prompt_cache_key").is_none());
        assert_eq!(body["store"], false);
        assert_eq!(input.observations()[0].model_context_window, Some(8_000));
        assert!(
            policy
                .bindings
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)[0]
                .has_ephemeral_input
        );

        test.codex.flush_rollout().await?;
        let rollout = std::fs::read_to_string(test.codex.rollout_path().expect("rollout path"))?;
        assert!(!rollout.contains(MARKER_PREFIX));
        assert!(!rollout.contains("hepta_memory_reference"));
        Ok(())
    })
}

#[test]
fn active_ephemeral_input_forces_sensitive_http_when_websockets_are_enabled() -> Result<()> {
    run_http_policy_test(async {
        let server = start_mock_server().await;
        let response = mount_sse_once(
            &server,
            sse(vec![ev_response_created("resp-1"), ev_completed("resp-1")]),
        )
        .await;
        let policy = ProviderPolicyState::new(true, TestDecision::Allow);
        policy.terminal_release.add_permits(4);
        let input = TestEphemeralInput::new(Arc::clone(&policy), false);
        let test = test_codex()
            .with_config(|config| {
                config.model_provider.supports_websockets = true;
                config.model_provider.request_max_retries = Some(0);
                config.model_provider.stream_max_retries = Some(0);
            })
            .with_extensions(extensions(Arc::clone(&policy), &[Arc::clone(&input)]))
            .build(&server)
            .await?;

        test.submit_turn("ephemeral input must use the resolved HTTP path")
            .await?;

        let request = response.single_request();
        assert!(request.body_json().to_string().contains(MARKER_PREFIX));
        assert_eq!(input.calls(), 1);
        let attempts = policy
            .attempts
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone();
        assert_eq!(
            attempts
                .iter()
                .filter(|attempt| attempt.transport == ModelProviderTransport::WebSocket)
                .count(),
            0,
            "active ephemeral input must not dispatch a WebSocket provider attempt"
        );
        assert_eq!(
            attempts
                .iter()
                .filter(|attempt| attempt.transport == ModelProviderTransport::Http)
                .count(),
            1
        );
        let physical_requests = server.received_requests().await.unwrap_or_default();
        assert_eq!(
            physical_requests
                .iter()
                .filter(|request| {
                    request.method == Method::POST && request.url.path().ends_with("/responses")
                })
                .count(),
            1
        );
        Ok(())
    })
}

#[test]
fn ephemeral_http_does_not_follow_redirects() -> Result<()> {
    run_http_policy_test(async {
        let origin = start_mock_server().await;
        let redirected = start_mock_server().await;
        let redirected_response = mount_sse_once(
            &redirected,
            sse(vec![ev_response_created("resp-1"), ev_completed("resp-1")]),
        )
        .await;
        let origin_response = mount_response_once(
            &origin,
            ResponseTemplate::new(307)
                .insert_header("location", format!("{}/v1/responses", redirected.uri())),
        )
        .await;
        let policy = ProviderPolicyState::new(true, TestDecision::Allow);
        policy.terminal_release.add_permits(4);
        let input = TestEphemeralInput::new(Arc::clone(&policy), false);
        let test = test_codex()
            .with_config(|config| {
                config.model_provider.request_max_retries = Some(0);
                config.model_provider.stream_max_retries = Some(0);
            })
            .with_extensions(extensions(Arc::clone(&policy), &[Arc::clone(&input)]))
            .build(&origin)
            .await?;

        test.submit_turn("redirect must not replay ephemeral input")
            .await?;
        assert_eq!(origin_response.requests().len(), 1);
        assert!(
            origin_response.requests()[0]
                .body_json()
                .to_string()
                .contains(MARKER_PREFIX)
        );
        assert!(redirected_response.requests().is_empty());
        assert_eq!(input.calls(), 1);
        Ok(())
    })
}

#[test]
fn frozen_policy_and_single_claimant_rules_fail_closed_before_send() -> Result<()> {
    run_http_policy_test(async {
        for (deactivate_policy, claimant_count, expected_begin) in
            [(true, 1usize, 1usize), (false, 2usize, 0usize)]
        {
            let server = start_mock_server().await;
            let policy = ProviderPolicyState::new(true, TestDecision::Block);
            let inputs = (0..claimant_count)
                .map(|_| TestEphemeralInput::new(Arc::clone(&policy), deactivate_policy))
                .collect::<Vec<_>>();
            let test = test_codex()
                .with_extensions(extensions(Arc::clone(&policy), &inputs))
                .build(&server)
                .await?;

            test.submit_turn("fail before provider dispatch").await?;
            assert_eq!(
                inputs.iter().map(|input| input.calls()).sum::<usize>(),
                claimant_count
            );
            assert_eq!(policy.begin_count.load(Ordering::SeqCst), expected_begin);
            assert!(
                server
                    .received_requests()
                    .await
                    .unwrap_or_default()
                    .is_empty()
            );
        }
        Ok(())
    })
}

#[test]
fn inactive_policy_preserves_provider_retry_without_proposals() -> Result<()> {
    run_http_policy_test(async {
        let server = start_mock_server().await;
        let response = mount_response_sequence(
            &server,
            vec![
                ResponseTemplate::new(500).set_body_string("retry without ephemeral input"),
                ResponseTemplate::new(200)
                    .insert_header("content-type", "text/event-stream")
                    .set_body_string(sse(vec![
                        ev_response_created("resp-1"),
                        ev_completed("resp-1"),
                    ])),
            ],
        )
        .await;
        let policy = ProviderPolicyState::new(false, TestDecision::Block);
        let input = TestEphemeralInput::new(Arc::clone(&policy), false);
        let test = test_codex()
            .with_config(|config| config.model_provider.stream_max_retries = Some(1))
            .with_extensions(extensions(Arc::clone(&policy), &[Arc::clone(&input)]))
            .build(&server)
            .await?;

        test.submit_turn("ordinary provider retry parity").await?;
        let requests = response.requests();
        assert_eq!(requests.len(), 2);
        assert_eq!(requests[0].input(), requests[1].input());
        assert_eq!(input.calls(), 0);
        assert_eq!(policy.begin_count.load(Ordering::SeqCst), 0);
        assert_eq!(policy.terminal_count.load(Ordering::SeqCst), 0);
        assert!(
            !requests
                .iter()
                .any(|request| request.body_json().to_string().contains(MARKER_PREFIX))
        );
        Ok(())
    })
}
