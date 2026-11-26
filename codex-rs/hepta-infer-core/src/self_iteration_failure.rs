//! Complete failure facts retain original owners; parsing grants no authority.
use crate::durable_control::native::NativeRunRecord;
use crate::self_iteration_model::*;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum SelfIterationModelFailureKindV1 {
    HttpRejection { status: u16 },
    ProviderFailed,
    ProviderIncomplete,
    ProviderError,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelfIterationModelFailureV1 {
    pub request_id: StableId,
    pub role: SelfIterationModelRoleV1,
    pub envelope_digest: Digest32,
    pub candidate_digest: Option<Digest32>,
    pub kind: SelfIterationModelFailureKindV1,
    pub native_run_digest: Digest32,
    pub provider_failure_digest: Digest32,
    pub facts_digest: Digest32,
    pub observed_at_ms: u64,
    pub authority: AuthorityPosture,
}

impl SelfIterationModelFailureV1 {
    pub fn validate(
        &self,
        request: &SelfIterationModelRequestV1,
    ) -> Result<(), SelfIterationModelErrorV1> {
        // This validates historical facts, including a real terminal observed
        // after its deadline. It neither extends the deadline nor grants use.
        request.validate(
            request
                .deadline_ms
                .checked_sub(1)
                .ok_or(SelfIterationModelErrorV1::InvalidRequest)?,
        )?;
        if self.request_id != request.request_id
            || self.role != request.role
            || self.envelope_digest != request.envelope_digest
            || self.candidate_digest != request.candidate_digest
            || self.native_run_digest.is_zero()
            || self.provider_failure_digest.is_zero()
            || self.facts_digest.is_zero()
            || self.observed_at_ms == 0
            || self.authority.grants_any()
            || matches!(self.kind, SelfIterationModelFailureKindV1::HttpRejection { status }
                if !(100..=599).contains(&status) || (200..=299).contains(&status))
        {
            return Err(SelfIterationModelErrorV1::InvalidResponse);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelfIterationModelFailureFactsV1 {
    pub request: SelfIterationModelRequestV1,
    pub native_record: NativeRunRecord,
    /// Original typed Root outcome bytes, independently authenticated by the
    /// installed reader. These bytes alone establish no Root custody.
    pub root_outcome_bytes: Vec<u8>,
    pub observed_at_ms: u64,
}

/// Installed readonly port to the independent Root failure service. It must
/// authenticate the actual service and join its full original provider facts.
pub trait SelfIterationModelFailureObserverV1: Send + Sync {
    fn observe<'a>(
        &'a self,
        request: &'a SelfIterationModelRequestV1,
    ) -> std::pin::Pin<
        Box<
            dyn std::future::Future<
                    Output = Result<Option<SelfIterationModelFailureV1>, SelfIterationModelErrorV1>,
                > + Send
                + 'a,
        >,
    >;
}

#[path = "self_iteration_failure_codec.rs"]
mod codec;
pub use codec::*;
