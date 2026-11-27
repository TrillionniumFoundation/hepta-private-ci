//! Delivery bindings to an existing external resource owner.
//!
//! These value constructors are a trusted A05 resolver seam, not authentication
//! of user-supplied IDs or an implementation of kernel capabilities. The pinned
//! owner supplies resource identity and lifetime; this module creates no host
//! ResourceDomain, budget state, persistent ledger, or alternate scheduler.
//! The executor must recheck real grant epochs, ancestors, leases and revision
//! under that owner's mutation lock before publishing any effect.

use alloc::sync::Arc;
use alloc::vec::Vec;
use core::any::Any;

use crate::{
    DeliveryError, DeliveryId, ManagementGrantSnapshot, PublisherId, RequestBinding,
    ResourceDomainId, ResourceError, StableObjectId, CPU_PERIOD_NS, MAX_RESOURCE_DEPTH,
};

/// A strong lifetime pin to the actual resource owner selected by trusted code.
/// Rewrapping the same Arc preserves instance identity; equal public IDs alone
/// do not make two separately allocated owners the same target.
#[derive(Clone)]
pub struct NativeTarget {
    owner: Arc<dyn Any + Send + Sync>,
    id: ResourceDomainId,
    stable_object_id: StableObjectId,
}

impl NativeTarget {
    /// Bind an already resolved owner. This does not prove that the supplied
    /// IDs were assigned by a kernel, or grant any rights to operate on it.
    pub fn from_owner<T: Any + Send + Sync>(
        owner: Arc<T>,
        id: ResourceDomainId,
        stable_object_id: StableObjectId,
    ) -> Result<Self, ResourceError> {
        if !id.is_nonzero() || !stable_object_id.is_nonzero() {
            return Err(ResourceError::InvalidIdentity);
        }
        Ok(Self {
            owner,
            id,
            stable_object_id,
        })
    }

    pub const fn id(&self) -> ResourceDomainId {
        self.id
    }

    pub const fn stable_object_id(&self) -> StableObjectId {
        self.stable_object_id
    }

    pub(crate) fn same_instance(&self, other: &Self) -> bool {
        Arc::ptr_eq(&self.owner, &other.owner)
    }

    pub(crate) fn owner_as<T: Any>(&self) -> Option<&T> {
        self.owner.as_ref().downcast_ref()
    }
}

/// Borrowed context from the exact native request stored in a live D slot.
/// The core constructs it only after validating the token and owner type.
/// Values still require admission checks under the original owner's lock;
/// an epoch snapshot is not proof that the authority is currently live.
pub struct NativeExecution<'a, T> {
    owner: &'a T,
    id: DeliveryId,
    binding: RequestBinding,
    ancestor_epochs: &'a [u64],
    management_snapshot: Option<&'a ManagementGrantSnapshot>,
}

impl<'a, T> NativeExecution<'a, T> {
    pub(crate) fn new(
        owner: &'a T,
        id: DeliveryId,
        binding: RequestBinding,
        ancestor_epochs: &'a [u64],
        management_snapshot: Option<&'a ManagementGrantSnapshot>,
    ) -> Self {
        Self {
            owner,
            id,
            binding,
            ancestor_epochs,
            management_snapshot,
        }
    }

    /// The original allocation pinned by NativeTarget, never a re-resolved alias.
    pub fn owner(&self) -> &'a T {
        self.owner
    }

    pub const fn id(&self) -> DeliveryId {
        self.id
    }

    pub const fn binding(&self) -> RequestBinding {
        self.binding
    }

    /// Issuance-time snapshot in immediate-parent to root order.
    pub fn ancestor_epochs(&self) -> &'a [u64] {
        self.ancestor_epochs
    }

    /// Optional saved management delegation. The real owner must check this
    /// against its canonical state under the same lock as budget admission.
    pub fn management_snapshot(&self) -> Option<&'a ManagementGrantSnapshot> {
        self.management_snapshot
    }
}

/// Immutable authorization snapshot from the external owner's trusted resolver.
/// Its values are compared on D replay, not treated as proof of current rights.
#[derive(Clone)]
pub struct NativeGrant {
    target: NativeTarget,
    principal: PublisherId,
    epoch: u64,
    ancestor_epochs: Vec<u64>,
    management_snapshot: Option<ManagementGrantSnapshot>,
}

