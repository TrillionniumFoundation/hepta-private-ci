//! Fail-closed Cell Split orchestration and receipt ledger.
//!
//! This is a product-side orchestration seam, NOT an alternative CAS, CNS,
//! supervisor, evaluator, selector, or signing authority. Production ports must
//! call their actual owners, verify signed evidence against independent trust,
//! and read back authoritative state. No port is installed at Agentd startup.
//!
//! A private regular ledger file and an independently retained, authenticated
//! ledger anchor are mandatory host inputs. In particular, a digest read from
//! this journal is NOT an acceptable recovery anchor.

use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::fs::TryLockError;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

use codex_hepta_intelligence_eval::VerifiedSelfEvolutionSelectionV1;
use codex_hepta_learning_artifacts::RevalidatingCandidate;
use codex_hepta_learning_artifacts::VerifiedCurrentRegistryViewV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

const MAGIC: &[u8; 8] = b"HCSPLT01";
const HEADER_SIZE: usize = 104;
const MAX_RECEIPT_BYTES: usize = 8 * 1024;
const FRAME_FIXED_SIZE: usize = 2 + 8 + 32 + 32 + 8 + 4 + 32;
const MAX_FRAME_SIZE: usize = FRAME_FIXED_SIZE + MAX_RECEIPT_BYTES;
const MAX_LEDGER_SIZE: usize = 256 * 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitPlanV1 {
    pub split_id: StableId,
    pub scope_digest: Digest32,
    /// Storage namespace authenticated by the immutable Artifact Owner,
    /// distinct from the logical Split scope.
    pub artifact_storage_binding_digest: Digest32,
    pub predecessor_id: StableId,
    pub child_id: StableId,
    /// Independently registered artifact lineage, never inferred from Cell IDs
    /// or a topology candidate ID. Required to pin real CAS publication.
    pub predecessor_artifact_id: StableId,
    pub child_artifact_id: StableId,
    /// Frozen candidate mapping; candidate identity is NOT the child Cell ID.
    pub selected_candidate_id: StableId,
    /// Frozen independent evaluation context; a valid selector token from a
    /// different objective or no-change control must never be reused.
    pub objective_digest: Digest32,
    pub no_change_baseline_id: StableId,
    pub no_change_baseline_digest: Digest32,
    pub evaluation_dataset_digest: Digest32,
    pub minimum_future_window_micros: u64,
    pub predecessor_generation: Generation,
    pub child_generation: Generation,
    pub predecessor_artifact_digest: Digest32,
    pub child_artifact_digest: Digest32,
    pub state_migration_digest: Digest32,
    /// Independently verified selector evidence, not a selector decision made here.
    pub selection_digest: Digest32,
    /// Exact Final-use binding. A digest is not itself authorization.
    pub final_use_binding_digest: Digest32,
}

impl CellSplitPlanV1 {
    fn validate(&self) -> Result<(), CellSplitErrorV1> {
        if self.predecessor_id == self.child_id
            || self.predecessor_artifact_id == self.child_artifact_id
            || self.no_change_baseline_id == self.selected_candidate_id
            || self.minimum_future_window_micros == 0
            || self.predecessor_generation.next() != Ok(self.child_generation)
            || [
                self.scope_digest,
                self.artifact_storage_binding_digest,
                self.objective_digest,
                self.no_change_baseline_digest,
                self.evaluation_dataset_digest,
                self.predecessor_artifact_digest,
                self.child_artifact_digest,
                self.state_migration_digest,
                self.selection_digest,
                self.final_use_binding_digest,
            ]
            .into_iter()
            .any(Digest32::is_zero)
        {
            return Err(CellSplitErrorV1::InvalidPlan);
        }
        Ok(())
    }

