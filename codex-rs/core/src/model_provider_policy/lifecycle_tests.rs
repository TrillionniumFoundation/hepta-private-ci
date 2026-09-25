use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_extension_api::ExtensionData;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::MODEL_PROVIDER_POLICY_INPUT_SCHEMA_VERSION;
use codex_extension_api::ModelProviderAttemptLease;
use codex_extension_api::ModelProviderInvocationInput;
use codex_extension_api::ModelProviderPolicyContributor;
use codex_extension_api::ModelProviderPolicyDecision;
use codex_extension_api::ModelProviderPolicyError;
use codex_extension_api::ModelProviderPolicyFuture;
use codex_extension_api::ModelProviderRequestKind;
use codex_extension_api::ModelProviderSha256Digest;
use codex_extension_api::ModelProviderTerminal;
use codex_extension_api::ModelProviderTransport;

use super::ModelProviderPolicyBegin;
use super::begin_model_provider_policy;
use super::has_active_model_provider_policy;

#[derive(Clone)]
enum Behavior {
    Allow { finish_error: bool },
    Block,
    Error,
    Pending,
}

struct RecordingContributor {
    name: &'static str,
    active: Arc<AtomicBool>,
    set_active_on_begin: Option<(Arc<AtomicBool>, bool)>,
    behavior: Behavior,
    events: Arc<Mutex<Vec<String>>>,
}

impl ModelProviderPolicyContributor for RecordingContributor {
    fn is_active(&self, _thread_store: &ExtensionData) -> bool {
        self.active.load(Ordering::SeqCst)
    }

    fn begin<'a>(
        &'a self,
        _input: ModelProviderInvocationInput<'a>,
    ) -> ModelProviderPolicyFuture<'a, ModelProviderPolicyDecision> {
        self.events
            .lock()
            .expect("events lock should not be poisoned")
            .push(format!("begin:{}", self.name));
        if let Some((active, value)) = &self.set_active_on_begin {
            active.store(*value, Ordering::SeqCst);
        }
        if matches!(self.behavior, Behavior::Pending) {
            return Box::pin(std::future::pending());
        }
        let result = match self.behavior {
            Behavior::Allow { finish_error } => Ok(ModelProviderPolicyDecision::Allow {
                lease: Box::new(RecordingLease {
                    name: self.name,
                    finish_error,
                    events: Arc::clone(&self.events),
                }),
            }),
            Behavior::Block => Ok(ModelProviderPolicyDecision::Block {
                reason_code: format!("{}_blocked", self.name),
                message: format!("{} blocked", self.name),
            }),
            Behavior::Error => Err(ModelProviderPolicyError::new(
                format!("{}_error", self.name),
                format!("{} failed", self.name),
            )),
            Behavior::Pending => unreachable!("pending behavior returned before result creation"),
        };
        Box::pin(std::future::ready(result))
    }
}

struct RecordingLease {
    name: &'static str,
    finish_error: bool,
    events: Arc<Mutex<Vec<String>>>,
}

impl ModelProviderAttemptLease for RecordingLease {
    fn finish(
        self: Box<Self>,
        terminal: ModelProviderTerminal,
    ) -> ModelProviderPolicyFuture<'static, ()> {
        self.events
            .lock()
            .expect("events lock should not be poisoned")
            .push(format!("finish:{}:{terminal:?}", self.name));
        let result = if self.finish_error {
            Err(ModelProviderPolicyError::new(
                format!("{}_finish_error", self.name),
                format!("{} finish failed", self.name),
            ))
        } else {
            Ok(())
        };
        Box::pin(std::future::ready(result))
    }
}

fn contributor(
    name: &'static str,
    active: bool,
    behavior: Behavior,
    events: &Arc<Mutex<Vec<String>>>,
) -> Arc<dyn ModelProviderPolicyContributor> {
    dynamic_contributor(
        name,
        Arc::new(AtomicBool::new(active)),
        None,
        behavior,
        events,
    )
}

fn dynamic_contributor(
    name: &'static str,
    active: Arc<AtomicBool>,
    set_active_on_begin: Option<(Arc<AtomicBool>, bool)>,
    behavior: Behavior,
    events: &Arc<Mutex<Vec<String>>>,
) -> Arc<dyn ModelProviderPolicyContributor> {
    Arc::new(RecordingContributor {
        name,
        active,
        set_active_on_begin,
        behavior,
        events: Arc::clone(events),
    })
}

