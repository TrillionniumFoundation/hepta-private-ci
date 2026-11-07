//! New finite source profile, retaining the same Root, sender and writer owners.
use super::*;
use crate::AgentdCalculatorStateObserver;
use crate::calculator_deadline::Deadline;
use crate::desktop_thread_tool::arguments::CalculatorArguments;
use crate::desktop_thread_tool::arguments::NotesArguments;
use crate::notes_literal_adapter::desktop_recorded::callback_matches;
use crate::notes_literal_adapter::desktop_recorded::reference_ids;
use crate::notes_thread_tool::human::VerifiedHumanTurn;
use codex_hepta_memory::CALCULATOR_EVALUATE_TOPIC_V1;
use codex_hepta_memory::LocalOutcomeState;
use codex_hepta_memory::NOTES_REPLACE_TOPIC_V1;
use codex_hepta_memory::OriginalDesktopThreadReference;
use codex_hepta_objective::DesktopThreadAction;
use codex_hepta_objective::DesktopThreadSourceContext;
use codex_hepta_objective::desktop_thread_source_json_v1;
use codex_hepta_types::StableId;
use serde_json::Value;
use serde_json::json;

struct DesktopCallIdentity<'a> {
    turn: &'a str,
    original_call_id: &'a str,
}

impl AgentdNotesLiteralAdapter {
    pub(crate) async fn prepare_desktop(
        &mut self,
        calculator: &AgentdCalculatorStateObserver,
        reference: OriginalDesktopThreadReference,
        arguments: &Value,
        human: &VerifiedHumanTurn,
        end: Deadline,
    ) -> Result<AgentdNotesPreparedObjective, AgentdError> {
        end.remaining()?;
        if self.profile != NotesAdapterProfile::OriginalDesktop
            || reference.thread_id != human.route().thread_id
            || reference.app_server_session_id != human.route().app_server_session_id
            || !callback_matches(&reference, arguments)?
        {
            return Err(invalid(
                "Desktop preparation differs from the verified original callback",
            ));
        }
        let (turn, call) = reference_ids(&reference, self.identity.agent_id.as_str())?;
        let prepared = tokio::time::timeout(end.remaining()?, async {
            let current = AgentdNotesLiteralAdapter::verify_original_human_text(
                self,
                human.ingress(),
                human.route(),
            )
            .await?;
            end.remaining()?;
            if !human.owner().same_authorization(&current) {
                return Err(invalid(
                    "original human authorization changed before Desktop preparation",
                ));
            }
            self.prepare_desktop_bound(
                calculator,
                reference,
                arguments,
                human,
                DesktopCallIdentity {
                    turn: &turn,
                    original_call_id: &call,
                },
                end,
            )
            .await
        })
        .await
        .map_err(|_| invalid("original Desktop preparation acknowledgement unknown"))??;
        end.remaining()?;
        Ok(prepared)
    }

