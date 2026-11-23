use super::TurnInput as PendingTurnInput;
use super::session::Session;
use super::turn_context::TurnContext;
use crate::codex_thread::InjectIfRunningError;
use crate::context::ContextualUserFragment;
use crate::context::SubagentNotification;
use crate::state::ActiveTurn;
use codex_features::Feature;
use codex_history::CodexHarnessMetadata;
use codex_history::ResponseItemEnvelope;
use codex_protocol::error::CodexErr;
use codex_protocol::error::Result as CodexResult;
use codex_protocol::models::ResponseItem;
use codex_protocol::protocol::InterAgentCommunication;

impl Session {
    /// Accepts model-visible mailbox input only after revoking any recovery
    /// authority for the request it can affect. Keep the active-turn lock
    /// across the durable revoke and queue append so controlled detach cannot
    /// acknowledge mail that a later recovery would silently omit.
    #[expect(
        clippy::await_holding_invalid_type,
        reason = "active turn checks, recovery revoke, and mailbox enqueue must remain atomic"
    )]
    pub(crate) async fn enqueue_mailbox_communication(
        &self,
        communication: InterAgentCommunication,
        parent_turn_id: Option<String>,
        root_turn_id: Option<String>,
    ) -> CodexResult<()> {
        if !self.enabled(Feature::HeptaTurnRecovery) {
            let active = self.active_turn.lock().await;
            if self.shutdown_started()
                || self.has_pending_task_terminalization()
                || active
                    .as_ref()
                    .is_some_and(|active_turn| active_turn.task_terminalization.is_some())
            {
                return Err(CodexErr::InvalidRequest(
                    "turn is terminalizing and cannot accept inter-agent communication".to_string(),
                ));
            }
            self.input_queue
                .enqueue_mailbox_communication(communication, parent_turn_id, root_turn_id)
                .await;
            drop(active);
            return Ok(());
        }

        if self.shutdown_started() || self.has_pending_task_terminalization() {
            return Err(CodexErr::InvalidRequest(
                "turn is terminalizing and cannot accept inter-agent communication".to_string(),
            ));
        }
        let active = self.active_turn.lock().await;
        if self.shutdown_started() || self.has_pending_task_terminalization() {
            return Err(CodexErr::InvalidRequest(
                "turn is terminalizing and cannot accept inter-agent communication".to_string(),
            ));
        }
        if let Some(active_turn) = active.as_ref() {
            if active_turn.task_terminalization.is_some() {
                return Err(CodexErr::InvalidRequest(
                    "turn is terminalizing and cannot accept inter-agent communication".to_string(),
                ));
            }
            let Some(task) = active_turn.task.as_ref() else {
                return Err(CodexErr::InvalidRequest(
                    "turn is transitioning and cannot accept inter-agent communication".to_string(),
                ));
            };
            if let Some(authority) = task.recovery_authority.as_ref() {
                self.ensure_turn_recovery_unready(&task.turn_context.sub_id, authority.as_ref())
                    .await?;
            }
            self.input_queue
                .enqueue_mailbox_communication(communication, parent_turn_id, root_turn_id)
                .await;
            return Ok(());
        }

        let consumed_recovery = self.consume_recovery_candidate_for_mutation().await?;
        self.input_queue
            .enqueue_mailbox_communication(communication, parent_turn_id, root_turn_id)
            .await;
        if consumed_recovery {
            self.settle_consumed_recovery_status();
        }
        drop(active);
        Ok(())
    }

    /// Returns the input if there is no active turn to inject into.
    #[expect(
        clippy::await_holding_invalid_type,
        reason = "active turn checks and turn state updates must remain atomic"
    )]
    pub async fn inject_if_running(
        &self,
        input: Vec<ResponseItem>,
    ) -> Result<(), InjectIfRunningError> {
        let mut active = self.active_turn.lock().await;
        self.inject_into_running_turn(active.as_mut(), input).await
    }

    async fn inject_into_running_turn(
        &self,
        active: Option<&mut ActiveTurn>,
        input: Vec<ResponseItem>,
    ) -> Result<(), InjectIfRunningError> {
        match active {
            Some(active_turn) => {
                if active_turn.task_terminalization.is_some() || active_turn.task.is_none() {
                    return Err(InjectIfRunningError::NoActiveTurn(input));
                }
                if let Some(task) = active_turn.task.as_ref()
                    && let Some(authority) = task.recovery_authority.as_ref()
                {
                    // Keep the active-turn lock across the strict recovery
                    // revoke and enqueue. This makes accepted model-visible
                    // input atomic with respect to Ready publication and task
                    // detach: active -> authority/rollout -> turn_state.
                    self.ensure_turn_recovery_unready(
                        &task.turn_context.sub_id,
                        authority.as_ref(),
                    )
                    .await
                    .map_err(InjectIfRunningError::RecoveryRevocation)?;
                }
                self.input_queue
                    .extend_pending_input_and_accept_mailbox_delivery_for_turn_state(
                        active_turn.turn_state.as_ref(),
                        input
                            .into_iter()
                            .map(ResponseItemEnvelope::new)
                            .map(PendingTurnInput::ResponseItem)
                            .collect(),
                    )
                    .await;
                Ok(())
            }
            None => Err(InjectIfRunningError::NoActiveTurn(input)),
        }
    }

    /// Preserves trusted client provenance while items wait for an active turn.
    #[expect(
        clippy::await_holding_invalid_type,
        reason = "active turn checks and turn state updates must remain atomic"
    )]
    pub(crate) async fn inject_client_response_items(
        &self,
        items: Vec<ResponseItem>,
        turn_context: &TurnContext,
    ) -> CodexResult<()> {
        let items = items
            .into_iter()
            .map(|item| self.annotate_client_response_item(item))
            .collect::<Vec<_>>();
        if self.shutdown_started() || self.has_pending_task_terminalization() {
            return Err(codex_protocol::error::CodexErr::InvalidRequest(
                "turn is terminalizing or shutting down and cannot accept injected context"
                    .to_string(),
            ));
        }
        let mut active = self.active_turn.lock().await;
        if self.shutdown_started() || self.has_pending_task_terminalization() {
            return Err(codex_protocol::error::CodexErr::InvalidRequest(
                "turn is terminalizing or shutting down and cannot accept injected context"
                    .to_string(),
            ));
        }
        if let Some(active_turn) = active.as_mut() {
            if active_turn.task_terminalization.is_some() || active_turn.task.is_none() {
                return Err(codex_protocol::error::CodexErr::InvalidRequest(
                    "turn is transitioning and cannot accept injected context".to_string(),
                ));
            }
            if let Some(task) = active_turn.task.as_ref()
                && let Some(authority) = task.recovery_authority.as_ref()
            {
                // As above, do not release the active-turn lock until the
                // durable Unready marker precedes the turn-state enqueue.
                self.ensure_turn_recovery_unready(&task.turn_context.sub_id, authority.as_ref())
                    .await?;
            }
            self.input_queue
                .extend_pending_input_and_accept_mailbox_delivery_for_turn_state(
                    active_turn.turn_state.as_ref(),
                    items
                        .into_iter()
                        .map(PendingTurnInput::ResponseItem)
                        .collect(),
                )
                .await;
            return Ok(());
        }
        if self.shutdown_started() || self.has_pending_task_terminalization() {
            return Err(CodexErr::InvalidRequest(
                "turn is terminalizing or shutting down and cannot accept idle injected context"
                    .to_string(),
            ));
        }
        let consumed_recovery = self.consume_recovery_candidate_for_mutation().await?;
        self.record_annotated_conversation_items(turn_context, items)
            .await;
        if consumed_recovery {
            self.settle_consumed_recovery_status();
        }
        drop(active);
        Ok(())
    }

    pub(crate) fn annotate_client_response_item(&self, item: ResponseItem) -> ResponseItemEnvelope {
        let metadata = (self.enabled(Feature::RetainClientDeveloperMessages)
            && matches!(&item, ResponseItem::Message { role, .. } if role == "developer"))
        .then_some(CodexHarnessMetadata {
            client_authored: true,
        });

        ResponseItemEnvelope { item, metadata }
    }

    pub(crate) async fn record_annotated_conversation_items(
        &self,
        turn_context: &TurnContext,
        items: Vec<ResponseItemEnvelope>,
    ) {
        if !self.enabled(Feature::RetainClientDeveloperMessages)
            || items.iter().all(|item| item.metadata.is_none())
        {
            let items = items
                .into_iter()
                .map(ResponseItemEnvelope::into_item)
                .collect::<Vec<_>>();
            self.record_conversation_items(turn_context, &items).await;
            return;
        }

        let mut annotated_items = Vec::with_capacity(items.len());
        let mut image_preparations = Vec::new();
        for envelope in items {
            let (prepared_items, prepared_images) = self.prepare_conversation_items_for_history(
                turn_context,
                std::slice::from_ref(&envelope.item),
            );
            image_preparations.extend(prepared_images);

            let mut metadata = envelope.metadata;
            annotated_items.extend(prepared_items.into_owned().into_iter().map(|item| {
                ResponseItemEnvelope {
                    item,
                    metadata: metadata.take(),
                }
            }));
        }
        self.record_prepared_conversation_items(turn_context, annotated_items, image_preparations)
            .await;
    }

    /// Injects items into active work, or records them without starting a turn.
    #[expect(
        clippy::await_holding_invalid_type,
        reason = "the active-turn guard is the atomic ownership fence across this awaited state transition"
    )]
    pub(crate) async fn inject_no_new_turn(
        &self,
        items: Vec<ResponseItem>,
        current_turn_context: Option<&TurnContext>,
    ) {
        let items = match self.inject_if_running(items).await {
            Ok(()) => return,
            Err(InjectIfRunningError::NoActiveTurn(items)) => items,
            Err(InjectIfRunningError::RecoveryRevocation(err)) => {
                tracing::error!(%err, "failed to revoke turn recovery before injecting context");
                return;
            }
        };
        if self.shutdown_started() || self.has_pending_task_terminalization() {
            tracing::error!(
                "session is terminalizing or shutting down; idle context injection was not recorded"
            );
            return;
        }
        let active = self.active_turn.lock().await;
        if self.shutdown_started() || self.has_pending_task_terminalization() || active.is_some() {
            tracing::error!(
                "active turn or terminalization fence changed while preparing an idle context injection; items were not recorded"
            );
            return;
        }
        self.record_idle_injection(items, current_turn_context)
            .await;
        drop(active);
    }

    /// The legacy child watcher delivers a finished child's context to its parent.
    /// Observe any in-flight lifecycle owner, then route under the normal active-turn
    /// guard. The watcher never retires a fence or starts another parent turn.
    #[expect(
        clippy::await_holding_invalid_type,
        reason = "notification routing uses the normal active-turn ownership fence across history or queue writes"
    )]
    pub(crate) async fn inject_subagent_notification(&self, notification: SubagentNotification) {
        loop {
            let mut active = self.active_turn.lock().await;
            if self.shutdown_started() {
                return;
            }
            if let Some(completion) = self.pending_admission_fence_completion() {
                drop(active);
                completion.await;
                continue;
            }
            let items = vec![ContextualUserFragment::into(notification)];
            if active.is_none() {
                self.record_idle_injection(items, /*current_turn_context*/ None)
                    .await;
            } else if let Err(error) = self.inject_into_running_turn(active.as_mut(), items).await {
                match error {
                    InjectIfRunningError::NoActiveTurn(_) => {
                        tracing::error!(
                            "subagent notification encountered an unowned turn transition"
                        );
                    }
                    InjectIfRunningError::RecoveryRevocation(error) => {
                        tracing::error!(%error, "failed to revoke turn recovery before injecting subagent notification");
                    }
                }
            }
            return;
        }
    }

    async fn record_idle_injection(
        &self,
        items: Vec<ResponseItem>,
        current_turn_context: Option<&TurnContext>,
    ) {
        let consumed_recovery = match self.consume_recovery_candidate_for_mutation().await {
            Ok(consumed_recovery) => consumed_recovery,
            Err(err) => {
                tracing::error!(%err, "failed to consume turn recovery before idle context injection");
                return;
            }
        };
        let default_turn_context;
        let turn_context = match current_turn_context {
            Some(turn_context) => turn_context,
            None => {
                default_turn_context = self.new_default_turn().await;
                default_turn_context.as_ref()
            }
        };
        self.record_conversation_items(turn_context, &items).await;
        if consumed_recovery {
            self.settle_consumed_recovery_status();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::session::session::RolloutPersistenceFault;
    use crate::session::tests::attach_in_memory_thread_store;
    use crate::session::tests::make_session_and_context_with_rx;
    use crate::state::TaskKind;
    use crate::state::TurnRecoveryAuthority;
    use crate::tasks::RecoveryProviderOutputGate;
    use crate::tasks::RecoveryReadyForSampling;
    use crate::tasks::SessionTask;
    use crate::tasks::SessionTaskResult;
    use codex_protocol::AgentPath;
    use codex_protocol::models::ContentItem;
    use codex_protocol::protocol::EventMsg;
    use codex_protocol::protocol::TurnAbortReason;
    use codex_protocol::protocol::TurnRecoveryCandidateState;
    use codex_protocol::protocol::WarningEvent;
    use std::sync::Arc;
    use std::sync::atomic::Ordering;
    use tokio_util::sync::CancellationToken;

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn terminal_child_notification_waits_for_normal_finish_and_stays_single() {
        use crate::session::tests::make_session_and_context;
        use codex_protocol::protocol::AgentStatus;
        use std::time::Duration;
        use tokio::sync::Notify;
        use tokio::time::timeout;

        struct ImmediateFinish;
        impl SessionTask for ImmediateFinish {
            fn kind(&self) -> TaskKind {
                TaskKind::Regular
            }

            fn span_name(&self) -> &'static str {
                "session_task.child_notification_finish_probe"
            }

            async fn run(
                self: Arc<Self>,
                _session: Arc<Session>,
                _context: Arc<TurnContext>,
                _input: Vec<PendingTurnInput>,
                _cancellation_token: CancellationToken,
            ) -> SessionTaskResult {
                Ok(None)
            }
        }

        struct IdleGate {
            entered: Arc<Notify>,
            release: Arc<Notify>,
        }
        impl codex_extension_api::ThreadLifecycleContributor<crate::config::Config> for IdleGate {
            fn on_thread_idle<'a>(
                &'a self,
                _input: codex_extension_api::ThreadIdleInput<'a>,
            ) -> codex_extension_api::ExtensionFuture<'a, ()> {
                Box::pin(async move {
                    self.entered.notify_one();
                    self.release.notified().await;
                })
            }
        }

        async fn count_notifications(session: &Session) -> usize {
            session.clone_history().await.raw_items().filter(|item| {
                let ResponseItem::Message { role, content, .. } = item else {
                    return false;
                };
                role == "user" && content.iter().any(|part| {
                    matches!(part, ContentItem::InputText { text } if SubagentNotification::matches_text(text))
                })
            }).count()
        }

        let (mut session, context) = make_session_and_context().await;
        let entered = Arc::new(Notify::new());
        let release = Arc::new(Notify::new());
        let mut extensions =
            codex_extension_api::ExtensionRegistryBuilder::<crate::config::Config>::new();
        extensions.thread_lifecycle_contributor(Arc::new(IdleGate {
            entered: Arc::clone(&entered),
            release: Arc::clone(&release),
        }));
        session.services.extensions = Arc::new(extensions.build());
        let session = Arc::new(session);
        session
            .spawn_task(Arc::new(context), Vec::new(), ImmediateFinish)
            .await
            .expect("start the original finish owner");
        timeout(Duration::from_secs(2), entered.notified())
            .await
            .expect("normal finish reached its idle callback");
        assert!(session.has_pending_task_terminalization());

        let send = session.inject_subagent_notification(SubagentNotification::new(
            "observed-child",
            AgentStatus::Completed(Some("child finished".into())),
        ));
        tokio::pin!(send);
        let returned_before_finish = timeout(Duration::from_millis(100), &mut send).await.is_ok();
        assert!(session.has_pending_task_terminalization());
        assert_eq!(count_notifications(&session).await, 0);
        release.notify_one();
        if !returned_before_finish {
            timeout(Duration::from_secs(2), send)
                .await
                .expect("deliver after genuine owner retirement");
        }
        assert!(
            !returned_before_finish,
            "child notification was discarded before the normal finish owner retired"
        );
        assert_eq!(count_notifications(&session).await, 1);

        session.begin_shutdown();
        session
            .inject_subagent_notification(SubagentNotification::new(
                "after-shutdown",
                AgentStatus::Completed(None),
            ))
            .await;
        assert_eq!(count_notifications(&session).await, 1);
    }

    #[derive(Clone, Copy, Debug)]
    enum InjectionPath {
        Raw,
        Client,
    }

    struct RecoverablePendingTask {
        authority: Arc<TurnRecoveryAuthority>,
    }

    impl SessionTask for RecoverablePendingTask {
        fn kind(&self) -> TaskKind {
            TaskKind::Regular
        }

        fn recovery_eligible_model_turn(&self) -> bool {
            true
        }

        fn recovery_authority(&self) -> Option<Arc<TurnRecoveryAuthority>> {
            Some(Arc::clone(&self.authority))
        }

        fn span_name(&self) -> &'static str {
            "session_task.inject_recovery_test"
        }

        async fn run(
            self: Arc<Self>,
            _session: Arc<Session>,
            _ctx: Arc<TurnContext>,
            _input: Vec<PendingTurnInput>,
            cancellation_token: CancellationToken,
        ) -> SessionTaskResult {
            cancellation_token.cancelled().await;
            Ok(None)
        }
    }

    fn injected_item(label: &str) -> ResponseItem {
        ResponseItem::Message {
            id: None,
            role: "developer".to_string(),
            content: vec![ContentItem::InputText {
                text: label.to_string(),
            }],
            phase: None,
            internal_chat_message_metadata_passthrough: None,
        }
    }

    async fn inject_via(
        session: &Session,
        turn_context: &TurnContext,
        path: InjectionPath,
        label: &str,
    ) -> CodexResult<()> {
        let item = injected_item(label);
        match path {
            InjectionPath::Raw => {
                session
                    .inject_if_running(vec![item])
                    .await
                    .map_err(|err| match err {
                        InjectIfRunningError::NoActiveTurn(_) => {
                            panic!("test turn should still be active")
                        }
                        InjectIfRunningError::RecoveryRevocation(err) => err,
                    })
            }
            InjectionPath::Client => {
                session
                    .inject_client_response_items(vec![item], turn_context)
                    .await
            }
        }
    }

    async fn recovery_fixture(
        feature_enabled: bool,
        turn_id: &str,
    ) -> (
        Arc<Session>,
        Arc<TurnContext>,
        Arc<TurnRecoveryAuthority>,
        Arc<codex_thread_store::InMemoryThreadStore>,
    ) {
        let (mut session, mut turn_context, _rx) = make_session_and_context_with_rx().await;
        if feature_enabled {
            let _ = Arc::get_mut(&mut session)
                .expect("fresh test session should be uniquely owned")
                .features
                .enable(Feature::HeptaTurnRecovery);
            let _ = Arc::make_mut(
                &mut Arc::get_mut(&mut turn_context)
                    .expect("fresh turn context should be uniquely owned")
                    .config,
            )
            .features
            .enable(Feature::HeptaTurnRecovery);
        }
        let store = attach_in_memory_thread_store(
            Arc::get_mut(&mut session).expect("test session should remain uniquely owned"),
        )
        .await;
        let authority = Arc::new(TurnRecoveryAuthority::default());
        let task = RecoverablePendingTask {
            authority: Arc::clone(&authority),
        };
        Arc::get_mut(&mut turn_context)
            .expect("test turn context should remain uniquely owned")
            .sub_id = turn_id.to_string();
        session
            .spawn_task(Arc::clone(&turn_context), Vec::new(), task)
            .await
            .expect("recovery fixture task should start");
        (session, turn_context, authority, store)
    }

    async fn mark_ready(session: &Session, turn_id: &str, authority: &Arc<TurnRecoveryAuthority>) {
        let baseline = session.rollout_persistence_failure_generation();
        assert_eq!(
            session
                .mark_recovery_ready_for_sampling(
                    turn_id,
                    authority,
                    baseline,
                    "inject-test-request-fingerprint",
                )
                .await
                .expect("Ready should append and flush"),
            RecoveryReadyForSampling::Ready,
        );
    }

    async fn recovery_markers(session: &Session, turn_id: &str) -> Vec<TurnRecoveryCandidateState> {
        session
            .live_thread()
            .expect("test fixture has live persistence")
            .load_history(/*include_archived*/ true)
            .await
            .expect("load injected recovery history")
            .items
            .into_iter()
            .filter_map(|item| match item {
                codex_history::RolloutItem::EventMsg(EventMsg::TurnRecoveryCandidate(marker))
                    if marker.turn_id == turn_id =>
                {
                    Some(marker.state)
                }
                _ => None,
            })
            .collect()
    }

    #[tokio::test]
    async fn active_injections_persist_unready_before_enqueue() {
        for path in [InjectionPath::Raw, InjectionPath::Client] {
            let turn_id = format!("inject-unready-{path:?}");
            let (session, turn_context, authority, _store) =
                recovery_fixture(/*feature_enabled*/ true, &turn_id).await;
            mark_ready(session.as_ref(), &turn_id, &authority).await;

            inject_via(
                session.as_ref(),
                turn_context.as_ref(),
                path,
                "accepted injection",
            )
            .await
            .expect("strict recovery revoke should allow injection");

            assert_eq!(
                recovery_markers(session.as_ref(), &turn_id).await,
                vec![
                    TurnRecoveryCandidateState::Ready,
                    TurnRecoveryCandidateState::Unready,
                ]
            );
            assert!(!authority.ready.load(Ordering::Acquire));
            assert_eq!(
                session
                    .input_queue
                    .get_pending_input(&session.active_turn)
                    .await
                    .0
                    .len(),
                1,
                "input may enter turn state only after durable Unready"
            );
            session.abort_all_tasks(TurnAbortReason::Replaced).await;
        }
    }

    #[tokio::test]
    async fn active_injections_reject_without_enqueue_when_revoke_fails() {
        for path in [InjectionPath::Raw, InjectionPath::Client] {
            let turn_id = format!("inject-revoke-failure-{path:?}");
            let (session, turn_context, authority, _store) =
                recovery_fixture(/*feature_enabled*/ true, &turn_id).await;
            mark_ready(session.as_ref(), &turn_id, &authority).await;
            authority.state.lock().await.poisoned = true;

            let err = inject_via(
                session.as_ref(),
                turn_context.as_ref(),
                path,
                "must be rejected",
            )
            .await
            .expect_err("a failed strict revoke must reject the injection");
            assert!(err.to_string().contains("recovery provenance is poisoned"));
            assert!(
                session
                    .input_queue
                    .get_pending_input(&session.active_turn)
                    .await
                    .0
                    .is_empty(),
                "failed revoke must not enqueue model-visible input"
            );
            assert_eq!(
                recovery_markers(session.as_ref(), &turn_id).await,
                vec![TurnRecoveryCandidateState::Ready]
            );
            session.abort_all_tasks(TurnAbortReason::Replaced).await;
        }
    }

    #[tokio::test]
    async fn feature_off_active_injections_add_no_recovery_persistence() {
        for path in [InjectionPath::Raw, InjectionPath::Client] {
            let turn_id = format!("inject-feature-off-{path:?}");
            let (session, turn_context, _authority, store) =
                recovery_fixture(/*feature_enabled*/ false, &turn_id).await;
            assert!(
                session
                    .active_turn
                    .lock()
                    .await
                    .as_ref()
                    .and_then(|active| active.task.as_ref())
                    .is_some_and(|task| task.recovery_authority.is_none()),
                "feature-off task must not retain recovery authority"
            );
            let appends_before = store.calls().await.append_items;

            inject_via(
                session.as_ref(),
                turn_context.as_ref(),
                path,
                "legacy injection",
            )
            .await
            .expect("feature-off injection keeps legacy behavior");

            assert_eq!(store.calls().await.append_items, appends_before);
            assert!(
                recovery_markers(session.as_ref(), &turn_id)
                    .await
                    .is_empty()
            );
            session.abort_all_tasks(TurnAbortReason::Replaced).await;
        }
    }

    fn mailbox_message(label: &str) -> InterAgentCommunication {
        InterAgentCommunication::new(
            AgentPath::root(),
            AgentPath::root(),
            Vec::new(),
            label.to_string(),
            /*trigger_turn*/ false,
        )
    }

    #[tokio::test]
    async fn active_mailbox_enqueue_persists_unready_before_acceptance() {
        let turn_id = "mailbox-unready";
        let (session, _turn_context, authority, _store) =
            recovery_fixture(/*feature_enabled*/ true, turn_id).await;
        mark_ready(session.as_ref(), turn_id, &authority).await;

        session
            .enqueue_mailbox_communication(
                mailbox_message("accepted mail"),
                /*parent_turn_id*/ None,
                /*root_turn_id*/ None,
            )
            .await
            .expect("strict recovery revoke should allow mailbox acceptance");

        assert_eq!(
            recovery_markers(session.as_ref(), turn_id).await,
            vec![
                TurnRecoveryCandidateState::Ready,
                TurnRecoveryCandidateState::Unready,
            ]
        );
        assert!(!authority.ready.load(Ordering::Acquire));
        assert!(session.input_queue.has_pending_mailbox_items().await);
        session.abort_all_tasks(TurnAbortReason::Replaced).await;
    }

    #[tokio::test]
    async fn mailbox_accepted_before_dispatch_suppresses_ready() {
        let turn_id = "mailbox-before-ready";
        let (session, _turn_context, authority, _store) =
            recovery_fixture(/*feature_enabled*/ true, turn_id).await;
        session
            .enqueue_mailbox_communication(
                mailbox_message("mail before dispatch"),
                /*parent_turn_id*/ None,
                /*root_turn_id*/ None,
            )
            .await
            .expect("mailbox input should be accepted while the task is attached");

        let baseline = session.rollout_persistence_failure_generation();
        assert_eq!(
            session
                .mark_recovery_ready_for_sampling(
                    turn_id,
                    &authority,
                    baseline,
                    "inject-test-request-fingerprint",
                )
                .await
                .expect("pending mailbox should fail closed without a Ready marker"),
            RecoveryReadyForSampling::PendingInput
        );
        assert!(!authority.ready.load(Ordering::Acquire));
        assert_eq!(
            recovery_markers(session.as_ref(), turn_id).await,
            vec![TurnRecoveryCandidateState::Unready]
        );
        session.abort_all_tasks(TurnAbortReason::Replaced).await;
    }

    #[tokio::test]
    async fn active_mailbox_enqueue_rejects_when_revoke_fails() {
        let turn_id = "mailbox-revoke-failure";
        let (session, _turn_context, authority, _store) =
            recovery_fixture(/*feature_enabled*/ true, turn_id).await;
        mark_ready(session.as_ref(), turn_id, &authority).await;
        authority.state.lock().await.poisoned = true;

        let err = session
            .enqueue_mailbox_communication(
                mailbox_message("must be rejected"),
                /*parent_turn_id*/ None,
                /*root_turn_id*/ None,
            )
            .await
            .expect_err("failed strict revoke must reject mailbox acceptance");

        assert!(err.to_string().contains("recovery provenance is poisoned"));
        assert!(!session.input_queue.has_pending_mailbox_items().await);
        assert_eq!(
            recovery_markers(session.as_ref(), turn_id).await,
            vec![TurnRecoveryCandidateState::Ready]
        );
        authority.state.lock().await.poisoned = false;
        session.abort_all_tasks(TurnAbortReason::Replaced).await;
    }

    #[tokio::test]
    async fn feature_off_mailbox_enqueue_keeps_legacy_behavior() {
        let turn_id = "mailbox-feature-off";
        let (session, _turn_context, _authority, store) =
            recovery_fixture(/*feature_enabled*/ false, turn_id).await;
        let appends_before = store.calls().await.append_items;

        session
            .enqueue_mailbox_communication(
                mailbox_message("legacy mail"),
                /*parent_turn_id*/ None,
                /*root_turn_id*/ None,
            )
            .await
            .expect("feature-off mailbox acceptance keeps legacy behavior");

        assert_eq!(store.calls().await.append_items, appends_before);
        assert!(session.input_queue.has_pending_mailbox_items().await);
        assert!(recovery_markers(session.as_ref(), turn_id).await.is_empty());
        session.abort_all_tasks(TurnAbortReason::Replaced).await;
    }

    #[tokio::test]
    async fn first_provider_output_gate_requires_exact_attached_authority() {
        let turn_id = "provider-output-gate";
        let (session, _turn_context, authority, _store) =
            recovery_fixture(/*feature_enabled*/ true, turn_id).await;
        mark_ready(session.as_ref(), turn_id, &authority).await;

        assert_eq!(
            session
                .gate_first_provider_output(turn_id, &authority)
                .await
                .expect("attached first output should close recovery authority"),
            RecoveryProviderOutputGate::Attached
        );
        assert_eq!(
            recovery_markers(session.as_ref(), turn_id).await,
            vec![
                TurnRecoveryCandidateState::Ready,
                TurnRecoveryCandidateState::Unready,
            ]
        );
        assert!(!authority.ready.load(Ordering::Acquire));

        session.abort_all_tasks(TurnAbortReason::Replaced).await;
        assert_eq!(
            session
                .gate_first_provider_output(turn_id, &authority)
                .await
                .expect("detached output should be rejected without persistence"),
            RecoveryProviderOutputGate::Detached
        );
    }

    #[tokio::test]
    async fn prior_transcript_gap_sticky_disables_later_ready_publication() {
        let first_turn_id = "persistence-gap-first-turn";
        let (session, first_turn, _first_authority, _store) =
            recovery_fixture(/*feature_enabled*/ true, first_turn_id).await;
        session
            .inject_rollout_persistence_fault(RolloutPersistenceFault::WarningAppend)
            .await;
        session
            .send_event(
                first_turn.as_ref(),
                EventMsg::Warning(WarningEvent {
                    message: "inject a transcript gap".to_string(),
                }),
            )
            .await;
        assert_eq!(session.rollout_persistence_failure_generation(), 1);
        session.abort_all_tasks(TurnAbortReason::Replaced).await;

        let second_turn_id = "persistence-gap-second-turn";
        let mut second_turn = session
            .new_default_turn_with_sub_id(second_turn_id.to_string())
            .await;
        let _ = Arc::make_mut(
            &mut Arc::get_mut(&mut second_turn)
                .expect("fresh turn context should be uniquely owned")
                .config,
        )
        .features
        .enable(Feature::HeptaTurnRecovery);
        let second_authority = Arc::new(TurnRecoveryAuthority::default());
        session
            .spawn_task(
                second_turn,
                Vec::new(),
                RecoverablePendingTask {
                    authority: Arc::clone(&second_authority),
                },
            )
            .await
            .expect("later task should start even though recovery is poisoned");

        let err = session
            .mark_recovery_ready_for_sampling(
                second_turn_id,
                &second_authority,
                session.rollout_persistence_failure_generation(),
                "inject-test-request-fingerprint",
            )
            .await
            .expect_err("a prior transcript gap must remain sticky for this session");
        assert!(
            err.to_string()
                .contains("recovery prerequisite persistence failed")
        );
        assert!(
            recovery_markers(session.as_ref(), second_turn_id)
                .await
                .is_empty(),
            "a poisoned session must not publish a later Ready marker"
        );
        assert!(!second_authority.ready.load(Ordering::Acquire));
        assert!(second_authority.state.lock().await.poisoned);
        session.abort_all_tasks(TurnAbortReason::Replaced).await;
    }
}