#[tokio::test]
async fn active_snapshot_is_stable_across_contributor_awaits() {
    for (next_initially_active, next_value, should_run_next) in
        [(true, false, true), (false, true, false)]
    {
        let events = Arc::new(Mutex::new(Vec::new()));
        let next_active = Arc::new(AtomicBool::new(next_initially_active));
        let mut builder = ExtensionRegistryBuilder::<crate::config::Config>::new();
        builder.model_provider_policy_contributor(dynamic_contributor(
            "first",
            Arc::new(AtomicBool::new(true)),
            Some((Arc::clone(&next_active), next_value)),
            Behavior::Allow {
                finish_error: false,
            },
            &events,
        ));
        builder.model_provider_policy_contributor(dynamic_contributor(
            "next",
            next_active,
            None,
            Behavior::Block,
            &events,
        ));
        let registry = builder.build();
        let (session_store, thread_store, turn_store) = stores();
        let digests = [digest('a'), digest('b'), digest('c'), digest('d')];

        let result = begin_model_provider_policy(
            &registry,
            input(&session_store, &thread_store, &turn_store, &digests),
        )
        .await
        .expect("snapshot evaluation should not fail");
        assert_eq!(
            matches!(result, ModelProviderPolicyBegin::Block { .. }),
            should_run_next
        );
        assert_eq!(
            events
                .lock()
                .expect("events lock should not be poisoned")
                .iter()
                .any(|event| event == "begin:next"),
            should_run_next
        );
    }
}

fn digest(byte: char) -> ModelProviderSha256Digest {
    ModelProviderSha256Digest::parse(byte.to_string().repeat(64))
        .expect("test digest should be valid")
}

fn stores() -> (ExtensionData, ExtensionData, ExtensionData) {
    (
        ExtensionData::new("session"),
        ExtensionData::new("thread"),
        ExtensionData::new("turn"),
    )
}

fn input<'a>(
    session_store: &'a ExtensionData,
    thread_store: &'a ExtensionData,
    turn_store: &'a ExtensionData,
    digests: &'a [ModelProviderSha256Digest; 4],
) -> ModelProviderInvocationInput<'a> {
    ModelProviderInvocationInput {
        schema_version: MODEL_PROVIDER_POLICY_INPUT_SCHEMA_VERSION,
        session_store,
        thread_store,
        turn_store,
        attempt_id: "attempt-1",
        request_binding_id: "binding-1",
        thread_id: "thread-1",
        turn_id: "turn-1",
        request_kind: ModelProviderRequestKind::Turn,
        provider_id: "provider-1",
        provider_config_sha256: &digests[0],
        model: "model-1",
        transport: ModelProviderTransport::Http,
        endpoint_sha256: &digests[1],
        logical_request_sha256: &digests[2],
        wire_semantic_sha256: &digests[3],
        ephemeral_input_sha256: None,
        ephemeral_input_witness_sha256: None,
        previous_response_id_sha256: None,
        generate: true,
    }
}

#[tokio::test]
async fn inactive_contributors_produce_no_policy() {
    let events = Arc::new(Mutex::new(Vec::new()));
    let mut builder = ExtensionRegistryBuilder::<crate::config::Config>::new();
    builder.model_provider_policy_contributor(contributor(
        "inactive",
        false,
        Behavior::Allow {
            finish_error: false,
        },
        &events,
    ));
    let registry = builder.build();
    let (session_store, thread_store, turn_store) = stores();
    let digests = [digest('a'), digest('b'), digest('c'), digest('d')];

    assert!(!has_active_model_provider_policy(&registry, &thread_store));
    assert!(matches!(
        begin_model_provider_policy(
            &registry,
            input(&session_store, &thread_store, &turn_store, &digests),
        )
        .await
        .expect("inactive contributors should not fail"),
        ModelProviderPolicyBegin::NoPolicy
    ));
    assert!(
        events
            .lock()
            .expect("events lock should not be poisoned")
            .is_empty()
    );
}

#[tokio::test]
async fn active_contributors_finish_in_registration_order() {
    let events = Arc::new(Mutex::new(Vec::new()));
    let mut builder = ExtensionRegistryBuilder::<crate::config::Config>::new();
    for name in ["one", "two"] {
        builder.model_provider_policy_contributor(contributor(
            name,
            true,
            Behavior::Allow {
                finish_error: false,
            },
            &events,
        ));
    }
    let registry = builder.build();
    let (session_store, thread_store, turn_store) = stores();
    let digests = [digest('a'), digest('b'), digest('c'), digest('d')];
    let ModelProviderPolicyBegin::Allow { lease } = begin_model_provider_policy(
        &registry,
        input(&session_store, &thread_store, &turn_store, &digests),
    )
    .await
    .expect("all contributors should allow") else {
        panic!("active allow contributors should produce a composite lease");
    };

    lease
        .finish(ModelProviderTerminal::NotDispatched {
            reason_code: "test_terminal".to_string(),
        })
        .await
        .expect("all child leases should finish");

    assert_eq!(
        events
            .lock()
            .expect("events lock should not be poisoned")
            .as_slice(),
        [
            "begin:one",
            "begin:two",
            "finish:one:NotDispatched { reason_code: \"test_terminal\" }",
            "finish:two:NotDispatched { reason_code: \"test_terminal\" }",
        ]
    );
}

