use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::FreshnessWindowV1;
use crate::RuntimeModuleAbiV1;
use crate::RuntimeModulePromotionWitnessV1;
use crate::RuntimeModuleRegistryError;
use crate::RuntimeModuleRegistryV1;
use crate::RuntimeModuleStateClassV1;
use crate::RuntimeTopologySnapshotV1;
use crate::TrustedClockErrorV1;
use crate::TrustedClockV1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeModuleAdmissionEnvelopeV1 {
    pub module_id: StableId,
    pub generation: Generation,
    pub implementation_digest: Digest32,
    pub candidate_artifact_digest: Digest32,
    pub dependency_graph_digest: Digest32,
    pub selected_topology_digest: Digest32,
    pub source_commit_digest: Digest32,
    pub policy_epoch: u64,
    pub selection_digest: Digest32,
    pub canary_digest: Digest32,
    pub handoff_digest: Digest32,
    pub observed_at_micros: u64,
    pub expires_at_micros: u64,
    pub deadline_micros: u64,
}

impl RuntimeModuleAdmissionEnvelopeV1 {
    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.control.runtime-module-admission.v1\0".to_vec();
        push_id(&mut bytes, &self.module_id);
        bytes.extend_from_slice(&self.generation.get().to_be_bytes());
        bytes.extend_from_slice(self.implementation_digest.as_array());
        bytes.extend_from_slice(self.candidate_artifact_digest.as_array());
        bytes.extend_from_slice(self.dependency_graph_digest.as_array());
        bytes.extend_from_slice(self.selected_topology_digest.as_array());
        bytes.extend_from_slice(self.source_commit_digest.as_array());
        bytes.extend_from_slice(&self.policy_epoch.to_be_bytes());
        bytes.extend_from_slice(self.selection_digest.as_array());
        bytes.extend_from_slice(self.canary_digest.as_array());
        bytes.extend_from_slice(self.handoff_digest.as_array());
        bytes.extend_from_slice(&self.observed_at_micros.to_be_bytes());
        bytes.extend_from_slice(&self.expires_at_micros.to_be_bytes());
        bytes.extend_from_slice(&self.deadline_micros.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RuntimeModuleAdmissionVerificationErrorV1 {
    Rejected,
    Unavailable,
}

impl fmt::Display for RuntimeModuleAdmissionVerificationErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for RuntimeModuleAdmissionVerificationErrorV1 {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeModuleAdmissionVerificationV1 {
    pub verifier_id: StableId,
    pub envelope_digest: Digest32,
    pub dependency_admission_digest: Digest32,
    pub verification_digest: Digest32,
}

pub trait RuntimeModuleAdmissionVerifierV1: Send + Sync {
    fn verify(
        &self,
        envelope: &RuntimeModuleAdmissionEnvelopeV1,
    ) -> Result<RuntimeModuleAdmissionVerificationV1, RuntimeModuleAdmissionVerificationErrorV1>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BoundRuntimeModulePromotionV1 {
    envelope: RuntimeModuleAdmissionEnvelopeV1,
    verifier_id: StableId,
    dependency_admission_digest: Digest32,
    verification_digest: Digest32,
}

impl BoundRuntimeModulePromotionV1 {
    #[must_use]
    pub fn module_id(&self) -> &StableId {
        &self.envelope.module_id
    }

    #[must_use]
    pub fn generation(&self) -> Generation {
        self.envelope.generation
    }

    #[must_use]
    pub fn verifier_id(&self) -> &StableId {
        &self.verifier_id
    }

    #[must_use]
    pub fn verification_digest(&self) -> Digest32 {
        self.verification_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RuntimeModuleAdmissionErrorV1 {
    EmptyDigest(&'static str),
    InvalidPolicyEpoch,
    CandidateMissing,
    ModuleBindingMismatch,
    GenerationBindingMismatch,
    ImplementationBindingMismatch,
    ArtifactBindingMismatch,
    DependencyBindingMismatch,
    TopologyBindingMismatch,
    MissingWriterHandoff,
    Verification(RuntimeModuleAdmissionVerificationErrorV1),
    VerificationBindingMismatch,
    Clock(TrustedClockErrorV1),
    Registry(RuntimeModuleRegistryError),
}

impl fmt::Display for RuntimeModuleAdmissionErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for RuntimeModuleAdmissionErrorV1 {}

impl From<TrustedClockErrorV1> for RuntimeModuleAdmissionErrorV1 {
    fn from(error: TrustedClockErrorV1) -> Self {
        Self::Clock(error)
    }
}

impl From<RuntimeModuleRegistryError> for RuntimeModuleAdmissionErrorV1 {
    fn from(error: RuntimeModuleRegistryError) -> Self {
        Self::Registry(error)
    }
}

pub fn admit_runtime_module_promotion_v1<C: TrustedClockV1>(
    registry: &RuntimeModuleRegistryV1,
    envelope: RuntimeModuleAdmissionEnvelopeV1,
    verifier: &dyn RuntimeModuleAdmissionVerifierV1,
    clock: &C,
) -> Result<BoundRuntimeModulePromotionV1, RuntimeModuleAdmissionErrorV1> {
    validate_envelope(registry, &envelope, clock.now_micros()?)?;
    let envelope_digest = envelope.digest();
    let verification = verifier
        .verify(&envelope)
        .map_err(RuntimeModuleAdmissionErrorV1::Verification)?;
    if verification.envelope_digest != envelope_digest
        || verification.dependency_admission_digest.is_zero()
        || verification.verification_digest.is_zero()
    {
        return Err(RuntimeModuleAdmissionErrorV1::VerificationBindingMismatch);
    }
    validate_envelope(registry, &envelope, clock.now_micros()?)?;
    Ok(BoundRuntimeModulePromotionV1 {
        envelope,
        verifier_id: verification.verifier_id,
        dependency_admission_digest: verification.dependency_admission_digest,
        verification_digest: verification.verification_digest,
    })
}

pub fn promote_bound_runtime_module_v1<C: TrustedClockV1>(
    registry: &mut RuntimeModuleRegistryV1,
    promotion: &BoundRuntimeModulePromotionV1,
    clock: &C,
) -> Result<RuntimeTopologySnapshotV1, RuntimeModuleAdmissionErrorV1> {
    validate_envelope(registry, &promotion.envelope, clock.now_micros()?)?;
    if promotion.dependency_admission_digest.is_zero() || promotion.verification_digest.is_zero() {
        return Err(RuntimeModuleAdmissionErrorV1::VerificationBindingMismatch);
    }
    Ok(registry.promote_after_handoff(
        &promotion.envelope.module_id,
        promotion.envelope.generation,
        RuntimeModulePromotionWitnessV1 {
            selection_digest: promotion.envelope.selection_digest,
            canary_digest: promotion.envelope.canary_digest,
            handoff_digest: promotion.envelope.handoff_digest,
        },
    )?)
}

#[must_use]
pub fn runtime_module_dependency_graph_digest_v1(abi: &RuntimeModuleAbiV1) -> Digest32 {
    let mut dependencies = abi.dependencies.clone();
    dependencies.sort();
    let mut bytes = b"hepta.control.runtime-module-dependencies.v1\0".to_vec();
    push_id(&mut bytes, &abi.module_id);
    bytes.extend_from_slice(&abi.generation.get().to_be_bytes());
    for dependency in dependencies {
        push_id(&mut bytes, &dependency);
    }
    Digest32::of_bytes(&bytes)
}

#[must_use]
pub fn serving_runtime_topology_digest_v1(snapshot: &RuntimeTopologySnapshotV1) -> Digest32 {
    let mut active = snapshot.active.clone();
    active.sort_by(|left, right| {
        left.module_id
            .cmp(&right.module_id)
            .then(left.generation.cmp(&right.generation))
    });
    let mut bytes = b"hepta.control.serving-runtime-topology.v1\0".to_vec();
    for module in active {
        push_id(&mut bytes, &module.module_id);
        bytes.extend_from_slice(&module.generation.get().to_be_bytes());
        bytes.extend_from_slice(module.implementation_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn validate_envelope(
    registry: &RuntimeModuleRegistryV1,
    envelope: &RuntimeModuleAdmissionEnvelopeV1,
    now_micros: u64,
) -> Result<(), RuntimeModuleAdmissionErrorV1> {
    if envelope.policy_epoch == 0 {
        return Err(RuntimeModuleAdmissionErrorV1::InvalidPolicyEpoch);
    }
    for (name, digest) in [
        ("implementation", envelope.implementation_digest),
        ("candidate artifact", envelope.candidate_artifact_digest),
        ("dependency graph", envelope.dependency_graph_digest),
        ("selected topology", envelope.selected_topology_digest),
        ("source commit", envelope.source_commit_digest),
        ("selection", envelope.selection_digest),
        ("canary", envelope.canary_digest),
    ] {
        if digest.is_zero() {
            return Err(RuntimeModuleAdmissionErrorV1::EmptyDigest(name));
        }
    }
    FreshnessWindowV1 {
        observed_at_micros: envelope.observed_at_micros,
        expires_at_micros: envelope.expires_at_micros,
        deadline_micros: envelope.deadline_micros,
    }
    .validate_at(now_micros)?;

    let record = registry
        .record(&envelope.module_id, envelope.generation)
        .ok_or(RuntimeModuleAdmissionErrorV1::CandidateMissing)?;
    let abi = &record.abi;
    if abi.module_id != envelope.module_id {
        return Err(RuntimeModuleAdmissionErrorV1::ModuleBindingMismatch);
    }
    if abi.generation != envelope.generation {
        return Err(RuntimeModuleAdmissionErrorV1::GenerationBindingMismatch);
    }
    if abi.implementation_digest != envelope.implementation_digest {
        return Err(RuntimeModuleAdmissionErrorV1::ImplementationBindingMismatch);
    }
    if abi.candidate_artifact_digest != envelope.candidate_artifact_digest {
        return Err(RuntimeModuleAdmissionErrorV1::ArtifactBindingMismatch);
    }
    if runtime_module_dependency_graph_digest_v1(abi) != envelope.dependency_graph_digest {
        return Err(RuntimeModuleAdmissionErrorV1::DependencyBindingMismatch);
    }
    if serving_runtime_topology_digest_v1(&registry.snapshot())
        != envelope.selected_topology_digest
    {
        return Err(RuntimeModuleAdmissionErrorV1::TopologyBindingMismatch);
    }
    let handoff_required = abi.state_class != RuntimeModuleStateClassV1::Stateless
        || !abi.authoritative_domains.is_empty()
        || !abi.effect_scope.is_empty();
    if handoff_required && envelope.handoff_digest.is_zero() {
        return Err(RuntimeModuleAdmissionErrorV1::MissingWriterHandoff);
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    bytes.extend_from_slice(&(value.as_str().len() as u64).to_be_bytes());
    bytes.extend_from_slice(value.as_str().as_bytes());
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeSet;

    use super::*;
    use crate::ManualTrustedClockV1;
    use crate::RuntimeModuleLifecycleV1;

    struct Verifier;

    impl RuntimeModuleAdmissionVerifierV1 for Verifier {
        fn verify(
            &self,
            envelope: &RuntimeModuleAdmissionEnvelopeV1,
        ) -> Result<
            RuntimeModuleAdmissionVerificationV1,
            RuntimeModuleAdmissionVerificationErrorV1,
        > {
            Ok(RuntimeModuleAdmissionVerificationV1 {
                verifier_id: id("dependency-verifier"),
                envelope_digest: envelope.digest(),
                dependency_admission_digest: digest("dependency-admission"),
                verification_digest: digest("verification"),
            })
        }
    }

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn abi() -> RuntimeModuleAbiV1 {
        RuntimeModuleAbiV1 {
            module_id: id("module"),
            owner_id: id("owner"),
            generation: Generation::new(1).expect("generation"),
            implementation_digest: digest("implementation"),
            candidate_artifact_digest: digest("artifact"),
            predecessor_generation: None,
            rollback_predecessor_digest: Digest32::ZERO,
            state_class: RuntimeModuleStateClassV1::Stateful,
            dependencies: Vec::new(),
            input_ports: Vec::new(),
            output_ports: Vec::new(),
            authoritative_domains: [id("ledger")].into_iter().collect(),
            effect_scope: BTreeSet::new(),
        }
    }

    fn envelope(
        registry: &RuntimeModuleRegistryV1,
        abi: &RuntimeModuleAbiV1,
    ) -> RuntimeModuleAdmissionEnvelopeV1 {
        RuntimeModuleAdmissionEnvelopeV1 {
            module_id: abi.module_id.clone(),
            generation: abi.generation,
            implementation_digest: abi.implementation_digest,
            candidate_artifact_digest: abi.candidate_artifact_digest,
            dependency_graph_digest: runtime_module_dependency_graph_digest_v1(abi),
            selected_topology_digest: serving_runtime_topology_digest_v1(&registry.snapshot()),
            source_commit_digest: digest("source-commit"),
            policy_epoch: 9,
            selection_digest: digest("selection"),
            canary_digest: digest("canary"),
            handoff_digest: digest("handoff"),
            observed_at_micros: 10,
            expires_at_micros: 100,
            deadline_micros: 90,
        }
    }

    #[test]
    fn promotion_is_bound_to_candidate_dependencies_topology_and_time() {
        let candidate = abi();
        let mut registry = RuntimeModuleRegistryV1::new();
        registry
            .register_candidate(candidate.clone())
            .expect("register");
        registry
            .enter_shadow(&candidate.module_id, candidate.generation)
            .expect("shadow");
        registry
            .enter_canary(&candidate.module_id, candidate.generation)
            .expect("canary");
        let clock = ManualTrustedClockV1::new(20);
        let bound = admit_runtime_module_promotion_v1(
            &registry,
            envelope(&registry, &candidate),
            &Verifier,
            &clock,
        )
        .expect("admit");
        let snapshot = promote_bound_runtime_module_v1(&mut registry, &bound, &clock)
            .expect("promote");
        assert_eq!(snapshot.active[0].module_id, candidate.module_id);
        assert_eq!(
            registry
                .record(&id("module"), Generation::new(1).expect("generation"))
                .expect("record")
                .lifecycle,
            RuntimeModuleLifecycleV1::Active
        );
    }

    #[test]
    fn final_use_rejects_expired_bound_evidence() {
        let candidate = abi();
        let mut registry = RuntimeModuleRegistryV1::new();
        registry
            .register_candidate(candidate.clone())
            .expect("register");
        registry
            .enter_shadow(&candidate.module_id, candidate.generation)
            .expect("shadow");
        registry
            .enter_canary(&candidate.module_id, candidate.generation)
            .expect("canary");
        let clock = ManualTrustedClockV1::new(20);
        let bound = admit_runtime_module_promotion_v1(
            &registry,
            envelope(&registry, &candidate),
            &Verifier,
            &clock,
        )
        .expect("admit");
        clock.advance_to(100).expect("advance");
        assert_eq!(
            promote_bound_runtime_module_v1(&mut registry, &bound, &clock),
            Err(RuntimeModuleAdmissionErrorV1::Clock(
                TrustedClockErrorV1::EvidenceExpired
            ))
        );
    }
}
