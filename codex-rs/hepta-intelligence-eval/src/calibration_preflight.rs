//! Authenticated early veto over a real ledger cut. Calibration cannot qualify
//! a model: passing this gate still requires the final-holdout product runner.
use codex_hepta_learning_ledger::AuthenticatedOutcomeTerminality;
use codex_hepta_learning_ledger::CalibrationCutBindingV1;
use codex_hepta_learning_ledger::CalibrationCycleScopeV2;
use codex_hepta_learning_ledger::DatasetFreezePlanV2;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerSnapshot;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::calibration_cut_signing_payload_v1;
use codex_hepta_learning_ledger::calibration_cycle_cut_signing_payload_v2;
use codex_hepta_learning_ledger::dataset_freeze_signing_payload_v2;
use codex_hepta_learning_ledger::verify_dataset_snapshot_receipt_against_ledger_v3;
use codex_hepta_learning_ledger::verify_signed_actor_separation;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use std::collections::BTreeMap;

pub struct SignedCalibrationPreflightRequestV1<'a> {
    pub snapshot: &'a LedgerSnapshot,
    pub dataset: &'a DatasetSnapshotReceiptV3,
    pub cut_binding: &'a CalibrationCutBindingV1,
    pub generator_payload: &'a [u8],
    pub minimum_primary_improvement: FixedQ32,
    pub generator: &'a SignedLearningEvidenceV1,
    pub observer: &'a SignedLearningEvidenceV1,
    pub producer: &'a SignedLearningEvidenceV1,
    pub evaluator: &'a SignedLearningEvidenceV1,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CalibrationPreflightDispositionV1 {
    Rejected,
    RequiresFinalQualification,
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedCalibrationPreflightDecisionV1 {
    pub disposition: CalibrationPreflightDispositionV1,
    pub candidate_correct: u64,
    pub baseline_correct: u64,
    pub labeled_pairs: u64,
    pub observed_improvement: FixedQ32,
    pub dataset_digest: Digest32,
    pub evidence_digest: Digest32,
    pub authority: AuthorityPosture,
}
#[derive(Debug)]
pub enum CalibrationPreflightError {
    Evidence(codex_hepta_learning_ledger::SignedEvidenceError),
    Ledger(codex_hepta_learning_ledger::ProductionLedgerError),
    Dataset(codex_hepta_learning_ledger::DatasetReceiptError),
    Binding(&'static str),
    Arithmetic,
}
impl std::fmt::Display for CalibrationPreflightError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for CalibrationPreflightError {}
impl From<codex_hepta_learning_ledger::SignedEvidenceError> for CalibrationPreflightError {
    fn from(v: codex_hepta_learning_ledger::SignedEvidenceError) -> Self {
        Self::Evidence(v)
    }
}
impl From<codex_hepta_learning_ledger::ProductionLedgerError> for CalibrationPreflightError {
    fn from(v: codex_hepta_learning_ledger::ProductionLedgerError) -> Self {
        Self::Ledger(v)
    }
}
impl From<codex_hepta_learning_ledger::DatasetReceiptError> for CalibrationPreflightError {
    fn from(v: codex_hepta_learning_ledger::DatasetReceiptError) -> Self {
        Self::Dataset(v)
    }
}

pub fn calibration_preflight_signing_payload_v1(
    cut: &[u8],
    minimum_primary_improvement: FixedQ32,
) -> Result<Vec<u8>, CalibrationPreflightError> {
    if cut.len() > 4 * 1024 * 1024 || minimum_primary_improvement < FixedQ32::ZERO {
        return Err(CalibrationPreflightError::Binding(
            "bounded preregistered calibration policy",
        ));
    }
    let mut bytes = b"hepta.intelligence-eval.signed-calibration-preflight.v1".to_vec();
    bytes.extend_from_slice(Digest32::of_bytes(cut).as_array());
    bytes.extend_from_slice(&minimum_primary_improvement.raw().to_be_bytes());
    Ok(bytes)
}
pub fn decide_with_signed_calibration_preflight_v1(
    request: SignedCalibrationPreflightRequestV1<'_>,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<SignedCalibrationPreflightDecisionV1, CalibrationPreflightError> {
    decide_current_cycle(request, None, verifier, now)
}
/// V2 verifies the full original ledger/dataset and a signed complete current
/// cycle. It never interprets repeated source tasks as independent samples.
pub fn decide_with_signed_calibration_cycle_v2(
    request: SignedCalibrationPreflightRequestV1<'_>,
    cycle: &CalibrationCycleScopeV2,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<SignedCalibrationPreflightDecisionV1, CalibrationPreflightError> {
    decide_current_cycle(request, Some(cycle), verifier, now)
}
pub fn calibration_cycle_preflight_signing_payload_v2(
    cut: &[u8],
    margin: FixedQ32,
) -> Result<Vec<u8>, CalibrationPreflightError> {
    if cut.len() > 4 * 1024 * 1024 || margin < FixedQ32::ZERO {
        return Err(CalibrationPreflightError::Binding(
            "bounded cycle calibration policy",
        ));
    }
    let mut payload = b"hepta.intelligence-eval.signed-calibration-cycle-preflight.v2".to_vec();
    payload.extend_from_slice(Digest32::of_bytes(cut).as_array());
    payload.extend_from_slice(&margin.raw().to_be_bytes());
    Ok(payload)
}
fn decide_current_cycle(
    request: SignedCalibrationPreflightRequestV1<'_>,
    cycle: Option<&CalibrationCycleScopeV2>,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<SignedCalibrationPreflightDecisionV1, CalibrationPreflightError> {
    let generator = verifier.verify(
        LearningEvidenceRoleV1::Generator,
        request.generator,
        request.generator_payload,
        now,
    )?;
    let cut_payload = cycle.map_or_else(
        || calibration_cut_signing_payload_v1(request.cut_binding),
        |scope| calibration_cycle_cut_signing_payload_v2(request.cut_binding, scope),
    );
    let observer = verifier.verify(
        LearningEvidenceRoleV1::Observer,
        request.observer,
        &cut_payload,
        now,
    )?;
    let payload = if cycle.is_some() {
        calibration_cycle_preflight_signing_payload_v2(
            &cut_payload,
            request.minimum_primary_improvement,
        )?
    } else {
        calibration_preflight_signing_payload_v1(&cut_payload, request.minimum_primary_improvement)?
    };
    let evaluator = verifier.verify(
        LearningEvidenceRoleV1::Evaluator,
        request.evaluator,
        &payload,
        now,
    )?;
    for (left, right) in [
        (&generator, &observer),
        (&generator, &evaluator),
        (&observer, &evaluator),
    ] {
        verify_signed_actor_separation(left, right, now)?;
    }
    verify_dataset_snapshot_receipt_against_ledger_v3(request.dataset, request.snapshot, now)?;
    if request.cut_binding.dataset_digest != request.dataset.snapshot.dataset_digest
        || request.cut_binding.acknowledged_head != request.snapshot.head_digest
        || request.cut_binding.acknowledged_sequence
            != request
                .snapshot
                .records()
                .last()
                .map_or(0, |r| r.sequence.get())
        || request.cut_binding.generator_payload_digest
            != Digest32::of_bytes(request.generator_payload)
        || request.cut_binding.freeze_payload_digest != request.producer.payload_digest
    {
        return Err(CalibrationPreflightError::Binding(
            "signed cut semantic binding",
        ));
    }
    let authentication = |item: &SignedLearningEvidenceV1| {
        let mut bytes = item.signing_bytes();
        bytes.extend_from_slice(&item.signature);
        Digest32::of_bytes(&bytes)
    };
    if authentication(request.generator) != request.cut_binding.generator_authentication_digest
        || authentication(request.producer) != request.cut_binding.freeze_authentication_digest
    {
        return Err(CalibrationPreflightError::Binding(
            "signed source authentication binding",
        ));
    }
    let plan = DatasetFreezePlanV2 {
        snapshot_id: request.dataset.snapshot.snapshot_id.clone(),
        objective_digest: request.dataset.snapshot.objective_digest,
        inclusion_policy_digest: request.dataset.inclusion_policy_digest,
    };
    let producer_payload = dataset_freeze_signing_payload_v2(request.snapshot, &plan)?;
    let producer = verifier.verify(
        LearningEvidenceRoleV1::Evaluator,
        request.producer,
        &producer_payload,
        now,
    )?;
    if producer.principal() != &request.dataset.producer {
        return Err(CalibrationPreflightError::Binding(
            "freeze producer identity",
        ));
    }
    verify_signed_actor_separation(&producer, &evaluator, now)?;
    verify_signed_actor_separation(&producer, &generator, now)?;
    if request.cut_binding.candidate_weights_digest.is_zero()
        || request.cut_binding.baseline_weights_digest.is_zero()
        || request.cut_binding.candidate_weights_digest
            == request.cut_binding.baseline_weights_digest
        || request.dataset.snapshot.pending_outcomes != 0
        || request.dataset.snapshot.censored_outcomes != 0
    {
        return Err(CalibrationPreflightError::Binding(
            "complete two-policy calibration scope",
        ));
    }
    let mut auth = request.generator.signing_bytes();
    auth.extend_from_slice(&request.generator.signature);
    let current_records = crate::calibration_cycle_scope::current_records(
        request.snapshot,
        request.cut_binding,
        cycle,
    )?;
    let first = current_records
        .first()
        .ok_or(CalibrationPreflightError::Binding("empty signed ledger"))?;
    if !matches!(&first.event,LedgerEvent::AuthenticatedDecisionV2(v) if v.authentication_digest==Digest32::of_bytes(&auth))
    {
        return Err(CalibrationPreflightError::Binding(
            "generator signature is not the admitted first decision",
        ));
    }
    let prefix = format!("calibration.episode.{}.", request.cut_binding.audit_digest);
    let mut decisions = BTreeMap::new();
    let mut counts = [0u64; 2];
    let mut correct = [0u64; 2];
    for record in current_records {
        match &record.event {
            LedgerEvent::AuthenticatedDecisionV2(v) => {
                if v.generator_id != generator.principal().principal_id
                    || v.generator_controller_id != *generator.controller_id()
                    || v.generator_signing_key_digest != generator.principal().signing_key_digest
                    || v.objective_digest != verifier.objective_digest()
                    || !v.episode_id.as_str().starts_with(&prefix)
                {
                    return Err(CalibrationPreflightError::Binding(
                        "admitted generator scope/controller",
                    ));
                }
                let policy = if v.policy_digest == request.cut_binding.candidate_weights_digest {
                    0
                } else if v.policy_digest == request.cut_binding.baseline_weights_digest {
                    1
                } else {
                    return Err(CalibrationPreflightError::Binding(
                        "unexpected calibration policy",
                    ));
                };
                if decisions.insert(v.episode_id.clone(), policy).is_some() {
                    return Err(CalibrationPreflightError::Binding(
                        "duplicate calibration decision",
                    ));
                }
            }
            LedgerEvent::AuthenticatedOutcomeV2(v) => {
                if v.observer_id != observer.principal().principal_id
                    || v.observer_controller_id != *observer.controller_id()
                    || v.observer_signing_key_digest != observer.principal().signing_key_digest
                    || v.terminality != AuthenticatedOutcomeTerminality::Terminal
                    || v.correction_predecessor.is_some()
                {
                    return Err(CalibrationPreflightError::Binding(
                        "actual terminal observer scope/controller",
                    ));
                }
                let policy =
                    decisions
                        .remove(&v.episode_id)
                        .ok_or(CalibrationPreflightError::Binding(
                            "outcome without its unique decision",
                        ))?;
                let value = match v.value {
                    Some(FixedQ32::ZERO) => 0,
                    Some(FixedQ32::ONE) => 1,
                    _ => {
                        return Err(CalibrationPreflightError::Binding(
                            "fixed binary correctness reward",
                        ));
                    }
                };
                counts[policy] += 1;
                correct[policy] += value;
            }
            _ => {
                return Err(CalibrationPreflightError::Binding(
                    "calibration cut contains unrelated event",
                ));
            }
        }
    }
    if !decisions.is_empty() || counts[0] == 0 || counts[0] != counts[1] || counts[0] > 2048 {
        return Err(CalibrationPreflightError::Binding(
            "all paired terminal policy outcomes",
        ));
    }
    let numerator = i128::from(correct[0]) * i128::from(counts[1])
        - i128::from(correct[1]) * i128::from(counts[0]);
    let denominator = i128::from(counts[0]) * i128::from(counts[1]);
    let widened = numerator
        .checked_mul(1i128 << 32)
        .ok_or(CalibrationPreflightError::Arithmetic)?;
    let improvement = FixedQ32::from_raw(
        i64::try_from(widened / denominator).map_err(|_| CalibrationPreflightError::Arithmetic)?,
    );
    let passed = widened > i128::from(request.minimum_primary_improvement.raw()) * denominator;
    let mut evidence = payload;
    for item in [
        request.generator,
        request.observer,
        request.producer,
        request.evaluator,
    ] {
        evidence.extend_from_slice(Digest32::of_bytes(&item.signing_bytes()).as_array());
        evidence.extend_from_slice(&item.signature);
    }
    Ok(SignedCalibrationPreflightDecisionV1 {
        disposition: if passed {
            CalibrationPreflightDispositionV1::RequiresFinalQualification
        } else {
            CalibrationPreflightDispositionV1::Rejected
        },
        candidate_correct: correct[0],
        baseline_correct: correct[1],
        labeled_pairs: counts[0],
        observed_improvement: improvement,
        dataset_digest: request.dataset.snapshot.dataset_digest,
        evidence_digest: Digest32::of_bytes(&evidence),
        authority: AuthorityPosture::DENY_ALL,
    })
}
