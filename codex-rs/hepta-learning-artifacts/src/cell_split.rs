//! Cell-specific artifact inheritance and fenced publication.
//!
//! `CellSplitV1` describes which child bundles should exist.  This module is
//! the small owner-side seam that turns that description into independently
//! replayable child manifests and CAS receipts.  It deliberately accepts the
//! child payload digest and encoded size from a host; it never invents tensor
//! bytes or claims that a bundle was persisted merely because a digest exists.
//!
//! The transaction stages every child in memory, verifies every receipt and
//! appends the registry on a clone before replacing the caller's registry.
//! Consequently a registry conflict or one bad child cannot leave a partial
//! split.  Physical CAS creation, writer leases and signed host evidence remain
//! obligations of the caller and are represented by the fence and receipts.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error;
use std::fmt;
use std::io::Write;

use codex_hepta_types::CellBundleBindingV1;
use codex_hepta_types::CellSplitContractErrorV1;
use codex_hepta_types::CellSplitV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::ArtifactEvent;
use crate::ArtifactKind;
use crate::ArtifactManifest;
use crate::ArtifactRegistry;
use crate::ArtifactRegistryError;
use crate::ArtifactStorageError;
use crate::CreateOnlyArtifactFile;
use crate::RegistryHeadRequirementV1;
use crate::RegistryHeadWitnessReceipt;
use crate::RegistryHeadWitnessV1;
use crate::RegistrySnapshotReceipt;
use crate::StateChange;

pub const MAX_CELL_ARTIFACT_CHILDREN_V1: usize = 64;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CellArtifactPublicationStateV1 {
    Prepared,
    PayloadsDurable,
    RegistryCommitted,
    RegistryDurable,
    Acknowledged,
    Quarantined,
    RolledBack,
}

impl CellArtifactPublicationStateV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Prepared => 0,
            Self::PayloadsDurable => 1,
            Self::RegistryCommitted => 2,
            Self::RegistryDurable => 3,
            Self::Acknowledged => 4,
            Self::Quarantined => 5,
            Self::RolledBack => 6,
        }
    }
}

/// The manifest for one child parameter bundle.  `child_bundle_digest` is the
/// digest of bytes owned by the host CAS, not a digest of an invented payload.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellParameterBundleManifestV1 {
    pub artifact_id: StableId,
    pub cell_id: StableId,
    pub parent_artifact_id: StableId,
    pub generation: Generation,
    pub parent_bundle_digest: Digest32,
    pub child_bundle_digest: Digest32,
    pub scope_digest: Digest32,
    pub definition_digest: Digest32,
    pub lineage_digest: Digest32,
    pub objective_digest: Digest32,
    pub compatibility_digest: Digest32,
    pub inheritance_digest: Digest32,
    pub split_digest: Digest32,
    pub producer_id: StableId,
    pub encoded_size_bytes: u64,
    pub manifest_digest: Digest32,
}

