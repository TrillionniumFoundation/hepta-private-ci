//! Fenced multi-child state migration owner.
//!
//! `CellStateSplitPlanV1` remains a pure projection.  This module adds the
//! owner-side transaction around it: the parent anchor must already be an
//! acknowledged journal checkpoint, every child payload must be written and
//! receipt-checked, and only then may a host acknowledge the batch.  The
//! module does not own paths, writer leases or a multi-file filesystem commit;
//! those facts are represented by the host-supplied receipts and batch fence.

use std::collections::BTreeMap;
use std::error::Error;
use std::fmt;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::io::Write;
use std::path::{Path, PathBuf};

use codex_hepta_types::CellCachePolicyV1;
use codex_hepta_types::CellInFlightPolicyV1;
use codex_hepta_types::CellSplitV1;
use codex_hepta_types::CellStateTransformKindV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CellStateSplitChildV1;
use crate::CellStateSplitError;
use crate::CellStateSplitPlanV1;
use crate::JournalAnchor;
use crate::SparseCheckpoint;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CellStateMigrationPhaseV1 {
    Prepared,
    PayloadsDurable,
    ChildrenCommitted,
    Acknowledged,
    Quarantined,
    RolledBack,
}

impl CellStateMigrationPhaseV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Prepared => 0,
            Self::PayloadsDurable => 1,
            Self::ChildrenCommitted => 2,
            Self::Acknowledged => 3,
            Self::Quarantined => 4,
            Self::RolledBack => 5,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellStateCasReceiptV1 {
    pub operation_id: StableId,
    pub child_cell_id: StableId,
    pub parent_anchor: JournalAnchor,
    pub payload_digest: Digest32,
    pub encoded_size_bytes: u64,
    pub fence_digest: Digest32,
    pub receipt_digest: Digest32,
}

