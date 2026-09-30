//! Bounded execution of the existing canonical owner composition.

use super::*;
use crate::intelligence_observability::AgentdIntelligenceWorkerStateV1;

#[path = "intelligence_prepared_integrity.rs"]
mod prepared_integrity;
#[path = "intelligence_worker_watchdog.rs"]
mod watchdog;

pub(super) struct AgentdIntelligenceWorkerV1<T> {
    handle: tokio::task::JoinHandle<T>,
    state: Arc<AgentdIntelligenceWorkerStateV1>,
}

impl<T> AgentdIntelligenceWorkerV1<T> {
    fn mark_timed_out(&self) -> bool {
        self.state.mark_timed_out()
    }

    #[cfg(test)]
    pub(super) fn abort(&self) {
        self.handle.abort();
    }
}

impl<T> std::future::Future for AgentdIntelligenceWorkerV1<T> {
    type Output = Result<T, tokio::task::JoinError>;

    fn poll(
        mut self: std::pin::Pin<&mut Self>,
        context: &mut std::task::Context<'_>,
    ) -> std::task::Poll<Self::Output> {
        let this = self.as_mut().get_mut();
        std::future::Future::poll(std::pin::Pin::new(&mut this.handle), context)
    }
}

impl AgentdIntelligenceProductRunnerV1 {
    pub fn new(
        authority_file: PathBuf,
        authority_verifier: IntelligenceAuthorityVerifierV1,
    ) -> Result<Self, AgentdIntelligenceProductError> {
        if !authority_file.is_absolute()
            || authority_verifier.signer_id.is_empty()
            || authority_verifier.signer_id.len() > 128
            || authority_verifier.signer_id.as_bytes().contains(&0)
            || VerifyingKey::from_bytes(&authority_verifier.verifying_key).is_err()
        {
            return Err(AgentdIntelligenceProductError::InvalidAuthorityVerifier);
        }
        Ok(Self {
            worker_slots: Arc::new(tokio::sync::Semaphore::new(MAX_CANONICAL_OWNER_WORKERS)),
            authority_file,
            authority_verifier,
            authority_rollback: None,
            evaluation_trust: None,
            telemetry: Arc::new(crate::AgentdIntelligenceTelemetryV1::new(
                MAX_CANONICAL_OWNER_WORKERS,
            )),
            hard_timeout_process_exit_grace: None,
        })
    }

    /// Install the independently retained monotonic witness used by every
    /// signed owner-manifest read. The witness must not be the manifest.
    pub fn with_authority_rollback_guard(
        mut self,
        guard: Arc<crate::IntelligenceAuthorityRollbackGuardV1>,
    ) -> Result<Self, AgentdIntelligenceProductError> {
        if self.authority_rollback.is_some() || guard.path() == self.authority_file {
            return Err(AgentdIntelligenceProductError::InvalidAuthorityRollback);
        }
        self.authority_rollback = Some(guard);
        Ok(self)
    }

    pub fn with_evaluation_trust(
        mut self,
        trust: codex_hepta_learning_ledger::ActivatedLearningTrustV1,
    ) -> Result<Self, AgentdIntelligenceProductError> {
        if self.evaluation_trust.is_some() {
            return Err(AgentdIntelligenceProductError::InvalidAuthorityVerifier);
        }
        self.evaluation_trust = Some(Arc::new(trust));
        Ok(self)
    }

    /// Install process-level containment required by canonical product
    /// composition. Supervision starts with the worker, independent of whether
    /// its request future is polled, dropped or aborted.
    pub fn with_hard_timeout_process_exit(
        mut self,
        grace: Duration,
    ) -> Result<Self, AgentdIntelligenceProductError> {
        if grace.is_zero() || grace > Duration::from_secs(300) {
            return Err(AgentdIntelligenceProductError::InvalidWorkerPolicy);
        }
        self.hard_timeout_process_exit_grace = Some(grace);
        Ok(self)
    }

