//! Sealed asynchronous state-transition port for the production journal actor.
//!
//! The provider/effect path never owns `DurableInferenceControl` directly. All
//! durable transitions cross this port, which lets production use the unique
//! writer actor while focused compatibility tests can still use an in-process
//! durable owner.

use std::error::Error as StdError;
use std::fmt;

use async_trait::async_trait;
use codex_hepta_infer_core::control_contracts::ProtectedOutput;
use codex_hepta_infer_core::control_contracts::VerifiedExecutionPlan;
#[cfg(test)]
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::Error;
use codex_hepta_infer_core::durable_control::native::NativeDispatch;
use codex_hepta_infer_core::durable_control::native::NativeDispatchRejection;
use codex_hepta_infer_core::durable_control::native::NativePreEffectAbortToken;
use codex_hepta_infer_core::durable_control::native::NativeRequest;
use codex_hepta_infer_core::durable_control::native::NativeRunOutput;
use codex_hepta_infer_core::durable_control::native::NativeRunRecord;

#[derive(Debug)]
pub enum NativeControlPortError {
    Actor(crate::control_actor::NativeControlActorError),
    Durable(Error),
    Backend(String),
}

impl fmt::Display for NativeControlPortError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Actor(error) => write!(formatter, "{error}"),
            Self::Durable(error) => write!(formatter, "{error}"),
            Self::Backend(error) => write!(formatter, "native control backend failed: {error}"),
        }
    }
}

impl StdError for NativeControlPortError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Actor(error) => Some(error),
            Self::Durable(error) => Some(error),
            Self::Backend(_) => None,
        }
    }
}

impl From<Error> for NativeControlPortError {
    fn from(error: Error) -> Self {
        Self::Durable(error)
    }
}

pub type NativeControlPortResult<T> = Result<T, NativeControlPortError>;

mod sealed {
    pub trait Sealed {}
    impl Sealed for crate::control_actor::NativeJournalWriterHandle {}
    #[cfg(test)]
    impl Sealed for codex_hepta_infer_core::durable_control::DurableInferenceControl {}
}

/// Durable transition port. Each method completes one bounded journal command.
/// Provider and network awaits occur outside the unique writer actor.
#[async_trait]
pub trait NativeControlPort: Send + Sync + sealed::Sealed {
    async fn reserve_native(
        &mut self,
        request: NativeRequest,
        maximum_in_flight: usize,
    ) -> NativeControlPortResult<NativeRunRecord>;

    async fn bind_native_execution(
        &mut self,
        request_id: &str,
        plan: &VerifiedExecutionPlan,
        now_unix_ms: u64,
    ) -> NativeControlPortResult<NativeRunRecord>;

    async fn dispatch_native_with_pre_effect_abort(
        &mut self,
        request_id: &str,
        dispatch: NativeDispatch,
    ) -> NativeControlPortResult<(NativeRunRecord, NativePreEffectAbortToken)>;

    async fn dispatch_native_authorized_with_pre_effect_abort(
        &mut self,
        request_id: &str,
        dispatch: NativeDispatch,
        plan: &VerifiedExecutionPlan,
        now_unix_ms: u64,
    ) -> NativeControlPortResult<(NativeRunRecord, NativePreEffectAbortToken)>;

    async fn abort_native_before_effect(
        &mut self,
        token: NativePreEffectAbortToken,
        reason: String,
    ) -> NativeControlPortResult<NativeRunRecord>;

    async fn native_started(
        &mut self,
        request_id: &str,
        turn_id: String,
    ) -> NativeControlPortResult<NativeRunRecord>;

    async fn reject_native_before_start(
        &mut self,
        request_id: &str,
        rejection: NativeDispatchRejection,
    ) -> NativeControlPortResult<NativeRunRecord>;

    async fn cancel_native(&mut self, request_id: &str)
    -> NativeControlPortResult<NativeRunRecord>;

    async fn stop_native_before_dispatch(
        &mut self,
        request_id: &str,
        reason: String,
    ) -> NativeControlPortResult<NativeRunRecord>;

    async fn settle_native(
        &mut self,
        request_id: &str,
        output: NativeRunOutput,
    ) -> NativeControlPortResult<NativeRunRecord>;

    async fn settle_native_authorized(
        &mut self,
        request_id: &str,
        plan: &VerifiedExecutionPlan,
        now_unix_ms: u64,
        output: NativeRunOutput,
        protected_output: Option<ProtectedOutput>,
    ) -> NativeControlPortResult<NativeRunRecord>;

