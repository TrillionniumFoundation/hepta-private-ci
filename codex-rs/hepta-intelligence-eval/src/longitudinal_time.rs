//! Signed observed-time admission; window names alone are not calendar evidence.
//!
//! The host supplies a trusted Unix-microsecond clock, preregistered duration
//! policy, and current signer configuration. Signatures authenticate the
//! observer's attestation, not empirical truth or reliable clocks by themselves.
use std::collections::BTreeSet;

use crate::EvaluationClaimScopeV1;
use crate::IndependentEvaluationBundleV1;
use crate::MetricRoleContractV2;
use crate::SignedEvaluationDecisionV1;
use crate::SignedEvaluationError;
use crate::SignedEvaluationEvidenceV1;
use crate::decide_independently_v2;
use crate::evaluation_signing_payload_v2;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_role_separation;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObservedFutureWindowV1 {
    pub window_id: StableId,
    pub snapshot_id: StableId,
    pub starts_unix_micros: u64,
    pub ends_unix_micros: u64,
    pub observation_count: u64,
    pub observed_source_cut: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LongitudinalTimeEvidenceV1 {
    pub frozen_unix_micros: u64,
    pub windows: Vec<ObservedFutureWindowV1>,
    /// A trusted, independent observer attests real collection intervals and
    /// source cuts. Simulation/generated timestamps cannot establish this role.
    pub observer: SignedLearningEvidenceV1,
}

/// Payload for the independent observer. The minimum duration is a host-owned,
/// preregistered policy input; it is signed, never fitted after seeing outcomes.
pub fn future_window_signing_payload_v1(
    bundle: &IndependentEvaluationBundleV1,
    timing: &LongitudinalTimeEvidenceV1,
    minimum_window_micros: u64,
) -> Result<Vec<u8>, SignedEvaluationError> {
    if bundle.claim_scope != EvaluationClaimScopeV1::SystemLongitudinal
        || minimum_window_micros == 0
        || !(2..=32).contains(&timing.windows.len())
    {
        return Err(SignedEvaluationError::Timing("scope_or_bounds"));
    }
    let mut bytes = b"hepta.intelligence-eval.observed-future-windows.unix-micros.v1\0".to_vec();
    for digest in [
        bundle.frozen_plan.plan_digest,
        bundle.dataset_digest,
        bundle.objective_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&minimum_window_micros.to_be_bytes());
    bytes.extend_from_slice(&timing.frozen_unix_micros.to_be_bytes());
    bytes.extend_from_slice(&(timing.windows.len() as u64).to_be_bytes());
    for window in &timing.windows {
        for id in [&window.window_id, &window.snapshot_id] {
            bytes.extend_from_slice(&(id.as_str().len() as u16).to_be_bytes());
            bytes.extend_from_slice(id.as_str().as_bytes());
        }
        for value in [
            window.starts_unix_micros,
            window.ends_unix_micros,
            window.observation_count,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        bytes.extend_from_slice(window.observed_source_cut.as_array());
    }
    Ok(bytes)
}

pub fn longitudinal_evaluation_signing_payload_v3(
    bundle: &IndependentEvaluationBundleV1,
    roles: &[MetricRoleContractV2],
    timing: &LongitudinalTimeEvidenceV1,
    minimum_window_micros: u64,
) -> Result<Vec<u8>, SignedEvaluationError> {
    let mut bytes = b"hepta.intelligence-eval.signed-request.v3\0".to_vec();
    bytes.extend_from_slice(&evaluation_signing_payload_v2(bundle, roles)?);
    bytes.extend_from_slice(&future_window_signing_payload_v1(
        bundle,
        timing,
        minimum_window_micros,
    )?);
    bytes.extend_from_slice(&timing.observer.signing_bytes());
    bytes.extend_from_slice(&timing.observer.signature);
    Ok(bytes)
}

/// External longitudinal entrypoint. Does not mint a holdout-use anchor,
/// authenticate a storage namespace, select an artifact, or bypass statistics.
pub fn decide_with_signed_longitudinal_evidence_v3(
    bundle: IndependentEvaluationBundleV1,
    roles: Vec<MetricRoleContractV2>,
    evidence: &SignedEvaluationEvidenceV1,
    timing: &LongitudinalTimeEvidenceV1,
    minimum_window_micros: u64,
    verifier: &LearningEvidenceVerifierV1,
    now_unix_micros: u64,
) -> Result<SignedEvaluationDecisionV1, SignedEvaluationError> {
    let payload =
        longitudinal_evaluation_signing_payload_v3(&bundle, &roles, timing, minimum_window_micros)?;
    let authentication = crate::signed_evaluation::authenticate(
        &bundle,
        evidence,
        verifier,
        &payload,
        now_unix_micros,
    )?;
    let observer_payload =
        future_window_signing_payload_v1(&bundle, timing, minimum_window_micros)?;
    let observer = verifier.verify(
        LearningEvidenceRoleV1::Observer,
        &timing.observer,
        &observer_payload,
        now_unix_micros,
    )?;
    let generator = verifier.verify(
        LearningEvidenceRoleV1::Generator,
        &evidence.generator_plan,
        bundle.frozen_plan.plan_digest.as_array(),
        now_unix_micros,
    )?;
    verify_signed_role_separation(&generator, &observer, now_unix_micros)?;
    validate_observed_windows(
        &bundle,
        timing,
        evidence.generator_plan.issued_at,
        minimum_window_micros,
        now_unix_micros,
    )?;
    let mut authenticated = authentication.as_array().to_vec();
    authenticated.extend_from_slice(&timing.observer.signature);
    Ok(SignedEvaluationDecisionV1 {
        decision: decide_independently_v2(bundle, roles, now_unix_micros)?,
        trust_digest: verifier.trust_digest(),
        authentication_digest: Digest32::of_bytes(&authenticated),
    })
}

pub(crate) fn validate_observed_windows(
    bundle: &IndependentEvaluationBundleV1,
    timing: &LongitudinalTimeEvidenceV1,
    frozen_signature_time: u64,
    minimum_window_micros: u64,
    now: u64,
) -> Result<(), SignedEvaluationError> {
    // Bounds also apply when this validation is invoked in isolation.
    future_window_signing_payload_v1(bundle, timing, minimum_window_micros)?;
    if timing.frozen_unix_micros == 0 || timing.frozen_unix_micros != frozen_signature_time {
        return Err(SignedEvaluationError::Timing("freeze_binding"));
    }
    let expected = bundle.future_window_ids.iter().collect::<BTreeSet<_>>();
    let mut seen = BTreeSet::new();
    let mut cuts = BTreeSet::new();
    let mut previous_end = timing.frozen_unix_micros;
    for window in &timing.windows {
        if !seen.insert(&window.window_id)
            || !bundle.snapshot_ids.contains(&window.snapshot_id)
            || window.observation_count == 0
            || window.observed_source_cut.is_zero()
            || !cuts.insert(window.observed_source_cut)
        {
            return Err(SignedEvaluationError::Timing("window_source_binding"));
        }
        if window.starts_unix_micros < previous_end
            || window.starts_unix_micros <= timing.frozen_unix_micros
            || window
                .ends_unix_micros
                .checked_sub(window.starts_unix_micros)
                .is_none_or(|duration| duration < minimum_window_micros)
            || window.ends_unix_micros > timing.observer.issued_at
            || window.ends_unix_micros > now
        {
            return Err(SignedEvaluationError::Timing("window_not_observed"));
        }
        previous_end = window.ends_unix_micros;
    }
    if expected.len() != bundle.future_window_ids.len()
        || seen != expected
        || !seen.contains(&bundle.frozen_plan.final_holdout_window_id)
    {
        return Err(SignedEvaluationError::Timing("window_set"));
    }
    Ok(())
}