    pub fn binding_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.agentd.cell-split.plan.v1\0".to_vec();
        for id in [
            &self.split_id,
            &self.predecessor_id,
            &self.child_id,
            &self.predecessor_artifact_id,
            &self.child_artifact_id,
            &self.selected_candidate_id,
            &self.no_change_baseline_id,
        ] {
            let raw = id.as_str().as_bytes();
            bytes.extend_from_slice(&(raw.len() as u64).to_be_bytes());
            bytes.extend_from_slice(raw);
        }
        bytes.extend_from_slice(&self.predecessor_generation.get().to_be_bytes());
        bytes.extend_from_slice(&self.child_generation.get().to_be_bytes());
        bytes.extend_from_slice(&self.minimum_future_window_micros.to_be_bytes());
        for value in [
            self.scope_digest,
            self.artifact_storage_binding_digest,
            self.objective_digest,
            self.no_change_baseline_digest,
            self.evaluation_dataset_digest,
            self.predecessor_artifact_digest,
            self.child_artifact_digest,
            self.state_migration_digest,
            self.selection_digest,
            self.final_use_binding_digest,
        ] {
            bytes.extend_from_slice(value.as_array());
        }
        Digest32::of_bytes(&bytes)
    }


    /// Consume the independently verified, opaque self-evolution selection
    /// token as a binding check only. Selection remains non-authorizing.
    /// The real port still has to verify freshness, signed evidence, and
    /// revocations at final-use/CNS cutover before any production mutation.
    pub fn verify_selected_candidate(
        &self,
        selected: &VerifiedSelfEvolutionSelectionV1,
    ) -> Result<(), CellSplitErrorV1> {
        self.validate()?;
        let receipt = selected.receipt();
        if selected.selection_digest() != self.selection_digest
            || receipt.objective_digest != self.objective_digest
            || receipt.no_change_baseline_id != self.no_change_baseline_id
            || receipt.no_change_baseline_digest != self.no_change_baseline_digest
            || receipt.dataset_digest != self.evaluation_dataset_digest
            || receipt.minimum_future_window_micros < self.minimum_future_window_micros
            || receipt.predecessor_id != self.predecessor_id
            || receipt.predecessor_generation != self.predecessor_generation
            || receipt.predecessor_artifact_digest != self.predecessor_artifact_digest
            || receipt.candidate_id != self.selected_candidate_id
            || receipt.candidate_generation != self.child_generation
            || receipt.candidate_artifact_digest != self.child_artifact_digest
            || receipt.authority.grants_any()
        {
            return Err(CellSplitErrorV1::Unapproved);
        }
        Ok(())
    }

    /// Verify the actual native artifact payload against the separately
    /// admitted immutable registry and an authority-verified CURRENT view.
    /// This read-only helper cannot publish a CAS object or approve a split.
    /// The product port MUST still execute the create-only CAS publication,
    /// retain the original signed publication receipt and recheck CURRENT
    /// eligibility at the final-use boundary. The effect's observer/receipt
    /// and idempotent operation key are owned by the production adapter.
    pub fn verify_current_child_artifact(
        &self,
        candidate: &mut RevalidatingCandidate,
        current: VerifiedCurrentRegistryViewV1,
    ) -> Result<(), CellSplitErrorV1> {
        self.validate()?;
        let manifest = &candidate.spec().manifest;
        if current.receipt().binding != self.artifact_storage_binding_digest
            || manifest.artifact_id != self.child_artifact_id
            || manifest.predecessor_id.as_ref() != Some(&self.predecessor_artifact_id)
            || manifest.generation != self.child_generation
            || manifest.content_digest != self.child_artifact_digest
        {
            return Err(CellSplitErrorV1::Conflict);
        }
        let actual = candidate
            .with_current(current, Digest32::of_bytes)
            .map_err(|_| CellSplitErrorV1::Conflict)?;
        if actual != self.child_artifact_digest {
            return Err(CellSplitErrorV1::Conflict);
        }
        Ok(())
    }

    pub fn operation_key(&self, step: CellSplitStepV1) -> Digest32 {
        let mut bytes = b"hepta.agentd.cell-split.effect.v1\0".to_vec();
        bytes.extend_from_slice(self.binding_digest().as_array());
        bytes.push(step as u8);
        Digest32::of_bytes(&bytes)
    }
}

/// Strict order. Selection and authorization are independent read-only gates.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u8)]
pub enum CellSplitStepV1 {
    ArtifactCas = 1,
    StateMigration = 2,
    ShadowChild = 3,
    IndependentSelection = 4,
    FinalUseReady = 5,
    SupervisorFence = 6,
    CnsRouteCutover = 7,
}

const STEPS: [CellSplitStepV1; 7] = [
    CellSplitStepV1::ArtifactCas,
    CellSplitStepV1::StateMigration,
    CellSplitStepV1::ShadowChild,
    CellSplitStepV1::IndependentSelection,
    CellSplitStepV1::FinalUseReady,
    CellSplitStepV1::SupervisorFence,
    CellSplitStepV1::CnsRouteCutover,
];

impl CellSplitStepV1 {
    fn decode(value: u8) -> Result<Self, CellSplitErrorV1> {
        STEPS
            .iter()
            .copied()
            .find(|step| *step as u8 == value)
            .ok_or(CellSplitErrorV1::Corrupt)
    }
}

