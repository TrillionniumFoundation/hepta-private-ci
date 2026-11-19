//! Versioned semantic contracts for typed cell roles.
//!
//! CellSplitV1 remains the DecisionCell split contract. This module adds a
//! role description layer without changing the old split wire format or digest.
//! Records here are authority-free descriptions, not runtime commands.

use std::error::Error;
use std::fmt;

use crate::AuthorityPosture;
use crate::Digest32;
use crate::Generation;
use crate::StableId;
use crate::canonical_digest::CanonicalDigestError;
use crate::canonical_digest::CanonicalFieldV1;
use crate::canonical_digest::CanonicalValueV1;
use crate::canonical_digest::canonical_digest_v1;

const ROLE_SCHEMA_V1: u32 = 1;
const DEFINITION_SCHEMA_V2: u32 = 2;
const RECEIPT_SCHEMA_V1: u32 = 1;
const PPM_MAX_V1: u32 = 1_000_000;

/// Semantic responsibility of a typed cell.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum CellRoleV1 {
    Representation,
    MemoryRead,
    Predictor,
    Value,
    Decision,
    Evaluator,
    Planner,
    Router,
    ActionProposal,
    Plasticity,
    Communication,
}

impl CellRoleV1 {
    pub const fn tag(self) -> u8 {
        match self {
            Self::Representation => 0,
            Self::MemoryRead => 1,
            Self::Predictor => 2,
            Self::Value => 3,
            Self::Decision => 4,
            Self::Evaluator => 5,
            Self::Planner => 6,
            Self::Router => 7,
            Self::ActionProposal => 8,
            Self::Plasticity => 9,
            Self::Communication => 10,
        }
    }

    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Representation => "representation",
            Self::MemoryRead => "memory-read",
            Self::Predictor => "predictor",
            Self::Value => "value",
            Self::Decision => "decision",
            Self::Evaluator => "evaluator",
            Self::Planner => "planner",
            Self::Router => "router",
            Self::ActionProposal => "action-proposal",
            Self::Plasticity => "plasticity",
            Self::Communication => "communication",
        }
    }
}

/// State retention contract. It is not a storage implementation.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum CellPersistenceClassV1 {
    Ephemeral,
    Checkpointed,
    Durable,
    LedgerBacked,
}

impl CellPersistenceClassV1 {
    pub const fn tag(self) -> u8 {
        match self {
            Self::Ephemeral => 0,
            Self::Checkpointed => 1,
            Self::Durable => 2,
            Self::LedgerBacked => 3,
        }
    }
}

/// Candidate update cadence. This never grants promotion or writer authority.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum CellUpdateModeV1 {
    InferenceOnly,
    OutcomeProposal,
    OnlineConstrained,
    BatchCandidate,
}

impl CellUpdateModeV1 {
    pub const fn tag(self) -> u8 {
        match self {
            Self::InferenceOnly => 0,
            Self::OutcomeProposal => 1,
            Self::OnlineConstrained => 2,
            Self::BatchCandidate => 3,
        }
    }
}

/// Terminal disposition carried by an immutable step receipt.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum CellStepStatusV1 {
    Accepted,
    Abstained,
    SlowPath,
    Rejected,
    Failed,
}

impl CellStepStatusV1 {
    pub const fn tag(self) -> u8 {
        match self {
            Self::Accepted => 0,
            Self::Abstained => 1,
            Self::SlowPath => 2,
            Self::Rejected => 3,
            Self::Failed => 4,
        }
    }

    pub const fn is_abstain(self) -> bool {
        matches!(self, Self::Abstained)
    }

    pub const fn is_slow_path(self) -> bool {
        matches!(self, Self::SlowPath)
    }
}

/// Capability and owner bindings for one role.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellCapabilityProfileV1 {
    pub role: CellRoleV1,
    pub observation_schema_digest: Digest32,
    pub output_schema_digest: Digest32,
    pub state_schema_digest: Digest32,
    pub input_port_digest: Digest32,
    pub output_port_digest: Digest32,
    pub termination_port_digest: Digest32,
    pub owner_module: StableId,
    pub persistence_class: CellPersistenceClassV1,
    pub update_mode: CellUpdateModeV1,
    pub fallback_role: Option<CellRoleV1>,
    pub objective_digest: Digest32,
    pub resource_budget_digest: Digest32,
    pub evaluation_profile_digest: Digest32,
    /// Explicitly carried so role and owner metadata cannot imply authority.
    pub authority: AuthorityPosture,
}

