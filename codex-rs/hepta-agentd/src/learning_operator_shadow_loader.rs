//! V3 evaluated read-only loader with distinct training and evaluation data.
//!
//! This composes existing verified selection/currentness boundaries; it never
//! issues either proof and is not evidence of a distinct process or activation.

use std::fs::File;

use codex_hepta_agent_components::bellman_operator::LoadedTabularOperatorV2;
use codex_hepta_agent_components::bellman_operator::TabularOperatorPredictionV1;
use codex_hepta_agent_components::bellman_operator::TabularPayloadPinV2;
use codex_hepta_agent_components::bellman_operator::WorkControlV1;
use codex_hepta_agent_components::intelligence_eval::VerifiedSelfEvolutionSelectionV2;
use codex_hepta_agent_components::learning_artifacts::ArtifactKind;
use codex_hepta_agent_components::learning_artifacts::ArtifactSelectionVerifierV1;
use codex_hepta_agent_components::learning_artifacts::LearningArtifactOwnerService;
use codex_hepta_agent_components::learning_artifacts::ProvenanceModeV1;
use codex_hepta_agent_components::learning_artifacts::RevalidatingCandidate;
use codex_hepta_agent_components::learning_artifacts::VerifiedArtifactSelectionV1;
use codex_hepta_agent_components::learning_artifacts::WithdrawalBoundArtifactAdmissionV3;
use codex_hepta_agent_components::learning_artifacts::load_selected_candidate;
use codex_hepta_agent_components::learning_artifacts::validate_artifact_publication_v3;
use codex_hepta_agent_components::learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_agent_components::learning_ledger::LedgerWriter;
use codex_hepta_agent_components::types::Digest32;
use codex_hepta_agent_components::types::StableId;

use crate::learning_operator_artifact_owner::LearningOperatorPublicationErrorV1;
use crate::learning_operator_artifact_owner::LearningOperatorStorageReceiptV2;
use crate::learning_operator_artifact_owner::clock::LearningOperatorUseClockV1;
use crate::learning_operator_artifact_owner::clock::authority_millis;
use crate::learning_operator_artifact_owner::wall_clock_micros;
use crate::learning_operator_source_binding::validate_disjoint_frozen_sources;

/// Complete externally admitted binding for one immutable shadow consumer.
/// Model runtime/trust/registry fields are independently retained host inputs.
pub struct EvaluatedTabularLoadBindingV4 {
    pub admission: WithdrawalBoundArtifactAdmissionV3,
    pub storage: LearningOperatorStorageReceiptV2,
    pub training: DatasetSnapshotReceiptV3,
    pub evaluation: DatasetSnapshotReceiptV3,
    pub selection: VerifiedSelfEvolutionSelectionV2,
    pub model_pin: TabularPayloadPinV2,
    pub expected_runtime_profile_digest: Digest32,
    pub deadline_unix_micros: u64,
    pub control: WorkControlV1,
}

/// Opaque read-only shadow model. Failed refresh requires complete re-admission.
pub struct EvaluatedTabularShadowConsumerV4 {
    candidate: RevalidatingCandidate,
    storage_selection: VerifiedArtifactSelectionV1,
    model: LoadedTabularOperatorV2,
    binding: EvaluatedTabularLoadBindingV4,
    unavailable: bool,
    clock: LearningOperatorUseClockV1,
}

impl EvaluatedTabularShadowConsumerV4 {
    #[allow(clippy::too_many_arguments)]
    pub fn load(
        owner: &LearningArtifactOwnerService,
        training_ledger: &LedgerWriter,
        evaluation_ledger: &LedgerWriter,
        selection_verifier: &ArtifactSelectionVerifierV1,
        snapshot: File,
        payload: File,
        selected: VerifiedArtifactSelectionV1,
        binding: EvaluatedTabularLoadBindingV4,
    ) -> Result<Self, LearningOperatorPublicationErrorV1> {
        Self::load_with_clock(
            owner,
            training_ledger,
            evaluation_ledger,
            selection_verifier,
            snapshot,
            payload,
            selected,
            binding,
            wall_clock_micros,
        )
    }