/// Raw bytes from the real owner (typically its signed durable receipt) plus
/// the exact operation and generation being observed. No synthetic receipts.
/// The port MUST independently authenticate these bytes and current owner state.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitExternalReceiptV1 {
    pub operation_key: Digest32,
    pub generation: Generation,
    pub evidence: Vec<u8>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellSplitObservationV1 {
    /// Only a definitive read from the authoritative owner may return Missing.
    /// Timeouts, stale replicas, unknown commit outcomes or missing receipts
    /// MUST return Indeterminate, not Missing.
    Missing,
    Applied(CellSplitExternalReceiptV1),
}

/// Production implementation must be backed by real independent owners.
/// All mutation calls must use operation_key for idempotence and expected
/// predecessor generation for compare-and-swap fencing. In particular:
/// - ArtifactCas writes/reads actual bytes from the immutable artifact owner.
/// - StateMigration commits a real checkpoint and its durable receipt.
/// - ShadowChild boots a real child, without routing production work to it.
/// - observe/verify inspect independently authenticated current owner state.
/// - fence_predecessor durably forbids old-generation writers.
/// - cutover_with_final_use must consume an independently issued signed
///   Final-use grant AT the effect boundary and CAS the actual CNS route.
/// The executor never manufactures evaluation, selection or authority evidence.
pub trait CellSplitExecutionPortsV1 {
    fn observe(
        &mut self,
        plan: &CellSplitPlanV1,
        step: CellSplitStepV1,
    ) -> Result<CellSplitObservationV1, CellSplitErrorV1>;

    fn verify(
        &mut self,
        plan: &CellSplitPlanV1,
        step: CellSplitStepV1,
        receipt: &CellSplitExternalReceiptV1,
    ) -> Result<(), CellSplitErrorV1>;

    /// Durably advance an INDEPENDENT, authenticated rollback-protected
    /// observer witness. Return only after the observer acknowledges the exact
    /// plan and chain head. Timeouts and conflicting high-watermarks fail closed.
    /// Repeating the exact anchor must be idempotent.
    fn retain_ledger_anchor(
        &mut self,
        plan: &CellSplitPlanV1,
        anchor: CellSplitLedgerAnchorV1,
    ) -> Result<(), CellSplitErrorV1>;

    fn publish_artifact(
        &mut self,
        plan: &CellSplitPlanV1,
        key: Digest32,
    ) -> Result<(), CellSplitErrorV1>;

    fn migrate_child(
        &mut self,
        plan: &CellSplitPlanV1,
        key: Digest32,
    ) -> Result<(), CellSplitErrorV1>;

    fn start_shadow(
        &mut self,
        plan: &CellSplitPlanV1,
        key: Digest32,
    ) -> Result<(), CellSplitErrorV1>;

    fn fence_predecessor(
        &mut self,
        plan: &CellSplitPlanV1,
        key: Digest32,
    ) -> Result<(), CellSplitErrorV1>;

    /// Reverify the SAME independently verified selection and signed grant
    /// accepted earlier. Consume authorization at the real CNS CAS boundary,
    /// never by trusting a previously captured digest or issuance alone.
    fn cutover_with_final_use(
        &mut self,
        plan: &CellSplitPlanV1,
        key: Digest32,
        selection: &CellSplitExternalReceiptV1,
        final_use: &CellSplitExternalReceiptV1,
    ) -> Result<(), CellSplitErrorV1>;
}

/// Must be independently retained and authenticated by the hosting observer.
/// A valid-prefix rollback is not detectable using the journal alone.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CellSplitLedgerAnchorV1 {
    pub sequence: u64,
    pub head_digest: Digest32,
}

