//! Crash-safe, single-writer Cell Split effect ledger.
//!
//! A split is a *saga*, not an atomic cross-owner transaction. Before dispatch,
//! write a durable intent. If a process dies after an effect but before its
//! receipt is committed, recovery ONLY performs a read-only reconciliation.
//! It never repeats an uncertain external effect. Native owners supply their
//! complete serialized receipt and independently observed readback; this owner
//! does not manufacture either. The resulting ledger does not itself authorize
//! production activation, physical splitting or parent retirement.

use std::collections::BTreeMap;
use std::fmt::Display;
use std::path::{Path, PathBuf};

use base64::Engine as _;
use base64::engine::general_purpose::STANDARD as BASE64;
use ed25519_dalek::{Signature, Verifier, VerifyingKey};
use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::durable::{
    SidecarLock, canonical_json, lock_sidecar, secure_read, secure_root, sha256,
    write_private_atomic_replace,
};

const SCHEMA: &str = "hepta.cell-split.execution-ledger.v1";
const LEDGER_FILE: &str = "cell-split-execution-ledger.json";
const LEDGER_TEMP: &str = "cell-split-execution-ledger.tmp";
const MAX_LEDGER_BYTES: usize = 1024 * 1024;
const MAX_PROOF_BYTES: usize = 64 * 1024;
const GENESIS: &str = "hepta.cell-split.execution-ledger.genesis.v1";

/// The drain fence is deliberately before CNS cutover, and the final fence
/// is committed after it. A child can never be selected merely because its
/// artifact or state has been written.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CellSplitEffectStepV1 {
    ArtifactCas,
    ChildStateMigration,
    SupervisorDrainFence,
    CnsRouteCutover,
    SupervisorGenerationFence,
}

impl CellSplitEffectStepV1 {
    pub const ORDER: [Self; 5] = [
        Self::ArtifactCas,
        Self::ChildStateMigration,
        Self::SupervisorDrainFence,
        Self::CnsRouteCutover,
        Self::SupervisorGenerationFence,
    ];
    const fn native_schema(self) -> &'static str {
        match self {
            Self::ArtifactCas => "hepta.native.cell-split.artifact-cas.v1",
            Self::ChildStateMigration => "hepta.native.cell-split.state-migration.v1",
            Self::SupervisorDrainFence => "hepta.native.cell-split.supervisor-drain.v1",
            Self::CnsRouteCutover => "hepta.native.cell-split.cns-cutover.v1",
            Self::SupervisorGenerationFence => "hepta.native.cell-split.supervisor-generation.v1",
        }
    }
}

/// Exact bytes emitted by the real owner and independently read back from its
/// persisted store. The signer and the independent observer both sign this
/// envelope, including its step, predecessor ledger head and operation ID.
/// Digests without materialized bytes and readback are never sufficient.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitNativeOperationReceiptV1 {
    pub step: CellSplitEffectStepV1,
    pub split_id: String,
    pub operation_id: String,
    pub parent_generation: u64,
    pub child_generation: u64,
    pub predecessor_ledger_head: String,
    pub native_receipt_schema: String,
    pub native_receipt_base64: String,
    pub native_readback_base64: String,
    pub native_receipt_sha256: String,
    pub signer_id: String,
    pub observer_id: String,
    pub owner_signature_base64: String,
    pub observer_signature_base64: String,
}

impl CellSplitNativeOperationReceiptV1 {
    /// The signature is over the *complete* transport, not a user-supplied
    /// digest. The omitted signature fields are canonical empty strings.
    pub fn signing_bytes(&self) -> Result<Vec<u8>, CellSplitExecutionErrorV1> {
        let mut unsigned = self.clone();
        unsigned.owner_signature_base64.clear();
        unsigned.observer_signature_base64.clear();
        canonical_json(&unsigned)
            .map_err(|error| CellSplitExecutionErrorV1::Store(error.to_string()))
    }
}

#[derive(Clone, Debug)]
pub struct CellSplitOperationTrustV1 {
    pub signer_id: String,
    pub owner_key: VerifyingKey,
    pub observer_id: String,
    pub observer_key: VerifyingKey,
}

