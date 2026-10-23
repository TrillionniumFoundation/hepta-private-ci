//! Real Core HTTP composition with a policy fixture; no HF/model qualification.
use super::model_provider_policy::ProviderPolicyState;
use super::model_provider_policy::TestDecision;
use super::model_provider_policy::test_provider_policy;
use anyhow::Result;
use codex_core::config::Config;
use codex_extension_api::ExtensionData;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::ModelProviderAttemptLease;
use codex_extension_api::ModelProviderInvocationInput;
use codex_extension_api::ModelProviderPolicyContributor;
use codex_extension_api::ModelProviderPolicyDecision;
use codex_extension_api::ModelProviderPolicyError;
use codex_extension_api::ModelProviderPolicyFuture;
use codex_extension_api::ModelProviderSha256Digest;
use codex_extension_api::ModelProviderTerminal;
use core_test_support::responses::ev_completed;
use core_test_support::responses::ev_response_created;
use core_test_support::responses::mount_sse_once;
use core_test_support::responses::sse;
use core_test_support::responses::start_mock_server;
use core_test_support::test_codex::test_codex;
use pretty_assertions::assert_eq;
use sha2::Digest;
use sha2::Sha256;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::Ordering;

#[derive(Clone, Copy)]
enum Admission {
    Allow,
    Refuse,
}
type Binding = Arc<Mutex<Option<(String, ModelProviderSha256Digest, u64)>>>;
struct Policy {
    inner: Arc<dyn ModelProviderPolicyContributor>,
    seen: Binding,
    admission: Admission,
}
struct Lease {
    inner: Box<dyn ModelProviderAttemptLease>,
    seen: Binding,
    admission: Admission,
    attempt: String,
}

impl ModelProviderPolicyContributor for Policy {
    fn is_active(&self, _store: &ExtensionData) -> bool {
        true
    }
    fn begin<'a>(
        &'a self,
        input: ModelProviderInvocationInput<'a>,
    ) -> ModelProviderPolicyFuture<'a, ModelProviderPolicyDecision> {
        let attempt = input.attempt_id.to_string();
        Box::pin(async move {
            Ok(match self.inner.begin(input).await? {
                ModelProviderPolicyDecision::Allow { lease } => {
                    ModelProviderPolicyDecision::Allow {
                        lease: Box::new(Lease {
                            inner: lease,
                            seen: self.seen.clone(),
                            admission: self.admission,
                            attempt,
                        }),
                    }
                }
                decision => decision,
            })
        })
    }
}

impl ModelProviderAttemptLease for Lease {
    fn encoded_body_required(&self) -> bool {
        true
    }
    fn bind_encoded_body_v1<'a>(
        &'a mut self,
        digest: ModelProviderSha256Digest,
        bytes: u64,
    ) -> ModelProviderPolicyFuture<'a, ()> {
        *self.seen.lock().expect("binding") = Some((self.attempt.clone(), digest, bytes));
        Box::pin(async move {
            match self.admission {
                Admission::Allow => Ok(()),
                Admission::Refuse => Err(ModelProviderPolicyError::new(
                    "fixture_late_refusal",
                    "controlled refusal",
                )),
            }
        })
    }
    fn finish(
        self: Box<Self>,
        terminal: ModelProviderTerminal,
    ) -> ModelProviderPolicyFuture<'static, ()> {
        self.inner.finish(terminal)
    }
}

async fn exercise(admission: Admission) -> Result<()> {
    let server = start_mock_server().await;
    let response = mount_sse_once(
        &server,
        sse(vec![
            ev_response_created("encoded-1"),
            ev_completed("encoded-1"),
        ]),
    )
    .await;
    let state = ProviderPolicyState::new(/*active*/ true, TestDecision::Allow);
    state.terminal_release.add_permits(1);
    let seen = Binding::default();
    let mut extensions = ExtensionRegistryBuilder::<Config>::new();
    extensions.model_provider_policy_contributor(Arc::new(Policy {
        inner: test_provider_policy(state.clone()),
        seen: seen.clone(),
        admission,
    }));
    let test = test_codex()
        .with_extensions(Arc::new(extensions.build()))
        .with_config(|config| {
            config
                .features
                .disable(codex_features::Feature::EnableRequestCompression)
                .expect("test profile must disable request compression");
        })
        .build_with_auto_env(&server)
        .await?;
    test.submit_turn("keep all compiled instructions and request fields")
        .await?;
    assert_eq!(state.begin_count.load(Ordering::SeqCst), 1);
    assert_eq!(state.terminal_count.load(Ordering::SeqCst), 1);
    let observed = seen.lock().expect("binding").clone();
    match admission {
        Admission::Allow => {
            let body = response.single_request().body_bytes();
            let digest = ModelProviderSha256Digest::parse(format!("{:x}", Sha256::digest(&body)))
                .expect("digest");
            let attempt = state.bindings.lock().expect("original attempt")[0]
                .attempt_id
                .clone();
            assert_eq!(
                observed,
                Some((attempt, digest, u64::try_from(body.len())?))
            );
            assert_eq!(state.completed_count.load(Ordering::SeqCst), 1);
        }
        Admission::Refuse => {
            assert!(observed.is_some());
            assert!(response.requests().is_empty());
            assert!(matches!(
                state.terminals.lock().expect("terminal").as_slice(),
                [ModelProviderTerminal::NotDispatched { .. }]
            ));
        }
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn exact_body_binding_matches_complete_real_http_request_and_original_attempt() -> Result<()>
{
    exercise(Admission::Allow).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn exact_body_late_refusal_prevents_http_and_settles_original_attempt() -> Result<()> {
    exercise(Admission::Refuse).await
}