/// Recovery anchor source owned by an independent observer, not the split
/// journal itself. Implementations must authenticate the observer and verify
/// the exact split plan, monotonic high-watermark and integrity chain.
///
/// A digest computed by reading the suspect journal does not satisfy this
/// contract. If the observer is missing, unreachable or inconsistent, recovery
/// MUST fail closed without repairing or replaying the ledger.
pub trait CellSplitRecoveryObserverV1 {
    fn verified_anchor(
        &mut self,
        plan: &CellSplitPlanV1,
    ) -> Result<CellSplitLedgerAnchorV1, CellSplitErrorV1>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitProgressV1 {
    pub completed: bool,
    pub accepted_steps: usize,
    pub anchor: CellSplitLedgerAnchorV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellSplitErrorV1 {
    Busy,
    NotRegular,
    InvalidPlan,
    AlreadyInitialized,
    ScopeMismatch,
    AnchorMismatch,
    Corrupt,
    Capacity,
    Conflict,
    Unapproved,
    Indeterminate,
    Poisoned,
    Backend(&'static str),
    Io(std::io::ErrorKind),
}

impl fmt::Display for CellSplitErrorV1 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl StdError for CellSplitErrorV1 {}
impl From<std::io::Error> for CellSplitErrorV1 {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value.kind())
    }
}

#[derive(Clone, Debug)]
struct LedgerFrame {
    step: CellSplitStepV1,
    accepted: Option<CellSplitExternalReceiptV1>,
}

struct LockedFile(File);
impl LockedFile {
    fn acquire(file: File) -> Result<Self, CellSplitErrorV1> {
        if !file.metadata()?.is_file() {
            return Err(CellSplitErrorV1::NotRegular);
        }
        match file.try_lock() {
            Ok(()) => Ok(Self(file)),
            Err(TryLockError::WouldBlock) => Err(CellSplitErrorV1::Busy),
            Err(TryLockError::Error(error)) => Err(error.into()),
        }
    }
}
impl Drop for LockedFile {
    fn drop(&mut self) {
        let _ = self.0.unlock();
    }
}

/// Single owner of one bounded split transaction, with an append-only,
/// hash-chained ledger. The host supplies the private file and external anchor.
/// New/anchored open are deliberately separate to prevent silent re-bootstrap.
pub struct CellSplitExecutionOwnerV1 {
    file: LockedFile,
    plan: CellSplitPlanV1,
    accepted: Vec<CellSplitExternalReceiptV1>,
    pending: Option<CellSplitStepV1>,
    heads: Vec<Digest32>,
    // Prevent truncated/replaced ledger suffixes from being appended in the
    // same owner lifetime. The host still owns the private file/directory.
    durable_bytes: u64,
    // Never report completion before the independent observer has durably
    // acknowledged the exact last ledger head in this process.
    witnessed_sequence: Option<u64>,
    // A witness proves a historical ledger head, not the current state of
    // live CAS/Checkpoint/Selector/Fence/CNS owners. An unsuccessful replay or
    // observation must never leave a previous "completed" status latched.
    terminal_revalidated: bool,
    poisoned: bool,
}

impl CellSplitExecutionOwnerV1 {
    pub fn bootstrap(file: File, plan: CellSplitPlanV1) -> Result<Self, CellSplitErrorV1> {
        plan.validate()?;
        let mut file = LockedFile::acquire(file)?;
        if file.0.metadata()?.len() != 0 {
            return Err(CellSplitErrorV1::AlreadyInitialized);
        }
        let header = encode_header(&plan);
        // The host may hand us a genuinely empty file with an arbitrary
        // cursor. Never durably acknowledge a sparse, misplaced header.
        file.0.seek(SeekFrom::Start(0)).map_err(|_| CellSplitErrorV1::Indeterminate)?;
        file.0.write_all(&header).map_err(|_| CellSplitErrorV1::Indeterminate)?;
        file.0.sync_all().map_err(|_| CellSplitErrorV1::Indeterminate)?;
        Ok(Self {
            file,
            plan,
            accepted: Vec::new(),
            pending: None,
            heads: vec![Digest32::of_bytes(&header)],
            durable_bytes: HEADER_SIZE as u64,
            witnessed_sequence: None,
            terminal_revalidated: false,
            poisoned: false,
        })
    }

    /// Recover only from the independently authenticated observer high-watermark.
    /// A caller cannot turn bytes found in this file into recovery authority.
    pub fn recover_from_observer<O: CellSplitRecoveryObserverV1>(
        file: File,
        plan: CellSplitPlanV1,
        observer: &mut O,
    ) -> Result<Self, CellSplitErrorV1> {
        let anchor = observer.verified_anchor(&plan)?;
        Self::recover(file, plan, anchor)
    }

