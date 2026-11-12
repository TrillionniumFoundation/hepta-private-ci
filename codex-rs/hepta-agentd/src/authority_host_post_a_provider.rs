//! The fixed post-A operation derives and registers under all original
//! historical refusal arms. No owner handoff escapes until their postchecks.

use super::*;
use crate::root_historical_task_read_protocol::POST_A_PURPOSE;
use crate::root_historical_task_read_protocol::PostAFrozenLearningResponseV1;

impl HistoricalTaskReadRuntime {
    pub(super) fn install_original_frozen_learning(
        &self,
        service: &HostAuthorityService,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        request_id: u64,
        end: Instant,
    ) -> io::Result<Vec<u8>> {
        let post_a: &post_a::PostALearningRuntime = self
            .post_a
            .as_ref()
            .ok_or_else(|| io::Error::other("original post-A deployment missing"))?;
        let (installation, reply) =
            RootRetainedHistoricalCompleteTaskV1::with_original_historical_task(
                &self.task,
                service,
                end,
                |read| {
                    require_end(end)?;
                    self.metadata.require_metadata_unchanged()?;
                    // Finish this original unfrozen context before the derived V2
                    // registration takes its own invocation of the SAME Root writer.
                    let (initial, proof, observed) = service.with_learning_profile(
                        config,
                        registration,
                        owner,
                        &self.deployment.initial,
                        |initial, proof| {
                            let expected = self.profile.require_original_context(
                                &registration.registered_identity.identity()?,
                                &proof,
                                &self.deployment.initial,
                            )?;
                            if expected != initial || self.phase.load(Ordering::Acquire) != SERVING
                            {
                                return Err(io::Error::other("original post-A recipient changed"));
                            }
                            RootHistoricalLearningTrustV1::revalidate(
                                &self.learning_trust,
                                service,
                                &initial,
                            )?;
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
                                RootOriginalHistoricalCompleteTaskObservationV1::ledger_read_data(
                                    &observed,
                                )?;
                            RootHistoricalLearningTrustV1::require_original_ledger(
                                &self.learning_trust,
                                &ledger,
                            )?;
                            require_end(end)?;
                            Ok((initial, proof, observed))
                        },
                    )?;
                    let data_cut =
                        RootOriginalHistoricalCompleteTaskObservationV1::data_cut_digest(&observed)
                            .to_string();
                    let installation = post_a::PostALearningRuntime::prepare_original_installation(
                        post_a,
                        service,
                        config,
                        registration,
                        owner,
                        &proof,
                        &initial,
                        &observed,
                        &self.learning_trust,
                        end,
                    )?;
                    let reply = serde_json::to_vec(&PostAFrozenLearningResponseV1 {
                        schema: 1,
                        purpose: POST_A_PURPOSE.into(),
                        request_id,
                        profile: self.profile.binding.clone(),
                        data_cut,
                        frozen_scope: installation.frozen_scope.clone(),
                    })
                    .map_err(io::Error::other)?;
                    if reply.is_empty() || reply.len() > WIRE_BOUND {
                        return Err(io::Error::other(
                            "post-A acknowledgement exceeds original bound",
                        ));
                    }
                    self.metadata.require_metadata_unchanged()?;
                    RootHistoricalLearningTrustV1::revalidate(
                        &self.learning_trust,
                        service,
                        &initial,
                    )?;
                    require_end(end)?;
                    Ok((installation, reply))
                },
            )?;
        // Every physical reread and durable refusal Ready transition finished
        // above. The freeze's two shared locks also released before delivery.
        require_end(end)?;
        let submitter = self
            .post_a_submitter
            .try_lock()
            .map_err(|_| io::Error::other("original post-A submission busy"))?
            .take()
            .ok_or_else(|| io::Error::other("original post-A submission already consumed"))?;
        post_a_worker::PostALearningSubmitter::submit(submitter, installation, end)?;
        require_end(end)?;
        Ok(reply)
    }
}
