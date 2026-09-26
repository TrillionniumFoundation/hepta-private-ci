//! Bounded execution of the existing canonical owner composition.

use super::*;

struct AgentdIntelligenceWorkerV1<T> {
    handle: tokio::task::JoinHandle<T>,
    timed_out: Arc<std::sync::atomic::AtomicBool>,
    finished: Arc<std::sync::atomic::AtomicBool>,
}

impl<T> AgentdIntelligenceWorkerV1<T> {
    fn mark_timed_out(&self) {
        self.timed_out
            .store(true, std::sync::atomic::Ordering::Release);
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
            evaluation_trust: None,
            telemetry: Arc::new(crate::AgentdIntelligenceTelemetryV1::new(
                MAX_CANONICAL_OWNER_WORKERS,
            )),
            hard_timeout_process_exit_grace: None,
        })
    }

    /// Configure trust that the host has already authenticated against its root.
    /// No request or wire field can install an evaluator key or grant itself trust.
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

    /// Explicit production isolation policy for synchronous owner code that
    /// cannot cooperatively cancel. If a timed-out blocking worker is still
    /// alive after this grace, Agentd exits with a dedicated software-error code
    /// and the Supervisor recovers a fresh fenced process generation. The policy
    /// is opt-in so library tests and compatibility profiles never terminate the
    /// embedding process unexpectedly.
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
    pub fn capability_profile_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.agentd.intelligence-capability-profile.v1\0".to_vec();
        bytes.extend_from_slice(self.authority_file.to_string_lossy().as_bytes());
        bytes.extend_from_slice(self.authority_verifier.signer_id.as_bytes());
        bytes.extend_from_slice(&self.authority_verifier.verifying_key);
        bytes.extend_from_slice(&(MAX_CANONICAL_OWNER_WORKERS as u64).to_be_bytes());
        let grace_ms = self
            .hard_timeout_process_exit_grace
            .map(|value| u64::try_from(value.as_millis()).unwrap_or(u64::MAX))
            .unwrap_or(0);
        bytes.extend_from_slice(&grace_ms.to_be_bytes());
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

    // The permit belongs to the worker, not the request future. Aborting a
    // running spawn_blocking task cannot stop its computation; releasing its
    // permit on request timeout would allow unbounded abandoned work.
    fn spawn_owner_work<F, T>(
        &self,
        work: F,
    ) -> Result<AgentdIntelligenceWorkerV1<T>, AgentdIntelligenceProductError>
    where
        F: FnOnce() -> T + Send + 'static,
        T: Send + 'static,
    {
        let permit = match Arc::clone(&self.worker_slots).try_acquire_owned() {
            Ok(permit) => permit,
            Err(_) => {
                self.telemetry.record_busy();
                return Err(AgentdIntelligenceProductError::Busy);
            }
        };
        let guard = self.telemetry.worker_started();
        let timed_out = guard.timed_out_flag();
        let finished = guard.finished_flag();
        let handle = tokio::task::spawn_blocking(move || {
            let _permit = permit;
            let _guard = guard;
            work()
        });
        Ok(AgentdIntelligenceWorkerV1 {
            handle,
            timed_out,
            finished,
        })
    }

    fn arm_hard_timeout_exit(&self, finished: Arc<std::sync::atomic::AtomicBool>) {
        let Some(grace) = self.hard_timeout_process_exit_grace else {
            return;
        };
        let telemetry = Arc::clone(&self.telemetry);
        tokio::spawn(async move {
            tokio::time::sleep(grace).await;
            if !finished.load(std::sync::atomic::Ordering::Acquire) {
                telemetry.record_hard_timeout_trip();
                // EX_SOFTWARE. The process generation is fenced by Supervisor
                // recovery; no in-process authority survives this boundary.
                std::process::exit(70);
            }
        });
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

    /// Run the seven-owner preparation against one frozen Agentd composition
    /// without retaining the run-coordinator mutex across owner execution.
    pub async fn prepare_for_composition(
        &self,
        composition: &crate::RuntimeComposition,
        request: CanonicalIntelligenceRunRequestV1,
        mut inputs: AgentdIntelligenceOwnerInputsV1,
    ) -> Result<AgentdIntelligenceProductOutcomeV1, AgentdIntelligenceProductError> {
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

        let candidate_ids = match canonical_candidate_ids_v1(&request.legal_candidates) {
            Ok(value) => value,
            Err(error) => {
                self.record_canonical_error(&error);
                return Err(AgentdIntelligenceProductError::Canonical(error));
            }
        };
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
        let remaining_ms = match run_identity
            .deadline_ms
            .checked_sub(started_ms)
            .filter(|remaining| *remaining != 0)
        {
            Some(value) => value,
            None => {
                self.telemetry.record_run_identity_rejection();
                return Err(AgentdIntelligenceProductError::RunIdentityMismatch);
            }
        };
        let remaining_micros = remaining_ms.saturating_mul(1_000);
        let timeout_micros = total_timeout_micros.min(remaining_micros);
        let authority_file = self.authority_file.clone();
        let authority_verifier = self.authority_verifier.clone();
        let evaluation_session = match inputs.signed_evaluation.take() {
            None => None,
            Some(signed) => {
                let trust = self
                    .evaluation_trust
                    .as_ref()
                    .ok_or(AgentdIntelligenceProductError::InvalidAuthorityVerifier)?;
                let mut oracle = FileBackedFreshnessOracleV1::new_observed(
                    authority_file.clone(),
                    authority_verifier.clone(),
                    Arc::clone(&self.telemetry),
                );
                let owner_id = StableId::new("learning.eval")
                    .map_err(|_| AgentdIntelligenceProductError::InvalidAuthorityVerifier)?;
                let current_owner = match oracle.current(&owner_id) {
                    Ok(value) => value,
                    Err(error) => {
                        self.record_canonical_error(&error);
                        return Err(AgentdIntelligenceProductError::Canonical(error));
                    }
                };
                Some(AgentdEvaluationSessionV1 {
                    run_id: request.run_id.clone(),
                    current_owner,
                    trust: Arc::clone(trust),
                    signed,
                })
            }
        };
        let worker_telemetry = Arc::clone(&self.telemetry);
        let mut worker = self.spawn_owner_work(move || {
            let mut ports =
                AgentdOwnerPortsV1::new(inputs, evaluation_session, Arc::clone(&worker_telemetry));
            let mut oracle = FileBackedFreshnessOracleV1::new_observed(
                authority_file,
                authority_verifier,
                worker_telemetry,
            );
            prepare_intelligence_run(request, &mut ports, &mut oracle)
        })?;
        let joined = match timeout(Duration::from_micros(timeout_micros), &mut worker.handle).await
        {
            Ok(value) => value,
            Err(_) => {
                worker.mark_timed_out();
                worker.handle.abort();
                self.telemetry.record_request_timeout();
                self.arm_hard_timeout_exit(Arc::clone(&worker.finished));
                return Err(AgentdIntelligenceProductError::TimedOut);
            }
        };
        let canonical = match joined {
            Ok(value) => value,
            Err(_) => {
                self.telemetry.record_worker_crash();
                return Err(AgentdIntelligenceProductError::WorkerCrashed);
            }
        };
        let outcome = match canonical {
            Ok(value) => value,
            Err(error) => {
                self.record_canonical_error(&error);
                return Err(AgentdIntelligenceProductError::Canonical(error));
            }
        };
        if let Err(error) = validate_canonical_outcome_v1(&request_for_validation, &outcome) {
            self.record_canonical_error(&error);
            return Err(AgentdIntelligenceProductError::Canonical(error));
        }

        match outcome {
            CanonicalRunOutcomeV1::Ready(envelope) => {
                let mut oracle = FileBackedFreshnessOracleV1::new_observed(
                    self.authority_file.clone(),
                    self.authority_verifier.clone(),
                    Arc::clone(&self.telemetry),
                );
                if let Err(error) = validate_current_snapshot(&snapshot, &mut oracle) {
                    self.record_canonical_error(&error);
                    return Err(AgentdIntelligenceProductError::Canonical(error));
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
                self.telemetry.record_ready();
                Ok(AgentdIntelligenceProductOutcomeV1::Ready(
                    PreparedAgentdIntelligenceRunV1 {
                        envelope,
                        dispatch_proposal_digest,
                        snapshot,
                        candidate_ids,
                        run_snapshot,
                        context_attachment,
                    },
                ))
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

    /// Execute the canonical seven-owner composition and immediately admit the
    /// exact resulting envelope into the Agentd-owned run coordinator. This
    /// prevents product callers from treating a prepared envelope as a valid
    /// physical-turn binding before Agentd has frozen its run/context identity.
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
        );
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
        );
        validate_current_snapshot(&pending.snapshot, &mut oracle)
            .map_err(AgentdIntelligenceLedgerError::Currentness)?;
        journal
            .append_qualification(pending.expected_predecessor, pending.event)
            .map_err(AgentdIntelligenceLedgerError::Ledger)
    }
}