    /// Verify a trusted external anchor against the journal's full committed
    /// prefix. A valid tail beyond that anchor is retained for lost-ack
    /// reconciliation; a missing anchored predecessor is fatal. This primitive
    /// is private so product callers must use recover_from_observer.
    fn recover(
        file: File,
        plan: CellSplitPlanV1,
        external_anchor: CellSplitLedgerAnchorV1,
    ) -> Result<Self, CellSplitErrorV1> {
        plan.validate()?;
        let mut file = LockedFile::acquire(file)?;
        let length = usize::try_from(file.0.metadata()?.len())
            .map_err(|_| CellSplitErrorV1::Capacity)?;
        if !(HEADER_SIZE..=MAX_LEDGER_SIZE).contains(&length) {
            return Err(CellSplitErrorV1::Corrupt);
        }
        // Read the exact bounded length captured from the locked descriptor.
        // read_to_end could otherwise allocate without bound if a hostile
        // descriptor grows the inode while recovery is in progress.
        let mut bytes = vec![0_u8; length];
        file.0.seek(SeekFrom::Start(0))?;
        file.0.read_exact(&mut bytes)?;
        if file.0.metadata()?.len() != length as u64 {
            return Err(CellSplitErrorV1::Indeterminate);
        }
        if bytes[..HEADER_SIZE] != encode_header(&plan) {
            return Err(CellSplitErrorV1::ScopeMismatch);
        }

        let mut owner = Self {
            file,
            plan,
            accepted: Vec::new(),
            pending: None,
            heads: vec![Digest32::of_bytes(&bytes[..HEADER_SIZE])],
            durable_bytes: HEADER_SIZE as u64,
            witnessed_sequence: None,
            terminal_revalidated: false,
            poisoned: false,
        };
        let mut offset = HEADER_SIZE;
        while offset < length {
            if length - offset < 4 {
                break;
            }
            let frame_length = read_u32(&bytes[offset..offset + 4])? as usize;
            if !(FRAME_FIXED_SIZE..=MAX_FRAME_SIZE).contains(&frame_length) {
                return Err(CellSplitErrorV1::Corrupt);
            }
            if length - offset - 4 < frame_length {
                break;
            }
            let end = offset + 4 + frame_length;
            let expected_previous = *owner.heads.last().ok_or(CellSplitErrorV1::Corrupt)?;
            let frame = decode_frame(
                &bytes[offset + 4..end],
                owner.heads.len() as u64,
                expected_previous,
                &owner.plan,
            )?;
            owner.accept_replayed(frame)?;
            owner.heads.push(Digest32::of_bytes(&bytes[offset..end]));
            owner.durable_bytes = end as u64;
            offset = end;
        }

        let anchored = owner
            .heads
            .get(external_anchor.sequence as usize)
            .is_some_and(|digest| *digest == external_anchor.head_digest);
        if !anchored {
            return Err(CellSplitErrorV1::AnchorMismatch);
        }
        // Only an incomplete final frame is repairable, never a complete
        // invalid frame. A verified external anchor cannot be truncated.
        if offset != length {
            owner.file.0.set_len(offset as u64).map_err(|_| CellSplitErrorV1::Indeterminate)?;
            owner.file.0.sync_all().map_err(|_| CellSplitErrorV1::Indeterminate)?;
        }
        owner.file.0.seek(SeekFrom::End(0))?;
        Ok(owner)
    }

    pub fn anchor(&self) -> CellSplitLedgerAnchorV1 {
        CellSplitLedgerAnchorV1 {
            sequence: (self.heads.len() - 1) as u64,
            head_digest: self.heads[self.heads.len() - 1],
        }
    }

    pub fn progress(&self) -> CellSplitProgressV1 {
        CellSplitProgressV1 {
            completed: self.accepted.len() == STEPS.len()
                && self.witnessed_sequence == Some(self.anchor().sequence)
                && self.terminal_revalidated,
            accepted_steps: self.accepted.len(),
            anchor: self.anchor(),
        }
    }

