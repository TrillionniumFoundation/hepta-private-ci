//! Authenticated product composition for topology plasticity proposals.
//!
//! Generator, Observer and Evaluator identities are verified under the existing
//! learning-evidence trust snapshot before a typed topology proposal can enter
//! the governed durable registry. This adapter never applies the topology.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_learning_ledger::{
    LearningEvidenceRoleV1, LearningEvidenceVerifierV1, SignedEvidenceError,
    SignedLearningEvidenceV1, verify_signed_role_separation,
};
use codex_hepta_plasticity::{
    DurableTopologyAppendReceiptV1, DurableTopologyProposalRegistryV1,
    DurableTopologyRegistryAnchorV1, DurableTopologyRegistryErrorV1,
    GovernedTopologyProposalV1, TopologyChangeV2, TopologyGovernanceErrorV1,
    TopologyProposalErrorV2, TopologyProposalRequestV2, ProposalWindowV2,
    WriterHandoffPlanV1, admit_governed_topology_v1, propose_topology_v2,
};
use codex_hepta_types::{Digest32, Generation, StableId};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TopologyAdmissionEvidenceV1 {
    pub baseline_id: StableId,
    pub objective_digest: Digest32,
    pub selected_artifact_digest: Digest32,
    pub artifact_registry_head_digest: Digest32,
    pub qualification_evidence_head_digest: Digest32,
    pub window: ProposalWindowV2,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub generation_digest: Digest32,
    /// Digest of an evaluator-owned result/receipt; the Evaluator signature
    /// below authenticates that exact receipt in this proposal context.
    pub evaluation_receipt_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TopologyPlasticityProductRequestV1 {
    pub proposal_id: StableId,
    pub proposer_generation_id: StableId,
    pub selected_artifact_digest: Digest32,
    pub window: ProposalWindowV2,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub rollback_predecessor_digest: Digest32,
    pub changes: Vec<TopologyChangeV2>,
    pub handoffs: Vec<WriterHandoffPlanV1>,
    pub admission: TopologyAdmissionEvidenceV1,
    pub generator_attestation: SignedLearningEvidenceV1,
    pub observer_attestation: SignedLearningEvidenceV1,
    pub evaluator_attestation: SignedLearningEvidenceV1,
    pub expected_registry_predecessor: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TopologyPlasticityProductReceiptV1 {
    pub governed: GovernedTopologyProposalV1,
    pub durable: DurableTopologyAppendReceiptV1,
    pub next_registry_anchor: DurableTopologyRegistryAnchorV1,
    pub generator_authentication_digest: Digest32,
    pub observer_authentication_digest: Digest32,
    pub evaluator_authentication_digest: Digest32,
    pub composition_digest: Digest32,
}

#[derive(Debug)]
pub enum TopologyPlasticityProductErrorV1 {
    Binding(&'static str),
    GeneratorEvidence(SignedEvidenceError),
    ObserverEvidence(SignedEvidenceError),
    EvaluatorEvidence(SignedEvidenceError),
    Proposal(TopologyProposalErrorV2),
    Governance(TopologyGovernanceErrorV1),
    Registry(DurableTopologyRegistryErrorV1),
    MissingAnchor,
}

impl fmt::Display for TopologyPlasticityProductErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for TopologyPlasticityProductErrorV1 {}
impl From<TopologyProposalErrorV2> for TopologyPlasticityProductErrorV1 {
    fn from(value: TopologyProposalErrorV2) -> Self {
        Self::Proposal(value)
    }
}
impl From<TopologyGovernanceErrorV1> for TopologyPlasticityProductErrorV1 {
    fn from(value: TopologyGovernanceErrorV1) -> Self {
        Self::Governance(value)
    }
}
impl From<DurableTopologyRegistryErrorV1> for TopologyPlasticityProductErrorV1 {
    fn from(value: DurableTopologyRegistryErrorV1) -> Self {
        Self::Registry(value)
    }
}

pub fn topology_generation_signing_payload_v1(
    request: &TopologyPlasticityProductRequestV1,
) -> Result<Vec<u8>, TopologyPlasticityProductErrorV1> {
    if request.selected_artifact_digest.is_zero()
        || request.window.window_digest.is_zero()
        || request.rollback_predecessor_digest != request.selected_artifact_digest
        || request.baseline_generation.next() != Ok(request.candidate_generation)
    {
        return Err(TopologyPlasticityProductErrorV1::Binding(
            "topology generation context",
        ));
    }
    let mut changes = request.changes.clone();
    changes.sort();
    let mut handoffs = request.handoffs.clone();
    handoffs.sort_by(|left, right| left.module_id.cmp(&right.module_id));
    let mut bytes = b"hepta.intelligence.topology-generation.v1\0".to_vec();
    push_id(&mut bytes, &request.proposer_generation_id);
    bytes.extend_from_slice(request.selected_artifact_digest.as_array());
    push_id(&mut bytes, &request.window.window_id);
    bytes.extend_from_slice(request.window.window_digest.as_array());
    bytes.extend_from_slice(&request.baseline_generation.get().to_be_bytes());
    bytes.extend_from_slice(&request.candidate_generation.get().to_be_bytes());
    push_len(&mut bytes, changes.len());
    for change in changes {
        push_id(&mut bytes, &change.module_id);
        bytes.push(match change.operation {
            codex_hepta_plasticity::TopologyOperationV2::Add => 0,
            codex_hepta_plasticity::TopologyOperationV2::Remove => 1,
            codex_hepta_plasticity::TopologyOperationV2::Replace => 2,
            codex_hepta_plasticity::TopologyOperationV2::Split => 3,
            codex_hepta_plasticity::TopologyOperationV2::Merge => 4,
            codex_hepta_plasticity::TopologyOperationV2::Rewire => 5,
            codex_hepta_plasticity::TopologyOperationV2::Retire => 6,
        });
        push_optional_digest(&mut bytes, change.predecessor_digest);
        push_optional_digest(&mut bytes, change.candidate_digest);
        for digest in [
            change.migration_digest,
            change.rollback_digest,
            change.writer_handoff_digest,
            change.evidence_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
    }
    push_len(&mut bytes, handoffs.len());
    for handoff in handoffs {
        push_id(&mut bytes, &handoff.module_id);
        bytes.extend_from_slice(handoff.plan_digest.as_array());
    }
    Ok(bytes)
}

pub fn topology_admission_signing_payload_v1(
    evidence: &TopologyAdmissionEvidenceV1,
) -> Vec<u8> {
    let mut bytes = b"hepta.intelligence.topology-admission.v1\0".to_vec();
    push_id(&mut bytes, &evidence.baseline_id);
    for digest in [
        evidence.objective_digest,
        evidence.selected_artifact_digest,
        evidence.artifact_registry_head_digest,
        evidence.qualification_evidence_head_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_id(&mut bytes, &evidence.window.window_id);
    bytes.extend_from_slice(evidence.window.window_digest.as_array());
    bytes.extend_from_slice(&evidence.baseline_generation.get().to_be_bytes());
    bytes.extend_from_slice(&evidence.candidate_generation.get().to_be_bytes());
    bytes.extend_from_slice(evidence.generation_digest.as_array());
    bytes.extend_from_slice(evidence.evaluation_receipt_digest.as_array());
    bytes
}

pub fn topology_evaluation_signing_payload_v1(
    evidence: &TopologyAdmissionEvidenceV1,
) -> Vec<u8> {
    let mut bytes = b"hepta.intelligence.topology-evaluation.v1\0".to_vec();
    bytes.extend_from_slice(Digest32::of_bytes(
        &topology_admission_signing_payload_v1(evidence),
    ).as_array());
    bytes.extend_from_slice(evidence.evaluation_receipt_digest.as_array());
    bytes
}

pub fn propose_authenticated_topology_plasticity_v1(
    request: TopologyPlasticityProductRequestV1,
    verifier: &LearningEvidenceVerifierV1,
    registry: &mut DurableTopologyProposalRegistryV1,
    now: u64,
) -> Result<TopologyPlasticityProductReceiptV1, TopologyPlasticityProductErrorV1> {
    use TopologyPlasticityProductErrorV1 as E;

    let generation_payload = topology_generation_signing_payload_v1(&request)?;
    let generation_digest = Digest32::of_bytes(&generation_payload);
    if request.admission.generation_digest != generation_digest
        || request.admission.selected_artifact_digest != request.selected_artifact_digest
        || request.admission.window != request.window
        || request.admission.baseline_generation != request.baseline_generation
        || request.admission.candidate_generation != request.candidate_generation
        || request.admission.objective_digest.is_zero()
        || request.admission.artifact_registry_head_digest.is_zero()
        || request.admission.qualification_evidence_head_digest.is_zero()
        || request.admission.evaluation_receipt_digest.is_zero()
    {
        return Err(E::Binding("topology admission"));
    }

    let generator = verifier
        .verify(
            LearningEvidenceRoleV1::Generator,
            &request.generator_attestation,
            &generation_payload,
            now,
        )
        .map_err(E::GeneratorEvidence)?;
    if generator.principal().principal_id != request.proposer_generation_id {
        return Err(E::Binding("generator principal"));
    }

    let admission_payload = topology_admission_signing_payload_v1(&request.admission);
    let observer = verifier
        .verify(
            LearningEvidenceRoleV1::Observer,
            &request.observer_attestation,
            &admission_payload,
            now,
        )
        .map_err(E::ObserverEvidence)?;
    let evaluation_payload = topology_evaluation_signing_payload_v1(&request.admission);
    let evaluator = verifier
        .verify(
            LearningEvidenceRoleV1::Evaluator,
            &request.evaluator_attestation,
            &evaluation_payload,
            now,
        )
        .map_err(E::EvaluatorEvidence)?;

    verify_signed_role_separation(&generator, &observer, now).map_err(E::ObserverEvidence)?;
    verify_signed_role_separation(&generator, &evaluator, now).map_err(E::EvaluatorEvidence)?;
    verify_signed_role_separation(&observer, &evaluator, now).map_err(E::EvaluatorEvidence)?;

    for evidence in [
        &request.generator_attestation,
        &request.observer_attestation,
        &request.evaluator_attestation,
    ] {
        if evidence.objective_digest != request.admission.objective_digest {
            return Err(E::Binding("objective trust context"));
        }
    }

    let evaluator_authentication_digest = attestation_digest(&request.evaluator_attestation);
    let proposal = propose_topology_v2(TopologyProposalRequestV2 {
        proposal_id: request.proposal_id,
        proposer_id: generator.principal().principal_id.clone(),
        evaluator_id: evaluator.principal().principal_id.clone(),
        selected_artifact_digest: request.selected_artifact_digest,
        window: request.window,
        baseline_generation: request.baseline_generation,
        candidate_generation: request.candidate_generation,
        evaluation_digest: evaluator_authentication_digest,
        rollback_predecessor_digest: request.rollback_predecessor_digest,
        changes: request.changes,
    })?;
    let generator_authentication_digest = attestation_digest(&request.generator_attestation);
    let observer_authentication_digest = attestation_digest(&request.observer_attestation);
    let governed = admit_governed_topology_v1(
        proposal,
        request.handoffs,
        observer_authentication_digest,
        evaluator_authentication_digest,
    )?;
    let durable = registry.append(request.expected_registry_predecessor, governed.clone())?;
    let next_registry_anchor = registry.current_anchor()?.ok_or(E::MissingAnchor)?;

    let mut composition = b"hepta.intelligence.topology-composition.v1\0".to_vec();
    for digest in [
        governed.admission_digest,
        durable.frame_digest,
        next_registry_anchor.frame_digest,
        generator_authentication_digest,
        observer_authentication_digest,
        evaluator_authentication_digest,
    ] {
        composition.extend_from_slice(digest.as_array());
    }
    Ok(TopologyPlasticityProductReceiptV1 {
        governed,
        durable,
        next_registry_anchor,
        generator_authentication_digest,
        observer_authentication_digest,
        evaluator_authentication_digest,
        composition_digest: Digest32::of_bytes(&composition),
    })
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
fn push_len(bytes: &mut Vec<u8>, value: usize) {
    bytes.extend_from_slice(&(value as u64).to_be_bytes());
}
fn push_optional_digest(bytes: &mut Vec<u8>, value: Option<Digest32>) {
    match value {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(value.as_array());
        }
        None => bytes.push(0),
    }
}


#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_learning_ledger::{
        AuthenticatedPrincipalV1, LearningEvidenceTrustV1, TrustedLearningSignerV1,
    };
    use codex_hepta_plasticity::{
        TopologyOperationV2, build_writer_handoff_plan_v1,
    };
    use ed25519_dalek::{Signer, SigningKey};
    use tempfile::tempfile;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }
    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }
    fn generation(value: u64) -> Generation {
        Generation::new(value).expect("generation")
    }

    #[test]
    fn authenticated_topology_path_verifies_three_roles_and_persists_governed_record() {
        let keys = [
            SigningKey::from_bytes(&[41; 32]),
            SigningKey::from_bytes(&[42; 32]),
            SigningKey::from_bytes(&[43; 32]),
        ];
        let objective = digest(b"objective");
        let scope = digest(b"scope");
        let principals = keys
            .iter()
            .enumerate()
            .map(|(index, key)| AuthenticatedPrincipalV1 {
                principal_id: id(&format!("principal:{index}")),
                credential_chain_digest: digest(format!("credential:{index}").as_bytes()),
                signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                scope_digest: scope,
                authority_epoch: 3,
                authenticated_at: 10,
                expires_at: 100,
            })
            .collect::<Vec<_>>();
        let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
            scope_digest: scope,
            objective_digest: objective,
            authority_epoch: 3,
            signers: principals
                .iter()
                .zip(&keys)
                .enumerate()
                .map(|(index, (principal, key))| TrustedLearningSignerV1 {
                    principal: principal.clone(),
                    controller_id: id(&format!("controller:{index}")),
                    verifying_key: key.verifying_key().to_bytes(),
                    roles: vec![match index {
                        0 => LearningEvidenceRoleV1::Generator,
                        1 => LearningEvidenceRoleV1::Observer,
                        _ => LearningEvidenceRoleV1::Evaluator,
                    }],
                    revoked_at: None,
                })
                .collect(),
        })
        .expect("verifier");

        let artifact = digest(b"artifact");
        let window = ProposalWindowV2 {
            window_id: id("window:topology"),
            window_digest: digest(b"window"),
        };
        let handoff = build_writer_handoff_plan_v1(
            id("module:adapter"),
            id("owner:old"),
            id("owner:new"),
            3,
            4,
            digest(b"source-store"),
            digest(b"migration"),
            digest(b"rollback"),
            digest(b"ack-contract"),
        )
        .expect("handoff");
        let change = TopologyChangeV2 {
            module_id: id("module:adapter"),
            operation: TopologyOperationV2::Replace,
            predecessor_digest: Some(digest(b"old")),
            candidate_digest: Some(digest(b"new")),
            migration_digest: handoff.migration_digest,
            rollback_digest: handoff.rollback_digest,
            writer_handoff_digest: handoff.plan_digest,
            evidence_digest: digest(b"evidence"),
        };

        let blank = |index: usize, role: LearningEvidenceRoleV1| SignedLearningEvidenceV1 {
            evidence_id: id(&format!("evidence:{index}")),
            principal_id: principals[index].principal_id.clone(),
            role,
            trust_digest: verifier.trust_digest(),
            scope_digest: scope,
            objective_digest: objective,
            authority_epoch: 3,
            issued_at: 20,
            expires_at: 90,
            payload_digest: digest(b"placeholder"),
            signature: [0; 64],
        };
        let mut request = TopologyPlasticityProductRequestV1 {
            proposal_id: id("proposal:topology"),
            proposer_generation_id: principals[0].principal_id.clone(),
            selected_artifact_digest: artifact,
            window: window.clone(),
            baseline_generation: generation(4),
            candidate_generation: generation(5),
            rollback_predecessor_digest: artifact,
            changes: vec![change],
            handoffs: vec![handoff],
            admission: TopologyAdmissionEvidenceV1 {
                baseline_id: id("artifact:baseline"),
                objective_digest: objective,
                selected_artifact_digest: artifact,
                artifact_registry_head_digest: digest(b"artifact-head"),
                qualification_evidence_head_digest: digest(b"evidence-head"),
                window,
                baseline_generation: generation(4),
                candidate_generation: generation(5),
                generation_digest: Digest32::ZERO,
                evaluation_receipt_digest: digest(b"evaluation-receipt"),
            },
            generator_attestation: blank(0, LearningEvidenceRoleV1::Generator),
            observer_attestation: blank(1, LearningEvidenceRoleV1::Observer),
            evaluator_attestation: blank(2, LearningEvidenceRoleV1::Evaluator),
            expected_registry_predecessor: Digest32::ZERO,
        };

        fn sign(
            mut evidence: SignedLearningEvidenceV1,
            key: &SigningKey,
            payload: &[u8],
        ) -> SignedLearningEvidenceV1 {
            evidence.payload_digest = Digest32::of_bytes(payload);
            evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
            evidence
        }

        let generation_payload =
            topology_generation_signing_payload_v1(&request).expect("generation payload");
        request.admission.generation_digest = Digest32::of_bytes(&generation_payload);
        request.generator_attestation =
            sign(request.generator_attestation, &keys[0], &generation_payload);
        let observer_payload = topology_admission_signing_payload_v1(&request.admission);
        request.observer_attestation =
            sign(request.observer_attestation, &keys[1], &observer_payload);
        let evaluator_payload = topology_evaluation_signing_payload_v1(&request.admission);
        request.evaluator_attestation =
            sign(request.evaluator_attestation, &keys[2], &evaluator_payload);

        let mut registry = DurableTopologyProposalRegistryV1::bootstrap_empty(
            tempfile().expect("registry"),
            digest(b"registry-scope"),
            9,
            8,
        )
        .expect("registry");
        let receipt =
            propose_authenticated_topology_plasticity_v1(request, &verifier, &mut registry, 50)
                .expect("topology product");
        assert_eq!(
            receipt.governed.proposal.proposer_id,
            principals[0].principal_id
        );
        assert_eq!(
            receipt.governed.proposal.evaluator_id,
            principals[2].principal_id
        );
        assert_eq!(registry.record_count(), Ok(1));
        assert!(!receipt.composition_digest.is_zero());
    }
}
