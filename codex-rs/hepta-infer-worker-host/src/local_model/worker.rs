pub struct ExperimentalLocalModelWorker<D: LocalModelDriver> {
    worker_id: String,
    generation: u64,
    maximum_in_flight: usize,
    driver: D,
    control: Mutex<DurableInferenceControl>,
    resources: ResourceManager,
    models: Mutex<BTreeMap<String, LoadedModel>>,
}

impl<D: LocalModelDriver> ExperimentalLocalModelWorker<D> {
    pub fn new(
        worker_id: String,
        generation: u64,
        maximum_in_flight: usize,
        driver: D,
        control: DurableInferenceControl,
        resources: ResourceManager,
    ) -> Result<Self, LocalModelError> {
        validate_identifier(&worker_id, "worker")?;
        if generation == 0 || maximum_in_flight == 0 || maximum_in_flight > 256 {
            return Err(LocalModelError::InvalidGrant("worker configuration"));
        }
        Ok(Self {
            worker_id,
            generation,
            maximum_in_flight,
            driver,
            control: Mutex::new(control),
            resources,
            models: Mutex::new(BTreeMap::new()),
        })
    }

    pub async fn load_model(
        &self,
        operation: OperationId,
        manifest: VerifiedModelManifest,
        grant: &VerifiedResourceGrant,
        cancellation: &CancellationToken,
        deadline: TrustedDeadline,
    ) -> Result<AttestedModelHandle, LocalModelError> {
        grant.revalidate(&self.worker_id, self.generation)?;
        deadline.ensure_live()?;
        let request_id = format!("local-load:{}", operation.as_str());
        let payload = digest(
            &[
                manifest.envelope.manifest_digest.as_bytes(),
                grant.witness_digest().as_bytes(),
                &deadline.unix_ms().to_be_bytes(),
            ]
            .concat(),
        );
        let record = self.reserve(&request_id, &manifest.envelope.model_id, payload)?;
        if record.state != NativeReservationState::Reserved {
            return self
                .models
                .lock()
                .map_err(|_| LocalModelError::StatePoisoned)?
                .get(&manifest.envelope.model_id)
                .map(|loaded| loaded.handle.clone())
                .ok_or(LocalModelError::ReconciliationRequired);
        }
        if cancellation.is_cancelled() {
            self.stop_before_dispatch(&request_id, "cancelled before local load")?;
            return Err(LocalModelError::Cancelled);
        }
        let reservation = match self.resources.reserve_load(
            &manifest.envelope.model_id,
            manifest.envelope.maximum_memory_bytes,
        ) {
            Ok(value) => value,
            Err(error) => {
                self.stop_before_dispatch(&request_id, "local load resource admission failed")?;
                return Err(error);
            }
        };
        self.dispatch(
            &request_id,
            operation.as_str(),
            &manifest.envelope.manifest_digest,
            grant.witness_digest(),
        )?;
        match self
            .driver
            .load(&operation, &manifest, grant, cancellation, deadline)
            .await
        {
            Ok(unverified) => {
                let handle = match AttestedModelHandle::verify(unverified, &manifest, grant) {
                    Ok(handle) => handle,
                    Err(error) => {
                        reservation.quarantine()?;
                        return Err(error);
                    }
                };
                reservation.commit(handle.observed_memory_bytes)?;
                self.models
                    .lock()
                    .map_err(|_| LocalModelError::StatePoisoned)?
                    .insert(
                        manifest.envelope.model_id.clone(),
                        LoadedModel {
                            handle: handle.clone(),
                        },
                    );
                self.settle(
                    &request_id,
                    operation.as_str(),
                    &manifest.envelope.model_id,
                    LocalExecutionStatus::Succeeded,
                    Some(handle.attestation_digest.clone()),
                    None,
                    true,
                )?;
                Ok(handle)
            }
            Err(DriverError::Rejected(reason)) => {
                self.settle(
                    &request_id,
                    operation.as_str(),
                    &manifest.envelope.model_id,
                    LocalExecutionStatus::Failed,
                    None,
                    None,
                    true,
                )?;
                Err(LocalModelError::DriverRejected(reason))
            }
            Err(DriverError::Indeterminate(reason)) => {
                reservation.quarantine()?;
                self.settle(
                    &request_id,
                    operation.as_str(),
                    &manifest.envelope.model_id,
                    LocalExecutionStatus::Indeterminate,
                    None,
                    None,
                    false,
                )?;
                Err(LocalModelError::DriverIndeterminate(reason))
            }
        }
    }

