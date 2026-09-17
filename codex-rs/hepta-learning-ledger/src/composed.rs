//! Strict authenticated composition over the witnessed durable learning journal.
//!
//! This module removes the source-level gap between cryptographic evidence,
//! causal V2 validators and the V1-compatible durable ledger. It does not name a
//! live production process or grant production/effect authority; deployment must
//! still prove which caller owns this service and the physical capabilities it
//! receives.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AcknowledgedLearningJournal;
use crate::AppendReceipt;
use crate::AuthenticatedOutcomeV1;
use crate::CandidateSetCompletenessReceiptV1;
use crate::CausalV2Error;
use crate::CreditAllocationBatchV1;
use crate::DatasetSnapshotReceiptV3;
use crate::DurableCreditBatchError;
use crate::DurableCreditBatchReceiptV1;
use crate::DurableLedgerError;
use crate::LedgerDerivedDatasetError;
use crate::LedgerDerivedDatasetPlanV1;
use crate::LedgerEvent;
use crate::LearningEvidenceRoleV1;
use crate::LearningEvidenceVerifierV1;
use crate::LearningLedger;
use crate::OutcomeFinality;
use crate::OutcomeObservation;
use crate::OutcomeTerminalityV1;
use crate::Revocation;
use crate::ShadowDecisionArtifact;
use crate::ShadowDecisionError;
use crate::ShadowDecisionRequest;
use crate::SignedEvidenceError;
use crate::SignedLearningEvidenceV1;
use crate::append_conserved_credit_batch_v1;
use crate::canonical_candidate_set_digest;
use crate::finalize_credit_batch;
use crate::freeze_dataset_from_ledger_v3;
use crate::prepare_shadow_decision;
use crate::validate_authenticated_outcome;
use crate::validate_candidate_set_completeness;
use crate::verify_signed_role_separation;

const DECISION_EVIDENCE_DOMAIN: &[u8] = b"hepta.learning-ledger.composed-decision.v1";
const EPISODE_ROLE_DOMAIN: &[u8] = b"hepta.learning-ledger.composed-episode-role.v1";
const OUTCOME_EVIDENCE_DOMAIN: &[u8] = b"hepta.learning-ledger.composed-outcome.v1";
const CREDIT_EVIDENCE_DOMAIN: &[u8] = b"hepta.learning-ledger.composed-credit.v1";
const DATASET_EVIDENCE_DOMAIN: &[u8] = b"hepta.learning-ledger.composed-dataset.v1";
const CORRECTION_REVOKE_DOMAIN: &[u8] = b"hepta.learning-ledger.correction-revoke.v1";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedDecisionCommitV1 {
    pub artifact: ShadowDecisionArtifact,
    pub completeness_digest: Digest32,
    pub evidence_payload_digest: Digest32,
    pub ledger_receipt: AppendReceipt,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedOutcomeCommitV1 {
    pub outcome_digest: Digest32,
    pub evidence_payload_digest: Digest32,
    pub ledger_receipts: Vec<AppendReceipt>,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ComposedLearningError {
    Signed(SignedEvidenceError),
    Causal(CausalV2Error),
    Durable(DurableLedgerError),
    Shadow(ShadowDecisionError),
    Credit(DurableCreditBatchError),
    Dataset(LedgerDerivedDatasetError),
    PrincipalBinding(&'static str),
    CandidateBinding,
    ObjectiveBinding,
    EpisodeMissing,
    CorrectionPredecessorMissing,
    CorrectionIdentityReuse,
    NonTerminalOutcome,
    Arithmetic,
    DerivedIdentity,
}

impl fmt::Display for ComposedLearningError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ComposedLearningError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Signed(error) => Some(error),
            Self::Causal(error) => Some(error),
            Self::Durable(error) => Some(error),
            Self::Shadow(error) => Some(error),
            Self::Credit(error) => Some(error),
            Self::Dataset(error) => Some(error),
            Self::PrincipalBinding(_)
            | Self::CandidateBinding
            | Self::ObjectiveBinding
            | Self::EpisodeMissing
            | Self::CorrectionPredecessorMissing
            | Self::CorrectionIdentityReuse
            | Self::NonTerminalOutcome
            | Self::Arithmetic
            | Self::DerivedIdentity => None,
        }
    }
}