    #[allow(clippy::too_many_arguments)]
    fn load_with_clock(
        owner: &LearningArtifactOwnerService,
        training_ledger: &LedgerWriter,
        evaluation_ledger: &LedgerWriter,
        selection_verifier: &ArtifactSelectionVerifierV1,
        snapshot: File,
        payload: File,
        selected: VerifiedArtifactSelectionV1,
        binding: EvaluatedTabularLoadBindingV4,
        clock: impl Fn() -> Result<u64, LearningOperatorPublicationErrorV1>,
    ) -> Result<Self, LearningOperatorPublicationErrorV1> {
        let now = clock()?;
        let mut use_clock = LearningOperatorUseClockV1::new(now);
        validate_binding(owner, training_ledger, evaluation_ledger, &binding, now)?;
        if selected.artifact_id() != &binding.model_pin.artifact_id
            || selected.authority().grants_any()
        {
            return Err(LearningOperatorPublicationErrorV1::Rejected(
                "artifact selection",
            ));
        }
        let storage_selection = selected.clone();
        let mut candidate = load_selected_candidate(snapshot, payload, selected)
            .map_err(|_| LearningOperatorPublicationErrorV1::Rejected("selected payload"))?;
        let legacy = &candidate.spec().manifest;
        let manifest = &binding.admission.validated_manifest.manifest;
        if legacy.content_digest != manifest.bytes_digest
            || legacy.support_digest != binding.admission.validated_manifest.manifest_digest
            || legacy.objective_digest != manifest.objective_class_digest
            || legacy.producer_id != manifest.producer_id
            || legacy.kind != manifest.kind
            || legacy.generation != manifest.generation
            || legacy.predecessor_id != manifest.rollback_predecessor
            || legacy.compatibility_digest != manifest.compatibility_digest
            || legacy.encoded_size_bytes != manifest.encoded_size_bytes
            || candidate.spec().registry_receipt.head_digest
                != binding.model_pin.registry_head_digest
        {
            return Err(LearningOperatorPublicationErrorV1::Rejected(
                "V3 registry projection",
            ));
        }
        let current = owner
            .current_registry_view(authority_millis(now)?)
            .map_err(|_| {
                LearningOperatorPublicationErrorV1::Rejected("artifact CURRENT unavailable")
            })?;
        selection_verifier
            .revalidate_for_use(&storage_selection, &current, authority_millis(now)?)
            .map_err(|_| {
                LearningOperatorPublicationErrorV1::Rejected("storage selection currentness")
            })?;
        let model = candidate
            .with_current(current, |bytes| {
                LoadedTabularOperatorV2::from_pinned_payload_v2(bytes, &binding.model_pin)
            })
            .map_err(|_| LearningOperatorPublicationErrorV1::Rejected("artifact currentness"))?
            .map_err(|_| LearningOperatorPublicationErrorV1::Rejected("model payload binding"))?;
        let finished = use_clock.observe(clock()?)?;
        validate_binding(
            owner,
            training_ledger,
            evaluation_ledger,
            &binding,
            finished,
        )?;
        let current = owner
            .current_registry_view(authority_millis(finished)?)
            .map_err(|_| {
                LearningOperatorPublicationErrorV1::Rejected("artifact CURRENT unavailable")
            })?;
        selection_verifier
            .revalidate_for_use(&storage_selection, &current, authority_millis(finished)?)
            .map_err(|_| {
                LearningOperatorPublicationErrorV1::Rejected("storage selection currentness")
            })?;
        let current_window = current.use_window().map_err(|_| {
            LearningOperatorPublicationErrorV1::Rejected("CURRENT time facts unavailable")
        })?;
        candidate
            .with_current(current, |_| ())
            .map_err(|_| LearningOperatorPublicationErrorV1::Rejected("artifact currentness"))?;
        let released = use_clock.observe(clock()?)?;
        current_window
            .revalidate_at(authority_millis(released)?)
            .map_err(|_| {
                LearningOperatorPublicationErrorV1::Rejected("artifact CURRENT time window")
            })?;
        validate_release_time(
            training_ledger,
            evaluation_ledger,
            selection_verifier,
            &storage_selection,
            &binding,
            released,
        )?;
        Ok(Self {
            candidate,
            storage_selection,
            model,
            binding,
            unavailable: false,
            clock: use_clock,
        })
    }

    /// Use the host's exact CURRENT source and active ledger before and after a
    /// shadow prediction. The caller retains its effect fence; no dispatch is
    /// authorized by this prediction.
    pub fn predict_shadow(
        &mut self,
        owner: &LearningArtifactOwnerService,
        training_ledger: &LedgerWriter,
        evaluation_ledger: &LedgerWriter,
        selection_verifier: &ArtifactSelectionVerifierV1,
        sensor: &StableId,
        action: &StableId,
    ) -> Result<TabularOperatorPredictionV1, LearningOperatorPublicationErrorV1> {
        self.predict_with_clock(
            owner,
            training_ledger,
            evaluation_ledger,
            selection_verifier,
            sensor,
            action,
            wall_clock_micros,
        )
    }