    async fn prepare_desktop_bound(
        &mut self,
        calculator: &AgentdCalculatorStateObserver,
        reference: OriginalDesktopThreadReference,
        arguments: &Value,
        human: &VerifiedHumanTurn,
        call: DesktopCallIdentity<'_>,
        end: Deadline,
    ) -> Result<AgentdNotesPreparedObjective, AgentdError> {
        let DesktopCallIdentity {
            turn,
            original_call_id,
        } = call;
        let run_id = self.run_id(turn)?;
        if let Some(retained) = self
            .sender
            .retained_request_for_run(&run_id)
            .await
            .map_err(|error| invalid(&error.to_string()))?
        {
            if retained.origin().original_desktop_thread.as_ref() != Some(&reference)
                || retained.origin().original_notes_thread.is_some()
            {
                return Err(invalid(
                    "original turn already belongs to another effect call; read only",
                ));
            }
            require_original_thread_call(&retained, original_call_id)?;
            return Ok(AgentdNotesPreparedObjective::Retained(Box::new(retained)));
        }
        // Shared across BOTH effect tools, including a prepared operation whose
        // source signing or sender acknowledgement was lost. No new send token.
        crate::notes_literal_prepare::require_unprepared_original_turn(&self.writer, &run_id)
            .await?;
        self.check_available()?;
        self.require_objective_ready().await?;
        let permit = Arc::clone(&self.blocking)
            .try_acquire_owned()
            .map_err(|_| invalid("previous original Desktop observation is still running"))?;
        let subject = StableId::new(self.identity.agent_id.as_str())
            .map_err(|error| invalid(&error.to_string()))?;
        let (action, topic, operation, payload) = match reference.tool.as_str() {
            "hepta_notes_replace" => {
                let args: NotesArguments = serde_json::from_value(arguments.clone())?;
                if args.text.trim().is_empty() || args.text.len() > 4096 {
                    return Err(invalid("original Notes text exceeds its byte bound"));
                }
                let observer = self.observer.clone();
                let state = tokio::task::spawn_blocking(move || {
                    let _permit = permit;
                    end.remaining()?;
                    observer.observe_document()
                })
                .await
                .map_err(|_| invalid("original Notes observation worker failed"))??;
                if state.target != *self.observer.target()
                    || state.receipt_pending
                    || state.revision != args.expected_revision
                {
                    return Err(invalid(
                        "original Notes predecessor changed or receipt is pending",
                    ));
                }
                let payload = serde_json::to_string(&json!({
                    "schema_version":1,"action":"replace_note","operation_id":run_id,
                    "destination_id":state.target.destination_id(),"target":state.target,
                    "expected_revision":state.revision,"text":args.text,
                }))?;
                let operation = codex_hepta_memory::notes_operation_intent(
                    self.observer.target(),
                    &payload,
                    subject,
                    self.bindings.policy_generation,
                )
                .map_err(AgentdError::Invalid)?;
                (
                    DesktopThreadAction::NotesReplace,
                    NOTES_REPLACE_TOPIC_V1,
                    operation,
                    payload,
                )
            }
            "hepta_calculator_evaluate" => {
                let args: CalculatorArguments = serde_json::from_value(arguments.clone())?;
                args.validate()?;
                let observer = calculator.clone();
                let state = tokio::task::spawn_blocking(move || {
                    let _permit = permit;
                    end.remaining()?;
                    observer.observe_state()
                })
                .await
                .map_err(|_| invalid("original Calculator observation worker failed"))??;
                if state.target != *calculator.target()
                    || state.receipt_pending
                    || state.revision != args.expected_revision
                {
                    return Err(invalid(
                        "original Calculator predecessor changed or receipt is pending",
                    ));
                }
                let payload = serde_json::to_string(&json!({
                    "schema_version":1,"action":"evaluate","operation_id":run_id,
                    "destination_id":state.target.destination_id(),"target":state.target,
                    "expected_revision":state.revision,"left":args.left,"operator":args.operator,"right":args.right,
                }))?;
                let operation = codex_hepta_memory::calculator_operation_intent(
                    calculator.target(),
                    &payload,
                    subject,
                    self.bindings.policy_generation,
                )
                .map_err(AgentdError::Invalid)?;
                (
                    DesktopThreadAction::CalculatorEvaluate,
                    CALCULATOR_EVALUATE_TOPIC_V1,
                    operation,
                    payload,
                )
            }
            _ => {
                return Err(invalid(
                    "state/status tools cannot prepare a Desktop effect",
                ));
            }
        };
        self.check_available()?;
        let now_ms = self
            .root
            .clock()
            .now_unix_ms()
            .map_err(|_| invalid("protected Root clock unavailable"))?;
        let source_deadline = now_ms
            .checked_add(5_000)
            .ok_or_else(|| invalid("Desktop source deadline overflow"))?
            .min(human.owner().expires_at_ms);
        end.remaining()?;
        if source_deadline <= now_ms {
            return Err(invalid("original Desktop preparation window expired"));
        }
        prepare_desktop_operation_before(
            &self.writer,
            operation.clone(),
            topic,
            payload.clone(),
            end,
        )
        .await?;
        let retained = self
            .writer
            .retained_operation(&run_id)
            .await?
            .ok_or_else(|| invalid("original Desktop preparation was not retained"))?;
        if retained.operation != operation
            || retained.topic != topic
            || retained.payload_json != payload
            || retained.state != LocalOutcomeState::Queued
        {
            return Err(invalid(
                "original Desktop operation differs or already entered execution",
            ));
        }
        end.remaining()?;
        let source = desktop_thread_source_json_v1(
            action,
            DesktopThreadSourceContext {
                original_call_id,
                source_digest: operation.semantic_digest(),
                principal_scope_digest: self.bindings.principal_scope_digest,
                locale: &self.bindings.locale,
                observed_at: &utc_millis(now_ms)?,
                deadline: &utc_millis(source_deadline)?,
            },
        )
        .map_err(AgentdError::Invalid)?;
        let body = AuthBusObjectiveBody {
            spawn_generation: self.identity.spawn_generation,
            run_id,
            objective_revision: 1,
            source_envelope_json: source,
            runtime_body_digest: self.bindings.runtime_body_digest.to_string(),
            preference_state_digest: self.bindings.preference_state_digest.to_string(),
            model_tuple_digest: self.bindings.model_tuple_digest.to_string(),
            prompt_registry_digest: self.bindings.prompt_registry_digest.to_string(),
            artifact_set_digest: self.bindings.artifact_set_digest.to_string(),
            authority_epoch: self.root.authority().authority_epoch,
        };
        let permit = Arc::clone(&self.blocking)
            .try_acquire_owned()
            .map_err(|_| invalid("Desktop signer slot is occupied"))?;
        let grants = Arc::clone(&self.grants);
        let root = Arc::clone(&self.root);
        let human_check = Some((
            human.ingress().clone(),
            human.owner().clone(),
            human.route().clone(),
        ));
        let signed = tokio::task::spawn_blocking(move || {
            let _permit = permit;
            end.remaining()?;
            if root
                .clock()
                .now_unix_ms()
                .map_err(|_| invalid("Root clock unavailable before sign"))?
                >= source_deadline
            {
                return Err(invalid("Desktop source expired before Root signing"));
            }
            if let Some((ingress, original, route)) = human_check {
                let current = crate::AgentdUnixFinalUseGrantProvider::verify_original_human_text(
                    grants.as_ref(),
                    &ingress,
                )
                .map_err(|_| {
                    invalid("original human session is unavailable before Desktop signing")
                })?;
                if !current.validate()
                    || current.route != route
                    || !original.same_authorization(&current)
                    || root
                        .clock()
                        .now_unix_ms()
                        .map_err(|_| invalid("Root clock unavailable"))?
                        >= current.expires_at_ms
                {
                    return Err(invalid(
                        "original human session changed or expired before Desktop signing",
                    ));
                }
            }
            end.remaining()?;
            grants
                .sign_objective(&body)
                .map_err(|error| invalid(&error.to_string()))
        })
        .await
        .map_err(|_| invalid("Desktop Root signing worker failed"))??;
        end.remaining()?;
        self.check_available()?;
        if signed.issuer_id != self.bindings.issuer_id
            || self
                .root
                .clock()
                .now_unix_ms()
                .map_err(|_| invalid("Root clock unavailable after sign"))?
                >= source_deadline
        {
            return Err(invalid(
                "Desktop signed ingress expired or differs from frozen issuer",
            ));
        }
        let mut origin = self.next_origin()?;
        origin.original_desktop_thread = Some(reference);
        let request =
            ObjectiveSenderRequest::from_original(serde_json::to_string(&signed)?, origin)
                .map_err(|error| invalid(&error.to_string()))?;
        end.remaining()?;
        let ticket = self
            .sender
            .retain_before_send(request)
            .await
            .map_err(|error| invalid(&error.to_string()))?;
        end.remaining()?;
        self.check_available()?;
        if self
            .root
            .clock()
            .now_unix_ms()
            .map_err(|_| invalid("Root clock unavailable after sender retention"))?
            >= source_deadline
        {
            return Err(invalid(
                "Desktop source expired during original sender acknowledgement",
            ));
        }
        Ok(AgentdNotesPreparedObjective::Ready {
            sender: Arc::clone(&self.sender),
            ticket: Box::new(ticket),
            ingress: Box::new(signed),
        })
    }
}

/// Use the caller's unchanged total budget at the actual durable reservation.
/// Timeout never deletes a possible commit or grants another preparation.
pub(crate) async fn prepare_desktop_operation_before(
    writer: &ProductionDurableWriter,
    operation: codex_hepta_operations::OperationIntentV1,
    topic: &str,
    payload: String,
    end: Deadline,
) -> Result<(), AgentdError> {
    tokio::time::timeout(
        end.remaining()?,
        writer.prepare_operation(operation, topic, payload),
    )
    .await
    .map_err(|_| invalid("original Desktop reservation acknowledgement unknown"))??;
    end.remaining()?;
    Ok(())
}
