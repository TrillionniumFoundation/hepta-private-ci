impl DurableInferenceControl {
    /// Host dispatch port for an execution whose independently verified plan was
    /// already bound durably. This check runs immediately before the App Server
    /// effect boundary and therefore catches expiry after initial admission.
    pub fn dispatch_native_bound_with_pre_effect_abort(
        &mut self,
        request_id: &str,
        dispatch: NativeDispatch,
        now_unix_ms: u64,
    ) -> Result<(NativeRunRecord, NativePreEffectAbortToken), Error> {
        let record = self
            .native
            .records
            .get(request_id)
            .ok_or(Error::RequestNotFound)?;
        let binding = record
            .execution_binding
            .as_ref()
            .ok_or(Error::InvalidIdentity("native execution binding"))?;
        if binding.valid_until_unix_ms <= now_unix_ms
            || binding.provider_id != dispatch.model_provider
            || binding.worker_generation != record.request.worker_generation
            || binding.model_id != record.request.model
        {
            return Err(Error::AssignmentMismatch);
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
}
