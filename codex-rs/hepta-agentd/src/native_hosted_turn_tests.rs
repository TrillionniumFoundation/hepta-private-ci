//! Actual Core idle reservation and original ext/queue admission, with the
//! production native adapter and canonical compiler. Only HTTP/evaluator and
//! independent signing authorities are controlled fixtures.

use pretty_assertions::assert_ne;

use super::*;
use codex_core::hosted_turn::HostedAdmittedTurn;
use codex_core::hosted_turn::HostedFuture;
use codex_core::hosted_turn::HostedTurnExecution;
use codex_core::hosted_turn::HostedTurnExecutor;
use codex_core::hosted_turn::HostedTurnInput;
use codex_core::hosted_turn::HostedTurnMode;
use codex_core::hosted_turn::HostedTurnObservation;
use codex_core::hosted_turn::HostedTurnOutcome;
use codex_core::hosted_turn::HostedTurnPlan;
use codex_core::hosted_turn::HostedTurnRecoveryInput;
use codex_extension_api::ExtensionFuture;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::NoopExtensionEventSink;
use codex_extension_api::ThreadIdleCause;
use codex_extension_api::ThreadIdleInput;
use codex_extension_api::ThreadLifecycleContributor;
use codex_extension_api::ThreadResumeInput;
use codex_extension_api::ThreadStartInput;
use codex_features::Feature;
use codex_hepta_context_compiler::ContextItem;
use codex_hepta_context_compiler::ContextRole;
use codex_queue_extension::QueueReconcileMode;
use codex_queue_extension::QueueReconcileOutcome;
use codex_queue_extension::QueuedItemService;
use core_test_support::test_codex::TestCodex;
use core_test_support::test_codex::test_codex;
use core_test_support::wait_for_event_match;
use pretty_assertions::assert_eq;
use std::collections::BTreeMap;
use std::sync::Mutex;
use std::sync::OnceLock;
use tokio::sync::Notify;

use crate::intelligence_product::NativeContextBindingV1;
use crate::intelligence_product::NativeContextMaterialV1;
use crate::intelligence_product::tests::native_context_binding_tests::prepare_native_context;
use crate::native_hosted_turn::AgentdNativeHostedExecutor;
use crate::native_hosted_turn::NativeHostedResolution;
use crate::native_hosted_turn::NativeHostedResolveFuture;
use crate::native_hosted_turn::NativeHostedTurnConfig;
use crate::native_hosted_turn::NativeHostedTurnResolver;

#[derive(Clone)]
struct CapturedInput {
    live: LiveThread,
    thread_id: ThreadId,
    turn_id: String,
}

struct OriginalResolver {
    expected_input: Vec<UserInput>,
    run: RunReceipt,
    scope: NativeTurnScope,
    context: NativeContextBindingV1,
    calls: AtomicUsize,
    captured: Mutex<Option<CapturedInput>>,
}

impl NativeHostedTurnResolver for OriginalResolver {
    fn resolve<'a>(&'a self, input: &'a HostedTurnInput) -> NativeHostedResolveFuture<'a> {
        Box::pin(async move {
            self.calls.fetch_add(1, Ordering::SeqCst);
            // This stands in for the trusted product owner's existing input
            // correlation. A second valid canonical run alone is insufficient.
            ensure!(
                input.input == self.expected_input,
                "original input owner rejected another queued payload"
            );
            *self
                .captured
                .lock()
                .map_err(|error| anyhow::anyhow!(error.to_string()))? = Some(CapturedInput {
                live: input.live_thread.clone(),
                thread_id: input.thread_id,
                turn_id: input.turn_id.clone(),
            });
            Ok(NativeHostedResolution {
                run: self.run.clone(),
                scope: self.scope.clone(),
                context: self.context.clone(),
            })
        })
    }
}

// Match the existing queue_service integration fixture: install the mode
// before Core startup/prewarm, then attach the service to the actual manager.
struct InstalledQueue {
    executor: Arc<dyn HostedTurnExecutor>,
    service: OnceLock<Arc<QueuedItemService>>,
    failed_idle: Arc<Notify>,
}

impl ThreadLifecycleContributor<codex_core::config::Config> for InstalledQueue {
    fn on_thread_start<'a>(
        &'a self,
        input: ThreadStartInput<'a, codex_core::config::Config>,
    ) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            input
                .session_store
                .insert(HostedTurnMode::new(self.executor.clone()));
        })
    }

    fn on_thread_resume<'a>(&'a self, input: ThreadResumeInput<'a>) -> ExtensionFuture<'a, ()> {
        match self.service.get() {
            Some(service) => <QueuedItemService as ThreadLifecycleContributor<
                codex_core::config::Config,
            >>::on_thread_resume(service, input),
            None => Box::pin(async {}),
        }
    }

    fn on_thread_idle<'a>(&'a self, input: ThreadIdleInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            let failed = input.cause == ThreadIdleCause::Failed;
            if let Some(service) = self.service.get() {
                <QueuedItemService as ThreadLifecycleContributor<codex_core::config::Config>>::on_thread_idle(service, input).await;
            }
            if failed {
                self.failed_idle.notify_one();
            }
        })
    }
}

