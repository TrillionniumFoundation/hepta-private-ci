//! Independent observations and immutable original receipts; never effect I/O.
use super::*;

impl AgentdDesktopThreadToolRuntime {
    pub(super) async fn observe_recorded(
        &self,
        original: RecordedDesktopOperation,
    ) -> Result<Value, AgentdError> {
        let receipt = match original.reference.tool.as_str() {
            REPLACE_TOOL => {
                self.adapter
                    .writer
                    .retained_notes_terminal_receipt(&original.run_id)
                    .await?
            }
            CALCULATOR_EVALUATE_TOOL => {
                self.adapter
                    .writer
                    .retained_calculator_terminal_receipt(&original.run_id)
                    .await?
            }
            _ => return Err(invalid("recorded Desktop operation is not a finite effect")),
        };
        let state = self.adapter.writer.status(&original.run_id).await?;
        let payload: Value = serde_json::from_str(&original.operation.payload_json)?;
        // Current revision changes cannot erase the original causal receipt.
        let current = self.observe_current(&original.reference.tool).await.ok();
        Ok(
            json!({"source_domain":"original_protected_sender_reference",
            "selection_scope":"retained_original_operation","provenance":original.reference,
            "operation_id":original.run_id,"semantic_sha256":original.operation.operation.semantic_digest().to_string(),
            "exact_request_sha256":original.request_sha256,"state":format!("{state:?}"),
            "receipt_utf8":receipt,"original_target":payload["target"],
            "original_destination":original.operation.operation.destination_id().as_str(),
            "current_state_readback_available":current.is_some(),"current_state":current}),
        )
    }

    pub(super) async fn observe_current(&self, tool: &str) -> Result<Value, AgentdError> {
        self.adapter.check_available()?;
        let notes_selected = matches!(tool, READ_TOOL | REPLACE_TOOL | STATUS_TOOL);
        let permit = Arc::clone(&self.adapter.blocking)
            .try_acquire_owned()
            .map_err(|_| invalid("previous original Desktop observation is still running"))?;
        let notes = self.adapter.observer.clone();
        let calculator = self.calculator.clone();
        let state = tokio::time::timeout(self.adapter.deadline, tokio::task::spawn_blocking(move || {
            let _permit = permit;
            if notes_selected {
                let state = notes.observe_document()?;
                Ok::<_, AgentdError>(json!({"target":state.target,"revision":state.revision,
                    "text_sha256":state.text_sha256.as_str(),"receipt_pending":state.receipt_pending}))
            } else {
                let state = calculator.observe_state()?;
                Ok(json!({"target":state.target,"revision":state.revision,"state":state.state,
                    "state_sha256":state.state_sha256.as_str(),"receipt_pending":state.receipt_pending}))
            }
        })).await.map_err(|_| invalid("original Desktop readback timed out"))?
            .map_err(|_| invalid("original Desktop observation worker failed"))??;
        self.adapter.check_available()?;
        Ok(state)
    }

    pub(super) async fn observe_original(
        &self,
        call: &OriginalDesktopThreadItem,
    ) -> Result<Value, AgentdError> {
        let end = tokio::time::Instant::now() + Duration::from_secs(5);
        let observed = self
            .adapter
            .recorded_desktop_operation(
                &self.route,
                call.tool(),
                call.turn_id(),
                call.call_id(),
                end,
            )
            .await?;
        if let RecordedDesktopLookup::Found(original) = &observed
            && original.reference.callback_sha256 != call.callback_digest().to_string()
        {
            return Err(invalid(
                "original Core item differs from retained Desktop callback",
            ));
        }
        self.observe_lookup(observed).await
    }

    pub(super) async fn observe_lookup(
        &self,
        lookup: RecordedDesktopLookup,
    ) -> Result<Value, AgentdError> {
        match lookup {
            RecordedDesktopLookup::Unknown(reason) => {
                Ok(json!({"status":"unknown","reason":reason,
                "source_domain":"original_protected_sender_reference",
                "instruction":"No exact original result was verified; read only, never repeat the effect."}))
            }
            RecordedDesktopLookup::Found(original) => self.observe_recorded(original).await,
        }
    }
}