impl CellParameterBundleManifestV1 {
    /// Build a child manifest from the validated semantic split.  The payload
    /// digest and encoded byte count must come from the artifact owner that
    /// actually materializes the bundle.
    pub fn from_split(
        split: &CellSplitV1,
        parent_artifact_id: StableId,
        producer_id: StableId,
        child_cell_id: &StableId,
        child_bundle_digest: Digest32,
        encoded_size_bytes: u64,
    ) -> Result<Self, CellArtifactOwnerErrorV1> {
        split.validate_plan()?;
        let split_digest = split.evaluation_subject_digest()?;
        let child = split
            .children
            .iter()
            .find(|value| &value.child_cell_id == child_cell_id)
            .ok_or_else(|| CellArtifactOwnerErrorV1::UnknownChild(child_cell_id.clone()))?;
        let binding = split
            .inheritance
            .children
            .iter()
            .find(|value| &value.child_cell_id == child_cell_id)
            .ok_or_else(|| CellArtifactOwnerErrorV1::UnknownChild(child_cell_id.clone()))?;
        if child_bundle_digest != child.child_bundle_digest || encoded_size_bytes == 0 {
            return Err(CellArtifactOwnerErrorV1::InvalidPayloadReceipt(
                child_cell_id.clone(),
            ));
        }
        let inheritance_digest = digest_binding(binding);
        let mut value = Self {
            artifact_id: child.child_cell_id.clone(),
            cell_id: child.child_cell_id.clone(),
            parent_artifact_id,
            generation: child.child_generation,
            parent_bundle_digest: split.parent_bundle_digest,
            child_bundle_digest,
            scope_digest: child.child_scope_digest,
            definition_digest: child.child_definition_digest,
            lineage_digest: child.lineage_digest,
            objective_digest: child.task_objective_digest,
            compatibility_digest: binding.compatibility_digest,
            inheritance_digest,
            split_digest,
            producer_id,
            encoded_size_bytes,
            manifest_digest: Digest32::ZERO,
        };
        value.manifest_digest = value.content_digest();
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), CellArtifactOwnerErrorV1> {
        for (label, digest) in [
            ("parent bundle", self.parent_bundle_digest),
            ("child bundle", self.child_bundle_digest),
            ("scope", self.scope_digest),
            ("definition", self.definition_digest),
            ("lineage", self.lineage_digest),
            ("objective", self.objective_digest),
            ("compatibility", self.compatibility_digest),
            ("inheritance", self.inheritance_digest),
            ("split", self.split_digest),
        ] {
            if digest.is_zero() {
                return Err(CellArtifactOwnerErrorV1::EmptyDigest(label));
            }
        }
        if self.encoded_size_bytes == 0 {
            return Err(CellArtifactOwnerErrorV1::InvalidPayloadReceipt(
                self.cell_id.clone(),
            ));
        }
        if self.artifact_id != self.cell_id || self.artifact_id == self.parent_artifact_id {
            return Err(CellArtifactOwnerErrorV1::ManifestBinding(
                self.cell_id.clone(),
            ));
        }
        if self.content_digest() != self.manifest_digest {
            return Err(CellArtifactOwnerErrorV1::ManifestDigestMismatch(
                self.cell_id.clone(),
            ));
        }
        Ok(())
    }

    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.learning.cell-parameter-bundle-manifest.v1".to_vec();
        for id in [
            &self.artifact_id,
            &self.cell_id,
            &self.parent_artifact_id,
            &self.producer_id,
        ] {
            push_id(&mut bytes, id);
        }
        bytes.extend_from_slice(&self.generation.get().to_be_bytes());
        for digest in [
            self.parent_bundle_digest,
            self.child_bundle_digest,
            self.scope_digest,
            self.definition_digest,
            self.lineage_digest,
            self.objective_digest,
            self.compatibility_digest,
            self.inheritance_digest,
            self.split_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&self.encoded_size_bytes.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }

    /// A compatibility projection into the existing V1 registry.  The generic
    /// registry requires a child objective to equal its predecessor objective;
    /// heterogeneous task objectives remain in the typed sidecar until that
    /// registry constraint is widened.
    #[must_use]
    pub fn as_registry_manifest(&self) -> ArtifactManifest {
        ArtifactManifest {
            artifact_id: self.artifact_id.clone(),
            kind: ArtifactKind::Parameters,
            generation: self.generation,
            predecessor_id: Some(self.parent_artifact_id.clone()),
            content_digest: self.child_bundle_digest,
            objective_digest: self.objective_digest,
            support_digest: self.lineage_digest,
            producer_id: self.producer_id.clone(),
            compatibility_digest: self.compatibility_digest,
            encoded_size_bytes: self.encoded_size_bytes,
        }
    }
}

