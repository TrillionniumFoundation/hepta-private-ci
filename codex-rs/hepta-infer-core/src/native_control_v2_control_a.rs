impl DurableInferenceControl {
    /// The first admission pins the local slot limit for this journal. A
    /// duplicate binds every request field and never reserves a second slot.
    pub fn reserve_native(
        &mut self,
        request: NativeRequest,
        maximum_in_flight: usize,
    ) -> Result<NativeRunRecord, Error> {
        if self.poisoned {
            return Err(Error::WriterUnavailable);
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            if self.file.metadata()?.permissions().mode() & 0o077 != 0 {
                return Err(Error::InvalidIdentity("native journal must be owner-only"));
            }
        }
        if self
            .native
            .maximum_in_flight
            .is_some_and(|limit| limit != maximum_in_flight)
            || self.records.contains_key(&request.request_id)
        {
            return Err(Error::Conflict);
        }
        if let Some(record) = self.native.records.get(&request.request_id) {
            return if record.request == request {
                Ok(record.clone())
            } else {
                Err(Error::Conflict)
            };
        }
        if self.records.len() + self.native.records.len() >= self.capacity {
            return Err(Error::CapacityExceeded);
        }
        self.ensure_native_dispatch_space()?;
        let id = request.request_id.clone();
        self.commit_native(
            &id,
            Event::Reserve {
                request,
                maximum_in_flight,
            },
        )
    }

    /// Persist the exact signed manifest, quota, resource, and data-policy
    /// digests before dispatch.
    pub fn bind_native_execution(
        &mut self,
        request_id: &str,
        plan: &VerifiedExecutionPlan,
        now_unix_ms: u64,
    ) -> Result<NativeRunRecord, Error> {
        plan.assert_valid_at(now_unix_ms)
            .map_err(|_| Error::InvalidTime)?;
        let record = self
            .native
            .records
            .get(request_id)
            .ok_or(Error::RequestNotFound)?;
        if record.request.request_id != plan.request_id()
            || record.request.principal_id != plan.principal_id()
            || record.request.worker_generation != plan.resource_lease().worker_generation
            || record.request.model != plan.manifest().model_id
            || record.request.payload_digest != plan.manifest().payload_digest
        {
            return Err(Error::AssignmentMismatch);
        }
        let binding = NativeExecutionBinding {
            authority_epoch: plan.authority_epoch(),
            bundle_digest: plan.bundle_digest().to_string(),
            manifest_digest: plan.manifest_digest().to_string(),
            quota_lease_digest: plan.quota_lease_digest().to_string(),
            resource_lease_digest: plan.resource_lease_digest().to_string(),
            output_policy_digest: plan.output_policy_digest().to_string(),
            execution_binding_digest: plan.execution_binding_digest().to_string(),
            provider_id: plan.manifest().provider_id.clone(),
            model_id: plan.manifest().model_id.clone(),
            model_revision: plan.manifest().model_revision.clone(),
            model_digest: plan.manifest().model_digest.clone(),
            tokenizer_digest: plan.manifest().tokenizer_digest.clone(),
            template_digest: plan.manifest().template_digest.clone(),
            runtime_digest: plan.manifest().runtime_digest.clone(),
            adapter_digest: plan.manifest().adapter_digest.clone(),
            worker_id: plan.resource_lease().worker_id.clone(),
            worker_generation: plan.resource_lease().worker_generation,
            maximum_input_tokens: plan.quota_lease().maximum_input_tokens,
            maximum_output_tokens: plan.quota_lease().maximum_output_tokens,
            maximum_cost_microunits: plan.quota_lease().maximum_cost_microunits,
            valid_until_unix_ms: plan.valid_until_unix_ms(),
        };
        if record.execution_binding.as_ref() == Some(&binding) {
            return Ok(record.clone());
        }
        self.commit_native(
            request_id,
            Event::BindExecution {
                request_id: request_id.to_string(),
                binding,
            },
        )
    }

    /// Must commit before `turn/start`, including before awaiting its response.
    pub fn dispatch_native(
        &mut self,
        request_id: &str,
        dispatch: NativeDispatch,
    ) -> Result<NativeRunRecord, Error> {
        self.ensure_native_dispatch_space()?;
        self.commit_native(
            request_id,
            Event::Dispatch {
                request_id: request_id.to_string(),
                dispatch,
            },
        )
    }

    /// Production dispatch requires an exact, still-live execution binding.
    pub fn dispatch_native_authorized(
        &mut self,
        request_id: &str,
        dispatch: NativeDispatch,
        plan: &VerifiedExecutionPlan,
        now_unix_ms: u64,
    ) -> Result<NativeRunRecord, Error> {
        plan.assert_valid_at(now_unix_ms)
            .map_err(|_| Error::InvalidTime)?;
        self.assert_native_plan_binding(request_id, plan, now_unix_ms)?;
        if dispatch.model_provider != plan.manifest().provider_id {
            return Err(Error::AssignmentMismatch);
        }
        self.dispatch_native(request_id, dispatch)
    }

    /// Commit the write-ahead dispatch while issuing a one-shot local proof
    /// that this exact process can still prove the external effect was not sent.
    /// If a signed execution plan was bound, the historical host entrypoint is
    /// automatically upgraded to an immediate expiry/provider/generation gate.
    pub fn dispatch_native_with_pre_effect_abort(
        &mut self,
        request_id: &str,
        dispatch: NativeDispatch,
    ) -> Result<(NativeRunRecord, NativePreEffectAbortToken), Error> {
        if let Some(binding) = self
            .native
            .records
            .get(request_id)
            .and_then(|record| record.execution_binding.as_ref())
        {
            let now_unix_ms: u64 = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map_err(|_| Error::InvalidTime)?
                .as_millis()
                .try_into()
                .map_err(|_| Error::ArithmeticOverflow)?;
            let request = &self
                .native
                .records
                .get(request_id)
                .ok_or(Error::RequestNotFound)?
                .request;
            if binding.valid_until_unix_ms <= now_unix_ms
                || binding.provider_id != dispatch.model_provider
                || binding.worker_generation != request.worker_generation
                || binding.model_id != request.model
            {
                return Err(Error::AssignmentMismatch);
            }
        }
        let record = self.dispatch_native(request_id, dispatch)?;
        Ok((
            record.clone(),
            NativePreEffectAbortToken {
                request_id: request_id.to_string(),
                dispatch_revision: record.revision,
            },
        ))
    }

    /// Authorized spelling of write-ahead dispatch plus one-shot abort proof.
    pub fn dispatch_native_authorized_with_pre_effect_abort(
        &mut self,
        request_id: &str,
        dispatch: NativeDispatch,
        plan: &VerifiedExecutionPlan,
        now_unix_ms: u64,
    ) -> Result<(NativeRunRecord, NativePreEffectAbortToken), Error> {
        let record = self.dispatch_native_authorized(request_id, dispatch, plan, now_unix_ms)?;
        Ok((
            record.clone(),
            NativePreEffectAbortToken {
                request_id: request_id.to_string(),
                dispatch_revision: record.revision,
            },
        ))
    }

    /// Release a prepared dispatch only while the same live process still owns
    /// the exact one-shot pre-effect proof. If the process died, this proof is
    /// gone and recovery must reconcile instead of declaring the effect unsent.
    pub fn abort_native_before_effect(
        &mut self,
        token: NativePreEffectAbortToken,
        reason: String,
    ) -> Result<NativeRunRecord, Error> {
        let record = self
            .native
            .records
            .get(&token.request_id)
            .ok_or(Error::RequestNotFound)?;
        if record.state != NativeReservationState::Dispatching
            || record.revision != token.dispatch_revision
            || record.turn_id.is_some()
            || record.observation.is_some()
            || record.dispatch_rejection.is_some()
            || record.cancel_requested
        {
            return Err(Error::InvalidTransition);
        }
        self.commit_native(
            &token.request_id,
            Event::AbortBeforeEffect {
                request_id: token.request_id.clone(),
                reason,
            },
        )
    }

    pub fn native_started(
        &mut self,
        request_id: &str,
        turn_id: String,
    ) -> Result<NativeRunRecord, Error> {
        self.commit_native(
            request_id,
            Event::Started {
                request_id: request_id.to_string(),
                turn_id,
            },
        )
    }

    /// A typed JSON-RPC error is evidence that the App Server returned a
    /// rejection rather than a lost acknowledgement. This transition is legal
    /// only after Dispatch and before any turn identity was observed.
    pub fn reject_native_before_start(
        &mut self,
        request_id: &str,
        rejection: NativeDispatchRejection,
    ) -> Result<NativeRunRecord, Error> {
        self.commit_native(
            request_id,
            Event::RejectBeforeStart {
                request_id: request_id.to_string(),
                rejection,
            },
        )
    }

    /// This records intent only: an interrupt acknowledgement never frees a slot.
    pub fn cancel_native(&mut self, request_id: &str) -> Result<NativeRunRecord, Error> {
        let record = self
            .native
            .records
            .get(request_id)
            .ok_or(Error::RequestNotFound)?;
        if record.cancel_requested {
            return Ok(record.clone());
        }
        self.commit_native(
            request_id,
            Event::Cancel {
                request_id: request_id.to_string(),
            },
        )
    }

    pub fn stop_native_before_dispatch(
        &mut self,
        request_id: &str,
        reason: String,
    ) -> Result<NativeRunRecord, Error> {
        self.commit_native(
            request_id,
            Event::Stop {
                request_id: request_id.to_string(),
                reason,
            },
        )
    }

    /// Compatibility spelling for the canonical one-shot pre-effect abort.
    /// The caller must retain the opaque proof returned by durable dispatch;
    /// a request ID or a recovered journal record can never replace it.
    pub fn stop_native_before_turn_start(
        &mut self,
        token: NativePreEffectAbortToken,
        reason: String,
    ) -> Result<NativeRunRecord, Error> {
        self.abort_native_before_effect(token, reason)
    }
}
