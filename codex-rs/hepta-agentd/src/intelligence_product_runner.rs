//! Bounded execution of the existing canonical owner composition.

use super::*;

#[path = "intelligence_run_start.rs"]
mod run_start;

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
            coupled_field_owner: None,
            coupled_run_files: BTreeMap::new(),
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

    /// Attach the host's read-only parameter owner. A selected field update must
    /// match a currently materialized pin and its published ordinary decision.
    pub fn with_coupled_field_evidence_owner<S>(
        mut self,
        owner: AgentdCoupledFieldEvidenceOwnerV1<S>,
        run_files: Vec<std::sync::Arc<AgentdCoupledFieldRunFileV1>>,
    ) -> Result<Self, AgentdIntelligenceProductError>
    where
        S: codex_hepta_intelligence_eval::FinalHoldoutCasStoreV1 + Send + 'static,
    {
        if self.coupled_field_owner.is_some() {
            return Err(AgentdIntelligenceProductError::InvalidAuthorityVerifier);
        }
        if run_files.is_empty() {
            return Err(AgentdIntelligenceProductError::InvalidAuthorityVerifier);
        }
        for file in run_files {
            if self
                .coupled_run_files
                .insert(file.run_id.clone(), file)
                .is_some()
            {
                return Err(AgentdIntelligenceProductError::InvalidAuthorityVerifier);
            }
        }
        self.coupled_field_owner = Some(std::sync::Arc::new(owner));
        Ok(self)
    }

    /// The bounded worker cannot publish evidence. The daemon records the
    /// verified evaluation only after revalidating the original durable run.
    pub(crate) fn retain_coupled_field_evaluation(
        &self,
        original: &codex_hepta_learning_ledger::RunStartRecordV1,
        prepared: &PreparedAgentdIntelligenceRunV1,
    ) -> Result<(), AgentdIntelligenceEvaluationError> {
        if let Some(proof) = &prepared.coupled_field_readback {
            let file = self
                .coupled_run_files
                .get(&original.snapshot.run_id)
                .ok_or(AgentdIntelligenceEvaluationError::Binding)?;
            file.retain(original, proof)?;
        }
        Ok(())
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
    /// This standalone path uses the caller's frozen composition identity;
    /// durable Objective admission uses the record-bound preparation instead.
    pub async fn prepare_for_composition(
        &self,
        composition: &crate::RuntimeComposition,
        request: CanonicalIntelligenceRunRequestV1,
        inputs: AgentdIntelligenceOwnerInputsV1,
    ) -> Result<AgentdIntelligenceProductOutcomeV1, AgentdIntelligenceProductError> {
        self.prepare_with_run_identity(composition, None, request, inputs)
            .await
    }

    async fn prepare_with_run_identity(
        &self,
        composition: &crate::RuntimeComposition,
        original_record: Option<&codex_hepta_learning_ledger::RunStartRecordV1>,
        request: CanonicalIntelligenceRunRequestV1,
        mut inputs: AgentdIntelligenceOwnerInputsV1,
    ) -> Result<AgentdIntelligenceProductOutcomeV1, AgentdIntelligenceProductError> {
        let original_run = original_record
            .map(run_start::original_run_identity)
            .transpose()?;
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
        let started_ms = wall_clock_ms()?;
        let timeout_micros = match &original_run {
            Some(original) => run_start::remaining_preparation_budget(
                started_ms,
                original.deadline_ms,
                request.budget.total_micros,
            )?,
            None => request.budget.total_micros,
        };
        let timeout_ms = timeout_micros.saturating_add(999) / 1_000;
        let deadline_ms = started_ms
            .checked_add(timeout_ms.max(1))
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
                    .map_err(AgentdIntelligenceProductError::Canonical)?;
                Some(AgentdEvaluationSessionV1 {
                    run_id: request.run_id.clone(),
                    current_owner,
                    trust: std::sync::Arc::clone(trust),
                    signed,
                    original_record_digest: if candidate_ids
                        .iter()
                        .any(|id| id.as_str().starts_with("candidate:field:"))
                    {
                        original_record.map(codex_hepta_learning_ledger::RunStartRecordV1::durable_record_digest_v1).transpose()
                            .map_err(|_| AgentdIntelligenceProductError::Run(crate::AgentRunError::MixedSnapshot))?
                    } else {
                        None
                    },
                    coupled_field_owner: self.coupled_field_owner.clone(),
                })
            }
        };
        let mut worker = self.spawn_owner_work(move || {
            let mut ports = AgentdOwnerPortsV1::new(inputs, evaluation_session);
            let mut oracle = FileBackedFreshnessOracleV1::new(authority_file, authority_verifier);
            let outcome = prepare_intelligence_run(request, &mut ports, &mut oracle)?;
            Ok((outcome, ports.coupled_field_readback))
        })?;
        let (outcome, coupled_field_readback) =
            timeout(Duration::from_micros(timeout_micros), &mut worker)
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
                let mut body = b"hepta.agentd.intelligence-body.v1\0".to_vec();
                body.extend_from_slice(snapshot.digest().as_array());
                body.extend_from_slice(&snapshot.body_generation().get().to_be_bytes());
                let body_digest = Digest32::of_bytes(&body);
                let run_snapshot = original_run.unwrap_or_else(|| crate::AgentRunSnapshot {
                    run_id: envelope.run_id.to_string(),
                    request_digest: envelope.trace_digest.to_string(),
                    objective_digest: envelope.objective_digest.to_string(),
                    body_digest: body_digest.to_string(),
                    artifact_set_digest: snapshot.digest().to_string(),
                    authority_epoch: snapshot.authority_epoch(),
                    generation,
                    fence_digest,
                    deadline_ms,
                });
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
                        coupled_field_readback,
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