impl NativeGrant {
    /// Ancestors use the same immediate-parent to root order as host grants.
    /// Real admission must compare this snapshot with the original owner.
    pub fn from_owner(
        target: NativeTarget,
        publisher: PublisherId,
        epoch: u64,
        ancestor_epochs: Vec<u64>,
    ) -> Result<Self, ResourceError> {
        if !publisher.is_nonzero() || epoch == 0 || ancestor_epochs.contains(&0) {
            return Err(ResourceError::InvalidIdentity);
        }
        if ancestor_epochs.len() >= MAX_RESOURCE_DEPTH {
            return Err(ResourceError::Exhausted);
        }
        Ok(Self {
            target,
            principal: publisher,
            epoch,
            ancestor_epochs,
            management_snapshot: None,
        })
    }

    /// Bind a saved delegation to the original resource owner. This is a
    /// value/lifetime seam; lease, liveness and cap-envelope admission remain
    /// the actual owner's responsibility via ManagementGrantState::check.
    pub fn from_management(
        target: NativeTarget,
        snapshot: ManagementGrantSnapshot,
        ancestor_epochs: Vec<u64>,
    ) -> Result<Self, ResourceError> {
        if snapshot.target() != target.id()
            || snapshot.stable_object_id() != target.stable_object_id()
        {
            return Err(ResourceError::InvalidIdentity);
        }
        let mut grant = Self::from_owner(
            target,
            snapshot.publisher(),
            snapshot.epoch(),
            ancestor_epochs,
        )?;
        grant.management_snapshot = Some(snapshot);
        Ok(grant)
    }

    pub const fn management_snapshot(&self) -> Option<&ManagementGrantSnapshot> {
        self.management_snapshot.as_ref()
    }

    pub const fn principal(&self) -> PublisherId {
        self.principal
    }

    pub const fn epoch(&self) -> u64 {
        self.epoch
    }

    pub(crate) fn target(&self) -> &NativeTarget {
        &self.target
    }

    pub(crate) fn ancestor_epochs(&self) -> &[u64] {
        &self.ancestor_epochs
    }
}

/// Canonical InstallBudget delivery bound to an external owner's identity.
/// Callers may change public fixture fields before reservation; the reservation
/// path validates them again and snapshots the complete immutable binding.
#[derive(Clone)]
pub struct NativeDeliveryRequest {
    pub sequence: u64,
    grant: NativeGrant,
    pub expected_revision: u64,
    pub period_ns: u64,
    pub cap_ns: u64,
    pub payload_digest: [u8; 32],
    wire_target_slot: u64,
    wire_target_generation: u64,
}

impl NativeDeliveryRequest {
    /// Build only after transport decoding and trusted handle/owner resolution.
    /// Structural rejection does not reserve a D or establish authority.
    pub fn from_wire(
        sequence: u64,
        grant: NativeGrant,
        expected_revision: u64,
        cap_ns: u64,
        target_slot: u64,
        target_generation: u64,
    ) -> Result<Self, DeliveryError> {
        if sequence == 0 || sequence == u64::MAX {
            return Err(DeliveryError::InvalidSequence);
        }
        if expected_revision == 0
            || expected_revision == u64::MAX
            || cap_ns > CPU_PERIOD_NS
            || target_slot == 0
            || target_generation == 0
        {
            return Err(DeliveryError::InvalidRequest);
        }
        Ok(Self {
            sequence,
            grant,
            expected_revision,
            period_ns: CPU_PERIOD_NS,
            cap_ns,
            payload_digest: [0; 32],
            wire_target_slot: target_slot,
            wire_target_generation: target_generation,
        })
    }

    pub fn with_payload_digest(mut self, payload_digest: [u8; 32]) -> Self {
        self.payload_digest = payload_digest;
        self
    }

    pub fn binding(&self) -> RequestBinding {
        RequestBinding {
            sequence: self.sequence,
            publisher: self.grant.principal,
            target: self.grant.target.id(),
            stable_object_id: self.grant.target.stable_object_id(),
            wire_target_slot: self.wire_target_slot,
            wire_target_generation: self.wire_target_generation,
            expected_revision: self.expected_revision,
            period_ns: self.period_ns,
            cap_ns: self.cap_ns,
            grant_epoch: self.grant.epoch,
            payload_digest: self.payload_digest,
        }
    }

    pub(crate) fn grant(&self) -> &NativeGrant {
        &self.grant
    }

    pub(crate) const fn wire_target_slot(&self) -> u64 {
        self.wire_target_slot
    }

    pub(crate) const fn wire_target_generation(&self) -> u64 {
        self.wire_target_generation
    }
}