    /// Every previously acknowledged effect is re-observed and verified before
    /// the next mutation. On a pending crash boundary, observe FIRST; only an
    /// authoritative Missing permits retry with the original idempotence key.
    pub fn drive<P: CellSplitExecutionPortsV1>(
        &mut self,
        ports: &mut P,
    ) -> Result<CellSplitProgressV1, CellSplitErrorV1> {
        // A prior successful replay does not attest to an external owner that
        // may have changed, been revoked, or become unreachable since then.
        self.terminal_revalidated = false;
        if self.poisoned {
            return Err(CellSplitErrorV1::Poisoned);
        }
        // The exact in-memory hash chain, not merely the file size, is the
        // expected live prefix. Detect same-length in-place corruption before
        // any external operation is permitted.
        self.verify_live_ledger()?;
        for (index, step) in STEPS.into_iter().enumerate() {
            if let Some(committed) = self.accepted.get(index) {
                validate_receipt(&self.plan, step, committed)?;
                ports.verify(&self.plan, step, committed)?;
                match ports.observe(&self.plan, step)? {
                    CellSplitObservationV1::Applied(current) if &current == committed => {
                        ports.verify(&self.plan, step, &current)?;
                    }
                    _ => return Err(CellSplitErrorV1::Conflict),
                }
                // Never advance the external witness over an unverified
                // recovered suffix. The pending or terminal boundary commits
                // the latest anchor only after all prior receipts pass.
                continue;
            }
            if self.pending.is_none() {
                self.append(LedgerFrame {
                    step,
                    accepted: None,
                })?;
            }
            if self.pending != Some(step) {
                return Err(CellSplitErrorV1::Corrupt);
            }
            // No external mutation before the pending intent is independently
            // acknowledged outside the potentially rolled-back ledger file.
            self.retain_anchor(ports)?;

            let observed = match ports.observe(&self.plan, step)? {
                CellSplitObservationV1::Applied(receipt) => {
                    CellSplitObservationV1::Applied(receipt)
                }
                CellSplitObservationV1::Missing => {
                    // An owner/observer callback may itself touch the backing
                    // file. Recheck immediately before dispatching an effect.
                    self.verify_live_ledger()?;
                    let key = self.plan.operation_key(step);
                    match step {
                        CellSplitStepV1::ArtifactCas => ports.publish_artifact(&self.plan, key)?,
                        CellSplitStepV1::StateMigration => ports.migrate_child(&self.plan, key)?,
                        CellSplitStepV1::ShadowChild => ports.start_shadow(&self.plan, key)?,
                        CellSplitStepV1::IndependentSelection
                        | CellSplitStepV1::FinalUseReady => {
                            // Evaluator, selector and issuer stay independent.
                            return Err(CellSplitErrorV1::Unapproved);
                        }
                        CellSplitStepV1::SupervisorFence => {
                            ports.fence_predecessor(&self.plan, key)?;
                        }
                        CellSplitStepV1::CnsRouteCutover => {
                            let selection = self.accepted.get(3)
                                .ok_or(CellSplitErrorV1::Unapproved)?;
                            let final_use = self.accepted.get(4)
                                .ok_or(CellSplitErrorV1::Unapproved)?;
                            validate_receipt(
                                &self.plan, CellSplitStepV1::IndependentSelection, selection,
                            )?;
                            validate_receipt(
                                &self.plan, CellSplitStepV1::FinalUseReady, final_use,
                            )?;
                            ports.cutover_with_final_use(&self.plan, key, selection, final_use)?;
                        }
                    }
                    ports.observe(&self.plan, step)?
                }
            };
            let CellSplitObservationV1::Applied(receipt) = observed else {
                return Err(CellSplitErrorV1::Indeterminate);
            };
            validate_receipt(&self.plan, step, &receipt)?;
            ports.verify(&self.plan, step, &receipt)?;
            self.append(LedgerFrame {
                step,
                accepted: Some(receipt),
            })?;
            // The next mutation must not run until this real receipt has
            // reached an independently protected observer high-watermark.
            self.retain_anchor(ports)?;
        }
        // Also reconcile fully recovered, already terminal owners: only
        // complete re-observation of every accepted external effect allows
        // witness advancement over an unauthenticated-but-valid journal tail.
        self.retain_anchor(ports)?;
        self.terminal_revalidated = true;
        Ok(self.progress())
    }

    /// Record successful independent high-watermark acknowledgement only
    /// after the observer has durably committed the exact chain head.
    fn retain_anchor<P: CellSplitExecutionPortsV1>(
        &mut self,
        ports: &mut P,
    ) -> Result<(), CellSplitErrorV1> {
        // Never send an anchor derived from a stale in-memory prefix when the
        // underlying bytes have been changed behind the owner's lock.
        self.verify_live_ledger()?;
        let anchor = self.anchor();
        ports.retain_ledger_anchor(&self.plan, anchor)?;
        self.witnessed_sequence = Some(anchor.sequence);
        Ok(())
    }

