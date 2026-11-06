//! Capability identities for logical, learnable cells inside existing owners.
//!
//! Roles classify work; a role is not a capability type, model, process or NDU
//! subject. These declarations neither authenticate model behavior nor grant
//! acceptance, publication, state-write or external-effect authority.

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

/// Initial engineering categories, not a claim that seven is an optimal count.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum CellFunctionalRoleV1 {
    PerceptionEncoding,
    MemoryAssociation,
    PredictionSimulation,
    DecisionCoordination,
    ActionGeneration,
    /// Critiques and calibration predictions require independently observed outcomes.
    VerificationMetacognition,
    /// Produces candidates for the existing learning and structural lifecycle owners.
    LearningDevelopment,
}

/// Deterministic support remains outside the learnable capability taxonomy.
/// These tags identify existing owner responsibilities, not new executable cells.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum DeterministicCellSupportV1 {
    ResourceHomeostasis,
    AuthorityEffects,
}

/// One versioned capability contract. Many contracts may share the same role.
///
/// Schema digests bind exact input, proposed output and isolated state formats.
/// The behavior contract additionally names semantics, abstention/termination
/// rules and evaluation targets. References require resolution by their existing
/// owners before execution; a nonzero digest alone is not evidence of validity.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellCapabilityContractV1 {
    pub type_id: StableId,
    pub generation: Generation,
    pub role: CellFunctionalRoleV1,
    pub input_schema_digest: Digest32,
    pub output_schema_digest: Digest32,
    pub state_schema_digest: Digest32,
    pub behavior_contract_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellCapabilityErrorV1 {
    EmptyDigest(&'static str),
}

impl std::fmt::Display for CellCapabilityErrorV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for CellCapabilityErrorV1 {}

impl CellCapabilityContractV1 {
    /// Bind the exact declaration without changing any existing neuron wire bytes.
    pub fn digest(&self) -> Result<Digest32, CellCapabilityErrorV1> {
        for (name, digest) in [
            ("input schema", self.input_schema_digest),
            ("output schema", self.output_schema_digest),
            ("state schema", self.state_schema_digest),
            ("behavior contract", self.behavior_contract_digest),
        ] {
            if digest.is_zero() {
                return Err(CellCapabilityErrorV1::EmptyDigest(name));
            }
        }
        let mut bytes = b"hepta.neuron.cell-capability.v1\0".to_vec();
        let id = self.type_id.as_str().as_bytes();
        bytes.extend_from_slice(&(id.len() as u64).to_be_bytes());
        bytes.extend_from_slice(id);
        bytes.extend_from_slice(&self.generation.get().to_be_bytes());
        bytes.push(match self.role {
            CellFunctionalRoleV1::PerceptionEncoding => 0,
            CellFunctionalRoleV1::MemoryAssociation => 1,
            CellFunctionalRoleV1::PredictionSimulation => 2,
            CellFunctionalRoleV1::DecisionCoordination => 3,
            CellFunctionalRoleV1::ActionGeneration => 4,
            CellFunctionalRoleV1::VerificationMetacognition => 5,
            CellFunctionalRoleV1::LearningDevelopment => 6,
        });
        for digest in [
            self.input_schema_digest,
            self.output_schema_digest,
            self.state_schema_digest,
            self.behavior_contract_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

#[cfg(test)]
#[path = "cell_roles_tests.rs"]
mod tests;