    pub async fn run(
        &self,
        operation: OperationId,
        model_id: &str,
        input: VerifiedInput,
        grant: &VerifiedResourceGrant,
        cancellation: &CancellationToken,
        deadline: TrustedDeadline,
    ) -> Result<LocalExecutionObservation, LocalModelError> {
        grant.revalidate(&self.worker_id, self.generation)?;
        deadline.ensure_live()?;
        if grant.claims.model_id != model_id
            || input.maximum_tokens > grant.claims.maximum_tokens_per_request
        {
            return Err(LocalModelError::InputBinding);
        }
        let handle = self
            .models
            .lock()
            .map_err(|_| LocalModelError::StatePoisoned)?
            .get(model_id)
            .map(|loaded| loaded.handle.clone())
            .ok_or(LocalModelError::ModelNotLoaded)?;
        if handle.model_id != model_id
            || handle.model_digest != grant.claims.model_digest
            || handle.device_id != grant.claims.device_id
        {
            return Err(LocalModelError::DriverAttestation);
        }
        let request_id = format!("local-run:{}", operation.as_str());
        let payload = digest(
            &[
                input.digest.as_bytes(),
                grant.witness_digest().as_bytes(),
                handle.attestation_digest.as_bytes(),
                &input.maximum_tokens.to_be_bytes(),
                &deadline.unix_ms().to_be_bytes(),
            ]
            .concat(),
        );
        let record = self.reserve(&request_id, model_id, payload)?;
        if record.state != NativeReservationState::Reserved {
            if let Some(output) = record.observation {
                return local_observation(&operation, &output);
            }
            return self.reconcile_run(&operation, &request_id, model_id).await;
        }
        if cancellation.is_cancelled() {
            self.stop_before_dispatch(&request_id, "cancelled before local inference")?;
            return Err(LocalModelError::Cancelled);
        }
        let transient = u64::try_from(input.bytes.len())
            .map_err(|_| LocalModelError::ArithmeticOverflow)?;
        let _run_reservation = match self.resources.reserve_run(transient) {
            Ok(value) => value,
            Err(error) => {
                self.stop_before_dispatch(&request_id, "local run resource admission failed")?;
                return Err(error);
            }
        };
        self.dispatch(
            &request_id,
            operation.as_str(),
            input.digest(),
            grant.witness_digest(),
        )?;
        match self
            .driver
            .run(&operation, &handle, input, cancellation, deadline)
            .await
        {
            Ok(observed) => self.commit_run(&operation, &request_id, model_id, observed),
            Err(DriverError::Rejected(reason)) => {
                let observed = self.settle(
                    &request_id,
                    operation.as_str(),
                    model_id,
                    LocalExecutionStatus::Failed,
                    None,
                    None,
                    true,
                )?;
                Err(LocalModelError::DriverRejected(format!(
                    "{reason}; terminal={:?}",
                    observed.status
                )))
            }
            Err(DriverError::Indeterminate(reason)) => {
                self.resources.observe_usage(None)?;
                self.settle(
                    &request_id,
                    operation.as_str(),
                    model_id,
                    LocalExecutionStatus::Indeterminate,
                    None,
                    None,
                    false,
                )?;
                Err(LocalModelError::DriverIndeterminate(reason))
            }
        }
    }

