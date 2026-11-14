//! All physical cuts, the original signed completions and current recipient
//! checks share one completed-learning attempt. No current observation can
//! silently stand in for the first immutable Root acceptance.

use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_types::Digest32;

use super::super::generation_publication::deployment::post_a::with_original_completed_publication;
use super::super::q24_evaluation::OriginalCompletedBReadV1;
use super::super::q24_evaluation::with_original_completed_b;
use super::completed_checkpoint::with_original_checkpoint;
use super::completed_deployment::CompletedLearningRuntime;
use super::completed_files::CompletedFiles;
use super::completed_record::RootCompletedLearningAcceptanceDataV1;
use super::completed_signatures::verify_original_completions;
use super::*;
use crate::authority_host_service::generation_publication::OriginalCompletedPublicationDataV1;
use crate::authority_host_service::generation_publication::OriginalCompletedPublicationModeV1;
use crate::authority_host_service::generation_publication::OriginalCompletedPublicationReadV1;

pub(super) struct CheckedCompletion {
    pub(super) fact: RootCompletedLearningAcceptanceDataV1,
    pub(super) publication: OriginalCompletedPublicationDataV1,
    pub(super) data_cut: String,
}

impl HistoricalTaskReadRuntime {
    pub(super) fn observe_completed_learning(
        &self,
        service: &HostAuthorityService,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        fixed: &CompletedLearningRuntime,
        files: &CompletedFiles,
        accepted: Option<&RootCompletedLearningAcceptanceDataV1>,
        mode: OriginalCompletedPublicationModeV1,
        end: Instant,
    ) -> io::Result<CheckedCompletion> {
        with_original_checkpoint(&config.state_dir, |checkpoint, checkpoint_digest| {
            RootRetainedHistoricalCompleteTaskV1::with_original_historical_task(
                &self.task,
                service,
                end,
                |read| {
                    fixed.require_original()?;
                    let (initial, proof, observed) = self.observe_completed_original_task(
                        service,
                        config,
                        registration,
                        owner,
                        read,
                        end,
                    )?;
                    let check_profile = |profile| {
                        self.observe_completed_profile(
                            service,
                            config,
                            registration,
                            owner,
                            fixed,
                            files,
                            accepted,
                            mode,
                            &initial,
                            &observed,
                            checkpoint,
                            checkpoint_digest,
                            profile,
                            end,
                        )
                    };
                    let result = if let Some(fact) = accepted {
                        if fact.deployment != fixed.binding.to_string()
                            || fact.checkpoint != checkpoint_digest.to_string()
                            || fact.original_task
                                != RootOriginalHistoricalCompleteTaskObservationV1::data_cut_digest(
                                    &observed,
                                )
                                .to_string()
                        {
                            return Err(io::Error::other(
                                "original completed acceptance cut differs",
                            ));
                        }
                        let profile: HostAuthorityLearningProfileV1 =
                            serde_json::from_str(&fact.original_profile)
                                .map_err(io::Error::other)?;
                        check_profile(profile)
                    } else {
                        let plan: &post_a::PostALearningRuntime = self
                            .post_a
                            .as_ref()
                            .ok_or_else(|| io::Error::other("original fresh post-A plan absent"))?;
                        post_a::PostALearningRuntime::require_completed_plan(
                            plan,
                            &fixed.data.original_post_a_deployment,
                            files.freeze()?,
                        )?;
                        post_a::PostALearningRuntime::with_original_derived_profile(
                            plan,
                            service,
                            &registration.registered_identity.identity()?,
                            &proof,
                            &initial,
                            &observed,
                            &self.learning_trust,
                            end,
                            check_profile,
                        )
                    };
                    fixed.require_original()?;
                    self.metadata.require_metadata_unchanged()?;
                    RootHistoricalLearningTrustV1::revalidate(
                        &self.learning_trust,
                        service,
                        &initial,
                    )?;
                    require_end(end)?;
                    result
                },
            )
        })
    }