/// Component-level evidence supplied by the materializer. It identifies the
/// exact base, organ adapter, cell adapter and head outputs used to assemble a
/// child bundle; the bytes themselves remain in the host CAS.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellParameterBundleMaterializationV1 {
    pub child_cell_id: StableId,
    pub base_digest: Digest32,
    pub organ_adapter_digest: Digest32,
    pub cell_adapter_digest: Digest32,
    pub head_digest: Digest32,
    pub output_bundle_digest: Digest32,
    pub encoded_size_bytes: u64,
    pub materialization_receipt_digest: Digest32,
}

impl CellParameterBundleMaterializationV1 {
    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.learning.cell-parameter-materialization.v1".to_vec();
        push_id(&mut bytes, &self.child_cell_id);
        for digest in [
            self.base_digest,
            self.organ_adapter_digest,
            self.cell_adapter_digest,
            self.head_digest,
            self.output_bundle_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&self.encoded_size_bytes.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }

    pub fn validate_against(
        &self,
        split: &CellSplitV1,
        manifest: &CellParameterBundleManifestV1,
    ) -> Result<(), CellArtifactOwnerErrorV1> {
        split.validate_plan()?;
        let binding = split
            .inheritance
            .children
            .iter()
            .find(|binding| binding.child_cell_id == self.child_cell_id)
            .ok_or_else(|| CellArtifactOwnerErrorV1::UnknownChild(self.child_cell_id.clone()))?;
        if self.child_cell_id != manifest.cell_id
            || self.base_digest != binding.base_digest
            || self.organ_adapter_digest != binding.organ_adapter_digest
            || self.cell_adapter_digest != binding.cell_adapter_digest
            || self.head_digest != binding.head_digest
            || self.output_bundle_digest != manifest.child_bundle_digest
            || self.encoded_size_bytes != manifest.encoded_size_bytes
            || self.materialization_receipt_digest != self.content_digest()
        {
            return Err(CellArtifactOwnerErrorV1::ManifestBinding(
                self.child_cell_id.clone(),
            ));
        }
        Ok(())
    }
}

/// Receipt from the host CAS.  A receipt is accepted only for the exact
/// operation fence, child digest and size named by the manifest.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellArtifactCasReceiptV1 {
    pub operation_id: StableId,
    pub child_artifact_id: StableId,
    pub payload_digest: Digest32,
    pub encoded_size_bytes: u64,
    pub predecessor_cas_head_digest: Digest32,
    pub fence_digest: Digest32,
    pub receipt_digest: Digest32,
}

impl CellArtifactCasReceiptV1 {
    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.learning.cell-artifact-cas-receipt.v1".to_vec();
        push_id(&mut bytes, &self.operation_id);
        push_id(&mut bytes, &self.child_artifact_id);
        for digest in [
            self.payload_digest,
            self.predecessor_cas_head_digest,
            self.fence_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&self.encoded_size_bytes.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }

