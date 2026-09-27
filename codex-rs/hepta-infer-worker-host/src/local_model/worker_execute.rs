impl<D, O, C> DurableLocalWorker<D, O, C>
where
    D: LocalModelDriver,
    O: TrustedResourceObserver,
    C: TrustedClock,
{
    pub async fn run(
        &self,
        control: &mut DurableInferenceControl,
        operation_id: OperationId,
        model_id: &str,
        input: VerifiedInput,
        maximum_tokens: u32,
        deadline_ms: u64,
        grant: &VerifiedResourceGrant,
        cancellation: &CancellationToken,
    ) -> Result<LocalRunReceipt, Error> {
        let now_ms = self.clock.now_ms()?;
        grant.validate_live(now_ms, &self.worker_id, self.generation)?;
        if maximum_tokens == 0
            || maximum_tokens > MAX_TOKENS
            || maximum_tokens > grant.claims.maximum_tokens
        {
            return Err(Error::InvalidGrant("token limit"));
        }
        let deadline = grant.verify_deadline(&self.clock, deadline_ms)?;
        let loaded = self.loaded_model(model_id, grant)?;
        control.submit(
            now_ms,
            DurableRequest {
                request_id: operation_id.as_str().to_string(),
                principal_id: self.worker_id.clone(),
                model_digest: loaded.handle.model_digest.clone(),
                payload_digest: input.digest().to_string(),
                maximum_tokens,
                deadline_ms,
                semantic_digest: request_semantic_digest(
                    &operation_id,
                    &loaded.handle,
                    &input,
                    maximum_tokens,
                    deadline_ms,
                    grant,
                ),
            },
        )?;
        let mut record = durable_record(control, &operation_id)?;
        if terminal_state(record.state) {
            return terminal_receipt(&record);
        }
        if cancellation.is_cancelled()
            && matches!(
                record.state,
                RequestState::Pending | RequestState::Reserved
            )
        {
            control.cancel(operation_id.as_str(), record.revision)?;
            return terminal_receipt(&durable_record(control, &operation_id)?);
        }
        if record.state == RequestState::Pending {
            control.reserve(
                now_ms,
                operation_id.as_str(),
                record.revision,
                DurableReservation {
                    reservation_id: grant.claims.grant_id.clone(),
                    quota_units: 1,
                    maximum_tokens,
                    authority_epoch: grant.claims.authority_epoch,
                    valid_until_ms: deadline_ms.min(grant.claims.expires_at_ms),
                },
            )?;
            record = durable_record(control, &operation_id)?;
        }
        let request_memory = request_memory(&loaded)?;
        if record.state == RequestState::Reserved {
            let mut resource = self.resources.reserve_request(
                &operation_id,
                request_memory,
                grant.claims.maximum_aggregate_memory_bytes,
                grant.claims.maximum_concurrent_requests,
            )?;
            control.assign(
                operation_id.as_str(),
                record.revision,
                Assignment {
                    worker_id: self.worker_id.clone(),
                    worker_generation: self.generation,
                    assignment_digest: assignment_digest(
                        &operation_id,
                        &loaded.handle,
                        grant,
                    ),
                },
            )?;
            resource.mark_dispatched()?;
            self.mark_active(model_id, operation_id.as_str())?;
            if cancellation.is_cancelled() {
                let assigned = durable_record(control, &operation_id)?;
                control.cancel(operation_id.as_str(), assigned.revision)?;
                let evidence = DriverRunEvidence {
                    terminal_observed: true,
                    status: Some(DriverTerminalStatus::Cancelled),
                    output_digest: None,
                    consumed_tokens: Some(0),
                    observed_model_bytes: loaded.handle.observed_weight_bytes,
                    observed_kv_memory_bytes: 0,
                    transient_memory_bytes: 0,
                };
                return self
                    .settle_after_host_observation(
                        control,
                        &operation_id,
                        model_id,
                        grant,
                        &loaded,
                        evidence,
                        resource,
                    )
                    .await;
            }
            return match self
                .driver
                .run(
                    &operation_id,
                    &loaded.handle,
                    &input,
                    cancellation,
                    &deadline,
                )
                .await
            {
                Ok(evidence)
                    if evidence.terminal_observed && evidence.consumed_tokens.is_some() =>
                {
                    self.settle_after_host_observation(
                        control,
                        &operation_id,
                        model_id,
                        grant,
                        &loaded,
                        evidence,
                        resource,
                    )
                    .await
                }
                Ok(_) => {
                    resource.quarantine()?;
                    Ok(indeterminate_receipt(
                        &operation_id,
                        "terminal result or trusted usage is unknown; quarantined",
                    ))
                }
                Err(error) => {
                    resource.quarantine()?;
                    Ok(indeterminate_receipt(
                        &operation_id,
                        &format!("driver result unknown after durable assignment: {error:?}"),
                    ))
                }
            };
        }
        if matches!(
            record.state,
            RequestState::Assigned | RequestState::Cancelling
        ) {
            self.resources.ensure_quarantined(
                &operation_id,
                request_memory,
                grant.claims.maximum_aggregate_memory_bytes,
                grant.claims.maximum_concurrent_requests,
            )?;
            self.mark_active(model_id, operation_id.as_str())?;
            return self
                .reconcile(control, &operation_id, model_id, grant, &loaded)
                .await;
        }
        Err(Error::Control(
            "unsupported durable request state".to_string(),
        ))
    }
}