struct HostedFixture {
    base: Fixture,
    test: TestCodex,
    service: Arc<QueuedItemService>,
    native: Arc<AgentdNativeHost>,
    resolver: Arc<OriginalResolver>,
    input: TurnInput,
    payload_sha256: String,
    failed_idle: Arc<Notify>,
}

enum CompletionDelivery {
    Immediate,
    Pause(Arc<Notify>),
    PauseBeforeFirstEffect(Arc<Notify>),
    EntryProbe(Arc<entry_cancel_tests::EntryProbe>),
    ChangedRecoveryPolicy(NativeAgent),
}

// Deterministic crash-window fixture: preserve the real adapter and all owner
// effects, but hold its terminal reply before Core can record TurnComplete.
struct PausedCompletionExecutor {
    original: Arc<dyn HostedTurnExecutor>,
    ready: Arc<Notify>,
}

impl HostedTurnExecutor for PausedCompletionExecutor {
    fn executor_id(&self) -> &str {
        self.original.executor_id()
    }
    fn prepare<'a>(&'a self, input: HostedTurnInput) -> HostedFuture<'a, HostedTurnPlan> {
        Box::pin(async move {
            let mut plan = self.original.prepare(input).await?;
            plan.execution = Box::new(PausedCompletion {
                original: plan.execution,
                ready: self.ready.clone(),
            });
            Ok(plan)
        })
    }
    fn observe_admission<'a>(
        &'a self,
        input: HostedTurnObservation,
    ) -> HostedFuture<'a, Option<String>> {
        self.original.observe_admission(input)
    }
    fn recover<'a>(
        &'a self,
        input: HostedTurnRecoveryInput,
    ) -> HostedFuture<'a, HostedTurnOutcome> {
        self.original.recover(input)
    }
}

struct PausedCompletion {
    original: Box<dyn HostedTurnExecution>,
    ready: Arc<Notify>,
}

impl HostedTurnExecution for PausedCompletion {
    fn run(self: Box<Self>, turn: HostedAdmittedTurn) -> HostedFuture<'static, HostedTurnOutcome> {
        Box::pin(async move {
            let cancellation = turn.cancellation().clone();
            let outcome = self.original.run(turn).await?;
            if matches!(outcome, HostedTurnOutcome::Completed { .. }) {
                self.ready.notify_one();
                cancellation.cancelled().await;
                return Ok(HostedTurnOutcome::Cancelled);
            }
            Ok(outcome)
        })
    }
}

// Deterministic pre-effect crash window. Plan compilation and recovery remain
// with the actual adapter. This wrapper calls the same production preparation
// and confirmation methods, then stops before drive_prepared can admit a model
// or tool operation. It neither constructs authority nor replaces a store.
struct PausedBeforeFirstEffectExecutor {
    original: Arc<dyn HostedTurnExecutor>,
    native: Arc<AgentdNativeHost>,
    resolver: Arc<OriginalResolver>,
    ready: Arc<Notify>,
}

impl HostedTurnExecutor for PausedBeforeFirstEffectExecutor {
    fn executor_id(&self) -> &str {
        self.original.executor_id()
    }

    fn prepare<'a>(&'a self, input: HostedTurnInput) -> HostedFuture<'a, HostedTurnPlan> {
        Box::pin(async move {
            let original = NativeCheckpointBinding {
                thread_id: input.thread_id,
                turn_id: input.turn_id.clone(),
                operation_id: self.resolver.run.run_id.clone(),
                generation: self.resolver.run.generation,
                lease_id: self.native.host.writer().lease_id().to_owned(),
            };
            let queue = input.queue.clone();
            let mut plan = self.original.prepare(input).await?;
            plan.execution = Box::new(PausedBeforeFirstEffect {
                native: self.native.clone(),
                resolver: self.resolver.clone(),
                ready: self.ready.clone(),
                original,
                queue,
                fingerprint: plan.request_fingerprint_sha256.clone(),
                correlation: plan.correlation.clone(),
                executor_id: self.executor_id().to_owned(),
            });
            Ok(plan)
        })
    }

    fn observe_admission<'a>(
        &'a self,
        input: HostedTurnObservation,
    ) -> HostedFuture<'a, Option<String>> {
        self.original.observe_admission(input)
    }

    fn recover<'a>(
        &'a self,
        input: HostedTurnRecoveryInput,
    ) -> HostedFuture<'a, HostedTurnOutcome> {
        self.original.recover(input)
    }
}

struct PausedBeforeFirstEffect {
    native: Arc<AgentdNativeHost>,
    resolver: Arc<OriginalResolver>,
    ready: Arc<Notify>,
    original: NativeCheckpointBinding,
    queue: codex_core::hosted_turn::HostedQueueBinding,
    fingerprint: String,
    correlation: BTreeMap<String, String>,
    executor_id: String,
}