impl CellCapabilityProfileV1 {
    pub fn validate(&self) -> Result<(), CellRoleContractErrorV1> {
        for (label, digest) in [
            ("observation schema", self.observation_schema_digest),
            ("output schema", self.output_schema_digest),
            ("state schema", self.state_schema_digest),
            ("input port", self.input_port_digest),
            ("output port", self.output_port_digest),
            ("termination port", self.termination_port_digest),
            ("objective", self.objective_digest),
            ("resource budget", self.resource_budget_digest),
            ("evaluation profile", self.evaluation_profile_digest),
        ] {
            require_digest(digest, label)?;
        }
        require_id(&self.owner_module, "owner module")?;
        if self.authority.grants_any() {
            return Err(CellRoleContractErrorV1::AuthorityGrant);
        }
        if self.fallback_role == Some(self.role) {
            return Err(CellRoleContractErrorV1::SelfFallback);
        }
        Ok(())
    }

    pub fn content_digest(&self) -> Result<Digest32, CellRoleContractErrorV1> {
        self.validate()?;
        let type_id = type_id("cell-capability-profile-v1")?;
        let fallback = self
            .fallback_role
            .map_or(u64::MAX, |role| u64::from(role.tag()));
        canonical_digest_v1(
            &type_id,
            ROLE_SCHEMA_V1,
            &[
                field("role", CanonicalValueV1::U64(u64::from(self.role.tag()))),
                field(
                    "observation-schema",
                    CanonicalValueV1::Digest(self.observation_schema_digest),
                ),
                field(
                    "output-schema",
                    CanonicalValueV1::Digest(self.output_schema_digest),
                ),
                field(
                    "state-schema",
                    CanonicalValueV1::Digest(self.state_schema_digest),
                ),
                field(
                    "input-port",
                    CanonicalValueV1::Digest(self.input_port_digest),
                ),
                field(
                    "output-port",
                    CanonicalValueV1::Digest(self.output_port_digest),
                ),
                field(
                    "termination-port",
                    CanonicalValueV1::Digest(self.termination_port_digest),
                ),
                field(
                    "owner-module",
                    CanonicalValueV1::StableId(&self.owner_module),
                ),
                field(
                    "persistence",
                    CanonicalValueV1::U64(u64::from(self.persistence_class.tag())),
                ),
                field(
                    "update-mode",
                    CanonicalValueV1::U64(u64::from(self.update_mode.tag())),
                ),
                field("fallback-role", CanonicalValueV1::U64(fallback)),
                field("objective", CanonicalValueV1::Digest(self.objective_digest)),
                field(
                    "resource-budget",
                    CanonicalValueV1::Digest(self.resource_budget_digest),
                ),
                field(
                    "evaluation-profile",
                    CanonicalValueV1::Digest(self.evaluation_profile_digest),
                ),
            ],
        )
        .map_err(CellRoleContractErrorV1::CanonicalDigest)
    }
}

/// Versioned identity and execution bindings for one typed cell.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellDefinitionV2 {
    pub cell_id: StableId,
    pub generation: Generation,
    pub scope_digest: Digest32,
    pub lineage_digest: Digest32,
    pub role: CellRoleV1,
    pub capability_profile: CellCapabilityProfileV1,
    pub parameter_bundle_digest: Digest32,
    pub state_schema_digest: Digest32,
    pub port_abi_digest: Digest32,
    pub owner_module: StableId,
    pub objective_digest: Digest32,
    pub fallback_role: Option<CellRoleV1>,
    pub evidence_owner: StableId,
    pub authority: AuthorityPosture,
}