    pub async fn unload_model(
        &self,
        operation: OperationId,
        model_id: &str,
        grant: &VerifiedResourceGrant,
        cancellation: &CancellationToken,
        deadline: TrustedDeadline,
    ) -> Result<(), LocalModelError> {
        grant.revalidate(&self.worker_id, self.generation)?;
        deadline.ensure_live()?;
        let handle = self
            .models
            .lock()
            .map_err(|_| LocalModelError::StatePoisoned)?
            .get(model_id)
            .map(|loaded| loaded.handle.clone())
            .ok_or(LocalModelError::ModelNotLoaded)?;
        let request_id = format!("local-unload:{}", operation.as_str());
        let payload = digest(
            &[
                handle.attestation_digest.as_bytes(),
                grant.witness_digest().as_bytes(),
                &deadline.unix_ms().to_be_bytes(),
            ]
            .concat(),
        );
        let record = self.reserve(&request_id, model_id, payload)?;
        if record.state != NativeReservationState::Reserved {
            return if record
                .observation
                .as_ref()
                .is_some_and(|value| value.terminal_observed)
            {
                Ok(())
            } else {
                Err(LocalModelError::ReconciliationRequired)
            };
        }
        let unload = match self.resources.begin_unload(model_id) {
            Ok(value) => value,
            Err(error) => {
                self.stop_before_dispatch(&request_id, "local unload admission failed")?;
                return Err(error);
            }
        };
        self.dispatch(
            &request_id,
            operation.as_str(),
            &handle.attestation_digest,
            grant.witness_digest(),
        )?;
        match self
            .driver
            .unload(&operation, &handle, cancellation, deadline)
            .await
        {
            Ok(observed)
                if observed.terminal_observed
                    && observed.opaque_id == handle.opaque_id
                    && observed.released_memory_bytes == handle.observed_memory_bytes =>
            {
                validate_digest(&observed.attestation_digest, "unload attestation")?;
                unload.complete(observed.released_memory_bytes)?;
                self.models
                    .lock()
                    .map_err(|_| LocalModelError::StatePoisoned)?
                    .remove(model_id);
                self.settle(
                    &request_id,
                    operation.as_str(),
                    model_id,
                    LocalExecutionStatus::Succeeded,
                    Some(observed.attestation_digest),
                    None,
                    true,
                )?;
                Ok(())
            }
            Ok(_) | Err(DriverError::Indeterminate(_)) => {
                unload.quarantine()?;
                self.settle(
                    &request_id,
                    operation.as_str(),
                    model_id,
                    LocalExecutionStatus::Indeterminate,
                    None,
                    None,
                    false,
                )?;
                Err(LocalModelError::ReconciliationRequired)
            }
            Err(DriverError::Rejected(reason)) => {
                drop(unload);
                Err(LocalModelError::DriverRejected(reason))
            }
        }
    }

    async fn reconcile_run(
        &self,
        operation: &OperationId,
        request_id: &str,
        model_id: &str,
    ) -> Result<LocalExecutionObservation, LocalModelError> {
        match self
            .driver
            .inspect(operation)
            .await
            .map_err(map_driver_error)?
        {
            DriverReconciliation::Run(observed) => {
                self.commit_run(operation, request_id, model_id, observed)
            }
            DriverReconciliation::Unknown | DriverReconciliation::Unload(_) => {
                Err(LocalModelError::ReconciliationRequired)
            }
        }
    }

    fn commit_run(
        &self,
        operation: &OperationId,
        request_id: &str,
        model_id: &str,
        observed: DriverRunObservation,
    ) -> Result<LocalExecutionObservation, LocalModelError> {
        validate_digest(&observed.attestation_digest, "run attestation")?;
        if observed.observed_memory_bytes > self.resources.lock()?.maximum_memory {
            self.resources.fence_generation()?;
            return Err(LocalModelError::DriverAttestation);
        }
        if let Some(output) = &observed.output_digest {
            validate_digest(output, "output")?;
        }
        if observed.terminal_observed
            && observed.status == DriverTerminalStatus::Succeeded
            && observed.output_digest.is_none()
        {
            return Err(LocalModelError::DriverAttestation);
        }
        self.resources
            .observe_usage(observed.observed_usage_tokens)?;
        let status = if !observed.terminal_observed {
            LocalExecutionStatus::Indeterminate
        } else {
            match observed.status {
                DriverTerminalStatus::Succeeded => LocalExecutionStatus::Succeeded,
                DriverTerminalStatus::Failed => LocalExecutionStatus::Failed,
                DriverTerminalStatus::Cancelled => LocalExecutionStatus::Cancelled,
            }
        };
        self.settle(
            request_id,
            operation.as_str(),
            model_id,
            status,
            observed.output_digest,
            observed.observed_usage_tokens,
            observed.terminal_observed,
        )
    }

