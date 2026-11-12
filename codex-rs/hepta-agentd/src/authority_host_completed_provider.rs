//! Fixed zero-payload completion operations. Replies escape only after the
//! original terminal, task, B and publication attempts have all reached Ready.

use codex_hepta_agent_protocol::OriginalQ24CompletedHistoryDataV1;

use super::completed_deployment::CompletedMode;
use super::completed_files::CompletedFiles;
use super::completed_record::CompletedLearningRecord;
use super::*;
use crate::authority_host_service::generation_publication::OriginalCompletedPublicationModeV1;
use crate::root_historical_task_read_protocol::CompletedLearningAcceptanceResponseV1;
use crate::root_historical_task_read_protocol::CompletedLearningHistoryResponseV1;

impl HistoricalTaskReadRuntime {
    pub(super) fn completed_learning_operation(
        &self,
        service: &HostAuthorityService,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        operation: HistoricalReadOperationV1,
        request_id: u64,
        end: Instant,
    ) -> io::Result<Vec<u8>> {
        require_end(end)?;
        let fixed = self
            .completed
            .as_ref()
            .ok_or_else(|| io::Error::other("original completed deployment missing"))?;
        fixed.require_original()?;
        let initial = self.deployment.initial.original_initial_data()?;
        let root = RootAuthorityDirectory::open(&config.state_dir).map_err(io::Error::other)?;
        let mode = match operation {
            HistoricalReadOperationV1::AcceptCompletedLearning if fixed.is_fresh() => {
                OriginalCompletedPublicationModeV1::AcceptedPublication
            }
            HistoricalReadOperationV1::CaptureCompletedHistory
                if fixed.data.mode == CompletedMode::CaptureRetired =>
            {
                OriginalCompletedPublicationModeV1::CaptureRetired
            }
            HistoricalReadOperationV1::ReadCompletedHistory
                if fixed.data.mode == CompletedMode::ReadFinalized
                    || (fixed.data.mode == CompletedMode::CaptureRetired
                        && fixed.completion_phase.load(Ordering::Acquire) == 2) =>
            {
                OriginalCompletedPublicationModeV1::ReadFinalized
            }
            _ => return Err(io::Error::other("Root-fixed completed phase differs")),
        };
        if mode != OriginalCompletedPublicationModeV1::ReadFinalized {
            fixed
                .completion_phase
                .compare_exchange(0, 1, Ordering::AcqRel, Ordering::Acquire)
                .map_err(|_| {
                    io::Error::other("original completion attempt was already consumed")
                })?;
        }
        let (acceptance, checked) =
            if mode == OriginalCompletedPublicationModeV1::AcceptedPublication {
                let (refusal, files) = fixed.original.as_ref().ok_or_else(|| {
                    io::Error::other("fresh original completion descriptors missing")
                })?;
                CompletedLearningRecord::accept(
                    refusal,
                    root,
                    &self.deployment.target,
                    &initial,
                    end,
                    || {
                        let checked = self.observe_completed_learning(
                            service,
                            config,
                            registration,
                            owner,
                            fixed,
                            files,
                            None,
                            mode,
                            end,
                        )?;
                        fixed.require_original()?;
                        require_end(end)?;
                        Ok((checked.fact.clone(), checked))
                    },
                )?
            } else {
                // Primary fact and all seven file descriptions are opened only
                // after the existing independent terminal attempt has been Armed.
                CompletedLearningRecord::read(
                    root,
                    &config.state_dir,
                    &self.deployment.target,
                    &initial,
                    end,
                    |fact| {
                        fixed.require_original()?;
                        if fact.deployment != fixed.binding.to_string() {
                            return Err(io::Error::other(
                                "original completed deployment binding changed",
                            ));
                        }
                        let files = CompletedFiles::retain_original(
                            fixed.data.files.clone(),
                            initial.request.envelope.objective_digest,
                        )?;
                        let result = self.observe_completed_learning(
                            service,
                            config,
                            registration,
                            owner,
                            fixed,
                            &files,
                            Some(fact),
                            mode,
                            end,
                        );
                        fixed.require_original()?;
                        require_end(end)?;
                        result
                    },
                )?
            };
        // No response is formed from an Armed attempt or a caught error.
        fixed.require_original()?;
        self.metadata.require_metadata_unchanged()?;
        require_end(end)?;
        if mode != OriginalCompletedPublicationModeV1::ReadFinalized {
            fixed
                .completion_phase
                .compare_exchange(1, 2, Ordering::AcqRel, Ordering::Acquire)
                .map_err(|_| io::Error::other("original completion phase changed"))?;
        }
        let reply = if mode == OriginalCompletedPublicationModeV1::AcceptedPublication {
            if checked.publication.successor.is_some() {
                return Err(io::Error::other(
                    "first acceptance cannot manufacture retired C",
                ));
            }
            serde_json::to_vec(&CompletedLearningAcceptanceResponseV1 {
                schema: 1,
                purpose: operation.purpose().into(),
                request_id,
                profile: self.profile.binding.clone(),
                data_cut: checked.data_cut,
                initial: initial.head_digest.to_string(),
                frozen_scope: checked.fact.frozen_scope,
                terminal_head: checked.fact.terminal_head,
                acceptance: acceptance.to_string(),
            })
        } else {
            let successor = checked
                .publication
                .successor
                .as_ref()
                .ok_or_else(|| io::Error::other("actual finalized original C is missing"))?;
            let completion = OriginalQ24CompletedHistoryDataV1 {
                schema: 1,
                identity_digest: self.profile.identity.clone(),
                root_profile: self.profile.binding.clone(),
                initial: initial.head_digest.to_string(),
                frozen_scope: checked.fact.frozen_scope,
                terminal_head: checked.fact.terminal_head,
                acceptance: acceptance.to_string(),
                current_head: checked.publication.current_head.to_string(),
                successor_record: successor.record_digest.clone(),
                successor_cut: crate::authority_host_service::generation_publication::RootCompletedSuccessorDataV1::original_cut_digest(successor)?.to_string(),
            };
            completion.validate_data().map_err(io::Error::other)?;
            serde_json::to_vec(&CompletedLearningHistoryResponseV1 {
                schema: 1,
                purpose: operation.purpose().into(),
                request_id,
                profile: self.profile.binding.clone(),
                data_cut: checked.data_cut,
                completion,
            })
        }
        .map_err(io::Error::other)?;
        if reply.is_empty() || reply.len() > WIRE_BOUND {
            return Err(io::Error::other(
                "completed history reply exceeds original bound",
            ));
        }
        require_end(end)?;
        Ok(reply)
    }
}
