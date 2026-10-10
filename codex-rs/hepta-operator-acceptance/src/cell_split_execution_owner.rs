//! Crash-recoverable, single-writer CellSplit execution *coordinator*.
//!
//! The coordinator does not fabricate a CAS/migration/CNS/Supervisor receipt.
//! Each port implementation must perform the actual operation against that
//! component's durable owner, authenticate its response against pinned trust,
//! and re-query the same owner after an ambiguous crash or lost acknowledgement.
//! No route, generation, selector or production authority is minted here.

use std::collections::BTreeSet;
use std::fs;
use std::io::ErrorKind;
use std::path::Path;
use std::path::PathBuf;

use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;
use thiserror::Error;

use crate::AcceptanceError;
use crate::durable::SidecarLock;
use crate::durable::canonical_json;
use crate::durable::lock_sidecar;
use crate::durable::secure_read;
use crate::durable::secure_root;
use crate::durable::sha256;
use crate::durable::write_private_new;

const SCHEMA: &str = "hepta.learning.cell-split.execution-owner.v1";
const MAX_RECORD_BYTES: usize = 64 * 1024;
const STEP_COUNT: usize = 4;

/// These are ordered *committed* owner operations, not digest declarations.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CellSplitExecutionStepV1 {
    ArtifactCas,
    ChildStateMigration,
    CnsRouteCutover,
    SupervisorGenerationFence,
}

impl CellSplitExecutionStepV1 {
    pub const fn index(self) -> usize {
        match self {
            Self::ArtifactCas => 0,
            Self::ChildStateMigration => 1,
            Self::CnsRouteCutover => 2,
            Self::SupervisorGenerationFence => 3,
        }
    }

    fn at(index: usize) -> Option<Self> {
        match index {
            0 => Some(Self::ArtifactCas),
            1 => Some(Self::ChildStateMigration),
            2 => Some(Self::CnsRouteCutover),
            3 => Some(Self::SupervisorGenerationFence),
            _ => None,
        }
    }
}

/// Frozen input for one split. The production caller must source these
/// identities and pins from verified Agentd/NDU/registry authority, not users.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitExecutionPlanV1 {
    pub split_id: String,
    pub scope_digest: String,
    pub parent_generation: u64,
    pub child_generation: u64,
    pub parent_artifact_digest: String,
    pub child_artifact_digest: String,
    pub ndu_snapshot_digest: String,
    pub route_fence_digest: String,
    pub owner_ids: [String; STEP_COUNT],
}

impl CellSplitExecutionPlanV1 {
    fn validate(&self) -> Result<(), CellSplitExecutionErrorV1> {
        let mut distinct_owners = BTreeSet::new();
        if self.split_id.is_empty()
            || self.split_id.len() > 256
            || self.parent_generation == 0
            || self.parent_generation.checked_add(1) != Some(self.child_generation)
            || self
                .owner_ids
                .iter()
                .any(|id| id.is_empty() || id.len() > 256 || !distinct_owners.insert(id))
        {
            return Err(CellSplitExecutionErrorV1::Invalid(
                "identity or generations",
            ));
        }
        for digest in [
            &self.scope_digest,
            &self.parent_artifact_digest,
            &self.child_artifact_digest,
            &self.ndu_snapshot_digest,
            &self.route_fence_digest,
        ] {
            if !valid_digest(digest) {
                return Err(CellSplitExecutionErrorV1::Invalid("unbound digest"));
            }
        }
        Ok(())
    }

    fn digest(&self) -> Result<String, CellSplitExecutionErrorV1> {
        Ok(sha256(&canonical_json(self)?))
    }
}

fn valid_digest(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
        && value.bytes().any(|byte| byte != b'0')
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitExecutionIntentV1 {
    pub schema: String,
    pub plan_digest: String,
    pub step: CellSplitExecutionStepV1,
    pub owner_id: String,
    pub idempotency_key: String,
    pub previous_receipt_digest: String,
}

/// Contains the raw typed operation receipt and its independent signature.
/// Neither a digest nor this envelope alone proves the effect occurred. The
/// port's verify_committed method MUST consult the appropriate real owner.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitExecutionReceiptV1 {
    pub intent: CellSplitExecutionIntentV1,
    pub owner_sequence: u64,
    pub output_digest: String,
    pub owner_receipt_bytes: Vec<u8>,
    pub owner_signature_bytes: Vec<u8>,
    pub receipt_digest: String,
}

/// Domain-separated signature payload shared with real external effect owners.
/// It binds the step, exact idempotency key, owner result and observed sequence.
/// A signature is not enough: read-after-write owner verification stays required.
pub fn cell_split_execution_signing_payload_v1(
    receipt: &CellSplitExecutionReceiptV1,
) -> Result<Vec<u8>, CellSplitExecutionErrorV1> {
    let mut unsigned = receipt.clone();
    unsigned.owner_signature_bytes.clear();
    unsigned.receipt_digest.clear();
    let mut payload = b"hepta.learning.cell-split.committed-effect.v1\0".to_vec();
    payload.extend_from_slice(&canonical_json(&unsigned)?);
    Ok(payload)
}