impl CellDefinitionV2 {
    pub fn validate(&self) -> Result<(), CellRoleContractErrorV1> {
        require_id(&self.cell_id, "cell")?;
        require_digest(self.scope_digest, "scope")?;
        require_digest(self.lineage_digest, "lineage")?;
        require_digest(self.parameter_bundle_digest, "parameter bundle")?;
        require_digest(self.state_schema_digest, "state schema")?;
        require_digest(self.port_abi_digest, "port ABI")?;
        require_digest(self.objective_digest, "objective")?;
        require_id(&self.owner_module, "owner module")?;
        require_id(&self.evidence_owner, "evidence owner")?;
        if self.authority.grants_any() {
            return Err(CellRoleContractErrorV1::AuthorityGrant);
        }
        self.capability_profile.validate()?;
        if self.role != self.capability_profile.role {
            return Err(CellRoleContractErrorV1::RoleMismatch);
        }
        if self.state_schema_digest != self.capability_profile.state_schema_digest {
            return Err(CellRoleContractErrorV1::StateSchemaMismatch);
        }
        if self.owner_module != self.capability_profile.owner_module {
            return Err(CellRoleContractErrorV1::OwnerMismatch);
        }
        if self.fallback_role != self.capability_profile.fallback_role {
            return Err(CellRoleContractErrorV1::FallbackMismatch);
        }
        if self.fallback_role == Some(self.role) {
            return Err(CellRoleContractErrorV1::SelfFallback);
        }
        Ok(())
    }

    pub fn capability_digest(&self) -> Result<Digest32, CellRoleContractErrorV1> {
        self.capability_profile.content_digest()
    }

    pub fn content_digest(&self) -> Result<Digest32, CellRoleContractErrorV1> {
        self.validate()?;
        let type_id = type_id("cell-definition-v2")?;
        let fallback = self
            .fallback_role
            .map_or(u64::MAX, |role| u64::from(role.tag()));
        let capability_digest = self.capability_digest()?;
        canonical_digest_v1(
            &type_id,
            DEFINITION_SCHEMA_V2,
            &[
                field("cell", CanonicalValueV1::StableId(&self.cell_id)),
                field("generation", CanonicalValueV1::U64(self.generation.get())),
                field("scope", CanonicalValueV1::Digest(self.scope_digest)),
                field("lineage", CanonicalValueV1::Digest(self.lineage_digest)),
                field("role", CanonicalValueV1::U64(u64::from(self.role.tag()))),
                field("capability", CanonicalValueV1::Digest(capability_digest)),
                field(
                    "parameter-bundle",
                    CanonicalValueV1::Digest(self.parameter_bundle_digest),
                ),
                field(
                    "state-schema",
                    CanonicalValueV1::Digest(self.state_schema_digest),
                ),
                field("port-abi", CanonicalValueV1::Digest(self.port_abi_digest)),
                field(
                    "owner-module",
                    CanonicalValueV1::StableId(&self.owner_module),
                ),
                field("objective", CanonicalValueV1::Digest(self.objective_digest)),
                field("fallback-role", CanonicalValueV1::U64(fallback)),
                field(
                    "evidence-owner",
                    CanonicalValueV1::StableId(&self.evidence_owner),
                ),
            ],
        )
        .map_err(CellRoleContractErrorV1::CanonicalDigest)
    }
}

/// Immutable observation receipt for one typed step.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellStepReceiptV1 {
    pub cell_id: StableId,
    pub generation: Generation,
    pub scope_digest: Digest32,
    pub role: CellRoleV1,
    pub capability_digest: Digest32,
    pub input_frontier_digest: Digest32,
    pub state_predecessor_digest: Digest32,
    pub state_successor_digest: Digest32,
    pub output_digest: Digest32,
    pub uncertainty_ppm: u32,
    pub ood_ppm: u32,
    pub resource_receipt_digest: Digest32,
    pub evidence_digest: Digest32,
    pub status: CellStepStatusV1,
    pub authority: AuthorityPosture,
}

impl CellStepReceiptV1 {
    pub const fn abstained(&self) -> bool {
        self.status.is_abstain()
    }

    pub const fn slow_path(&self) -> bool {
        self.status.is_slow_path()
    }