#[tokio::test]
async fn block_and_begin_error_close_previously_acquired_leases() {
    for (terminal_name, behavior, expected_reason, cleanup_reason) in [
        (
            "block",
            Behavior::Block,
            "block_blocked",
            "model_provider_policy_blocked",
        ),
        (
            "error",
            Behavior::Error,
            "error_error",
            "model_provider_policy_begin_failed",
        ),
    ] {
        let events = Arc::new(Mutex::new(Vec::new()));
        let mut builder = ExtensionRegistryBuilder::<crate::config::Config>::new();
        builder.model_provider_policy_contributor(contributor(
            "allow",
            true,
            Behavior::Allow {
                finish_error: false,
            },
            &events,
        ));
        builder.model_provider_policy_contributor(contributor(
            terminal_name,
            true,
            behavior,
            &events,
        ));
        let registry = builder.build();
        let (session_store, thread_store, turn_store) = stores();
        let digests = [digest('a'), digest('b'), digest('c'), digest('d')];

        let result = begin_model_provider_policy(
            &registry,
            input(&session_store, &thread_store, &turn_store, &digests),
        )
        .await;
        match result {
            Ok(ModelProviderPolicyBegin::Block { reason_code, .. }) => {
                assert_eq!(reason_code, expected_reason);
            }
            Err(error) => assert_eq!(error.reason_code(), expected_reason),
            Ok(ModelProviderPolicyBegin::NoPolicy | ModelProviderPolicyBegin::Allow { .. }) => {
                panic!("terminal contributor must not allow")
            }
        }
        assert_eq!(
            events
                .lock()
                .expect("events lock should not be poisoned")
                .last()
                .map(String::as_str),
            Some(
                format!("finish:allow:NotDispatched {{ reason_code: \"{cleanup_reason}\" }}")
                    .as_str()
            )
        );
    }
}

#[tokio::test]
async fn composite_finish_attempts_every_lease_and_surfaces_failures() {
    let events = Arc::new(Mutex::new(Vec::new()));
    let mut builder = ExtensionRegistryBuilder::<crate::config::Config>::new();
    for (name, finish_error) in [("bad", true), ("good", false), ("also_bad", true)] {
        builder.model_provider_policy_contributor(contributor(
            name,
            true,
            Behavior::Allow { finish_error },
            &events,
        ));
    }
    let registry = builder.build();
    let (session_store, thread_store, turn_store) = stores();
    let digests = [digest('a'), digest('b'), digest('c'), digest('d')];
    let ModelProviderPolicyBegin::Allow { lease } = begin_model_provider_policy(
        &registry,
        input(&session_store, &thread_store, &turn_store, &digests),
    )
    .await
    .expect("all contributors should begin") else {
        panic!("active allow contributors should produce a composite lease");
    };

    let error = lease
        .finish(ModelProviderTerminal::NotDispatched {
            reason_code: "test_terminal".to_string(),
        })
        .await
        .expect_err("any child failure should fail the composite terminal");
    assert_eq!(error.reason_code(), "model_provider_policy_terminal_failed");
    assert!(error.detail().contains("bad_finish_error"));
    assert!(error.detail().contains("also_bad_finish_error"));
    assert!(
        events
            .lock()
            .expect("events lock should not be poisoned")
            .iter()
            .any(|event| event.starts_with("finish:good:"))
    );
}

#[tokio::test]
async fn cancelled_begin_closes_every_acquired_lease() {
    let events = Arc::new(Mutex::new(Vec::new()));
    let mut builder = ExtensionRegistryBuilder::<crate::config::Config>::new();
    builder.model_provider_policy_contributor(contributor(
        "allow",
        true,
        Behavior::Allow {
            finish_error: false,
        },
        &events,
    ));
    builder.model_provider_policy_contributor(contributor(
        "pending",
        true,
        Behavior::Pending,
        &events,
    ));
    let registry = builder.build();
    let (session_store, thread_store, turn_store) = stores();
    let digests = [digest('a'), digest('b'), digest('c'), digest('d')];
    let mut begin = Box::pin(begin_model_provider_policy(
        &registry,
        input(&session_store, &thread_store, &turn_store, &digests),
    ));

    tokio::select! {
        result = &mut begin => panic!("pending contributor unexpectedly completed: {}", result.is_ok()),
        _ = tokio::time::sleep(std::time::Duration::from_millis(10)) => {}
    }
    drop(begin);

    tokio::time::timeout(std::time::Duration::from_secs(1), async {
        loop {
            if events
                .lock()
                .expect("events lock should not be poisoned")
                .iter()
                .any(|event| {
                    event == "finish:allow:NotDispatched { reason_code: \"model_provider_policy_begin_cancelled\" }"
                })
            {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("cancelled begin should close acquired leases");
}
