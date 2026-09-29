impl DurableInferenceControl {
    fn assert_native_recovery_plan_identity(
        &self,
        request_id: &str,
        plan: &crate::recovery_contracts::RecoveryExecutionPlan,
    ) -> Result<(), Error> {
        let record = self
            .native
            .records
            .get(request_id)
            .ok_or(Error::RequestNotFound)?;
        let binding = record
            .execution_binding
            .as_ref()
            .ok_or(Error::InvalidIdentity("native execution binding"))?;
        if record.request.request_id != plan.request_id()
            || record.request.principal_id != plan.principal_id()
            || record.request.model != plan.model_id()
            || record.request.worker_generation != plan.worker_generation()
            || binding.authority_epoch != plan.execution_authority_epoch()
            || binding.bundle_digest != plan.bundle_digest()
            || binding.manifest_digest != plan.manifest_digest()
            || binding.quota_lease_digest != plan.quota_lease_digest()
            || binding.resource_lease_digest != plan.resource_lease_digest()
            || binding.output_policy_digest != plan.output_policy_digest()
            || binding.execution_binding_digest != plan.execution_binding_digest()
            || binding.provider_id != plan.provider_id()
            || binding.model_id != plan.model_id()
            || binding.model_digest != plan.model_digest()
            || binding.worker_id != plan.worker_id()
            || binding.worker_generation != plan.worker_generation()
        {
            return Err(Error::AssignmentMismatch);
        }
        Ok(())
    }

    /// Apply fresh signed terminal/usage evidence to a historical execution.
    /// The original dispatch lease may have expired, but every historical
    /// identity and the current receipt signature is re-verified before this
    /// method is called. The durable pre-effect quota remains authoritative for
    /// settlement even after its dispatch window expires.
    pub fn reconcile_native_recovery(
        &mut self,
        request_id: &str,
        plan: &crate::recovery_contracts::RecoveryExecutionPlan,
        verified: &crate::recovery_contracts::VerifiedRecoveryReconciliationReceipt,
    ) -> Result<NativeRunRecord, Error> {
        self.assert_native_recovery_plan_identity(request_id, plan)?;
        let record = self
            .native
            .records
            .get(request_id)
            .ok_or(Error::RequestNotFound)?;
        if !matches!(
            record.state,
            NativeReservationState::Dispatching
                | NativeReservationState::Running
                | NativeReservationState::Cancelling
                | NativeReservationState::Indeterminate
        ) || record.dispatch_rejection.is_some()
        {
            return Err(Error::InvalidTransition);
        }
        let binding = record
            .execution_binding
            .as_ref()
            .ok_or(Error::InvalidIdentity("native execution binding"))?;
        let dispatch = record.dispatch.as_ref().ok_or(Error::AssignmentMismatch)?;
        let dispatch_digest = native_dispatch_digest(dispatch)?;
        let receipt = verified.receipt();
        if receipt.request_id != request_id
            || receipt.principal_id != record.request.principal_id
            || receipt.execution_binding_digest != plan.execution_binding_digest()
            || receipt.dispatch_digest != dispatch_digest
            || receipt.thread_id != dispatch.thread_id
            || receipt.provider_id != dispatch.model_provider
            || receipt.model_digest != plan.model_digest()
            || receipt.execution_authority_epoch != plan.execution_authority_epoch()
            || receipt
                .observed_output_tokens
                .is_some_and(|value| value > binding.maximum_output_tokens)
            || receipt
                .usage_microunits
                .is_some_and(|value| value > binding.maximum_cost_microunits)
        {
            return Err(Error::AssignmentMismatch);
        }
        if let Some(previous) = &record.reconciliation
            && receipt.terminal_sequence <= previous.terminal_sequence
        {
            return if previous.receipt_digest == verified.receipt_digest() {
                Ok(record.clone())
            } else {
                Err(Error::Conflict)
            };
        }
        let (status, boundary_status) = match receipt.terminal_status {
            ReconciledTerminalStatus::Completed => {
                (NativeRunStatus::Completed, NativeBoundaryStatus::Succeeded)
            }
            ReconciledTerminalStatus::Failed => {
                (NativeRunStatus::Failed, NativeBoundaryStatus::Failed)
            }
            ReconciledTerminalStatus::Interrupted => (
                NativeRunStatus::Interrupted,
                NativeBoundaryStatus::Interrupted,
            ),
        };
        let output = NativeRunOutput {
            thread_id: receipt.thread_id.clone(),
            turn_id: receipt.turn_id.clone(),
            model: record.request.model.clone(),
            model_provider: receipt.provider_id.clone(),
            status,
            boundary_status,
            output: receipt
                .output_digest
                .as_ref()
                .map(|digest| format!("hepta-reconciled-output-v1:{digest}"))
                .unwrap_or_default(),
            observed_output_tokens: receipt.observed_output_tokens,
            terminal_observed: true,
            stop_reason: None,
            owner_authority: NativeOwnerAuthority::ObservedReady,
            codex_terminal_correlation_digest: Some(verified.receipt_digest().to_string()),
        };
        let audit = NativeReconciliationAudit {
            receipt_digest: verified.receipt_digest().to_string(),
            authenticated_key_id: verified.authenticated_key_id().to_string(),
            terminal_sequence: receipt.terminal_sequence,
            usage_microunits: receipt.usage_microunits,
            output_digest: receipt.output_digest.clone(),
            encrypted_output_reference: receipt.encrypted_output_reference.clone(),
        };
        self.commit_native(
            request_id,
            Event::Reconcile {
                request_id: request_id.to_string(),
                output,
                audit,
            },
        )
    }

    /// Release a historical indeterminate execution only with a fresh,
    /// revision-bound, two-person retirement approval.
    pub fn retire_native_indeterminate_recovery(
        &mut self,
        request_id: &str,
        plan: &crate::recovery_contracts::RecoveryExecutionPlan,
        verified: &crate::recovery_contracts::VerifiedRecoveryRetirement,
    ) -> Result<NativeRunRecord, Error> {
        self.assert_native_recovery_plan_identity(request_id, plan)?;
        let record = self
            .native
            .records
            .get(request_id)
            .ok_or(Error::RequestNotFound)?;
        let dispatch = record.dispatch.as_ref().ok_or(Error::AssignmentMismatch)?;
        let retirement = verified.retirement();
        if record.state != NativeReservationState::Indeterminate
            || record.retirement.is_some()
            || retirement.request_id != request_id
            || retirement.principal_id != record.request.principal_id
            || retirement.record_revision != record.revision
            || retirement.dispatch_digest != native_dispatch_digest(dispatch)?
            || retirement.execution_binding_digest != plan.execution_binding_digest()
            || retirement.execution_authority_epoch != plan.execution_authority_epoch()
        {
            return Err(Error::InvalidTransition);
        }
        let audit = NativeRetirementAudit {
            retirement_digest: verified.retirement_digest().to_string(),
            operator_ids: [
                verified.operator_ids()[0].clone(),
                verified.operator_ids()[1].clone(),
            ],
            key_ids: [
                verified.key_ids()[0].clone(),
                verified.key_ids()[1].clone(),
            ],
            reason_code: retirement.reason_code.clone(),
            reason: retirement.reason.clone(),
        };
        self.commit_native(
            request_id,
            Event::Retire {
                request_id: request_id.to_string(),
                audit,
            },
        )
    }
}