impl HostedTurnExecution for PausedBeforeFirstEffect {
    fn run(self: Box<Self>, turn: HostedAdmittedTurn) -> HostedFuture<'static, HostedTurnOutcome> {
        let Self {
            native,
            resolver,
            ready,
            original,
            queue,
            fingerprint,
            correlation,
            executor_id,
        } = *self;
        Box::pin(async move {
            let prepare: Result<_> = async {
                ensure!(
                    turn.thread_id() == original.thread_id
                        && turn.turn_id() == original.turn_id
                        && turn.queue() == &queue
                        && turn.recovery().fingerprint_sha256 == fingerprint,
                    "pre-effect fixture changed the actual adapter plan"
                );
                let provenance =
                    codex_core::hosted_turn::HostedTurnProvenance::from_recovery(turn.recovery())?
                        .context("actual Core hosted provenance")?;
                ensure!(
                    provenance.executor_id == executor_id
                        && provenance.correlation == correlation
                        && provenance.queue == queue,
                    "pre-effect fixture lost its original correlation"
                );
                let anchor = NativeTurnAnchorV1 {
                    checkpoint: original,
                    recovery: turn.recovery().clone(),
                    queue: Some(NativeQueueBindingV1 {
                        queued_item_id: queue.queued_item_id,
                        client_id: queue.client_id,
                        payload_sha256: queue.payload_sha256,
                    }),
                    run: None,
                    execution: None,
                    rendered_context_sha256: Some(
                        resolver.context.rendered_context_digest().to_string(),
                    ),
                };
                let prepared = native
                    .prepare_hosted_turn(
                        turn.live_thread().clone(),
                        anchor,
                        resolver.run.clone(),
                        resolver.scope.clone(),
                        resolver.context.clone(),
                    )
                    .await?;
                prepared.confirm_durable().await?;
                Ok(prepared)
            }
            .await;
            let prepared = prepare.map_err(|error| {
                codex_protocol::error::CodexErr::InvalidRequest(format!(
                    "pre-effect fixture preparation: {error:#}"
                ))
            })?;
            // This is the original Core notification and original queue CAS,
            // after the real native checkpoint/history confirmation above.
            turn.confirm_durable().await?;
            ready.notify_one();
            turn.cancellation().cancelled().await;
            // The original guard records the unresolved run as Indeterminate.
            // Never call drive_prepared after this simulated caller loss.
            drop(prepared);
            Ok(HostedTurnOutcome::Cancelled)
        })
    }
}

impl HostedFixture {
    async fn new(server: &MockServer) -> Result<Self> {
        Self::with_delivery(server, CompletionDelivery::Immediate).await
    }

    async fn with_delivery(server: &MockServer, delivery: CompletionDelivery) -> Result<Self> {
        Self::with_agent_and_delivery(server, delivery, agent()).await
    }