    fn observe_completed_profile(
        &self,
        service: &HostAuthorityService,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        fixed: &CompletedLearningRuntime,
        files: &CompletedFiles,
        accepted: Option<&RootCompletedLearningAcceptanceDataV1>,
        mode: OriginalCompletedPublicationModeV1,
        initial: &LearningIterationSnapshotV1,
        observed: &RootOriginalHistoricalCompleteTaskObservationV1,
        checkpoint: &crate::LearningIterationCheckpointRecordV1,
        checkpoint_digest: Digest32,
        profile: HostAuthorityLearningProfileV1,
        end: Instant,
    ) -> io::Result<CheckedCompletion> {
        if profile.original_initial_data()? != *initial {
            return Err(io::Error::other(
                "original frozen completed initial differs",
            ));
        }
        let scope = profile.require_cell_scope(initial)?;
        let data_cut =
            RootOriginalHistoricalCompleteTaskObservationV1::data_cut_digest(observed).to_string();
        with_original_completed_b(
            &fixed.data.independent_b,
            RootAuthorityDirectory::open(&config.state_dir).map_err(io::Error::other)?,
            initial,
            &scope,
            service,
            end,
            |b| {
                let (result, _) = with_original_completed_publication(
                    &fixed.data.publication,
                    initial,
                    &scope,
                    service,
                    config,
                    end,
                    mode,
                    |publication| {
                        CompletedFiles::with_original_records(files, end, |journals| {
                            self.with_original_completed_context(service, config, registration, owner,
                            &scope, checkpoint, observed, end, |context| {
                                let b = OriginalCompletedBReadV1::observe(b, context)?;
                                let publication = OriginalCompletedPublicationReadV1::observe(publication, context)?;
                                let verified = verify_original_completions(context, journals, &b, accepted)?;
                                if verified.verified_at > context.current_unix_seconds()?
                                    || (accepted.is_none() && verified.verified_at >= initial.request.envelope.expiry_unix_seconds)
                                {
                                    return Err(io::Error::other("first terminal acceptance must be in original work window"));
                                }
                                let fact = RootCompletedLearningAcceptanceDataV1 {
                                    schema: 1, purpose: "runtime.learning.completed-acceptance.v1".into(),
                                    initial: initial.head_digest.to_string(),
                                    target: Digest32::from_array(self.deployment.target.digest().map_err(io::Error::other)?).to_string(),
                                    deployment: fixed.binding.to_string(),
                                    original_profile: serde_json::to_string(&profile).map_err(io::Error::other)?,
                                    frozen_scope: scope.binding().to_string(),
                                    terminal_head: context.terminal().head_digest.to_string(),
                                    checkpoint: checkpoint_digest.to_string(),
                                    root_verified_at_seconds: verified.verified_at,
                                    original_task: data_cut.clone(), journals: verified.journals,
                                    signatures: verified.signatures,
                                    independent_b: b.acceptance.to_string(),
                                    publication: publication.acceptance.to_string(),
                                };
                                if accepted.is_some_and(|expected| expected != &fact) {
                                    return Err(io::Error::other("original terminal acceptance changed"));
                                }
                                fact.data_digest()?;
                                require_end(end)?;
                                Ok(CheckedCompletion { fact, publication, data_cut: data_cut.clone() })
                            })
                        })
                    },
                )?;
                require_end(end)?;
                Ok(result)
            },
        )
    }

    fn observe_completed_original_task(
        &self,
        service: &HostAuthorityService,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        read: &mut RootOriginalHistoricalTaskReadV1<'_, '_, '_, '_>,
        end: Instant,
    ) -> io::Result<(
        LearningIterationSnapshotV1,
        String,
        RootOriginalHistoricalCompleteTaskObservationV1,
    )> {
        service.with_learning_profile(
            config,
            registration,
            owner,
            &self.deployment.initial,
            |initial, proof| {
                if self.profile.require_original_context(
                    &registration.registered_identity.identity()?,
                    &proof,
                    &self.deployment.initial,
                )? != initial
                    || self.phase.load(Ordering::Acquire) != SERVING
                {
                    return Err(io::Error::other(
                        "completed original task recipient differs",
                    ));
                }
                self.metadata.require_metadata_unchanged()?;
                RootHistoricalLearningTrustV1::revalidate(&self.learning_trust, service, &initial)?;
                RootOriginalHistoricalTaskReadV1::require_original_target(
                    read,
                    &self.deployment.target,
                )?;
                let observed = RootOriginalHistoricalTaskReadV1::observe_original_task(
                    read,
                    |identity| {
                        RootHistoricalSourceInputsV1::open_original_source_deployment(
                            &self.deployment.source_deployment,
                            identity,
                        )
                    },
                    || {
                        RootInitialRunStartFilesV1::open_original_deployment(
                            &self.deployment.run_start_deployment,
                        )
                        .map(Arc::new)
                    },
                )?;
                let ledger =
                    RootOriginalHistoricalCompleteTaskObservationV1::ledger_read_data(&observed)?;
                RootHistoricalLearningTrustV1::require_original_ledger(
                    &self.learning_trust,
                    &ledger,
                )?;
                self.metadata.require_metadata_unchanged()?;
                RootHistoricalLearningTrustV1::revalidate(&self.learning_trust, service, &initial)?;
                require_end(end)?;
                Ok((initial, proof, observed))
            },
        )
    }
}
