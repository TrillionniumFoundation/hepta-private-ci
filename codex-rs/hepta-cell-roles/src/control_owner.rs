//! Owner-facing lifecycle for control-plane cell roles.
//!
//! Planner, Router, Communication and ActionProposal adapters describe and
//! validate a request; they do not own a durable run, route registry,
//! transport, or effect provider.  This module is the common bridge contract
//! those real owners implement.  The deterministic owner below is a
//! repository-qualification harness: it proves idempotency, generation/fence
//! checks, terminal receipts and restart reconciliation without pretending to
//! be a live TaskFlow/CNS/transport/effect deployment.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::fs;
use std::fs::File;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::CellRoleV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::digest_bytes;

pub const CONTROL_OWNER_SCHEMA_V1: &str = "hepta.cell-role.control-owner.v1";
const DURABLE_CONTROL_MAGIC_V1: &[u8] = b"HEPTA-CONTROL-DISPATCH-SNAPSHOT-V1\0";
const DURABLE_CONTROL_MAX_FILE_BYTES_V1: usize = 128 * 1024 * 1024;
const DURABLE_CONTROL_MAX_RECORDS_V1: usize = 65_536;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub enum ControlOperationKindV1 {
    Planner,
    Router,
    Communication,
    ActionProposal,
}

impl ControlOperationKindV1 {
    pub const fn role(self) -> CellRoleV1 {
        match self {
            Self::Planner => CellRoleV1::Planner,
            Self::Router => CellRoleV1::Router,
            Self::Communication => CellRoleV1::Communication,
            Self::ActionProposal => CellRoleV1::ActionProposal,
        }
    }

    pub const fn tag(self) -> u8 {
        match self {
            Self::Planner => 0,
            Self::Router => 1,
            Self::Communication => 2,
            Self::ActionProposal => 3,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ControlDispatchStatusV1 {
    Prepared,
    Forwarded,
    Terminal,
    Rejected,
    Reconciled,
}

impl ControlDispatchStatusV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Prepared => 0,
            Self::Forwarded => 1,
            Self::Terminal => 2,
            Self::Rejected => 3,
            Self::Reconciled => 4,
        }
    }
}

/// Typed request handed to a durable TaskFlow, CNS, transport or effect
/// owner.  The request has no authority and does not contain executable
/// effect bytes; those stay in the downstream owner.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ControlDispatchIntentV1 {
    pub dispatch_id: StableId,
    pub cell_id: StableId,
    pub generation: Generation,
    pub scope_digest: Digest32,
    pub operation: ControlOperationKindV1,
    pub request_digest: Digest32,
    pub route_fence_digest: Digest32,
    pub idempotency_key_digest: Digest32,
    pub payload_digest: Digest32,
    pub precondition_digest: Digest32,
    pub effect_class_digest: Digest32,
    pub deadline_ms: u64,
    pub expiry_ms: u64,
    pub authority: AuthorityPosture,
}

impl ControlDispatchIntentV1 {
    pub fn validate(&self) -> Result<(), ControlOwnerErrorV1> {
        for (label, id) in [("dispatch", &self.dispatch_id), ("cell", &self.cell_id)] {
            if id.as_str().is_empty() {
                return Err(ControlOwnerErrorV1::EmptyId(label));
            }
        }
        for (label, digest) in [
            ("scope", self.scope_digest),
            ("request", self.request_digest),
            ("route fence", self.route_fence_digest),
            ("idempotency key", self.idempotency_key_digest),
            ("payload", self.payload_digest),
            ("precondition", self.precondition_digest),
            ("effect class", self.effect_class_digest),
        ] {
            if digest.is_zero() {
                return Err(ControlOwnerErrorV1::EmptyDigest(label));
            }
        }
        if self.deadline_ms > self.expiry_ms {
            return Err(ControlOwnerErrorV1::InvalidWindow);
        }
        if self.operation == ControlOperationKindV1::ActionProposal
            && self.effect_class_digest.is_zero()
        {
            return Err(ControlOwnerErrorV1::EffectBoundaryMissing);
        }
        if self.authority.grants_any() {
            return Err(ControlOwnerErrorV1::AuthorityGranted);
        }
        Ok(())
    }

