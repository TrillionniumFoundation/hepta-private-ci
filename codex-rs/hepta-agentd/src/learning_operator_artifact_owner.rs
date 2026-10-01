//! Real immutable storage adapter for an independently selected tabular fit.
//!
//! The artifact owner's existing fenced checkpoint is the only write journal.
//! Stored bytes grant no activation, shadow execution or rollback authority.

use std::error::Error;
use std::fmt;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_bellman_operator::FinalUseTabularCandidateV1;
use codex_hepta_bellman_operator::WorkControlV1;
use codex_hepta_intelligence_eval::VerifiedSelfEvolutionSelectionV1;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::ArtifactPublicationReceiptV1;
use codex_hepta_learning_artifacts::LearningArtifactOwnerService;
use codex_hepta_learning_artifacts::LearningArtifactPublicationStatusV1;
use codex_hepta_learning_artifacts::LearningArtifactPublishRequestV1;
use codex_hepta_learning_artifacts::ProvenanceModeV1;
use codex_hepta_learning_artifacts::validate_artifact_publication_v3;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_types::Digest32;

use crate::learning_operator_coordinator::LearningOperatorShadowRequestV1;
use crate::learning_operator_coordinator::PersistedOperatorCandidateV1;
use crate::learning_operator_source_binding::validate_disjoint_frozen_sources;

#[path = "learning_operator_clock.rs"]
pub(crate) mod clock;
use clock::LearningOperatorUseClockV1;

/// Host-owned inputs; every timestamp uses Unix microseconds in this adapter.
/// `control` is the host's retained cancellation domain for this fit/run.
pub struct LearningOperatorPublicationInputsV1<'a> {
    pub run: &'a LearningOperatorShadowRequestV1,
    pub candidate: &'a FinalUseTabularCandidateV1,
    pub training: &'a DatasetSnapshotReceiptV3,
    pub evaluation: &'a DatasetSnapshotReceiptV3,
    pub selection: &'a VerifiedSelfEvolutionSelectionV1,
    pub control: &'a WorkControlV1,
    pub publication: LearningArtifactPublishRequestV1,
}

/// Exclusive product composition around the actual artifact owner service.
pub struct LearningOperatorArtifactOwnerV1 {
    service: LearningArtifactOwnerService,
    expected_runtime_profile_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningOperatorStorageReceiptV1 {
    pub publication: ArtifactPublicationReceiptV1,
    pub candidate: PersistedOperatorCandidateV1,
    pub training_dataset_digest: Digest32,
    pub evaluation_dataset_digest: Digest32,
}

#[derive(Debug)]
pub enum LearningOperatorPublicationErrorV1 {
    Rejected(&'static str),
    /// A write may have happened. Retain this exact request for read-only
    /// status discovery or a currently authorized exact retry.
    OutcomeUnknown {
        request: Box<LearningArtifactPublishRequestV1>,
        message: String,
    },
    /// Storage is known complete, but current admission failed afterwards.
    PersistedButNotCurrent {
        receipt: Box<LearningOperatorStorageReceiptV1>,
        message: String,
    },
}

impl fmt::Display for LearningOperatorPublicationErrorV1 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Rejected(message) => write!(f, "learning operator rejected: {message}"),
            Self::OutcomeUnknown { request, message } => write!(
                f,
                "learning operator publication {} outcome unknown: {message}",
                request.operation_id
            ),
            Self::PersistedButNotCurrent { receipt, message } => write!(
                f,
                "learning operator publication {} is stored but not current: {message}",
                receipt.publication.operation_id
            ),
        }
    }
}
impl Error for LearningOperatorPublicationErrorV1 {}

impl LearningOperatorArtifactOwnerV1 {
    pub fn new(
        service: LearningArtifactOwnerService,
        expected_runtime_profile_digest: Digest32,
    ) -> Result<Self, LearningOperatorPublicationErrorV1> {
        if expected_runtime_profile_digest.is_zero() {
            return Err(LearningOperatorPublicationErrorV1::Rejected(
                "runtime profile",
            ));
        }
        Ok(Self {
            service,
            expected_runtime_profile_digest,
        })
    }

    #[must_use]
    pub const fn service(&self) -> &LearningArtifactOwnerService {
        &self.service
    }

    /// Resolve historical storage facts even after selection/deadline expiry.
    /// An absent status performs no write and confers no permission to retry.
    pub fn reconcile_status(
        &self,
        request: &LearningArtifactPublishRequestV1,
    ) -> Result<Option<LearningArtifactPublicationStatusV1>, LearningOperatorPublicationErrorV1>
    {
        self.service.publication_status(request).map_err(|error| {
            LearningOperatorPublicationErrorV1::OutcomeUnknown {
                request: Box::new(request.clone()),
                message: error.to_string(),
            }
        })
    }

    /// Publish or resume the exact owner transaction with fresh qualification.
    /// The host must retain its exclusive runtime fence across this call.
    pub fn persist_or_reconcile(
        &mut self,
        training_ledger: &LedgerWriter,
        evaluation_ledger: &LedgerWriter,
        inputs: LearningOperatorPublicationInputsV1<'_>,
    ) -> Result<LearningOperatorStorageReceiptV1, LearningOperatorPublicationErrorV1> {
        self.persist_with_clock(
            training_ledger,
            evaluation_ledger,
            inputs,
            wall_clock_micros,
        )
    }

