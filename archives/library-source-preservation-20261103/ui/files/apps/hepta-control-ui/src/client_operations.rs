//! Final-use request admission and query-only recovery under the client owner.
use super::*;

impl<T: ControlTransport, R: RecoveryStore> RuntimeClient<T, R> {
    pub fn capture_confirmation(
        &mut self,
        input: &ConfirmationInput,
    ) -> Result<ConfirmationContext> {
        self.session_for(Permission::Read)?;
        contract::capture_confirmation(self.session.as_ref(), self.snapshot.as_ref(), input)
    }
    pub fn submit(
        &mut self,
        method: Method,
        input: ConfirmationInput,
        confirmation: &ConfirmationContext,
    ) -> Result<OperationView> {
        let session = self.session_for(method.permission())?;
        let snapshot = self
            .snapshot
            .clone()
            .ok_or_else(|| ControlError::new(ErrorCode::StaleRevision).not_dispatched())?;
        contract::assert_confirmation(confirmation, Some(&session), Some(&snapshot), &input)?;
        let intent = OperationIntent {
            action: input.action,
            target_id: input.target_id.clone(),
            generation: snapshot.generation,
            displayed_revision: snapshot.revision,
            reason: input.reason.clone(),
        };
        let request = OperationRequest {
            protocol_version: session.protocol_version.clone(),
            method,
            operation_id: input.operation_id.clone(),
            semantic_digest: contract::digest_operation_intent(&intent)?,
            action: input.action,
            target_id: input.target_id,
            reason: input.reason,
            session_id: session.session_id,
            connection_generation: session.connection_generation,
            generation: snapshot.generation,
            displayed_revision: snapshot.revision,
            snapshot_digest: snapshot.semantic_digest,
        };
        let (prior, new) = self.ledger.reserve(request.clone(), (self.clock)())?;
        if !new {
            return Ok(prior);
        }
        let admission = self
            .ledger
            .find(&request.operation_id)
            .ok_or_else(|| ControlError::new(ErrorCode::InvalidInput))?
            .admitted_record
            .clone();
        match self.recovery.prepare(&request.operation_id, &admission) {
            Ok(Preparation::New) => {}
            Ok(Preparation::ExistingNeedsRecovery) => {
                return self.ledger.mark_active(
                    &request.operation_id,
                    OperationStatus::Indeterminate,
                    None,
                    (self.clock)(),
                );
            }
            Err(error) => {
                self.storage_error = true;
                self.ledger.mark_active(
                    &request.operation_id,
                    OperationStatus::Indeterminate,
                    None,
                    (self.clock)(),
                )?;
                return Err(error);
            }
        }
        // Persistence may block. Recheck expiry immediately before transport admission.
        if let Err(error) = self.session_for(method.permission()) {
            self.cleanup_rejected(&request.operation_id, &admission);
            return Err(error);
        }
        let response = self.transport.request(method.as_str(), &encoded(&request)?);
        let result =
            response.and_then(|value| contract::validate_acknowledgement(&request, &value));
        match result {
            Ok(ack) => self.ledger.mark_active(
                &request.operation_id,
                ack.status,
                Some(ack.audit_trace_id),
                (self.clock)(),
            ),
            Err(error) => {
                self.error_authority(&error);
                if rejects(&error) {
                    self.cleanup_rejected(&request.operation_id, &admission);
                    Err(error)
                } else {
                    self.ledger.mark_active(
                        &request.operation_id,
                        OperationStatus::Indeterminate,
                        None,
                        (self.clock)(),
                    )?;
                    Err(ControlError {
                        code: ErrorCode::AmbiguousSubmission,
                        request_dispatched: Some(true),
                    })
                }
            }
        }
    }
    fn cleanup_rejected(&mut self, id: &str, admission: &Value) {
        if self.recovery.complete(id, admission).is_ok() {
            self.ledger.pending.remove(id);
        } else {
            self.storage_error = true;
            let _ =
                self.ledger
                    .mark_active(id, OperationStatus::Indeterminate, None, (self.clock)());
        }
    }
    pub fn recover_operation(&mut self, id: &str) -> Result<OperationView> {
        let session = self.session_for(Permission::Read)?;
        let record = self
            .ledger
            .find(id)
            .ok_or_else(|| ControlError::new(ErrorCode::InvalidInput))?
            .clone();
        if record.state == OperationState::Terminal {
            return Ok(record.view());
        }
        let result=self.transport.lookup(&json!({"sessionId":session.session_id,"connectionGeneration":session.connection_generation,
            "operationId":id,"semanticDigest":record.request.semantic_digest}));
        let raw = match result {
            Ok(raw) => raw,
            Err(error) => {
                self.error_authority(&error);
                return Err(error);
            }
        };
        crate::canonical::canonical_json(&raw)?;
        match raw.get("found").and_then(Value::as_bool) {
            Some(false) => {
                if record.audit_trace_id.is_some() {
                    return Err(ControlError::new(ErrorCode::AckMismatch));
                }
                return self.ledger.mark_active(
                    id,
                    OperationStatus::Indeterminate,
                    None,
                    (self.clock)(),
                );
            }
            Some(true) => {}
            None => return Err(ControlError::new(ErrorCode::InvalidInput)),
        }
        if raw["operationId"].as_str() != Some(id)
            || raw["semanticDigest"].as_str() != Some(&record.request.semantic_digest)
        {
            return Err(ControlError::new(ErrorCode::AckMismatch));
        }
        let status: OperationStatus = serde_json::from_value(raw["status"].clone())
            .map_err(|_| ControlError::new(ErrorCode::InvalidInput))?;
        let audit = contract::validate_audit_trace(
            record.audit_trace_id.as_deref(),
            raw["auditTraceId"].as_str(),
        )?
        .to_owned();
        if status.is_terminal() {
            let outcome_digest = match raw.get("outcomeDigest") {
                None | Some(Value::Null) => None,
                Some(Value::String(value)) => Some(value.clone()),
                Some(_) => return Err(ControlError::new(ErrorCode::InvalidInput)),
            };
            let observation = Observation {
                operation_id: id.into(),
                semantic_digest: record.request.semantic_digest,
                status,
                terminal_observed: true,
                audit_trace_id: Some(audit),
                outcome_digest,
            };
            let view = self.ledger.reconcile(observation, (self.clock)())?;
            // Terminal truth is retained even when local cleanup fails.
            if self.recovery.complete(id, &record.admitted_record).is_err() {
                self.storage_error = true;
            } else {
                self.ledger.prune_completed(id);
            }
            Ok(view)
        } else {
            self.ledger
                .mark_active(id, status, Some(audit), (self.clock)())
        }
    }
    pub fn recover_pending(&mut self, limit: usize) -> Result<Vec<OperationView>> {
        self.session_for(Permission::Read)?;
        let selected =
            self.recovery_schedule
                .select(&self.ledger.pending_views(), (self.clock)(), limit)?;
        let mut results = Vec::new();
        for id in selected {
            let outcome = self.recover_operation(&id);
            self.recovery_schedule.record(
                &id,
                (self.clock)(),
                outcome
                    .as_ref()
                    .is_ok_and(|view| view.state == OperationState::Terminal),
            )?;
            match outcome {
                Ok(view) => results.push(view),
                Err(error) => {
                    if self.session.is_none() {
                        return Err(error);
                    }
                }
            }
        }
        Ok(results)
    }
    pub fn cleanup_terminal(&mut self, limit: usize) -> Result<usize> {
        if limit == 0 || limit > 32 {
            return Err(ControlError::new(ErrorCode::InvalidInput));
        }
        let identity = self.session_for(Permission::Read)?.identity_id;
        let mut ids: Vec<_> = self
            .ledger
            .completed
            .iter()
            .filter(|(_, record)| record.identity_id == identity && !record.cleanup_complete)
            .map(|(id, _)| id.clone())
            .collect();
        let start = self
            .cleanup_cursor
            .as_ref()
            .and_then(|cursor| ids.iter().position(|id| id > cursor))
            .unwrap_or(0);
        ids.rotate_left(start);
        ids.truncate(limit);
        if let Some(last) = ids.last() {
            self.cleanup_cursor = Some(last.clone());
        }
        let candidates: Vec<_> = ids
            .into_iter()
            .filter_map(|id| {
                self.ledger
                    .completed
                    .get(&id)
                    .map(|record| (id, record.admitted_record.clone()))
            })
            .collect();
        let mut failure = None;
        for (id, value) in &candidates {
            match self.recovery.complete(id, value) {
                Ok(()) => self.ledger.prune_completed(id),
                Err(error) => {
                    failure.get_or_insert(error);
                }
            }
        }
        self.storage_error = self
            .ledger
            .completed
            .values()
            .any(|record| record.identity_id == identity && !record.cleanup_complete);
        if let Some(error) = failure {
            return Err(error);
        }
        Ok(candidates.len())
    }
}
