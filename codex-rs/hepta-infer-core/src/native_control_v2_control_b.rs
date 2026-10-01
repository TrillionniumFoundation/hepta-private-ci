impl DurableInferenceControl {
    /// Compatibility port for historical trusted-host callers. New production
    /// callers use `settle_native_authorized` or signed reconciliation.
    pub fn settle_native(
        &mut self,
        request_id: &str,
        output: NativeRunOutput,
    ) -> Result<NativeRunRecord, Error> {
        self.ensure_native_writer_available()?;
        let record = self
            .native
            .records
            .get(request_id)
            .ok_or(Error::RequestNotFound)?;
        if record.observation.as_ref() == Some(&output) {
            return Ok(record.clone());
        }
        self.commit_native(
            request_id,
            Event::Observe {
                request_id: request_id.to_string(),
                output,
                protected_output: None,
            },
        )
    }

    /// Production settlement stores only a protected-output marker and metadata.
    /// Dispatch expiry prevents a new external effect, but cannot erase terminal
    /// truth for an effect which already crossed the boundary. Settlement still
    /// requires the exact previously bound plan identity and live data policy.
    /// A non-terminal observation with no output has no data object to encrypt;
    /// its absence is persisted explicitly rather than fabricating ciphertext.
    pub fn settle_native_authorized(
        &mut self,
        request_id: &str,
        plan: &VerifiedExecutionPlan,
        now_unix_ms: u64,
        mut output: NativeRunOutput,
        protected_output: Option<ProtectedOutput>,
    ) -> Result<NativeRunRecord, Error> {
        self.ensure_native_writer_available()?;
        self.assert_native_plan_identity(request_id, plan)?;
        let protected = if output.output.is_empty() && !output.terminal_observed {
            None
        } else {
            let protected = match plan.output_policy().storage_mode {
                OutputStorageMode::DigestOnly => ProtectedOutput::digest_only(
                    now_unix_ms,
                    plan.output_policy(),
                    output.output.as_bytes(),
                )
                .map_err(|_| Error::InvalidIdentity("native output policy"))?,
                OutputStorageMode::ExternalEncrypted => protected_output
                    .ok_or(Error::InvalidIdentity("native encrypted output reference"))?,
            };
            protected
                .assert_matches_policy(now_unix_ms, plan.output_policy())
                .map_err(|_| Error::InvalidIdentity("native protected output policy"))?;
            if protected.output_digest
                != sha256_hex(
                    b"hepta.inference-control.output.v1\0",
                    output.output.as_bytes(),
                )
                || protected.delete_after_unix_ms != plan.output_policy().delete_after_unix_ms
                || protected.classification != plan.output_policy().classification
                || protected.storage_mode != plan.output_policy().storage_mode
            {
                return Err(Error::AssignmentMismatch);
            }
            output.output = protected
                .journal_marker()
                .map_err(|_| Error::InvalidIdentity("native protected output"))?;
            Some(protected)
        };
        self.commit_native(
            request_id,
            Event::Observe {
                request_id: request_id.to_string(),
                output,
                protected_output: protected,
            },
        )
    }

    /// Apply independently signed terminal evidence and monotonic usage
    /// refinements. Actual usage above the pre-effect quota quarantines success
    /// qualification without erasing terminal truth or authorizing excess pay.
    pub fn reconcile_native(
        &mut self,
        request_id: &str,
        plan: &VerifiedExecutionPlan,
        now_unix_ms: u64,
        verified: &VerifiedReconciliationReceipt,
    ) -> Result<NativeRunRecord, Error> {
        self.ensure_native_writer_available()?;
        verified
            .assert_valid_at(now_unix_ms)
            .map_err(|_| Error::InvalidTime)?;
        self.assert_native_plan_identity(request_id, plan)?;
        let record = self
            .native
            .records
            .get(request_id)
            .ok_or(Error::RequestNotFound)?;
        let dispatch = record.dispatch.as_ref().ok_or(Error::AssignmentMismatch)?;
        let dispatch_digest = native_dispatch_digest(dispatch)?;
        let receipt = verified.receipt();
        if receipt.request_id != request_id
            || receipt.dispatch_digest != dispatch_digest
            || receipt.thread_id != dispatch.thread_id
            || receipt.provider_id != dispatch.model_provider
            || receipt.execution_binding_digest != plan.execution_binding_digest()
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
        let output_marker = receipt
            .output_digest
            .as_ref()
            .map(|digest| format!("hepta-reconciled-output-v1:{digest}"))
            .unwrap_or_default();
        let output = NativeRunOutput {
            thread_id: receipt.thread_id.clone(),
            turn_id: receipt.turn_id.clone(),
            model: record.request.model.clone(),
            model_provider: receipt.provider_id.clone(),
            status,
            boundary_status,
            output: output_marker,
            observed_output_tokens: receipt.observed_output_tokens,
            terminal_observed: true,
            stop_reason: None,
            owner_authority: record
                .observation
                .as_ref()
                .map_or(NativeOwnerAuthority::Unverified, |previous| {
                    previous.owner_authority.clone()
                }),
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

    /// Release an unreconciled execution only with a revision-bound, signed
    /// two-person retirement.
    pub fn retire_native_indeterminate(
        &mut self,
        request_id: &str,
        plan: &VerifiedExecutionPlan,
        now_unix_ms: u64,
        verified: &VerifiedRetirement,
    ) -> Result<NativeRunRecord, Error> {
        self.ensure_native_writer_available()?;
        verified
            .assert_valid_at(now_unix_ms)
            .map_err(|_| Error::InvalidTime)?;
        self.assert_native_plan_identity(request_id, plan)?;
        let record = self
            .native
            .records
            .get(request_id)
            .ok_or(Error::RequestNotFound)?;
        let dispatch = record.dispatch.as_ref().ok_or(Error::AssignmentMismatch)?;
        let retirement = verified.retirement();
        if record.state != NativeReservationState::Indeterminate
            || retirement.request_id != request_id
            || retirement.record_revision != record.revision
            || retirement.dispatch_digest != native_dispatch_digest(dispatch)?
            || retirement.execution_binding_digest != plan.execution_binding_digest()
        {
            return Err(Error::InvalidTransition);
        }
        let audit = NativeRetirementAudit {
            retirement_digest: verified.retirement_digest().to_string(),
            operator_ids: [
                verified.operator_ids()[0].clone(),
                verified.operator_ids()[1].clone(),
            ],
            key_ids: [verified.key_ids()[0].clone(), verified.key_ids()[1].clone()],
            independent_operator_key_digests: Some(verified.key_fingerprints().clone()),
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

    pub fn native_record(&self, request_id: &str) -> Option<&NativeRunRecord> {
        self.native.records.get(request_id)
    }

    pub fn native_metrics(&self, now_unix_ms: u64) -> NativeControlMetrics {
        let mut metrics = NativeControlMetrics {
            journal_bytes: self.journal_bytes,
            checkpoint_generation: self.native.checkpoint_generation,
            reserved: 0,
            dispatching: 0,
            running: 0,
            cancelling: 0,
            indeterminate: 0,
            released: 0,
            protected_outputs: 0,
            expired_output_references: 0,
        };
        for record in self.native.records.values() {
            match record.state {
                NativeReservationState::Reserved => metrics.reserved += 1,
                NativeReservationState::Dispatching => metrics.dispatching += 1,
                NativeReservationState::Running => metrics.running += 1,
                NativeReservationState::Cancelling => metrics.cancelling += 1,
                NativeReservationState::Indeterminate => metrics.indeterminate += 1,
                NativeReservationState::Released => metrics.released += 1,
            }
            if let Some(output) = &record.protected_output {
                metrics.protected_outputs += 1;
                if output.delete_after_unix_ms <= now_unix_ms
                    && output.encrypted_reference.is_some()
                {
                    metrics.expired_output_references += 1;
                }
            }
        }
        metrics
    }

    /// Atomically archive the complete predecessor stream and install a
    /// content-addressed checkpoint reference.
    pub fn compact_native_journal(&mut self) -> Result<NativeMaintenanceReceipt, Error> {
        self.ensure_native_writer_available()?;
        let now_unix_ms = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| Error::InvalidTime)?
            .as_millis()
            .try_into()
            .map_err(|_| Error::ArithmeticOverflow)?;
        self.compact_native_journal_with_failpoint(now_unix_ms, &mut NoMaintenanceFailpoint)
    }

    /// Deterministic maintenance entrypoint used by kill/fault qualification.
    pub fn compact_native_journal_with_failpoint(
        &mut self,
        now_unix_ms: u64,
        failpoint: &mut dyn NativeMaintenanceFailpoint,
    ) -> Result<NativeMaintenanceReceipt, Error> {
        if self.poisoned {
            return Err(Error::WriterUnavailable);
        }
        let result = self.compact_native_journal_inner(now_unix_ms, failpoint);
        if matches!(
            result,
            Err(Error::Io(_)) | Err(Error::WriterUnavailable) | Err(Error::CorruptJournal(_))
        ) {
            self.poisoned = true;
        }
        result
    }
}
