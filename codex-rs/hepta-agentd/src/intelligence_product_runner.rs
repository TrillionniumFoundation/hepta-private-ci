//! Bounded execution of the existing canonical owner composition.

use super::*;

impl AgentdIntelligenceProductRunnerV1 {
    pub fn new(
        authority_file: PathBuf,
        authority_verifier: IntelligenceAuthorityVerifierV1,
    ) -> Result<Self, AgentdIntelligenceProductError> {
        let verifying_key = VerifyingKey::from_bytes(&authority_verifier.verifying_key)
            .map_err(|_| AgentdIntelligenceProductError::InvalidAuthorityVerifier)?;
        if !authority_file.is_absolute()
            || authority_verifier.signer_id.is_empty()
            || authority_verifier.signer_id.len() > 128
            || authority_verifier.signer_id.as_bytes().contains(&0)
            || verifying_key.is_weak()
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
        let candidate_ids = request
            .legal_candidates
            .candidates
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect::<Vec<_>>();
        let intuition_ids = inputs
            .intuition_request
            .candidates
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect::<Vec<_>>();
        if candidate_ids != intuition_ids {
            return Err(AgentdIntelligenceProductError::CandidateSetMismatch);
        }

        // Freeze the identity of the existing owner, never a new coordinator
        // or a caller-selected body/model generation. Agentd validates this
        // fence again at the actual admission and attachment boundary.
        let generation = composition.agentd_generation;
        let mut fence_bytes = b"hepta:agentd:objective-fence:v1\0".to_vec();
        fence_bytes.extend_from_slice(composition.agent_id.as_bytes());
        fence_bytes.extend_from_slice(&generation.to_be_bytes());
        fence_bytes.extend_from_slice(&generation.to_be_bytes());
        let fence_digest = Digest32::of_bytes(&fence_bytes).to_string();
        let snapshot = request.snapshot.clone();
        let timeout_micros = request.budget.total_micros;
        let started_ms = wall_clock_ms()?;
        let timeout_ms = timeout_micros.saturating_add(999) / 1_000;
        let deadline_ms = started_ms
            .checked_add(timeout_ms.max(1))
            .ok_or(AgentdIntelligenceProductError::Clock)?;
        let authority_file = self.authority_file.clone();
        let authority_verifier = self.authority_verifier.clone();
        let evaluation_session = match inputs.qualified_evaluation.take() {
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
                    .map_err(AgentdIntelligenceProductError::Canonical)?;
                Some(AgentdEvaluationSessionV1 {
                    run_id: request.run_id.clone(),
                    current_owner,
                    trust: std::sync::Arc::clone(trust),
                    signed,
                })
            }
        };
        let mut worker = self.spawn_owner_work(move || {
            let mut ports = AgentdOwnerPortsV1::new(inputs, evaluation_session);
            let mut oracle = FileBackedFreshnessOracleV1::new(authority_file, authority_verifier);
            prepare_intelligence_run(request, &mut ports, &mut oracle)
        })?;
        let outcome = timeout(Duration::from_micros(timeout_micros), &mut worker)
            .await
            .map_err(|_| {
                worker.abort();
                AgentdIntelligenceProductError::TimedOut
            })?
            .map_err(|_| AgentdIntelligenceProductError::WorkerCrashed)?
            .map_err(AgentdIntelligenceProductError::Canonical)?;