    pub fn content_digest(&self) -> Result<Digest32, ControlOwnerErrorV1> {
        self.validate()?;
        Ok(digest_bytes(
            CONTROL_OWNER_SCHEMA_V1.as_bytes(),
            &[
                self.dispatch_id.as_str().as_bytes(),
                self.cell_id.as_str().as_bytes(),
                &self.generation.get().to_be_bytes(),
                &[self.operation.tag()],
                self.scope_digest.as_array(),
                self.request_digest.as_array(),
                self.route_fence_digest.as_array(),
                self.idempotency_key_digest.as_array(),
                self.payload_digest.as_array(),
                self.precondition_digest.as_array(),
                self.effect_class_digest.as_array(),
                &self.deadline_ms.to_be_bytes(),
                &self.expiry_ms.to_be_bytes(),
            ],
        ))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ControlDispatchReceiptV1 {
    pub dispatch_id: StableId,
    pub cell_id: StableId,
    pub generation: Generation,
    pub operation: ControlOperationKindV1,
    pub intent_digest: Digest32,
    pub route_fence_digest: Digest32,
    pub sequence: u64,
    pub status: ControlDispatchStatusV1,
    pub terminal_receipt_digest: Digest32,
    pub restart_reconciliation_digest: Option<Digest32>,
    pub execution_allowed: bool,
    pub authority: AuthorityPosture,
}

impl ControlDispatchReceiptV1 {
    pub fn validate(&self) -> Result<(), ControlOwnerErrorV1> {
        if self.dispatch_id.as_str().is_empty() || self.cell_id.as_str().is_empty() {
            return Err(ControlOwnerErrorV1::EmptyId("dispatch or cell"));
        }
        for (label, digest) in [
            ("intent", self.intent_digest),
            ("route fence", self.route_fence_digest),
            ("terminal", self.terminal_receipt_digest),
        ] {
            if digest.is_zero() {
                return Err(ControlOwnerErrorV1::EmptyDigest(label));
            }
        }
        if self.sequence == 0 || self.authority.grants_any() || self.execution_allowed {
            return Err(ControlOwnerErrorV1::AuthorityGranted);
        }
        match (self.status, self.restart_reconciliation_digest) {
            (ControlDispatchStatusV1::Reconciled, None) => {
                return Err(ControlOwnerErrorV1::ReconciliationMissing);
            }
            (ControlDispatchStatusV1::Reconciled, Some(digest)) if digest.is_zero() => {
                return Err(ControlOwnerErrorV1::EmptyDigest("restart reconciliation"));
            }
            (ControlDispatchStatusV1::Reconciled, Some(_)) => {}
            (_, Some(_)) => return Err(ControlOwnerErrorV1::UnexpectedReconciliation),
            (_, None) => {}
        }
        Ok(())
    }

    pub fn content_digest(&self) -> Result<Digest32, ControlOwnerErrorV1> {
        self.validate()?;
        Ok(digest_bytes(
            b"hepta.cell-role.control-dispatch-receipt.v1",
            &[
                self.dispatch_id.as_str().as_bytes(),
                self.cell_id.as_str().as_bytes(),
                &self.generation.get().to_be_bytes(),
                &[self.operation.tag(), self.status.tag()],
                self.intent_digest.as_array(),
                self.route_fence_digest.as_array(),
                &self.sequence.to_be_bytes(),
                self.terminal_receipt_digest.as_array(),
                self.restart_reconciliation_digest
                    .unwrap_or(Digest32::ZERO)
                    .as_array(),
            ],
        ))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ControlOwnerErrorV1 {
    EmptyId(&'static str),
    EmptyDigest(&'static str),
    InvalidWindow,
    EffectBoundaryMissing,
    AuthorityGranted,
    GenerationRegression,
    RouteFenceMismatch,
    IdempotencyConflict,
    MissingDispatch,
    InvalidPhase,
    Expired,
    IdempotencyKeyConflict,
    TerminalReceiptMissing,
    TerminalReceiptConflict,
    ReconciliationMissing,
    UnexpectedReconciliation,
    DurableIo,
    InvalidDurableSnapshot,
    WriterUnavailable,
    StaleWriter,
    BackendReceiptMismatch,
}

impl fmt::Display for ControlOwnerErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ControlOwnerErrorV1 {}

pub trait ControlRoleOwnerV1 {
    fn prepare(
        &mut self,
        intent: ControlDispatchIntentV1,
    ) -> Result<ControlDispatchReceiptV1, ControlOwnerErrorV1>;
    fn forward(
        &mut self,
        dispatch_id: &StableId,
    ) -> Result<ControlDispatchReceiptV1, ControlOwnerErrorV1>;
    fn record_terminal(
        &mut self,
        dispatch_id: &StableId,
        terminal_receipt_digest: Digest32,
    ) -> Result<ControlDispatchReceiptV1, ControlOwnerErrorV1>;
    fn reconcile_restart(
        &mut self,
        dispatch_id: &StableId,
    ) -> Result<ControlDispatchReceiptV1, ControlOwnerErrorV1>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct ControlDispatchRecordV1 {
    intent: ControlDispatchIntentV1,
    intent_digest: Digest32,
    receipt: ControlDispatchReceiptV1,
}

/// Deterministic owner used for repository qualification.  A production
/// implementation replaces its map with the durable TaskFlow/CNS/transport/
/// effect store while preserving these fences and receipt transitions.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct InMemoryControlRoleOwnerV1 {
    records: BTreeMap<StableId, ControlDispatchRecordV1>,
    idempotency_index: BTreeMap<Digest32, StableId>,
    active_generations: BTreeMap<StableId, (Generation, Digest32)>,
    next_sequence: u64,
    now_ms: u64,
}

/// File-backed control-plane owner.  It persists the exact intent and receipt
/// state machine used by the qualification owner, then reconstructs and
/// validates every record on restart.  It owns durable dispatch state; the
/// downstream TaskFlow/CNS/transport/effect worker still owns execution and
/// must supply the terminal receipt.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableControlRoleOwnerV1 {
    path: PathBuf,
    inner: InMemoryControlRoleOwnerV1,
}

impl DurableControlRoleOwnerV1 {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, ControlOwnerErrorV1> {
        let path = path.as_ref().to_path_buf();
        reject_durable_path(&path)?;
        let _writer_lock = lock_durable_control_writer(&path)?;
        if !path.exists() {
            let mut file = fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&path)
                .map_err(|_| ControlOwnerErrorV1::DurableIo)?;
            let mut initial = Vec::new();
            initial.extend_from_slice(DURABLE_CONTROL_MAGIC_V1);
            initial.extend_from_slice(&0_u32.to_be_bytes());
            initial.extend_from_slice(&0_u32.to_be_bytes());
            initial.extend_from_slice(&0_u64.to_be_bytes());
            initial.extend_from_slice(&0_u64.to_be_bytes());
            let checksum = digest_bytes(b"hepta.cell-role.control-owner.snapshot.v1", &[&initial]);
            file.write_all(&initial)
                .map_err(|_| ControlOwnerErrorV1::DurableIo)?;
            file.write_all(checksum.as_array())
                .map_err(|_| ControlOwnerErrorV1::DurableIo)?;
            file.sync_all()
                .map_err(|_| ControlOwnerErrorV1::DurableIo)?;
        }
        let bytes = fs::read(&path).map_err(|_| ControlOwnerErrorV1::DurableIo)?;
        let inner = decode_durable_control(&bytes)?;
        Ok(Self { path, inner })
    }

    // A stale process may not overwrite a newer durable generation or dispatch.
    // The OS lock spans read/compare/write/rename and the containing-dir sync.
    fn apply_mutation<T>(
        &mut self,
        mutation: impl FnOnce(&mut InMemoryControlRoleOwnerV1) -> Result<T, ControlOwnerErrorV1>,
    ) -> Result<T, ControlOwnerErrorV1> {
        let _writer_lock = lock_durable_control_writer(&self.path)?;
        let bytes = fs::read(&self.path).map_err(|_| ControlOwnerErrorV1::DurableIo)?;
        if decode_durable_control(&bytes)? != self.inner {
            return Err(ControlOwnerErrorV1::StaleWriter);
        }
        let mut candidate = self.inner.clone();
        let output = mutation(&mut candidate)?;
        // Avoid rewriting an entire snapshot on idempotent retries.
        if candidate != self.inner {
            persist_durable_control(&self.path, &candidate)?;
            self.inner = candidate;
        }
        Ok(output)
    }

    #[must_use]
    pub fn path(&self) -> &Path {
        &self.path
    }

    #[must_use]
    pub fn inner(&self) -> &InMemoryControlRoleOwnerV1 {
        &self.inner
    }

    /// Return the immutable dispatch intent that is bound to one durable
    /// outbox identity. Downstream owners must submit this exact value; a
    /// caller cannot construct a replacement payload after local forwarding.
    #[must_use]
    pub fn dispatch_intent(&self, dispatch_id: &StableId) -> Option<&ControlDispatchIntentV1> {
        self.inner.dispatch_intent(dispatch_id)
    }

    /// Return the locally persisted receipt for one dispatch after reopen.
    #[must_use]
    pub fn dispatch_receipt(&self, dispatch_id: &StableId) -> Option<&ControlDispatchReceiptV1> {
        self.inner.dispatch_receipt(dispatch_id)
    }

    pub fn set_now_ms(&mut self, now_ms: u64) -> Result<(), ControlOwnerErrorV1> {
        self.apply_mutation(|owner| {
            owner.set_now_ms(now_ms);
            Ok(())
        })
    }

    pub fn activate_generation(
        &mut self,
        cell_id: StableId,
        generation: Generation,
        route_fence_digest: Digest32,
    ) -> Result<Digest32, ControlOwnerErrorV1> {
        self.apply_mutation(|owner| owner.activate_generation(cell_id, generation, route_fence_digest))
    }
}

impl ControlRoleOwnerV1 for DurableControlRoleOwnerV1 {
    fn prepare(
        &mut self,
        intent: ControlDispatchIntentV1,
    ) -> Result<ControlDispatchReceiptV1, ControlOwnerErrorV1> {
        self.apply_mutation(|owner| owner.prepare(intent))
    }

    fn forward(
        &mut self,
        dispatch_id: &StableId,
    ) -> Result<ControlDispatchReceiptV1, ControlOwnerErrorV1> {
        self.apply_mutation(|owner| owner.forward(dispatch_id))
    }

    fn record_terminal(
        &mut self,
        dispatch_id: &StableId,
        terminal_receipt_digest: Digest32,
    ) -> Result<ControlDispatchReceiptV1, ControlOwnerErrorV1> {
        self.apply_mutation(|owner| owner.record_terminal(dispatch_id, terminal_receipt_digest))
    }

    fn reconcile_restart(
        &mut self,
        dispatch_id: &StableId,
    ) -> Result<ControlDispatchReceiptV1, ControlOwnerErrorV1> {
        self.apply_mutation(|owner| owner.reconcile_restart(dispatch_id))
    }
}

impl InMemoryControlRoleOwnerV1 {
    /// Return the immutable dispatch intent bound to one outbox identity.
    #[must_use]
    pub fn dispatch_intent(&self, dispatch_id: &StableId) -> Option<&ControlDispatchIntentV1> {
        self.records.get(dispatch_id).map(|record| &record.intent)
    }

    /// Return the local lifecycle receipt for one dispatch.
    #[must_use]
    pub fn dispatch_receipt(&self, dispatch_id: &StableId) -> Option<&ControlDispatchReceiptV1> {
        self.records.get(dispatch_id).map(|record| &record.receipt)
    }

    /// Set the owner clock used for expiry checks.  A production owner must
    /// source this value from its durable host clock, never from the request.
    pub fn set_now_ms(&mut self, now_ms: u64) {
        self.now_ms = now_ms;
    }

    /// Publish the generation/fence pair that a durable route or task owner
    /// currently accepts.  Replaying the same pair is idempotent; advancing
    /// the generation fences every older request.
    pub fn activate_generation(
        &mut self,
        cell_id: StableId,
        generation: Generation,
        route_fence_digest: Digest32,
    ) -> Result<Digest32, ControlOwnerErrorV1> {
        if cell_id.as_str().is_empty() {
            return Err(ControlOwnerErrorV1::EmptyId("cell"));
        }
        if route_fence_digest.is_zero() {
            return Err(ControlOwnerErrorV1::EmptyDigest("route fence"));
        }
        if let Some((active_generation, active_fence)) = self.active_generations.get(&cell_id) {
            if generation < *active_generation {
                return Err(ControlOwnerErrorV1::GenerationRegression);
            }
            if generation == *active_generation && route_fence_digest != *active_fence {
                return Err(ControlOwnerErrorV1::RouteFenceMismatch);
            }
        }
        self.active_generations
            .insert(cell_id.clone(), (generation, route_fence_digest));
        Ok(Digest32::of_parts(&[
            b"hepta.cell-role.control-generation-activation.v1",
            cell_id.as_str().as_bytes(),
            &generation.get().to_be_bytes(),
            route_fence_digest.as_array(),
        ]))
    }

    fn make_receipt(
        intent: &ControlDispatchIntentV1,
        intent_digest: Digest32,
        sequence: u64,
        status: ControlDispatchStatusV1,
        terminal: Digest32,
        reconciliation: Option<Digest32>,
    ) -> ControlDispatchReceiptV1 {
        ControlDispatchReceiptV1 {
            dispatch_id: intent.dispatch_id.clone(),
            cell_id: intent.cell_id.clone(),
            generation: intent.generation,
            operation: intent.operation,
            intent_digest,
            route_fence_digest: intent.route_fence_digest,
            sequence,
            status,
            terminal_receipt_digest: terminal,
            restart_reconciliation_digest: reconciliation,
            execution_allowed: false,
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    fn next_sequence(&mut self) -> Result<u64, ControlOwnerErrorV1> {
        self.next_sequence = self
            .next_sequence
            .checked_add(1)
            .ok_or(ControlOwnerErrorV1::InvalidPhase)?;
        Ok(self.next_sequence)
    }
}

impl ControlRoleOwnerV1 for InMemoryControlRoleOwnerV1 {
    fn prepare(
        &mut self,
        intent: ControlDispatchIntentV1,
    ) -> Result<ControlDispatchReceiptV1, ControlOwnerErrorV1> {
        intent.validate()?;
        if let Some((active_generation, active_fence)) =
            self.active_generations.get(&intent.cell_id)
        {
            if intent.generation != *active_generation {
                return Err(ControlOwnerErrorV1::GenerationRegression);
            }
            if intent.route_fence_digest != *active_fence {
                return Err(ControlOwnerErrorV1::RouteFenceMismatch);
            }
        }
        if self.now_ms >= intent.expiry_ms {
            return Err(ControlOwnerErrorV1::Expired);
        }
        let intent_digest = intent.content_digest()?;
        if let Some(existing) = self.records.get(&intent.dispatch_id) {
            if existing.intent_digest != intent_digest {
                return Err(ControlOwnerErrorV1::IdempotencyConflict);
            }
            return Ok(existing.receipt.clone());
        }
        if let Some(existing_dispatch) = self.idempotency_index.get(&intent.idempotency_key_digest)
            && existing_dispatch != &intent.dispatch_id
        {
            return Err(ControlOwnerErrorV1::IdempotencyKeyConflict);
        }
        let sequence = self.next_sequence()?;
        let terminal = Digest32::of_parts(&[
            b"hepta.cell-role.control-prepared.v1",
            intent_digest.as_array(),
        ]);
        let receipt = Self::make_receipt(
            &intent,
            intent_digest,
            sequence,
            ControlDispatchStatusV1::Prepared,
            terminal,
            None,
        );
        receipt.validate()?;
        let idempotency_key_digest = intent.idempotency_key_digest;
        let dispatch_id = intent.dispatch_id.clone();
        self.records.insert(
            dispatch_id.clone(),
            ControlDispatchRecordV1 {
                intent,
                intent_digest,
                receipt: receipt.clone(),
            },
        );
        self.idempotency_index
            .insert(idempotency_key_digest, dispatch_id);
        Ok(receipt)
    }

    fn forward(
        &mut self,
        dispatch_id: &StableId,
    ) -> Result<ControlDispatchReceiptV1, ControlOwnerErrorV1> {
        let record = self
            .records
            .get(dispatch_id)
            .cloned()
            .ok_or(ControlOwnerErrorV1::MissingDispatch)?;
        // A worker may retry a forward after its durable write succeeded.  The
        // terminal and reconciled states are immutable observations, so the
        // existing receipt is the idempotent answer.  A prepared record still
        // has to pass the current expiry and generation/fence checks below.
        if matches!(
            record.receipt.status,
            ControlDispatchStatusV1::Forwarded
                | ControlDispatchStatusV1::Terminal
                | ControlDispatchStatusV1::Reconciled
        ) {
            return Ok(record.receipt);
        }
        if record.receipt.status != ControlDispatchStatusV1::Prepared {
            return Err(ControlOwnerErrorV1::InvalidPhase);
        }
        if self.now_ms >= record.intent.expiry_ms {
            return Err(ControlOwnerErrorV1::Expired);
        }
        if let Some((active_generation, active_fence)) =
            self.active_generations.get(&record.intent.cell_id)
        {
            if record.intent.generation != *active_generation {
                return Err(ControlOwnerErrorV1::GenerationRegression);
            }
            if record.intent.route_fence_digest != *active_fence {
                return Err(ControlOwnerErrorV1::RouteFenceMismatch);
            }
        }
        let receipt = Self::make_receipt(
            &record.intent,
            record.intent_digest,
            record.receipt.sequence,
            ControlDispatchStatusV1::Forwarded,
            record.receipt.terminal_receipt_digest,
            None,
        );
        receipt.validate()?;
        self.records.insert(
            dispatch_id.clone(),
            ControlDispatchRecordV1 {
                receipt: receipt.clone(),
                ..record
            },
        );
        Ok(receipt)
    }

    fn record_terminal(
        &mut self,
        dispatch_id: &StableId,
        terminal_receipt_digest: Digest32,
    ) -> Result<ControlDispatchReceiptV1, ControlOwnerErrorV1> {
        if terminal_receipt_digest.is_zero() {
            return Err(ControlOwnerErrorV1::EmptyDigest("terminal"));
        }
        let record = self
            .records
            .get(dispatch_id)
            .cloned()
            .ok_or(ControlOwnerErrorV1::MissingDispatch)?;
        if matches!(
            record.receipt.status,
            ControlDispatchStatusV1::Terminal | ControlDispatchStatusV1::Reconciled
        ) {
            if record.receipt.terminal_receipt_digest == terminal_receipt_digest {
                return Ok(record.receipt);
            }
            return Err(ControlOwnerErrorV1::TerminalReceiptConflict);
        }
        if record.receipt.status != ControlDispatchStatusV1::Forwarded {
            return Err(ControlOwnerErrorV1::InvalidPhase);
        }
        let receipt = Self::make_receipt(
            &record.intent,
            record.intent_digest,
            record.receipt.sequence,
            ControlDispatchStatusV1::Terminal,
            terminal_receipt_digest,
            None,
        );
        receipt.validate()?;
        self.records.insert(
            dispatch_id.clone(),
            ControlDispatchRecordV1 {
                receipt: receipt.clone(),
                ..record
            },
        );
        Ok(receipt)
    }

    fn reconcile_restart(
        &mut self,
        dispatch_id: &StableId,
    ) -> Result<ControlDispatchReceiptV1, ControlOwnerErrorV1> {
        let record = self
            .records
            .get(dispatch_id)
            .cloned()
            .ok_or(ControlOwnerErrorV1::MissingDispatch)?;
        if record.receipt.status == ControlDispatchStatusV1::Reconciled {
            return Ok(record.receipt);
        }
        if !matches!(record.receipt.status, ControlDispatchStatusV1::Terminal) {
            return if record.receipt.status == ControlDispatchStatusV1::Forwarded {
                Err(ControlOwnerErrorV1::TerminalReceiptMissing)
            } else {
                Err(ControlOwnerErrorV1::InvalidPhase)
            };
        }
        let reconciliation = Digest32::of_parts(&[
            b"hepta.cell-role.control-restart-reconciliation.v1",
            record.intent_digest.as_array(),
            record.receipt.terminal_receipt_digest.as_array(),
        ]);
        let receipt = Self::make_receipt(
            &record.intent,
            record.intent_digest,
            record.receipt.sequence,
            ControlDispatchStatusV1::Reconciled,
            record.receipt.terminal_receipt_digest,
            Some(reconciliation),
        );
        receipt.validate()?;
        self.records.insert(
            dispatch_id.clone(),
            ControlDispatchRecordV1 {
                receipt: receipt.clone(),
                ..record
            },
        );
        Ok(receipt)
    }
}

// A separate lock inode survives replacing the current-state snapshot.
fn lock_durable_control_writer(path: &Path) -> Result<File, ControlOwnerErrorV1> {
    let lock_path = path.with_extension("control.writer.lock");
    reject_durable_path(&lock_path)?;
    let mut options = fs::OpenOptions::new();
    options.read(true).write(true).create(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let lock = options.open(&lock_path).map_err(|_| ControlOwnerErrorV1::DurableIo)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        let meta = lock.metadata().map_err(|_| ControlOwnerErrorV1::DurableIo)?;
        if !meta.is_file() || meta.nlink() != 1 || meta.mode() & 0o077 != 0 {
            return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
        }
    }
    lock.try_lock().map_err(|_| ControlOwnerErrorV1::WriterUnavailable)?;
    Ok(lock)
}

fn reject_durable_path(path: &Path) -> Result<(), ControlOwnerErrorV1> {
    if let Ok(metadata) = fs::symlink_metadata(path)
        && (metadata.file_type().is_symlink() || !metadata.is_file())
    {
        return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
    }
    Ok(())
}

fn persist_durable_control(
    path: &Path,
    owner: &InMemoryControlRoleOwnerV1,
) -> Result<(), ControlOwnerErrorV1> {
    reject_durable_path(path)?;
    let mut bytes = Vec::with_capacity(128 + owner.records.len() * 512);
    bytes.extend_from_slice(DURABLE_CONTROL_MAGIC_V1);
    put_u32(&mut bytes, owner.records.len())?;
    for record in owner.records.values() {
        encode_intent(&mut bytes, &record.intent)?;
        put_digest(&mut bytes, record.intent_digest);
        encode_receipt(&mut bytes, &record.receipt);
    }
    put_u32(&mut bytes, owner.active_generations.len())?;
    for (cell_id, (generation, fence)) in &owner.active_generations {
        put_id(&mut bytes, cell_id)?;
        put_u64(&mut bytes, generation.get());
        put_digest(&mut bytes, *fence);
    }
    put_u64(&mut bytes, owner.next_sequence);
    put_u64(&mut bytes, owner.now_ms);
    let checksum = digest_bytes(b"hepta.cell-role.control-owner.snapshot.v1", &[&bytes]);
    bytes.extend_from_slice(checksum.as_array());
    let temp = path.with_extension("control.snapshot.tmp");
    reject_durable_path(&temp)?;
    let mut file = fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&temp)
        .map_err(|_| ControlOwnerErrorV1::DurableIo)?;
    file.write_all(&bytes)
        .and_then(|_| file.sync_all())
        .map_err(|_| ControlOwnerErrorV1::DurableIo)?;
    drop(file);
    fs::rename(&temp, path).map_err(|_| ControlOwnerErrorV1::DurableIo)?;
    let parent = path.parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    File::open(parent)
        .and_then(|directory| directory.sync_all())
        .map_err(|_| ControlOwnerErrorV1::DurableIo)?;
    Ok(())
}

fn decode_durable_control(bytes: &[u8]) -> Result<InMemoryControlRoleOwnerV1, ControlOwnerErrorV1> {
    if bytes.len() > DURABLE_CONTROL_MAX_FILE_BYTES_V1 {
        return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
    }
    if bytes.len() < 32 {
        return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
    }
    let payload_length = bytes.len() - 32;
    let expected_checksum = Digest32::from_array(
        bytes[payload_length..]
            .try_into()
            .map_err(|_| ControlOwnerErrorV1::InvalidDurableSnapshot)?,
    );
    let actual_checksum = digest_bytes(
        b"hepta.cell-role.control-owner.snapshot.v1",
        &[&bytes[..payload_length]],
    );
    if expected_checksum != actual_checksum {
        return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
    }
    let mut cursor = ControlCursor::new(&bytes[..payload_length]);
    if cursor.take(DURABLE_CONTROL_MAGIC_V1.len())? != DURABLE_CONTROL_MAGIC_V1 {
        return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
    }
    let record_count = cursor.u32()? as usize;
    if record_count > DURABLE_CONTROL_MAX_RECORDS_V1 {
        return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
    }
    let mut owner = InMemoryControlRoleOwnerV1::default();
    for _ in 0..record_count {
        let intent = decode_intent(&mut cursor)?;
        let intent_digest = cursor.digest()?;
        if intent.content_digest()? != intent_digest {
            return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
        }
        let receipt = decode_receipt(&mut cursor)?;
        receipt.validate()?;
        if receipt.dispatch_id != intent.dispatch_id
            || receipt.cell_id != intent.cell_id
            || receipt.generation != intent.generation
            || receipt.operation != intent.operation
            || receipt.intent_digest != intent_digest
            || receipt.route_fence_digest != intent.route_fence_digest
        {
            return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
        }
        if owner
            .records
            .insert(
                intent.dispatch_id.clone(),
                ControlDispatchRecordV1 {
                    intent: intent.clone(),
                    intent_digest,
                    receipt,
                },
            )
            .is_some()
        {
            return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
        }
        if owner
            .idempotency_index
            .insert(intent.idempotency_key_digest, intent.dispatch_id.clone())
            .is_some()
        {
            return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
        }
    }
    let active_count = cursor.u32()? as usize;
    if active_count > DURABLE_CONTROL_MAX_RECORDS_V1 {
        return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
    }
    for _ in 0..active_count {
        let cell_id = cursor.id()?;
        let generation = Generation::new(cursor.u64()?)
            .map_err(|_| ControlOwnerErrorV1::InvalidDurableSnapshot)?;
        let fence = cursor.digest()?;
        if fence.is_zero()
            || owner
                .active_generations
                .insert(cell_id, (generation, fence))
                .is_some()
        {
            return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
        }
    }
    owner.next_sequence = cursor.u64()?;
    owner.now_ms = cursor.u64()?;
    if !cursor.is_empty() {
        return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
    }
    let max_sequence = owner
        .records
        .values()
        .map(|record| record.receipt.sequence)
        .max()
        .unwrap_or(0);
    if owner.next_sequence < max_sequence {
        return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
    }
    Ok(owner)
}

fn encode_intent(
    output: &mut Vec<u8>,
    intent: &ControlDispatchIntentV1,
) -> Result<(), ControlOwnerErrorV1> {
    intent.validate()?;
    put_id(output, &intent.dispatch_id)?;
    put_id(output, &intent.cell_id)?;
    put_u64(output, intent.generation.get());
    put_digest(output, intent.scope_digest);
    output.push(intent.operation.tag());
    for digest in [
        intent.request_digest,
        intent.route_fence_digest,
        intent.idempotency_key_digest,
        intent.payload_digest,
        intent.precondition_digest,
        intent.effect_class_digest,
    ] {
        put_digest(output, digest);
    }
    put_u64(output, intent.deadline_ms);
    put_u64(output, intent.expiry_ms);
    Ok(())
}

fn decode_intent(
    cursor: &mut ControlCursor<'_>,
) -> Result<ControlDispatchIntentV1, ControlOwnerErrorV1> {
    let intent = ControlDispatchIntentV1 {
        dispatch_id: cursor.id()?,
        cell_id: cursor.id()?,
        generation: Generation::new(cursor.u64()?)
            .map_err(|_| ControlOwnerErrorV1::InvalidDurableSnapshot)?,
        scope_digest: cursor.digest()?,
        operation: operation(cursor.byte()?)?,
        request_digest: cursor.digest()?,
        route_fence_digest: cursor.digest()?,
        idempotency_key_digest: cursor.digest()?,
        payload_digest: cursor.digest()?,
        precondition_digest: cursor.digest()?,
        effect_class_digest: cursor.digest()?,
        deadline_ms: cursor.u64()?,
        expiry_ms: cursor.u64()?,
        authority: AuthorityPosture::DENY_ALL,
    };
    intent.validate()?;
    Ok(intent)
}

fn encode_receipt(output: &mut Vec<u8>, receipt: &ControlDispatchReceiptV1) {
    put_id_unchecked(output, &receipt.dispatch_id);
    put_id_unchecked(output, &receipt.cell_id);
    put_u64(output, receipt.generation.get());
    output.push(receipt.operation.tag());
    put_digest(output, receipt.intent_digest);
    put_digest(output, receipt.route_fence_digest);
    put_u64(output, receipt.sequence);
    output.push(receipt.status.tag());
    put_digest(output, receipt.terminal_receipt_digest);
    match receipt.restart_reconciliation_digest {
        Some(digest) => {
            output.push(1);
            put_digest(output, digest);
        }
        None => output.push(0),
    }
}

fn decode_receipt(
    cursor: &mut ControlCursor<'_>,
) -> Result<ControlDispatchReceiptV1, ControlOwnerErrorV1> {
    let receipt = ControlDispatchReceiptV1 {
        dispatch_id: cursor.id()?,
        cell_id: cursor.id()?,
        generation: Generation::new(cursor.u64()?)
            .map_err(|_| ControlOwnerErrorV1::InvalidDurableSnapshot)?,
        operation: operation(cursor.byte()?)?,
        intent_digest: cursor.digest()?,
        route_fence_digest: cursor.digest()?,
        sequence: cursor.u64()?,
        status: status(cursor.byte()?)?,
        terminal_receipt_digest: cursor.digest()?,
        restart_reconciliation_digest: if cursor.byte()? == 0 {
            None
        } else {
            Some(cursor.digest()?)
        },
        execution_allowed: false,
        authority: AuthorityPosture::DENY_ALL,
    };
    Ok(receipt)
}

fn operation(tag: u8) -> Result<ControlOperationKindV1, ControlOwnerErrorV1> {
    match tag {
        0 => Ok(ControlOperationKindV1::Planner),
        1 => Ok(ControlOperationKindV1::Router),
        2 => Ok(ControlOperationKindV1::Communication),
        3 => Ok(ControlOperationKindV1::ActionProposal),
        _ => Err(ControlOwnerErrorV1::InvalidDurableSnapshot),
    }
}

fn status(tag: u8) -> Result<ControlDispatchStatusV1, ControlOwnerErrorV1> {
    match tag {
        0 => Ok(ControlDispatchStatusV1::Prepared),
        1 => Ok(ControlDispatchStatusV1::Forwarded),
        2 => Ok(ControlDispatchStatusV1::Terminal),
        3 => Ok(ControlDispatchStatusV1::Rejected),
        4 => Ok(ControlDispatchStatusV1::Reconciled),
        _ => Err(ControlOwnerErrorV1::InvalidDurableSnapshot),
    }
}

fn put_id(output: &mut Vec<u8>, id: &StableId) -> Result<(), ControlOwnerErrorV1> {
    if id.as_str().len() > u16::MAX as usize {
        return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
    }
    put_id_unchecked(output, id);
    Ok(())
}

fn put_id_unchecked(output: &mut Vec<u8>, id: &StableId) {
    output.extend_from_slice(&(id.as_str().len() as u16).to_be_bytes());
    output.extend_from_slice(id.as_str().as_bytes());
}

fn put_u32(output: &mut Vec<u8>, value: usize) -> Result<(), ControlOwnerErrorV1> {
    let value = u32::try_from(value).map_err(|_| ControlOwnerErrorV1::InvalidDurableSnapshot)?;
    output.extend_from_slice(&value.to_be_bytes());
    Ok(())
}

fn put_u64(output: &mut Vec<u8>, value: u64) {
    output.extend_from_slice(&value.to_be_bytes());
}

fn put_digest(output: &mut Vec<u8>, digest: Digest32) {
    output.extend_from_slice(digest.as_array());
}

struct ControlCursor<'a> {
    bytes: &'a [u8],
    position: usize,
}

impl<'a> ControlCursor<'a> {
    const fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, position: 0 }
    }

    fn take(&mut self, length: usize) -> Result<&'a [u8], ControlOwnerErrorV1> {
        let end = self
            .position
            .checked_add(length)
            .ok_or(ControlOwnerErrorV1::InvalidDurableSnapshot)?;
        if end > self.bytes.len() {
            return Err(ControlOwnerErrorV1::InvalidDurableSnapshot);
        }
        let value = &self.bytes[self.position..end];
        self.position = end;
        Ok(value)
    }

    fn byte(&mut self) -> Result<u8, ControlOwnerErrorV1> {
        Ok(self.take(1)?[0])
    }

    fn u32(&mut self) -> Result<u32, ControlOwnerErrorV1> {
        let mut bytes = [0; 4];
        bytes.copy_from_slice(self.take(4)?);
        Ok(u32::from_be_bytes(bytes))
    }

    fn u64(&mut self) -> Result<u64, ControlOwnerErrorV1> {
        let mut bytes = [0; 8];
        bytes.copy_from_slice(self.take(8)?);
        Ok(u64::from_be_bytes(bytes))
    }

    fn digest(&mut self) -> Result<Digest32, ControlOwnerErrorV1> {
        let mut bytes = [0; 32];
        bytes.copy_from_slice(self.take(32)?);
        Ok(Digest32::from_array(bytes))
    }

    fn id(&mut self) -> Result<StableId, ControlOwnerErrorV1> {
        let mut bytes = [0; 2];
        bytes.copy_from_slice(self.take(2)?);
        let length = u16::from_be_bytes(bytes) as usize;
        let value = std::str::from_utf8(self.take(length)?)
            .map_err(|_| ControlOwnerErrorV1::InvalidDurableSnapshot)?;
        StableId::new(value).map_err(|_| ControlOwnerErrorV1::InvalidDurableSnapshot)
    }

    fn is_empty(&self) -> bool {
        self.position == self.bytes.len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn digest(label: &str) -> Digest32 {
        Digest32::of_bytes(label.as_bytes())
    }

    fn intent(operation: ControlOperationKindV1) -> ControlDispatchIntentV1 {
        ControlDispatchIntentV1 {
            dispatch_id: StableId::new("dispatch.control").expect("id"),
            cell_id: StableId::new("cell.control").expect("id"),
            generation: Generation::new(3).expect("generation"),
            scope_digest: digest("scope"),
            operation,
            request_digest: digest("request"),
            route_fence_digest: digest("fence"),
            idempotency_key_digest: digest("idempotency"),
            payload_digest: digest("payload"),
            precondition_digest: digest("precondition"),
            effect_class_digest: digest("effect"),
            deadline_ms: 10,
            expiry_ms: 20,
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    #[test]
    fn control_owner_is_idempotent_and_reconciles_restart() {
        let mut owner = InMemoryControlRoleOwnerV1::default();
        owner
            .activate_generation(
                StableId::new("cell.control").expect("id"),
                Generation::new(3).expect("generation"),
                digest("fence"),
            )
            .expect("activate");
        let prepared = owner
            .prepare(intent(ControlOperationKindV1::Router))
            .expect("prepare");
        assert_eq!(
            owner
                .prepare(intent(ControlOperationKindV1::Router))
                .expect("retry"),
            prepared
        );
        let forwarded = owner.forward(&prepared.dispatch_id).expect("forward");
        let terminal = owner
            .record_terminal(&prepared.dispatch_id, digest("terminal"))
            .expect("terminal");
        assert_eq!(terminal.status, ControlDispatchStatusV1::Terminal);
        let reconciled = owner
            .reconcile_restart(&prepared.dispatch_id)
            .expect("reconcile");
        assert_eq!(reconciled.status, ControlDispatchStatusV1::Reconciled);
        assert!(reconciled.restart_reconciliation_digest.is_some());
        assert_ne!(forwarded, reconciled);
        let mut invalid = reconciled.clone();
        invalid.restart_reconciliation_digest = None;
        assert_eq!(
            invalid.validate(),
            Err(ControlOwnerErrorV1::ReconciliationMissing)
        );
        let mut invalid = forwarded.clone();
        invalid.restart_reconciliation_digest = Some(digest("unexpected-reconciliation"));
        assert_eq!(
            invalid.validate(),
            Err(ControlOwnerErrorV1::UnexpectedReconciliation)
        );
    }

    #[test]
    fn stale_generation_and_route_fence_are_rejected() {
        let mut owner = InMemoryControlRoleOwnerV1::default();
        owner
            .activate_generation(
                StableId::new("cell.control").expect("id"),
                Generation::new(4).expect("generation"),
                digest("fence.v2"),
            )
            .expect("activate");
        let mut stale = intent(ControlOperationKindV1::Router);
        stale.generation = Generation::new(3).expect("generation");
        assert_eq!(
            owner.prepare(stale),
            Err(ControlOwnerErrorV1::GenerationRegression)
        );
        let mut wrong_fence = intent(ControlOperationKindV1::Router);
        wrong_fence.generation = Generation::new(4).expect("generation");
        assert_eq!(
            owner.prepare(wrong_fence),
            Err(ControlOwnerErrorV1::RouteFenceMismatch)
        );
    }

    #[test]
    fn action_proposal_never_grants_effect_authority() {
        let mut owner = InMemoryControlRoleOwnerV1::default();
        let receipt = owner
            .prepare(intent(ControlOperationKindV1::ActionProposal))
            .expect("prepare");
        assert!(!receipt.execution_allowed);
        assert_eq!(receipt.status, ControlDispatchStatusV1::Prepared);
    }

    #[test]
    fn forward_rechecks_fence_and_restart_requires_terminal_receipt() {
        let mut owner = InMemoryControlRoleOwnerV1::default();
        owner
            .activate_generation(
                StableId::new("cell.control").expect("id"),
                Generation::new(3).expect("generation"),
                digest("fence"),
            )
            .expect("activate");
        let prepared = owner
            .prepare(intent(ControlOperationKindV1::Router))
            .expect("prepare");
        owner
            .activate_generation(
                StableId::new("cell.control").expect("id"),
                Generation::new(4).expect("generation"),
                digest("fence.v2"),
            )
            .expect("cutover");
        assert_eq!(
            owner.forward(&prepared.dispatch_id),
            Err(ControlOwnerErrorV1::GenerationRegression)
        );

        let mut fresh = InMemoryControlRoleOwnerV1::default();
        fresh
            .activate_generation(
                StableId::new("cell.control").expect("id"),
                Generation::new(3).expect("generation"),
                digest("fence"),
            )
            .expect("activate");
        let prepared = fresh
            .prepare(intent(ControlOperationKindV1::Router))
            .expect("prepare");
        fresh.forward(&prepared.dispatch_id).expect("forward");
        assert_eq!(
            fresh.reconcile_restart(&prepared.dispatch_id),
            Err(ControlOwnerErrorV1::TerminalReceiptMissing)
        );
    }

    #[test]
    fn idempotency_key_cannot_be_reused_by_another_dispatch() {
        let mut owner = InMemoryControlRoleOwnerV1::default();
        let first = owner
            .prepare(intent(ControlOperationKindV1::Planner))
            .expect("prepare");
        let mut duplicate = intent(ControlOperationKindV1::Planner);
        duplicate.dispatch_id = StableId::new("dispatch.control.other").expect("id");
        assert_eq!(
            owner.prepare(duplicate),
            Err(ControlOwnerErrorV1::IdempotencyKeyConflict)
        );
        assert_eq!(first.status, ControlDispatchStatusV1::Prepared);
    }

    #[test]
    fn terminal_and_reconciliation_retries_are_idempotent() {
        let mut owner = InMemoryControlRoleOwnerV1::default();
        let prepared = owner
            .prepare(intent(ControlOperationKindV1::Communication))
            .expect("prepare");
        let forwarded = owner.forward(&prepared.dispatch_id).expect("forward");
        assert_eq!(
            owner.forward(&prepared.dispatch_id).expect("forward retry"),
            forwarded
        );
        let terminal_digest = digest("terminal.retry");
        let terminal = owner
            .record_terminal(&prepared.dispatch_id, terminal_digest)
            .expect("terminal");
        assert_eq!(
            owner
                .record_terminal(&prepared.dispatch_id, terminal_digest)
                .expect("terminal retry"),
            terminal
        );
        assert_eq!(
            owner.record_terminal(&prepared.dispatch_id, digest("other")),
            Err(ControlOwnerErrorV1::TerminalReceiptConflict)
        );
        let reconciled = owner
            .reconcile_restart(&prepared.dispatch_id)
            .expect("reconcile");
        assert_eq!(
            owner
                .reconcile_restart(&prepared.dispatch_id)
                .expect("reconcile retry"),
            reconciled
        );
        assert_eq!(
            owner
                .forward(&prepared.dispatch_id)
                .expect("late forward retry"),
            reconciled
        );
    }

    struct DurableTestDirectory(std::path::PathBuf);

    impl DurableTestDirectory {
        fn new() -> Self {
            let root = std::env::temp_dir().join(format!(
                "hepta-control-exclusive-{}-{}",
                std::process::id(),
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .expect("clock")
                    .as_nanos()
            ));
            std::fs::create_dir(&root).expect("test directory");
            Self(root)
        }

        fn file(&self) -> std::path::PathBuf {
            self.0.join("control")
        }
    }

    impl Drop for DurableTestDirectory {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    #[test]
    fn durable_control_stale_open_owner_cannot_overwrite_newer_state() {
        let root = DurableTestDirectory::new();
        let path = root.file();
        let mut first = DurableControlRoleOwnerV1::open(&path).expect("first");
        let mut second = DurableControlRoleOwnerV1::open(&path).expect("second");
        first
            .activate_generation(
                StableId::new("cell.control").expect("id"),
                Generation::new(3).expect("generation"),
                digest("fence"),
            )
            .expect("committed generation");
        assert_eq!(
            second.prepare(intent(ControlOperationKindV1::Router)),
            Err(ControlOwnerErrorV1::StaleWriter)
        );
        let mut reopened = DurableControlRoleOwnerV1::open(&path).expect("reopen");
        let prepared = reopened
            .prepare(intent(ControlOperationKindV1::Router))
            .expect("new writer");
        assert_eq!(prepared.status, ControlDispatchStatusV1::Prepared);
        assert_eq!(
            first.forward(&prepared.dispatch_id),
            Err(ControlOwnerErrorV1::StaleWriter)
        );
    }

    #[test]
    fn durable_control_rejects_os_writer_lock_contention() {
        let root = DurableTestDirectory::new();
        let path = root.file();
        let mut owner = DurableControlRoleOwnerV1::open(&path).expect("open");
        let guard = lock_durable_control_writer(&path).expect("hold lock");
        assert_eq!(
            owner.prepare(intent(ControlOperationKindV1::ActionProposal)),
            Err(ControlOwnerErrorV1::WriterUnavailable)
        );
        drop(guard);
        owner
            .activate_generation(
                StableId::new("cell.control").expect("id"),
                Generation::new(3).expect("generation"),
                digest("fence"),
            )
            .expect("writer after release");
    }

    #[test]
    fn idempotent_durable_control_retry_does_not_rewrite_snapshot() {
        let root = DurableTestDirectory::new();
        let path = root.file();
        let mut owner = DurableControlRoleOwnerV1::open(&path).expect("open");
        owner
            .prepare(intent(ControlOperationKindV1::Planner))
            .expect("first");
        let before = std::fs::read(&path).expect("read");
        owner
            .prepare(intent(ControlOperationKindV1::Planner))
            .expect("repeat");
        assert_eq!(std::fs::read(&path).expect("read"), before);
    }

    #[test]
    fn durable_control_owner_reopens_terminal_chain_and_rejects_tamper() {
        let path = std::env::temp_dir().join(format!(
            "hepta-control-owner-{}-{}.bin",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock")
                .as_nanos()
        ));
        let mut owner = DurableControlRoleOwnerV1::open(&path).expect("open");
        owner
            .activate_generation(
                StableId::new("cell.control").expect("id"),
                Generation::new(3).expect("generation"),
                digest("fence"),
            )
            .expect("activate");
        let prepared = owner
            .prepare(intent(ControlOperationKindV1::Communication))
            .expect("prepare");
        owner.forward(&prepared.dispatch_id).expect("forward");
        owner
            .record_terminal(&prepared.dispatch_id, digest("terminal"))
            .expect("terminal");
        let mut restored = DurableControlRoleOwnerV1::open(&path).expect("reload");
        let reconciled = restored
            .inner()
            .records
            .get(&prepared.dispatch_id)
            .expect("record");
        assert_eq!(reconciled.receipt.status, ControlDispatchStatusV1::Terminal);
        let terminal = restored
            .record_terminal(&prepared.dispatch_id, digest("terminal"))
            .expect("terminal retry after restart");
        assert_eq!(terminal.status, ControlDispatchStatusV1::Terminal);
        let reconciliation = restored
            .reconcile_restart(&prepared.dispatch_id)
            .expect("reconcile after restart");
        assert_eq!(reconciliation.status, ControlDispatchStatusV1::Reconciled);
        assert_eq!(
            restored
                .reconcile_restart(&prepared.dispatch_id)
                .expect("reconcile retry after restart"),
            reconciliation
        );
        let mut bytes = std::fs::read(&path).expect("read");
        *bytes.last_mut().expect("bytes") ^= 0x40;
        std::fs::write(&path, bytes).expect("tamper");
        assert_eq!(
            DurableControlRoleOwnerV1::open(&path),
            Err(ControlOwnerErrorV1::InvalidDurableSnapshot)
        );
        let _ = std::fs::remove_file(path);
    }
}