impl CellSplitOperationTrustV1 {
    fn validate(&self) -> Result<(), CellSplitExecutionErrorV1> {
        if self.signer_id.is_empty()
            || self.observer_id.is_empty()
            || self.signer_id == self.observer_id
            || self.owner_key == self.observer_key
        {
            return Err(CellSplitExecutionErrorV1::Trust);
        }
        Ok(())
    }
}

/// A deployment adapter must execute native CAS/migration/CNS/Supervisor APIs
/// and return their materialized receipts. `reconcile` MUST be read-only and
/// prove the outcome of the *same* operation ID, without re-dispatching it.
/// A missing observation leaves the ledger in an unresolved intent state.
pub trait CellSplitNativeEffectPortV1 {
    type Error: Display;

    fn execute(
        &mut self,
        step: CellSplitEffectStepV1,
        operation_id: &str,
        predecessor_head: &str,
    ) -> Result<CellSplitNativeOperationReceiptV1, Self::Error>;

    fn reconcile(
        &mut self,
        step: CellSplitEffectStepV1,
        operation_id: &str,
        predecessor_head: &str,
    ) -> Result<Option<CellSplitNativeOperationReceiptV1>, Self::Error>;
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum EntryEffectV1 {
    Intent {
        step: CellSplitEffectStepV1,
        operation_id: String,
    },
    Committed {
        receipt: CellSplitNativeOperationReceiptV1,
    },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EntryV1 {
    predecessor: String,
    effect: EntryEffectV1,
    entry_digest: String,
}

impl EntryV1 {
    fn digest(&self) -> Result<String, CellSplitExecutionErrorV1> {
        let bytes = canonical_json(&(&self.predecessor, &self.effect))
            .map_err(|error| CellSplitExecutionErrorV1::Store(error.to_string()))?;
        Ok(sha256(
            &[b"hepta.cell-split.execution-entry.v1".as_slice(), &bytes].concat(),
        ))
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct LedgerV1 {
    schema: String,
    split_id: String,
    parent_generation: u64,
    child_generation: u64,
    entries: Vec<EntryV1>,
    head: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitPendingEffectV1 {
    pub step: CellSplitEffectStepV1,
    pub operation_id: String,
    pub predecessor_head: String,
}

#[derive(Debug, Error)]
pub enum CellSplitExecutionErrorV1 {
    #[error("Cell Split execution trust configuration is invalid")]
    Trust,
    #[error("Cell Split native receipt failed verification")]
    NativeReceipt,
    #[error("Cell Split operation is out of order or the ledger is corrupt")]
    Transition,
    #[error("Cell Split effect may have happened; reconcile without replay")]
    UncertainEffect,
    #[error("Cell Split ledger is complete; no new operation is allowed")]
    Complete,
    #[error("Cell Split external owner failed: {0}")]
    External(String),
    #[error("Cell Split durable store failed: {0}")]
    Store(String),
}

/// One locally exclusive execution authority for one split identity. The
/// private sidecar lock remains held until this owner is dropped.
pub struct CellSplitExecutionLedgerOwnerV1 {
    root: PathBuf,
    ledger: LedgerV1,
    trust: BTreeMap<CellSplitEffectStepV1, CellSplitOperationTrustV1>,
    _lock: SidecarLock,
}

impl CellSplitExecutionLedgerOwnerV1 {
    pub fn open(
        root: impl AsRef<Path>,
        split_id: &str,
        parent_generation: u64,
        trust: BTreeMap<CellSplitEffectStepV1, CellSplitOperationTrustV1>,
    ) -> Result<Self, CellSplitExecutionErrorV1> {
        if split_id.is_empty()
            || split_id.len() > 200
            || parent_generation == 0
            || parent_generation == u64::MAX
            || trust.len() != CellSplitEffectStepV1::ORDER.len()
        {
            return Err(CellSplitExecutionErrorV1::Trust);
        }
        for step in CellSplitEffectStepV1::ORDER {
            trust
                .get(&step)
                .ok_or(CellSplitExecutionErrorV1::Trust)?
                .validate()?;
        }
        let root = secure_root(root.as_ref(), "split execution ledger root")
            .map_err(|error| CellSplitExecutionErrorV1::Store(error.to_string()))?;
        let lock = lock_sidecar(&root)
            .map_err(|error| CellSplitExecutionErrorV1::Store(error.to_string()))?;
        let path = root.join(LEDGER_FILE);
        let ledger = if path.exists() {
            let bytes = secure_read(&path, MAX_LEDGER_BYTES)
                .map_err(|error| CellSplitExecutionErrorV1::Store(error.to_string()))?;
            let ledger: LedgerV1 = serde_json::from_slice(&bytes)
                .map_err(|error| CellSplitExecutionErrorV1::Store(error.to_string()))?;
            if canonical_json(&ledger)
                .map_err(|error| CellSplitExecutionErrorV1::Store(error.to_string()))?
                != bytes
            {
                return Err(CellSplitExecutionErrorV1::Transition);
            }
            ledger
        } else {
            let child_generation = parent_generation + 1;
            let genesis = sha256(
                &canonical_json(&(GENESIS, split_id, parent_generation, child_generation))
                    .map_err(|error| CellSplitExecutionErrorV1::Store(error.to_string()))?,
            );
            LedgerV1 {
                schema: SCHEMA.to_owned(),
                split_id: split_id.to_owned(),
                parent_generation,
                child_generation,
                entries: Vec::new(),
                head: genesis,
            }
        };
        if ledger.schema != SCHEMA
            || ledger.split_id != split_id
            || ledger.parent_generation != parent_generation
            || ledger.child_generation != parent_generation + 1
        {
            return Err(CellSplitExecutionErrorV1::Transition);
        }
        let owner = Self {
            root,
            ledger,
            trust,
            _lock: lock,
        };
        owner.replay()?;
        if owner.ledger.entries.is_empty() {
            owner.persist(&owner.ledger)?;
        }
        Ok(owner)
    }

    #[must_use]
    pub fn head(&self) -> &str {
        &self.ledger.head
    }

    #[must_use]
    pub fn completed_steps(&self) -> usize {
        self.ledger
            .entries
            .iter()
            .filter(|entry| matches!(entry.effect, EntryEffectV1::Committed { .. }))
            .count()
    }

    #[must_use]
    pub fn complete(&self) -> bool {
        self.completed_steps() == CellSplitEffectStepV1::ORDER.len()
    }

    #[must_use]
    pub fn pending(&self) -> Option<CellSplitPendingEffectV1> {
        let entry = self.ledger.entries.last()?;
        let EntryEffectV1::Intent { step, operation_id } = &entry.effect else {
            return None;
        };
        Some(CellSplitPendingEffectV1 {
            step: *step,
            operation_id: operation_id.clone(),
            predecessor_head: entry.predecessor.clone(),
        })
    }

    pub fn execute_next<P: CellSplitNativeEffectPortV1>(
        &mut self,
        operation_id: &str,
        port: &mut P,
    ) -> Result<CellSplitNativeOperationReceiptV1, CellSplitExecutionErrorV1> {
        self.replay()?;
        if self.pending().is_some() {
            return Err(CellSplitExecutionErrorV1::UncertainEffect);
        }
        let completed = self.completed_steps();
        let step = *CellSplitEffectStepV1::ORDER
            .get(completed)
            .ok_or(CellSplitExecutionErrorV1::Complete)?;
        if operation_id.is_empty() || operation_id.len() > 200
            || self.ledger.entries.iter().any(|entry| matches!(&entry.effect, EntryEffectV1::Intent { operation_id: prior, .. } if prior == operation_id))
        {
            return Err(CellSplitExecutionErrorV1::Transition);
        }
        let predecessor_head = self.ledger.head.clone();
        self.append(EntryEffectV1::Intent {
            step,
            operation_id: operation_id.to_owned(),
        })?;
        // After this point ANY callback failure is an uncertain outcome.
        // Never synthesize a rollback or call execute twice.
        let receipt = port
            .execute(step, operation_id, &predecessor_head)
            .map_err(|error| CellSplitExecutionErrorV1::External(error.to_string()))?;
        self.finish_pending(receipt.clone())?;
        Ok(receipt)
    }

    /// Restart path. There is intentionally no automatic execute fallback.
    pub fn reconcile_pending<P: CellSplitNativeEffectPortV1>(
        &mut self,
        port: &mut P,
    ) -> Result<CellSplitNativeOperationReceiptV1, CellSplitExecutionErrorV1> {
        self.replay()?;
        let pending = self
            .pending()
            .ok_or(CellSplitExecutionErrorV1::Transition)?;
        let receipt = port
            .reconcile(
                pending.step,
                &pending.operation_id,
                &pending.predecessor_head,
            )
            .map_err(|error| CellSplitExecutionErrorV1::External(error.to_string()))?
            .ok_or(CellSplitExecutionErrorV1::UncertainEffect)?;
        self.finish_pending(receipt.clone())?;
        Ok(receipt)
    }

    fn finish_pending(
        &mut self,
        receipt: CellSplitNativeOperationReceiptV1,
    ) -> Result<(), CellSplitExecutionErrorV1> {
        let pending = self
            .pending()
            .ok_or(CellSplitExecutionErrorV1::Transition)?;
        self.verify_receipt(&receipt, &pending)?;
        self.append(EntryEffectV1::Committed { receipt })
    }

    fn verify_receipt(
        &self,
        receipt: &CellSplitNativeOperationReceiptV1,
        pending: &CellSplitPendingEffectV1,
    ) -> Result<(), CellSplitExecutionErrorV1> {
        let trust = self
            .trust
            .get(&pending.step)
            .ok_or(CellSplitExecutionErrorV1::Trust)?;
        if receipt.step != pending.step
            || receipt.split_id != self.ledger.split_id
            || receipt.operation_id != pending.operation_id
            || receipt.parent_generation != self.ledger.parent_generation
            || receipt.child_generation != self.ledger.child_generation
            || receipt.predecessor_ledger_head != pending.predecessor_head
            || receipt.native_receipt_schema != pending.step.native_schema()
            || receipt.signer_id != trust.signer_id
            || receipt.observer_id != trust.observer_id
        {
            return Err(CellSplitExecutionErrorV1::NativeReceipt);
        }
        let native = bounded_decode(&receipt.native_receipt_base64)?;
        let readback = bounded_decode(&receipt.native_readback_base64)?;
        if sha256(&native) != receipt.native_receipt_sha256 {
            return Err(CellSplitExecutionErrorV1::NativeReceipt);
        }
        // Both materialized receipts are typed JSON, not a caller-supplied
        // 32-byte hash standing in for an operation.
        let native_json: serde_json::Value = serde_json::from_slice(&native)
            .map_err(|_| CellSplitExecutionErrorV1::NativeReceipt)?;
        let readback_json: serde_json::Value = serde_json::from_slice(&readback)
            .map_err(|_| CellSplitExecutionErrorV1::NativeReceipt)?;
        if native_json.get("schema").and_then(|v| v.as_str())
            != Some(receipt.native_receipt_schema.as_str())
            || native_json.get("operationId").and_then(|v| v.as_str())
                != Some(receipt.operation_id.as_str())
            || native_json
                .get("commitWitness")
                .and_then(|v| v.as_str())
                .is_none_or(|s| !is_digest(s))
            || readback_json.get("operationId").and_then(|v| v.as_str())
                != Some(receipt.operation_id.as_str())
            || readback_json.get("receiptSha256").and_then(|v| v.as_str())
                != Some(receipt.native_receipt_sha256.as_str())
            || readback_json.get("committed").and_then(|v| v.as_bool()) != Some(true)
        {
            return Err(CellSplitExecutionErrorV1::NativeReceipt);
        }
        let payload = receipt.signing_bytes()?;
        let owner_signature = decode_signature(&receipt.owner_signature_base64)?;
        let observer_signature = decode_signature(&receipt.observer_signature_base64)?;
        trust
            .owner_key
            .verify(&payload, &owner_signature)
            .map_err(|_| CellSplitExecutionErrorV1::NativeReceipt)?;
        trust
            .observer_key
            .verify(&payload, &observer_signature)
            .map_err(|_| CellSplitExecutionErrorV1::NativeReceipt)?;
        Ok(())
    }

    fn append(&mut self, effect: EntryEffectV1) -> Result<(), CellSplitExecutionErrorV1> {
        let mut next = self.ledger.clone();
        let mut entry = EntryV1 {
            predecessor: next.head.clone(),
            effect,
            entry_digest: String::new(),
        };
        entry.entry_digest = entry.digest()?;
        next.head.clone_from(&entry.entry_digest);
        next.entries.push(entry);
        self.replay_ledger(&next)?;
        self.persist(&next)?;
        self.ledger = next;
        Ok(())
    }

    fn persist(&self, ledger: &LedgerV1) -> Result<(), CellSplitExecutionErrorV1> {
        let bytes = canonical_json(ledger)
            .map_err(|error| CellSplitExecutionErrorV1::Store(error.to_string()))?;
        if bytes.len() > MAX_LEDGER_BYTES {
            return Err(CellSplitExecutionErrorV1::Store(
                "ledger capacity exceeded".to_owned(),
            ));
        }
        write_private_atomic_replace(
            &self.root.join(LEDGER_FILE),
            &self.root.join(LEDGER_TEMP),
            &bytes,
        )
        .map_err(|error| CellSplitExecutionErrorV1::Store(error.to_string()))
    }

    fn replay(&self) -> Result<(), CellSplitExecutionErrorV1> {
        self.replay_ledger(&self.ledger)
    }

    fn replay_ledger(&self, ledger: &LedgerV1) -> Result<(), CellSplitExecutionErrorV1> {
        if ledger.entries.len() > CellSplitEffectStepV1::ORDER.len() * 2 {
            return Err(CellSplitExecutionErrorV1::Transition);
        }
        let mut head = sha256(
            &canonical_json(&(
                GENESIS,
                &ledger.split_id,
                ledger.parent_generation,
                ledger.child_generation,
            ))
            .map_err(|error| CellSplitExecutionErrorV1::Store(error.to_string()))?,
        );
        let mut completed = 0;
        let mut pending: Option<CellSplitPendingEffectV1> = None;
        for entry in &ledger.entries {
            if entry.predecessor != head || entry.entry_digest != entry.digest()? {
                return Err(CellSplitExecutionErrorV1::Transition);
            }
            match &entry.effect {
                EntryEffectV1::Intent { step, operation_id } => {
                    if pending.is_some()
                        || CellSplitEffectStepV1::ORDER.get(completed) != Some(step)
                        || operation_id.is_empty()
                    {
                        return Err(CellSplitExecutionErrorV1::Transition);
                    }
                    pending = Some(CellSplitPendingEffectV1 {
                        step: *step,
                        operation_id: operation_id.clone(),
                        predecessor_head: entry.predecessor.clone(),
                    });
                }
                EntryEffectV1::Committed { receipt } => {
                    let prior = pending
                        .take()
                        .ok_or(CellSplitExecutionErrorV1::Transition)?;
                    self.verify_receipt(receipt, &prior)?;
                    completed += 1;
                }
            }
            head = entry.entry_digest.clone();
        }
        if ledger.head != head {
            return Err(CellSplitExecutionErrorV1::Transition);
        }
        Ok(())
    }
}

fn is_digest(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
        && value.bytes().any(|b| b != b'0')
}

fn bounded_decode(encoded: &str) -> Result<Vec<u8>, CellSplitExecutionErrorV1> {
    if encoded.len() > MAX_PROOF_BYTES * 2 {
        return Err(CellSplitExecutionErrorV1::NativeReceipt);
    }
    let bytes = BASE64
        .decode(encoded)
        .map_err(|_| CellSplitExecutionErrorV1::NativeReceipt)?;
    if bytes.len() < 64 || bytes.len() > MAX_PROOF_BYTES {
        return Err(CellSplitExecutionErrorV1::NativeReceipt);
    }
    Ok(bytes)
}

fn decode_signature(encoded: &str) -> Result<Signature, CellSplitExecutionErrorV1> {
    let bytes = BASE64
        .decode(encoded)
        .map_err(|_| CellSplitExecutionErrorV1::NativeReceipt)?;
    Signature::from_slice(&bytes).map_err(|_| CellSplitExecutionErrorV1::NativeReceipt)
}

#[cfg(test)]
#[path = "cell_split_execution_ledger_tests.rs"]
mod tests;