/// Pinned distinct signer keys, bound to a single immutable split and the
/// four fixed owner identities. Never accept the coordinator's own key as a
/// substitute for a real CAS/CNS/Supervisor operation receipt.
#[derive(Clone)]
pub struct CellSplitOwnerTrustV1 {
    plan_digest: String,
    owner_keys: [VerifyingKey; STEP_COUNT],
}

impl CellSplitOwnerTrustV1 {
    pub fn new(
        plan: &CellSplitExecutionPlanV1,
        keys: [VerifyingKey; STEP_COUNT],
    ) -> Result<Self, CellSplitExecutionErrorV1> {
        plan.validate()?;
        let mut seen = BTreeSet::new();
        if keys.iter().any(|key| !seen.insert(key.to_bytes())) {
            return Err(CellSplitExecutionErrorV1::Invalid(
                "effect owners share a signing key",
            ));
        }
        Ok(Self {
            plan_digest: plan.digest()?,
            owner_keys: keys,
        })
    }

    fn verify(
        &self,
        intent: &CellSplitExecutionIntentV1,
        receipt: &CellSplitExecutionReceiptV1,
    ) -> Result<(), CellSplitExecutionErrorV1> {
        if self.plan_digest != intent.plan_digest {
            return Err(CellSplitExecutionErrorV1::Invalid(
                "effect trust plan drift",
            ));
        }
        let signature = Signature::from_slice(&receipt.owner_signature_bytes)
            .map_err(|_| CellSplitExecutionErrorV1::Invalid("invalid owner signature"))?;
        self.owner_keys[intent.step.index()]
            .verify_strict(
                &cell_split_execution_signing_payload_v1(receipt)?,
                &signature,
            )
            .map_err(|_| CellSplitExecutionErrorV1::Invalid("untrusted effect owner"))?;
        Ok(())
    }
}

fn receipt_digest(
    receipt: &CellSplitExecutionReceiptV1,
) -> Result<String, CellSplitExecutionErrorV1> {
    let mut unsealed = receipt.clone();
    unsealed.receipt_digest.clear();
    Ok(sha256(&canonical_json(&unsealed)?))
}

/// The deployment's *real* CAS, child migration, CNS and Supervisor owners.
/// execute must use intent.idempotency_key as its durable effect key. reconcile
/// must read back an already committed result, not re-execute an uncertain
/// effect. verify_committed must authenticate and revalidate owner state.
/// Source-only mocks must never be wired to production activation.
pub trait CellSplitExecutionPortV1 {
    type Error: std::fmt::Display;

