//! Identity and freshness checks for owner-issued stage receipts.

use super::*;

pub(super) fn validate_request(
    request: &LearningOperatorShadowRequestV1,
) -> Result<(), LearningOperatorShadowErrorV1> {
    if [
        request.objective_digest,
        request.training_source_digest,
        request.evaluation_source_digest,
        request.predecessor_artifact_digest,
    ]
    .into_iter()
    .any(Digest32::is_zero)
    {
        return Err(LearningOperatorShadowErrorV1::InvalidRequest(
            "all objective, source, and predecessor digests must be nonzero",
        ));
    }
    if request.training_source_digest == request.evaluation_source_digest {
        return Err(LearningOperatorShadowErrorV1::InvalidRequest(
            "training and independent evaluation sources must differ",
        ));
    }
    if request.expected_authority_epoch == 0
        || request.expected_stop_epoch == 0
        || request.now_unix_micros == 0
        || request.now_unix_micros >= request.deadline_unix_micros
    {
        return Err(LearningOperatorShadowErrorV1::InvalidRequest(
            "trusted epochs and an unexpired absolute deadline are mandatory",
        ));
    }
    request
        .predecessor_generation
        .next()
        .map_err(|_| LearningOperatorShadowErrorV1::InvalidRequest("generation overflow"))?;
    Ok(())
}

pub(super) fn validate_frozen(
    request: &LearningOperatorShadowRequestV1,
    value: &FrozenOperatorDatasetV1,
    expected_source: Digest32,
    not_before: u64,
    now: u64,
    stage: LearningOperatorShadowStageV1,
) -> Result<(), LearningOperatorShadowErrorV1> {
    if value.owner_id != request.owner_id
        || value.authority_epoch != request.expected_authority_epoch
        || value.stop_epoch != request.expected_stop_epoch
        || value.source_digest != expected_source
        || value.ledger_head_digest.is_zero()
        || value.dataset_digest.is_zero()
        || value.row_commitment_digest.is_zero()
        || !valid_window(request, value.frozen_at, value.expires_at, not_before, now)
    {
        return invariant(
            stage,
            "frozen dataset is stale or not bound to owner, epochs, source, rows, and timeline",
        );
    }
    Ok(())
}

pub(super) fn valid_fresh_load(
    request: &LearningOperatorShadowRequestV1,
    persisted: &PersistedOperatorCandidateV1,
    loaded: &FreshProcessLoadedOperatorV1,
    not_before: u64,
    now: u64,
) -> bool {
    loaded.artifact_digest == persisted.artifact_digest
        && loaded.payload_digest == persisted.payload_digest
        && loaded.selection_digest == persisted.selection_digest
        && loaded.storage_receipt_digest == persisted.storage_receipt_digest
        && !loaded.boot_nonce_digest.is_zero()
        && !loaded.loaded_digest.is_zero()
        && valid_window(
            request,
            loaded.loaded_at,
            loaded.expires_at,
            not_before,
            now,
        )
}

#[allow(clippy::too_many_arguments)]
pub(super) fn valid_shadow(
    request: &LearningOperatorShadowRequestV1,
    candidate: &FittedOperatorCandidateV1,
    selection: &SelectedOperatorCandidateV1,
    loaded: &FreshProcessLoadedOperatorV1,
    shadow: &OperatorShadowReceiptV1,
    not_before: u64,
    now: u64,
) -> bool {
    shadow.process_id == loaded.process_id
        && shadow.loaded_digest == loaded.loaded_digest
        && shadow.artifact_digest == candidate.artifact_digest
        && shadow.selection_digest == selection.selection_digest
        && !shadow.shadow_digest.is_zero()
        && shadow.observation_count > 0
        && valid_window(
            request,
            shadow.observed_at,
            shadow.expires_at,
            not_before,
            now,
        )
}

pub(super) fn valid_currentness(
    request: &LearningOperatorShadowRequestV1,
    candidate: &FittedOperatorCandidateV1,
    selection: &SelectedOperatorCandidateV1,
    currentness: &OperatorCurrentnessReceiptV1,
    not_before: u64,
    now: u64,
) -> bool {
    currentness.artifact_digest == candidate.artifact_digest
        && currentness.selection_digest == selection.selection_digest
        && !currentness.ledger_head_digest.is_zero()
        && !currentness.registry_head_digest.is_zero()
        && currentness.authority_epoch == request.expected_authority_epoch
        && currentness.stop_epoch == request.expected_stop_epoch
        && !currentness.currentness_digest.is_zero()
        && valid_window(
            request,
            currentness.observed_at,
            currentness.expires_at,
            not_before,
            now,
        )
}

pub(super) fn valid_window(
    request: &LearningOperatorShadowRequestV1,
    issued_at: u64,
    expires_at: u64,
    not_before: u64,
    now: u64,
) -> bool {
    issued_at >= request.now_unix_micros
        && issued_at >= not_before
        && issued_at <= now
        && now < expires_at
        && issued_at < expires_at
        && issued_at < request.deadline_unix_micros
        && expires_at <= request.deadline_unix_micros
}

pub(super) fn invariant<T>(
    stage: LearningOperatorShadowStageV1,
    message: &'static str,
) -> Result<T, LearningOperatorShadowErrorV1> {
    Err(LearningOperatorShadowErrorV1::Invariant { stage, message })
}

/// A receipt cannot advance or rewind trusted host time.
pub(super) struct ShadowHostClockV1 {
    pub(super) observed_at: u64,
}

impl ShadowHostClockV1 {
    pub(super) fn new(admitted_at: u64) -> Self {
        Self {
            observed_at: admitted_at,
        }
    }

    pub(super) fn check<P: LearningOperatorShadowPortsV1>(
        &mut self,
        ports: &mut P,
        request: &LearningOperatorShadowRequestV1,
        stage: LearningOperatorShadowStageV1,
        valid_until: u64,
    ) -> Result<(), LearningOperatorShadowErrorV1> {
        let observed_at = ports.now_unix_micros();
        if observed_at < self.observed_at {
            return invariant(stage, "trusted host clock regressed");
        }
        self.observed_at = observed_at;
        if observed_at >= request.deadline_unix_micros || observed_at >= valid_until {
            return invariant(stage, "trusted host deadline or source receipt expired");
        }
        Ok(())
    }
}

pub(super) fn checked_port<P, T>(
    ports: &mut P,
    request: &LearningOperatorShadowRequestV1,
    clock: &mut ShadowHostClockV1,
    stage: LearningOperatorShadowStageV1,
    valid_until: u64,
    call: impl FnOnce(&mut P) -> Result<T, String>,
) -> Result<T, LearningOperatorShadowErrorV1>
where
    P: LearningOperatorShadowPortsV1,
{
    clock.check(ports, request, stage, valid_until)?;
    let value =
        call(ports).map_err(|message| LearningOperatorShadowErrorV1::Port { stage, message })?;
    clock.check(ports, request, stage, valid_until)?;
    Ok(value)
}