    /// Returns an owned snapshot so callers never borrow writer state across an
    /// await or provider boundary.
    async fn native_record(
        &self,
        request_id: &str,
    ) -> NativeControlPortResult<Option<NativeRunRecord>>;
}

#[cfg(test)]
#[async_trait]
impl NativeControlPort for DurableInferenceControl {
    async fn reserve_native(
        &mut self,
        request: NativeRequest,
        maximum_in_flight: usize,
    ) -> NativeControlPortResult<NativeRunRecord> {
        DurableInferenceControl::reserve_native(self, request, maximum_in_flight)
            .map_err(Into::into)
    }

    async fn bind_native_execution(
        &mut self,
        request_id: &str,
        plan: &VerifiedExecutionPlan,
        now_unix_ms: u64,
    ) -> NativeControlPortResult<NativeRunRecord> {
        DurableInferenceControl::bind_native_execution(self, request_id, plan, now_unix_ms)
            .map_err(Into::into)
    }

    async fn dispatch_native_with_pre_effect_abort(
        &mut self,
        request_id: &str,
        dispatch: NativeDispatch,
    ) -> NativeControlPortResult<(NativeRunRecord, NativePreEffectAbortToken)> {
        DurableInferenceControl::dispatch_native_with_pre_effect_abort(self, request_id, dispatch)
            .map_err(Into::into)
    }

    async fn dispatch_native_authorized_with_pre_effect_abort(
        &mut self,
        request_id: &str,
        dispatch: NativeDispatch,
        plan: &VerifiedExecutionPlan,
        now_unix_ms: u64,
    ) -> NativeControlPortResult<(NativeRunRecord, NativePreEffectAbortToken)> {
        DurableInferenceControl::dispatch_native_authorized_with_pre_effect_abort(
            self,
            request_id,
            dispatch,
            plan,
            now_unix_ms,
        )
        .map_err(Into::into)
    }

    async fn abort_native_before_effect(
        &mut self,
        token: NativePreEffectAbortToken,
        reason: String,
    ) -> NativeControlPortResult<NativeRunRecord> {
        DurableInferenceControl::abort_native_before_effect(self, token, reason).map_err(Into::into)
    }

    async fn native_started(
        &mut self,
        request_id: &str,
        turn_id: String,
    ) -> NativeControlPortResult<NativeRunRecord> {
        DurableInferenceControl::native_started(self, request_id, turn_id).map_err(Into::into)
    }

    async fn reject_native_before_start(
        &mut self,
        request_id: &str,
        rejection: NativeDispatchRejection,
    ) -> NativeControlPortResult<NativeRunRecord> {
        DurableInferenceControl::reject_native_before_start(self, request_id, rejection)
            .map_err(Into::into)
    }

    async fn cancel_native(
        &mut self,
        request_id: &str,
    ) -> NativeControlPortResult<NativeRunRecord> {
        DurableInferenceControl::cancel_native(self, request_id).map_err(Into::into)
    }

    async fn stop_native_before_dispatch(
        &mut self,
        request_id: &str,
        reason: String,
    ) -> NativeControlPortResult<NativeRunRecord> {
        DurableInferenceControl::stop_native_before_dispatch(self, request_id, reason)
            .map_err(Into::into)
    }

    async fn settle_native(
        &mut self,
        request_id: &str,
        output: NativeRunOutput,
    ) -> NativeControlPortResult<NativeRunRecord> {
        DurableInferenceControl::settle_native(self, request_id, output).map_err(Into::into)
    }

    async fn settle_native_authorized(
        &mut self,
        request_id: &str,
        plan: &VerifiedExecutionPlan,
        now_unix_ms: u64,
        output: NativeRunOutput,
        protected_output: Option<ProtectedOutput>,
    ) -> NativeControlPortResult<NativeRunRecord> {
        DurableInferenceControl::settle_native_authorized(
            self,
            request_id,
            plan,
            now_unix_ms,
            output,
            protected_output,
        )
        .map_err(Into::into)
    }

    async fn native_record(
        &self,
        request_id: &str,
    ) -> NativeControlPortResult<Option<NativeRunRecord>> {
        Ok(DurableInferenceControl::native_record(self, request_id).cloned())
    }
}
