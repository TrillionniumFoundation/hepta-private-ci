//! Final-use hardening for the authenticated product boundary.
//!
//! Static canonical payloads are retained at prepare time, but current validity
//! is never cached. Generator, evaluator and observer evidence is reverified
//! with the sole LedgerWriter's verifier and a fresh owner clock after the writer
//! mutex has been acquired. A known durable commit is still never rewritten as
//! an uncommitted failure.

use super::*;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::verify_signed_role_separation;
use codex_hepta_learning_ledger::verify_verified_role_separation;

const FINAL_USE_STAGE_METRIC: &str = "codex.hepta.intuition.policy.final_use_stage";

/// Wall-clock milliseconds at the owner final-use boundary.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct IntuitionWallClockMs(u64);

impl IntuitionWallClockMs {
    #[must_use]
    pub const fn new(value: u64) -> Self {
        Self(value)
    }

    #[must_use]
    pub const fn get(self) -> u64 {
        self.0
    }
}

/// Decision sequence in the policy domain; never a wall clock or generation.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct IntuitionDecisionSequence(u64);

impl IntuitionDecisionSequence {
    #[must_use]
    pub const fn new(value: u64) -> Self {
        Self(value)
    }

    #[must_use]
    pub const fn get(self) -> u64 {
        self.0
    }
}

/// Counter supplied by the separately owned assignment stream.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct IntuitionAssignmentCounter(u64);

impl IntuitionAssignmentCounter {
    #[must_use]
    pub const fn new(value: u64) -> Self {
        Self(value)
    }

    #[must_use]
    pub const fn get(self) -> u64 {
        self.0
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct FinalUseQualificationV1 {
    completeness_evidence: SignedLearningEvidenceV1,
    profile_qualification_evidence: SignedLearningEvidenceV1,
    runtime_evidence: SignedLearningEvidenceV1,
    completeness_payload: Vec<u8>,
    profile_qualification_payload: Vec<u8>,
    runtime_payload: Vec<u8>,
}

/// Non-dispatchable preparation carrying the exact immutable material needed
/// for a current-authority final-use check.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreparedAgentdIntuitionDecisionV4 {
    prepared: PreparedAgentdIntuitionDecisionV3,
    final_use: FinalUseQualificationV1,
}

impl PreparedAgentdIntuitionDecisionV4 {
    #[must_use]
    pub fn decision(&self) -> &AuthenticatedIntuitionDecisionV3 {
        self.prepared.decision()
    }

    #[must_use]
    pub fn host_binding_digest(&self) -> Digest32 {
        self.prepared.host_binding_digest()
    }

    #[must_use]
    pub fn production_decision(&self) -> Option<&ProductionDecisionV2> {
        self.prepared.production_decision()
    }

    #[must_use]
    pub fn prepared_digest(&self) -> Digest32 {
        self.prepared.prepared_digest()
    }

    pub fn decision_signing_payload(&self) -> Result<Option<Vec<u8>>, AgentdIntuitionPolicyError> {
        self.prepared.decision_signing_payload()
    }
}

impl AgentdIntuitionPolicyHostV1 {
    /// Prepare the current product value and retain immutable canonical payloads
    /// for the final-use check. Authorization conclusions are not retained.
    #[allow(clippy::too_many_arguments)]
    pub fn prepare_v4(
        &self,
        agent_id: &AgentId,
        spawn_generation: u64,
        request: CalibratedDecisionRequestV1,
        profile: CanonicalPolicyProfileV1,
        scoring: ScoringCommitmentV2,
        assignment: AssignmentCommitmentV2,
        qualification: IntuitionQualificationEvidenceV2<'_>,
        episode_id: StableId,
        run_snapshot_digest: Digest32,
        now: IntuitionWallClockMs,
    ) -> Result<PreparedAgentdIntuitionDecisionV4, AgentdIntuitionPolicyError> {
        validate_typed_assignment_boundary(&request, &assignment)?;
        let completeness_payload =
            codex_hepta_intuition::canonical_completeness_evidence_payload_v1(&request).map_err(
                |source| {
                    AgentdIntuitionPolicyError::QualificationV3(
                        IntuitionQualificationErrorV3::Policy(
                            codex_hepta_intuition::ProductionPolicyError::Qualified(source),
                        ),
                    )
                },
            )?;
        let profile_qualification_payload =
            codex_hepta_intuition::canonical_profile_qualification_payload_v1(&profile).map_err(
                |source| {
                    let policy = match source {
                        codex_hepta_intuition::RuntimeCommitmentError::Profile(inner) => {
                            codex_hepta_intuition::ProductionPolicyError::Qualified(inner)
                        }
                        _ => codex_hepta_intuition::ProductionPolicyError::ScoringIdentityMismatch(
                            "profile qualification",
                        ),
                    };
                    AgentdIntuitionPolicyError::QualificationV3(
                        IntuitionQualificationErrorV3::Policy(policy),
                    )
                },
            )?;
        let runtime_payload = codex_hepta_intuition::canonical_runtime_commitment_payload_v2(
            &request,
            &profile,
            &scoring,
            &assignment,
        )
        .map_err(|source| {
            AgentdIntuitionPolicyError::QualificationV3(IntuitionQualificationErrorV3::Policy(
                source,
            ))
        })?;
        let final_use = FinalUseQualificationV1 {
            completeness_evidence: qualification.completeness.clone(),
            profile_qualification_evidence: qualification.profile_qualification.clone(),
            runtime_evidence: qualification.runtime.clone(),
            completeness_payload,
            profile_qualification_payload,
            runtime_payload,
        };
        let prepared = self.prepare_v3(
            agent_id,
            spawn_generation,
            request,
            profile,
            scoring,
            assignment,
            qualification,
            episode_id,
            run_snapshot_digest,
            now.get(),
        )?;
        Ok(PreparedAgentdIntuitionDecisionV4 {
            prepared,
            final_use,
        })
    }

