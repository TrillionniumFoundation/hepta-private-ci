//! Readiness is only the exact identity of retained source DATA. Complete
//! still enters the original Root owner and physically authenticates that cut.

use std::io;

use serde::Deserialize;
use serde::Serialize;

use crate::root_independent_b_candidate_notice::CandidateNotice;
use crate::root_independent_b_protocol::PreparedPlanData;
use crate::root_independent_b_protocol::digest;
use crate::root_independent_b_source_protocol::SourceAcknowledgement;

const PURPOSE: &str = "runtime.learning.independent-b-source-ready.v1";

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct SourceReadyData {
    schema: u8,
    purpose: String,
    pub(crate) initial: String,
    pub(crate) binding: String,
    pub(crate) scope: String,
    pub(crate) training_head: String,
    pub(crate) candidate_bundle: String,
    pub(crate) source: SourceAcknowledgement,
}

impl SourceReadyData {
    pub(crate) fn require_original_observation(
        &self,
        initial: codex_hepta_types::Digest32,
        binding: codex_hepta_types::Digest32,
        scope: codex_hepta_types::Digest32,
        training: codex_hepta_types::Digest32,
        candidate: codex_hepta_types::Digest32,
        source: &SourceAcknowledgement,
    ) -> io::Result<()> {
        if self.schema != 1
            || self.purpose != PURPOSE
            || self.initial != initial.to_string()
            || self.binding != binding.to_string()
            || self.scope != scope.to_string()
            || self.training_head != training.to_string()
            || self.candidate_bundle != candidate.to_string()
            || &self.source != source
        {
            return Err(io::Error::other(
                "original B retained source differs from notification DATA",
            ));
        }
        Ok(())
    }

    pub(crate) fn from_original_source(
        candidate: &CandidateNotice,
        source: SourceAcknowledgement,
    ) -> io::Result<Self> {
        let data = Self {
            schema: 1,
            purpose: PURPOSE.into(),
            initial: candidate.plan.initial.clone(),
            binding: candidate.binding.clone(),
            scope: candidate.plan.scope.clone(),
            training_head: candidate.plan.training_head.clone(),
            candidate_bundle: candidate.plan.candidate_bundle.clone(),
            source,
        };
        data.require_candidate(&candidate.binding, &candidate.plan)?;
        Ok(data)
    }

    pub(crate) fn require_candidate(
        &self,
        binding: &str,
        plan: &PreparedPlanData,
    ) -> io::Result<()> {
        if self.schema != 1
            || self.purpose != PURPOSE
            || self.initial != plan.initial
            || self.binding != binding
            || self.scope != plan.scope
            || self.training_head != plan.training_head
            || self.candidate_bundle != plan.candidate_bundle
            || self.source.schema != 1
            || self.source.purpose != crate::root_independent_b_source_protocol::PURPOSE
            || self.source.binding != binding
        {
            return Err(io::Error::other("original B source readiness differs"));
        }
        for value in [
            &self.initial,
            &self.binding,
            &self.scope,
            &self.training_head,
            &self.candidate_bundle,
            &self.source.source_digest,
            &self.source.observed_digest,
            &self.source.policy_digest,
        ] {
            digest(value)?;
        }
        Ok(())
    }

    pub(crate) fn encode(&self) -> io::Result<Vec<u8>> {
        let bytes = serde_json::to_vec(self).map_err(io::Error::other)?;
        if bytes.is_empty() || bytes.len() > crate::root_independent_b_notice::BOUND {
            return Err(io::Error::other(
                "bounded original B source readiness required",
            ));
        }
        Ok(bytes)
    }

    pub(crate) fn decode(bytes: &[u8], binding: &str, plan: &PreparedPlanData) -> io::Result<Self> {
        if bytes.is_empty() || bytes.len() > crate::root_independent_b_notice::BOUND {
            return Err(io::Error::other(
                "bounded original B source readiness required",
            ));
        }
        let data: Self = serde_json::from_slice(bytes).map_err(io::Error::other)?;
        if data.encode()? != bytes {
            return Err(io::Error::other("canonical original B readiness required"));
        }
        data.require_candidate(binding, plan)?;
        Ok(data)
    }
}