    // Keep the independent owner boundaries explicit; the extra argument is
    // the private clock used by production and deterministic boundary tests.
    #[allow(clippy::too_many_arguments)]
    fn predict_with_clock(
        &mut self,
        owner: &LearningArtifactOwnerService,
        training_ledger: &LedgerWriter,
        evaluation_ledger: &LedgerWriter,
        selection_verifier: &ArtifactSelectionVerifierV1,
        sensor: &StableId,
        action: &StableId,
        clock: impl Fn() -> Result<u64, LearningOperatorPublicationErrorV1>,
    ) -> Result<TabularOperatorPredictionV1, LearningOperatorPublicationErrorV1> {
        if self.unavailable {
            return Err(LearningOperatorPublicationErrorV1::Rejected(
                "consumer unavailable",
            ));
        }
        self.unavailable = true;
        let now = self.clock.observe(clock()?)?;
        validate_binding(
            owner,
            training_ledger,
            evaluation_ledger,
            &self.binding,
            now,
        )?;
        let current = owner
            .current_registry_view(authority_millis(now)?)
            .map_err(|_| {
                LearningOperatorPublicationErrorV1::Rejected("artifact CURRENT unavailable")
            })?;
        selection_verifier
            .revalidate_for_use(&self.storage_selection, &current, authority_millis(now)?)
            .map_err(|_| {
                LearningOperatorPublicationErrorV1::Rejected("storage selection currentness")
            })?;
        let prediction = self
            .candidate
            .with_current(current, |_| self.model.predict(sensor, action))
            .map_err(|_| LearningOperatorPublicationErrorV1::Rejected("artifact currentness"))?
            .map_err(|_| LearningOperatorPublicationErrorV1::Rejected("shadow prediction"))?;
        let finished = self.clock.observe(clock()?)?;
        validate_binding(
            owner,
            training_ledger,
            evaluation_ledger,
            &self.binding,
            finished,
        )?;
        let current = owner
            .current_registry_view(authority_millis(finished)?)
            .map_err(|_| {
                LearningOperatorPublicationErrorV1::Rejected("artifact CURRENT unavailable")
            })?;
        selection_verifier
            .revalidate_for_use(
                &self.storage_selection,
                &current,
                authority_millis(finished)?,
            )
            .map_err(|_| {
                LearningOperatorPublicationErrorV1::Rejected("storage selection currentness")
            })?;
        let current_window = current.use_window().map_err(|_| {
            LearningOperatorPublicationErrorV1::Rejected("CURRENT time facts unavailable")
        })?;
        self.candidate
            .with_current(current, |_| ())
            .map_err(|_| LearningOperatorPublicationErrorV1::Rejected("artifact currentness"))?;
        let released = self.clock.observe(clock()?)?;
        current_window
            .revalidate_at(authority_millis(released)?)
            .map_err(|_| {
                LearningOperatorPublicationErrorV1::Rejected("artifact CURRENT time window")
            })?;
        validate_release_time(
            training_ledger,
            evaluation_ledger,
            selection_verifier,
            &self.storage_selection,
            &self.binding,
            released,
        )?;
        self.unavailable = false;
        Ok(prediction)
    }
}