    fn validate(&self) -> Result<(), CellArtifactOwnerErrorV1> {
        if self.payload_digest.is_zero()
            || self.fence_digest.is_zero()
            || self.encoded_size_bytes == 0
            || self.receipt_digest != self.content_digest()
        {
            return Err(CellArtifactOwnerErrorV1::InvalidPayloadReceipt(
                self.child_artifact_id.clone(),
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellArtifactRegistryReceiptV1 {
    pub operation_id: StableId,
    pub predecessor_head_digest: Digest32,
    pub head_digest: Digest32,
    pub child_event_digests: Vec<Digest32>,
    pub records: usize,
    pub receipt_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellArtifactPublicationReceiptV1 {
    pub operation_id: StableId,
    pub split_digest: Digest32,
    pub fence_digest: Digest32,
    pub registry: CellArtifactRegistryReceiptV1,
    pub cas_receipt_digests: Vec<Digest32>,
    pub rollback_predecessor_id: StableId,
    pub state: CellArtifactPublicationStateV1,
    pub receipt_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellArtifactOwnerErrorV1 {
    Contract(CellSplitContractErrorV1),
    EmptyDigest(&'static str),
    UnknownChild(StableId),
    ChildCount,
    DuplicateChild(StableId),
    ManifestBinding(StableId),
    ManifestDigestMismatch(StableId),
    ParentManifestMismatch,
    GenerationMismatch,
    InvalidPayloadReceipt(StableId),
    MissingPayloadReceipt(StableId),
    ReceiptOperationMismatch(StableId),
    ReceiptFenceMismatch(StableId),
    ReceiptPayloadMismatch(StableId),
    RegistryHeadMismatch,
    RegistryProjection(ArtifactRegistryError),
    Storage(ArtifactStorageError),
    DurabilityReceiptMismatch,
    Io(std::io::ErrorKind),
    InvalidState,
    InvalidRollback(StableId),
    SelfEvaluate(StableId),
}

impl fmt::Display for CellArtifactOwnerErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for CellArtifactOwnerErrorV1 {}

impl From<CellSplitContractErrorV1> for CellArtifactOwnerErrorV1 {
    fn from(error: CellSplitContractErrorV1) -> Self {
        Self::Contract(error)
    }
}

impl From<ArtifactRegistryError> for CellArtifactOwnerErrorV1 {
    fn from(error: ArtifactRegistryError) -> Self {
        Self::RegistryProjection(error)
    }
}

impl From<ArtifactStorageError> for CellArtifactOwnerErrorV1 {
    fn from(error: ArtifactStorageError) -> Self {
        Self::Storage(error)
    }
}

/// A fenced all-or-nothing artifact publication owner.  It has no signing or
/// filesystem authority; those are supplied by the host that produces the CAS
/// receipts.  Registry mutation happens only after every child receipt passes.
#[derive(Clone, Debug)]
pub struct CellArtifactPublicationV1 {
    operation_id: StableId,
    split_digest: Digest32,
    parent_artifact_id: StableId,
    parent_bundle_digest: Digest32,
    rollback_predecessor_id: StableId,
    expected_registry_head: Digest32,
    fence_digest: Digest32,
    children: Vec<CellParameterBundleManifestV1>,
    payload_receipts: BTreeMap<StableId, CellArtifactCasReceiptV1>,
    registry_receipt: Option<CellArtifactRegistryReceiptV1>,
    state: CellArtifactPublicationStateV1,
}

impl CellArtifactPublicationV1 {
    pub fn begin(
        operation_id: StableId,
        split: &CellSplitV1,
        parent: &ArtifactManifest,
        children: Vec<CellParameterBundleManifestV1>,
        expected_registry_head: Digest32,
    ) -> Result<Self, CellArtifactOwnerErrorV1> {
        split.validate_plan()?;
        let split_digest = split.evaluation_subject_digest()?;
        if parent.artifact_id
            != children
                .first()
                .map(|child| child.parent_artifact_id.clone())
                .unwrap_or_else(|| parent.artifact_id.clone())
        {
            return Err(CellArtifactOwnerErrorV1::ParentManifestMismatch);
        }
        if parent.kind != ArtifactKind::Parameters
            || parent.content_digest != split.parent_bundle_digest
            || parent.generation != split.predecessor_generation
        {
            return Err(CellArtifactOwnerErrorV1::ParentManifestMismatch);
        }
        if children.len() != split.children.len() || children.len() > MAX_CELL_ARTIFACT_CHILDREN_V1
        {
            return Err(CellArtifactOwnerErrorV1::ChildCount);
        }
        let expected_ids: BTreeSet<_> = split
            .children
            .iter()
            .map(|child| child.child_cell_id.clone())
            .collect();
        let mut seen = BTreeSet::new();
        for child in &children {
            child.validate()?;
            if child.split_digest != split_digest
                || child.parent_artifact_id != parent.artifact_id
                || child.parent_bundle_digest != parent.content_digest
                || child.generation != split.successor_generation
                || !expected_ids.contains(&child.cell_id)
                || !seen.insert(child.cell_id.clone())
            {
                return Err(CellArtifactOwnerErrorV1::ManifestBinding(
                    child.cell_id.clone(),
                ));
            }
        }
        if seen != expected_ids {
            return Err(CellArtifactOwnerErrorV1::ChildCount);
        }
        let fence_digest = digest_fence(&operation_id, split_digest, expected_registry_head);
        Ok(Self {
            operation_id,
            split_digest,
            parent_artifact_id: parent.artifact_id.clone(),
            parent_bundle_digest: parent.content_digest,
            rollback_predecessor_id: parent.artifact_id.clone(),
            expected_registry_head,
            fence_digest,
            children,
            payload_receipts: BTreeMap::new(),
            registry_receipt: None,
            state: CellArtifactPublicationStateV1::Prepared,
        })
    }

    #[must_use]
    pub const fn state(&self) -> CellArtifactPublicationStateV1 {
        self.state
    }

    #[must_use]
    pub const fn fence_digest(&self) -> Digest32 {
        self.fence_digest
    }

    #[must_use]
    pub fn children(&self) -> &[CellParameterBundleManifestV1] {
        &self.children
    }

    /// Persist the actual child bytes to a host-authorized create-only file.
    /// Receipt construction happens after `sync_all`; a caller cannot obtain
    /// a successful receipt for empty, wrong-sized or digest-drifted bytes.
    /// The host must sync the containing directory before publishing CURRENT.
    pub fn persist_payload(
        &self,
        child_artifact_id: &StableId,
        mut file: CreateOnlyArtifactFile,
        bytes: &[u8],
    ) -> Result<CellArtifactCasReceiptV1, CellArtifactOwnerErrorV1> {
        if self.state != CellArtifactPublicationStateV1::Prepared {
            return Err(CellArtifactOwnerErrorV1::InvalidState);
        }
        let child = self
            .children
            .iter()
            .find(|child| &child.artifact_id == child_artifact_id)
            .ok_or_else(|| CellArtifactOwnerErrorV1::UnknownChild(child_artifact_id.clone()))?;
        if bytes.len() as u64 != child.encoded_size_bytes
            || Digest32::of_bytes(bytes) != child.child_bundle_digest
        {
            return Err(CellArtifactOwnerErrorV1::ReceiptPayloadMismatch(
                child_artifact_id.clone(),
            ));
        }
        file.0
            .write_all(bytes)
            .map_err(|error| CellArtifactOwnerErrorV1::Io(error.kind()))?;
        file.0
            .sync_all()
            .map_err(|error| CellArtifactOwnerErrorV1::Io(error.kind()))?;
        let mut receipt = CellArtifactCasReceiptV1 {
            operation_id: self.operation_id.clone(),
            child_artifact_id: child_artifact_id.clone(),
            payload_digest: child.child_bundle_digest,
            encoded_size_bytes: child.encoded_size_bytes,
            predecessor_cas_head_digest: self.parent_bundle_digest,
            fence_digest: self.fence_digest,
            receipt_digest: Digest32::ZERO,
        };
        receipt.receipt_digest = receipt.content_digest();
        Ok(receipt)
    }

    /// Record all CAS receipts in one call.  The state transition is all or
    /// nothing: a malformed or missing child leaves the transaction Prepared.
    pub fn record_payloads_durable(
        &mut self,
        receipts: Vec<CellArtifactCasReceiptV1>,
    ) -> Result<(), CellArtifactOwnerErrorV1> {
        if self.state != CellArtifactPublicationStateV1::Prepared {
            return Err(CellArtifactOwnerErrorV1::InvalidState);
        }
        let expected: BTreeMap<_, _> = self
            .children
            .iter()
            .map(|child| (child.artifact_id.clone(), child))
            .collect();
        if receipts.len() != expected.len() {
            return Err(CellArtifactOwnerErrorV1::ChildCount);
        }
        let mut next = BTreeMap::new();
        for receipt in receipts {
            receipt.validate()?;
            let child = expected.get(&receipt.child_artifact_id).ok_or_else(|| {
                CellArtifactOwnerErrorV1::UnknownChild(receipt.child_artifact_id.clone())
            })?;
            if receipt.operation_id != self.operation_id {
                return Err(CellArtifactOwnerErrorV1::ReceiptOperationMismatch(
                    receipt.child_artifact_id,
                ));
            }
            if receipt.fence_digest != self.fence_digest {
                return Err(CellArtifactOwnerErrorV1::ReceiptFenceMismatch(
                    receipt.child_artifact_id,
                ));
            }
            if receipt.payload_digest != child.child_bundle_digest
                || receipt.encoded_size_bytes != child.encoded_size_bytes
                || receipt.predecessor_cas_head_digest != self.parent_bundle_digest
            {
                return Err(CellArtifactOwnerErrorV1::ReceiptPayloadMismatch(
                    receipt.child_artifact_id,
                ));
            }
            if next
                .insert(receipt.child_artifact_id.clone(), receipt)
                .is_some()
            {
                return Err(CellArtifactOwnerErrorV1::DuplicateChild(
                    child.artifact_id.clone(),
                ));
            }
        }
        if next.len() != expected.len() {
            return Err(CellArtifactOwnerErrorV1::ChildCount);
        }
        self.payload_receipts = next;
        self.state = CellArtifactPublicationStateV1::PayloadsDurable;
        Ok(())
    }

    /// Append child manifests to a cloned registry and replace the caller only
    /// after every event succeeds.  This is the in-memory equivalent of an
    /// atomic fenced registry commit; the host still must persist the snapshot
    /// and its independent current-head witness.
    pub fn commit_registry(
        &mut self,
        registry: &mut ArtifactRegistry,
    ) -> Result<CellArtifactRegistryReceiptV1, CellArtifactOwnerErrorV1> {
        if self.state != CellArtifactPublicationStateV1::PayloadsDurable {
            return Err(CellArtifactOwnerErrorV1::InvalidState);
        }
        if registry.snapshot().head_digest != self.expected_registry_head {
            return Err(CellArtifactOwnerErrorV1::RegistryHeadMismatch);
        }
        let parent = registry
            .manifest(&self.parent_artifact_id)
            .ok_or(CellArtifactOwnerErrorV1::ParentManifestMismatch)?;
        if parent.content_digest != self.parent_bundle_digest
            || !registry.is_eligible(&self.parent_artifact_id)
        {
            return Err(CellArtifactOwnerErrorV1::ParentManifestMismatch);
        }
        let registry_objective = parent.objective_digest;
        let mut staged = registry.clone();
        let mut event_receipts = Vec::with_capacity(self.children.len());
        for child in &self.children {
            let event_id = event_id(&self.operation_id, &child.artifact_id)?;
            let mut manifest = child.as_registry_manifest();
            // The compatibility index retains the parent's objective class;
            // the complete sidecar keeps the child's specialized task objective.
            manifest.objective_digest = registry_objective;
            let receipt = staged.append(ArtifactEvent::Register { event_id, manifest })?;
            event_receipts.push(receipt);
        }
        let head_digest = staged.snapshot().head_digest;
        let child_event_digests = event_receipts
            .iter()
            .map(|receipt| receipt.event_digest)
            .collect::<Vec<_>>();
        let receipt_digest = digest_registry_receipt(
            &self.operation_id,
            self.expected_registry_head,
            head_digest,
            &child_event_digests,
            staged.records().len(),
        );
        let result = CellArtifactRegistryReceiptV1 {
            operation_id: self.operation_id.clone(),
            predecessor_head_digest: self.expected_registry_head,
            head_digest,
            child_event_digests,
            records: staged.records().len(),
            receipt_digest,
        };
        *registry = staged;
        self.registry_receipt = Some(result.clone());
        self.state = CellArtifactPublicationStateV1::RegistryCommitted;
        Ok(result)
    }

    /// Confirm the exact immutable snapshot and current-head witness produced
    /// by the existing artifact storage/owner path before acknowledgement.
    /// Signing-key verification remains `LearningArtifactOwnerHost` work.
    pub fn record_registry_durable(
        &mut self,
        snapshot: RegistrySnapshotReceipt,
        witness: &RegistryHeadWitnessV1,
        requirement: &RegistryHeadRequirementV1,
        witness_receipt: RegistryHeadWitnessReceipt,
    ) -> Result<(), CellArtifactOwnerErrorV1> {
        if self.state != CellArtifactPublicationStateV1::RegistryCommitted {
            return Err(CellArtifactOwnerErrorV1::InvalidState);
        }
        let registry = self
            .registry_receipt
            .as_ref()
            .ok_or(CellArtifactOwnerErrorV1::InvalidState)?;
        let validated = crate::validate_registry_head_witness(witness, requirement)
            .map_err(|_| CellArtifactOwnerErrorV1::DurabilityReceiptMismatch)?;
        if snapshot.binding != self.fence_digest
            || snapshot.head_digest != registry.head_digest
            || snapshot.records != registry.records
            || snapshot.file_digest.is_zero()
            || witness.head_digest != registry.head_digest
            || witness.predecessor_head_digest != self.expected_registry_head
            || witness_receipt.binding != self.fence_digest
            || witness_receipt.witness_digest != validated.witness_digest
            || witness_receipt.file_digest.is_zero()
        {
            return Err(CellArtifactOwnerErrorV1::DurabilityReceiptMismatch);
        }
        self.state = CellArtifactPublicationStateV1::RegistryDurable;
        Ok(())
    }

    pub fn acknowledge(
        &mut self,
    ) -> Result<CellArtifactPublicationReceiptV1, CellArtifactOwnerErrorV1> {
        if self.state != CellArtifactPublicationStateV1::RegistryDurable {
            return Err(CellArtifactOwnerErrorV1::InvalidState);
        }
        let registry = self
            .registry_receipt
            .clone()
            .ok_or(CellArtifactOwnerErrorV1::InvalidState)?;
        let mut cas_receipt_digests = self
            .payload_receipts
            .values()
            .map(|receipt| receipt.receipt_digest)
            .collect::<Vec<_>>();
        cas_receipt_digests.sort_unstable();
        self.state = CellArtifactPublicationStateV1::Acknowledged;
        let receipt_digest = digest_publication_receipt(
            &self.operation_id,
            self.split_digest,
            self.fence_digest,
            &registry,
            &cas_receipt_digests,
            self.state,
        );
        Ok(CellArtifactPublicationReceiptV1 {
            operation_id: self.operation_id.clone(),
            split_digest: self.split_digest,
            fence_digest: self.fence_digest,
            registry,
            cas_receipt_digests,
            rollback_predecessor_id: self.rollback_predecessor_id.clone(),
            state: self.state,
            receipt_digest,
        })
    }

    /// Quarantine every child as one staged registry mutation.  The parent is
    /// intentionally preserved as rollback predecessor and is never silently
    /// revoked by this operation.
    pub fn quarantine_children(
        &mut self,
        registry: &mut ArtifactRegistry,
        evaluator_id: StableId,
        reason_digest: Digest32,
    ) -> Result<(), CellArtifactOwnerErrorV1> {
        if !matches!(
            self.state,
            CellArtifactPublicationStateV1::RegistryCommitted
                | CellArtifactPublicationStateV1::RegistryDurable
                | CellArtifactPublicationStateV1::Acknowledged
        ) {
            return Err(CellArtifactOwnerErrorV1::InvalidState);
        }
        if evaluator_id == self.operation_id || reason_digest.is_zero() {
            return Err(CellArtifactOwnerErrorV1::SelfEvaluate(
                self.operation_id.clone(),
            ));
        }
        let mut staged = registry.clone();
        for child in &self.children {
            let event = ArtifactEvent::Quarantine(StateChange {
                event_id: event_id(
                    &self.operation_id,
                    &format_id("quarantine", &child.artifact_id)?,
                )?,
                artifact_id: child.artifact_id.clone(),
                evaluator_id: evaluator_id.clone(),
                reason_digest,
            });
            staged.append(event)?;
        }
        *registry = staged;
        self.state = CellArtifactPublicationStateV1::Quarantined;
        Ok(())
    }

    /// Mark the transaction rolled back after all children have been
    /// quarantined.  A rollback receipt always points at the immutable parent.
    pub fn rollback(&mut self) -> Result<StableId, CellArtifactOwnerErrorV1> {
        if self.state != CellArtifactPublicationStateV1::Quarantined {
            return Err(CellArtifactOwnerErrorV1::InvalidRollback(
                self.rollback_predecessor_id.clone(),
            ));
        }
        self.state = CellArtifactPublicationStateV1::RolledBack;
        Ok(self.rollback_predecessor_id.clone())
    }
}

fn digest_binding(binding: &CellBundleBindingV1) -> Digest32 {
    let mut bytes = b"hepta.learning.cell-bundle-binding.v1".to_vec();
    push_id(&mut bytes, &binding.child_cell_id);
    for digest in [
        binding.base_digest,
        binding.organ_adapter_digest,
        binding.cell_adapter_digest,
        binding.head_digest,
        binding.compatibility_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn digest_fence(
    operation_id: &StableId,
    split_digest: Digest32,
    registry_head: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.learning.cell-artifact-fence.v1".to_vec();
    push_id(&mut bytes, operation_id);
    bytes.extend_from_slice(split_digest.as_array());
    bytes.extend_from_slice(registry_head.as_array());
    Digest32::of_bytes(&bytes)
}

fn digest_registry_receipt(
    operation_id: &StableId,
    predecessor: Digest32,
    head: Digest32,
    events: &[Digest32],
    records: usize,
) -> Digest32 {
    let mut bytes = b"hepta.learning.cell-artifact-registry-receipt.v1".to_vec();
    push_id(&mut bytes, operation_id);
    for digest in [predecessor, head] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&(records as u64).to_be_bytes());
    for digest in events {
        bytes.extend_from_slice(digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn digest_publication_receipt(
    operation_id: &StableId,
    split_digest: Digest32,
    fence_digest: Digest32,
    registry: &CellArtifactRegistryReceiptV1,
    cas: &[Digest32],
    state: CellArtifactPublicationStateV1,
) -> Digest32 {
    let mut bytes = b"hepta.learning.cell-artifact-publication-receipt.v1".to_vec();
    push_id(&mut bytes, operation_id);
    for digest in [split_digest, fence_digest, registry.receipt_digest] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.push(state.tag());
    for digest in cas {
        bytes.extend_from_slice(digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn event_id(
    operation_id: &StableId,
    child: &StableId,
) -> Result<StableId, CellArtifactOwnerErrorV1> {
    StableId::new(format!(
        "{}:register:{}",
        operation_id.as_str(),
        child.as_str()
    ))
    .map_err(|_| CellArtifactOwnerErrorV1::ManifestBinding(child.clone()))
}

fn format_id(prefix: &str, child: &StableId) -> Result<StableId, CellArtifactOwnerErrorV1> {
    StableId::new(format!("{prefix}:{}", child.as_str()))
        .map_err(|_| CellArtifactOwnerErrorV1::ManifestBinding(child.clone()))
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    let raw = id.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u32).to_be_bytes());
    bytes.extend_from_slice(raw);
}