impl CellStateCasReceiptV1 {
    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.neuron.cell-state-cas-receipt.v1".to_vec();
        push_id(&mut bytes, &self.operation_id);
        push_id(&mut bytes, &self.child_cell_id);
        bytes.extend_from_slice(&self.parent_anchor.sequence.to_be_bytes());
        bytes.extend_from_slice(self.parent_anchor.checkpoint_digest.as_array());
        bytes.extend_from_slice(self.payload_digest.as_array());
        bytes.extend_from_slice(&self.encoded_size_bytes.to_be_bytes());
        bytes.extend_from_slice(self.fence_digest.as_array());
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellStateBatchReceiptV1 {
    pub operation_id: StableId,
    pub parent_anchor: JournalAnchor,
    pub fence_digest: Digest32,
    pub child_receipt_digests: Vec<Digest32>,
    pub commit_witness_digest: Digest32,
    pub receipt_digest: Digest32,
}

impl CellStateBatchReceiptV1 {
    /// Construct the batch witness after the host has atomically committed all
    /// child CAS objects. The commit witness itself is intentionally supplied
    /// by that host and must be independently durable.
    #[must_use]
    pub fn new(
        operation_id: StableId,
        parent_anchor: JournalAnchor,
        fence_digest: Digest32,
        mut child_receipt_digests: Vec<Digest32>,
        commit_witness_digest: Digest32,
    ) -> Self {
        child_receipt_digests.sort_unstable();
        let mut value = Self {
            operation_id,
            parent_anchor,
            fence_digest,
            child_receipt_digests,
            commit_witness_digest,
            receipt_digest: Digest32::ZERO,
        };
        value.receipt_digest = digest_batch(&value);
        value
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellStateMigrationReceiptV1 {
    pub operation_id: StableId,
    pub split_digest: Digest32,
    pub parent_anchor: JournalAnchor,
    pub child_state_digests: Vec<Digest32>,
    pub batch_receipt_digest: Digest32,
    pub optimizer_policy: CellStateTransformKindV1,
    pub cache_policy: CellCachePolicyV1,
    pub in_flight_policy: CellInFlightPolicyV1,
    pub rollback_parent_cell_id: StableId,
    pub phase: CellStateMigrationPhaseV1,
    pub receipt_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellStateMigrationErrorV1 {
    InvalidContract,
    InvalidParentAnchor,
    ParentAnchorMismatch,
    ParentGenerationMismatch,
    CandidateGenerationMismatch,
    Split(CellStateSplitError),
    EmptyDigest(&'static str),
    UnknownChild(StableId),
    ChildCount,
    ReceiptMismatch(StableId),
    FenceMismatch,
    InvalidState,
    BatchCommitMismatch,
    UnsupportedPolicy(&'static str),
    Io(std::io::ErrorKind),
    CasWriterBusy,
    CasCorruption(&'static str),
}

impl fmt::Display for CellStateMigrationErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for CellStateMigrationErrorV1 {}

impl From<CellStateSplitError> for CellStateMigrationErrorV1 {
    fn from(error: CellStateSplitError) -> Self {
        Self::Split(error)
    }
}

/// A multi-child migration transaction.  It never mutates the parent
/// `SparseJournal`; it requires a committed parent checkpoint and produces a
/// receipt that an external child-journal/CAS owner can atomically publish.
#[derive(Clone, Debug)]
pub struct CellStateMigrationV1 {
    operation_id: StableId,
    split_digest: Digest32,
    parent_anchor: JournalAnchor,
    parent_cell_id: StableId,
    optimizer_policy: CellStateTransformKindV1,
    cache_policy: CellCachePolicyV1,
    in_flight_policy: CellInFlightPolicyV1,
    fence_digest: Digest32,
    children: Vec<CellStateSplitChildV1>,
    payload_receipts: BTreeMap<StableId, CellStateCasReceiptV1>,
    batch_receipt: Option<CellStateBatchReceiptV1>,
    phase: CellStateMigrationPhaseV1,
}

impl CellStateMigrationV1 {
    pub fn begin(
        operation_id: StableId,
        contract: &CellSplitV1,
        parent_anchor: JournalAnchor,
        parent_checkpoint: &SparseCheckpoint,
        plan: &CellStateSplitPlanV1,
    ) -> Result<Self, CellStateMigrationErrorV1> {
        contract
            .validate_plan()
            .map_err(|_| CellStateMigrationErrorV1::InvalidContract)?;
        if parent_anchor.sequence == 0 || parent_anchor.checkpoint_digest.is_zero() {
            return Err(CellStateMigrationErrorV1::InvalidParentAnchor);
        }
        if parent_checkpoint.digest() != parent_anchor.checkpoint_digest
            || parent_checkpoint.sequence() != parent_anchor.sequence
        {
            return Err(CellStateMigrationErrorV1::ParentAnchorMismatch);
        }
        if plan.parent_cell_id != contract.parent_cell_id
            || plan.parent_generation != contract.predecessor_generation
            || plan.candidate_generation != contract.successor_generation
        {
            return Err(CellStateMigrationErrorV1::ParentGenerationMismatch);
        }
        if contract.state.optimizer.kind != CellStateTransformKindV1::Reset {
            return Err(CellStateMigrationErrorV1::UnsupportedPolicy(
                "neuron optimizer migration requires external reset",
            ));
        }
        let children = parent_checkpoint.split_state_v1(plan)?;
        Self::begin_from_children(operation_id, contract, parent_anchor, plan, children)
    }

    /// Begin from a projection produced by either the sparse V1 or population
    /// V2 kernel. The executable plan is supplied again at this boundary so
    /// the owner can reject a child vector projected with a different mapping.
    /// The child vector must still carry the exact acknowledged parent digest;
    /// this is the common migration boundary for both kernels.
    pub fn begin_from_children(
        operation_id: StableId,
        contract: &CellSplitV1,
        parent_anchor: JournalAnchor,
        plan: &CellStateSplitPlanV1,
        children: Vec<CellStateSplitChildV1>,
    ) -> Result<Self, CellStateMigrationErrorV1> {
        contract
            .validate_plan()
            .map_err(|_| CellStateMigrationErrorV1::InvalidContract)?;
        if parent_anchor.sequence == 0 || parent_anchor.checkpoint_digest.is_zero() {
            return Err(CellStateMigrationErrorV1::InvalidParentAnchor);
        }
        let bound_plan = CellStateSplitPlanV1::from_contract(
            contract,
            plan.temporal_partitions.clone(),
            plan.activation_partitions.clone(),
        )
        .map_err(|_| CellStateMigrationErrorV1::InvalidContract)?;
        if bound_plan != *plan {
            return Err(CellStateMigrationErrorV1::InvalidContract);
        }
        if children.len() != contract.children.len() {
            return Err(CellStateMigrationErrorV1::ChildCount);
        }
        if contract.state.optimizer.kind != CellStateTransformKindV1::Reset {
            return Err(CellStateMigrationErrorV1::UnsupportedPolicy(
                "neuron optimizer migration requires external reset",
            ));
        }
        let split_digest = contract
            .evaluation_subject_digest()
            .map_err(|_| CellStateMigrationErrorV1::InvalidContract)?;
        let expected_ids = contract
            .children
            .iter()
            .map(|child| child.child_cell_id.clone())
            .collect::<std::collections::BTreeSet<_>>();
        let mut seen = std::collections::BTreeSet::new();
        for child in &children {
            if child.parent_cell_id != contract.parent_cell_id
                || child.parent_generation != contract.predecessor_generation
                || child.candidate_generation != contract.successor_generation
                || child.parent_checkpoint_digest != parent_anchor.checkpoint_digest
                || !child.verify_digest()
                || !expected_ids.contains(&child.child_cell_id)
                || !seen.insert(child.child_cell_id.clone())
            {
                return Err(CellStateMigrationErrorV1::ParentAnchorMismatch);
            }
        }
        if seen != expected_ids {
            return Err(CellStateMigrationErrorV1::ChildCount);
        }
        let fence_digest = digest_fence(&operation_id, split_digest, parent_anchor);
        Ok(Self {
            operation_id,
            split_digest,
            parent_anchor,
            parent_cell_id: contract.parent_cell_id.clone(),
            optimizer_policy: contract.state.optimizer.kind,
            cache_policy: contract.state.cache_policy,
            in_flight_policy: contract.state.in_flight_policy,
            fence_digest,
            children,
            payload_receipts: BTreeMap::new(),
            batch_receipt: None,
            phase: CellStateMigrationPhaseV1::Prepared,
        })
    }

    #[must_use]
    pub const fn phase(&self) -> CellStateMigrationPhaseV1 {
        self.phase
    }

    #[must_use]
    pub const fn fence_digest(&self) -> Digest32 {
        self.fence_digest
    }

    #[must_use]
    pub fn children(&self) -> &[CellStateSplitChildV1] {
        &self.children
    }

    /// Canonical bytes for a child state CAS object.  No tensor or optimizer
    /// bytes are fabricated: these are exactly the projected Q24 vectors.
    #[must_use]
    pub fn encode_child_state(child: &CellStateSplitChildV1) -> Vec<u8> {
        encode_child_state(child)
    }

    #[must_use]
    pub fn child_payload_digest(child: &CellStateSplitChildV1) -> Digest32 {
        Digest32::of_bytes(&encode_child_state(child))
    }

    /// Write one child object to a host-created file and sync it before
    /// returning a receipt. The host must create the file exclusively and sync
    /// its directory; this API never opens paths or overwrites an existing CAS
    /// object.
    pub fn persist_child_state(
        &self,
        child_cell_id: &StableId,
        mut file: File,
    ) -> Result<CellStateCasReceiptV1, CellStateMigrationErrorV1> {
        if self.phase != CellStateMigrationPhaseV1::Prepared {
            return Err(CellStateMigrationErrorV1::InvalidState);
        }
        let child = self
            .children
            .iter()
            .find(|child| &child.child_cell_id == child_cell_id)
            .ok_or_else(|| CellStateMigrationErrorV1::UnknownChild(child_cell_id.clone()))?;
        let bytes = encode_child_state(child);
        file.write_all(&bytes)
            .map_err(|error| CellStateMigrationErrorV1::Io(error.kind()))?;
        file.sync_all()
            .map_err(|error| CellStateMigrationErrorV1::Io(error.kind()))?;
        let mut receipt = CellStateCasReceiptV1 {
            operation_id: self.operation_id.clone(),
            child_cell_id: child_cell_id.clone(),
            parent_anchor: self.parent_anchor,
            payload_digest: Digest32::of_bytes(&bytes),
            encoded_size_bytes: bytes.len() as u64,
            fence_digest: self.fence_digest,
            receipt_digest: Digest32::ZERO,
        };
        receipt.receipt_digest = receipt.content_digest();
        Ok(receipt)
    }

    pub fn record_payloads_durable(
        &mut self,
        receipts: Vec<CellStateCasReceiptV1>,
    ) -> Result<(), CellStateMigrationErrorV1> {
        if self.phase != CellStateMigrationPhaseV1::Prepared {
            return Err(CellStateMigrationErrorV1::InvalidState);
        }
        if receipts.len() != self.children.len() {
            return Err(CellStateMigrationErrorV1::ChildCount);
        }
        let expected: BTreeMap<_, _> = self
            .children
            .iter()
            .map(|child| (child.child_cell_id.clone(), child))
            .collect();
        let mut next = BTreeMap::new();
        for receipt in receipts {
            let child = expected.get(&receipt.child_cell_id).ok_or_else(|| {
                CellStateMigrationErrorV1::UnknownChild(receipt.child_cell_id.clone())
            })?;
            if receipt.operation_id != self.operation_id
                || receipt.parent_anchor != self.parent_anchor
                || receipt.fence_digest != self.fence_digest
                || receipt.payload_digest != Self::child_payload_digest(child)
                || receipt.receipt_digest != receipt.content_digest()
                || receipt.encoded_size_bytes != encode_child_state(child).len() as u64
            {
                return Err(CellStateMigrationErrorV1::ReceiptMismatch(
                    receipt.child_cell_id,
                ));
            }
            if next
                .insert(receipt.child_cell_id.clone(), receipt)
                .is_some()
            {
                return Err(CellStateMigrationErrorV1::ReceiptMismatch(
                    child.child_cell_id.clone(),
                ));
            }
        }
        self.payload_receipts = next;
        self.phase = CellStateMigrationPhaseV1::PayloadsDurable;
        Ok(())
    }

    /// Accept an external multi-file commit witness only after every child CAS
    /// receipt is present. This is the fenced boundary before route activation.
    pub fn commit_children(
        &mut self,
        batch: CellStateBatchReceiptV1,
    ) -> Result<(), CellStateMigrationErrorV1> {
        if self.phase != CellStateMigrationPhaseV1::PayloadsDurable {
            return Err(CellStateMigrationErrorV1::InvalidState);
        }
        let mut expected = self
            .payload_receipts
            .values()
            .map(|receipt| receipt.receipt_digest)
            .collect::<Vec<_>>();
        expected.sort_unstable();
        let mut actual = batch.child_receipt_digests.clone();
        actual.sort_unstable();
        if batch.operation_id != self.operation_id
            || batch.parent_anchor != self.parent_anchor
            || batch.fence_digest != self.fence_digest
            || batch.commit_witness_digest.is_zero()
            || actual != expected
            || batch.receipt_digest != digest_batch(&batch)
        {
            return Err(CellStateMigrationErrorV1::BatchCommitMismatch);
        }
        self.batch_receipt = Some(batch);
        self.phase = CellStateMigrationPhaseV1::ChildrenCommitted;
        Ok(())
    }

    /// Children can only be acknowledged after the external batch commit.
    /// Parent retirement must remain fenced after this receipt is consumed.
    pub fn acknowledge(
        &mut self,
    ) -> Result<CellStateMigrationReceiptV1, CellStateMigrationErrorV1> {
        if self.phase != CellStateMigrationPhaseV1::ChildrenCommitted {
            return Err(CellStateMigrationErrorV1::InvalidState);
        }
        let batch = self
            .batch_receipt
            .clone()
            .ok_or(CellStateMigrationErrorV1::InvalidState)?;
        let child_state_digests = self
            .children
            .iter()
            .map(|child| child.state_digest)
            .collect::<Vec<_>>();
        self.phase = CellStateMigrationPhaseV1::Acknowledged;
        let receipt_digest = digest_migration_receipt(
            &self.operation_id,
            self.split_digest,
            self.parent_anchor,
            &child_state_digests,
            batch.receipt_digest,
            self.optimizer_policy,
            self.cache_policy,
            self.in_flight_policy,
            self.phase,
        );
        Ok(CellStateMigrationReceiptV1 {
            operation_id: self.operation_id.clone(),
            split_digest: self.split_digest,
            parent_anchor: self.parent_anchor,
            child_state_digests,
            batch_receipt_digest: batch.receipt_digest,
            optimizer_policy: self.optimizer_policy,
            cache_policy: self.cache_policy,
            in_flight_policy: self.in_flight_policy,
            rollback_parent_cell_id: self.parent_cell_id.clone(),
            phase: self.phase,
            receipt_digest,
        })
    }

    /// Any failed child can quarantine the whole transaction before parent
    /// retirement. No partial child state is considered eligible afterwards.
    pub fn quarantine(&mut self, reason_digest: Digest32) -> Result<(), CellStateMigrationErrorV1> {
        if reason_digest.is_zero() || self.phase == CellStateMigrationPhaseV1::RolledBack {
            return Err(CellStateMigrationErrorV1::InvalidState);
        }
        self.phase = CellStateMigrationPhaseV1::Quarantined;
        Ok(())
    }

    pub fn rollback(&mut self) -> Result<StableId, CellStateMigrationErrorV1> {
        if self.phase != CellStateMigrationPhaseV1::Quarantined {
            return Err(CellStateMigrationErrorV1::InvalidState);
        }
        self.phase = CellStateMigrationPhaseV1::RolledBack;
        Ok(self.parent_cell_id.clone())
    }

    #[must_use]
    pub const fn parent_retirement_is_fenced(&self) -> bool {
        matches!(
            self.phase,
            CellStateMigrationPhaseV1::Acknowledged
                | CellStateMigrationPhaseV1::Quarantined
                | CellStateMigrationPhaseV1::RolledBack
        )
    }
}

/// Exclusive local-disk owner for the actual child state CAS and batch commit.
///
/// The caller opens a trusted, existing private directory. Each child is
/// written with create_new, file sync and parent-directory sync. Content hashes
/// are verified on every retry, and a second independent writer cannot hold
/// the same OS file lock. The commit marker is persisted after all child
/// objects and is checked byte-for-byte on restart before acknowledgement.
///
/// This owner proves only local filesystem operations. It does not publish CNS
/// routes, advance a Supervisor generation, sign independent host evidence,
/// or certify a power-loss test.
#[derive(Debug)]
pub struct DurableCellStateCasDirectoryOwnerV1 {
    root: PathBuf,
    writer_lock: File,
}

impl DurableCellStateCasDirectoryOwnerV1 {
    pub fn open(root: impl AsRef<Path>) -> Result<Self, CellStateMigrationErrorV1> {
        let root = root.as_ref().canonicalize().map_err(cas_io)?;
        if !root.is_dir() {
            return Err(CellStateMigrationErrorV1::CasCorruption(
                "CAS root is not a directory",
            ));
        }
        let lock_path = root.join(".hepta-cell-state-cas-owner.lock");
        let writer_lock = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .open(lock_path)
            .map_err(cas_io)?;
        match writer_lock.try_lock() {
            Ok(()) => (),
            Err(TryLockError::WouldBlock) => {
                return Err(CellStateMigrationErrorV1::CasWriterBusy);
            }
            Err(TryLockError::Error(error)) => return Err(cas_io(error)),
        }
        // Persist any newly created lock entry before accepting operations.
        File::open(&root)
            .and_then(|directory| directory.sync_all())
            .map_err(cas_io)?;
        Ok(Self { root, writer_lock })
    }

    /// Publish only after each exact child payload and the batch marker has
    /// been read, checked, synced, and parent-directory synced. A failed or
    /// torn existing object is never overwritten, repaired or acknowledged.
    /// A restarted caller reconstructs its migration from the original,
    /// authenticated parent checkpoint and then safely calls this again.
    pub fn persist_commit_and_acknowledge(
        &mut self,
        migration: &mut CellStateMigrationV1,
    ) -> Result<CellStateMigrationReceiptV1, CellStateMigrationErrorV1> {
        if migration.phase != CellStateMigrationPhaseV1::Prepared {
            return Err(CellStateMigrationErrorV1::InvalidState);
        }
        let mut receipts = Vec::with_capacity(migration.children.len());
        for child in &migration.children {
            if !child.verify_digest()
                || child.parent_checkpoint_digest != migration.parent_anchor.checkpoint_digest
                || child.parent_cell_id != migration.parent_cell_id
            {
                return Err(CellStateMigrationErrorV1::ParentAnchorMismatch);
            }
            let bytes = encode_child_state(child);
            let digest = Digest32::of_bytes(&bytes);
            let path = self.root.join(format!("object-{digest}.q24"));
            let new_file = OpenOptions::new()
                .read(true)
                .write(true)
                .create_new(true)
                .open(&path);
            let receipt = match new_file {
                Ok(file) => {
                    // This performs a real write and file.sync_all.
                    migration.persist_child_state(&child.child_cell_id, file)?
                }
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                    // An earlier crashed writer may have committed the same CAS
                    // object, but only independently checked bytes count.
                    let metadata = fs::symlink_metadata(&path).map_err(cas_io)?;
                    if !metadata.file_type().is_file() {
                        return Err(CellStateMigrationErrorV1::CasCorruption(
                            "CAS object is not a regular file",
                        ));
                    }
                    let file = OpenOptions::new().read(true).open(&path).map_err(cas_io)?;
                    file.sync_all().map_err(cas_io)?;
                    let mut receipt = CellStateCasReceiptV1 {
                        operation_id: migration.operation_id.clone(),
                        child_cell_id: child.child_cell_id.clone(),
                        parent_anchor: migration.parent_anchor,
                        payload_digest: digest,
                        encoded_size_bytes: bytes.len() as u64,
                        fence_digest: migration.fence_digest,
                        receipt_digest: Digest32::ZERO,
                    };
                    receipt.receipt_digest = receipt.content_digest();
                    receipt
                }
                Err(error) => return Err(cas_io(error)),
            };
            if fs::read(&path).map_err(cas_io)? != bytes
                || receipt.payload_digest != digest
                || receipt.encoded_size_bytes != bytes.len() as u64
                || receipt.receipt_digest != receipt.content_digest()
            {
                return Err(CellStateMigrationErrorV1::CasCorruption(
                    "CAS object bytes or operation receipt do not match",
                ));
            }
            self.sync_directory()?;
            receipts.push(receipt);
        }

        let mut sorted = receipts
            .iter()
            .map(|receipt| receipt.receipt_digest)
            .collect::<Vec<_>>();
        sorted.sort_unstable();
        let mut marker_bytes = b"hepta.neuron.cell-state-cas-durable-batch.v1\0".to_vec();
        push_id(&mut marker_bytes, &migration.operation_id);
        marker_bytes.extend_from_slice(migration.split_digest.as_array());
        marker_bytes.extend_from_slice(&migration.parent_anchor.sequence.to_be_bytes());
        marker_bytes.extend_from_slice(migration.parent_anchor.checkpoint_digest.as_array());
        marker_bytes.extend_from_slice(migration.fence_digest.as_array());
        marker_bytes.extend_from_slice(&(sorted.len() as u64).to_be_bytes());
        for digest in &sorted {
            marker_bytes.extend_from_slice(digest.as_array());
        }

        let commit_path = self
            .root
            .join(format!("commit-{}.ack", migration.fence_digest));
        match OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(&commit_path)
        {
            Ok(mut file) => {
                file.write_all(&marker_bytes).map_err(cas_io)?;
                file.sync_all().map_err(cas_io)?;
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                let metadata = fs::symlink_metadata(&commit_path).map_err(cas_io)?;
                if !metadata.file_type().is_file() {
                    return Err(CellStateMigrationErrorV1::CasCorruption(
                        "batch marker is not a regular file",
                    ));
                }
                let file = OpenOptions::new()
                    .read(true)
                    .open(&commit_path)
                    .map_err(cas_io)?;
                file.sync_all().map_err(cas_io)?;
            }
            Err(error) => return Err(cas_io(error)),
        };
        let observed_marker = fs::read(&commit_path).map_err(cas_io)?;
        if observed_marker != marker_bytes {
            return Err(CellStateMigrationErrorV1::CasCorruption(
                "batch commit marker does not match source migration",
            ));
        }
        self.sync_directory()?;
        // The witness digest now names the on-disk, directory-synced batch
        // marker, not an asserted or caller-provided hash.
        let witness = Digest32::of_bytes(&observed_marker);
        migration.record_payloads_durable(receipts)?;
        migration.commit_children(CellStateBatchReceiptV1::new(
            migration.operation_id.clone(),
            migration.parent_anchor,
            migration.fence_digest,
            sorted,
            witness,
        ))?;
        migration.acknowledge()
    }

    fn sync_directory(&self) -> Result<(), CellStateMigrationErrorV1> {
        File::open(&self.root)
            .and_then(|directory| directory.sync_all())
            .map_err(cas_io)
    }
}

impl Drop for DurableCellStateCasDirectoryOwnerV1 {
    fn drop(&mut self) {
        let _ = self.writer_lock.unlock();
    }
}

fn cas_io(error: std::io::Error) -> CellStateMigrationErrorV1 {
    CellStateMigrationErrorV1::Io(error.kind())
}

#[must_use]
pub fn encode_cell_state_v1(child: &CellStateSplitChildV1) -> Vec<u8> {
    encode_child_state(child)
}

fn encode_child_state(child: &CellStateSplitChildV1) -> Vec<u8> {
    let mut bytes = b"hepta.neuron.cell-state.q24.v1".to_vec();
    push_id(&mut bytes, &child.parent_cell_id);
    push_id(&mut bytes, &child.child_cell_id);
    bytes.extend_from_slice(child.child_scope.as_array());
    bytes.extend_from_slice(&child.parent_generation.get().to_be_bytes());
    bytes.extend_from_slice(&child.candidate_generation.get().to_be_bytes());
    for digest in [
        child.parent_checkpoint_digest,
        child.parent_config_digest,
        child.parent_scope,
        child.objective_digest,
        child.body_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&child.sequence.to_be_bytes());
    for vector in [
        &child.temporal_q24,
        &child.activation_q24,
        &child.activity_q24,
        &child.threshold_q24,
        &child.eligibility_q24,
    ] {
        bytes.extend_from_slice(&(vector.len() as u64).to_be_bytes());
        for value in vector {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
    }
    bytes.extend_from_slice(child.state_digest.as_array());
    bytes
}

fn digest_fence(
    operation_id: &StableId,
    split_digest: Digest32,
    anchor: JournalAnchor,
) -> Digest32 {
    let mut bytes = b"hepta.neuron.cell-state-migration-fence.v1".to_vec();
    push_id(&mut bytes, operation_id);
    bytes.extend_from_slice(split_digest.as_array());
    bytes.extend_from_slice(&anchor.sequence.to_be_bytes());
    bytes.extend_from_slice(anchor.checkpoint_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn digest_batch(batch: &CellStateBatchReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.neuron.cell-state-batch-receipt.v1".to_vec();
    push_id(&mut bytes, &batch.operation_id);
    bytes.extend_from_slice(&batch.parent_anchor.sequence.to_be_bytes());
    bytes.extend_from_slice(batch.parent_anchor.checkpoint_digest.as_array());
    bytes.extend_from_slice(batch.fence_digest.as_array());
    bytes.extend_from_slice(batch.commit_witness_digest.as_array());
    for digest in &batch.child_receipt_digests {
        bytes.extend_from_slice(digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

#[allow(clippy::too_many_arguments)]
fn digest_migration_receipt(
    operation_id: &StableId,
    split_digest: Digest32,
    parent_anchor: JournalAnchor,
    child_states: &[Digest32],
    batch_receipt: Digest32,
    optimizer: CellStateTransformKindV1,
    cache: CellCachePolicyV1,
    in_flight: CellInFlightPolicyV1,
    phase: CellStateMigrationPhaseV1,
) -> Digest32 {
    let mut bytes = b"hepta.neuron.cell-state-migration-receipt.v1".to_vec();
    push_id(&mut bytes, operation_id);
    bytes.extend_from_slice(split_digest.as_array());
    bytes.extend_from_slice(&parent_anchor.sequence.to_be_bytes());
    bytes.extend_from_slice(parent_anchor.checkpoint_digest.as_array());
    bytes.extend_from_slice(batch_receipt.as_array());
    bytes.push(match optimizer {
        CellStateTransformKindV1::Copy => 0,
        CellStateTransformKindV1::Partition => 1,
        CellStateTransformKindV1::Reset => 2,
        CellStateTransformKindV1::Custom => 3,
    });
    bytes.push(match cache {
        CellCachePolicyV1::Drop => 0,
        CellCachePolicyV1::Partition => 1,
        CellCachePolicyV1::Revalidate => 2,
    });
    bytes.push(match in_flight {
        CellInFlightPolicyV1::Drain => 0,
        CellInFlightPolicyV1::Reassign => 1,
        CellInFlightPolicyV1::Cancel => 2,
    });
    bytes.push(phase.tag());
    for digest in child_states {
        bytes.extend_from_slice(digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    let raw = id.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u32).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
mod durable_cas_tests {
    use super::*;
    use crate::SparseConfig;
    use crate::SparseTick;
    use crate::sparse_tick;
    use codex_hepta_types::Generation;
    use std::sync::atomic::{AtomicU64, Ordering};

    static SERIAL: AtomicU64 = AtomicU64::new(0);
    const Q: i64 = 1 << 24;

    struct TempRoot(PathBuf);

    impl TempRoot {
        fn new() -> Self {
            let id = SERIAL.fetch_add(1, Ordering::Relaxed);
            let root = std::env::temp_dir()
                .join(format!("hepta-child-state-cas-{}-{id}", std::process::id()));
            fs::create_dir(&root).expect("create private fixture root");
            Self(root)
        }
    }

    impl Drop for TempRoot {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    fn id(name: &str) -> StableId {
        StableId::new(name).expect("valid identity")
    }

    fn migration() -> CellStateMigrationV1 {
        let model = Digest32::of_bytes(b"model");
        let config = SparseConfig {
            model_digest: model,
            normalization_digest: Digest32::of_bytes(b"normalization"),
            generation: Generation::new(1).unwrap(),
            width: 2,
            top_k: 1,
            temporal_decay_q24: Q / 2,
            inhibition_gain_q24: Q,
            inhibition: Vec::new(),
            activity_decay_q24: Q / 2,
            target_activity_q24: Q / 4,
            threshold_rate_q24: Q / 8,
            threshold_min_q24: -Q,
            threshold_max_q24: Q,
            eligibility_decay_q24: Q / 2,
        };
        let tick = SparseTick {
            scope_digest: Digest32::of_bytes(b"parent-scope"),
            objective_digest: Digest32::of_bytes(b"objective"),
            ndu_digest: Digest32::of_bytes(b"ndu"),
            body_digest: Digest32::of_bytes(b"body"),
            input_digest: Digest32::of_bytes(b"input"),
            sequence: 1,
            monotonic_micros: 10,
            drive_q24: vec![Q, Q / 2],
            prediction_q24: vec![0, 0],
        };
        let checkpoint = sparse_tick(&config, &tick, None).unwrap().0;
        let plan = CellStateSplitPlanV1::new(
            id("cell.parent"),
            vec![id("cell.child.a"), id("cell.child.b")],
            vec![
                Digest32::of_bytes(b"child-scope-a"),
                Digest32::of_bytes(b"child-scope-b"),
            ],
            Generation::new(1).unwrap(),
            Generation::new(2).unwrap(),
            vec![vec![0], vec![1]],
            vec![vec![0], vec![1]],
        )
        .unwrap();
        let children = checkpoint.split_state_v1(&plan).unwrap();
        assert!(children.iter().all(CellStateSplitChildV1::verify_digest));
        let parent_anchor = JournalAnchor {
            sequence: checkpoint.sequence(),
            checkpoint_digest: checkpoint.digest(),
        };
        let operation_id = id("migration.operation");
        let split_digest = Digest32::of_bytes(b"frozen-split");
        CellStateMigrationV1 {
            fence_digest: digest_fence(&operation_id, split_digest, parent_anchor),
            operation_id,
            split_digest,
            parent_anchor,
            parent_cell_id: id("cell.parent"),
            optimizer_policy: CellStateTransformKindV1::Reset,
            cache_policy: CellCachePolicyV1::Revalidate,
            in_flight_policy: CellInFlightPolicyV1::Drain,
            children,
            payload_receipts: BTreeMap::new(),
            batch_receipt: None,
            phase: CellStateMigrationPhaseV1::Prepared,
        }
    }

    #[test]
    fn actual_child_cas_and_batch_marker_survive_owner_reopen() {
        let root = TempRoot::new();
        let mut first = migration();
        let receipt = {
            let mut owner = DurableCellStateCasDirectoryOwnerV1::open(&root.0).unwrap();
            let observed = owner.persist_commit_and_acknowledge(&mut first).unwrap();
            assert!(first.parent_retirement_is_fenced());
            assert_eq!(observed.phase, CellStateMigrationPhaseV1::Acknowledged);
            observed
        };
        let mut replay = migration();
        let mut reopened = DurableCellStateCasDirectoryOwnerV1::open(&root.0).unwrap();
        assert_eq!(
            reopened
                .persist_commit_and_acknowledge(&mut replay)
                .unwrap(),
            receipt
        );
        assert_eq!(replay.phase(), CellStateMigrationPhaseV1::Acknowledged);
    }

    #[test]
    fn concurrent_writer_and_changed_cas_payload_are_rejected() {
        let root = TempRoot::new();
        let mut first = migration();
        let owner = DurableCellStateCasDirectoryOwnerV1::open(&root.0).unwrap();
        assert!(matches!(
            DurableCellStateCasDirectoryOwnerV1::open(&root.0),
            Err(CellStateMigrationErrorV1::CasWriterBusy)
        ));
        let mut owner = owner;
        owner.persist_commit_and_acknowledge(&mut first).unwrap();
        drop(owner);
        let child = &first.children[0];
        let object = root.0.join(format!(
            "object-{}.q24",
            CellStateMigrationV1::child_payload_digest(child)
        ));
        fs::write(object, b"forged payload after commit").unwrap();
        let mut next = migration();
        let mut reopened = DurableCellStateCasDirectoryOwnerV1::open(&root.0).unwrap();
        assert!(matches!(
            reopened.persist_commit_and_acknowledge(&mut next),
            Err(CellStateMigrationErrorV1::CasCorruption(_))
        ));
        assert_eq!(next.phase(), CellStateMigrationPhaseV1::Prepared);
    }

    #[test]
    fn torn_batch_marker_is_not_repaired_or_acknowledged() {
        let root = TempRoot::new();
        let mut first = migration();
        {
            let mut owner = DurableCellStateCasDirectoryOwnerV1::open(&root.0).unwrap();
            owner.persist_commit_and_acknowledge(&mut first).unwrap();
        }
        let marker = root.0.join(format!("commit-{}.ack", first.fence_digest()));
        fs::write(marker, b"torn batch").unwrap();
        let mut replay = migration();
        let mut owner = DurableCellStateCasDirectoryOwnerV1::open(&root.0).unwrap();
        assert!(matches!(
            owner.persist_commit_and_acknowledge(&mut replay),
            Err(CellStateMigrationErrorV1::CasCorruption(_))
        ));
        assert_eq!(replay.phase(), CellStateMigrationPhaseV1::Prepared);
    }
}
