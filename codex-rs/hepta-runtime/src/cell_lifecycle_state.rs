//! Complete, quiescent state snapshots for the existing lifecycle owner.
//! The V2 binding checks actual supplied bytes; it grants no custody, transform
//! quality, publication or FinalUse authority. The original observer and anchor
//! remain mandatory. V1 journals retain their original replay semantics.

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::RuntimeCellLifecycleError as Error;
use crate::RuntimeCellLifecyclePlanV1;

const MAX_STATE_BYTES: u64 = 64 * 1024 * 1024 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u8)]
pub enum RuntimeCellStateRoleV2 {
    Parameters,
    Optimizer,
    RandomGenerator,
    Sampler,
    PrivateState,
    SourceReferences,
    MemoryReferences,
    Routing,
    RequestLedger,
    EffectLedger,
}

impl RuntimeCellStateRoleV2 {
    /// Canonical roster. An inapplicable component still requires an explicit
    /// schema-bound absence record; omission never means an empty optimizer.
    pub const ALL: [Self; 10] = [
        Self::Parameters, Self::Optimizer, Self::RandomGenerator, Self::Sampler,
        Self::PrivateState, Self::SourceReferences, Self::MemoryReferences,
        Self::Routing, Self::RequestLedger, Self::EffectLedger,
    ];
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeCellStateComponentV2 {
    pub role: RuntimeCellStateRoleV2,
    pub owner_id: StableId,
    pub owner_checkpoint: Digest32,
    pub schema: Digest32,
    pub content_digest: Digest32,
    pub encoded_bytes: u64,
}

/// Each component's schema covers the complete, ordered partition set. The
/// authenticating observer must check its semantic completeness and the current
/// owner checkpoint, including retained request/effect identities and outcomes.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeCellStateManifestV2 {
    pub agent_id: StableId,
    pub principal_scope: Digest32,
    pub cells: Vec<StableId>,
    pub generation: Generation,
    pub writer_id: StableId,
    pub writer_fence: u64,
    pub topology: Digest32,
    pub bundle: Digest32,
    pub source_frontier: Digest32,
    pub inflight_requests: u32,
    pub unknown_effects: u32,
    pub components: Vec<RuntimeCellStateComponentV2>,
}

impl RuntimeCellStateManifestV2 {
    pub fn state_root(&self) -> Result<Digest32, Error> {
        if self.cells.len() > 64 || self.cells.windows(2).any(|pair| pair[0] >= pair[1])
            || self.components.len() != RuntimeCellStateRoleV2::ALL.len() || self.writer_fence == 0
        {
            return Err(Error::InvalidPlan);
        }
        let mut bytes = b"hepta.runtime.cell-complete-state.v2\0".to_vec();
        for id in [&self.agent_id, &self.writer_id] { push_id(&mut bytes, id); }
        for digest in [self.principal_scope, self.topology, self.bundle, self.source_frontier] {
            if digest.is_zero() { return Err(Error::InvalidPlan); }
            bytes.extend_from_slice(digest.as_array());
        }
        for number in [self.generation.get(), self.writer_fence, u64::from(self.inflight_requests), u64::from(self.unknown_effects)] {
            bytes.extend_from_slice(&number.to_be_bytes());
        }
        bytes.extend_from_slice(&(self.cells.len() as u32).to_be_bytes());
        for cell in &self.cells { push_id(&mut bytes, cell); }
        let mut total = 0_u64;
        for (component, role) in self.components.iter().zip(RuntimeCellStateRoleV2::ALL) {
            if component.role != role || component.encoded_bytes == 0 {
                return Err(Error::InvalidPlan);
            }
            total = total.checked_add(component.encoded_bytes).ok_or(Error::Capacity)?;
            if total > MAX_STATE_BYTES { return Err(Error::Capacity); }
            if role == RuntimeCellStateRoleV2::PrivateState && component.owner_id != self.writer_id {
                return Err(Error::ScopeMismatch);
            }
            bytes.push(role as u8);
            push_id(&mut bytes, &component.owner_id);
            for digest in [component.owner_checkpoint, component.schema, component.content_digest] {
                if digest.is_zero() { return Err(Error::InvalidPlan); }
                bytes.extend_from_slice(digest.as_array());
            }
            bytes.extend_from_slice(&component.encoded_bytes.to_be_bytes());
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

/// Immutable borrows keep the supplied manifests and bytes pinned for this
/// binding. Storage custody and physical transfer still belong to their owners.
#[derive(Debug)]
pub struct RuntimeCellVerifiedStateV2<'a> {
    manifest: &'a RuntimeCellStateManifestV2,
    contents: &'a [&'a [u8]],
    maximum_bytes: u64,
    root: Digest32,
}

impl<'a> RuntimeCellVerifiedStateV2<'a> {
    pub fn verify(
        manifest: &'a RuntimeCellStateManifestV2,
        contents: &'a [&'a [u8]],
        maximum_bytes: u64,
    ) -> Result<Self, Error> {
        let verified = Self { manifest, contents, maximum_bytes, root: manifest.state_root()? };
        verified.revalidate()?;
        Ok(verified)
    }

    pub fn state_root(&self) -> Digest32 { self.root }
    pub fn manifest(&self) -> &RuntimeCellStateManifestV2 { self.manifest }