    /// Commit through the sole writer after reading a fresh clock under the
    /// writer mutex and re-verifying all three qualification roles with the
    /// writer's current trust snapshot.
    #[allow(clippy::too_many_arguments)]
    pub fn commit_v4_with_final_clock<F>(
        &self,
        agent_id: &AgentId,
        spawn_generation: u64,
        prepared: PreparedAgentdIntuitionDecisionV4,
        expected_ledger_head: Digest32,
        decision_evidence: Option<SignedLearningEvidenceV1>,
        final_clock: F,
    ) -> Result<AgentdIntuitionDecisionReceiptV2, AgentdIntuitionPolicyError>
    where
        F: FnOnce() -> Result<IntuitionWallClockMs, AgentdIntuitionPolicyError>,
    {
        self.require_identity(agent_id, spawn_generation)?;
        let product = self
            .product
            .as_ref()
            .ok_or(AgentdIntuitionPolicyError::ProductHostRequired)?;
        let PreparedAgentdIntuitionDecisionV4 {
            prepared: mut prepared,
            final_use,
        } = prepared;

        if prepared.owner_agent_id != self.agent_id
            || prepared.owner_spawn_generation != self.spawn_generation
            || prepared.owner_trust_digest != self.verifier.trust_digest()
        {
            return Err(AgentdIntuitionPolicyError::PreparedOwnerMismatch);
        }
        match (prepared.production.is_some(), decision_evidence.is_some()) {
            (true, false) => return Err(AgentdIntuitionPolicyError::MissingDecisionEvidence),
            (false, true) => return Err(AgentdIntuitionPolicyError::UnexpectedDecisionEvidence),
            _ => {}
        }

        let (production_record_id, learning) = with_final_use_lock(
            &product.learning.writer,
            final_clock,
            |writer, final_now| {
                let verification_started = std::time::Instant::now();
                let verification = (|| {
                    let writer_trust_digest = writer.verifier().trust_digest();
                    if writer_trust_digest != self.verifier.trust_digest()
                        || writer_trust_digest != prepared.owner_trust_digest
                    {
                        return Err(AgentdIntuitionPolicyError::PreparedOwnerMismatch);
                    }
                    validate_prepared_time(
                        prepared.prepared_at,
                        prepared.qualification_expires_at,
                        final_now.get(),
                    )?;
                    let current_binding = product_host_binding_digest(
                        &self.agent_id,
                        self.spawn_generation,
                        writer_trust_digest,
                        &product.pins,
                        prepared.decision.authentication_digest,
                    );
                    if current_binding != prepared.host_binding_digest {
                        return Err(AgentdIntuitionPolicyError::PreparedProfileMismatch);
                    }
                    reverify_final_use(
                        writer.verifier(),
                        &prepared.decision,
                        &final_use,
                        final_now.get(),
                    )
                })();
                record_final_use_stage(
                    "qualification_reverify",
                    if verification.is_ok() {
                        "completed"
                    } else {
                        "failed"
                    },
                    verification_started.elapsed(),
                );
                verification?;

                match (prepared.production.take(), decision_evidence) {
                    (Some(production), Some(evidence)) => {
                        let record_id = production.record_id.clone();
                        let retry_production = production.clone();
                        let retry_evidence = evidence.clone();
                        let append_started = std::time::Instant::now();
                        let result = match append_decision_locked(
                            writer,
                            expected_ledger_head,
                            production,
                            evidence,
                            final_now.get(),
                        ) {
                            Ok(receipt) => Ok(receipt),
                            Err(AgentdIntuitionPolicyError::IndeterminateAfterLedgerCommit {
                                receipt,
                            }) => preserve_known_commit(
                                receipt,
                                append_decision_locked(
                                    writer,
                                    expected_ledger_head,
                                    retry_production,
                                    retry_evidence,
                                    final_now.get(),
                                ),
                            )
                            .map_err(|receipt| {
                                AgentdIntuitionPolicyError::IndeterminateAfterLedgerCommit {
                                    receipt,
                                }
                            }),
                            Err(error) => Err(error),
                        };
                        record_final_use_stage(
                            "ledger_append_and_witness",
                            if result.is_ok() {
                                "completed"
                            } else {
                                "failed"
                            },
                            append_started.elapsed(),
                        );
                        result.map(|receipt| (Some(record_id), Some(receipt)))
                    }
                    (None, None) => {
                        record_final_use_stage(
                            "ledger_append_and_witness",
                            "not_applicable",
                            std::time::Duration::ZERO,
                        );
                        Ok((None, None))
                    }
                    (Some(_), None) => Err(AgentdIntuitionPolicyError::MissingDecisionEvidence),
                    (None, Some(_)) => Err(AgentdIntuitionPolicyError::UnexpectedDecisionEvidence),
                }
            },
        )?;

        let mut bytes = b"hepta.agentd.committed-intuition.v1\0".to_vec();
        bytes.extend_from_slice(prepared.prepared_digest.as_array());
        match &learning {
            Some(receipt) => {
                bytes.push(1);
                bytes.extend_from_slice(receipt.event_digest.as_array());
                bytes.extend_from_slice(receipt.chain_digest.as_array());
                bytes.extend_from_slice(&receipt.sequence.get().to_be_bytes());
            }
            None => bytes.push(0),
        }
        Ok(AgentdIntuitionDecisionReceiptV2 {
            decision: prepared.decision,
            host_binding_digest: prepared.host_binding_digest,
            production_record_id,
            learning,
            service_receipt_digest: Digest32::of_bytes(&bytes),
        })
    }
}

fn validate_typed_assignment_boundary(
    request: &CalibratedDecisionRequestV1,
    assignment: &AssignmentCommitmentV2,
) -> Result<(), AgentdIntuitionPolicyError> {
    let sequence = IntuitionDecisionSequence::new(request.sequence);
    if let AssignmentCommitmentV2::CounterBased { counter, .. } = assignment {
        let counter = IntuitionAssignmentCounter::new(*counter);
        if counter.get() != sequence.get() {
            return Err(AgentdIntuitionPolicyError::QualificationV3(
                IntuitionQualificationErrorV3::Policy(
                    codex_hepta_intuition::ProductionPolicyError::AssignmentCounterMismatch,
                ),
            ));
        }
    }
    Ok(())
}

fn with_final_use_lock<T, R, FClock, FWork>(
    lock: &Mutex<T>,
    final_clock: FClock,
    work: FWork,
) -> Result<R, AgentdIntuitionPolicyError>
where
    FClock: FnOnce() -> Result<IntuitionWallClockMs, AgentdIntuitionPolicyError>,
    FWork: FnOnce(&mut T, IntuitionWallClockMs) -> Result<R, AgentdIntuitionPolicyError>,
{
    let wait_started = std::time::Instant::now();
    let mut value = match lock.lock() {
        Ok(value) => {
            record_final_use_stage("writer_wait", "completed", wait_started.elapsed());
            value
        }
        Err(_) => {
            record_final_use_stage("writer_wait", "failed", wait_started.elapsed());
            return Err(AgentdIntuitionPolicyError::LearningLockPoisoned);
        }
    };
    let clock_started = std::time::Instant::now();
    let final_now = final_clock();
    record_final_use_stage(
        "final_clock_and_generation",
        if final_now.is_ok() {
            "completed"
        } else {
            "failed"
        },
        clock_started.elapsed(),
    );
    let final_now = final_now?;
    work(&mut value, final_now)
}

fn reverify_final_use(
    verifier: &LearningEvidenceVerifierV1,
    decision: &AuthenticatedIntuitionDecisionV3,
    final_use: &FinalUseQualificationV1,
    now: u64,
) -> Result<(), AgentdIntuitionPolicyError> {
    let generator = verifier
        .verify(
            LearningEvidenceRoleV1::Generator,
            &final_use.completeness_evidence,
            &final_use.completeness_payload,
            now,
        )
        .map_err(IntuitionQualificationErrorV3::from)?;
    let evaluator = verifier
        .verify(
            LearningEvidenceRoleV1::Evaluator,
            &final_use.profile_qualification_evidence,
            &final_use.profile_qualification_payload,
            now,
        )
        .map_err(IntuitionQualificationErrorV3::from)?;
    let observer = verifier
        .verify(
            LearningEvidenceRoleV1::Observer,
            &final_use.runtime_evidence,
            &final_use.runtime_payload,
            now,
        )
        .map_err(IntuitionQualificationErrorV3::from)?;
    verify_signed_role_separation(&generator, &evaluator, now)
        .map_err(IntuitionQualificationErrorV3::from)?;
    verify_signed_role_separation(&generator, &observer, now)
        .map_err(IntuitionQualificationErrorV3::from)?;
    verify_verified_role_separation(&evaluator, &observer, now)
        .map_err(IntuitionQualificationErrorV3::from)?;

    let completeness_payload_digest = Digest32::of_bytes(&final_use.completeness_payload);
    let profile_qualification_payload_digest =
        Digest32::of_bytes(&final_use.profile_qualification_payload);
    let runtime_payload_digest = Digest32::of_bytes(&final_use.runtime_payload);
    if decision.trust_digest != verifier.trust_digest()
        || decision.completeness_payload_digest != completeness_payload_digest
        || decision.profile_qualification_payload_digest != profile_qualification_payload_digest
        || decision.runtime_payload_digest != runtime_payload_digest
    {
        return Err(AgentdIntuitionPolicyError::PreparedProfileMismatch);
    }

    let mut bytes = b"hepta.intelligence.authenticated-intuition.v3\0".to_vec();
    for digest in [
        verifier.trust_digest(),
        decision.profile_digest,
        decision.scoring_commitment_digest,
        decision.assignment_commitment_digest,
        completeness_payload_digest,
        profile_qualification_payload_digest,
        runtime_payload_digest,
        Digest32::of_bytes(&final_use.completeness_evidence.signing_bytes()),
        Digest32::of_bytes(&final_use.profile_qualification_evidence.signing_bytes()),
        Digest32::of_bytes(&final_use.runtime_evidence.signing_bytes()),
        decision.decision.receipt_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&final_use.completeness_evidence.signature);
    bytes.extend_from_slice(&final_use.profile_qualification_evidence.signature);
    bytes.extend_from_slice(&final_use.runtime_evidence.signature);
    if Digest32::of_bytes(&bytes) != decision.authentication_digest {
        return Err(AgentdIntuitionPolicyError::PreparedProfileMismatch);
    }
    Ok(())
}

fn append_decision_locked(
    writer: &mut LedgerWriter,
    expected_predecessor: Digest32,
    request: ProductionDecisionV2,
    evidence: SignedLearningEvidenceV1,
    now: u64,
) -> Result<AppendReceipt, AgentdIntuitionPolicyError> {
    match writer.append_decision(expected_predecessor, request, &evidence, now) {
        Ok(receipt) => Ok(receipt),
        Err(ProductionLedgerError::IndeterminateAfterLedgerCommit {
            receipt,
            witness_error: _,
        }) => Err(AgentdIntuitionPolicyError::IndeterminateAfterLedgerCommit { receipt }),
        Err(error) => Err(AgentdIntuitionPolicyError::Learning(error)),
    }
}

fn record_final_use_stage(stage: &'static str, status: &'static str, elapsed: std::time::Duration) {
    let Some(metrics) = codex_otel::global() else {
        return;
    };
    if let Err(error) = metrics.record_duration(
        FINAL_USE_STAGE_METRIC,
        elapsed,
        &[("stage", stage), ("status", status)],
    ) {
        tracing::debug!(
            metric = FINAL_USE_STAGE_METRIC,
            stage,
            status,
            error = %error,
            "intuition final-use stage metric emission failed"
        );
    }
}

#[cfg(test)]
mod final_use_boundary_tests {
    use super::*;

    #[test]
    fn final_clock_is_read_only_after_the_owner_lock_is_held() {
        let lock = Mutex::new(());
        let observed = with_final_use_lock(
            &lock,
            || {
                assert!(lock.try_lock().is_err(), "clock ran before the owner lock");
                Ok(IntuitionWallClockMs::new(17))
            },
            |_, now| Ok(now.get()),
        )
        .expect("final-use helper");
        assert_eq!(observed, 17);
    }

    #[test]
    fn sequence_and_assignment_counter_are_distinct_domains() {
        assert_eq!(IntuitionDecisionSequence::new(11).get(), 11);
        assert_eq!(IntuitionAssignmentCounter::new(12).get(), 12);
        assert_ne!(
            IntuitionDecisionSequence::new(11).get(),
            IntuitionAssignmentCounter::new(12).get()
        );
    }
}
