//! One bounded external-effect workflow through the original Agentd/TaskFlow
//! owners. Existing attempts always enter exact evidence reconciliation; only
//! original-store absence permits preparation and the existing FinalUse call.
use super::*;
use codex_hepta_automation::TaskFlowCommand;
use codex_hepta_automation::TaskFlowDefinition;
use codex_hepta_automation::TaskFlowEdgeSpec;
use codex_hepta_automation::TaskFlowNodeKind;
use codex_hepta_automation::TaskFlowNodeSpec;
use codex_hepta_automation::TaskFlowRun;
use codex_hepta_automation::TaskFlowRunState;
use codex_hepta_automation::TaskFlowStepState;
use codex_hepta_automation::TaskFlowTransition;

const OWNER: &str = "agentd.external-effect";
const LEASE_MS: u64 = 60_000;

pub(crate) struct AgentdEffectResumeInput<'a> {
    pub intent: &'a AuthorizedEffectIntent,
    pub wire_payload: &'a [u8],
    pub signed_grant: &'a SignedFinalUseGrant,
    pub command_id: &'a str,
    pub deadline: Instant,
}

impl AgentdAutomationEffectHost {
    pub(crate) async fn resume_effect(
        &self,
        store: &AutomationStore,
        state: &crate::AgentdState,
        input: AgentdEffectResumeInput<'_>,
    ) -> Result<AgentdAutomationEffectReconcileOutcome, AgentdError> {
        let _serial = self.resume_serial.lock().await;
        let AgentdEffectResumeInput { intent, wire_payload, signed_grant, command_id, deadline } = input;
        let now_ms = crate::state::control_time_ms()?;
        state.require_effect_ready()?;
        let identity = state.identity();
        self.validate_intent(intent, wire_payload)?;
        self.refresh_revocations()?;
        if identity.agent_id != self.agent_id
            || identity.spawn_generation == 0
            || intent.step_id != "effect"
            || intent.attempt != 1
            || !intent.dependencies.is_empty()
            || intent.compensation_for.is_some()
            || intent.expected_predecessor_digest.is_some()
        {
            return Err(AgentdError::Invalid(
                "ordinary effect entry requires this Agent's single first effect step".to_owned(),
            ));
        }
        let digest = intent.digest().map_err(protocol)?;
        let digest_hex = digest.as_str();
        let definition = TaskFlowDefinition::new(
            format!("agentd.external-effect.v1:{digest_hex}"),
            1,
            "effect",
            vec![
                TaskFlowNodeSpec::effect("effect", &intent.operation_id, "provider-effect-key-v1"),
                TaskFlowNodeSpec::new("success", TaskFlowNodeKind::TerminalSuccess),
                TaskFlowNodeSpec::new("failure", TaskFlowNodeKind::TerminalFailure),
            ],
            vec![TaskFlowEdgeSpec::new("effect", "success"), TaskFlowEdgeSpec::new("effect", "failure")],
            vec![intent.operation_id.clone()],
            intent.final_use_scope_digest.clone(),
        ).map_err(protocol)?;
        let thread_id = format!("agentd.external-effect:{digest_hex}");
        let existing_run = store.taskflow_run(&intent.run_id).await.map_err(protocol)?;
        if let Some(run) = &existing_run
            && (run.owner_agent_id != self.agent_id
                || run.workflow_id != definition.workflow_id
                || run.workflow_version != definition.version
                || run.definition_digest != *definition.definition_digest()
                || run.thread_id != thread_id)
        {
            return Err(AgentdError::GenerationFenced("run belongs to another original workflow".to_owned()));
        }
        // This original read validates the exact command and FinalUse binding
        // even when it returns None for a nonterminal durable attempt.
        if store.read_authorized_taskflow_effect_receipt(intent, command_id).await.map_err(protocol)?.is_some() {
            return self.observe_terminal(store, intent, command_id).await;
        }
        if let Some(pending) = store.authorized_taskflow_effect_attempt(
            &intent.run_id, &intent.step_id, intent.attempt,
        ).await.map_err(protocol)? {
            if pending.intent_digest != digest || pending.wire_payload.as_deref() != Some(wire_payload) {
                return Err(AgentdError::GenerationFenced("durable attempt differs from exact effect input".to_owned()));
            }
            self.provider_intent(&pending)?;
            let run = existing_run.ok_or_else(|| AgentdError::Protocol("durable attempt has no TaskFlow run".to_owned()))?;
            let historical = stored_fence(&run)?;
            if historical.owner_id != OWNER
                || historical.owner_epoch != historical.generation
                || historical.generation > identity.spawn_generation
                || historical != identity_fence(&self.agent_id, historical.generation)?
            {
                return Err(AgentdError::GenerationFenced("durable attempt has another Agentd owner fence".to_owned()));
            }
            // The original store already permits exact historical observation
            // after lease expiry. This branch never claims or renews a lease,
            // consumes/refunds a grant, or submits provider bytes again.
            return self.reconcile_pending(store, &pending, &historical, now_ms).await;
        }

        let fence = identity_fence(&self.agent_id, identity.spawn_generation)?;
        let dispatch_budget = ProviderDispatchBudget::ControlDeadline(deadline);
        dispatch_budget.require_remaining(&self.adapter).map_err(|_| AgentdError::Protocol(
            "effect control budget cannot cover provider dispatch; no new attempt was prepared; retry the exact original input".to_owned(),
        ))?;
        if let Some(run) = &existing_run
            && run.generation.is_some_and(|generation| generation != identity.spawn_generation)
        {
            return Err(AgentdError::GenerationFenced(
                "undispatched prior-generation step requires original TaskFlow recovery".to_owned(),
            ));
        }
        store.register_taskflow_definition(&definition, &fence, now_ms).await.map_err(protocol)?;
        store.create_taskflow_run(
            &intent.run_id, &definition.workflow_id, definition.version,
            definition.definition_digest(), thread_id, now_ms,
        ).await.map_err(protocol)?;
        let run = store.claim_taskflow_run(&intent.run_id, &fence, now_ms, LEASE_MS).await.map_err(protocol)?;
        match run.state {
            TaskFlowRunState::Queued => {
                let command = TaskFlowCommand::new(
                    &intent.run_id, format!("agentd.effect.start:{digest_hex}"), fence.clone(),
                    run.revision, TaskFlowTransition::Start, now_ms,
                ).map_err(protocol)?;
                store.apply_taskflow_command(&command).await.map_err(protocol)?;
            }
            TaskFlowRunState::Running => {}
            TaskFlowRunState::Waiting | TaskFlowRunState::RetryBackoff | TaskFlowRunState::Succeeded
            | TaskFlowRunState::Failed | TaskFlowRunState::Cancelled | TaskFlowRunState::Indeterminate => {
                return Err(AgentdError::Protocol("existing TaskFlow state cannot start another dispatch".to_owned()));
            }
        }
        let step = store.read_taskflow_step(&intent.run_id, &intent.step_id, intent.attempt, &fence)
            .await.map_err(protocol)?;
        if step.as_ref().is_some_and(|step| step.intent_digest != digest || step.payload_digest != intent.payload_digest) {
            return Err(AgentdError::GenerationFenced("prepared TaskFlow step differs from exact input".to_owned()));
        }
        if step.is_none() {
            store.prepare_taskflow_step(
                &intent.run_id, &intent.step_id, intent.attempt, &fence, &digest, &intent.payload_digest,
                &format!("agentd.effect.prepare:{digest_hex}"), now_ms,
            ).await.map_err(protocol)?;
        }
        match step.as_ref().map(|step| step.state) {
            None | Some(TaskFlowStepState::Prepared) => {
                store.claim_taskflow_step(
                    &intent.run_id, &intent.step_id, intent.attempt, &fence, &digest, &intent.payload_digest,
                    &format!("agentd.effect.claim:{digest_hex}"), now_ms,
                ).await.map_err(protocol)?;
            }
            Some(TaskFlowStepState::Claimed) => {}
            Some(TaskFlowStepState::Recorded | TaskFlowStepState::Reconciled) => {
                return Err(AgentdError::Protocol("observed step is missing its durable dispatch evidence".to_owned()));
            }
        }
        state.require_effect_ready()?;
        let dispatch_time_ms = crate::state::control_time_ms()?;
        dispatch_budget.require_remaining(&self.adapter).map_err(|_| AgentdError::Protocol(
            "effect control budget expired before dispatch; original prepared step remains recoverable".to_owned(),
        ))?;
        let receipt = self.execute_with_budget(store, AgentdEffectExecution {
            intent, wire_payload, signed_grant, command_id, now_ms: dispatch_time_ms, dispatch_budget,
        }).await?;
        if receipt.observation == Some(TaskFlowStepObservation::Indeterminate) {
            return Ok(AgentdAutomationEffectReconcileOutcome::Indeterminate);
        }
        self.observe_terminal(store, intent, command_id).await
    }
}

fn stored_fence(run: &TaskFlowRun) -> Result<TaskFlowFence, AgentdError> {
    let missing = || AgentdError::GenerationFenced("pending attempt lost its original owner tuple".to_owned());
    TaskFlowFence::new(
        run.owner_agent_id.clone(), run.owner_id.clone().ok_or_else(missing)?,
        run.owner_epoch.ok_or_else(missing)?, run.generation.ok_or_else(missing)?,
        run.fencing_token.clone().ok_or_else(missing)?,
    ).map_err(protocol)
}

fn identity_fence(agent: &codex_hepta_contracts::AgentId, generation: u64) -> Result<TaskFlowFence, AgentdError> {
    let mut bytes = b"hepta.agentd.external-effect.fence.v1\0".to_vec();
    bytes.extend_from_slice(agent.as_str().as_bytes());
    bytes.extend_from_slice(&generation.to_be_bytes());
    TaskFlowFence::new(
        agent.clone(), OWNER, generation, generation, Sha256Digest::for_bytes(&bytes).as_str(),
    ).map_err(protocol)
}

fn protocol(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Protocol(error.to_string())
}