fn validate_binding(
    owner: &LearningArtifactOwnerService,
    training_ledger: &LedgerWriter,
    evaluation_ledger: &LedgerWriter,
    binding: &EvaluatedTabularLoadBindingV4,
    now: u64,
) -> Result<(), LearningOperatorPublicationErrorV1> {
    let reject = LearningOperatorPublicationErrorV1::Rejected;
    let training = &binding.training.snapshot;
    let evaluation = &binding.evaluation.snapshot;
    validate_disjoint_frozen_sources(
        &training.source_record_digests,
        &evaluation.source_record_digests,
    )
    .map_err(reject)?;
    validate_binding_time(training_ledger, evaluation_ledger, binding, now)?;
    training_ledger
        .revalidate_dataset_snapshot(&binding.training, authority_millis(now)?)
        .map_err(|_| reject("training currentness"))?;
    evaluation_ledger
        .revalidate_dataset_snapshot(&binding.evaluation, authority_millis(now)?)
        .map_err(|_| reject("evaluation currentness"))?;
    validate_artifact_publication_v3(
        &binding.admission,
        owner.withdrawal_registry(),
        authority_millis(now)?,
    )
    .map_err(|_| reject("artifact admission currentness"))?;
    let manifest = &binding.admission.validated_manifest.manifest;
    let pin = &binding.model_pin;
    let selection = binding.selection.receipt();
    if manifest.artifact_id != pin.artifact_id
        || !matches!(manifest.kind, ArtifactKind::Model | ArtifactKind::Policy)
        || manifest.producer_id != pin.producer_id
        || manifest.generation != pin.generation
        || manifest.objective_class_digest != pin.objective_digest
        || manifest.compatibility_digest != pin.runtime_profile_digest
        || manifest.bytes_digest != pin.payload_digest
        || manifest.provenance_mode != ProvenanceModeV1::DatasetDerived
        || manifest.source_dataset_digests.len() != 2
        || !manifest
            .source_dataset_digests
            .contains(&training.dataset_digest)
        || !manifest
            .source_dataset_digests
            .contains(&evaluation.dataset_digest)
        || manifest.predecessor_ids != [selection.request.predecessor_id.clone()]
        || manifest.rollback_predecessor.as_ref() != Some(&selection.request.predecessor_id)
        || pin.dataset_digest != training.dataset_digest
        || training.dataset_digest == evaluation.dataset_digest
        || training.snapshot_id == evaluation.snapshot_id
        || training.objective_digest != pin.objective_digest
        || evaluation.objective_digest != pin.objective_digest
        || selection.objective_digest != pin.objective_digest
        || selection.evaluation_trust_digest != evaluation_ledger.verifier().trust_digest()
        || binding.storage.training_dataset_digest() != training.dataset_digest
        || binding.storage.evaluation_dataset_digest() != evaluation.dataset_digest
        || binding.storage.learning_distribution_digest()
            != training_ledger.trust_distribution_digest()
        || binding.storage.publication().admission_digest != binding.admission.admission_digest
        || binding.storage.candidate().payload_digest != pin.payload_digest
        || binding.storage.candidate().artifact_digest != pin.artifact_digest
        || binding.storage.candidate().selection_digest != binding.selection.selection_digest()
        || manifest.created_at != authority_millis(binding.storage.fit_published_at_unix_micros())?
        || !manifest
            .lineage_digests
            .contains(&binding.storage.fit_receipt_digest())
        || selection.request.candidate_id != pin.artifact_id
        || selection.request.candidate_generation != pin.generation
        || selection.request.candidate_artifact_digest != pin.payload_digest
        || selection.registered_at_unix_micros <= binding.storage.fit_published_at_unix_micros()
        || selection.dataset_digest != evaluation.dataset_digest
        || selection.ledger_head_digest != evaluation.ledger_head_digest
        || selection.authority.grants_any()
        || pin.authority_epoch != binding.selection.authority_epoch()
        || pin.trust_digest != training_ledger.verifier().trust_digest()
        || training_ledger.trust_distribution_digest()
            != evaluation_ledger.trust_distribution_digest()
        || binding.expected_runtime_profile_digest.is_zero()
        || pin.runtime_profile_digest != binding.expected_runtime_profile_digest
    {
        return Err(reject("training, evaluation or model identity"));
    }
    Ok(())
}

// Current owner projections and immutable binding have already been verified.
// No owner I/O, payload materialization or signature checks follow this guard.
fn validate_release_time(
    training_ledger: &LedgerWriter,
    evaluation_ledger: &LedgerWriter,
    selection_verifier: &ArtifactSelectionVerifierV1,
    storage_selection: &VerifiedArtifactSelectionV1,
    binding: &EvaluatedTabularLoadBindingV4,
    now: u64,
) -> Result<(), LearningOperatorPublicationErrorV1> {
    validate_binding_time(training_ledger, evaluation_ledger, binding, now)?;
    selection_verifier
        .revalidate_window_for_use(storage_selection, authority_millis(now)?)
        .map_err(|_| LearningOperatorPublicationErrorV1::Rejected("storage selection currentness"))
}

fn validate_binding_time(
    training_ledger: &LedgerWriter,
    evaluation_ledger: &LedgerWriter,
    binding: &EvaluatedTabularLoadBindingV4,
    now: u64,
) -> Result<(), LearningOperatorPublicationErrorV1> {
    let reject = LearningOperatorPublicationErrorV1::Rejected;
    if binding.control.is_cancelled() || now >= binding.deadline_unix_micros {
        return Err(reject("shadow deadline or cancellation"));
    }
    let now = authority_millis(now)?;
    training_ledger
        .revalidate_trust_at(now)
        .map_err(|_| reject("host learning trust currentness"))?;
    evaluation_ledger
        .revalidate_trust_at(now)
        .map_err(|_| reject("evaluation host trust currentness"))?;
    binding
        .selection
        .revalidate_current(evaluation_ledger.activated_trust())
        .map_err(|_| reject("selection currentness"))?;
    binding
        .training
        .producer
        .validate(now)
        .map_err(|_| reject("training currentness"))?;
    binding
        .evaluation
        .producer
        .validate(now)
        .map_err(|_| reject("evaluation currentness"))?;
    let manifest = &binding.admission.validated_manifest.manifest;
    if now < binding.admission.admitted_at || now < manifest.created_at || now > manifest.expires_at
    {
        return Err(reject("artifact admission currentness"));
    }
    Ok(())
}
