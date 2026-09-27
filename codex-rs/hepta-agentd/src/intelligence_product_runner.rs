//! Bounded execution of the existing canonical owner composition.

use super::*;

struct ObservedOwnerWorkV1<T> {
    handle: tokio::task::JoinHandle<T>,
    completion: std::sync::Arc<std::sync::atomic::AtomicU8>,
    metrics: Option<std::sync::Arc<crate::AgentdIntelligenceRuntimeMetricsV1>>,
}

impl<T> ObservedOwnerWorkV1<T> {
    fn mark_timed_out(&self) {
        if self
            .completion
            .compare_exchange(
                0,
                1,
                std::sync::atomic::Ordering::AcqRel,
                std::sync::atomic::Ordering::Acquire,
            )
            .is_ok()
            && let Some(metrics) = self.metrics.as_ref()
        {
            metrics.record_cognition_timeout();
            metrics.record_late_worker_started();
        }
    }
}

struct ObservedOwnerPortsV1 {
    inner: AgentdOwnerPortsV1,
    metrics: Option<std::sync::Arc<crate::AgentdIntelligenceRuntimeMetricsV1>>,
}

impl ObservedOwnerPortsV1 {
    fn new(
        inner: AgentdOwnerPortsV1,
        metrics: Option<std::sync::Arc<crate::AgentdIntelligenceRuntimeMetricsV1>>,
    ) -> Self {
        Self { inner, metrics }
    }

    fn finish(
        &self,
        input: &CanonicalPortInputV1,
        started: Instant,
        result: Result<CanonicalPortReceiptV1, CanonicalPortFailureV1>,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        if let Some(metrics) = self.metrics.as_ref() {
            metrics.observe_stage(
                input.stage,
                started.elapsed(),
                result.as_ref().err().map(|failure| failure.class),
            );
        }
        result
    }
}

impl CanonicalOwnerPortsV1 for ObservedOwnerPortsV1 {
    fn validate_objective(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        let started = Instant::now();
        let result = self.inner.validate_objective(input);
        self.finish(input, started, result)
    }

    fn evaluate_utility(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        let started = Instant::now();
        let result = self.inner.evaluate_utility(input);
        self.finish(input, started, result)
    }

    fn collect_neural_signal(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        let started = Instant::now();
        let result = self.inner.collect_neural_signal(input);
        self.finish(input, started, result)
    }

    fn build_prompt_portfolio(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        let started = Instant::now();
        let result = self.inner.build_prompt_portfolio(input);
        self.finish(input, started, result)
    }

    fn decide_intuition(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        let started = Instant::now();
        let result = self.inner.decide_intuition(input);
        self.finish(input, started, result)
    }

    fn compile_context(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        let started = Instant::now();
        let result = self.inner.compile_context(input);
        self.finish(input, started, result)
    }

    fn evaluate_candidate(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        let started = Instant::now();
        let result = self.inner.evaluate_candidate(input);
        self.finish(input, started, result)
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
            worker_slots: std::sync::Arc::new(tokio::sync::Semaphore::new(
                MAX_CANONICAL_OWNER_WORKERS,
            )),
            authority_file,
            authority_verifier,
            evaluation_trust: None,
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
        self.evaluation_trust = Some(std::sync::Arc::new(trust));
        Ok(self)
    }

    #[must_use]
    pub const fn worker_capacity(&self) -> usize {
        MAX_CANONICAL_OWNER_WORKERS
    }

    #[must_use]
    pub fn worker_available(&self) -> usize {
        self.worker_slots.available_permits()
    }

    // The permit belongs to the worker, not the request future. Aborting a
    // running spawn_blocking task cannot stop its computation; releasing its
    // permit on request timeout would allow unbounded abandoned work.
    pub(super) fn spawn_owner_work<F, T>(
        &self,
        work: F,
    ) -> Result<tokio::task::JoinHandle<T>, AgentdIntelligenceProductError>
    where
        F: FnOnce() -> T + Send + 'static,
        T: Send + 'static,
    {
        let permit = std::sync::Arc::clone(&self.worker_slots)
            .try_acquire_owned()
            .map_err(|_| AgentdIntelligenceProductError::Busy)?;
        Ok(tokio::task::spawn_blocking(move || {
            let _permit = permit;
            work()
        }))
    }