    /// The file lock excludes cooperative writers, but not a compromised
    /// holder of another descriptor to the same inode. Verify every recorded
    /// frame against the owner's already authenticated hash chain, including
    /// its boundaries. This is deliberately bounded to MAX_LEDGER_SIZE.
    ///
    /// Any read, length, framing, or digest mismatch irreversibly poisons the
    /// live owner. Recovery requires a *new* file handle and independently
    /// authenticated observer high-watermark; never re-seed from these bytes.
    fn verify_live_ledger(&mut self) -> Result<(), CellSplitErrorV1> {
        if self.poisoned {
            return Err(CellSplitErrorV1::Poisoned);
        }
        let checked = (|| -> Result<(), CellSplitErrorV1> {
            let length = usize::try_from(self.durable_bytes)
                .map_err(|_| CellSplitErrorV1::Capacity)?;
            if !(HEADER_SIZE..=MAX_LEDGER_SIZE).contains(&length)
                || self.file.0.metadata()?.len() != self.durable_bytes
            {
                return Err(CellSplitErrorV1::Corrupt);
            }
            let mut bytes = vec![0_u8; length];
            self.file.0.seek(SeekFrom::Start(0))?;
            self.file.0.read_exact(&mut bytes)?;
            let first = self.heads.first().ok_or(CellSplitErrorV1::Corrupt)?;
            if Digest32::of_bytes(&bytes[..HEADER_SIZE]) != *first {
                return Err(CellSplitErrorV1::Corrupt);
            }
            let mut offset = HEADER_SIZE;
            for expected in self.heads.iter().skip(1) {
                if length - offset < 4 {
                    return Err(CellSplitErrorV1::Corrupt);
                }
                let body_len = read_u32(&bytes[offset..offset + 4])? as usize;
                if !(FRAME_FIXED_SIZE..=MAX_FRAME_SIZE).contains(&body_len)
                    || length - offset - 4 < body_len
                {
                    return Err(CellSplitErrorV1::Corrupt);
                }
                let end = offset + 4 + body_len;
                if Digest32::of_bytes(&bytes[offset..end]) != *expected {
                    return Err(CellSplitErrorV1::Corrupt);
                }
                offset = end;
            }
            if offset != length || self.file.0.metadata()?.len() != self.durable_bytes {
                return Err(CellSplitErrorV1::Corrupt);
            }
            Ok(())
        })();
        if checked.is_err() {
            self.poisoned = true;
            return Err(CellSplitErrorV1::Poisoned);
        }
        Ok(())
    }

    fn accept_replayed(&mut self, frame: LedgerFrame) -> Result<(), CellSplitErrorV1> {
        apply_replayed_state(&self.plan, &mut self.accepted, &mut self.pending, frame)
    }

