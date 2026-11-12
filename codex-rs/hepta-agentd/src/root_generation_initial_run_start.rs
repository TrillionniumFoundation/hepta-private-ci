//! One live first-append acknowledgement on the same original Initial lane.
//! The request is data from the original writer; Root independently reads its
//! registered descriptor. A returned data digest grants no execution authority.

use codex_hepta_intelligence::PublishedObjectiveRunV1;
use codex_hepta_learning_ledger::RunStartAppendDisposition;
use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_types::Digest32;

use super::*;
use crate::RootGenerationInitialModeV1;
use crate::authority_host_service::generation_initial::run_start_retention::OriginalRunStartPublicationDataV1;
use crate::authority_host_service::generation_initial::run_start_retention::OriginalRunStartRetentionResponseV1;
use crate::authority_host_service::generation_initial::run_start_retention::RUN_START_RETENTION_PURPOSE;
use crate::neuron_generation_current::initial_root::original_initial_record;

impl RootGenerationInitialClient {
    pub(crate) fn retain_live_run_start(
        &self,
        record: &RunStartRecordV1,
        published: &PublishedObjectiveRunV1,
    ) -> Result<(), AgentdError> {
        let result = (|| {
            if self.run_start_attempted.swap(true, Ordering::AcqRel)
                || self.mode != RootGenerationInitialModeV1::Reserve
                || self.fenced.load(Ordering::Acquire)
                || published.publication.disposition != RunStartAppendDisposition::Appended
                || published.run_start != record.snapshot
                || record.snapshot.run_id.as_str() != self.scope().run_id
                || record.snapshot.generation != self.profile.deployment.target.generation()
            {
                return Err(uncertain());
            }
            self.connection.require_original_publication_session()?;
            validate_profile(&self.profile)?;
            let before = self.observe_initial_current()?;
            original_initial_record(&self.profile.prepared, &before)?.ok_or_else(uncertain)?;
            let publication = OriginalRunStartPublicationDataV1 {
                run_id: record.snapshot.run_id.to_string(),
                profile_digest: record.admission.profile_digest.to_string(),
                sequence: published.publication.sequence,
                record_digest: published.publication.record_digest.to_string(),
                chain_digest: published.publication.chain_digest.to_string(),
            };
            publication.validate().map_err(|_| uncertain())?;
            {
                let mut held = self.lane.try_lock().map_err(|_| uncertain())?;
                let mut lane = held.take().ok_or_else(uncertain)?;
                let request_id = lane.sequence;
                lane.sequence = request_id.checked_add(1).ok_or_else(uncertain)?;
                let request = Request {
                    schema: 1,
                    purpose: RUN_START_RETENTION_PURPOSE.into(),
                    request_id,
                    profile: self.profile.binding.clone(),
                    command: Command::RetainRunStart {
                        publication: publication.clone(),
                    },
                };
                self.connection.require_original_publication_session()?;
                // exchange retains the original absolute end and Root pidfd;
                // neither this attempt nor a fresh timeout can extend it.
                let raw = lane.stream.exchange(&serde_json::to_vec(&request)?)?;
                require_retained_reply(
                    &raw,
                    request_id,
                    &self.profile.binding,
                    self.mode,
                    &publication,
                )?;
                self.connection.require_original_publication_session()?;
                if self.fenced.load(Ordering::Acquire) {
                    return Err(uncertain());
                }
                *held = Some(lane);
            }
            if self.observe_initial_current()? != before {
                return Err(uncertain());
            }
            self.connection.require_original_publication_session()
        })();
        if result.is_err() {
            // Even IdempotentReplay cannot replace a lost first reply. Keeping
            // the byte-for-byte tuple does not create another live attempt.
            self.fence();
        }
        result
    }
}

fn require_retained_reply(
    raw: &[u8],
    request_id: u64,
    profile: &str,
    mode: RootGenerationInitialModeV1,
    publication: &OriginalRunStartPublicationDataV1,
) -> Result<(), AgentdError> {
    let response: OriginalRunStartRetentionResponseV1 =
        serde_json::from_slice(raw).map_err(|_| uncertain())?;
    let retained: Digest32 = response.retained.parse().map_err(|_| uncertain())?;
    if response.schema != 1
        || response.purpose != RUN_START_RETENTION_PURPOSE
        || response.request_id != request_id
        || response.profile != profile
        || response.mode != mode
        || &response.publication != publication
        || retained.is_zero()
        || retained.to_string() != response.retained
    {
        return Err(uncertain());
    }
    Ok(())
}

#[cfg(test)]
#[path = "root_generation_initial_run_start_tests.rs"]
mod tests;
