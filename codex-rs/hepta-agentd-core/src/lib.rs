//! Product-neutral Agentd composition kernel.
//!
//! This crate records which reviewed capability packs are attached to an
//! Agentd process. It owns no product fact, performs no I/O, invokes no model,
//! and grants no authority. Concrete domains remain behind capability-pack
//! crates; Agentd core depends only on stable Hepta identity types.

#![forbid(unsafe_code)]

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

pub const MAX_CAPABILITY_PACKS: usize = 128;
pub const MAX_CAPABILITIES_PER_PACK: usize = 64;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdCapabilityPackV1 {
    pub pack_id: StableId,
    pub owner_id: StableId,
    pub generation: Generation,
    pub implementation_digest: Digest32,
    pub capabilities: BTreeSet<StableId>,
}

impl AgentdCapabilityPackV1 {
    pub fn validate(&self) -> Result<(), AgentdCoreCompositionError> {
        if self.implementation_digest.is_zero() {
            return Err(AgentdCoreCompositionError::EmptyImplementationDigest);
        }
        if self.capabilities.is_empty() || self.capabilities.len() > MAX_CAPABILITIES_PER_PACK {
            return Err(AgentdCoreCompositionError::CapabilityBounds);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AttachedCapabilityPackV1 {
    pub pack_id: StableId,
    pub owner_id: StableId,
    pub generation: Generation,
    pub implementation_digest: Digest32,
    pub capabilities: Vec<StableId>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdCoreCompositionSnapshotV1 {
    pub packs: Vec<AttachedCapabilityPackV1>,
    pub digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AgentdCoreCompositionError {
    PackBounds,
    CapabilityBounds,
    EmptyImplementationDigest,
    DuplicatePack,
    DuplicateCapabilityOwner(StableId),
    UnknownPack,
    PackIdentityMismatch,
}

impl fmt::Display for AgentdCoreCompositionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for AgentdCoreCompositionError {}

/// In-memory product-neutral composition registry.
///
/// This registry is deliberately not a durable owner and never starts or stops
/// product code. A supervisor may persist its own exact generation snapshot and
/// attach concrete pack lifecycles only after independent admission.
#[derive(Clone, Debug, Default)]
pub struct AgentdCoreCompositionV1 {
    packs: BTreeMap<StableId, AgentdCapabilityPackV1>,
    capability_owners: BTreeMap<StableId, StableId>,
}

impl AgentdCoreCompositionV1 {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn attach(
        &mut self,
        pack: AgentdCapabilityPackV1,
    ) -> Result<AgentdCoreCompositionSnapshotV1, AgentdCoreCompositionError> {
        pack.validate()?;
        if self.packs.len() >= MAX_CAPABILITY_PACKS {
            return Err(AgentdCoreCompositionError::PackBounds);
        }
        if self.packs.contains_key(&pack.pack_id) {
            return Err(AgentdCoreCompositionError::DuplicatePack);
        }
        if let Some(capability) = pack
            .capabilities
            .iter()
            .find(|capability| self.capability_owners.contains_key(*capability))
        {
            return Err(AgentdCoreCompositionError::DuplicateCapabilityOwner(
                capability.clone(),
            ));
        }
        for capability in &pack.capabilities {
            self.capability_owners
                .insert(capability.clone(), pack.pack_id.clone());
        }
        self.packs.insert(pack.pack_id.clone(), pack);
        Ok(self.snapshot())
    }

    pub fn detach(
        &mut self,
        pack_id: &StableId,
        expected_generation: Generation,
        expected_implementation_digest: Digest32,
    ) -> Result<AgentdCoreCompositionSnapshotV1, AgentdCoreCompositionError> {
        let pack = self
            .packs
            .get(pack_id)
            .ok_or(AgentdCoreCompositionError::UnknownPack)?;
        if pack.generation != expected_generation
            || pack.implementation_digest != expected_implementation_digest
        {
            return Err(AgentdCoreCompositionError::PackIdentityMismatch);
        }
        let capabilities = pack.capabilities.clone();
        self.packs.remove(pack_id);
        for capability in capabilities {
            self.capability_owners.remove(&capability);
        }
        Ok(self.snapshot())
    }

    pub fn snapshot(&self) -> AgentdCoreCompositionSnapshotV1 {
        let packs = self
            .packs
            .values()
            .map(|pack| AttachedCapabilityPackV1 {
                pack_id: pack.pack_id.clone(),
                owner_id: pack.owner_id.clone(),
                generation: pack.generation,
                implementation_digest: pack.implementation_digest,
                capabilities: pack.capabilities.iter().cloned().collect(),
            })
            .collect::<Vec<_>>();
        let mut bytes = Vec::new();
        bytes.extend_from_slice(b"hepta.agentd-core-composition.v1");
        bytes.extend_from_slice(&(packs.len() as u32).to_be_bytes());
        for pack in &packs {
            push_text(&mut bytes, pack.pack_id.as_str());
            push_text(&mut bytes, pack.owner_id.as_str());
            bytes.extend_from_slice(&pack.generation.get().to_be_bytes());
            bytes.extend_from_slice(pack.implementation_digest.as_array());
            bytes.extend_from_slice(&(pack.capabilities.len() as u32).to_be_bytes());
            for capability in &pack.capabilities {
                push_text(&mut bytes, capability.as_str());
            }
        }
        AgentdCoreCompositionSnapshotV1 {
            packs,
            digest: Digest32::of_bytes(&bytes),
        }
    }
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&(value.len() as u32).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("stable id")
    }

    fn pack(pack_id: &str, generation: u64, capability: &str) -> AgentdCapabilityPackV1 {
        AgentdCapabilityPackV1 {
            pack_id: id(pack_id),
            owner_id: id("agent-runtime"),
            generation: Generation::new(generation).expect("generation"),
            implementation_digest: Digest32::of_bytes(pack_id.as_bytes()),
            capabilities: [id(capability)].into_iter().collect(),
        }
    }

    #[test]
    fn snapshot_is_independent_of_attach_order() {
        let mut left = AgentdCoreCompositionV1::new();
        left.attach(pack("pack.a", 1, "capability.a")).expect("a");
        let left = left.attach(pack("pack.b", 1, "capability.b")).expect("b");

        let mut right = AgentdCoreCompositionV1::new();
        right.attach(pack("pack.b", 1, "capability.b")).expect("b");
        let right = right.attach(pack("pack.a", 1, "capability.a")).expect("a");
        assert_eq!(left, right);
    }

    #[test]
    fn one_capability_has_one_pack_owner() {
        let mut registry = AgentdCoreCompositionV1::new();
        registry
            .attach(pack("pack.a", 1, "capability.shared"))
            .expect("first owner");
        assert_eq!(
            registry.attach(pack("pack.b", 1, "capability.shared")),
            Err(AgentdCoreCompositionError::DuplicateCapabilityOwner(id(
                "capability.shared"
            )))
        );
    }

    #[test]
    fn detach_requires_exact_generation_and_implementation() {
        let mut registry = AgentdCoreCompositionV1::new();
        let descriptor = pack("pack.a", 7, "capability.a");
        registry.attach(descriptor.clone()).expect("attach");
        assert_eq!(
            registry.detach(
                &descriptor.pack_id,
                Generation::new(8).expect("generation"),
                descriptor.implementation_digest,
            ),
            Err(AgentdCoreCompositionError::PackIdentityMismatch)
        );
        let snapshot = registry
            .detach(
                &descriptor.pack_id,
                descriptor.generation,
                descriptor.implementation_digest,
            )
            .expect("exact detach");
        assert!(snapshot.packs.is_empty());
    }

    #[test]
    fn empty_or_zero_identity_pack_is_rejected() {
        let mut descriptor = pack("pack.a", 1, "capability.a");
        descriptor.capabilities.clear();
        assert_eq!(
            descriptor.validate(),
            Err(AgentdCoreCompositionError::CapabilityBounds)
        );
        descriptor.capabilities.insert(id("capability.a"));
        descriptor.implementation_digest = Digest32::ZERO;
        assert_eq!(
            descriptor.validate(),
            Err(AgentdCoreCompositionError::EmptyImplementationDigest)
        );
    }
}