    fn append(&mut self, frame: LedgerFrame) -> Result<(), CellSplitErrorV1> {
        // Validate the exact persisted prefix even if a previous external
        // operation returned successfully but changed the ledger in place.
        self.verify_live_ledger()?;
        // Reject noncanonical transitions before touching the durable file.
        let mut accepted = self.accepted.clone();
        let mut pending = self.pending;
        apply_replayed_state(&self.plan, &mut accepted, &mut pending, frame.clone())?;
        // A duplicate descriptor is never an acknowledgement.
        let prev = self.anchor().head_digest;
        let bytes = encode_frame(
            &self.plan,
            frame.step,
            frame.accepted.as_ref(),
            self.heads.len() as u64,
            prev,
        )?;
        let physical_length = match self.file.0.metadata() {
            Ok(meta) => meta.len(),
            Err(_) => {
                self.poisoned = true;
                return Err(CellSplitErrorV1::Indeterminate);
            }
        };
        if physical_length != self.durable_bytes {
            self.poisoned = true;
            return Err(CellSplitErrorV1::Poisoned);
        }
        let next_length = self.durable_bytes
            .checked_add(bytes.len() as u64)
            .ok_or(CellSplitErrorV1::Capacity)?;
        if next_length > MAX_LEDGER_SIZE as u64 {
            return Err(CellSplitErrorV1::Capacity);
        }
        if self.file.0.seek(SeekFrom::End(0)).is_err()
            || self.file.0.write_all(&bytes).is_err()
            || self.file.0.sync_all().is_err()
        {
            self.poisoned = true;
            return Err(CellSplitErrorV1::Indeterminate);
        }
        self.accepted = accepted;
        self.pending = pending;
        self.heads.push(Digest32::of_bytes(&bytes));
        self.durable_bytes = next_length;
        Ok(())
    }
}

fn apply_replayed_state(
    plan: &CellSplitPlanV1,
    accepted: &mut Vec<CellSplitExternalReceiptV1>,
    pending: &mut Option<CellSplitStepV1>,
    frame: LedgerFrame,
) -> Result<(), CellSplitErrorV1> {
    let expected = STEPS.get(accepted.len()).copied().ok_or(CellSplitErrorV1::Corrupt)?;
    if frame.step != expected {
        return Err(CellSplitErrorV1::Corrupt);
    }
    match frame.accepted {
        None if pending.is_none() => *pending = Some(frame.step),
        Some(receipt) if *pending == Some(frame.step) => {
            validate_receipt(plan, frame.step, &receipt)
                .map_err(|_| CellSplitErrorV1::Corrupt)?;
            accepted.push(receipt);
            *pending = None;
        }
        _ => return Err(CellSplitErrorV1::Corrupt),
    }
    Ok(())
}

fn validate_receipt(
    plan: &CellSplitPlanV1,
    step: CellSplitStepV1,
    receipt: &CellSplitExternalReceiptV1,
) -> Result<(), CellSplitErrorV1> {
    if receipt.operation_key != plan.operation_key(step)
        || receipt.generation != plan.child_generation
        || receipt.evidence.is_empty()
        || receipt.evidence.len() > MAX_RECEIPT_BYTES
    {
        return Err(CellSplitErrorV1::Conflict);
    }
    Ok(())
}

fn encode_header(plan: &CellSplitPlanV1) -> Vec<u8> {
    let mut bytes = MAGIC.to_vec();
    bytes.extend_from_slice(plan.scope_digest.as_array());
    bytes.extend_from_slice(plan.binding_digest().as_array());
    let checksum = Digest32::of_bytes(&bytes);
    bytes.extend_from_slice(checksum.as_array());
    bytes
}

fn encode_frame(
    plan: &CellSplitPlanV1,
    step: CellSplitStepV1,
    accepted: Option<&CellSplitExternalReceiptV1>,
    sequence: u64,
    predecessor: Digest32,
) -> Result<Vec<u8>, CellSplitErrorV1> {
    if let Some(receipt) = accepted {
        validate_receipt(plan, step, receipt)?;
    }
    let mut body = Vec::with_capacity(FRAME_FIXED_SIZE + accepted.map_or(0, |r| r.evidence.len()));
    body.push(u8::from(accepted.is_some()));
    body.push(step as u8);
    body.extend_from_slice(&sequence.to_be_bytes());
    body.extend_from_slice(predecessor.as_array());
    body.extend_from_slice(plan.operation_key(step).as_array());
    body.extend_from_slice(
        &accepted.map_or(0, |receipt| receipt.generation.get()).to_be_bytes(),
    );
    let evidence = accepted.map_or(&[][..], |receipt| receipt.evidence.as_slice());
    body.extend_from_slice(&(evidence.len() as u32).to_be_bytes());
    body.extend_from_slice(evidence);
    let checksum = Digest32::of_bytes(&body);
    body.extend_from_slice(checksum.as_array());
    let mut frame = (body.len() as u32).to_be_bytes().to_vec();
    frame.extend_from_slice(&body);
    Ok(frame)
}

fn decode_frame(
    body: &[u8],
    expected_sequence: u64,
    predecessor: Digest32,
    plan: &CellSplitPlanV1,
) -> Result<LedgerFrame, CellSplitErrorV1> {
    if body.len() < FRAME_FIXED_SIZE {
        return Err(CellSplitErrorV1::Corrupt);
    }
    let without_checksum = body.len() - 32;
    if Digest32::of_bytes(&body[..without_checksum]).as_array()
        != &body[without_checksum..]
    {
        return Err(CellSplitErrorV1::Corrupt);
    }
    let step = CellSplitStepV1::decode(body[1])?;
    let evidence_length = read_u32(&body[82..86])? as usize;
    if body.len() != FRAME_FIXED_SIZE + evidence_length
        || evidence_length > MAX_RECEIPT_BYTES
        || read_u64(&body[2..10])? != expected_sequence
        || &body[10..42] != predecessor.as_array()
        || &body[42..74] != plan.operation_key(step).as_array()
    {
        return Err(CellSplitErrorV1::Corrupt);
    }
    let generation = read_u64(&body[74..82])?;
    let accepted = match body[0] {
        0 if evidence_length == 0 && generation == 0 => None,
        1 if evidence_length != 0 && generation == plan.child_generation.get() => {
            Some(CellSplitExternalReceiptV1 {
                operation_key: plan.operation_key(step),
                generation: plan.child_generation,
                evidence: body[86..without_checksum].to_vec(),
            })
        }
        _ => return Err(CellSplitErrorV1::Corrupt),
    };
    Ok(LedgerFrame { step, accepted })
}

fn read_u32(bytes: &[u8]) -> Result<u32, CellSplitErrorV1> {
    Ok(u32::from_be_bytes(bytes.try_into().map_err(|_| CellSplitErrorV1::Corrupt)?))
}
fn read_u64(bytes: &[u8]) -> Result<u64, CellSplitErrorV1> {
    Ok(u64::from_be_bytes(bytes.try_into().map_err(|_| CellSplitErrorV1::Corrupt)?))
}

#[cfg(test)]
#[path = "cell_split_owner_tests.rs"]
mod tests;
