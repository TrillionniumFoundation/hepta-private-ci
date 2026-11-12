//! A synchronous borrow of the actual new recipient's Root context. It can
//! surround completed historical observation, never an old learning writer or
//! a new execution. The complete persistent acceptance must still be checked
//! by the enclosing terminal/history operation before it returns any result.

use std::cell::RefCell;
use std::marker::PhantomData;
use std::rc::Rc;

use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;

use super::*;
use crate::root_historical_learning_trust_data::HistoricalLearningTrustPayloadV1;

pub(crate) struct OriginalCompletedLearningContextV1<'a> {
    initial: &'a LearningIterationSnapshotV1,
    scope: &'a FrozenLearningScopeV2,
    terminal: &'a LearningIterationSnapshotV1,
    writer: &'a str,
    profile: &'a str,
    verifier: &'a LearningEvidenceVerifierV1,
    trust: &'a HistoricalLearningTrustPayloadV1,
    service: &'a HostAuthorityService,
    original_task: &'a RootOriginalHistoricalCompleteTaskObservationV1,
    current_signatures: RefCell<Vec<SignedLearningEvidenceV1>>,
    end: Instant,
    not_send: PhantomData<Rc<()>>,
}

impl OriginalCompletedLearningContextV1<'_> {
    pub(crate) fn initial(&self) -> &LearningIterationSnapshotV1 {
        self.initial
    }
    pub(crate) fn frozen_scope(&self) -> &FrozenLearningScopeV2 {
        self.scope
    }
    pub(crate) fn terminal(&self) -> &LearningIterationSnapshotV1 {
        self.terminal
    }
    pub(crate) fn original_writer_proof(&self) -> &str {
        self.writer
    }
    pub(crate) fn recipient_profile(&self) -> &str {
        self.profile
    }
    pub(crate) fn original_end(&self) -> Instant {
        self.end
    }
    pub(crate) fn current_verifier(&self) -> &LearningEvidenceVerifierV1 {
        self.verifier
    }

    pub(crate) fn original_task_publication(
        &self,
    ) -> crate::circuit_task::RootHistoricalTaskPublicationDataV1 {
        RootOriginalHistoricalCompleteTaskObservationV1::publication_read_data(self.original_task)
    }

    pub(crate) fn require_original_publication_context(
        &self,
        service: &HostAuthorityService,
        end: Instant,
    ) -> io::Result<()> {
        if !std::ptr::eq(self.service, service) || self.end != end {
            return Err(io::Error::other(
                "completed publication Root context differs",
            ));
        }
        require_end(self.end)
    }

    pub(crate) fn current_unix_seconds(&self) -> io::Result<u64> {
        require_end(self.end)?;
        HostAuthorityService::original_learning_unix_seconds(self.service)
    }

    /// Current trust/revocation is separate from the retained original
    /// signature-verification instant. This check does not validate a payload
    /// and cannot turn an expired signature into a new execution permission.
    pub(crate) fn require_current_signer(
        &self,
        signed: &SignedLearningEvidenceV1,
    ) -> io::Result<()> {
        let mut signers = self
            .trust
            .signed
            .distribution
            .signers
            .iter()
            .filter(|signer| signer.principal_id == signed.principal_id.as_str());
        let signer = signers
            .next()
            .ok_or_else(|| io::Error::other("current completed-history signer missing"))?
            .original_signer()?;
        if signers.next().is_some() || signed.trust_digest != self.verifier.trust_digest() {
            return Err(io::Error::other("current completed-history trust differs"));
        }
        self.verifier
            .require_signer_binding(signed.role, &signer, self.current_unix_seconds()?)
            .map_err(io::Error::other)?;
        let mut recorded = self
            .current_signatures
            .try_borrow_mut()
            .map_err(|_| io::Error::other("completed-history signer borrow busy"))?;
        if !recorded.iter().any(|previous| {
            previous.principal_id == signed.principal_id && previous.role == signed.role
        }) {
            if recorded.len() == 16 {
                return Err(io::Error::other("completed-history signer bound exceeded"));
            }
            recorded.push(signed.clone());
        }
        Ok(())
    }

    pub(super) fn require_current_freeze_signer(
        &self,
        signed: &SignedLearningEvidenceV1,
    ) -> io::Result<()> {
        if signed.principal_id.as_str() != self.trust.freeze_evaluator.principal_id
            || signed.role != codex_hepta_learning_ledger::LearningEvidenceRoleV1::Evaluator
        {
            return Err(io::Error::other("original fixed freeze signer differs"));
        }
        Self::require_current_signer(self, signed)
    }

    fn revalidate_recorded_signers(&self) -> io::Result<()> {
        let signatures = self
            .current_signatures
            .try_borrow()
            .map_err(|_| io::Error::other("completed-history signer borrow busy"))?
            .clone();
        for signed in signatures {
            Self::require_current_signer(self, &signed)?;
        }
        Ok(())
    }
}

impl HistoricalTaskReadRuntime {
    pub(super) fn with_original_completed_context<T>(
        &self,
        service: &HostAuthorityService,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        scope: &FrozenLearningScopeV2,
        checkpoint: &crate::LearningIterationCheckpointRecordV1,
        observed: &RootOriginalHistoricalCompleteTaskObservationV1,
        end: Instant,
        action: impl FnOnce(&OriginalCompletedLearningContextV1<'_>) -> io::Result<T>,
    ) -> io::Result<T> {
        require_end(end)?;
        self.metadata.require_metadata_unchanged()?;
        let result = service.with_learning_profile(
            config,
            registration,
            owner,
            &self.deployment.initial,
            |initial, proof| {
                let expected = self.profile.require_original_context(
                    &registration.registered_identity.identity()?,
                    &proof,
                    &self.deployment.initial,
                )?;
                if expected != initial || self.phase.load(Ordering::Acquire) != SERVING {
                    return Err(io::Error::other("completed-history recipient changed"));
                }
                let terminal =
                    crate::LearningIterationCheckpointRecordV1::read_original_completed_scoped(
                        checkpoint, &initial, scope,
                    )
                    .map_err(io::Error::other)?;
                let ledger =
                    RootOriginalHistoricalCompleteTaskObservationV1::ledger_read_data(observed)?;
                let trust = RootHistoricalLearningTrustV1::read_original_payload(
                    &self.learning_trust,
                    service,
                    &initial,
                    &ledger,
                )?;
                let (activated, _) = trust.activate_for_recipient(
                    &initial,
                    HostAuthorityService::original_learning_unix_seconds(service)?,
                )?;
                trust.require_activation_pin(&initial, &activated, &self.learning_trust.pin)?;
                require_end(end)?;
                let context = OriginalCompletedLearningContextV1 {
                    initial: &initial,
                    scope,
                    terminal: &terminal,
                    writer: &proof,
                    profile: &self.profile.binding,
                    verifier: activated.verifier(),
                    trust: &trust,
                    service,
                    original_task: observed,
                    current_signatures: RefCell::new(Vec::new()),
                    end,
                    not_send: PhantomData,
                };
                let value = action(&context);
                RootHistoricalLearningTrustV1::revalidate(&self.learning_trust, service, &initial)?;
                context.revalidate_recorded_signers()?;
                self.metadata.require_metadata_unchanged()?;
                require_end(end)?;
                value
            },
        );
        // The original writer/issuer/pidfd context above has completed before
        // this final deadline check. Outer persistent arms enclose this method.
        self.metadata.require_metadata_unchanged()?;
        require_end(end)?;
        result
    }
}