    fn execute(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<CellSplitExecutionReceiptV1, Self::Error>;

    fn reconcile(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<Option<CellSplitExecutionReceiptV1>, Self::Error>;

    fn verify_committed(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
        receipt: &CellSplitExecutionReceiptV1,
    ) -> Result<(), Self::Error>;
}

#[derive(Debug, Error)]
pub enum CellSplitExecutionErrorV1 {
    #[error("cell split owner rejected input: {0}")]
    Invalid(&'static str),
    #[error("cell split step has an ambiguous outcome; reconcile against the real owner")]
    Ambiguous,
    #[error("cell split external owner failed: {0}")]
    External(String),
    #[error(transparent)]
    Durable(#[from] AcceptanceError),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Codec(#[from] serde_json::Error),
}

/// Owns exactly one frozen split in an exclusively locked private directory.
/// All transitions are write-once, fsync'd frames. A step is *never* invoked
/// again after an intent frame exists: recovery instead queries the original
/// owner and verifies its actual signed commit receipt.
pub struct CellSplitExecutionOwnerV1<P: CellSplitExecutionPortV1> {
    root: PathBuf,
    plan: CellSplitExecutionPlanV1,
    plan_digest: String,
    port: P,
    trust: CellSplitOwnerTrustV1,
    cursor: usize,
    pending: bool,
    previous_receipt_digest: String,
    _lock: SidecarLock,
}

impl<P: CellSplitExecutionPortV1> CellSplitExecutionOwnerV1<P> {
    pub fn open(
        root: &Path,
        plan: CellSplitExecutionPlanV1,
        trust: CellSplitOwnerTrustV1,
        mut port: P,
    ) -> Result<Self, CellSplitExecutionErrorV1> {
        plan.validate()?;
        let root = secure_root(root, "cell split owner root")?;
        let lock = lock_sidecar(&root)?;
        let plan_digest = plan.digest()?;
        if trust.plan_digest != plan_digest {
            return Err(CellSplitExecutionErrorV1::Invalid("trusted plan mismatch"));
        }
        let path = root.join("cell-split-frozen-plan.json");
        let bytes = canonical_json(&plan)?;
        match read_frame(&path)? {
            Some(persisted) if persisted != bytes => {
                return Err(CellSplitExecutionErrorV1::Invalid("frozen plan changed"));
            }
            Some(_) => {}
            None => write_private_new(&path, &bytes)?,
        }

        let mut cursor = 0;
        let mut pending = false;
        let mut previous_receipt_digest = plan_digest.clone();
        for index in 0..STEP_COUNT {
            let step = CellSplitExecutionStepV1::at(index)
                .ok_or(CellSplitExecutionErrorV1::Invalid("step index"))?;
            let intent = make_intent(&plan, &plan_digest, step, &previous_receipt_digest);
            let expected = canonical_json(&intent)?;
            let prepared = read_frame(&frame_path(&root, index, "prepared"))?;
            let committed = read_frame(&frame_path(&root, index, "committed"))?;
            match (prepared, committed) {
                (None, None) => {
                    if (index + 1..STEP_COUNT).any(|later| {
                        frame_path(&root, later, "prepared").exists()
                            || frame_path(&root, later, "committed").exists()
                    }) {
                        return Err(CellSplitExecutionErrorV1::Invalid("non-prefix history"));
                    }
                    break;
                }
                (None, Some(_)) => {
                    return Err(CellSplitExecutionErrorV1::Invalid("commit without intent"));
                }
                (Some(stored), outcome) => {
                    if stored != expected {
                        return Err(CellSplitExecutionErrorV1::Invalid(
                            "prepared intent changed",
                        ));
                    }
                    if let Some(bytes) = outcome {
                        let receipt: CellSplitExecutionReceiptV1 = serde_json::from_slice(&bytes)?;
                        validate_receipt(&intent, &receipt)?;
                        trust.verify(&intent, &receipt)?;
                        port.verify_committed(&intent, &receipt).map_err(|error| {
                            CellSplitExecutionErrorV1::External(error.to_string())
                        })?;
                        previous_receipt_digest = receipt.receipt_digest;
                        cursor += 1;
                    } else {
                        pending = true;
                        if (index + 1..STEP_COUNT).any(|later| {
                            frame_path(&root, later, "prepared").exists()
                                || frame_path(&root, later, "committed").exists()
                        }) {
                            return Err(CellSplitExecutionErrorV1::Invalid(
                                "pending step has successors",
                            ));
                        }
                        break;
                    }
                }
            }
        }
        Ok(Self {
            root,
            plan,
            plan_digest,
            port,
            trust,
            cursor,
            pending,
            previous_receipt_digest,
            _lock: lock,
        })
    }

    #[must_use]
    pub fn completed_steps(&self) -> usize {
        self.cursor
    }

    #[must_use]
    pub fn is_complete(&self) -> bool {
        self.cursor == STEP_COUNT
    }

    /// Read each committed predecessor back from the durable ledger and from
    /// its real owner immediately before a successor is dispatched. An external
    /// rollback, stale route or post-open sidecar tamper must fence execution,
    /// even when the coordinator previously opened successfully.
    pub fn verify_committed_prefix(&mut self) -> Result<(), CellSplitExecutionErrorV1> {
        // A live coordinator must also re-validate its immutable plan before
        // every effect; validating it only at open leaves a post-open window.
        let frozen = read_frame(&self.root.join("cell-split-frozen-plan.json"))?.ok_or(
            CellSplitExecutionErrorV1::Invalid("frozen plan disappeared"),
        )?;
        if frozen != canonical_json(&self.plan)? {
            return Err(CellSplitExecutionErrorV1::Invalid("frozen plan drift"));
        }
        let mut predecessor = self.plan_digest.clone();
        for index in 0..self.cursor {
            let step = CellSplitExecutionStepV1::at(index)
                .ok_or(CellSplitExecutionErrorV1::Invalid("step index"))?;
            let intent = make_intent(&self.plan, &self.plan_digest, step, &predecessor);
            let prepared = read_frame(&frame_path(&self.root, index, "prepared"))?.ok_or(
                CellSplitExecutionErrorV1::Invalid("missing committed intent"),
            )?;
            if prepared != canonical_json(&intent)? {
                return Err(CellSplitExecutionErrorV1::Invalid("committed intent drift"));
            }
            let bytes = read_frame(&frame_path(&self.root, index, "committed"))?.ok_or(
                CellSplitExecutionErrorV1::Invalid("missing committed receipt"),
            )?;
            let receipt: CellSplitExecutionReceiptV1 = serde_json::from_slice(&bytes)?;
            validate_receipt(&intent, &receipt)?;
            self.trust.verify(&intent, &receipt)?;
            self.port
                .verify_committed(&intent, &receipt)
                .map_err(|error| CellSplitExecutionErrorV1::External(error.to_string()))?;
            predecessor = receipt.receipt_digest;
        }
        if predecessor != self.previous_receipt_digest {
            return Err(CellSplitExecutionErrorV1::Invalid("committed prefix drift"));
        }
        Ok(())
    }

    /// Advances at most one durable owner effect; never drives a later stage
    /// until the preceding owner receipt is authenticated and fsync'd.
    pub fn advance(
        &mut self,
    ) -> Result<Option<CellSplitExecutionReceiptV1>, CellSplitExecutionErrorV1> {
        self.verify_committed_prefix()?;
        let Some(step) = CellSplitExecutionStepV1::at(self.cursor) else {
            return Ok(None);
        };
        let intent = make_intent(
            &self.plan,
            &self.plan_digest,
            step,
            &self.previous_receipt_digest,
        );
        let pending = self.pending;
        if pending {
            // A lost acknowledgement cannot permit replacing or deleting the
            // prepared intent while this owner remains alive.
            let prepared = read_frame(&frame_path(&self.root, self.cursor, "prepared"))?.ok_or(
                CellSplitExecutionErrorV1::Invalid("pending intent disappeared"),
            )?;
            if prepared != canonical_json(&intent)? {
                return Err(CellSplitExecutionErrorV1::Invalid("pending intent drift"));
            }
        } else {
            write_private_new(
                &frame_path(&self.root, self.cursor, "prepared"),
                &canonical_json(&intent)?,
            )?;
            self.pending = true;
        }
        let receipt = if pending {
            self.port
                .reconcile(&intent)
                .map_err(|error| CellSplitExecutionErrorV1::External(error.to_string()))?
                .ok_or(CellSplitExecutionErrorV1::Ambiguous)?
        } else {
            self.port
                .execute(&intent)
                .map_err(|error| CellSplitExecutionErrorV1::External(error.to_string()))?
        };
        validate_receipt(&intent, &receipt)?;
        self.trust.verify(&intent, &receipt)?;
        self.port
            .verify_committed(&intent, &receipt)
            .map_err(|error| CellSplitExecutionErrorV1::External(error.to_string()))?;
        write_private_new(
            &frame_path(&self.root, self.cursor, "committed"),
            &canonical_json(&receipt)?,
        )?;
        self.previous_receipt_digest = receipt.receipt_digest.clone();
        self.cursor += 1;
        self.pending = false;
        Ok(Some(receipt))
    }
}

fn make_intent(
    plan: &CellSplitExecutionPlanV1,
    plan_digest: &str,
    step: CellSplitExecutionStepV1,
    predecessor: &str,
) -> CellSplitExecutionIntentV1 {
    let idempotency_key =
        sha256(format!("{SCHEMA}\0{plan_digest}\0{}\0{predecessor}", step.index()).as_bytes());
    CellSplitExecutionIntentV1 {
        schema: SCHEMA.to_string(),
        plan_digest: plan_digest.to_string(),
        step,
        owner_id: plan.owner_ids[step.index()].clone(),
        idempotency_key,
        previous_receipt_digest: predecessor.to_string(),
    }
}

fn validate_receipt(
    intent: &CellSplitExecutionIntentV1,
    receipt: &CellSplitExecutionReceiptV1,
) -> Result<(), CellSplitExecutionErrorV1> {
    if &receipt.intent != intent
        || receipt.owner_sequence == 0
        || !valid_digest(&receipt.output_digest)
        || !valid_digest(&receipt.receipt_digest)
        || receipt.owner_receipt_bytes.is_empty()
        || receipt.owner_signature_bytes.len() != 64
        || receipt.output_digest != sha256(&receipt.owner_receipt_bytes)
        || receipt.owner_receipt_bytes.len() > MAX_RECORD_BYTES / 2
        || receipt.owner_signature_bytes.len() > 4096
        || receipt.receipt_digest != receipt_digest(receipt)?
    {
        return Err(CellSplitExecutionErrorV1::Invalid(
            "unverified operation receipt",
        ));
    }
    Ok(())
}

fn frame_path(root: &Path, index: usize, phase: &str) -> PathBuf {
    root.join(format!("cell-split-{index:02}-{phase}.json"))
}

fn read_frame(path: &Path) -> Result<Option<Vec<u8>>, CellSplitExecutionErrorV1> {
    match fs::symlink_metadata(path) {
        Ok(_) => Ok(Some(secure_read(path, MAX_RECORD_BYTES)?)),
        Err(error) if error.kind() == ErrorKind::NotFound => Ok(None),
        Err(error) => Err(error.into()),
    }
}

#[cfg(test)]
#[path = "cell_split_execution_owner_tests.rs"]
mod tests;
