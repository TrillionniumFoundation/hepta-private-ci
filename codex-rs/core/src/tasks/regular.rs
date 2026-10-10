use std::sync::Arc;

use tokio_util::sync::CancellationToken;

use crate::session::TurnInput;
use crate::session::session::Session;
use crate::session::turn::TurnRunOrigin;
use crate::session::turn::run_hooks_and_record_inputs;
use crate::session::turn::run_turn;
use crate::session::turn_context::TurnContext;
use crate::session_startup_prewarm::SessionStartupPrewarmResolution;
use crate::state::TaskKind;
use crate::state::TurnRecoveryAuthority;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::TurnStartedEvent;
use codex_thread_store::PersistContext;
use tracing::Instrument;
use tracing::trace_span;

use super::SessionTask;
use super::SessionTaskResult;

pub(crate) struct RegularTask {
    recovery_authority: Arc<TurnRecoveryAuthority>,
    run_origin: TurnRunOrigin,
    expected_recovery_fingerprint_sha256: Option<String>,
}

impl RegularTask {
    pub(crate) fn new(run_origin: TurnRunOrigin) -> Self {
        Self {
            recovery_authority: Arc::new(TurnRecoveryAuthority::default()),
            run_origin,
            expected_recovery_fingerprint_sha256: None,
        }
    }

    pub(crate) fn for_recovery(
        request_fingerprint_sha256: String,
        consumed_generation: u64,
    ) -> Self {
        Self {
            recovery_authority: Arc::new(TurnRecoveryAuthority::resumed_at_unready_generation(
                consumed_generation,
            )),
            run_origin: TurnRunOrigin::Recovery,
            expected_recovery_fingerprint_sha256: Some(request_fingerprint_sha256),
        }
    }
}

impl SessionTask for RegularTask {
    fn kind(&self) -> TaskKind {
        TaskKind::Regular
    }

    fn recovery_eligible_model_turn(&self) -> bool {
        true
    }

    fn recovery_authority(&self) -> Option<Arc<TurnRecoveryAuthority>> {
        Some(Arc::clone(&self.recovery_authority))
    }

    fn span_name(&self) -> &'static str {
        "session_task.turn"
    }

    fn turn_start_origin(&self) -> codex_extension_api::TurnStartOrigin {
        match self.run_origin {
            TurnRunOrigin::NewTurn => codex_extension_api::TurnStartOrigin::NewTurn,
            TurnRunOrigin::Recovery => codex_extension_api::TurnStartOrigin::Recovery,
        }
    }

    async fn run(
        self: Arc<Self>,
        sess: Arc<Session>,
        ctx: Arc<TurnContext>,
        input: Vec<TurnInput>,
        cancellation_token: CancellationToken,
    ) -> SessionTaskResult {
        // Lifecycle contributors finish before this task is spawned.  Keep
        // this check before TurnStarted/prewarm so a failed qualification
        // prepare cannot reach any provider-facing work.
        if let Some(gate) = ctx
            .extension_data
            .get::<codex_extension_api::TurnStartGate>()
            && !gate.is_allowed()
        {
            return Err(codex_protocol::error::CodexErr::TurnAborted);
        }
        let run_turn_span = trace_span!("run_turn");
        let persistence_failure_baseline = sess.rollout_persistence_failure_generation();
        // Regular turns emit `TurnStarted` inline so first-turn lifecycle does
        // not wait on startup prewarm resolution.
        let event = EventMsg::TurnStarted(TurnStartedEvent {
            turn_id: ctx.sub_id.clone(),
            trace_id: ctx.trace_id.clone(),
            started_at: ctx.turn_timing_state.started_at_unix_secs().await,
            model_context_window: ctx.model_context_window(),
            collaboration_mode_kind: ctx.mode,
        });
        sess.send_event(ctx.as_ref(), event).await;
        let prewarmed_client_session = async {
            sess.set_server_reasoning_included(/*included*/ false).await;
            sess.consume_startup_prewarm_for_regular_turn(&cancellation_token)
                .await
        }
        .instrument(trace_span!("regular_task.prepare_run_turn"))
        .await;
        let prewarmed_client_session = match prewarmed_client_session {
            SessionStartupPrewarmResolution::Cancelled => {
                run_hooks_and_record_inputs(&sess, &ctx, &input, PersistContext::Standard).await;
                return Ok(None);
            }
            SessionStartupPrewarmResolution::Unavailable { .. } => None,
            SessionStartupPrewarmResolution::Ready(prewarmed_client_session) => {
                Some(*prewarmed_client_session)
            }
        };
        let mut next_input = input;
        let mut prewarmed_client_session = prewarmed_client_session;
        let mut run_origin = self.run_origin;
        let mut expected_recovery_fingerprint_sha256 =
            self.expected_recovery_fingerprint_sha256.clone();
        loop {
            let last_agent_message = run_turn(
                Arc::clone(&sess),
                Arc::clone(&ctx),
                next_input,
                prewarmed_client_session.take(),
                Arc::clone(&self.recovery_authority),
                persistence_failure_baseline,
                run_origin,
                expected_recovery_fingerprint_sha256.take(),
                cancellation_token.child_token(),
            )
            .instrument(run_turn_span.clone())
            .await?;
            if !sess.input_queue.has_pending_input(&sess.active_turn).await {
                return Ok(last_agent_message);
            }
            next_input = Vec::new();
            run_origin = TurnRunOrigin::NewTurn;
        }
    }
}