    #[must_use]
    pub fn telemetry(&self) -> Arc<crate::AgentdIntelligenceTelemetryV1> {
        Arc::clone(&self.telemetry)
    }

    #[must_use]
    pub fn canonical_profile_ready(&self) -> bool {
        self.authority_rollback.is_some() && self.hard_timeout_process_exit_grace.is_some()
    }

    #[must_use]
    pub fn authority_rollback_path(&self) -> Option<&std::path::Path> {
        self.authority_rollback.as_deref().map(
            super::super::intelligence_authority_rollback::IntelligenceAuthorityRollbackGuardV1::path,
        )
    }

    #[must_use]
    pub fn capability_profile_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.agentd.intelligence-capability-profile.v2\0".to_vec();
        let path = self.authority_file.to_string_lossy();
        for value in [
            path.as_bytes(),
            self.authority_verifier.signer_id.as_bytes(),
        ] {
            bytes.extend_from_slice(&(value.len() as u64).to_be_bytes());
            bytes.extend_from_slice(value);
        }
        bytes.extend_from_slice(&self.authority_verifier.verifying_key);
        bytes.extend_from_slice(&(MAX_CANONICAL_OWNER_WORKERS as u64).to_be_bytes());
        match self.hard_timeout_process_exit_grace {
            Some(grace) => {
                bytes.push(1);
                bytes.extend_from_slice(&grace.as_secs().to_be_bytes());
                bytes.extend_from_slice(&grace.subsec_nanos().to_be_bytes());
            }
            None => bytes.push(0),
        }
        match self.authority_rollback.as_ref() {
            Some(guard) => {
                bytes.push(1);
                bytes.extend_from_slice(guard.profile_digest().as_array());
            }
            None => bytes.push(0),
        }
        match self.evaluation_trust.as_ref() {
            Some(trust) => {
                bytes.push(1);
                bytes.extend_from_slice(trust.distribution_digest().as_array());
                bytes.extend_from_slice(&trust.generation().to_be_bytes());
            }
            None => bytes.push(0),
        }
        Digest32::of_bytes(&bytes)
    }

    #[must_use]
    pub const fn hard_timeout_process_exit_enabled(&self) -> bool {
        self.hard_timeout_process_exit_grace.is_some()
    }

    #[cfg(test)]
    pub(super) fn spawn_owner_work<F, T>(
        &self,
        work: F,
    ) -> Result<AgentdIntelligenceWorkerV1<T>, AgentdIntelligenceProductError>
    where
        F: FnOnce() -> T + Send + 'static,
        T: Send + 'static,
    {
        self.spawn_owner_work_with_budget(work, Duration::from_secs(300))
    }

    fn spawn_owner_work_with_budget<F, T>(
        &self,
        work: F,
        budget: Duration,
    ) -> Result<AgentdIntelligenceWorkerV1<T>, AgentdIntelligenceProductError>
    where
        F: FnOnce() -> T + Send + 'static,
        T: Send + 'static,
    {
        if budget.is_zero() {
            return Err(AgentdIntelligenceProductError::TimedOut);
        }
        let queue_started = Instant::now();
        let permit_result = Arc::clone(&self.worker_slots).try_acquire_owned();
        self.telemetry
            .record_queue_wait(elapsed_micros(queue_started.elapsed()));
        let permit = match permit_result {
            Ok(permit) => permit,
            Err(_) => {
                self.telemetry.record_busy();
                return Err(AgentdIntelligenceProductError::Busy);
            }
        };
        let guard = self.telemetry.worker_started();
        let state = guard.state();
        let completion = watchdog::WorkerCompletionV1::supervise(
            budget,
            self.hard_timeout_process_exit_grace,
            Arc::clone(&state),
            Arc::clone(&self.telemetry),
        )
        .map_err(|_| AgentdIntelligenceProductError::WorkerCrashed)?;
        let handle = tokio::task::spawn_blocking(move || {
            // Drop order matters: disarm/join the watchdog, then publish worker
            // completion, then release capacity. Request cancellation owns none.
            let _permit = permit;
            let _guard = guard;
            let _completion = completion;
            work()
        });
        Ok(AgentdIntelligenceWorkerV1 { handle, state })
    }

    fn record_canonical_error(&self, error: &CanonicalIntelligenceError) {
        match error {
            CanonicalIntelligenceError::FreshnessUnavailable(_)
            | CanonicalIntelligenceError::StaleOwner(_)
            | CanonicalIntelligenceError::KeyDrift(_)
            | CanonicalIntelligenceError::AuthorityEpochDrift(_)
            | CanonicalIntelligenceError::RevocationFrontierDrift(_) => {
                self.telemetry.record_currentness_rejection();
            }
            CanonicalIntelligenceError::PortFailure { stage, class, .. } => {
                self.telemetry.record_stage_failure(*stage, *class);
                self.telemetry.record_canonical_rejection();
            }
            _ => self.telemetry.record_canonical_rejection(),
        }
    }

    pub(crate) async fn build_host_invocation(
        &self,
        provider: Arc<dyn crate::AgentdIntelligenceInvocationProviderV1>,
        identity: crate::AgentdIdentity,
        record: codex_hepta_learning_ledger::RunStartRecordV1,
    ) -> Result<crate::AgentdIntelligenceInvocationV1, crate::AgentdError> {
        let deadline_ms = record.admission.deadline_unix_micros / 1_000;
        let now =
            wall_clock_ms().map_err(|error| crate::AgentdError::Protocol(error.to_string()))?;
        let remaining = deadline_ms
            .checked_sub(now)
            .filter(|value| *value != 0)
            .ok_or_else(|| {
                crate::AgentdError::Protocol("invocation deadline elapsed".to_string())
            })?;
        let budget = Duration::from_millis(remaining.min(30_000));
        let started = Instant::now();
        let mut worker = self
            .spawn_owner_work_with_budget(move || provider.build(&identity, &record), budget)
            .map_err(|error| crate::AgentdError::Protocol(error.to_string()))?;
        let joined = match timeout(budget, &mut worker).await {
            Ok(joined) => joined,
            Err(_) => {
                worker.mark_timed_out();
                return Err(crate::AgentdError::Protocol(
                    "invocation deadline elapsed".to_string(),
                ));
            }
        };
        let observed_at =
            wall_clock_ms().map_err(|error| crate::AgentdError::Protocol(error.to_string()))?;
        if worker.state.timed_out() || started.elapsed() >= budget || observed_at >= deadline_ms {
            worker.mark_timed_out();
            return Err(crate::AgentdError::Protocol(
                "invocation deadline elapsed".to_string(),
            ));
        }
        match joined {
            Ok(result) => result,
            Err(error) => Err(crate::AgentdError::Protocol(format!(
                "invocation worker failed: {error}"
            ))),
        }
    }

    pub async fn prepare(
        &self,
        coordinator: &crate::AgentRunCoordinator,
        request: CanonicalIntelligenceRunRequestV1,
        inputs: AgentdIntelligenceOwnerInputsV1,
    ) -> Result<AgentdIntelligenceProductOutcomeV1, AgentdIntelligenceProductError> {
        let composition = coordinator.composition().clone();
        self.prepare_for_composition(&composition, request, inputs)
            .await
    }

    pub async fn prepare_for_composition(
        &self,
        composition: &crate::RuntimeComposition,
        request: CanonicalIntelligenceRunRequestV1,
        mut inputs: AgentdIntelligenceOwnerInputsV1,
    ) -> Result<AgentdIntelligenceProductOutcomeV1, AgentdIntelligenceProductError> {
        let started = Instant::now();
        let prompt_delivery = inputs.prompt_delivery.clone();
        let Some(run_identity) = inputs.run_identity.take() else {
            self.telemetry.record_run_identity_rejection();
            return Err(AgentdIntelligenceProductError::MissingRunIdentity);
        };
        if run_identity
            .validate_process_binding(&composition.agent_id, composition.supervisor_generation)
            .is_err()
            || run_identity.validate_request(&request).is_err()
        {
            self.telemetry.record_run_identity_rejection();
            return Err(AgentdIntelligenceProductError::RunIdentityMismatch);
        }
        let candidate_ids =
            canonical_candidate_ids_v1(&request.legal_candidates).map_err(|error| {
                self.record_canonical_error(&error);
                AgentdIntelligenceProductError::Canonical(error)
            })?;
        self.telemetry.record_candidate_count(candidate_ids.len());
        let mut intuition_ids = inputs
            .intuition_request
            .candidates
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect::<Vec<_>>();
        intuition_ids.sort();
        if candidate_ids != intuition_ids {
            self.telemetry.record_canonical_rejection();
            return Err(AgentdIntelligenceProductError::CandidateSetMismatch);
        }
        let snapshot = request.snapshot.clone();
        let request_for_validation = request.clone();
        let total_timeout_micros = request.budget.total_micros;
        let started_ms = wall_clock_ms()?;
        let remaining_ms = run_identity
            .deadline_ms
            .checked_sub(started_ms)
            .filter(|remaining| *remaining != 0)
            .ok_or(AgentdIntelligenceProductError::TimedOut)?;
        let timeout_micros = total_timeout_micros.min(remaining_ms.saturating_mul(1_000));
        let budget = Duration::from_micros(timeout_micros);
        let authority_file = self.authority_file.clone();
        let authority_verifier = self.authority_verifier.clone();
        let authority_rollback = self.authority_rollback.clone();
        let evaluation_trust = self.evaluation_trust.clone();
        let signed_evaluation = inputs.signed_evaluation.take();
        let run_id = request.run_id.clone();
        let worker_telemetry = Arc::clone(&self.telemetry);
        let worker_budget = budget.saturating_sub(started.elapsed());
        let mut worker = self.spawn_owner_work_with_budget(
            move || {
                // All signed-evaluation authority-file I/O is inside the supervised
                // worker; a blocking file read cannot escape its resource lifetime.
                let mut oracle = FileBackedFreshnessOracleV1::new_observed(
                    authority_file,
                    authority_verifier,
                    Arc::clone(&worker_telemetry),
                )
                .with_rollback(authority_rollback);
                let evaluation_session = match signed_evaluation {
                    None => None,
                    Some(signed) => {
                        let trust = evaluation_trust.ok_or_else(|| {
                            CanonicalIntelligenceError::FreshnessUnavailable(run_id.clone())
                        })?;
                        let owner_id = StableId::new("learning.eval")
                            .map_err(|_| CanonicalIntelligenceError::Arithmetic)?;
                        Some(AgentdEvaluationSessionV1 {
                            run_id,
                            current_owner: oracle.current(&owner_id)?,
                            trust,
                            signed,
                        })
                    }
                };
                let mut ports =
                    AgentdOwnerPortsV1::new(inputs, evaluation_session, worker_telemetry);
                prepare_intelligence_run(request, &mut ports, &mut oracle)
            },
            worker_budget,
        )?;
        let joined = match timeout(worker_budget, &mut worker.handle).await {
            Ok(value) => value,
            Err(_) => {
                worker.mark_timed_out();
                worker.handle.abort();
                return Err(AgentdIntelligenceProductError::TimedOut);
            }
        };
        if worker.state.timed_out() || started.elapsed() >= budget {
            worker.mark_timed_out();
            return Err(AgentdIntelligenceProductError::TimedOut);
        }
        let outcome = match joined {
            Ok(Ok(value)) => value,
            Ok(Err(error)) => {
                self.record_canonical_error(&error);
                return Err(AgentdIntelligenceProductError::Canonical(error));
            }
            Err(_) => {
                self.telemetry.record_worker_crash();
                return Err(AgentdIntelligenceProductError::WorkerCrashed);
            }
        };
        debug_assert!(worker.state.finished());
        if let Err(error) = validate_canonical_outcome_v1(&request_for_validation, &outcome) {
            self.record_canonical_error(&error);
            return Err(AgentdIntelligenceProductError::Canonical(error));
        }
        match outcome {
            CanonicalRunOutcomeV1::Ready(envelope) => {
                let authority_file = self.authority_file.clone();
                let verifier = self.authority_verifier.clone();
                let rollback = self.authority_rollback.clone();
                let telemetry = Arc::clone(&self.telemetry);
                let final_snapshot = snapshot.clone();
                let remaining = budget.saturating_sub(started.elapsed());
                if remaining.is_zero() {
                    worker.mark_timed_out();
                    return Err(AgentdIntelligenceProductError::TimedOut);
                }
                let mut final_check = self.spawn_owner_work_with_budget(
                    move || {
                        let mut oracle = FileBackedFreshnessOracleV1::new_observed(
                            authority_file,
                            verifier,
                            telemetry,
                        )
                        .with_rollback(rollback);
                        validate_current_snapshot(&final_snapshot, &mut oracle)
                    },
                    remaining,
                )?;
                let joined = match timeout(remaining, &mut final_check.handle).await {
                    Ok(joined) => joined,
                    Err(_) => {
                        final_check.mark_timed_out();
                        final_check.handle.abort();
                        return Err(AgentdIntelligenceProductError::TimedOut);
                    }
                };
                if final_check.state.timed_out()
                    || started.elapsed() >= budget
                    || wall_clock_ms()? >= run_identity.deadline_ms
                {
                    final_check.mark_timed_out();
                    return Err(AgentdIntelligenceProductError::TimedOut);
                }
                match joined {
                    Ok(Ok(())) => {}
                    Ok(Err(error)) => {
                        self.record_canonical_error(&error);
                        return Err(AgentdIntelligenceProductError::Canonical(error));
                    }
                    Err(_) => {
                        self.telemetry.record_worker_crash();
                        return Err(AgentdIntelligenceProductError::WorkerCrashed);
                    }
                }
                let mut bytes = b"hepta.agentd.intelligence-dispatch-proposal.v1\0".to_vec();
                bytes.extend_from_slice(envelope.envelope_digest.as_array());
                bytes.extend_from_slice(snapshot.revocation_frontier_digest().as_array());
                bytes.extend_from_slice(run_identity.request_digest.as_array());
                let dispatch_proposal_digest = Digest32::of_bytes(&bytes);
                let run_snapshot = crate::AgentRunSnapshot {
                    run_id: run_identity.run_id.to_string(),
                    request_digest: run_identity.request_digest.to_string(),
                    objective_digest: run_identity.objective_digest.to_string(),
                    body_digest: run_identity.body_digest.to_string(),
                    artifact_set_digest: run_identity.artifact_set_digest.to_string(),
                    authority_epoch: run_identity.authority_epoch,
                    generation: run_identity.generation,
                    fence_digest: run_identity.fence_digest.to_string(),
                    deadline_ms: run_identity.deadline_ms,
                };
                let context_attachment = crate::AgentContextAttachment {
                    run_id: run_snapshot.run_id.clone(),
                    request_digest: run_snapshot.request_digest.clone(),
                    objective_digest: run_snapshot.objective_digest.clone(),
                    body_digest: run_snapshot.body_digest.clone(),
                    artifact_set_digest: run_snapshot.artifact_set_digest.clone(),
                    authority_epoch: run_snapshot.authority_epoch,
                    generation: run_snapshot.generation,
                    fence_digest: run_snapshot.fence_digest.clone(),
                    deadline_ms: run_snapshot.deadline_ms,
                    context_digest: envelope.context_receipt_digest.to_string(),
                    compilation_receipt_digest: envelope.envelope_digest.to_string(),
                };
                let prepared = PreparedAgentdIntelligenceRunV1 {
                    envelope,
                    dispatch_proposal_digest,
                    snapshot,
                    candidate_ids,
                    run_snapshot,
                    context_attachment,
                    prompt_delivery,
                };
                prepared
                    .validate_integrity()
                    .map_err(AgentdIntelligenceProductError::Canonical)?;
                // Projection and integrity verification remain part of the
                // cognition budget, including prompt-delivery serialization.
                if started.elapsed() >= budget || wall_clock_ms()? >= run_identity.deadline_ms {
                    final_check.mark_timed_out();
                    return Err(AgentdIntelligenceProductError::TimedOut);
                }
                self.telemetry.record_ready();
                Ok(AgentdIntelligenceProductOutcomeV1::Ready(prepared))
            }
            CanonicalRunOutcomeV1::Abstained(_) => {
                self.telemetry.record_abstained();
                Ok(AgentdIntelligenceProductOutcomeV1::Abstained)
            }
            CanonicalRunOutcomeV1::SlowPath(_) => {
                self.telemetry.record_slow_path();
                Ok(AgentdIntelligenceProductOutcomeV1::SlowPath)
            }
        }
    }

    pub async fn prepare_and_admit(
        &self,
        coordinator: &mut crate::AgentRunCoordinator,
        request: CanonicalIntelligenceRunRequestV1,
        inputs: AgentdIntelligenceOwnerInputsV1,
    ) -> Result<AgentdIntelligenceAdmittedOutcomeV1, AgentdIntelligenceProductError> {
        match self.prepare(coordinator, request, inputs).await? {
            AgentdIntelligenceProductOutcomeV1::Ready(prepared) => {
                let snapshot = prepared.run_snapshot();
                let admitted = coordinator
                    .start_bound_run(
                        wall_clock_ms()?,
                        crate::RunSnapshot {
                            run_id: snapshot.run_id,
                            request_digest: snapshot.request_digest,
                            objective_digest: snapshot.objective_digest,
                            body_digest: snapshot.body_digest,
                            artifact_set_digest: snapshot.artifact_set_digest,
                            authority_epoch: snapshot.authority_epoch,
                            generation: snapshot.generation,
                            fence_digest: snapshot.fence_digest,
                            deadline_ms: snapshot.deadline_ms,
                        },
                    )
                    .map_err(AgentdIntelligenceProductError::Run)?;
                let attachment = prepared.context_attachment();
                let run_receipt = coordinator
                    .attach_context(
                        wall_clock_ms()?,
                        admitted.revision,
                        crate::ContextAttachment {
                            run_id: attachment.run_id,
                            request_digest: attachment.request_digest,
                            objective_digest: attachment.objective_digest,
                            body_digest: attachment.body_digest,
                            artifact_set_digest: attachment.artifact_set_digest,
                            authority_epoch: attachment.authority_epoch,
                            generation: attachment.generation,
                            fence_digest: attachment.fence_digest,
                            deadline_ms: attachment.deadline_ms,
                            context_digest: attachment.context_digest,
                            compilation_receipt_digest: attachment.compilation_receipt_digest,
                        },
                    )
                    .map_err(AgentdIntelligenceProductError::Run)?;
                Ok(AgentdIntelligenceAdmittedOutcomeV1::Ready {
                    prepared,
                    run_receipt,
                })
            }
            AgentdIntelligenceProductOutcomeV1::Abstained => {
                Ok(AgentdIntelligenceAdmittedOutcomeV1::Abstained)
            }
            AgentdIntelligenceProductOutcomeV1::SlowPath => {
                Ok(AgentdIntelligenceAdmittedOutcomeV1::SlowPath)
            }
        }
    }

    #[cfg(feature = "qualification-legacy-learning-write")]
    pub fn append_decision(
        &self,
        journal: &mut DurableLedger,
        expected_predecessor: Digest32,
        prepared: &PreparedAgentdIntelligenceRunV1,
        episode_id: StableId,
        policy_id: StableId,
    ) -> Result<AppendReceipt, AgentdIntelligenceLedgerError> {
        prepared
            .validate_integrity()
            .map_err(AgentdIntelligenceLedgerError::Currentness)?;
        let AdvisoryDecisionV1::Selected {
            candidate_id,
            propensity,
        } = &prepared.envelope.decision.decision
        else {
            return Err(AgentdIntelligenceLedgerError::NotSelected);
        };
        let event = LedgerEvent::Decision(EpisodeDecision {
            record_id: prepared.envelope.run_id.clone(),
            episode_id,
            objective_digest: prepared.envelope.objective_digest,
            policy_id,
            candidate_ids: prepared.candidate_ids.clone(),
            selected_candidate_id: candidate_id.clone(),
            selected_propensity: *propensity,
            completeness: CandidateSetCompleteness::Complete,
            support_digest: prepared.dispatch_proposal_digest,
        });
        self.append_event(
            journal,
            expected_predecessor,
            prepared.snapshot.clone(),
            event,
        )
    }

    #[cfg(feature = "qualification-legacy-learning-write")]
    #[allow(clippy::too_many_arguments)]
    pub fn append_outcome(
        &self,
        journal: &mut DurableLedger,
        expected_predecessor: Digest32,
        prepared: &PreparedAgentdIntelligenceRunV1,
        outcome_record_id: StableId,
        outcome_id: StableId,
        episode_id: StableId,
        observer_id: StableId,
        value: FixedQ32,
        finality: OutcomeFinality,
        support_digest: Digest32,
    ) -> Result<AppendReceipt, AgentdIntelligenceLedgerError> {
        prepared
            .validate_integrity()
            .map_err(AgentdIntelligenceLedgerError::Currentness)?;
        if support_digest.is_zero() {
            return Err(AgentdIntelligenceLedgerError::InvalidOutcome);
        }
        let event = LedgerEvent::Outcome(OutcomeObservation {
            record_id: outcome_record_id,
            outcome_id,
            episode_id,
            observer_id,
            value,
            finality,
            support_digest,
        });
        self.append_event(
            journal,
            expected_predecessor,
            prepared.snapshot.clone(),
            event,
        )
    }

    #[cfg(feature = "qualification-legacy-learning-write")]
    fn append_event(
        &self,
        journal: &mut DurableLedger,
        expected_predecessor: Digest32,
        snapshot: CanonicalIntelligenceSnapshotV1,
        event: LedgerEvent,
    ) -> Result<AppendReceipt, AgentdIntelligenceLedgerError> {
        let mut oracle = FileBackedFreshnessOracleV1::new(
            self.authority_file.clone(),
            self.authority_verifier.clone(),
        )
        .with_rollback(self.authority_rollback.clone());
        validate_current_snapshot(&snapshot, &mut oracle)
            .map_err(AgentdIntelligenceLedgerError::Currentness)?;
        match journal.append_qualification(expected_predecessor, event.clone()) {
            Ok(receipt) => Ok(receipt),
            Err(DurableLedgerError::Indeterminate | DurableLedgerError::Io(_)) => Err(
                AgentdIntelligenceLedgerError::Indeterminate(PendingIntelligenceLedgerAppendV1 {
                    expected_predecessor,
                    snapshot,
                    event,
                }),
            ),
            Err(error) => Err(AgentdIntelligenceLedgerError::Ledger(error)),
        }
    }

    #[cfg(feature = "qualification-legacy-learning-write")]
    pub fn reconcile_ledger_append(
        &self,
        journal: &mut DurableLedger,
        pending: PendingIntelligenceLedgerAppendV1,
    ) -> Result<AppendReceipt, AgentdIntelligenceLedgerError> {
        let mut oracle = FileBackedFreshnessOracleV1::new(
            self.authority_file.clone(),
            self.authority_verifier.clone(),
        )
        .with_rollback(self.authority_rollback.clone());
        validate_current_snapshot(&pending.snapshot, &mut oracle)
            .map_err(AgentdIntelligenceLedgerError::Currentness)?;
        journal
            .append_qualification(pending.expected_predecessor, pending.event)
            .map_err(AgentdIntelligenceLedgerError::Ledger)
    }
}

fn elapsed_micros(value: Duration) -> u64 {
    u64::try_from(value.as_micros()).unwrap_or(u64::MAX)
}
