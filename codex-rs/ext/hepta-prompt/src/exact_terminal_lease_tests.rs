//! Exercise the real context contributor, policy lease and exact-body observer.
use super::*;

use std::sync::Mutex as StdMutex;
use std::task::Context;
use std::task::Poll;
use std::task::Waker;

use codex_api::EncodedRequestTerminal;
use codex_extension_api::ModelProviderSha256Digest;
use codex_protocol::ThreadId;

const BODY: &[u8] = br#"{"model":"model","input":[{"role":"developer","content":[{"type":"input_text","text":"approved-context"}]}]}"#;

#[derive(Clone, Copy)]
enum Persistence {
    Accept,
    RejectExact,
    RejectProjection,
    PendingExact,
    PendingProjection,
}

struct Harness {
    extension: PromptRuntimeExtension,
    session: ExtensionData,
    thread: ExtensionData,
    turn: ExtensionData,
    events: Arc<StdMutex<Vec<&'static str>>>,
}

fn digest(value: &str) -> ModelProviderSha256Digest {
    ModelProviderSha256Digest::parse(Digest32::of_bytes(value.as_bytes()).to_string())
        .expect("digest")
}

fn completed() -> ModelProviderTerminal {
    ModelProviderTerminal::Completed {
        response_id_sha256: digest("response"),
        response_items_sha256: digest("items"),
        token_usage_sha256: digest("usage"),
        end_turn: Some(true),
    }
}

impl Harness {
    async fn new(persistence: Persistence) -> Self {
        let fragment = PromptRuntimeDeveloperFragmentV1::new("approved-context").expect("fragment");
        let attachment = PromptRuntimeAttachmentV1::new(
            StableId::new("compilation").expect("id"),
            Digest32::of_bytes(b"attachment"),
            fragment.content_digest,
            "model",
            current_unix_ms().expect("clock") + 60_000,
            vec![fragment],
        )
        .expect("attachment");
        let events = Arc::new(StdMutex::new(Vec::new()));
        let exact_events = Arc::clone(&events);
        let projection_events = Arc::clone(&events);
        let host = PromptRuntimeHost::new(
            "lease-integration",
            move |_| {
                let attachment = attachment.clone();
                Box::pin(async move { Ok(Some(attachment)) })
            },
            |_| Box::pin(async { Ok(()) }),
            move |_| {
                let events = Arc::clone(&projection_events);
                Box::pin(async move {
                    events.lock().expect("events").push("projection");
                    match persistence {
                        Persistence::RejectProjection => Err(PromptRuntimeHostError::new(
                            "projection_rejected",
                            "test rejection",
                        )),
                        Persistence::PendingProjection => std::future::pending().await,
                        Persistence::Accept
                        | Persistence::RejectExact
                        | Persistence::PendingExact => Ok(()),
                    }
                })
            },
        )
        .expect("host")
        .with_final_request_observer(|_| Box::pin(async { Ok(()) }))
        .with_final_terminal_observer(move |_| {
            let events = Arc::clone(&exact_events);
            Box::pin(async move {
                events.lock().expect("events").push("exact");
                match persistence {
                    Persistence::RejectExact => Err(PromptRuntimeHostError::new(
                        "exact_rejected",
                        "test rejection",
                    )),
                    Persistence::PendingExact => std::future::pending().await,
                    Persistence::Accept
                    | Persistence::RejectProjection
                    | Persistence::PendingProjection => Ok(()),
                }
            })
        });
        let harness = Self {
            extension: PromptRuntimeExtension { host },
            session: ExtensionData::new("session"),
            thread: ExtensionData::new("00000000-0000-4000-8000-000000000001"),
            turn: ExtensionData::new("turn"),
            events,
        };
        let fragments = harness
            .extension
            .contribute_turn_context(TurnContextContributionInput {
                thread_id: ThreadId::from_string(harness.thread.level_id()).expect("thread id"),
                turn_id: harness.turn.level_id(),
                session_store: &harness.session,
                thread_store: &harness.thread,
                turn_store: &harness.turn,
                model_context_window: Some(4096),
            })
            .await;
        assert_eq!(fragments.len(), 1);
        assert_eq!(fragments[0].text(), "approved-context");
        harness
    }

