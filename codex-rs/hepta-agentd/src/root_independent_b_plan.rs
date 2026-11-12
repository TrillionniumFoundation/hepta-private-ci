//! A one-session challenge from the actual Root purpose. This opaque value is
//! not a native plan, execution receipt, evaluator grant or heldout capability.

use super::*;
use crate::cell_q24_training_receipt_owner::OriginalQ24TrainingOperationEvidenceV1;

pub(crate) struct OriginalRootBPlanChallengeV1<'a> {
    client: &'a OriginalRootIndependentBEvaluationClientV1,
    data: PreparedPlanData,
    not_send: std::marker::PhantomData<std::rc::Rc<()>>,
}

impl OriginalRootBPlanChallengeV1<'_> {
    pub(crate) fn require_original_training(
        &self,
        original: &OriginalQ24TrainingOperationEvidenceV1<'_>,
        scope: &FrozenLearningScopeV2,
    ) -> Result<Digest32, Error> {
        original.require_current_training_source()?;
        self.client.require_initial(original.snapshot(), scope)?;
        let candidate = original.original_candidate_material()?;
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(unavailable)?
            .as_secs();
        if self.data.initial != self.client.bootstrap.initial
            || self.data.scope != scope.binding().to_string()
            || self.data.training_head != original.snapshot().head_digest.to_string()
            || self.data.candidate_bundle
                != candidate.bundle.digest().map_err(unavailable)?.to_string()
            || self.data.profile != original.snapshot().request.evaluation_profile.to_string()
            || self.data.expires_at_seconds
                != original.snapshot().request.envelope.expiry_unix_seconds
            || now >= self.data.expires_at_seconds
        {
            return Err(Error::WrongScope);
        }
        digest(&self.data.comparison_digest).map_err(unavailable)?;
        digest(&self.data.plan_digest).map_err(unavailable)
    }

    pub(crate) fn original_binding(&self) -> Result<Digest32, Error> {
        self.client.original_binding()
    }

    pub(super) fn wait_original_source(
        &self,
        original: &OriginalQ24TrainingOperationEvidenceV1<'_>,
        scope: &FrozenLearningScopeV2,
    ) -> Result<SourceReadyData, Error> {
        self.require_original_training(original, scope)?;
        let reader = self
            .client
            .source_admitted
            .try_lock()
            .map_err(|_| Error::CommitUncertain)?
            .take()
            .ok_or(Error::CommitUncertain)?;
        // The original frame has completed. No client stream lock is held and
        // this wait cannot renew the session or start a second request lane.
        let raw = crate::root_independent_b_notice::receive_original_notice(
            reader,
            self.client.bootstrap.root.pid,
            self.client.end,
            || {
                self.client
                    .connection
                    .require_original()
                    .map_err(std::io::Error::other)
            },
        )
        .map_err(unavailable)?;
        let ready = SourceReadyData::decode(&raw, &self.client.bootstrap.binding, &self.data)
            .map_err(unavailable)?;
        self.require_original_training(original, scope)?;
        Ok(ready)
    }
}

impl OriginalRootIndependentBEvaluationClientV1 {
    pub(super) fn prepare_from_original_training(
        &self,
        original: &OriginalQ24TrainingOperationEvidenceV1<'_>,
        scope: &FrozenLearningScopeV2,
    ) -> Result<OriginalRootBPlanChallengeV1<'_>, Error> {
        let result = (|| {
            self.write_original_candidate_data(original, scope)?;
            let payload = learning_iteration_receipt_signing_bytes_v1(original.receipt())?;
            let Observation::Prepared(data) = self.exchange(Command::PrepareCandidate {
                training_head: original.snapshot().head_digest.to_string(),
                training_attestation: learning_owner_evidence::encode(
                    &payload,
                    original.attestation(),
                )
                .map_err(unavailable)?,
            })?
            else {
                return Err(Error::CommitUncertain);
            };
            let challenge = OriginalRootBPlanChallengeV1 {
                client: self,
                data: *data,
                not_send: std::marker::PhantomData,
            };
            challenge.require_original_training(original, scope)?;
            Ok(challenge)
        })();
        if result.is_err() {
            self.refused.store(true, Ordering::Release);
        }
        result
    }
}
