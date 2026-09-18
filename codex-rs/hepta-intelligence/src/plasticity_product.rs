//! Authenticated product-workspace composition for governed plasticity proposals.
//!
//! This adapter closes the gap between the authority-free proposal crate and the
//! existing signed learning-evidence/evaluation boundary. It authenticates a
//! deterministic generator-complete candidate set, a typed mutation grammar, a
//! current lineage/evidence witness, and an independent signed evaluation for
//! every update candidate before writing one proposal record. It still cannot
//! select, apply, activate, train, promote or release any candidate.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::io;

use codex_hepta_intelligence_eval::{
    IndependentEvaluationBundleV1, IndependentEvaluationDispositionV1, MetricRoleContractV2,
    SignedEvaluationError, SignedEvaluationEvidenceV1, decide_with_signed_evidence_v2,
};
use codex_hepta_learning_ledger::{
    LearningEvidenceRoleV1, LearningEvidenceVerifierV1, SignedEvidenceError,
    SignedLearningEvidenceV1, verify_signed_role_separation,
};
use codex_hepta_plasticity::{
    DurableProposalAppendReceiptV1, DurableProposalRegistry, DurableProposalRegistryError,
    DurableRegistryAnchorV1, GeneratedParameterCandidateSetV3, MutationGrammarErrorV1,
    MutationGrammarManifestV1, ParameterCandidateKindV2, ParameterGeneratorErrorV3,
    ParameterGeneratorProfileV3, ParameterProposalRequestV2, ParameterProposalV2,
    ProposalWindowV2, parameter_generator_signing_payload_v3, propose_v2,
    verify_generated_parameter_candidates_v3, verify_generator_profile_against_mutation_grammar_v1,
    verify_mutation_grammar_manifest_v1,
};
use codex_hepta_types::{Digest32, Generation, StableId};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityAdmissionEvidenceV1 {
    pub baseline_id: StableId,
    pub objective_digest: Digest32,
    pub selected_artifact_digest: Digest32,
    pub artifact_registry_binding: Digest32,
    pub artifact_registry_head_digest: Digest32,
    pub qualification_evidence_head_digest: Digest32,
    pub mutation_grammar_digest: Digest32,
    pub window: ProposalWindowV2,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub dataset_digest: Digest32,
    pub update_rule_digest: Digest32,
    pub modulator_digest: Digest32,
    pub modulator_broadcast_digest: Digest32,
    pub eligibility_digest: Digest32,
    pub generator_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CandidateEvaluationAdmissionV1 {
    pub bundle: IndependentEvaluationBundleV1,
    pub metric_roles: Vec<MetricRoleContractV2>,
    pub evidence: SignedEvaluationEvidenceV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ParameterPlasticityProductRequestV1 {
    pub proposal_id: StableId,
    pub mutation_grammar: MutationGrammarManifestV1,
    pub generator_profile: ParameterGeneratorProfileV3,
    pub generated: GeneratedParameterCandidateSetV3,
    pub generator_attestation: SignedLearningEvidenceV1,
    pub admission: PlasticityAdmissionEvidenceV1,
    pub admission_attestation: SignedLearningEvidenceV1,
    pub evaluations: Vec<CandidateEvaluationAdmissionV1>,
    /// Canonical digest of the selected host's verified owner-evidence receipts
    /// and owner policy. A selected host overwrites this with its own verification.
    pub host_evidence_verification_digest: Digest32,
    pub expected_registry_predecessor: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ParameterPlasticityProductReceiptV1 {
    pub proposal: ParameterProposalV2,
    pub registry: DurableProposalAppendReceiptV1,
    pub generator_authentication_digest: Digest32,
    pub admission_authentication_digest: Digest32,
    pub evaluation_digest: Digest32,
    pub committed_registry_anchor: DurableRegistryAnchorV1,
    pub composition_digest: Digest32,
}

#[derive(Debug)]
pub enum ParameterPlasticityProductErrorV1 {
    Binding(&'static str),
    Grammar(MutationGrammarErrorV1),
    Generator(ParameterGeneratorErrorV3),
    GeneratorEvidence(SignedEvidenceError),
    AdmissionEvidence(SignedEvidenceError),
    Evaluation(SignedEvaluationError),
    Ineligible(IndependentEvaluationDispositionV1),
    MissingEvaluation(String),
    DuplicateEvaluation(String),
    UnexpectedEvaluation(String),
    EvaluatorMismatch,
    NoUpdateCandidate,
    AnchorPersistenceFailed,
    Proposal(codex_hepta_plasticity::Error),
    Registry(DurableProposalRegistryError),
}

impl fmt::Display for ParameterPlasticityProductErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for ParameterPlasticityProductErrorV1 {}

impl From<MutationGrammarErrorV1> for ParameterPlasticityProductErrorV1 {
    fn from(value: MutationGrammarErrorV1) -> Self {
        Self::Grammar(value)
    }
}
impl From<ParameterGeneratorErrorV3> for ParameterPlasticityProductErrorV1 {
    fn from(value: ParameterGeneratorErrorV3) -> Self {
        Self::Generator(value)
    }
}
impl From<codex_hepta_plasticity::Error> for ParameterPlasticityProductErrorV1 {
    fn from(value: codex_hepta_plasticity::Error) -> Self {
        Self::Proposal(value)
    }
}
impl From<DurableProposalRegistryError> for ParameterPlasticityProductErrorV1 {
    fn from(value: DurableProposalRegistryError) -> Self {
        Self::Registry(value)
    }
}

#[derive(Debug)]
pub enum AnchoredPlasticityWriterErrorV1 {
    BootstrapFileNotEmpty,
    Io(io::ErrorKind),
    Registry(DurableProposalRegistryError),
}
impl fmt::Display for AnchoredPlasticityWriterErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for AnchoredPlasticityWriterErrorV1 {}
impl From<DurableProposalRegistryError> for AnchoredPlasticityWriterErrorV1 {
    fn from(value: DurableProposalRegistryError) -> Self {
        Self::Registry(value)
    }
}

/// Host-owned sink for an independently retained rollback anchor.
///
/// Returning `true` means the anchor is durably committed in a rollback domain
/// independent from the proposal registry file. A `false` result poisons the
/// product writer and prevents any further operation through that handle.
pub trait PlasticityAnchorCommitterV1 {
    fn persist_anchor(
        &mut self,
        registry_scope_digest: Digest32,
        writer_fence: u64,
        anchor: DurableRegistryAnchorV1,
    ) -> bool;
}

/// Explicit lifecycle for a product writer. `AppendPendingAnchor` is entered
/// only after the proposal frame is durable and before its external rollback
/// anchor is acknowledged. It is intentionally observable for diagnostics but
/// no public read/append operation is allowed in that state.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PlasticityWriterStateV1 {
    Healthy,
    AppendPendingAnchor,
    Poisoned,
}

/// Product writer that cannot reopen acknowledged history without a host-retained
/// external anchor. Raw `DurableProposalRegistry::open` remains available to the
/// proposal crate for isolated/bootstrap use, but cannot enter this product path.
pub struct AnchoredPlasticityWriterV1 {
    registry: DurableProposalRegistry,
    registry_scope_digest: Digest32,
    writer_fence: u64,
    state: PlasticityWriterStateV1,
}

impl AnchoredPlasticityWriterV1 {
    /// Enroll a brand-new empty registry. After the first append the caller cannot
    /// observe success unless the newly acknowledged anchor is also committed via
    /// [`PlasticityAnchorCommitterV1`].
    pub fn bootstrap_new(
        file: File,
        registry_scope_digest: Digest32,
        writer_fence: u64,
        maximum_records: usize,
    ) -> Result<Self, AnchoredPlasticityWriterErrorV1> {
        let registry = match DurableProposalRegistry::open_bootstrap_empty(
            file,
            registry_scope_digest,
            writer_fence,
            maximum_records,
        ) {
            Ok(registry) => registry,
            Err(DurableProposalRegistryError::BootstrapRequiresEmptyFile) => {
                return Err(AnchoredPlasticityWriterErrorV1::BootstrapFileNotEmpty);
            }
            Err(error) => return Err(AnchoredPlasticityWriterErrorV1::Registry(error)),
        };
        Ok(Self {
            registry,
            registry_scope_digest,
            writer_fence,
            state: PlasticityWriterStateV1::Healthy,
        })
    }

    /// Reopen any non-bootstrap registry only with independently retained history.
    pub fn reopen_anchored(
        file: File,
        registry_scope_digest: Digest32,
        writer_fence: u64,
        maximum_records: usize,
        anchor: DurableRegistryAnchorV1,
    ) -> Result<Self, AnchoredPlasticityWriterErrorV1> {
        Ok(Self {
            registry: DurableProposalRegistry::open_anchored(
                file,
                registry_scope_digest,
                writer_fence,
                maximum_records,
                anchor,
            )?,
            registry_scope_digest,
            writer_fence,
            state: PlasticityWriterStateV1::Healthy,
        })
    }

    #[must_use]
    pub const fn state(&self) -> PlasticityWriterStateV1 {
        self.state
    }

    pub fn current_anchor(
        &self,
    ) -> Result<Option<DurableRegistryAnchorV1>, DurableProposalRegistryError> {
        self.require_healthy()?;
        self.registry.current_anchor()
    }

    pub fn record_count(&self) -> Result<usize, DurableProposalRegistryError> {
        self.require_healthy()?;
        self.registry.record_count()
    }

    fn require_healthy(&self) -> Result<(), DurableProposalRegistryError> {
        match self.state {
            PlasticityWriterStateV1::Healthy => Ok(()),
            PlasticityWriterStateV1::AppendPendingAnchor | PlasticityWriterStateV1::Poisoned => {
                Err(DurableProposalRegistryError::Poisoned)
            }
        }
    }

    fn mark_pending_anchor(&mut self) {
        self.state = PlasticityWriterStateV1::AppendPendingAnchor;
    }

    fn mark_anchor_committed(&mut self) {
        debug_assert_eq!(self.state, PlasticityWriterStateV1::AppendPendingAnchor);
        self.state = PlasticityWriterStateV1::Healthy;
    }

    fn poison(&mut self) {
        self.state = PlasticityWriterStateV1::Poisoned;
    }
}

/// Canonical bytes attested by the trusted Observer evidence role. The verifier's
/// own validity/revocation window provides freshness; the payload binds the exact
/// artifact/evidence frontiers, typed mutation grammar and proposal lineage digests.
pub fn plasticity_admission_signing_payload_v1(
    evidence: &PlasticityAdmissionEvidenceV1,
) -> Vec<u8> {
    let mut bytes = b"hepta.intelligence.plasticity-admission.v1\0".to_vec();
    push_id(&mut bytes, &evidence.baseline_id);
    for digest in [
        evidence.objective_digest,
        evidence.selected_artifact_digest,
        evidence.artifact_registry_binding,
        evidence.artifact_registry_head_digest,
        evidence.qualification_evidence_head_digest,
        evidence.mutation_grammar_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_id(&mut bytes, &evidence.window.window_id);
    bytes.extend_from_slice(evidence.window.window_digest.as_array());
    bytes.extend_from_slice(&evidence.baseline_generation.get().to_be_bytes());
    bytes.extend_from_slice(&evidence.candidate_generation.get().to_be_bytes());
    for digest in [
        evidence.dataset_digest,
        evidence.update_rule_digest,
        evidence.modulator_digest,
        evidence.modulator_broadcast_digest,
        evidence.eligibility_digest,
        evidence.generator_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes
}

pub fn propose_authenticated_parameter_plasticity_v1(
    request: ParameterPlasticityProductRequestV1,
    verifier: &LearningEvidenceVerifierV1,
    writer: &mut AnchoredPlasticityWriterV1,
    anchor_committer: &mut impl PlasticityAnchorCommitterV1,
    now: u64,
) -> Result<ParameterPlasticityProductReceiptV1, ParameterPlasticityProductErrorV1> {
    use ParameterPlasticityProductErrorV1 as E;

    writer.require_healthy()?;
    verify_mutation_grammar_manifest_v1(&request.mutation_grammar)?;
    verify_generator_profile_against_mutation_grammar_v1(
        &request.generator_profile,
        &request.mutation_grammar,
    )?;
    verify_generated_parameter_candidates_v3(
        request.generator_profile.clone(),
        &request.generated,
    )?;
    validate_admission_binding(&request)?;

    let generator_payload = parameter_generator_signing_payload_v3(&request.generated);
    let generator = verifier
        .verify(
            LearningEvidenceRoleV1::Generator,
            &request.generator_attestation,
            &generator_payload,
            now,
        )
        .map_err(E::GeneratorEvidence)?;
    let admission_payload = plasticity_admission_signing_payload_v1(&request.admission);
    let observer = verifier
        .verify(
            LearningEvidenceRoleV1::Observer,
            &request.admission_attestation,
            &admission_payload,
            now,
        )
        .map_err(E::AdmissionEvidence)?;
    verify_signed_role_separation(&generator, &observer, now).map_err(E::AdmissionEvidence)?;

    if request.generator_attestation.objective_digest != request.admission.objective_digest
        || request.admission_attestation.objective_digest != request.admission.objective_digest
    {
        return Err(E::Binding("objective trust context"));
    }

    let update_candidates = request
        .generated
        .candidates
        .iter()
        .filter(|candidate| candidate.kind == ParameterCandidateKindV2::Update)
        .collect::<Vec<_>>();
    if update_candidates.is_empty() {
        return Err(E::NoUpdateCandidate);
    }

    let mut evaluations = BTreeMap::new();
    for evaluation in request.evaluations {
        let key = evaluation.bundle.candidate_id.clone();
        if evaluations.insert(key.clone(), evaluation).is_some() {
            return Err(E::DuplicateEvaluation(key.to_string()));
        }
    }

    let mut evaluator_id: Option<StableId> = None;
    let mut evaluation_binding = b"hepta.intelligence.plasticity-evaluations.v1\0".to_vec();
    evaluation_binding.extend_from_slice(request.host_evidence_verification_digest.as_array());
    for candidate in update_candidates {
        let candidate_id = candidate.candidate_id.clone();
        let CandidateEvaluationAdmissionV1 {
            bundle,
            metric_roles,
            evidence,
        } = evaluations
            .remove(&candidate_id)
            .ok_or_else(|| E::MissingEvaluation(candidate_id.to_string()))?;
        if bundle.candidate_id != candidate_id
            || bundle.baseline_id != request.admission.baseline_id
            || bundle.objective_digest != request.admission.objective_digest
            || bundle.dataset_digest != request.admission.dataset_digest
            || &bundle.generator != generator.principal()
        {
            return Err(E::Binding("candidate evaluation lineage"));
        }
        let this_evaluator = bundle.evaluator.principal_id.clone();
        if evaluator_id
            .as_ref()
            .is_some_and(|existing| existing != &this_evaluator)
        {
            return Err(E::EvaluatorMismatch);
        }
        evaluator_id.get_or_insert(this_evaluator);

        let decision = decide_with_signed_evidence_v2(
            bundle,
            metric_roles,
            &evidence,
            verifier,
            now,
        )
        .map_err(E::Evaluation)?;
        if decision.decision.disposition
            != IndependentEvaluationDispositionV1::EligibleForIndependentSelection
        {
            return Err(E::Ineligible(decision.decision.disposition));
        }
        push_id(&mut evaluation_binding, &candidate_id);
        evaluation_binding.extend_from_slice(decision.decision.evidence_digest.as_array());
        evaluation_binding.extend_from_slice(decision.authentication_digest.as_array());
        evaluation_binding.extend_from_slice(decision.trust_digest.as_array());
    }
    if let Some(unexpected) = evaluations.keys().next() {
        return Err(E::UnexpectedEvaluation(unexpected.to_string()));
    }
    let evaluator_id = evaluator_id.ok_or(E::NoUpdateCandidate)?;
    let evaluation_digest = Digest32::of_bytes(&evaluation_binding);

    let proposal = propose_v2(ParameterProposalRequestV2 {
        proposal_id: request.proposal_id,
        proposer_id: generator.principal().principal_id.clone(),
        evaluator_id,
        selected_artifact_digest: request.generated.selected_artifact_digest,
        window: request.generated.window.clone(),
        baseline_generation: request.admission.baseline_generation,
        candidate_generation: request.admission.candidate_generation,
        dataset_digest: request.admission.dataset_digest,
        update_rule_digest: request.admission.update_rule_digest,
        modulator_digest: request.admission.modulator_digest,
        modulator_broadcast_digest: request.admission.modulator_broadcast_digest,
        eligibility_digest: request.admission.eligibility_digest,
        evaluation_digest,
        rollback_predecessor_digest: request.admission.selected_artifact_digest,
        norm_layers: request.generated.norm_layers.clone(),
        candidates: request.generated.candidates.clone(),
    })?;

    let registry = match writer
        .registry
        .append_v2(request.expected_registry_predecessor, proposal.clone())
    {
        Ok(receipt) => {
            writer.mark_pending_anchor();
            receipt
        }
        Err(error) => {
            if matches!(
                error,
                DurableProposalRegistryError::Indeterminate
                    | DurableProposalRegistryError::Poisoned
            ) {
                writer.poison();
            }
            return Err(E::Registry(error));
        }
    };
    let committed_registry_anchor = match writer.registry.current_anchor() {
        Ok(Some(anchor)) => anchor,
        Ok(None) => {
            writer.poison();
            return Err(E::Registry(DurableProposalRegistryError::Corrupt));
        }
        Err(error) => {
            writer.poison();
            return Err(E::Registry(error));
        }
    };
    if !anchor_committer.persist_anchor(
        writer.registry_scope_digest,
        writer.writer_fence,
        committed_registry_anchor,
    ) {
        writer.poison();
        return Err(E::AnchorPersistenceFailed);
    }
    writer.mark_anchor_committed();

    let generator_authentication_digest = attestation_digest(&request.generator_attestation);
    let admission_authentication_digest = attestation_digest(&request.admission_attestation);
    let mut composition = b"hepta.intelligence.plasticity-composition.v1\0".to_vec();
    for digest in [
        proposal.proposal_digest,
        registry.frame_digest,
        committed_registry_anchor.frame_digest,
        request.mutation_grammar.manifest_digest,
        request.generated.generator_digest,
        generator_authentication_digest,
        admission_authentication_digest,
        evaluation_digest,
    ] {
        composition.extend_from_slice(digest.as_array());
    }
    Ok(ParameterPlasticityProductReceiptV1 {
        proposal,
        registry,
        generator_authentication_digest,
        admission_authentication_digest,
        evaluation_digest,
        committed_registry_anchor,
        composition_digest: Digest32::of_bytes(&composition),
    })
}

fn validate_admission_binding(
    request: &ParameterPlasticityProductRequestV1,
) -> Result<(), ParameterPlasticityProductErrorV1> {
    use ParameterPlasticityProductErrorV1 as E;
    let evidence = &request.admission;
    for (label, digest) in [
        ("objective", evidence.objective_digest),
        ("selected artifact", evidence.selected_artifact_digest),
        ("artifact registry binding", evidence.artifact_registry_binding),
        ("artifact registry head", evidence.artifact_registry_head_digest),
        (
            "qualification evidence head",
            evidence.qualification_evidence_head_digest,
        ),
        ("mutation grammar", evidence.mutation_grammar_digest),
        ("dataset", evidence.dataset_digest),
        ("update rule", evidence.update_rule_digest),
        ("modulator", evidence.modulator_digest),
        ("modulator broadcast", evidence.modulator_broadcast_digest),
        ("eligibility", evidence.eligibility_digest),
        ("generator", evidence.generator_digest),
        (
            "host evidence verification",
            request.host_evidence_verification_digest,
        ),
    ] {
        if digest.is_zero() {
            return Err(E::Binding(label));
        }
    }
    if evidence.baseline_generation.next() != Ok(evidence.candidate_generation) {
        return Err(E::Binding("generation successor"));
    }
    if evidence.selected_artifact_digest != request.generated.selected_artifact_digest
        || evidence.window != request.generated.window
        || evidence.generator_digest != request.generated.generator_digest
        || evidence.mutation_grammar_digest != request.mutation_grammar.manifest_digest
        || request.mutation_grammar.selected_artifact_digest
            != request.generated.selected_artifact_digest
        || request.generator_profile.selected_artifact_digest
            != request.generated.selected_artifact_digest
        || request.generator_profile.window != request.generated.window
    {
        return Err(E::Binding("generator/admission"));
    }
    Ok(())
}

fn attestation_digest(evidence: &SignedLearningEvidenceV1) -> Digest32 {
    let mut bytes = evidence.signing_bytes();
    bytes.extend_from_slice(&evidence.signature);
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    bytes.extend_from_slice(&(value.as_str().len() as u64).to_be_bytes());
    bytes.extend_from_slice(value.as_str().as_bytes());
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_plasticity::{
        ParameterMutationRuleV1, ProtectedParameterClassV1, ProtectedParameterV1,
        build_mutation_grammar_manifest_v1,
    };
    use std::io::{Seek, SeekFrom, Write};
    use tempfile::tempfile;

    #[test]
    fn product_writer_refuses_unanchored_nonempty_bootstrap() {
        let mut file = tempfile().expect("tempfile");
        file.write_all(b"history").expect("write");
        file.seek(SeekFrom::Start(0)).expect("seek");
        let result = AnchoredPlasticityWriterV1::bootstrap_new(
            file,
            Digest32::of_bytes(b"scope"),
            1,
            8,
        );
        assert!(matches!(
            result,
            Err(AnchoredPlasticityWriterErrorV1::BootstrapFileNotEmpty)
        ));
    }

    #[test]
    fn admission_payload_binds_current_frontiers_generator_and_grammar() {
        let id = |value: &str| StableId::new(value).expect("id");
        let generation = |value| Generation::new(value).expect("generation");
        let grammar = build_mutation_grammar_manifest_v1(
            id("grammar:1"),
            Digest32::of_bytes(b"artifact"),
            1,
            vec![ParameterMutationRuleV1 {
                layer_id: id("layer:1"),
                parameter_id: id("parameter:1"),
                minimum_delta: codex_hepta_types::FixedQ32::from_raw(-10),
                maximum_delta: codex_hepta_types::FixedQ32::from_raw(10),
            }],
            vec![ProtectedParameterV1 {
                parameter_id: id("parameter:authority"),
                class: ProtectedParameterClassV1::Authority,
            }],
        )
        .expect("grammar");
        let evidence = PlasticityAdmissionEvidenceV1 {
            baseline_id: id("artifact:baseline"),
            objective_digest: Digest32::of_bytes(b"objective"),
            selected_artifact_digest: Digest32::of_bytes(b"artifact"),
            artifact_registry_binding: Digest32::of_bytes(b"binding"),
            artifact_registry_head_digest: Digest32::of_bytes(b"artifact-head"),
            qualification_evidence_head_digest: Digest32::of_bytes(b"evidence-head"),
            mutation_grammar_digest: grammar.manifest_digest,
            window: ProposalWindowV2 {
                window_id: id("window:1"),
                window_digest: Digest32::of_bytes(b"window"),
            },
            baseline_generation: generation(1),
            candidate_generation: generation(2),
            dataset_digest: Digest32::of_bytes(b"dataset"),
            update_rule_digest: Digest32::of_bytes(b"update"),
            modulator_digest: Digest32::of_bytes(b"modulator"),
            modulator_broadcast_digest: Digest32::of_bytes(b"broadcast"),
            eligibility_digest: Digest32::of_bytes(b"eligibility"),
            generator_digest: Digest32::of_bytes(b"generator"),
        };
        let first = plasticity_admission_signing_payload_v1(&evidence);
        let mut changed = evidence.clone();
        changed.mutation_grammar_digest = Digest32::of_bytes(b"other-grammar");
        assert_ne!(first, plasticity_admission_signing_payload_v1(&changed));
    }
}