    async fn with_agent_and_delivery(
        server: &MockServer,
        delivery: CompletionDelivery,
        native_agent: NativeAgent,
    ) -> Result<Self> {
        let max_request_bytes = native_agent.limits.context_bytes;
        let max_stream_bytes = max_request_bytes
            .checked_mul(2)
            .context("fixture model stream budget overflow")?
            .max(16384);
        let base = Fixture::new_with_agent_model_bounds(
            format!("{}/v1/responses", server.uri()),
            AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c81")?,
            max_request_bytes,
            max_stream_bytes,
        )
        .await?;
        // The shared fixture's standalone thread is never handed to this
        // executor. The executed thread/queue below belong solely to Core.
        let identity = base.state.identity();
        let composition = crate::RuntimeComposition {
            agent_id: identity.agent_id.to_string(),
            supervisor_generation: identity.spawn_generation,
            agentd_generation: base.state.current_generation()?,
            configuration_digest: Sha256Digest::for_bytes(
                format!(
                    "{}|{}|{}|{}|{}",
                    identity.agent_id,
                    identity.spawn_generation,
                    identity.workspace.display(),
                    identity.home_root.display(),
                    identity.run_root.display()
                )
                .as_bytes(),
            )
            .as_str()
            .to_owned(),
            ports_digest: Sha256Digest::for_bytes(
                format!(
                    "{}|{}|{}",
                    identity.control_socket.display(),
                    identity.app_server_socket.display(),
                    crate::AGENTD_CONTROL_SCHEMA_VERSION
                )
                .as_bytes(),
            )
            .as_str()
            .to_owned(),
            max_active_runs: usize::from(identity.resources.max_concurrent_turns),
        };
        let text = "answer this original hosted queue input";
        let item = ContextItem {
            item_id: StableId::new("evidence.hosted-input")?,
            role: ContextRole::UntrustedEvidence,
            content_digest: Digest32::of_bytes(text.as_bytes()),
            source_digest: Digest32::of_bytes(b"original-hosted-input-owner"),
            token_count: 8,
            contains_secret: false,
        };
        let prepared = prepare_native_context(
            &composition,
            "run:hosted-queue",
            vec![item.clone()],
            /*token_budget*/ 16,
        )
        .await?;
        let context = prepared.bind_native_context(vec![NativeContextMaterialV1 {
            item_id: item.item_id,
            source_digest: item.source_digest,
            content: text.as_bytes().to_vec(),
        }])?;
        let snapshot = prepared.run_snapshot();
        base.state
            .response(
                /*request_id*/ 30,
                identity.spawn_generation,
                crate::AgentdMethod::RunStart {
                    snapshot: snapshot.clone(),
                },
            )
            .await?;
        let admitted = base.state.native_run_receipt(&snapshot.run_id)?;
        base.state
            .response(
                /*request_id*/ 31,
                identity.spawn_generation,
                crate::AgentdMethod::RunAttachContext {
                    expected_revision: admitted.revision,
                    attachment: prepared.context_attachment(),
                },
            )
            .await?;
        let run = base.state.native_run_receipt(&snapshot.run_id)?;
        let content = vec![UserInput::Text {
            text: text.to_owned(),
            text_elements: Vec::new(),
        }];
        let payload_sha256 = user_input_payload_sha256(&content)?;
        let input = TurnInput::UserInput {
            content: content.clone(),
            client_id: Some("client:hosted-queue".to_owned()),
        };
        let resolver = Arc::new(OriginalResolver {
            expected_input: content,
            run,
            scope: base.scope.clone(),
            context,
            calls: AtomicUsize::new(0),
            captured: Mutex::new(None),
        });
        let native = Arc::new(AgentdNativeHost {
            gate: base.native.gate.clone(),
            host: base.native.host.clone(),
            model: base.native.model.clone(),
            runtime: base.native.runtime.clone(),
            compiler: base.native.compiler.clone(),
        });
        let executor: Arc<dyn HostedTurnExecutor> = Arc::new(AgentdNativeHostedExecutor::new(
            native.clone(),
            NativeHostedTurnConfig {
                agent: Arc::new(native_agent),
                resolver: resolver.clone(),
            },
        )?);
        let executor: Arc<dyn HostedTurnExecutor> = match delivery {
            CompletionDelivery::Immediate => executor,
            CompletionDelivery::Pause(ready) => Arc::new(PausedCompletionExecutor {
                original: executor,
                ready,
            }),
            CompletionDelivery::PauseBeforeFirstEffect(ready) => {
                Arc::new(PausedBeforeFirstEffectExecutor {
                    original: executor,
                    native: native.clone(),
                    resolver: resolver.clone(),
                    ready,
                })
            }
            CompletionDelivery::EntryProbe(probe) => {
                Arc::new(entry_cancel_tests::EntryProbeExecutor {
                    original: executor,
                    native: native.clone(),
                    resolver: resolver.clone(),
                    probe,
                })
            }
            CompletionDelivery::ChangedRecoveryPolicy(recovery_agent) => {
                Arc::new(policy_recovery_tests::ChangedRecoveryExecutor {
                    original: executor,
                    recovered: Arc::new(AgentdNativeHostedExecutor::new(
                        native.clone(),
                        NativeHostedTurnConfig {
                            agent: Arc::new(recovery_agent),
                            resolver: resolver.clone(),
                        },
                    )?),
                })
            }
        };
        let failed_idle = Arc::new(Notify::new());
        let installed = Arc::new(InstalledQueue {
            executor: executor.clone(),
            service: OnceLock::new(),
            failed_idle: failed_idle.clone(),
        });
        let mut registry = ExtensionRegistryBuilder::new();
        registry.thread_lifecycle_contributor(installed.clone());
        let test = test_codex()
            .with_extensions(Arc::new(registry.build()))
            .with_history_mode(ThreadHistoryMode::Paginated)
            .with_config(|config| {
                config.include_environment_context = false;
                let _ = config.features.enable(Feature::HeptaTurnRecovery);
            })
            .build_with_auto_env(server)
            .await?;
        let original_queue = Arc::new(LocalQueueStore::new(
            test.codex
                .state_db()
                .context("Core original state database")?,
        ));
        let service = Arc::new(
            QueuedItemService::new(
                original_queue,
                Arc::downgrade(&test.thread_manager),
                Arc::new(NoopExtensionEventSink),
            )
            .with_hosted_turn_executor(Some(executor)),
        );
        ensure!(
            installed.service.set(service.clone()).is_ok(),
            "original queue already installed"
        );
        Ok(Self {
            base,
            test,
            service,
            native,
            resolver,
            input,
            payload_sha256,
            failed_idle,
        })
    }

    async fn enqueue(&self, input: TurnInput, payload_sha256: String) -> Result<String> {
        let reply = self
            .service
            .reconcile(
                self.test.session_configured.thread_id,
                /*rollout_path*/ None,
                input,
                payload_sha256,
                QueueReconcileMode::AllowIfAbsent,
            )
            .await?;
        let QueueReconcileOutcome::Queued {
            item,
            created: true,
        } = reply.outcome
        else {
            anyhow::bail!("expected original queue admission, got {:?}", reply.outcome);
        };
        Ok(item.id)
    }

    async fn start(&self) -> Result<String> {
        // Reconcile wakes the original loaded-thread queue. Observe that
        // admission; a second explicit start would race its completed row.
        self.enqueue(self.input.clone(), self.payload_sha256.clone())
            .await?;
        Ok(wait_for_event_match(&self.test.codex, |event| match event {
            EventMsg::TurnStarted(started) => Some(started.turn_id.clone()),
            _ => None,
        })
        .await)
    }

    async fn checkpoint(&self) -> Result<(NativeTurnAnchorV1, TurnState)> {
        let captured = self
            .resolver
            .captured
            .lock()
            .map_err(|error| anyhow::anyhow!(error.to_string()))?
            .clone()
            .context("Core never called resolver")?;
        let original = NativeCheckpointBinding {
            thread_id: captured.thread_id,
            turn_id: captured.turn_id,
            operation_id: self.resolver.run.run_id.clone(),
            generation: self.resolver.run.generation,
            lease_id: self.base.writer.lease_id().to_owned(),
        };
        self.native
            .read_hosted_checkpoint(&captured.live, &original)
            .await
    }