    fn revalidate(&self) -> Result<(), Error> {
        if self.maximum_bytes == 0 || self.maximum_bytes > MAX_STATE_BYTES
            || self.contents.len() != self.manifest.components.len()
        { return Err(Error::Capacity); }
        let mut total = 0_u64;
        for (component, bytes) in self.manifest.components.iter().zip(self.contents) {
            total = total.checked_add(component.encoded_bytes).ok_or(Error::Capacity)?;
            if total > self.maximum_bytes { return Err(Error::Capacity); }
            if bytes.len() as u64 != component.encoded_bytes || Digest32::of_bytes(bytes) != component.content_digest {
                return Err(Error::InvalidObservation);
            }
        }
        if self.manifest.state_root()? != self.root { return Err(Error::InvalidPlan); }
        Ok(())
    }
}

/// Bind this digest as the existing WriterHandoffPlanV1 migration_digest. It
/// commits the two complete snapshots and the frozen transformation/qualification
/// references; nonzero references do not authenticate a migration's quality.
pub fn runtime_cell_state_transfer_digest_v2(
    predecessor: &RuntimeCellVerifiedStateV2<'_>,
    successor: &RuntimeCellVerifiedStateV2<'_>,
    transform: Digest32,
    qualification: Digest32,
) -> Result<Digest32, Error> {
    if transform.is_zero() || qualification.is_zero() { return Err(Error::InvalidPlan); }
    predecessor.revalidate()?;
    successor.revalidate()?;
    Ok(Digest32::of_parts(&[
        b"hepta.runtime.cell-state-transfer.v2\0", predecessor.root.as_array(),
        successor.root.as_array(), transform.as_array(), qualification.as_array(),
    ]))
}

/// An opt-in complete-state profile over the same seven-stage lifecycle journal.
/// It intentionally requires a quiescent source: moving live or UNKNOWN work
/// needs its original owner's reconciliation, not a relabelled snapshot.
/// Callers must keep using these V2 entry points for each stage. The underlying
/// V1 API and its stored event format retain their original compatibility rules;
/// they do not independently require or reload this profile's material bytes.
#[derive(Debug)]
pub struct RuntimeCellLifecyclePlanV2<'a> {
    pub(crate) plan: &'a RuntimeCellLifecyclePlanV1,
    predecessor: &'a RuntimeCellVerifiedStateV2<'a>,
    successor: &'a RuntimeCellVerifiedStateV2<'a>,
    transform: Digest32,
    qualification: Digest32,
}

impl<'a> RuntimeCellLifecyclePlanV2<'a> {
    pub fn new(
        plan: &'a RuntimeCellLifecyclePlanV1,
        predecessor: &'a RuntimeCellVerifiedStateV2<'a>,
        successor: &'a RuntimeCellVerifiedStateV2<'a>,
        transform: Digest32,
        qualification: Digest32,
    ) -> Result<Self, Error> {
        let bound = Self { plan, predecessor, successor, transform, qualification };
        bound.validate()?;
        Ok(bound)
    }

    pub fn plan_digest(&self) -> Result<Digest32, Error> { self.plan.digest() }

    pub(crate) fn validate_observed_bundle(&self, observation: &crate::RuntimeCellLifecycleObservationV1) -> Result<(), Error> {
        let requested = observation.stage.code();
        let stage = if observation.outcome == crate::RuntimeCellLifecycleNativeOutcomeV1::Applied {
            requested
        } else {
            requested.saturating_sub(1)
        };
        let expected = if stage >= crate::RuntimeCellLifecycleStageV1::TransferState.code() {
            self.successor.manifest.bundle
        } else {
            self.predecessor.manifest.bundle
        };
        if observation.bundle != expected.to_string() { return Err(Error::InvalidObservation); }
        Ok(())
    }

    pub(crate) fn validate(&self) -> Result<(), Error> {
        self.plan.digest()?;
        let before = self.predecessor.manifest;
        let after = self.successor.manifest;
        if [before, after].iter().any(|state| state.inflight_requests != 0 || state.unknown_effects != 0) {
            return Err(Error::ReconciliationRequired);
        }
        for state in [before, after] {
            if state.agent_id != self.plan.agent_id || state.principal_scope != self.plan.principal_scope {
                return Err(Error::ScopeMismatch);
            }
        }
        if before.cells != self.plan.predecessors || after.cells != self.plan.successors
            || before.generation != self.plan.predecessor_generation || after.generation != self.plan.successor_generation
            || before.writer_id != self.plan.handoff.from_owner || after.writer_id != self.plan.handoff.to_owner
            || before.writer_fence != self.plan.handoff.predecessor_writer_fence
            || after.writer_fence != self.plan.handoff.successor_writer_fence
            || before.topology != self.plan.predecessor_topology || after.topology != self.plan.successor_topology
            || before.source_frontier != after.source_frontier || after.bundle != self.plan.successor_bundle
            || self.predecessor.root != self.plan.predecessor_state_root || self.successor.root != self.plan.successor_state_root
        { return Err(Error::InvalidPlan); }
        // Model/topology restoration cannot roll back or move the external
        // effect owner. Preserve its exact ledger bytes and owner checkpoint.
        if before.components.last() != after.components.last() { return Err(Error::InvalidObservation); }
        let transfer = runtime_cell_state_transfer_digest_v2(
            self.predecessor, self.successor, self.transform, self.qualification,
        )?;
        if transfer != self.plan.handoff.migration_digest { return Err(Error::InvalidPlan); }
        Ok(())
    }
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    bytes.extend_from_slice(&(id.as_str().len() as u32).to_be_bytes());
    bytes.extend_from_slice(id.as_str().as_bytes());
}
