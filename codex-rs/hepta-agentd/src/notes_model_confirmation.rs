//! Human confirmation consumes only an original owner proposal reference. No
//! replacement text, target, thread, callback or authority enters this method.

use super::*;

enum Decision {
    Confirm,
    Decline,
}

impl NotesModelBridge {
    pub(in super::super) async fn handle_command(
        &mut self,
        adapter: &mut AgentdNotesLiteralAdapter,
        command: ObjectiveCommand,
        end: Instant,
        view: &mut ObjectiveObservation,
        phase: &mut NotesUiCallPhase,
    ) -> Result<(), AgentdError> {
        if !self.available {
            view.issue = Some(ObjectiveHostIssue::Unavailable);
            return Ok(());
        }
        let (id, digest, decision) = match command {
            ObjectiveCommand::ConfirmModelProposal {
                proposal_id,
                proposal_sha256,
            } => (proposal_id, proposal_sha256, Decision::Confirm),
            ObjectiveCommand::DeclineModelProposal {
                proposal_id,
                proposal_sha256,
            } => (proposal_id, proposal_sha256, Decision::Decline),
            _ => return Err(invalid("not an original Notes model confirmation")),
        };
        view.issue = None;
        view.notes_document = None;
        view.observed_unix_ms =
            ObjectiveObservation::new(None, ObjectiveStage::Unavailable).observed_unix_ms;
        let Some(pending) = self.pending.get_mut(&id) else {
            view.issue = Some(ObjectiveHostIssue::NoRetainedIntent);
            return Ok(());
        };
        if pending.view.proposal_sha256 != digest {
            view.issue = Some(ObjectiveHostIssue::IdentityMismatch);
            return Ok(());
        }
        if pending.view.phase != NotesModelPhase::ReviewRequired {
            // Repeated confirmation only reads the original sender; it cannot
            // rearm preparation or a callback after an ambiguous response.
            *view = adapter.retained_view(&id).await?;
            return Ok(());
        }
        let live = self
            .session
            .requests
            .notes_tool_calls()
            .map_err(text_error)?;
        if pending.call.connection_id != self.session.requests.connection_id()
            || !live.iter().any(|call| {
                call.request_id == pending.call.request_id
                    && call.params == pending.call.params
                    && call.phase == NotesToolPhase::Pending
            })
            || self
                .session
                .requests
                .reconcile_notes_tool(&pending.call)
                .await
                .map_err(text_error)?
                != NotesToolPhase::Pending
        {
            view.issue = Some(ObjectiveHostIssue::OwnerRefused);
            return Ok(());
        }
        let run_id = adapter.run_id(&id)?;
        if adapter.writer.retained_operation(&run_id).await?.is_some() {
            pending.admission.mark_may_exist();
            check_retained_literal(
                &adapter.writer,
                &run_id,
                &pending.view.text,
                LiteralPredecessor::Current,
            )
            .await?;
            pending.view.phase = NotesModelPhase::Retained;
            pending.settle_by = Instant::now() + Duration::from_secs(30);
            *view = adapter.retained_view(&id).await?;
            return Ok(());
        }
        if Instant::now() >= end {
            return Err(invalid(
                "Notes model confirmation expired before original preparation",
            ));
        }
        let reviewed = pending.reviewed.clone().ok_or_else(|| {
            invalid("recovered Notes proposals have no new confirmation permission")
        })?;
        pending.settle_by = Instant::now() + Duration::from_secs(30);
        match decision {
            Decision::Confirm => {
                // Fence this disposable decision before entering the original
                // bounded preparation. Durable uncertainty stays at the owner.
                pending.admission.mark_may_exist();
                pending.view.phase = NotesModelPhase::Retained;
                adapter
                    .submit_ui_intent(
                        &ObjectiveIntent {
                            client_intent_id: id,
                            text: pending.view.text.clone(),
                        },
                        LiteralPredecessor::Reviewed(&reviewed),
                        end,
                        view,
                        phase,
                    )
                    .await?;
            }
            Decision::Decline => {
                let response =
                    unresolved_response(&pending.view, &run_id, NotesModelResult::Declined)?;
                pending.reply = Some(response.clone());
                pending.view.result = Some(NotesModelResult::Declined);
                pending.view.phase = NotesModelPhase::ReplyStarted;
                self.session
                    .requests
                    .reply_notes_tool(&mut pending.call, response)
                    .await
                    .map_err(text_error)?;
            }
        }
        adapter.refresh_ui_document(view, end).await
    }
}