    async fn terminal(&self) -> EventMsg {
        wait_for_event_match(&self.test.codex, |event| match event {
            EventMsg::TurnComplete(_) | EventMsg::TurnAborted(_) => Some(event.clone()),
            _ => None,
        })
        .await
    }

    async fn error(&self) -> Result<String> {
        let observed = wait_for_event_match(&self.test.codex, |event| match event {
            EventMsg::Error(_) | EventMsg::TurnComplete(_) | EventMsg::TurnAborted(_) => {
                Some(event.clone())
            }
            _ => None,
        })
        .await;
        let EventMsg::Error(error) = observed else {
            anyhow::bail!("hosted technical failure created a terminal outcome: {observed:?}");
        };
        ensure!(!error.message.is_empty(), "hosted error omitted its reason");
        Ok(error.message)
    }

    async fn history(&self) -> Result<StoredModelContext> {
        // These paginated fixture turns contain no compaction. Readback uses
        // the original store's model-context API; recovery identity still
        // comes from Core's separate complete, bounded canonical history scan.
        let history = self
            .test
            .thread_store
            .load_latest_model_context(LoadThreadHistoryParams {
                thread_id: self.test.session_configured.thread_id,
                include_archived: false,
            })
            .await?;
        ensure!(
            history.thread_id == self.test.session_configured.thread_id,
            "original store returned another hosted thread's model context"
        );
        Ok(history)
    }

    async fn held(&self, turn_id: &str, original_aborts: usize) -> Result<()> {
        self.error().await?;
        // Error delivery precedes terminalizer cleanup. This original API
        // flushes/scans the typed tail and verifies the stable idle epoch.
        self.recovery_epoch(turn_id).await?;
        let history = self.history().await?;
        let aborted = history.items.iter().filter(|item| matches!(item,
            RolloutItem::EventMsg(EventMsg::TurnAborted(event)) if event.turn_id.as_deref() == Some(turn_id))).count();
        let completed = history
            .items
            .iter()
            .filter(|item| {
                matches!(item,
            RolloutItem::EventMsg(EventMsg::TurnComplete(event)) if event.turn_id == turn_id)
            })
            .count();
        assert_eq!(
            (aborted, completed),
            (original_aborts, 0),
            "technical failure must not append a fake terminal event"
        );
        Ok(())
    }

    async fn recovery_epoch(&self, turn_id: &str) -> Result<u64> {
        // Outcome/error notification precedes Core's task-finalization CAS.
        // Wait for the actual original idle owner and durable typed tail.
        tokio::time::timeout(Duration::from_secs(10), async {
            loop {
                if let Some(epoch) = self.test.codex.recovery_epoch_if_idle(turn_id).await {
                    return epoch;
                }
                tokio::task::yield_now().await;
            }
        })
        .await
        .context("Core did not expose the original idle recovery epoch")
    }