    fn persist_with_clock(
        &mut self,
        training_ledger: &LedgerWriter,
        evaluation_ledger: &LedgerWriter,
        mut inputs: LearningOperatorPublicationInputsV1<'_>,
        clock: impl Fn() -> Result<u64, LearningOperatorPublicationErrorV1>,
    ) -> Result<LearningOperatorStorageReceiptV1, LearningOperatorPublicationErrorV1> {
        let started = clock()?;
        let mut use_clock = LearningOperatorUseClockV1::new(started);
        self.validate(training_ledger, evaluation_ledger, &inputs, started)?;
        // Materialize the owned request before sampling the actual dispatch
        // boundary, including its potentially large immutable payload.
        let mut request = inputs.publication.clone();
        let write_now = use_clock.observe(clock()?)?;
        self.validate_dispatch_time(training_ledger, evaluation_ledger, &inputs, write_now)?;
        inputs.publication.now = write_now;
        request.now = write_now;
        let publication = self.service.publish(request).map_err(|error| {
            LearningOperatorPublicationErrorV1::OutcomeUnknown {
                request: Box::new(inputs.publication.clone()),
                message: error.to_string(),
            }
        })?;
        let view = inputs.candidate.publication_view();
        let receipt = LearningOperatorStorageReceiptV1 {
            candidate: PersistedOperatorCandidateV1 {
                artifact_digest: view.artifact_digest(),
                payload_digest: view.payload_digest(),
                selection_digest: inputs.selection.selection_digest(),
                storage_receipt_digest: publication.state_digest,
            },
            publication,
            training_dataset_digest: inputs.training.snapshot.dataset_digest,
            evaluation_dataset_digest: inputs.evaluation.snapshot.dataset_digest,
        };
        let current = (|| {
            let now = use_clock.observe(clock()?)?;
            self.validate(training_ledger, evaluation_ledger, &inputs, now)?;
            if receipt.publication.operation_id != inputs.run.run_id
                || receipt.publication.admission_digest
                    != inputs.publication.admission.admission_digest
                || receipt.publication.authority.grants_any()
                || receipt.publication.state_digest.is_zero()
            {
                return Err(LearningOperatorPublicationErrorV1::Rejected(
                    "owner acknowledgement",
                ));
            }
            let owner_current = self.service.current_registry_view(now).map_err(|_| {
                LearningOperatorPublicationErrorV1::Rejected("owner CURRENT unavailable")
            })?;
            if owner_current.receipt().head_digest != receipt.publication.registry_head_digest
                || owner_current.receipt().head_digest
                    != inputs.publication.signed_current_head.witness.head_digest
                || owner_current.witness_digest() != receipt.publication.witness_digest
            {
                return Err(LearningOperatorPublicationErrorV1::Rejected(
                    "owner CURRENT acknowledgement binding",
                ));
            }
            let current_window = owner_current.use_window();
            drop(owner_current);
            let released = use_clock.observe(clock()?)?;
            current_window.revalidate_at(released).map_err(|_| {
                LearningOperatorPublicationErrorV1::Rejected("owner CURRENT time window")
            })?;
            self.validate_dispatch_time(training_ledger, evaluation_ledger, &inputs, released)?;
            Ok(())
        })();
        current.map_err(
            |error| LearningOperatorPublicationErrorV1::PersistedButNotCurrent {
                receipt: Box::new(receipt.clone()),
                message: error.to_string(),
            },
        )?;
        Ok(receipt)
    }

    // The immutable receipts and owner projections were fully checked before
    // this guard. Recheck only time-dependent facts without replaying owners,
    // materializing payloads or verifying signatures at the dispatch boundary.
    fn validate_dispatch_time(
        &self,
        training_ledger: &LedgerWriter,
        evaluation_ledger: &LedgerWriter,
        inputs: &LearningOperatorPublicationInputsV1<'_>,
        now: u64,
    ) -> Result<(), LearningOperatorPublicationErrorV1> {
        let reject = LearningOperatorPublicationErrorV1::Rejected;
        if inputs.control.is_cancelled()
            || now < inputs.run.now_unix_micros
            || now >= inputs.run.deadline_unix_micros
        {
            return Err(reject("run clock or cancellation"));
        }
        training_ledger
            .revalidate_trust_at(now)
            .map_err(|_| reject("host learning trust currentness"))?;
        evaluation_ledger
            .revalidate_trust_at(now)
            .map_err(|_| reject("evaluation host trust currentness"))?;
        inputs
            .selection
            .revalidate(evaluation_ledger.verifier(), now)
            .map_err(|_| reject("selection currentness"))?;
        inputs
            .training
            .producer
            .validate(now)
            .map_err(|_| reject("training currentness"))?;
        inputs
            .evaluation
            .producer
            .validate(now)
            .map_err(|_| reject("evaluation currentness"))?;
        let admission = &inputs.publication.admission;
        let manifest = &admission.validated_manifest.manifest;
        let head = &inputs.publication.signed_current_head.witness;
        if now < admission.admitted_at
            || now < manifest.created_at
            || now > manifest.expires_at
            || now < head.issued_at
            || now > head.expires_at
        {
            return Err(reject("artifact admission currentness"));
        }
        Ok(())
    }