    fn reserve(
        &self,
        request_id: &str,
        model_id: &str,
        payload_digest: String,
    ) -> Result<codex_hepta_infer_core::durable_control::native::NativeRunRecord, LocalModelError>
    {
        self.control
            .lock()
            .map_err(|_| LocalModelError::StatePoisoned)?
            .reserve_native(
                NativeRequest {
                    request_id: request_id.to_string(),
                    principal_id: self.worker_id.clone(),
                    worker_generation: self.generation,
                    model: model_id.to_string(),
                    payload_digest,
                },
                self.maximum_in_flight,
            )
            .map_err(LocalModelError::Journal)
    }

    fn dispatch(
        &self,
        request_id: &str,
        operation_id: &str,
        context_digest: &str,
        grant_witness: &str,
    ) -> Result<(), LocalModelError> {
        self.control
            .lock()
            .map_err(|_| LocalModelError::StatePoisoned)?
            .dispatch_native(
                request_id,
                NativeDispatch {
                    thread_id: operation_id.to_string(),
                    model_provider: LOCAL_PROVIDER.to_string(),
                    context_digest: context_digest.to_string(),
                    owner_context_digest: Some(grant_witness.to_string()),
                    codex_payload_digest: None,
                    codex_request_digest: None,
                    app_server_version: None,
                    protocol_id: None,
                    codex_source_admission_digest: None,
                    codex_home_digest: None,
                    codex_connection_id: None,
                    codex_session_id: None,
                    codex_deadline_ms: None,
                    codex_authority_epoch: None,
                    codex_revocation_revision: None,
                    codex_revocation_head_sha256: None,
                    codex_authority_witness_sha256: None,
                },
            )
            .map(|_| ())
            .map_err(LocalModelError::Journal)
    }

    fn stop_before_dispatch(&self, request_id: &str, reason: &str) -> Result<(), LocalModelError> {
        self.control
            .lock()
            .map_err(|_| LocalModelError::StatePoisoned)?
            .stop_native_before_dispatch(request_id, reason.to_string())
            .map(|_| ())
            .map_err(LocalModelError::Journal)
    }

    #[allow(clippy::too_many_arguments)]
    fn settle(
        &self,
        request_id: &str,
        operation_id: &str,
        model_id: &str,
        status: LocalExecutionStatus,
        output_digest: Option<String>,
        usage: Option<u64>,
        terminal: bool,
    ) -> Result<LocalExecutionObservation, LocalModelError> {
        let native_status = match status {
            LocalExecutionStatus::Succeeded => NativeRunStatus::Completed,
            LocalExecutionStatus::Failed => NativeRunStatus::Failed,
            LocalExecutionStatus::Cancelled => NativeRunStatus::Interrupted,
            LocalExecutionStatus::Indeterminate => NativeRunStatus::Indeterminate,
        };
        let boundary = match status {
            LocalExecutionStatus::Succeeded => NativeBoundaryStatus::Succeeded,
            LocalExecutionStatus::Failed => NativeBoundaryStatus::Failed,
            LocalExecutionStatus::Cancelled => NativeBoundaryStatus::Cancelled,
            LocalExecutionStatus::Indeterminate => NativeBoundaryStatus::Indeterminate,
        };
        let output = NativeRunOutput {
            thread_id: operation_id.to_string(),
            turn_id: if terminal {
                format!("terminal-{operation_id}")
            } else {
                String::new()
            },
            model: model_id.to_string(),
            model_provider: LOCAL_PROVIDER.to_string(),
            status: native_status,
            boundary_status: boundary,
            output: output_digest.clone().unwrap_or_default(),
            observed_output_tokens: usage,
            terminal_observed: terminal,
            stop_reason: if terminal {
                None
            } else {
                Some("local driver terminality unknown; inspect only, do not replay".to_string())
            },
            owner_authority: NativeOwnerAuthority::Unverified,
            codex_terminal_correlation_digest: None,
        };
        let record = self
            .control
            .lock()
            .map_err(|_| LocalModelError::StatePoisoned)?
            .settle_native(request_id, output)
            .map_err(LocalModelError::Journal)?;
        local_observation(
            &OperationId(operation_id.to_string()),
            record
                .observation
                .as_ref()
                .ok_or(LocalModelError::ReconciliationRequired)?,
        )
    }
}