    async fn shutdown(self) -> Result<()> {
        self.test.codex.shutdown_and_wait().await?;
        self.base.live.shutdown().await?;
        Ok(())
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_core_queue_drives_native_canonical_turn_and_completes_once() -> Result<()> {
    let server = provider().await;
    let fixture = HostedFixture::new(&server).await?;
    assert!(
        server
            .received_requests()
            .await
            .context("HTTP capture")?
            .is_empty()
    );
    assert_eq!(fixture.base.issuer.grants.load(Ordering::SeqCst), 0);
    let turn_id = fixture.start().await?;
    let terminal = fixture.terminal().await;
    assert!(
        matches!(terminal, EventMsg::TurnComplete(_)),
        "hosted terminal: {terminal:?}"
    );
    let (anchor, checkpoint) = fixture.checkpoint().await?;
    assert_eq!(
        (
            anchor.checkpoint.turn_id.as_str(),
            checkpoint.final_answer.as_deref(),
            checkpoint.model_calls
        ),
        (turn_id.as_str(), Some("native owner complete"), 1)
    );
    assert_eq!(
        anchor.rendered_context_sha256,
        Some(
            fixture
                .resolver
                .context
                .rendered_context_digest()
                .to_string()
        )
    );
    assert_ne!(
        anchor.rendered_context_sha256.as_deref(),
        fixture.resolver.run.context_digest.as_deref()
    );
    let captured = server.received_requests().await.context("HTTP capture")?;
    assert_eq!(captured.len(), 1);
    assert_eq!(
        anchor.recovery.fingerprint_sha256,
        Digest32::of_bytes(&captured[0].body).to_string()
    );
    let operation = captured[0]
        .headers
        .get("idempotency-key")
        .context("native original key")?
        .to_str()?;
    assert_eq!(
        fixture.base.writer.status(operation).await?,
        LocalOutcomeState::Committed
    );
    assert_eq!(
        fixture
            .base
            .state
            .native_run_receipt(&fixture.resolver.run.run_id)?
            .phase,
        RunPhase::Succeeded
    );
    assert!(
        fixture
            .service
            .list(fixture.test.session_configured.thread_id)
            .await?
            .is_empty()
    );
    let duplicate = fixture
        .service
        .reconcile(
            fixture.test.session_configured.thread_id,
            /*rollout_path*/ None,
            fixture.input.clone(),
            fixture.payload_sha256.clone(),
            QueueReconcileMode::AllowIfAbsent,
        )
        .await?;
    assert_eq!(
        duplicate.outcome,
        QueueReconcileOutcome::Persisted {
            turn_id: turn_id.clone()
        }
    );
    let history = fixture.history().await?;
    let inputs = history.items.iter().filter(|item| matches!(item,
        RolloutItem::EventMsg(EventMsg::ItemCompleted(event)) if matches!(&event.item,
            TurnItem::UserMessage(message) if message.client_id.as_deref() == Some("client:hosted-queue")))).count();
    let outputs = history
        .items
        .iter()
        .filter(|item| {
            matches!(item,
        RolloutItem::ResponseItem(envelope) if matches!(&envelope.item,
            codex_protocol::models::ResponseItem::Message { role, .. } if role == "assistant"))
        })
        .count();
    let typed_outputs = history
        .items
        .iter()
        .filter(|item| {
            matches!(item,
        RolloutItem::EventMsg(EventMsg::ItemCompleted(event)) if event.turn_id == turn_id
            && matches!(&event.item, TurnItem::AgentMessage(_)))
        })
        .count();
    assert_eq!(
        (
            inputs,
            outputs,
            typed_outputs,
            fixture.resolver.calls.load(Ordering::SeqCst),
            fixture.base.issuer.grants.load(Ordering::SeqCst)
        ),
        (1, 1, 1, 1, 1)
    );
    assert_eq!(
        server
            .received_requests()
            .await
            .context("HTTP capture")?
            .len(),
        1
    );
    fixture.shutdown().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn trusted_input_owner_rejects_other_queue_payload_before_native_dispatch() -> Result<()> {
    let server = provider().await;
    let fixture = HostedFixture::new(&server).await?;
    let content = vec![UserInput::Text {
        text: "another original input".to_owned(),
        text_elements: Vec::new(),
    }];
    fixture
        .enqueue(
            TurnInput::UserInput {
                content: content.clone(),
                client_id: Some("client:other-input".to_owned()),
            },
            user_input_payload_sha256(&content)?,
        )
        .await?;
    let turn_id = wait_for_event_match(&fixture.test.codex, |event| match event {
        EventMsg::TurnStarted(started) => Some(started.turn_id.clone()),
        _ => None,
    })
    .await;
    assert!(
        fixture
            .error()
            .await?
            .contains("original input owner rejected another queued payload")
    );
    // The resolver failed before Core could publish typed recovery. Observe
    // the original failed-idle lifecycle and flush, without claiming recovery.
    tokio::time::timeout(Duration::from_secs(10), fixture.failed_idle.notified()).await?;
    fixture.test.codex.flush_rollout().await?;
    let history = fixture.history().await?;
    assert!(history.items.iter().all(|item| !matches!(item,
        RolloutItem::TurnRecoveryRequestBinding(binding) if binding.turn_id == turn_id)));
    assert!(history.items.iter().all(|item| !matches!(item,
        RolloutItem::EventMsg(EventMsg::TurnComplete(event)) if event.turn_id == turn_id)));
    assert!(history.items.iter().all(|item| !matches!(item,
        RolloutItem::EventMsg(EventMsg::TurnAborted(event)) if event.turn_id.as_deref() == Some(turn_id.as_str()))));
    assert!(
        fixture
            .test
            .codex
            .recovery_epoch_if_idle(&turn_id)
            .await
            .is_none()
    );
    assert_eq!(
        fixture
            .base
            .state
            .native_run_receipt(&fixture.resolver.run.run_id)?,
        fixture.resolver.run
    );
    assert!(
        fixture
            .resolver
            .captured
            .lock()
            .expect("captured input")
            .is_none()
    );
    assert_eq!(fixture.base.issuer.grants.load(Ordering::SeqCst), 0);
    assert!(
        server
            .received_requests()
            .await
            .context("HTTP capture")?
            .is_empty()
    );
    assert!(
        !fixture
            .service
            .list(fixture.test.session_configured.thread_id)
            .await?
            .is_empty()
    );
    fixture.shutdown().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn core_turn_recover_observes_original_native_response_without_queue_or_post_retry()
-> Result<()> {
    let server = MockServer::start().await;
    let created = json!({"type":"response.created","response":{"id":"response-recovery"}});
    Mock::given(method("POST"))
        .and(path("/v1/responses"))
        .respond_with(
            ResponseTemplate::new(200)
                .set_body_raw(format!("data: {created}\n\n"), "text/event-stream"),
        )
        .mount(&server)
        .await;
    let fixture = HostedFixture::new(&server).await?;
    let turn_id = fixture.start().await?;
    fixture.held(&turn_id, /*original_aborts*/ 0).await?;
    let (anchor_before, pending) = fixture.checkpoint().await?;
    let original = pending.pending_model.context("original pending model")?;
    assert_eq!(
        pending.provider_response_id.as_deref(),
        Some("response-recovery")
    );
    assert_eq!(
        fixture
            .base
            .state
            .native_run_receipt(&fixture.resolver.run.run_id)?
            .phase,
        RunPhase::Indeterminate
    );
    assert!(
        fixture
            .service
            .list(fixture.test.session_configured.thread_id)
            .await?
            .is_empty()
    );
    let output = json!({"type":"message","id":"hosted-recovered-output","role":"assistant","content":[{"type":"output_text","text":"observed original native response"}]});
    Mock::given(method("GET")).and(path("/v1/responses/response-recovery"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"id":"response-recovery","status":"completed","output":[output],"usage":{"input_tokens":3,"output_tokens":4}})))
        .mount(&server).await;
    let epoch = fixture.recovery_epoch(&turn_id).await?;
    let reply = fixture
        .test
        .codex
        .recover_turn_if_idle(codex_core::RecoverTurnRequest {
            turn_id: turn_id.clone(),
            expected_epoch: epoch,
            thread_settings: Default::default(),
            trace: None,
        })
        .await?;
    assert_eq!(
        reply,
        codex_core::StartIfIdleSubmission::Started {
            turn_id: turn_id.clone()
        }
    );
    let terminal = fixture.terminal().await;
    assert!(
        matches!(terminal, EventMsg::TurnComplete(_)),
        "hosted recovery: {terminal:?}"
    );
    let (anchor_after, completed) = fixture.checkpoint().await?;
    assert_eq!(anchor_after, anchor_before);
    assert_eq!(
        completed.final_answer.as_deref(),
        Some("observed original native response")
    );
    assert_eq!(
        fixture.base.writer.status(&original.operation_id).await?,
        LocalOutcomeState::Committed
    );
    assert_eq!(
        fixture
            .base
            .state
            .native_run_receipt(&fixture.resolver.run.run_id)?
            .phase,
        RunPhase::Succeeded
    );
    let requests = server.received_requests().await.context("HTTP capture")?;
    assert_eq!(
        (
            requests
                .iter()
                .filter(|request| request.method.as_str() == "POST")
                .count(),
            requests
                .iter()
                .filter(|request| request.method.as_str() == "GET")
                .count(),
            fixture.resolver.calls.load(Ordering::SeqCst),
            fixture.base.issuer.grants.load(Ordering::SeqCst)
        ),
        (1, 1, 1, 1)
    );
    let duplicate = fixture
        .service
        .reconcile(
            fixture.test.session_configured.thread_id,
            /*rollout_path*/ None,
            fixture.input.clone(),
            fixture.payload_sha256.clone(),
            QueueReconcileMode::AllowIfAbsent,
        )
        .await?;
    assert_eq!(
        duplicate.outcome,
        QueueReconcileOutcome::Persisted { turn_id }
    );
    fixture.shutdown().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn core_recovers_original_native_success_before_its_completion_event_without_new_effect()
-> Result<()> {
    let server = provider().await;
    let completed = Arc::new(Notify::new());
    let fixture =
        HostedFixture::with_delivery(&server, CompletionDelivery::Pause(completed.clone())).await?;
    let turn_id = fixture.start().await?;
    tokio::time::timeout(Duration::from_secs(10), completed.notified()).await?;
    let receipt = fixture
        .base
        .state
        .native_run_receipt(&fixture.resolver.run.run_id)?;
    assert_eq!(
        (receipt.phase, receipt.terminal_observed),
        (RunPhase::Succeeded, true)
    );
    let before = fixture.checkpoint().await?;
    assert_eq!(
        before.1.final_answer.as_deref(),
        Some("native owner complete")
    );
    fixture
        .test
        .codex
        .submit(codex_protocol::protocol::Op::Interrupt)
        .await?;
    assert!(matches!(fixture.terminal().await, EventMsg::TurnAborted(_)));
    let epoch = fixture.recovery_epoch(&turn_id).await?;
    let recovered = fixture
        .test
        .codex
        .recover_turn_if_idle(codex_core::RecoverTurnRequest {
            turn_id: turn_id.clone(),
            expected_epoch: epoch,
            thread_settings: Default::default(),
            trace: None,
        })
        .await?;
    assert_eq!(
        recovered,
        codex_core::StartIfIdleSubmission::Started {
            turn_id: turn_id.clone()
        }
    );
    let terminal = fixture.terminal().await;
    assert!(
        matches!(terminal, EventMsg::TurnComplete(_)),
        "original successful recovery: {terminal:?}"
    );
    let after = fixture.checkpoint().await?;
    assert_eq!(after.0, before.0);
    assert_eq!(
        crate::native_turn_checkpoint::encode(&after.0, &after.1)?,
        crate::native_turn_checkpoint::encode(&before.0, &before.1)?
    );
    assert_eq!(
        fixture
            .base
            .state
            .native_run_receipt(&fixture.resolver.run.run_id)?,
        receipt
    );
    assert_eq!(
        (
            server
                .received_requests()
                .await
                .context("HTTP capture")?
                .len(),
            fixture.base.issuer.grants.load(Ordering::SeqCst),
            fixture.resolver.calls.load(Ordering::SeqCst)
        ),
        (1, 1, 1)
    );
    assert!(
        fixture
            .service
            .list(fixture.test.session_configured.thread_id)
            .await?
            .is_empty()
    );
    assert!(
        fixture
            .test
            .codex
            .recovery_epoch_if_idle(&turn_id)
            .await
            .is_none()
    );
    let history = fixture.history().await?;
    assert_eq!(
        history
            .items
            .iter()
            .filter(|item| matches!(item,
        RolloutItem::EventMsg(EventMsg::ItemCompleted(event)) if event.turn_id == turn_id
            && matches!(&event.item, TurnItem::AgentMessage(_))))
            .count(),
        1,
        "original successful recovery must publish its one typed assistant result"
    );
    fixture.shutdown().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn core_recovery_after_queue_commit_before_first_effect_stays_held_without_dispatch()
-> Result<()> {
    let server = provider().await;
    let ready = Arc::new(Notify::new());
    let fixture = HostedFixture::with_delivery(
        &server,
        CompletionDelivery::PauseBeforeFirstEffect(ready.clone()),
    )
    .await?;
    let turn_id = fixture.start().await?;
    tokio::time::timeout(Duration::from_secs(10), ready.notified()).await?;
    let before = fixture.checkpoint().await?;
    assert_eq!((before.1.model_calls, before.1.tool_calls), (0, 0));
    assert!(
        before.1.pending_model.is_none()
            && before.1.provider_response_id.is_none()
            && before.1.pending_tool.is_none()
            && before.1.queued_tools.is_empty()
            && before.1.final_answer.is_none()
    );
    assert_eq!(
        fixture
            .base
            .state
            .native_run_receipt(&fixture.resolver.run.run_id)?
            .phase,
        RunPhase::Dispatched
    );
    assert!(
        fixture
            .service
            .list(fixture.test.session_configured.thread_id)
            .await?
            .is_empty()
    );
    assert_eq!(fixture.base.issuer.grants.load(Ordering::SeqCst), 0);
    assert!(
        server
            .received_requests()
            .await
            .context("HTTP capture")?
            .is_empty()
    );

    let captured = fixture
        .resolver
        .captured
        .lock()
        .expect("captured input")
        .clone()
        .context("original Core owner")?;
    let session = captured
        .live
        .open_native_checkpoint(
            before.0.checkpoint.clone(),
            NativeCheckpointOpenMode::Recover,
            Arc::new(ReadOriginalOnly),
        )
        .await?;
    let stored_before = captured.live.load_native_checkpoint(&session).await?;
    assert!(matches!(&stored_before, NativeCheckpointLoad::Present(_)));
    fixture
        .test
        .codex
        .submit(codex_protocol::protocol::Op::Interrupt)
        .await?;
    assert!(matches!(fixture.terminal().await, EventMsg::TurnAborted(_)));
    let original_snapshot = fixture
        .base
        .state
        .native_run_snapshot(&fixture.resolver.run.run_id)?;

    // Repeated recovery may observe only original operations. This checkpoint
    // has none, so both attempts remain held instead of issuing a first POST.
    for _ in 0..2 {
        let epoch = fixture.recovery_epoch(&turn_id).await?;
        assert_eq!(
            fixture
                .base
                .state
                .native_run_receipt(&fixture.resolver.run.run_id)?
                .phase,
            RunPhase::Indeterminate
        );
        let recovered = fixture
            .test
            .codex
            .recover_turn_if_idle(codex_core::RecoverTurnRequest {
                turn_id: turn_id.clone(),
                expected_epoch: epoch,
                thread_settings: Default::default(),
                trace: None,
            })
            .await?;
        assert_eq!(
            recovered,
            codex_core::StartIfIdleSubmission::Started {
                turn_id: turn_id.clone()
            }
        );
        // The one real Op::Interrupt remains in history. Technical recovery
        // failure must not manufacture another cancellation or completion.
        fixture.held(&turn_id, /*original_aborts*/ 1).await?;
        let after = fixture.checkpoint().await?;
        assert_eq!(
            crate::native_turn_checkpoint::encode(&after.0, &after.1)?,
            crate::native_turn_checkpoint::encode(&before.0, &before.1)?
        );
        assert_eq!(
            captured.live.load_native_checkpoint(&session).await?,
            stored_before
        );
        assert_eq!(
            fixture
                .base
                .state
                .native_run_snapshot(&fixture.resolver.run.run_id)?,
            original_snapshot
        );
        assert_eq!(
            (
                fixture.resolver.calls.load(Ordering::SeqCst),
                fixture.base.issuer.grants.load(Ordering::SeqCst)
            ),
            (1, 0)
        );
        assert!(
            server
                .received_requests()
                .await
                .context("HTTP capture")?
                .is_empty()
        );
        let original_queue = fixture
            .service
            .reconcile(
                fixture.test.session_configured.thread_id,
                fixture.test.codex.rollout_path(),
                fixture.input.clone(),
                fixture.payload_sha256.clone(),
                QueueReconcileMode::ReconcileOnly,
            )
            .await?;
        assert_eq!(
            original_queue.outcome,
            QueueReconcileOutcome::Persisted {
                turn_id: turn_id.clone()
            }
        );
        assert!(
            fixture
                .service
                .list(fixture.test.session_configured.thread_id)
                .await?
                .is_empty()
        );
    }
    fixture.recovery_epoch(&turn_id).await?;
    fixture.shutdown().await
}

#[path = "native_hosted_entry_cancel_tests.rs"]
mod entry_cancel_tests;

#[path = "native_hosted_context_tests.rs"]
mod context_tests;

#[path = "native_hosted_policy_recovery_tests.rs"]
mod policy_recovery_tests;
