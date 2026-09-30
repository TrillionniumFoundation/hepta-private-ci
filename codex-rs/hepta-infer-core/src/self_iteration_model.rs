//! Bounded model assistance for self-iteration. Model text is candidate input
//! or an assessment; it never substitutes for independent owner evidence.

use std::error::Error;
use std::fmt;
use std::future::Future;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

pub const MAX_SELF_ITERATION_MODEL_PROMPT_BYTES: usize = 8 * 1024;
pub const MAX_SELF_ITERATION_MODEL_RESPONSE_BYTES: u32 = 64 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SelfIterationModelRoleV1 {
    Generator,
    Evaluator,
    Selector,
    Observer,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelfIterationModelRequestV1 {
    pub request_id: StableId,
    pub role: SelfIterationModelRoleV1,
    pub envelope_digest: Digest32,
    pub candidate_digest: Option<Digest32>,
    pub prompt: String,
    pub deadline_ms: u64,
    pub maximum_response_bytes: u32,
}

impl SelfIterationModelRequestV1 {
    pub fn validate(&self, now_ms: u64) -> Result<(), SelfIterationModelErrorV1> {
        if self.envelope_digest.is_zero()
            || self.candidate_digest.is_some_and(|digest| digest.is_zero())
            || self.prompt.is_empty()
            || self.prompt.len() > MAX_SELF_ITERATION_MODEL_PROMPT_BYTES
            || self.deadline_ms <= now_ms
            || self.maximum_response_bytes == 0
            || self.maximum_response_bytes > MAX_SELF_ITERATION_MODEL_RESPONSE_BYTES
            || (self.role != SelfIterationModelRoleV1::Generator && self.candidate_digest.is_none())
        {
            return Err(SelfIterationModelErrorV1::InvalidRequest);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelfIterationModelAssessmentV1 {
    pub request_id: StableId,
    pub role: SelfIterationModelRoleV1,
    pub envelope_digest: Digest32,
    pub candidate_digest: Option<Digest32>,
    pub model_output: String,
    /// Digest of the actual durable native terminal receipt, not a hash invented
    /// from model prose. Consumers may resolve that receipt through its owner.
    pub native_run_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl SelfIterationModelAssessmentV1 {
    pub fn validate(
        &self,
        request: &SelfIterationModelRequestV1,
    ) -> Result<(), SelfIterationModelErrorV1> {
        if self.request_id != request.request_id
            || self.role != request.role
            || self.envelope_digest != request.envelope_digest
            || self.candidate_digest != request.candidate_digest
            || self.native_run_digest.is_zero()
            || self.model_output.is_empty()
            || self.model_output.len() > request.maximum_response_bytes as usize
            || self.authority.grants_any()
        {
            return Err(SelfIterationModelErrorV1::InvalidResponse);
        }
        Ok(())
    }
}

#[derive(Debug)]
pub enum SelfIterationModelErrorV1 {
    InvalidRequest,
    InvalidResponse,
    TimedOut,
    Provider(String),
}
impl fmt::Display for SelfIterationModelErrorV1 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl Error for SelfIterationModelErrorV1 {}

/// A real model session adapter. Each role receives its own native request
/// identity and terminal receipt. Different sessions do not establish an
/// independent authority domain; signed learning-owner gates remain mandatory.
pub trait SelfIterationModelPortV1: Send {
    fn assess(
        &mut self,
        request: SelfIterationModelRequestV1,
    ) -> impl Future<Output = Result<SelfIterationModelAssessmentV1, SelfIterationModelErrorV1>> + Send;
}