        match outcome {
            CanonicalRunOutcomeV1::Ready(envelope) => {
                let mut oracle = FileBackedFreshnessOracleV1::new(
                    self.authority_file.clone(),
                    self.authority_verifier.clone(),
                );
                validate_current_snapshot(&snapshot, &mut oracle)
                    .map_err(AgentdIntelligenceProductError::Canonical)?;
                let mut bytes = b"hepta.agentd.intelligence-dispatch-proposal.v1\0".to_vec();
                bytes.extend_from_slice(envelope.envelope_digest.as_array());
                bytes.extend_from_slice(snapshot.revocation_frontier_digest().as_array());
                let dispatch_proposal_digest = Digest32::of_bytes(&bytes);
                let body_digest =
                    crate::intelligence_ingress::canonical_runtime_body_digest(&snapshot);
                let run_snapshot = crate::AgentRunSnapshot {
                    run_id: envelope.run_id.to_string(),
                    request_digest: envelope.trace_digest.to_string(),
                    objective_digest: envelope.objective_digest.to_string(),
                    body_digest: body_digest.to_string(),
                    artifact_set_digest: snapshot.digest().to_string(),
                    authority_epoch: snapshot.authority_epoch(),
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

    /// Bind canonical owner evidence to an authenticated Objective publication.
    /// The caller revalidates live trust. Body keeps its process incarnation;
    /// physical admission uses the exact durable Running tuple and deadline.
    pub(crate) async fn prepare_for_run_start(
        &self,
        composition: &crate::RuntimeComposition,
        record: &codex_hepta_learning_ledger::RunStartRecordV1,
        request: CanonicalIntelligenceRunRequestV1,
        inputs: AgentdIntelligenceOwnerInputsV1,
    ) -> Result<AgentdIntelligenceProductOutcomeV1, AgentdIntelligenceProductError> {
        let running_generation = composition
            .agentd_generation
            .checked_add(1)
            .ok_or(AgentdIntelligenceProductError::Clock)?;
        let mut fence = b"hepta:agentd:objective-fence:v1\0".to_vec();
        fence.extend_from_slice(composition.agent_id.as_bytes());
        fence.extend_from_slice(&composition.agentd_generation.to_be_bytes());
        fence.extend_from_slice(&running_generation.to_be_bytes());
        if request.run_id != record.snapshot.run_id
            || request.snapshot.body_generation().get() != composition.agentd_generation
            || request.snapshot.objective_digest() != record.snapshot.objective_digest
            || request.snapshot.authority_epoch() != record.snapshot.authority_epoch
            || request.snapshot.digest() != record.snapshot.artifact_set_digest
            || crate::intelligence_ingress::canonical_runtime_body_digest(&request.snapshot)
                != record.runtime_body_digest
            || record.snapshot.generation != running_generation
            || record.snapshot.fence_digest != Digest32::of_bytes(&fence)
        {
            return Err(AgentdIntelligenceProductError::Run(
                crate::AgentRunError::MixedSnapshot,
            ));
        }
        let outcome = self
            .prepare_for_composition(composition, request, inputs)
            .await?;
        let AgentdIntelligenceProductOutcomeV1::Ready(mut prepared) = outcome else {
            return Ok(outcome);
        };
        // Reject incompatible body, artifacts or authority; never replace them
        // with caller values to disguise a different canonical owner result.
        if prepared.run_snapshot.body_digest != record.runtime_body_digest.to_string()
            || prepared.run_snapshot.artifact_set_digest
                != record.snapshot.artifact_set_digest.to_string()
            || prepared.run_snapshot.authority_epoch != record.snapshot.authority_epoch
            || prepared.run_snapshot.objective_digest
                != record.snapshot.objective_digest.to_string()
        {
            return Err(AgentdIntelligenceProductError::Run(
                crate::AgentRunError::MixedSnapshot,
            ));
        }
        let deadline_ms = record
            .admission
            .deadline_unix_micros
            .checked_add(999)
            .map(|value| value / 1_000)
            .ok_or(AgentdIntelligenceProductError::Clock)?;
        let physical = &mut prepared.run_snapshot;
        physical.request_digest = record.admission.admitted_source_digest.to_string();
        physical.generation = record.snapshot.generation;
        physical.fence_digest = record.snapshot.fence_digest.to_string();
        physical.deadline_ms = deadline_ms;
        let attachment = &mut prepared.context_attachment;
        attachment.request_digest = physical.request_digest.clone();
        attachment.generation = physical.generation;
        attachment.fence_digest = physical.fence_digest.clone();
        attachment.deadline_ms = physical.deadline_ms;
        Ok(AgentdIntelligenceProductOutcomeV1::Ready(prepared))
    }

    /// Execute the canonical seven-owner composition and immediately admit the
    /// exact resulting envelope into the Agentd-owned run coordinator. This
    /// prevents product callers from treating a prepared envelope as a valid
    /// physical-turn binding before Agentd has frozen its run/context identity.
    /// This standalone path has no daemon Fleet lifecycle admission; ordinary
    /// ObjectiveStart uses the authenticated durable binding instead.
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