    pub fn validate(&self) -> Result<(), CellRoleContractErrorV1> {
        require_id(&self.cell_id, "cell")?;
        for (label, digest) in [
            ("scope", self.scope_digest),
            ("capability", self.capability_digest),
            ("input frontier", self.input_frontier_digest),
            ("state predecessor", self.state_predecessor_digest),
            ("state successor", self.state_successor_digest),
            ("output", self.output_digest),
            ("resource receipt", self.resource_receipt_digest),
            ("evidence", self.evidence_digest),
        ] {
            require_digest(digest, label)?;
        }
        if self.uncertainty_ppm > PPM_MAX_V1 || self.ood_ppm > PPM_MAX_V1 {
            return Err(CellRoleContractErrorV1::InvalidPpm);
        }
        if self.authority.grants_any() {
            return Err(CellRoleContractErrorV1::AuthorityGrant);
        }
        Ok(())
    }

    pub fn content_digest(&self) -> Result<Digest32, CellRoleContractErrorV1> {
        self.validate()?;
        let type_id = type_id("cell-step-receipt-v1")?;
        canonical_digest_v1(
            &type_id,
            RECEIPT_SCHEMA_V1,
            &[
                field("cell", CanonicalValueV1::StableId(&self.cell_id)),
                field("generation", CanonicalValueV1::U64(self.generation.get())),
                field("scope", CanonicalValueV1::Digest(self.scope_digest)),
                field("role", CanonicalValueV1::U64(u64::from(self.role.tag()))),
                field(
                    "capability",
                    CanonicalValueV1::Digest(self.capability_digest),
                ),
                field(
                    "input-frontier",
                    CanonicalValueV1::Digest(self.input_frontier_digest),
                ),
                field(
                    "state-predecessor",
                    CanonicalValueV1::Digest(self.state_predecessor_digest),
                ),
                field(
                    "state-successor",
                    CanonicalValueV1::Digest(self.state_successor_digest),
                ),
                field("output", CanonicalValueV1::Digest(self.output_digest)),
                field(
                    "uncertainty-ppm",
                    CanonicalValueV1::U64(u64::from(self.uncertainty_ppm)),
                ),
                field("ood-ppm", CanonicalValueV1::U64(u64::from(self.ood_ppm))),
                field(
                    "resource-receipt",
                    CanonicalValueV1::Digest(self.resource_receipt_digest),
                ),
                field("evidence", CanonicalValueV1::Digest(self.evidence_digest)),
                field(
                    "status",
                    CanonicalValueV1::U64(u64::from(self.status.tag())),
                ),
            ],
        )
        .map_err(CellRoleContractErrorV1::CanonicalDigest)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellRoleContractErrorV1 {
    EmptyDigest(&'static str),
    EmptyId(&'static str),
    AuthorityGrant,
    SelfFallback,
    RoleMismatch,
    StateSchemaMismatch,
    OwnerMismatch,
    FallbackMismatch,
    InvalidPpm,
    CanonicalDigest(CanonicalDigestError),
}

impl fmt::Display for CellRoleContractErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for CellRoleContractErrorV1 {}

fn field<'a>(name: &'a str, value: CanonicalValueV1<'a>) -> CanonicalFieldV1<'a> {
    CanonicalFieldV1 { name, value }
}

fn type_id(local: &str) -> Result<StableId, CellRoleContractErrorV1> {
    StableId::new(format!("hepta.types:{local}"))
        .map_err(|_| CellRoleContractErrorV1::EmptyId("type id"))
}

fn require_id(id: &StableId, label: &'static str) -> Result<(), CellRoleContractErrorV1> {
    if id.as_str().is_empty() {
        Err(CellRoleContractErrorV1::EmptyId(label))
    } else {
        Ok(())
    }
}

fn require_digest(digest: Digest32, label: &'static str) -> Result<(), CellRoleContractErrorV1> {
    if digest.is_zero() {
        Err(CellRoleContractErrorV1::EmptyDigest(label))
    } else {
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("valid stable id")
    }

    fn digest(value: u8) -> Digest32 {
        Digest32::of_bytes(&[value])
    }

    fn profile(role: CellRoleV1) -> CellCapabilityProfileV1 {
        CellCapabilityProfileV1 {
            role,
            observation_schema_digest: digest(1),
            output_schema_digest: digest(2),
            state_schema_digest: digest(3),
            input_port_digest: digest(4),
            output_port_digest: digest(5),
            termination_port_digest: digest(6),
            owner_module: id("hepta.neuron"),
            persistence_class: CellPersistenceClassV1::Checkpointed,
            update_mode: CellUpdateModeV1::InferenceOnly,
            fallback_role: Some(CellRoleV1::Evaluator),
            objective_digest: digest(7),
            resource_budget_digest: digest(8),
            evaluation_profile_digest: digest(9),
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    #[test]
    fn role_profile_and_definition_have_stable_digests() {
        let capability = profile(CellRoleV1::Representation);
        let capability_digest = capability.content_digest().expect("profile");
        let definition = CellDefinitionV2 {
            cell_id: id("cell.representation.1"),
            generation: Generation::new(1).expect("generation"),
            scope_digest: digest(10),
            lineage_digest: digest(11),
            role: CellRoleV1::Representation,
            capability_profile: capability,
            parameter_bundle_digest: digest(12),
            state_schema_digest: digest(3),
            port_abi_digest: digest(13),
            owner_module: id("hepta.neuron"),
            objective_digest: digest(14),
            fallback_role: Some(CellRoleV1::Evaluator),
            evidence_owner: id("hepta.learning.eval"),
            authority: AuthorityPosture::DENY_ALL,
        };
        assert_eq!(
            definition.capability_digest().expect("capability"),
            capability_digest
        );
        assert_eq!(
            definition.content_digest().expect("definition"),
            definition.content_digest().expect("repeat")
        );
    }

    #[test]
    fn definition_rejects_role_or_owner_drift() {
        let capability = profile(CellRoleV1::Predictor);
        let mut definition = CellDefinitionV2 {
            cell_id: id("cell.predictor.1"),
            generation: Generation::new(1).expect("generation"),
            scope_digest: digest(10),
            lineage_digest: digest(11),
            role: CellRoleV1::Decision,
            capability_profile: capability,
            parameter_bundle_digest: digest(12),
            state_schema_digest: digest(3),
            port_abi_digest: digest(13),
            owner_module: id("hepta.neuron"),
            objective_digest: digest(14),
            fallback_role: Some(CellRoleV1::Evaluator),
            evidence_owner: id("hepta.learning.eval"),
            authority: AuthorityPosture::DENY_ALL,
        };
        assert_eq!(
            definition.validate(),
            Err(CellRoleContractErrorV1::RoleMismatch)
        );
        definition.role = CellRoleV1::Predictor;
        definition.owner_module = id("hepta.other");
        assert_eq!(
            definition.validate(),
            Err(CellRoleContractErrorV1::OwnerMismatch)
        );
    }

    #[test]
    fn receipt_rejects_invalid_confidence_bounds_and_zero_digest() {
        let mut receipt = CellStepReceiptV1 {
            cell_id: id("cell.decision.1"),
            generation: Generation::new(1).expect("generation"),
            scope_digest: digest(1),
            role: CellRoleV1::Decision,
            capability_digest: digest(2),
            input_frontier_digest: digest(3),
            state_predecessor_digest: digest(4),
            state_successor_digest: digest(5),
            output_digest: digest(6),
            uncertainty_ppm: PPM_MAX_V1 + 1,
            ood_ppm: 0,
            resource_receipt_digest: digest(7),
            evidence_digest: digest(8),
            status: CellStepStatusV1::Accepted,
            authority: AuthorityPosture::DENY_ALL,
        };
        assert_eq!(receipt.validate(), Err(CellRoleContractErrorV1::InvalidPpm));
        receipt.uncertainty_ppm = 0;
        receipt.output_digest = Digest32::ZERO;
        assert_eq!(
            receipt.validate(),
            Err(CellRoleContractErrorV1::EmptyDigest("output"))
        );
    }

    #[test]
    fn fallback_cannot_be_same_role() {
        let mut capability = profile(CellRoleV1::Decision);
        capability.fallback_role = Some(CellRoleV1::Decision);
        assert_eq!(
            capability.validate(),
            Err(CellRoleContractErrorV1::SelfFallback)
        );
    }
}
