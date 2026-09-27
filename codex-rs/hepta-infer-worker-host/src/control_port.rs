//! State-transition port shared by the direct compatibility owner and the
//! production journal-writer actor.

use codex_hepta_infer_core::control_contracts::ProtectedOutput;
use codex_hepta_infer_core::control_contracts::VerifiedExecutionPlan;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::Error;
use codex_hepta_infer_core::durable_control::native::NativeDispatch;
use codex_hepta_infer_core::durable_control::native::NativeDispatchRejection;
use codex_hepta_infer_core::durable_control::native::NativePreEffectAbortToken;
use codex_hepta_infer_core::durable_control::native::NativeRequest;
use codex_hepta_infer_core::durable_control::native::NativeRunOutput;
use codex_hepta_infer_core::durable_control::native::NativeRunRecord;

/// Synchronous durable transition port. Every method is a short local journal
/// operation. Provider/network awaits occur outside this interface.
pub trait NativeControlPort: Send {
    fn reserve_native(
        &mut self,
        request: NativeRequest,
        maximum_in_flight: usize,
    ) -> Result<NativeRunRecord, Error>;

    fn bind_native_execution(
        &mut self,
        request_id: &str,
        plan: &VerifiedExecutionPlan,
        now_unix_ms: u64,
    ) -> Result<NativeRunRecord, Error>;

    fn dispatch_native_with_pre_effect_abort(
        &mut self,
        request_id: &str,
        dispatch: NativeDispatch,
    ) -> Result<(NativeRunRecord, NativePreEffectAbortToken), Error>;

    fn dispatch_native_authorized_with_pre_effect_abort(
        &mut self,
        request_id: &str,
        dispatch: NativeDispatch,
        plan: &VerifiedExecutionPlan,
        now_unix_ms: u64,
    ) -> Result<(NativeRunRecord, NativePreEffectAbortToken), Error>;

    fn abort_native_before_effect(
        &mut self,
        token: NativePreEffectAbortToken,
        reason: String,
    ) -> Result<NativeRunRecord, Error>;

    fn native_started(
        &mut self,
        request_id: &str,
        turn_id: String,
    ) -> Result<NativeRunRecord, Error>;

    fn reject_native_before_start(
        &mut self,
        request_id: &str,
        rejection: NativeDispatchRejection,
    ) -> Result<NativeRunRecord, Error>;

    fn cancel_native(&mut self, request_id: &str) -> Result<NativeRunRecord, Error>;

    fn stop_native_before_dispatch(
        &mut self,
        request_id: &str,
        reason: String,
    ) -> Result<NativeRunRecord, Error>;

    fn settle_native(
        &mut self,
        request_id: &str,
        output: NativeRunOutput,
    ) -> Result<NativeRunRecord, Error>;

    fn settle_native_authorized(
        &mut self,
        request_id: &str,
        plan: &VerifiedExecutionPlan,
        now_unix_ms: u64,
        output: NativeRunOutput,
        protected_output: Option<ProtectedOutput>,
    ) -> Result<NativeRunRecord, Error>;

    /// Returns an owned snapshot so actor callers never borrow the writer's
    /// in-memory state across an await.
    fn native_record(&self, request_id: &str) -> Option<NativeRunRecord>;
}

impl NativeControlPort for DurableInferenceControl {
    fn reserve_native(
        &mut self,
        request: NativeRequest,
        maximum_in_flight: usize,
    ) -> Result<NativeRunRecord, Error> {
        DurableInferenceControl::reserve_native(self, request, maximum_in_flight)
    }

    fn bind_native_execution(
        &mut self,
        request_id: &str,
        plan: &VerifiedExecutionPlan,
        now_unix_ms: u64,
    ) -> Result<NativeRunRecord, Error> {
        DurableInferenceControl::bind_native_execution(self, request_id, plan, now_unix_ms)
    }

    fn dispatch_native_with_pre_effect_abort(
        &mut self,
        request_id: &str,
        dispatch: NativeDispatch,
    ) -> Result<(NativeRunRecord, NativePreEffectAbortToken), Error> {
        DurableInferenceControl::dispatch_native_with_pre_effect_abort(self, request_id, dispatch)
    }

    fn dispatch_native_authorized_with_pre_effect_abort(
        &mut self,
        request_id: &str,
        dispatch: NativeDispatch,
        plan: &VerifiedExecutionPlan,
        now_unix_ms: u64,
    ) -> Result<(NativeRunRecord, NativePreEffectAbortToken), Error> {
        DurableInferenceControl::dispatch_native_authorized_with_pre_effect_abort(
            self,
            request_id,
            dispatch,
            plan,
            now_unix_ms,
        )
    }

    fn abort_native_before_effect(
        &mut self,
        token: NativePreEffectAbortToken,
        reason: String,
    ) -> Result<NativeRunRecord, Error> {
        DurableInferenceControl::abort_native_before_effect(self, token, reason)
    }

    fn native_started(
        &mut self,
        request_id: &str,
        turn_id: String,
    ) -> Result<NativeRunRecord, Error> {
        DurableInferenceControl::native_started(self, request_id, turn_id)
    }

    fn reject_native_before_start(
        &mut self,
        request_id: &str,
        rejection: NativeDispatchRejection,
    ) -> Result<NativeRunRecord, Error> {
        DurableInferenceControl::reject_native_before_start(self, request_id, rejection)
    }

    fn cancel_native(&mut self, request_id: &str) -> Result<NativeRunRecord, Error> {
        DurableInferenceControl::cancel_native(self, request_id)
    }

    fn stop_native_before_dispatch(
        &mut self,
        request_id: &str,
        reason: String,
    ) -> Result<NativeRunRecord, Error> {
        DurableInferenceControl::stop_native_before_dispatch(self, request_id, reason)
    }

    fn settle_native(
        &mut self,
        request_id: &str,
        output: NativeRunOutput,
    ) -> Result<NativeRunRecord, Error> {
        DurableInferenceControl::settle_native(self, request_id, output)
    }

    fn settle_native_authorized(
        &mut self,
        request_id: &str,
        plan: &VerifiedExecutionPlan,
        now_unix_ms: u64,
        output: NativeRunOutput,
        protected_output: Option<ProtectedOutput>,
    ) -> Result<NativeRunRecord, Error> {
        DurableInferenceControl::settle_native_authorized(
            self,
            request_id,
            plan,
            now_unix_ms,
            output,
            protected_output,
        )
    }

    fn native_record(&self, request_id: &str) -> Option<NativeRunRecord> {
        DurableInferenceControl::native_record(self, request_id).cloned()
    }
}
