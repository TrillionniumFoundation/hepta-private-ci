//! Retain authenticated publication evidence through the outer handoff.

use super::FinalUseErrorV1;
use super::FinalUseTabularCandidateV1;
use super::FinalUseWorldModelCandidateV1;
use super::issued::IssuedEvidenceV1;
use crate::world_model_v2::WorldModelV2Error;

/// Only a real owner-authenticated fit can construct this release proof. The
/// small sealed evidence and its reservation survive the payload/input cleanup
/// and the outer wrapper's last actual time sample.
pub(crate) struct FinalUseCandidateReleaseV1<'a, T> {
    pub(super) candidate: T,
    pub(super) evidence: IssuedEvidenceV1<'a>,
    pub(super) checked_at: u64,
    pub(super) model_window: Option<(u64, u64)>,
}

/// Internal candidates expose only their mutable handoff timestamp to the
/// retained release proof; this trait cannot create or authorize a candidate.
pub(crate) trait CandidateReleaseTimeV1 {
    fn record_release_at(&mut self, now: u64);
}

impl CandidateReleaseTimeV1 for FinalUseTabularCandidateV1 {
    fn record_release_at(&mut self, now: u64) {
        self.published_at_unix_micros = now;
    }
}

impl CandidateReleaseTimeV1 for FinalUseWorldModelCandidateV1 {
    fn record_release_at(&mut self, now: u64) {
        self.published_at_unix_micros = now;
    }
}

impl<T: CandidateReleaseTimeV1> FinalUseCandidateReleaseV1<'_, T> {
    pub(crate) fn finish(mut self, now: u64) -> Result<T, FinalUseErrorV1> {
        if now < self.checked_at {
            return Err(FinalUseErrorV1::ClockRegression);
        }
        self.evidence.revalidate(now)?;
        if self
            .model_window
            .is_some_and(|(retained, expires)| now > retained || now > expires)
        {
            return Err(WorldModelV2Error::Expired.into());
        }
        self.candidate.record_release_at(now);
        Ok(self.candidate)
    }
}
