use codex_hepta_types::CellParentDispositionV1;
use codex_hepta_types::CellSplitV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::CnsOrganHostV1;
use crate::CnsRouteV1;

use super::cell_split_route::CellSplitRouteErrorV1;
use super::cell_split_route_digest::cns_route_digest_v1;

/// A replayable fence observation that the route owner can persist beside the
/// split tombstone. The controller computes it only after successful CNS
/// cutover; persistence and restart recovery remain an external owner duty.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitRouteFenceReceiptV1 {
    pub split_id: StableId,
    pub parent_route_digest: Digest32,
    pub split_subject_digest: Digest32,
    pub predecessor_generation: Generation,
    pub successor_generation: Generation,
    pub parent_scope_digest: Digest32,
    pub tombstone_digest: Digest32,
    pub fence_digest: Digest32,
}

/// Read-only replay result used by a process that has reopened the CNS
/// registry after a restart.  This is a structural verification receipt: it
/// proves that the persisted successor generation still excludes the
/// predecessor route and carries the same tombstone-bound fence.  It does not
/// claim that a host reboot, power loss, or external observer actually ran;
/// those facts remain owned by the target-host evidence adapter.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitRouteRestartReplayReceiptV1 {
    pub split_id: StableId,
    pub persisted_generation: Generation,
    pub predecessor_route_digest: Digest32,
    pub fence_digest: Digest32,
    pub tombstone_digest: Digest32,
    pub predecessor_route_rejected: bool,
    pub parent_identity_absent: bool,
    pub replay_digest: Digest32,
}

impl CellSplitRouteFenceReceiptV1 {
    pub(crate) fn new(
        split: &CellSplitV1,
        parent_route: &CnsRouteV1,
    ) -> Result<Self, CellSplitRouteErrorV1> {
        let parent_route_digest = cns_route_digest_v1(parent_route);
        let split_subject_digest = split.evaluation_subject_digest()?;
        let mut bytes = b"hepta.cns.cell-route-fence.v1\0".to_vec();
        push_id(&mut bytes, &split.split_id);
        bytes.extend_from_slice(parent_route_digest.as_array());
        bytes.extend_from_slice(&split.predecessor_generation.get().to_be_bytes());
        bytes.extend_from_slice(&split.successor_generation.get().to_be_bytes());
        bytes.extend_from_slice(split.parent_scope_digest.as_array());
        bytes.extend_from_slice(split.retirement.tombstone_digest.as_array());
        bytes.extend_from_slice(split_subject_digest.as_array());
        Ok(Self {
            split_id: split.split_id.clone(),
            parent_route_digest,
            split_subject_digest,
            predecessor_generation: split.predecessor_generation,
            successor_generation: split.successor_generation,
            parent_scope_digest: split.parent_scope_digest,
            tombstone_digest: split.retirement.tombstone_digest,
            fence_digest: Digest32::of_bytes(&bytes),
        })
    }

    /// Verify a persisted fence against the same split and predecessor route
    /// during recovery. This is a pure check; the caller still owns durable
    /// storage and must keep the parent tombstone fenced across restart.
    pub fn verify(
        &self,
        split: &CellSplitV1,
        parent_route: &CnsRouteV1,
    ) -> Result<(), CellSplitRouteErrorV1> {
        split.validate_plan()?;
        if *self != Self::new(split, parent_route)? {
            return Err(CellSplitRouteErrorV1::RouteFenceMismatch);
        }
        Ok(())
    }

    /// Verify the route portion of a clean-process replay.  The successor
    /// host is supplied by the durable CNS owner after reopening its
    /// registry.  No route is dispatched here and no hardware/restart claim
    /// is manufactured; the checks are limited to persisted generation,
    /// route-fence and tombstone invariants.
    pub fn verify_after_restart(
        &self,
        split: &CellSplitV1,
        predecessor_route: &CnsRouteV1,
        successor: &CnsOrganHostV1,
    ) -> Result<CellSplitRouteRestartReplayReceiptV1, CellSplitRouteErrorV1> {
        split.validate_plan()?;
        if split.retirement.disposition != CellParentDispositionV1::Retire {
            return Err(CellSplitRouteErrorV1::RestartReplayRequiresRetire);
        }
        self.verify(split, predecessor_route)?;
        if successor.generation() != split.successor_generation
            || predecessor_route.generation != split.predecessor_generation
            || successor.cns != predecessor_route.cns
        {
            return Err(CellSplitRouteErrorV1::RestartGeneration);
        }
        if self.tombstone_digest != split.retirement.tombstone_digest
            || self.tombstone_digest.is_zero()
        {
            return Err(CellSplitRouteErrorV1::TombstoneMismatch);
        }

        // A retired parent must be absent from both the reopened route table
        // and the status projection.  Comparing the complete route also
        // catches an old generation accidentally being reinserted under the
        // same source/port key.
        let parent_identity_absent = !successor
            .routes
            .keys()
            .any(|(organ, _)| organ == &split.organ_id)
            && !successor
                .statuses()
                .iter()
                .any(|status| status.id.as_str() == split.organ_id.as_str());
        if !parent_identity_absent {
            return Err(CellSplitRouteErrorV1::ParentRouteResurrected);
        }

        // The route is rejected by the reopened registry before any handler
        // can run: there is no source/port entry for the retired parent and
        // the route itself still carries the predecessor generation.
        let predecessor_route_rejected = !successor.routes.contains_key(&(
            predecessor_route.source.organ.clone(),
            predecessor_route.output_port,
        ));
        if !predecessor_route_rejected {
            return Err(CellSplitRouteErrorV1::ParentRouteResurrected);
        }

        let mut bytes = b"hepta.cns.cell-route-restart-replay.v1\0".to_vec();
        bytes.extend_from_slice(self.split_id.as_str().as_bytes());
        bytes.extend_from_slice(&split.predecessor_generation.get().to_be_bytes());
        bytes.extend_from_slice(&split.successor_generation.get().to_be_bytes());
        bytes.extend_from_slice(cns_route_digest_v1(predecessor_route).as_array());
        bytes.extend_from_slice(self.fence_digest.as_array());
        bytes.extend_from_slice(self.tombstone_digest.as_array());
        bytes.push(u8::from(predecessor_route_rejected));
        bytes.push(u8::from(parent_identity_absent));
        Ok(CellSplitRouteRestartReplayReceiptV1 {
            split_id: self.split_id.clone(),
            persisted_generation: successor.generation(),
            predecessor_route_digest: cns_route_digest_v1(predecessor_route),
            fence_digest: self.fence_digest,
            tombstone_digest: self.tombstone_digest,
            predecessor_route_rejected,
            parent_identity_absent,
            replay_digest: Digest32::of_bytes(&bytes),
        })
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u64).to_be_bytes());
    bytes.extend_from_slice(raw);
}