    fn validate(
        &self,
        training_ledger: &LedgerWriter,
        evaluation_ledger: &LedgerWriter,
        inputs: &LearningOperatorPublicationInputsV1<'_>,
        now: u64,
    ) -> Result<(), LearningOperatorPublicationErrorV1> {
        let reject = LearningOperatorPublicationErrorV1::Rejected;
        let run = inputs.run;
        let view = inputs.candidate.publication_view();
        let selected = inputs.selection.receipt();
        let training = &inputs.training.snapshot;
        let evaluation = &inputs.evaluation.snapshot;
        let manifest = &inputs.publication.admission.validated_manifest.manifest;
        validate_disjoint_frozen_sources(
            &training.source_record_digests,
            &evaluation.source_record_digests,
        )
        .map_err(reject)?;
        self.validate_dispatch_time(training_ledger, evaluation_ledger, inputs, now)?;
        training_ledger
            .revalidate_dataset_snapshot(inputs.training, now)
            .map_err(|_| reject("training currentness"))?;
        evaluation_ledger
            .revalidate_dataset_snapshot(inputs.evaluation, now)
            .map_err(|_| reject("evaluation currentness"))?;
        validate_artifact_publication_v3(
            &inputs.publication.admission,
            self.service.withdrawal_registry(),
            now,
        )
        .map_err(|_| reject("artifact admission currentness"))?;
        if view.producer_id() != &run.producer_id
            || view.objective_digest() != run.objective_digest
            || view.generation()
                != run
                    .predecessor_generation
                    .next()
                    .map_err(|_| reject("generation"))?
            || view.authority_epoch() != run.expected_authority_epoch
            || view.stop_epoch() != run.expected_stop_epoch
            || view.runtime_profile_digest() != self.expected_runtime_profile_digest
            || view.trust_digest() != training_ledger.verifier().trust_digest()
            || training_ledger.trust_distribution_digest()
                != evaluation_ledger.trust_distribution_digest()
            || run.owner_id != inputs.training.producer.principal_id
            || run.training_source_digest != training.dataset_digest
            || run.evaluation_source_digest != evaluation.dataset_digest
            || inputs.selection.authority_epoch() != run.expected_authority_epoch
            || training.objective_digest != run.objective_digest
            || evaluation.objective_digest != run.objective_digest
            || training.dataset_digest != view.dataset_digest()
            || training.ledger_head_digest != view.ledger_head_digest()
            || training.dataset_digest == evaluation.dataset_digest
            || training.snapshot_id == evaluation.snapshot_id
            || selected.dataset_digest != evaluation.dataset_digest
            || selected.ledger_head_digest != evaluation.ledger_head_digest
            || selected.objective_digest != run.objective_digest
            || selected.predecessor_generation != run.predecessor_generation
            || selected.predecessor_artifact_digest != run.predecessor_artifact_digest
            || selected.candidate_id != *view.artifact_id()
            || selected.candidate_generation != view.generation()
            || selected.candidate_artifact_digest != view.payload_digest()
            || inputs.selection.evaluation_frozen_at_unix_micros()
                <= view.published_at_unix_micros()
            || selected.authority.grants_any()
        {
            return Err(reject("fit, datasets or sealed selection identity"));
        }
        if inputs.publication.operation_id != run.run_id
            || manifest.kind != ArtifactKind::Model
            || manifest.artifact_id != *view.artifact_id()
            || manifest.producer_id != *view.producer_id()
            || manifest.generation != view.generation()
            || manifest.created_at != view.published_at_unix_micros()
            || manifest.objective_class_digest != view.objective_digest()
            || manifest.provenance_mode != ProvenanceModeV1::DatasetDerived
            || manifest.source_dataset_digests != [training.dataset_digest]
            || manifest.predecessor_ids != [selected.predecessor_id.clone()]
            || manifest.rollback_predecessor.as_ref() != Some(&selected.predecessor_id)
            || !manifest
                .lineage_digests
                .contains(&inputs.candidate.fit_receipt_digest())
            || manifest.bytes_digest != view.payload_digest()
            || u64::try_from(view.payload().len()).ok() != Some(manifest.encoded_size_bytes)
            || inputs.publication.payload != view.payload()
        {
            return Err(reject("admitted publication target"));
        }
        Ok(())
    }
}

pub(crate) fn wall_clock_micros() -> Result<u64, LearningOperatorPublicationErrorV1> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .ok()
        .and_then(|value| u64::try_from(value.as_micros()).ok())
        .ok_or(LearningOperatorPublicationErrorV1::Rejected("host clock"))
}

#[cfg(test)]
#[path = "learning_operator_artifact_owner_tests.rs"]
pub(crate) mod tests;