impl From<SignedEvidenceError> for ComposedLearningError {
    fn from(value: SignedEvidenceError) -> Self {
        Self::Signed(value)
    }
}
impl From<CausalV2Error> for ComposedLearningError {
    fn from(value: CausalV2Error) -> Self {
        Self::Causal(value)
    }
}
impl From<DurableLedgerError> for ComposedLearningError {
    fn from(value: DurableLedgerError) -> Self {
        Self::Durable(value)
    }
}
impl From<ShadowDecisionError> for ComposedLearningError {
    fn from(value: ShadowDecisionError) -> Self {
        Self::Shadow(value)
    }
}
impl From<DurableCreditBatchError> for ComposedLearningError {
    fn from(value: DurableCreditBatchError) -> Self {
        Self::Credit(value)
    }
}
impl From<LedgerDerivedDatasetError> for ComposedLearningError {
    fn from(value: LedgerDerivedDatasetError) -> Self {
        Self::Dataset(value)
    }
}

/// Immutable trust generation plus the only acknowledged journal exposed to the
/// strict source-composition API. Rotate trust by constructing a new service
/// with a newly admitted `LearningEvidenceVerifierV1`; evidence from another
/// trust digest/authority epoch then fails closed.
pub struct CausalLearningWriterV1<J: AcknowledgedLearningJournal> {
    journal: J,
    verifier: LearningEvidenceVerifierV1,
}

impl<J: AcknowledgedLearningJournal> CausalLearningWriterV1<J> {
    #[must_use]
    pub fn new(journal: J, verifier: LearningEvidenceVerifierV1) -> Self {
        Self { journal, verifier }
    }

    #[must_use]
    pub fn trust_digest(&self) -> Digest32 {
        self.verifier.trust_digest()
    }

