impl<D, O, C> DurableLocalWorker<D, O, C>
where
    D: LocalModelDriver,
    O: TrustedResourceObserver,
    C: TrustedClock,
{
    pub async fn resolve_indeterminate(
        &self,
        control: &mut DurableInferenceControl,
        operation_id: OperationId,
        model_id: &str,
        grant: &VerifiedResourceGrant,
    ) -> Result<LocalRunReceipt, Error> {
        grant.validate_live(self.clock.now_ms()?, &self.worker_id, self.generation)?;
        let record = durable_record(control, &operation_id)?;
        if terminal_state(record.state) {
            return terminal_receipt(&record);
        }
        if !matches!(
            record.state,
            RequestState::Assigned | RequestState::Cancelling
        ) {
            return Err(Error::Control(
                "operation has no durable dispatch to inspect".to_string(),
            ));
        }
        let loaded = self.loaded_model(model_id, grant)?;
        self.resources.ensure_quarantined(
            &operation_id,
            request_memory(&loaded)?,
            grant.claims.maximum_aggregate_memory_bytes,
            grant.claims.maximum_concurrent_requests,
        )?;
        self.mark_active(model_id, operation_id.as_str())?;
        self.reconcile(control, &operation_id, model_id, grant, &loaded)
            .await
    }

    async fn reconcile(
        &self,
        control: &mut DurableInferenceControl,
        operation_id: &OperationId,
        model_id: &str,
        grant: &VerifiedResourceGrant,
        loaded: &LoadedModel,
    ) -> Result<LocalRunReceipt, Error> {
        let Some(evidence) = self.driver.inspect(operation_id).await? else {
            return Ok(indeterminate_receipt(
                operation_id,
                "inspection found no exact terminal evidence; no replay",
            ));
        };
        if !evidence.terminal_observed || evidence.consumed_tokens.is_none() {
            return Ok(indeterminate_receipt(
                operation_id,
                "inspection remains nonterminal or usage-unknown; no replay",
            ));
        }
        self.settle_after_host_observation(
            control,
            operation_id,
            model_id,
            grant,
            loaded,
            evidence,
            RequestReservation::from_quarantine(self.resources.clone(), operation_id),
        )
        .await
    }

    async fn settle_after_host_observation(
        &self,
        control: &mut DurableInferenceControl,
        operation_id: &OperationId,
        model_id: &str,
        grant: &VerifiedResourceGrant,
        loaded: &LoadedModel,
        evidence: DriverRunEvidence,
        mut resource: RequestReservation,
    ) -> Result<LocalRunReceipt, Error> {
        let host = match self
            .observer
            .observe(loaded.handle.handle_id(), Some(operation_id))
            .await
        {
            Ok(host) => host,
            Err(error) => {
                resource.quarantine()?;
                return Ok(indeterminate_receipt(
                    operation_id,
                    &format!("trusted resource observation unavailable: {error:?}"),
                ));
            }
        };
        if let Err(error) = validate_run_evidence(
            &evidence,
            &host,
            loaded,
            grant,
            self.generation,
        ) {
            resource.quarantine()?;
            return Err(error);
        }
        self.settle_terminal(
            control,
            operation_id,
            model_id,
            loaded,
            evidence,
            resource,
        )
    }

    fn settle_terminal(
        &self,
        control: &mut DurableInferenceControl,
        operation_id: &OperationId,
        model_id: &str,
        loaded: &LoadedModel,
        evidence: DriverRunEvidence,
        mut resource: RequestReservation,
    ) -> Result<LocalRunReceipt, Error> {
        let consumed_tokens = evidence
            .consumed_tokens
            .ok_or_else(|| Error::Control("terminal usage missing".to_string()))?;
        let (state, status, output) = match evidence
            .status
            .ok_or_else(|| Error::Control("terminal status missing".to_string()))?
        {
            DriverTerminalStatus::Succeeded => {
                let output = evidence.output_digest.ok_or_else(|| {
                    Error::Control("successful output missing".to_string())
                })?;
                (
                    RequestState::Completed,
                    LocalRunStatus::Succeeded,
                    Some(output),
                )
            }
            DriverTerminalStatus::Failed => {
                (RequestState::Failed, LocalRunStatus::Failed, evidence.output_digest)
            }
            DriverTerminalStatus::Cancelled => {
                (RequestState::Cancelled, LocalRunStatus::Cancelled, None)
            }
        };
        let current = durable_record(control, operation_id)?;
        let reservation_id = current
            .reservation
            .as_ref()
            .ok_or_else(|| Error::Control("durable reservation missing".to_string()))?
            .reservation_id
            .clone();
        let observation_digest = output.clone().unwrap_or_else(|| {
            digest(
                format!(
                    "hepta.local-terminal.v1|{}|{:?}|{}",
                    operation_id.as_str(),
                    status,
                    consumed_tokens
                )
                .as_bytes(),
            )
        });
        if let Err(error) = control.settle(
            operation_id.as_str(),
            current.revision,
            observation_digest,
            TerminalObservation {
                request_id: operation_id.as_str().to_string(),
                reservation_id,
                worker_id: self.worker_id.clone(),
                worker_generation: self.generation,
                model_digest: loaded.handle.model_digest.clone(),
                payload_digest: current.request.payload_digest,
                terminal_observed: true,
                terminal_status: Some(state),
                output_digest: output.clone(),
                consumed_tokens,
                usage_units: u64::from(consumed_tokens),
            },
        ) {
            resource.quarantine()?;
            return Err(error.into());
        }
        resource.finish()?;
        self.finish_active(model_id, operation_id.as_str())?;
        Ok(LocalRunReceipt {
            operation_id: operation_id.as_str().to_string(),
            status,
            output_digest: output,
            consumed_tokens: Some(consumed_tokens),
            terminal_observed: true,
            replayed_provider: false,
            stop_reason: None,
        })
    }
}