    fn observer(&self) -> Arc<dyn EncodedRequestBodyObserver> {
        self.turn
            .get::<EncodedRequestBodyObserverAttachment>()
            .expect("installed observer")
            .observer()
    }

    async fn begin(
        &self,
        attempt_id: &str,
    ) -> Result<ModelProviderPolicyDecision, ModelProviderPolicyError> {
        let config = digest("config");
        let endpoint = digest("endpoint");
        let logical = digest("logical");
        let wire = digest("wire");
        self.extension
            .begin(ModelProviderInvocationInput {
                schema_version: codex_extension_api::MODEL_PROVIDER_POLICY_INPUT_SCHEMA_VERSION,
                session_store: &self.session,
                thread_store: &self.thread,
                turn_store: &self.turn,
                attempt_id,
                request_binding_id: "binding",
                thread_id: self.thread.level_id(),
                turn_id: self.turn.level_id(),
                request_kind: ModelProviderRequestKind::Turn,
                provider_id: "provider",
                provider_config_sha256: &config,
                model: "model",
                transport: ModelProviderTransport::Http,
                endpoint_sha256: &endpoint,
                logical_request_sha256: &logical,
                wire_semantic_sha256: &wire,
                ephemeral_input_sha256: None,
                ephemeral_input_witness_sha256: None,
                previous_response_id_sha256: None,
                generate: true,
            })
            .await
    }

    async fn proven_lease(&self) -> Box<dyn ModelProviderAttemptLease> {
        let ModelProviderPolicyDecision::Allow { lease } =
            self.begin("attempt-a").await.expect("begin")
        else {
            panic!("expected admitted lease");
        };
        self.observer()
            .observe_encoded_body(BODY)
            .await
            .expect("exact body");
        lease
    }
}

#[tokio::test]
async fn exact_terminal_lease_releases_only_after_both_owner_records() {
    let harness = Harness::new(Persistence::Accept).await;
    let lease = harness.proven_lease().await;
    harness
        .observer()
        .observe_terminal(EncodedRequestTerminal::Completed {
            response_id: "unbound".to_owned(),
        })
        .await
        .expect("notification");
    assert!(harness.begin("attempt-b").await.is_err());
    lease.finish(completed()).await.expect("persist terminal");
    assert_eq!(
        *harness.events.lock().expect("events"),
        vec!["exact", "projection"]
    );
    assert!(matches!(
        harness.begin("attempt-b").await,
        Ok(ModelProviderPolicyDecision::Allow { .. })
    ));
}

#[tokio::test]
async fn exact_terminal_lease_owner_failure_cannot_rearm_the_turn() {
    for persistence in [Persistence::RejectExact, Persistence::RejectProjection] {
        let harness = Harness::new(persistence).await;
        let lease = harness.proven_lease().await;
        assert!(lease.finish(completed()).await.is_err());
        assert!(harness.begin("attempt-b").await.is_err());
        let expected = match persistence {
            Persistence::RejectExact => vec!["exact"],
            Persistence::RejectProjection => vec!["exact", "projection"],
            Persistence::Accept | Persistence::PendingExact | Persistence::PendingProjection => {
                unreachable!()
            }
        };
        assert_eq!(*harness.events.lock().expect("events"), expected);
    }
}

#[tokio::test]
async fn exact_terminal_lease_cancellation_during_persistence_retains_the_claim() {
    for persistence in [Persistence::PendingExact, Persistence::PendingProjection] {
        let harness = Harness::new(persistence).await;
        let lease = harness.proven_lease().await;
        let mut finish = lease.finish(completed());
        assert!(matches!(
            finish
                .as_mut()
                .poll(&mut Context::from_waker(Waker::noop())),
            Poll::Pending
        ));
        drop(finish);
        assert!(harness.begin("attempt-b").await.is_err());
    }
}

#[tokio::test]
async fn exact_terminal_lease_indeterminate_never_becomes_a_retry_permission() {
    let harness = Harness::new(Persistence::Accept).await;
    let lease = harness.proven_lease().await;
    lease
        .finish(ModelProviderTerminal::Indeterminate {
            reason_code: "connection_lost".to_owned(),
            partial_response_sha256: None,
        })
        .await
        .expect("persist unknown");
    assert!(harness.begin("attempt-b").await.is_err());
    assert_eq!(
        *harness.events.lock().expect("events"),
        vec!["exact", "projection"]
    );
}