    fn spawn_observed_owner_work<F, T>(
        &self,
        work: F,
        metrics: Option<std::sync::Arc<crate::AgentdIntelligenceRuntimeMetricsV1>>,
    ) -> Result<ObservedOwnerWorkV1<T>, AgentdIntelligenceProductError>
    where
        F: FnOnce() -> T + Send + 'static,
        T: Send + 'static,
    {
        let permit = match std::sync::Arc::clone(&self.worker_slots).try_acquire_owned() {
            Ok(permit) => permit,
            Err(_) => {
                if let Some(metrics) = metrics.as_ref() {
                    metrics.record_worker_busy();
                }
                return Err(AgentdIntelligenceProductError::Busy);
            }
        };
        let completion = std::sync::Arc::new(std::sync::atomic::AtomicU8::new(0));
        let worker_completion = std::sync::Arc::clone(&completion);
        let worker_metrics = metrics.clone();
        let handle = tokio::task::spawn_blocking(move || {
            let _permit = permit;
            let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(work));
            let previous = worker_completion.swap(2, std::sync::atomic::Ordering::AcqRel);
            if previous == 1
                && let Some(metrics) = worker_metrics.as_ref()
            {
                metrics.record_late_worker_completed();
            }
            match outcome {
                Ok(value) => value,
                Err(payload) => std::panic::resume_unwind(payload),
            }
        });
        Ok(ObservedOwnerWorkV1 {
            handle,
            completion,
            metrics,
        })
    }

    /// Compatibility preparation retained for focused source tests. Product
    /// daemon routing uses `prepare_bound_for_composition` and an exact durable
    /// RunStart binding.
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

    /// Compatibility composition without a durable RunStart identity. It is
    /// deliberately not used by the configured ObjectiveStart product route.
    pub async fn prepare_for_composition(
        &self,
        composition: &crate::RuntimeComposition,
        request: CanonicalIntelligenceRunRequestV1,
        inputs: AgentdIntelligenceOwnerInputsV1,
    ) -> Result<AgentdIntelligenceProductOutcomeV1, AgentdIntelligenceProductError> {
        self.prepare_inner(composition, request, inputs, None, None)
            .await
    }

    /// Product preparation inherited from one authenticated durable RunStart.
    pub async fn prepare_bound_for_composition(
        &self,
        composition: &crate::RuntimeComposition,
        request: CanonicalIntelligenceRunRequestV1,
        inputs: AgentdIntelligenceOwnerInputsV1,
        run_start: crate::AgentdRunStartBindingV1,
    ) -> Result<AgentdIntelligenceProductOutcomeV1, AgentdIntelligenceProductError> {
        let metrics = run_start.runtime_metrics();
        self.prepare_bound_for_composition_inner(
            composition,
            request,
            inputs,
            run_start,
            metrics,
        )
        .await
    }

    /// Product preparation with one explicit profile-owned metrics sink.
    pub async fn prepare_bound_for_composition_observed(
        &self,
        composition: &crate::RuntimeComposition,
        request: CanonicalIntelligenceRunRequestV1,
        inputs: AgentdIntelligenceOwnerInputsV1,
        run_start: crate::AgentdRunStartBindingV1,
        metrics: std::sync::Arc<crate::AgentdIntelligenceRuntimeMetricsV1>,
    ) -> Result<AgentdIntelligenceProductOutcomeV1, AgentdIntelligenceProductError> {
        self.prepare_bound_for_composition_inner(
            composition,
            request,
            inputs,
            run_start,
            Some(metrics),
        )
        .await
    }

    async fn prepare_bound_for_composition_inner(
        &self,
        composition: &crate::RuntimeComposition,
        request: CanonicalIntelligenceRunRequestV1,
        inputs: AgentdIntelligenceOwnerInputsV1,
        run_start: crate::AgentdRunStartBindingV1,
        metrics: Option<std::sync::Arc<crate::AgentdIntelligenceRuntimeMetricsV1>>,
    ) -> Result<AgentdIntelligenceProductOutcomeV1, AgentdIntelligenceProductError> {
        if request.run_id != *run_start.run_id()
            || request.snapshot.objective_digest() != run_start.objective_digest()
            || request.snapshot.authority_epoch() != run_start.authority_epoch()
            || request.snapshot.body_generation().get() != run_start.generation()
            || request.legal_candidates.state_digest != run_start.objective_digest()
        {
            return Err(AgentdIntelligenceProductError::Run(
                crate::AgentRunError::MixedSnapshot,
            ));
        }
        let expected_fence = composition
            .objective_fence_for(run_start.generation())
            .map_err(AgentdIntelligenceProductError::Run)?;
        if run_start.fence_digest().to_string() != expected_fence {
            return Err(AgentdIntelligenceProductError::Run(
                crate::AgentRunError::MixedSnapshot,
            ));
        }
        self.prepare_inner(composition, request, inputs, Some(run_start), metrics)
            .await
    }

    async fn prepare_inner(
        &self,
        composition: &crate::RuntimeComposition,
        request: CanonicalIntelligenceRunRequestV1,
        mut inputs: AgentdIntelligenceOwnerInputsV1,
        run_start: Option<crate::AgentdRunStartBindingV1>,
        metrics: Option<std::sync::Arc<crate::AgentdIntelligenceRuntimeMetricsV1>>,
    ) -> Result<AgentdIntelligenceProductOutcomeV1, AgentdIntelligenceProductError> {
        if let Some(metrics) = metrics.as_ref() {
            metrics.observe_authority_epoch(request.snapshot.authority_epoch());
        }
        let mut candidate_ids = request
            .legal_candidates
            .candidates
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect::<Vec<_>>();
        let mut intuition_ids = inputs
            .intuition_request
            .candidates
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect::<Vec<_>>();
        candidate_ids.sort();
        intuition_ids.sort();
        if candidate_ids != intuition_ids {
            if let Some(metrics) = metrics.as_ref() {
                metrics.record_candidate_set_rejection();
            }
            return Err(AgentdIntelligenceProductError::CandidateSetMismatch);
        }

        let snapshot = request.snapshot.clone();
        let requested_timeout_micros = request.budget.total_micros;
        let started_ms = wall_clock_ms()?;
        let timeout_micros = match run_start.as_ref() {
            Some(binding) => {
                let remaining_ms = binding
                    .deadline_ms()
                    .checked_sub(started_ms)
                    .ok_or(AgentdIntelligenceProductError::Run(
                        crate::AgentRunError::DeadlineElapsed,
                    ))?;
                if remaining_ms == 0 {
                    return Err(AgentdIntelligenceProductError::Run(
                        crate::AgentRunError::DeadlineElapsed,
                    ));
                }
                let remaining_micros = remaining_ms.saturating_mul(1_000);
                requested_timeout_micros.min(remaining_micros)
            }
            None => requested_timeout_micros,
        };
        if timeout_micros == 0 {
            if let Some(metrics) = metrics.as_ref() {
                metrics.record_cognition_timeout();
            }
            return Err(AgentdIntelligenceProductError::TimedOut);
        }
        let compatibility_deadline_ms = started_ms
            .checked_add(timeout_micros.saturating_add(999) / 1_000)
            .ok_or(AgentdIntelligenceProductError::Clock)?;
        let authority_file = self.authority_file.clone();
        let authority_verifier = self.authority_verifier.clone();
        let evaluation_session = match inputs.signed_evaluation.take() {
            None => None,
            Some(signed) => {
                let trust = self
                    .evaluation_trust
                    .as_ref()
                    .ok_or(AgentdIntelligenceProductError::InvalidAuthorityVerifier)?;
                let mut oracle = FileBackedFreshnessOracleV1::new(
                    authority_file.clone(),
                    authority_verifier.clone(),
                );
                let owner_id = StableId::new("learning.eval")
                    .map_err(|_| AgentdIntelligenceProductError::InvalidAuthorityVerifier)?;
                let current_owner = oracle
                    .current(&owner_id)
                    .map_err(|error| observed_canonical_error(metrics.as_ref(), error))?;
                Some(AgentdEvaluationSessionV1 {
                    run_id: request.run_id.clone(),
                    current_owner,
                    trust: std::sync::Arc::clone(trust),
                    signed,
                })
            }
        };
        let ports_metrics = metrics.clone();
        let mut worker = self.spawn_observed_owner_work(
            move || {
                let inner = AgentdOwnerPortsV1::new(inputs, evaluation_session);
                let mut ports = ObservedOwnerPortsV1::new(inner, ports_metrics);
                let mut oracle = FileBackedFreshnessOracleV1::new(authority_file, authority_verifier);
                prepare_intelligence_run(request, &mut ports, &mut oracle)
            },
            metrics.clone(),
        )?;
        let joined = match timeout(Duration::from_micros(timeout_micros), &mut worker.handle).await {
            Ok(joined) => joined,
            Err(_) => {
                // Dropping a spawn_blocking JoinHandle detaches the computation;
                // it does not terminate it. Keep the permit in the worker and
                // account for the late completion instead of admitting more
                // abandoned work.
                worker.mark_timed_out();
                return Err(AgentdIntelligenceProductError::TimedOut);
            }
        };
        let canonical = joined.map_err(|_| {
            if let Some(metrics) = metrics.as_ref() {
                metrics.record_worker_crash();
            }
            AgentdIntelligenceProductError::WorkerCrashed
        })?;
        let outcome = canonical.map_err(|error| observed_canonical_error(metrics.as_ref(), error))?;

        match outcome {
            CanonicalRunOutcomeV1::Ready(envelope) => {
                let mut oracle = FileBackedFreshnessOracleV1::new(
                    self.authority_file.clone(),
                    self.authority_verifier.clone(),
                );
                validate_current_snapshot(&snapshot, &mut oracle)
                    .map_err(|error| observed_canonical_error(metrics.as_ref(), error))?;
                let mut bytes = b"hepta.agentd.intelligence-dispatch-proposal.v2\0".to_vec();
                bytes.extend_from_slice(envelope.envelope_digest.as_array());
                bytes.extend_from_slice(snapshot.revocation_frontier_digest().as_array());
                if let Some(binding) = run_start.as_ref() {
                    bytes.extend_from_slice(binding.digest().as_array());
                }
                let dispatch_proposal_digest = Digest32::of_bytes(&bytes);

                let (
                    request_digest,
                    body_digest,
                    artifact_set_digest,
                    authority_epoch,
                    generation,
                    fence_digest,
                    deadline_ms,
                ) = match run_start.as_ref() {
                    Some(binding) => {
                        if wall_clock_ms()? >= binding.deadline_ms() {
                            return Err(AgentdIntelligenceProductError::Run(
                                crate::AgentRunError::DeadlineElapsed,
                            ));
                        }
                        (
                            binding.request_digest().to_string(),
                            binding.body_digest().to_string(),
                            binding.artifact_set_digest().to_string(),
                            binding.authority_epoch(),
                            binding.generation(),
                            binding.fence_digest().to_string(),
                            binding.deadline_ms(),
                        )
                    }
                    None => {
                        let generation = composition.agentd_generation;
                        let fence_digest = crate::agentd_objective_fence(
                            &composition.agent_id,
                            composition.supervisor_generation,
                            generation,
                        )
                        .map_err(AgentdIntelligenceProductError::Run)?;
                        let mut body = b"hepta.agentd.intelligence-body.v1\0".to_vec();
                        body.extend_from_slice(snapshot.digest().as_array());
                        body.extend_from_slice(&snapshot.body_generation().get().to_be_bytes());
                        (
                            envelope.trace_digest.to_string(),
                            Digest32::of_bytes(&body).to_string(),
                            snapshot.digest().to_string(),
                            snapshot.authority_epoch(),
                            generation,
                            fence_digest,
                            compatibility_deadline_ms,
                        )
                    }
                };
                let run_snapshot = crate::AgentRunSnapshot {
                    run_id: envelope.run_id.to_string(),
                    request_digest,
                    objective_digest: envelope.objective_digest.to_string(),
                    body_digest,
                    artifact_set_digest,
                    authority_epoch,
                    generation,
                    fence_digest,
                    deadline_ms,
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
                Ok(AgentdIntelligenceProductOutcomeV1::Abstained)
            }
            CanonicalRunOutcomeV1::SlowPath(_) => Ok(AgentdIntelligenceProductOutcomeV1::SlowPath),
        }
    }

    /// Compatibility helper retained for focused source tests. The daemon
    /// product route performs bound admission in `AgentdState`.
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
                    .start_run(
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

fn observed_canonical_error(
    metrics: Option<&std::sync::Arc<crate::AgentdIntelligenceRuntimeMetricsV1>>,
    error: CanonicalIntelligenceError,
) -> AgentdIntelligenceProductError {
    if let Some(metrics) = metrics {
        metrics.record_canonical_error(&error);
    }
    AgentdIntelligenceProductError::Canonical(error)
}