    pub fn append_decision(
        &mut self,
        expected_predecessor: Digest32,
        request: ShadowDecisionRequest,
        completeness: &CandidateSetCompletenessReceiptV1,
        generator_evidence: &SignedLearningEvidenceV1,
        now: u64,
    ) -> Result<AuthenticatedDecisionCommitV1, ComposedLearningError> {
        let completeness_digest = validate_candidate_set_completeness(completeness)?;
        let count = u32::try_from(request.decision.candidates.len())
            .map_err(|_| ComposedLearningError::Arithmetic)?;
        let actual_candidates_digest = canonical_candidate_set_digest(&request.decision);
        if completeness.candidate_count != count
            || completeness.candidates_digest != actual_candidates_digest
            || request.decision.candidate_set_digest != actual_candidates_digest
        {
            return Err(ComposedLearningError::CandidateBinding);
        }
        if request.decision.objective_digest != generator_evidence.objective_digest {
            return Err(ComposedLearningError::ObjectiveBinding);
        }

        let payload = decision_evidence_payload_v1(&request, completeness_digest)?;
        let generator = self.verifier.verify(
            LearningEvidenceRoleV1::Generator,
            generator_evidence,
            &payload,
            now,
        )?;
        if completeness.generator_id != generator.principal().principal_id
            || request.policy_id != generator.principal().principal_id
        {
            return Err(ComposedLearningError::PrincipalBinding("generator"));
        }

        let artifact = prepare_shadow_decision(request)?;
        let ledger_receipt = self.journal.append(
            expected_predecessor,
            LedgerEvent::Decision(artifact.ledger_decision.clone()),
        )?;
        Ok(AuthenticatedDecisionCommitV1 {
            artifact,
            completeness_digest,
            evidence_payload_digest: Digest32::of_bytes(&payload),
            ledger_receipt,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    /// Admit and persist one independently signed terminal outcome. If the V2
    /// outcome identifies a correction predecessor, the predecessor V1 outcome
    /// is logically revoked and the corrected terminal outcome is appended in
    /// one witnessed atomic batch.
    pub fn append_terminal_outcome(
        &mut self,
        expected_predecessor: Digest32,
        outcome: AuthenticatedOutcomeV1,
        generator_evidence: &SignedLearningEvidenceV1,
        observer_evidence: &SignedLearningEvidenceV1,
        now: u64,
    ) -> Result<AuthenticatedOutcomeCommitV1, ComposedLearningError> {
        let snapshot = self.journal.snapshot()?;
        let replayed = LearningLedger::from_snapshot(snapshot)
            .map_err(|error| DurableLedgerError::Semantic(error))?;
        let decision_record = replayed
            .active_records()
            .into_iter()
            .find(|record| {
                matches!(
                    &record.event,
                    LedgerEvent::Decision(decision) if decision.episode_id == outcome.episode_id
                )
            })
            .ok_or(ComposedLearningError::EpisodeMissing)?;
        let LedgerEvent::Decision(decision) = &decision_record.event else {
            return Err(ComposedLearningError::EpisodeMissing);
        };

        let generator_payload = episode_role_payload_v1(
            &decision.episode_id,
            decision_record.event_digest,
            decision.objective_digest,
        );
        let generator = self.verifier.verify(
            LearningEvidenceRoleV1::Generator,
            generator_evidence,
            &generator_payload,
            now,
        )?;
        if generator.principal().principal_id != decision.policy_id {
            return Err(ComposedLearningError::PrincipalBinding("generator"));
        }
        if generator_evidence.objective_digest != decision.objective_digest
            || observer_evidence.objective_digest != decision.objective_digest
        {
            return Err(ComposedLearningError::ObjectiveBinding);
        }

        let outcome_digest = validate_authenticated_outcome(generator.principal(), &outcome, now)?;
        let observer_payload = outcome_evidence_payload_v1(outcome_digest);
        let observer = self.verifier.verify(
            LearningEvidenceRoleV1::Observer,
            observer_evidence,
            &observer_payload,
            now,
        )?;
        if observer.principal() != &outcome.observer {
            return Err(ComposedLearningError::PrincipalBinding("observer"));
        }
        verify_signed_role_separation(&generator, &observer, now)?;

        if outcome.watermark.terminality != OutcomeTerminalityV1::Terminal {
            return Err(ComposedLearningError::NonTerminalOutcome);
        }
        let value = outcome.value.ok_or(ComposedLearningError::NonTerminalOutcome)?;
        let terminal = LedgerEvent::Outcome(OutcomeObservation {
            record_id: outcome.record_id.clone(),
            outcome_id: outcome.outcome_id.clone(),
            episode_id: outcome.episode_id.clone(),
            observer_id: observer.principal().principal_id.clone(),
            value,
            finality: OutcomeFinality::Terminal,
            support_digest: outcome_digest,
        });

        let ledger_receipts = if let Some(predecessor_outcome_id) =
            outcome.watermark.correction_predecessor.as_ref()
        {
            if predecessor_outcome_id == &outcome.outcome_id {
                return Err(ComposedLearningError::CorrectionIdentityReuse);
            }
            let predecessor = replayed
                .active_records()
                .into_iter()
                .find_map(|record| {
                    let LedgerEvent::Outcome(previous) = &record.event else {
                        return None;
                    };
                    (previous.outcome_id == *predecessor_outcome_id
                        && previous.episode_id == outcome.episode_id)
                        .then_some(record)
                })
                .ok_or(ComposedLearningError::CorrectionPredecessorMissing)?;
            let revoke_record_id = derived_correction_revoke_id(
                outcome_digest,
                predecessor.event.record_id(),
            )?;
            self.journal.append_batch(
                expected_predecessor,
                vec![
                    LedgerEvent::Revocation(Revocation {
                        record_id: revoke_record_id,
                        target_record_id: predecessor.event.record_id().clone(),
                        authority_id: observer.principal().principal_id.clone(),
                        reason_digest: outcome_digest,
                    }),
                    terminal,
                ],
            )?
        } else {
            vec![self.journal.append(expected_predecessor, terminal)?]
        };

        Ok(AuthenticatedOutcomeCommitV1 {
            outcome_digest,
            evidence_payload_digest: Digest32::of_bytes(&observer_payload),
            ledger_receipts,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    pub fn append_credit_batch(
        &mut self,
        expected_predecessor: Digest32,
        batch: CreditAllocationBatchV1,
        generator_evidence: &SignedLearningEvidenceV1,
        allocator_evidence: &SignedLearningEvidenceV1,
        now: u64,
    ) -> Result<DurableCreditBatchReceiptV1, ComposedLearningError> {
        let snapshot = self.journal.snapshot()?;
        let replayed = LearningLedger::from_snapshot(snapshot)
            .map_err(|error| DurableLedgerError::Semantic(error))?;
        let decision_record = replayed
            .active_records()
            .into_iter()
            .find(|record| {
                matches!(
                    &record.event,
                    LedgerEvent::Decision(decision) if decision.episode_id == batch.episode_id
                )
            })
            .ok_or(ComposedLearningError::EpisodeMissing)?;
        let LedgerEvent::Decision(decision) = &decision_record.event else {
            return Err(ComposedLearningError::EpisodeMissing);
        };
        if generator_evidence.objective_digest != decision.objective_digest
            || allocator_evidence.objective_digest != decision.objective_digest
        {
            return Err(ComposedLearningError::ObjectiveBinding);
        }

        let generator_payload = episode_role_payload_v1(
            &decision.episode_id,
            decision_record.event_digest,
            decision.objective_digest,
        );
        let generator = self.verifier.verify(
            LearningEvidenceRoleV1::Generator,
            generator_evidence,
            &generator_payload,
            now,
        )?;
        if generator.principal().principal_id != decision.policy_id {
            return Err(ComposedLearningError::PrincipalBinding("generator"));
        }

        let conservation = finalize_credit_batch(batch.clone(), now)?;
        let allocator_payload = credit_evidence_payload_v1(
            conservation.batch_digest,
            decision_record.event_digest,
            &batch.episode_id,
        );
        let allocator = self.verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            allocator_evidence,
            &allocator_payload,
            now,
        )?;
        if allocator.principal() != &batch.allocator {
            return Err(ComposedLearningError::PrincipalBinding("allocator"));
        }
        verify_signed_role_separation(&generator, &allocator, now)?;

        append_conserved_credit_batch_v1(
            &mut self.journal,
            expected_predecessor,
            batch,
            now,
        )
        .map_err(Into::into)
    }

    pub fn freeze_dataset(
        &mut self,
        plan: LedgerDerivedDatasetPlanV1,
        evaluator_evidence: &SignedLearningEvidenceV1,
        now: u64,
    ) -> Result<DatasetSnapshotReceiptV3, ComposedLearningError> {
        let snapshot = self.journal.snapshot()?;
        if evaluator_evidence.objective_digest != plan.objective_digest {
            return Err(ComposedLearningError::ObjectiveBinding);
        }
        let payload = dataset_evidence_payload_v1(snapshot.head_digest, &plan)?;
        let evaluator = self.verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            evaluator_evidence,
            &payload,
            now,
        )?;
        if evaluator.principal() != &plan.producer {
            return Err(ComposedLearningError::PrincipalBinding("dataset producer"));
        }
        freeze_dataset_from_ledger_v3(&snapshot, plan, now).map_err(Into::into)
    }

    pub fn snapshot(&self) -> Result<crate::LedgerSnapshot, DurableLedgerError> {
        self.journal.snapshot()
    }
}

pub fn decision_evidence_payload_v1(
    request: &ShadowDecisionRequest,
    completeness_digest: Digest32,
) -> Result<Vec<u8>, ComposedLearningError> {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(DECISION_EVIDENCE_DOMAIN);
    push_id(&mut bytes, &request.record_id)?;
    push_id(&mut bytes, &request.episode_id)?;
    push_id(&mut bytes, &request.policy_id)?;
    push_id(&mut bytes, &request.decision.decision_id)?;
    bytes.extend_from_slice(request.decision.objective_digest.as_array());
    bytes.extend_from_slice(request.decision.candidate_set_digest.as_array());
    bytes.extend_from_slice(completeness_digest.as_array());
    Ok(bytes)
}

pub fn episode_role_payload_v1(
    episode_id: &StableId,
    decision_event_digest: Digest32,
    objective_digest: Digest32,
) -> Vec<u8> {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(EPISODE_ROLE_DOMAIN);
    push_id_unchecked(&mut bytes, episode_id);
    bytes.extend_from_slice(decision_event_digest.as_array());
    bytes.extend_from_slice(objective_digest.as_array());
    bytes
}

pub fn outcome_evidence_payload_v1(outcome_digest: Digest32) -> Vec<u8> {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(OUTCOME_EVIDENCE_DOMAIN);
    bytes.extend_from_slice(outcome_digest.as_array());
    bytes
}

pub fn credit_evidence_payload_v1(
    batch_digest: Digest32,
    decision_event_digest: Digest32,
    episode_id: &StableId,
) -> Vec<u8> {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(CREDIT_EVIDENCE_DOMAIN);
    bytes.extend_from_slice(batch_digest.as_array());
    bytes.extend_from_slice(decision_event_digest.as_array());
    push_id_unchecked(&mut bytes, episode_id);
    bytes
}

pub fn dataset_evidence_payload_v1(
    ledger_head_digest: Digest32,
    plan: &LedgerDerivedDatasetPlanV1,
) -> Result<Vec<u8>, ComposedLearningError> {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(DATASET_EVIDENCE_DOMAIN);
    push_id(&mut bytes, &plan.snapshot_id)?;
    bytes.extend_from_slice(plan.objective_digest.as_array());
    bytes.extend_from_slice(ledger_head_digest.as_array());
    bytes.extend_from_slice(&plan.outcome_watermark.to_be_bytes());
    bytes.extend_from_slice(plan.inclusion_policy_digest.as_array());
    Ok(bytes)
}

fn derived_correction_revoke_id(
    outcome_digest: Digest32,
    target_record_id: &StableId,
) -> Result<StableId, ComposedLearningError> {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(CORRECTION_REVOKE_DOMAIN);
    bytes.extend_from_slice(outcome_digest.as_array());
    push_id(&mut bytes, target_record_id)?;
    StableId::new(format!("correction-revoke:{}", Digest32::of_bytes(&bytes)))
        .map_err(|_| ComposedLearningError::DerivedIdentity)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), ComposedLearningError> {
    let raw = value.as_str().as_bytes();
    let len = u32::try_from(raw.len()).map_err(|_| ComposedLearningError::Arithmetic)?;
    bytes.extend_from_slice(&len.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

fn push_id_unchecked(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u32).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
mod tests {
    use std::fs::File;
    use std::fs::OpenOptions;
    use std::path::Path;
    use std::path::PathBuf;
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    use codex_hepta_intuition::ActionCandidate;
    use codex_hepta_intuition::DecisionRequest;
    use codex_hepta_types::FixedQ32;
    use codex_hepta_types::ProbabilityQ32;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

    use super::*;
    use crate::AuthenticatedPrincipalV1;
    use crate::LearningEvidenceTrustV1;
    use crate::LedgerWitnessStore;
    use crate::TrustedLearningSignerV1;
    use crate::WitnessedLearningLedger;
    use crate::DurableLedger;

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("valid test id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn signer(
        name: &str,
        controller: &str,
        seed: u8,
        role: LearningEvidenceRoleV1,
    ) -> TrustedLearningSignerV1 {
        let key = SigningKey::from_bytes(&[seed; 32]).verifying_key().to_bytes();
        TrustedLearningSignerV1 {
            principal: AuthenticatedPrincipalV1 {
                principal_id: id(name),
                credential_chain_digest: digest(&format!("{name}-credential")),
                signing_key_digest: Digest32::of_bytes(&key),
                scope_digest: digest("scope"),
                authority_epoch: 7,
                authenticated_at: 10,
                expires_at: 100,
            },
            controller_id: id(controller),
            verifying_key: key,
            roles: vec![role],
            revoked_at: None,
        }
    }

    fn trust() -> LearningEvidenceTrustV1 {
        LearningEvidenceTrustV1 {
            scope_digest: digest("scope"),
            objective_digest: digest("objective"),
            authority_epoch: 7,
            signers: vec![
                signer("generator", "controller-generator", 1, LearningEvidenceRoleV1::Generator),
                signer("observer", "controller-observer", 2, LearningEvidenceRoleV1::Observer),
                signer("evaluator", "controller-evaluator", 3, LearningEvidenceRoleV1::Evaluator),
            ],
        }
    }

    fn sign(
        verifier: &LearningEvidenceVerifierV1,
        principal: &str,
        role: LearningEvidenceRoleV1,
        seed: u8,
        payload: &[u8],
        evidence_id: &str,
    ) -> SignedLearningEvidenceV1 {
        let mut evidence = SignedLearningEvidenceV1 {
            evidence_id: id(evidence_id),
            principal_id: id(principal),
            role,
            trust_digest: verifier.trust_digest(),
            scope_digest: digest("scope"),
            objective_digest: digest("objective"),
            authority_epoch: 7,
            issued_at: 20,
            expires_at: 90,
            payload_digest: Digest32::of_bytes(payload),
            signature: [0; 64],
        };
        evidence.signature = SigningKey::from_bytes(&[seed; 32])
            .sign(&evidence.signing_bytes())
            .to_bytes();
        evidence
    }

    fn file(root: &Path, name: &str, create_new: bool) -> File {
        let mut options = OpenOptions::new();
        options.read(true).write(true);
        if create_new {
            options.create_new(true);
        }
        options.open(root.join(name)).expect("open test file")
    }

    fn temp_root(label: &str) -> PathBuf {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock after epoch")
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "hepta-composed-writer-{label}-{}-{nanos}",
            std::process::id()
        ));
        std::fs::create_dir(&root).expect("create test root");
        root
    }

    fn verifier() -> LearningEvidenceVerifierV1 {
        LearningEvidenceVerifierV1::new(trust()).expect("valid trust")
    }

    fn writer(root: &Path) -> CausalLearningWriterV1<WitnessedLearningLedger<DurableLedger>> {
        let ledger = DurableLedger::create(file(root, "ledger", true), digest("ledger-binding"), 32)
            .expect("create ledger");
        let witness = LedgerWitnessStore::create(file(root, "witness", true), digest("witness-binding"))
            .expect("create witness");
        let acknowledged = WitnessedLearningLedger::attach(ledger, witness).expect("attach witness");
        CausalLearningWriterV1::new(acknowledged, verifier())
    }

    fn decision_request() -> ShadowDecisionRequest {
        let candidate = ActionCandidate {
            candidate_id: id("action"),
            legal: true,
            hard_veto: false,
            utility: FixedQ32::ONE,
            confidence: ProbabilityQ32::ONE,
            support_digest: digest("candidate-support"),
        };
        let mut decision = DecisionRequest {
            decision_id: id("decision"),
            objective_digest: digest("objective"),
            candidate_set_digest: Digest32::ZERO,
            minimum_confidence: ProbabilityQ32::ZERO,
            candidates: vec![candidate],
        };
        decision.candidate_set_digest = canonical_candidate_set_digest(&decision);
        ShadowDecisionRequest {
            record_id: id("decision-record"),
            episode_id: id("episode"),
            policy_id: id("generator"),
            decision,
        }
    }

    fn completeness(request: &ShadowDecisionRequest) -> CandidateSetCompletenessReceiptV1 {
        CandidateSetCompletenessReceiptV1 {
            set_id: id("candidate-set"),
            state_digest: digest("state"),
            generator_id: id("generator"),
            generator_code_digest: digest("generator-code"),
            grammar_digest: digest("grammar"),
            hard_filter_digest: digest("filter"),
            truncation_digest: digest("truncation"),
            candidates_digest: canonical_candidate_set_digest(&request.decision),
            candidate_count: request.decision.candidates.len() as u32,
            omitted_count_bound: 0,
            canonical_order_digest: digest("candidate-order"),
            complete_for_generator: true,
        }
    }

    fn principal(name: &str) -> AuthenticatedPrincipalV1 {
        trust()
            .signers
            .into_iter()
            .find(|signer| signer.principal.principal_id == id(name))
            .expect("principal")
            .principal
    }

    #[test]
    fn composed_writer_binds_signed_decision_and_terminal_outcome_to_witnessed_history() {
        let root = temp_root("decision-outcome");
        let mut writer = writer(&root);
        let request = decision_request();
        let completeness = completeness(&request);
        let completeness_digest = validate_candidate_set_completeness(&completeness)
            .expect("valid completeness");
        let decision_payload = decision_evidence_payload_v1(&request, completeness_digest)
            .expect("decision payload");
        let generator_decision = sign(
            &writer.verifier,
            "generator",
            LearningEvidenceRoleV1::Generator,
            1,
            &decision_payload,
            "generator-decision-evidence",
        );
        let committed = writer
            .append_decision(
                Digest32::ZERO,
                request,
                &completeness,
                &generator_decision,
                50,
            )
            .expect("append decision");

        let role_payload = episode_role_payload_v1(
            &committed.artifact.ledger_decision.episode_id,
            committed.ledger_receipt.event_digest,
            committed.artifact.ledger_decision.objective_digest,
        );
        let generator_role = sign(
            &writer.verifier,
            "generator",
            LearningEvidenceRoleV1::Generator,
            1,
            &role_payload,
            "generator-role-evidence",
        );
        let outcome = AuthenticatedOutcomeV1 {
            record_id: id("outcome-record"),
            outcome_id: id("outcome"),
            episode_id: id("episode"),
            observer: principal("observer"),
            observed_at: Some(40),
            value: Some(FixedQ32::ONE),
            unit_profile_digest: digest("unit"),
            support_digest: digest("outcome-support"),
            watermark: crate::OutcomeWatermarkV1 {
                latest_observable_at: 45,
                expected_delay_profile_digest: digest("delay"),
                terminality: OutcomeTerminalityV1::Terminal,
                censoring_reason: None,
                correction_predecessor: None,
                finalized_at: Some(46),
            },
        };
        let outcome_digest = validate_authenticated_outcome(&principal("generator"), &outcome, 50)
            .expect("valid outcome");
        let outcome_payload = outcome_evidence_payload_v1(outcome_digest);
        let observer = sign(
            &writer.verifier,
            "observer",
            LearningEvidenceRoleV1::Observer,
            2,
            &outcome_payload,
            "observer-outcome-evidence",
        );
        let outcome_commit = writer
            .append_terminal_outcome(
                committed.ledger_receipt.chain_digest,
                outcome,
                &generator_role,
                &observer,
                50,
            )
            .expect("append outcome");
        assert_eq!(outcome_commit.ledger_receipts.len(), 1);
        assert_eq!(writer.snapshot().expect("snapshot").records().len(), 2);
        drop(writer);
        std::fs::remove_dir_all(root).expect("remove test root");
    }

    #[test]
    fn composed_writer_rejects_unsigned_candidate_binding_drift() {
        let root = temp_root("candidate-drift");
        let mut writer = writer(&root);
        let request = decision_request();
        let mut completeness = completeness(&request);
        let original_digest = validate_candidate_set_completeness(&completeness)
            .expect("valid completeness");
        let payload = decision_evidence_payload_v1(&request, original_digest)
            .expect("decision payload");
        let generator = sign(
            &writer.verifier,
            "generator",
            LearningEvidenceRoleV1::Generator,
            1,
            &payload,
            "generator-evidence",
        );
        completeness.candidates_digest = digest("different-candidates");
        assert_eq!(
            writer.append_decision(
                Digest32::ZERO,
                request,
                &completeness,
                &generator,
                50,
            ),
            Err(ComposedLearningError::CandidateBinding)
        );
        assert!(writer.snapshot().expect("snapshot").records().is_empty());
        drop(writer);
        std::fs::remove_dir_all(root).expect("remove test root");
    }
}
