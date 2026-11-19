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
use crate::durable::lock_existing_sidecar;
use crate::durable::lock_sidecar;
use crate::durable::same_file_snapshot;
use crate::durable::secure_read_with_snapshot;
use crate::durable::secure_root;
use crate::durable::sha256;
use crate::durable::write_private_new;
use crate::durable::write_private_new_with_snapshot;

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
        if codex_hepta_types::StableId::new(self.split_id.clone()).is_err()
            || self.parent_generation == 0
            || self.parent_generation.checked_add(1) != Some(self.child_generation)
            || self.owner_ids.iter().any(|id| {
                codex_hepta_types::StableId::new(id.clone()).is_err() || !distinct_owners.insert(id)
            })
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

    /// Canonical plan digest used to bind external owner ports to the exact
    /// coordinator intent. This is an identity, never an authorization grant.
    pub fn digest(&self) -> Result<String, CellSplitExecutionErrorV1> {
        // Independent effect owners must reject an invalid split plan before
        // pinning its digest or opening a durable mutation namespace.
        self.validate()?;
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

/// Read-only evidence export after four current independent owner readbacks.
/// The coordinator cannot sign, promote or deploy this bundle: a separate
/// Observer must authenticate the original owners and target-host evidence.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitExecutionTranscriptV1 {
    pub plan: CellSplitExecutionPlanV1,
    pub receipts: Vec<CellSplitExecutionReceiptV1>,
    pub transcript_digest: String,
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
        if keys.iter().any(|key| key.is_weak()) {
            return Err(CellSplitExecutionErrorV1::Invalid(
                "effect owner has a weak signing key",
            ));
        }
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

    /// Used by independent Observer acceptance to prevent a purported host
    /// or observer from reusing one of the four effect-owner signing keys.
    pub(crate) fn contains_owner_key(&self, key: &VerifyingKey) -> bool {
        self.owner_keys.iter().any(|owner| owner == key)
    }

    /// The independent four-key trust set must match every live RPC reader
    /// key; accepting a caller-chosen second key set could fake freshness.
    pub(crate) fn owner_verifying_keys(&self) -> &[VerifyingKey; STEP_COUNT] {
        &self.owner_keys
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

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct CellSplitOwnerTrustPinsV1<'a> {
    schema: &'static str,
    plan_digest: &'a str,
    owner_ids: &'a [String; STEP_COUNT],
    verifying_keys: [[u8; 32]; STEP_COUNT],
}

/// A local write-once continuity record for independently pinned owner keys.
/// It does not mint authority or replace any fresh signed owner readback.
fn frozen_owner_trust_pins(
    plan: &CellSplitExecutionPlanV1,
    trust: &CellSplitOwnerTrustV1,
) -> Result<Vec<u8>, CellSplitExecutionErrorV1> {
    if trust.plan_digest != plan.digest()? {
        return Err(CellSplitExecutionErrorV1::Invalid("owner trust plan drift"));
    }
    Ok(canonical_json(&CellSplitOwnerTrustPinsV1 {
        schema: "hepta.learning.cell-split.owner-trust-pins.v1",
        plan_digest: &trust.plan_digest,
        owner_ids: &plan.owner_ids,
        verifying_keys: std::array::from_fn(|index| trust.owner_keys[index].to_bytes()),
    })?)
}

fn receipt_digest(
    receipt: &CellSplitExecutionReceiptV1,
) -> Result<String, CellSplitExecutionErrorV1> {
    let mut unsealed = receipt.clone();
    unsealed.receipt_digest.clear();
    Ok(sha256(&canonical_json(&unsealed)?))
}

/// Verify the four original signatures and exact predecessor chain without
/// trusting the coordinator's transcript digest alone.
///
/// This is deliberately an OFFLINE proof of byte/identity consistency, not a
/// live readback, host attestation, NDU selection, or production authorization.
/// The caller must supply keys pinned independently of this transcript and
/// obtain fresh current-owner observations before using these records as
/// deployment evidence.
pub fn verify_cell_split_execution_transcript_signatures_v1(
    transcript: &CellSplitExecutionTranscriptV1,
    trust: &CellSplitOwnerTrustV1,
) -> Result<(), CellSplitExecutionErrorV1> {
    transcript.plan.validate()?;
    let plan_digest = transcript.plan.digest()?;
    if trust.plan_digest != plan_digest || transcript.receipts.len() != STEP_COUNT {
        return Err(CellSplitExecutionErrorV1::Invalid(
            "transcript plan, trust, or step count mismatch",
        ));
    }
    let mut predecessor = plan_digest.clone();
    for (index, receipt) in transcript.receipts.iter().enumerate() {
        let step = CellSplitExecutionStepV1::at(index)
            .ok_or(CellSplitExecutionErrorV1::Invalid("transcript step index"))?;
        let intent = make_intent(&transcript.plan, &plan_digest, step, &predecessor);
        validate_receipt(&intent, receipt)?;
        trust.verify(&intent, receipt)?;
        predecessor = receipt.receipt_digest.clone();
    }
    let mut payload = b"hepta.learning.cell-split.verified-transcript.v1\0".to_vec();
    payload.extend_from_slice(&canonical_json(&transcript.plan)?);
    payload.extend_from_slice(&canonical_json(&transcript.receipts)?);
    if transcript.transcript_digest != sha256(&payload) {
        return Err(CellSplitExecutionErrorV1::Invalid(
            "transcript digest mismatch",
        ));
    }
    Ok(())
}

/// Validate one signed CNS predecessor receipt against the frozen CellSplit
/// plan and its independently pinned CNS effect-owner key. This checks the
/// outer coordinator receipt; the original CNS runtime receipt and current
/// serving route must additionally be verified by the live CNS/Supervisor
/// owner before a successor effect is authorized.
pub fn verify_cell_split_cns_step_receipt_v1(
    plan: &CellSplitExecutionPlanV1,
    receipt: &CellSplitExecutionReceiptV1,
    pinned_cns_key: &VerifyingKey,
) -> Result<(), CellSplitExecutionErrorV1> {
    let plan_digest = plan.digest()?;
    let predecessor = &receipt.intent.previous_receipt_digest;
    if !valid_digest(predecessor) || pinned_cns_key.is_weak() {
        return Err(CellSplitExecutionErrorV1::Invalid(
            "untrusted CNS predecessor receipt",
        ));
    }
    let expected = make_intent(
        plan,
        &plan_digest,
        CellSplitExecutionStepV1::CnsRouteCutover,
        predecessor,
    );
    validate_receipt(&expected, receipt)?;
    let signature = Signature::from_slice(&receipt.owner_signature_bytes)
        .map_err(|_| CellSplitExecutionErrorV1::Invalid("invalid CNS owner signature"))?;
    pinned_cns_key
        .verify_strict(
            &cell_split_execution_signing_payload_v1(receipt)?,
            &signature,
        )
        .map_err(|_| CellSplitExecutionErrorV1::Invalid("untrusted CNS owner signature"))
}

/// The digest used for the durable coordinator chain commits the signed outer
/// receipt, not the original CNS runtime's independently signed inner bytes.
pub fn cell_split_execution_receipt_digest_v1(
    receipt: &CellSplitExecutionReceiptV1,
) -> Result<String, CellSplitExecutionErrorV1> {
    receipt_digest(receipt)
}

/// The deployment's *real* CAS, child migration, CNS and Supervisor owners.
/// execute must use intent.idempotency_key as its durable effect key. reconcile
/// must read back an already committed result, not re-execute an uncertain
/// effect. verify_committed must authenticate and revalidate owner state.
/// Source-only mocks must never be wired to production activation.
pub trait CellSplitExecutionPortV1 {
    type Error: std::fmt::Display;

    /// Side-effect-free, nonce-bound negative observation of the original
    /// owner. This must reject a committed effect for the exact intent; it
    /// never dispatches, reserves, consumes Final-use or reconciles anything.
    /// Both execution preparation and verified incomplete-status inspection
    /// require this check. There is no default allow-all implementation.
    fn preflight_uncommitted(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<(), Self::Error>;

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
    read_only: bool,
    previous_receipt_digest: String,
    frozen_plan_instance: fs::Metadata,
    frozen_pins_instance: fs::Metadata,
    frame_instances: Vec<(Option<fs::Metadata>, Option<fs::Metadata>)>,
    _lock: SidecarLock,
}

impl<P: CellSplitExecutionPortV1> CellSplitExecutionOwnerV1<P> {
    pub fn open(
        root: &Path,
        plan: CellSplitExecutionPlanV1,
        trust: CellSplitOwnerTrustV1,
        port: P,
    ) -> Result<Self, CellSplitExecutionErrorV1> {
        Self::open_inner(root, plan, trust, port, false)
    }

    /// Read-only re-open for transcript inspection. Never creates a lock or
    /// frozen plan as a side effect of a query against an empty split root.
    pub fn open_existing(
        root: &Path,
        plan: CellSplitExecutionPlanV1,
        trust: CellSplitOwnerTrustV1,
        port: P,
    ) -> Result<Self, CellSplitExecutionErrorV1> {
        Self::open_inner(root, plan, trust, port, true)
    }

    fn open_inner(
        root: &Path,
        plan: CellSplitExecutionPlanV1,
        trust: CellSplitOwnerTrustV1,
        mut port: P,
        existing_only: bool,
    ) -> Result<Self, CellSplitExecutionErrorV1> {
        plan.validate()?;
        let root = secure_root(root, "cell split owner root")?;
        verify_split_frame_namespace(&root)?;
        // The shared sidecar lock is created before the frozen plan on first
        // initialization. If both immutable owner frames later vanish, the
        // surviving lock is a local continuity marker: do not silently
        // initialize a different split from newly supplied plan/key bytes.
        // An external witness is still required against full root rollback.
        let sidecar_lock_path = root.join(crate::durable::SIDECAR_LOCK_FILE);
        let previously_opened = match fs::symlink_metadata(&sidecar_lock_path) {
            Ok(_) => true,
            Err(error) if error.kind() == ErrorKind::NotFound => false,
            Err(error) => return Err(error.into()),
        };
        // An existing frozen plan or effect ledger must retain its original
        // writer-lock inode. Recreating a missing lock would allow a second
        // process to acquire a different inode while the old writer still
        // holds its original OS lock. Fail before creating any replacement.
        if !previously_opened
            && (read_frame(&root.join("cell-split-frozen-plan.json"))?.is_some()
                || read_frame(&root.join("cell-split-owner-trust-pins.json"))?.is_some()
                || has_successor_frame(&root, 0)?)
        {
            return Err(CellSplitExecutionErrorV1::Invalid(
                "initialized split owner lost original writer lock",
            ));
        }
        let lock = if existing_only {
            lock_existing_sidecar(&root)?
        } else {
            lock_sidecar(&root)?
        };
        lock.verify_current(&root)?;
        let plan_digest = plan.digest()?;
        if trust.plan_digest != plan_digest {
            return Err(CellSplitExecutionErrorV1::Invalid("trusted plan mismatch"));
        }
        let path = root.join("cell-split-frozen-plan.json");
        let pins_path = root.join("cell-split-owner-trust-pins.json");
        // Observe the entire frozen namespace before writing any new file.
        // Restoring a deleted plan after preparation, even from matching
        // caller-supplied bytes, would hide lost or tampered durable evidence.
        let has_effect_history = has_successor_frame(&root, 0)?;
        let persisted_pins = read_frame(&pins_path)?;
        let persisted_plan = read_frame(&path)?;
        if previously_opened
            && persisted_plan.is_none()
            && persisted_pins.is_none()
            && !has_effect_history
        {
            return Err(CellSplitExecutionErrorV1::Invalid(
                "initialized split owner lost frozen identity",
            ));
        }
        let bytes = canonical_json(&plan)?;
        // Once the plan exists, its independently pinned owner keys may not
        // be regenerated, even if no external effect has started. Otherwise
        // a deleted pins frame could silently rebind a frozen split to
        // caller-supplied signer keys before the first prepared intent.
        let plan_was_frozen = persisted_plan.is_some();
        match persisted_plan {
            Some(persisted) if persisted != bytes => {
                return Err(CellSplitExecutionErrorV1::Invalid("frozen plan changed"));
            }
            Some(_) => {}
            None if existing_only => {
                return Err(CellSplitExecutionErrorV1::Invalid(
                    "read-only transcript requires an existing frozen plan",
                ));
            }
            None if has_effect_history || persisted_pins.is_some() => {
                return Err(CellSplitExecutionErrorV1::Invalid(
                    "frozen plan lost after initialization",
                ));
            }
            None => write_private_new(&path, &bytes)?,
        }

        // Keep all four trusted signer keys frozen across restarts.
        // The symlink-aware frame scan must not treat a broken link as absence.
        let frozen_pins = frozen_owner_trust_pins(&plan, &trust)?;
        match persisted_pins {
            Some(stored) if stored != frozen_pins => {
                return Err(CellSplitExecutionErrorV1::Invalid(
                    "persisted effect owner keys changed",
                ));
            }
            Some(_) => {}
            None if has_effect_history => {
                return Err(CellSplitExecutionErrorV1::Invalid(
                    "effect history lost trust pins",
                ));
            }
            None if plan_was_frozen => {
                return Err(CellSplitExecutionErrorV1::Invalid(
                    "frozen plan lost owner trust pins",
                ));
            }
            None if existing_only => {
                return Err(CellSplitExecutionErrorV1::Invalid(
                    "read-only transcript requires existing owner trust pins",
                ));
            }
            None => write_private_new(&pins_path, &frozen_pins)?,
        }

        // Snapshot the complete bounded local namespace before querying
        // any original owner. A remote readback may race with local corruption
        // or replacement; neither a reconstructed cursor nor a fresh open
        // may accept the resulting mixed local history.
        let (plan_bytes, frozen_plan_instance) = read_frame_with_snapshot(&path)?.ok_or(
            CellSplitExecutionErrorV1::Invalid("frozen plan disappeared"),
        )?;
        let (pins_bytes, frozen_pins_instance) = read_frame_with_snapshot(&pins_path)?.ok_or(
            CellSplitExecutionErrorV1::Invalid("owner trust pins disappeared"),
        )?;
        if plan_bytes != bytes || pins_bytes != frozen_pins {
            return Err(CellSplitExecutionErrorV1::Invalid(
                "frozen identity changed before owner recovery",
            ));
        }
        let mut frame_snapshots = Vec::with_capacity(STEP_COUNT);
        let mut frame_instances = Vec::with_capacity(STEP_COUNT);
        for index in 0..STEP_COUNT {
            let prepared_path = frame_path(&root, index, "prepared");
            let committed_path = frame_path(&root, index, "committed");
            let (prepared, prepared_instance) = match read_frame_with_snapshot(&prepared_path)? {
                Some((bytes, metadata)) => (Some(bytes), Some(metadata)),
                None => (None, None),
            };
            let (committed, committed_instance) = match read_frame_with_snapshot(&committed_path)? {
                Some((bytes, metadata)) => (Some(bytes), Some(metadata)),
                None => (None, None),
            };
            frame_instances.push((prepared_instance, committed_instance));
            frame_snapshots.push((prepared, committed));
        }
        let mut cursor = 0;
        let mut pending = false;
        let mut previous_receipt_digest = plan_digest.clone();
        for index in 0..STEP_COUNT {
            let step = CellSplitExecutionStepV1::at(index)
                .ok_or(CellSplitExecutionErrorV1::Invalid("step index"))?;
            let intent = make_intent(&plan, &plan_digest, step, &previous_receipt_digest);
            let expected = canonical_json(&intent)?;
            let (prepared, committed) = frame_snapshots[index].clone();
            match (prepared, committed) {
                (None, None) => {
                    if has_successor_frame(&root, index + 1)? {
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
                        let receipt = decode_committed_receipt(&bytes)?;
                        validate_receipt(&intent, &receipt)?;
                        trust.verify(&intent, &receipt)?;
                        port.verify_committed(&intent, &receipt).map_err(|error| {
                            CellSplitExecutionErrorV1::External(error.to_string())
                        })?;
                        previous_receipt_digest = receipt.receipt_digest;
                        cursor += 1;
                    } else {
                        pending = true;
                        if has_successor_frame(&root, index + 1)? {
                            return Err(CellSplitExecutionErrorV1::Invalid(
                                "pending step has successors",
                            ));
                        }
                        break;
                    }
                }
            }
        }
        // Original-owner RPCs can be slow. Reconfirm both the immutable
        // execution identity and *every* originally observed frame after the
        // last remote callback, before declaring a successful recovery.
        verify_split_frame_namespace(&root)?;
        if read_frame(&path)? != Some(bytes) || read_frame(&pins_path)? != Some(frozen_pins) {
            return Err(CellSplitExecutionErrorV1::Invalid(
                "frozen identity changed during owner recovery",
            ));
        }
        for (index, (prepared, committed)) in frame_snapshots.into_iter().enumerate() {
            if read_frame(&frame_path(&root, index, "prepared"))? != prepared
                || read_frame(&frame_path(&root, index, "committed"))? != committed
            {
                return Err(CellSplitExecutionErrorV1::Invalid(
                    "local history changed during owner recovery",
                ));
            }
        }
        // A byte-identical rename over any original frame during signed owner
        // RPC is not evidence continuity. Pin the original file instances too.
        verify_frame_instance(&path, &frozen_plan_instance)?;
        verify_frame_instance(&pins_path, &frozen_pins_instance)?;
        for (index, (prepared, committed)) in frame_instances.iter().enumerate() {
            if let Some(original) = prepared {
                verify_frame_instance(&frame_path(&root, index, "prepared"), original)?;
            }
            if let Some(original) = committed {
                verify_frame_instance(&frame_path(&root, index, "committed"), original)?;
            }
        }
        lock.verify_current(&root)?;
        Ok(Self {
            root,
            plan,
            plan_digest,
            port,
            trust,
            cursor,
            pending,
            read_only: existing_only,
            previous_receipt_digest,
            frozen_plan_instance,
            frozen_pins_instance,
            frame_instances,
            _lock: lock,
        })
    }

    #[must_use]
    pub fn completed_steps(&self) -> usize {
        self.cursor
    }

    /// Historical four-step cursor only. Never treat this as a live production
    /// readiness check; an independently signed owner effect can be revoked.
    #[must_use]
    pub fn is_complete(&self) -> bool {
        self.cursor == STEP_COUNT
    }

    /// Demand a fresh readback of all four original durable owners before
    /// reporting a complete current lifecycle. No activation authority.
    ///
    /// Even a negative answer must reauthenticate the frozen ledger and each
    /// committed original-owner effect. Otherwise an externally revoked
    /// predecessor or a corrupted pending frame could be reported as harmless
    /// incompleteness without any live owner readback. A still-prepared intent
    /// is ambiguous until the original owner is reconciled: it is never a
    /// safe, verified false result.
    pub fn verified_complete(&mut self) -> Result<bool, CellSplitExecutionErrorV1> {
        // Locally absent next-step frames cannot prove original-owner absence.
        self.probe_next_unprepared_original()?;
        self.verify_committed_prefix()?;
        if self.pending {
            return Err(CellSplitExecutionErrorV1::Ambiguous);
        }
        // A signed negative readback taken before slow predecessor RPCs can
        // become stale. Recheck original next-owner absence before reporting
        // a harmless incomplete state. This is diagnostic only, not an
        // atomic multi-owner snapshot or a Final-use grant.
        if !self.is_complete() {
            self.probe_next_unprepared_original()?;
            // The final negative RPC is not a reservation and may be slow.
            // Reject any local ledger/pin mutation caused by that callback
            // without repeating all live predecessor-owner RPCs.
            self.verify_local_prefix_after_callback()?;
        }
        Ok(self.is_complete())
    }

    /// Export a four-effect proof only while every original commit is still
    /// live, independently signed and bound to the same frozen plan. A local
    /// digest chain alone never substitutes for fresh owner readback.
    pub fn verified_transcript(
        &mut self,
    ) -> Result<Option<CellSplitExecutionTranscriptV1>, CellSplitExecutionErrorV1> {
        // Refuse an unledgered original next-step effect in read-only exports.
        self.probe_next_unprepared_original()?;
        // This same readback validates the frozen plan, complete receipt chain,
        // pinned signatures and the current real owner state. Do not repeat
        // the four potentially remote owner reads just to export the bytes.
        let receipts = self.read_verified_prefix(true, true)?;
        // A prepared step may already have changed the original external
        // owner even when its local Commit frame is absent. The Operator's
        // read-only transcript action must never collapse that unknown effect
        // into benign incompleteness; only the execution owner may reconcile.
        if self.pending {
            return Err(CellSplitExecutionErrorV1::Ambiguous);
        }
        if !self.is_complete() {
            // Re-probe the exact original next owner after current signed
            // predecessor verification. Never report an empty transcript
            // if a next effect appeared during the preceding readbacks.
            self.probe_next_unprepared_original()?;
            self.verify_local_prefix_after_callback()?;
            return Ok(None);
        }
        let mut payload = b"hepta.learning.cell-split.verified-transcript.v1\0".to_vec();
        payload.extend_from_slice(&canonical_json(&self.plan)?);
        payload.extend_from_slice(&canonical_json(&receipts)?);
        Ok(Some(CellSplitExecutionTranscriptV1 {
            plan: self.plan.clone(),
            receipts,
            transcript_digest: sha256(&payload),
        }))
    }

    /// An independently signed negative readback of the next unprepared
    /// original effect. A missing endpoint must fail closed, not be reported
    /// as a verified incomplete split. Do not probe a pending prepared intent:
    /// its unknown outcome is reconciliation-only, regardless of readback.
    /// This observation is non-authorizing and not an atomic multi-owner view.
    fn probe_next_unprepared_original(&mut self) -> Result<(), CellSplitExecutionErrorV1> {
        if self.pending {
            return Ok(());
        }
        let Some(step) = CellSplitExecutionStepV1::at(self.cursor) else {
            return Ok(());
        };
        let intent = make_intent(
            &self.plan,
            &self.plan_digest,
            step,
            &self.previous_receipt_digest,
        );
        self.port
            .preflight_uncommitted(&intent)
            .map_err(|error| CellSplitExecutionErrorV1::External(error.to_string()))
    }

    fn verify_original_frame_instances(&self) -> Result<(), CellSplitExecutionErrorV1> {
        verify_frame_instance(
            &self.root.join("cell-split-frozen-plan.json"),
            &self.frozen_plan_instance,
        )?;
        verify_frame_instance(
            &self.root.join("cell-split-owner-trust-pins.json"),
            &self.frozen_pins_instance,
        )?;
        for (index, (prepared, committed)) in self.frame_instances.iter().enumerate() {
            if let Some(original) = prepared {
                verify_frame_instance(&frame_path(&self.root, index, "prepared"), original)?;
            }
            if let Some(original) = committed {
                verify_frame_instance(&frame_path(&self.root, index, "committed"), original)?;
            }
        }
        Ok(())
    }

    /// Read each committed predecessor back from the durable ledger and from
    /// its real owner immediately before a successor is dispatched. An external
    /// rollback, stale route or post-open sidecar tamper must fence execution,
    /// even when the coordinator previously opened successfully.
    pub fn verify_committed_prefix(&mut self) -> Result<(), CellSplitExecutionErrorV1> {
        self.read_verified_prefix(false, true).map(|_| ())
    }

    /// Locally revalidate the *same* original ledger, frozen plan and signer
    /// pins after a potentially slow negative-readback or Selector/NDU
    /// callback. The preceding full verification already consulted each
    /// original owner; do not repeat remote RPCs on this final local fence.
    /// This check is not an atomic multi-owner snapshot or Final-use grant.
    fn verify_local_prefix_after_callback(&mut self) -> Result<(), CellSplitExecutionErrorV1> {
        self.read_verified_prefix(false, false).map(|_| ())
    }

    /// Canonical bounded local history pass. When verify_original_owner is
    /// true, each committed predecessor must ALSO be freshly read from its
    /// real effect owner. False is permitted only as a final post-callback
    /// local continuity fence after the full signed live pass has succeeded.
    fn read_verified_prefix(
        &mut self,
        collect_receipts: bool,
        verify_original_owner: bool,
    ) -> Result<Vec<CellSplitExecutionReceiptV1>, CellSplitExecutionErrorV1> {
        self._lock.verify_current(&self.root)?;
        verify_split_frame_namespace(&self.root)?;
        let frozen = read_frame(&self.root.join("cell-split-frozen-plan.json"))?.ok_or(
            CellSplitExecutionErrorV1::Invalid("frozen plan disappeared"),
        )?;
        if frozen != canonical_json(&self.plan)? {
            return Err(CellSplitExecutionErrorV1::Invalid("frozen plan drift"));
        }
        let pinned = read_frame(&self.root.join("cell-split-owner-trust-pins.json"))?.ok_or(
            CellSplitExecutionErrorV1::Invalid("owner trust pins disappeared"),
        )?;
        if pinned != frozen_owner_trust_pins(&self.plan, &self.trust)? {
            return Err(CellSplitExecutionErrorV1::Invalid("owner trust pins drift"));
        }
        let mut predecessor = self.plan_digest.clone();
        // Capture the unresolved intent BEFORE potentially slow remote owner
        // verification. A later valid-looking pending frame cannot silently
        // replace the one this invocation originally observed.
        let pending_frame = if self.pending {
            Some(
                read_frame(&frame_path(&self.root, self.cursor, "prepared"))?.ok_or(
                    CellSplitExecutionErrorV1::Invalid("pending intent disappeared"),
                )?,
            )
        } else {
            None
        };
        // Retain the original bounded on-disk frames during the live owner
        // readbacks. A callback may take time; rechecking only the remote
        // effects would permit local journal or trust-frame replacement
        // between the first read and a reported verified transcript.
        let mut local_frames = Vec::with_capacity(self.cursor);
        let mut receipts = if collect_receipts {
            Vec::with_capacity(self.cursor)
        } else {
            Vec::new()
        };
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
            let receipt = decode_committed_receipt(&bytes)?;
            validate_receipt(&intent, &receipt)?;
            self.trust.verify(&intent, &receipt)?;
            if verify_original_owner {
                self.port
                    .verify_committed(&intent, &receipt)
                    .map_err(|error| CellSplitExecutionErrorV1::External(error.to_string()))?;
            }
            local_frames.push((prepared, bytes));
            if collect_receipts {
                predecessor = receipt.receipt_digest.clone();
                receipts.push(receipt);
            } else {
                predecessor = receipt.receipt_digest;
            }
        }
        if predecessor != self.previous_receipt_digest {
            return Err(CellSplitExecutionErrorV1::Invalid("committed prefix drift"));
        }
        // The pending intent is part of the durable replay boundary too.
        // Read-only transcript export must not silently accept post-open
        // mutation or an unacknowledged commit at the pending cursor.
        if !self.pending && has_successor_frame(&self.root, self.cursor)? {
            // Revalidate the *unexecuted* suffix too. A forged later intent
            // injected after open must not let a current owner dispatch an
            // earlier effect under a non-prefix durable history.
            return Err(CellSplitExecutionErrorV1::Invalid(
                "unexpected successor frame; reopen required",
            ));
        }
        if let Some(prepared) = &pending_frame {
            let step = CellSplitExecutionStepV1::at(self.cursor)
                .ok_or(CellSplitExecutionErrorV1::Invalid("pending step index"))?;
            let intent = make_intent(&self.plan, &self.plan_digest, step, &predecessor);
            if read_frame(&frame_path(&self.root, self.cursor, "prepared"))?.as_ref()
                != Some(prepared)
            {
                return Err(CellSplitExecutionErrorV1::Invalid(
                    "pending intent changed during live owner readback",
                ));
            }
            if *prepared != canonical_json(&intent)? {
                return Err(CellSplitExecutionErrorV1::Invalid("pending intent drift"));
            }
            if read_frame(&frame_path(&self.root, self.cursor, "committed"))?.is_some()
                || has_successor_frame(&self.root, self.cursor + 1)?
            {
                return Err(CellSplitExecutionErrorV1::Invalid(
                    "pending cursor changed; reopen required",
                ));
            }
        }
        // An original owner might have been slow or adversarial while it
        // returned a signed live receipt. Do not publish a verified view from
        // locally replaced plan, signer pins or previously checked prefix.
        // These are at most four frames and are only reread on a cold
        // execution/qualification boundary, never per neuron inference tick.
        if read_frame(&self.root.join("cell-split-frozen-plan.json"))? != Some(frozen)
            || read_frame(&self.root.join("cell-split-owner-trust-pins.json"))? != Some(pinned)
        {
            return Err(CellSplitExecutionErrorV1::Invalid(
                "frozen identity changed during live owner readback",
            ));
        }
        for (index, (prepared, committed)) in local_frames.into_iter().enumerate() {
            if read_frame(&frame_path(&self.root, index, "prepared"))? != Some(prepared)
                || read_frame(&frame_path(&self.root, index, "committed"))? != Some(committed)
            {
                return Err(CellSplitExecutionErrorV1::Invalid(
                    "committed frame changed during live owner readback",
                ));
            }
        }
        // The pending intent is not in local_frames because it has no
        // committed receipt. An original-owner callback can nevertheless
        // replace it after the first validation. Re-read its exact bytes and
        // reject a new commit/successor before reporting a verified prefix.
        if let Some(prepared) = pending_frame {
            if read_frame(&frame_path(&self.root, self.cursor, "prepared"))? != Some(prepared)
                || read_frame(&frame_path(&self.root, self.cursor, "committed"))?.is_some()
                || has_successor_frame(&self.root, self.cursor + 1)?
            {
                return Err(CellSplitExecutionErrorV1::Invalid(
                    "pending intent changed during live owner readback",
                ));
            }
        }
        // An original owner may take arbitrarily long to answer. In addition
        // to rechecking existing bytes, reject any newly injected frame or
        // unknown successor that appeared while its live RPC was in flight.
        // Only the single split owner may extend this write-once namespace.
        verify_split_frame_namespace(&self.root)?;
        self.verify_original_frame_instances()?;
        self._lock.verify_current(&self.root)?;
        Ok(receipts)
    }

    /// Source-only fixture convenience. An unauthenticated callback must
    /// never be a public production entry for CAS/migration/CNS/Supervisor
    /// execution. Production callers enter through the Agentd selected-split
    /// admission path, and every original effect owner enforces final-use.
    #[cfg(test)]
    pub(crate) fn advance(
        &mut self,
    ) -> Result<Option<CellSplitExecutionReceiptV1>, CellSplitExecutionErrorV1> {
        self.advance_with_admission(|| Ok(()))
    }

    /// Product admission seam: independently reread current NDU/Selector state
    /// after the original owner's potentially slow preflight, before writing
    /// the first prepared intent. This callback is advisory, not final-use;
    /// the independent effect backend must reauthorize at its commit boundary.
    pub(crate) fn advance_with_admission(
        &mut self,
        mut revalidate: impl FnMut() -> Result<(), String>,
    ) -> Result<Option<CellSplitExecutionReceiptV1>, CellSplitExecutionErrorV1> {
        // Inspection handles may authenticate existing evidence but must never
        // prepare an intent or invoke an external CAS/CNS/Supervisor effect.
        if self.read_only {
            return Err(CellSplitExecutionErrorV1::Invalid(
                "read-only CellSplit owner cannot advance",
            ));
        }
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
            // A missing/retired original effect owner must not strand a newly
            // selected split in permanent reconcile-only state before the
            // first mutation request has even been sent.
            self.port
                .preflight_uncommitted(&intent)
                .map_err(|error| CellSplitExecutionErrorV1::External(error.to_string()))?;
            // External preflight is not a durable reservation. It can observe
            // a valid predecessor and then return after the independent
            // Selector/NDU has withdrawn admission. Refuse to create even a
            // prepared intent when the current selection has been revoked.
            revalidate().map_err(CellSplitExecutionErrorV1::External)?;
            // Also recheck external predecessor effects and frozen local pins
            // after the preflight/admission callbacks, never trust old reads.
            self.verify_committed_prefix()?;
            // The first negative owner readback is NOT a reservation: the
            // original effect may appear while Selector/NDU admission and
            // predecessor RPCs are in flight. Recheck the exact next original
            // owner before writing the irreversible prepared intent. Never
            // adopt an external effect absent from this local ledger.
            self.port
                .preflight_uncommitted(&intent)
                .map_err(|error| CellSplitExecutionErrorV1::External(error.to_string()))?;
            // The second signed negative RPC may itself be slow or adversarial.
            // Reverify frozen local frames and each committed original owner
            // before writing. This is bounded lifecycle work, not a neuron tick.
            self.verify_committed_prefix()?;
            // Revalidate Selector/NDU after both potentially slow original
            // checks. Final-use remains an independent physical-owner gate;
            // these negative observations do NOT create an atomic commit.
            revalidate().map_err(CellSplitExecutionErrorV1::External)?;
            // The final independent Selector/NDU callback can race with
            // durable ledger or trust-pin mutations. Do not prepare after it.
            self.verify_local_prefix_after_callback()?;
            let prepared_path = frame_path(&self.root, self.cursor, "prepared");
            let prepared_instance =
                write_private_new_with_snapshot(&prepared_path, &canonical_json(&intent)?)?;
            // The write helper returns the fsynced original descriptor's
            // metadata rather than trusting a second path lookup.
            self.pending = true;
            self.frame_instances[self.cursor].0 = Some(prepared_instance);
        }
        // The prepared intent is already fsynced. From this point onward,
        // any RPC/transport failure may hide a committed original effect.
        // Recovery must preserve the same intent and use read-only readback.
        let receipt = if pending {
            self.port
                .reconcile(&intent)
                .map_err(|_| CellSplitExecutionErrorV1::Ambiguous)?
                .ok_or(CellSplitExecutionErrorV1::Ambiguous)?
        } else {
            self.port
                .execute(&intent)
                .map_err(|_| CellSplitExecutionErrorV1::Ambiguous)?
        };
        // The prepared intent is durable and the original owner may already
        // have committed. A malformed/forged ACK cannot prove non-execution:
        // retain this key for read-only original-owner reconciliation.
        validate_receipt(&intent, &receipt).map_err(|_| CellSplitExecutionErrorV1::Ambiguous)?;
        self.trust
            .verify(&intent, &receipt)
            .map_err(|_| CellSplitExecutionErrorV1::Ambiguous)?;
        // This is AFTER a durable prepared intent and an original effect
        // response. A live confirmation RPC failure (including a bad/absent
        // owner readback) cannot establish that the effect did not commit.
        // Preserve the fixed intent and reconcile it; never issue Execute
        // again just because current-state verification was unavailable.
        self.port
            .verify_committed(&intent, &receipt)
            .map_err(|_| CellSplitExecutionErrorV1::Ambiguous)?;
        // An effect may finish after another owner revoked a predecessor or
        // replaced a frozen local frame. Before acknowledging the new step,
        // revalidate the original signed owner prefix and still-pending intent.
        // If this fails, leave the durable intent pending for reconciliation:
        // the external operation may already have committed and MUST NOT be
        // dispatched a second time.
        // A completed original effect must not be dispatched again if the
        // local final readback, receipt serialization or fsynced Commit fails.
        self.verify_committed_prefix()
            .map_err(|_| CellSplitExecutionErrorV1::Ambiguous)?;

        // An independently selected split can be withdrawn while the real
        // CAS/migration/CNS/Supervisor owner performs its physical effect and
        // signed readback. Recheck CURRENT Selector/NDU admission *after* the
        // original effect, before sealing a local success. Do not translate a
        // post-effect denial into an ordinary preflight failure: execution may
        // already be durable. The fsynced prepared intent must remain the sole
        // idempotency key and recovery must reconcile, never execute again.
        revalidate().map_err(|_| CellSplitExecutionErrorV1::Ambiguous)?;

        // A slow or compromised admission callback could also replace the
        // original frozen plan, trust pins, pending intent or predecessor
        // frames. Check the write-once local history after that callback.
        // This cannot make Final-use atomic with an external effect; the
        // native owner must still fence its own commit and generation.
        self.verify_local_prefix_after_callback()
            .map_err(|_| CellSplitExecutionErrorV1::Ambiguous)?;

        // The native effect's first authenticated readback preceded a
        // potentially slow NDU/Selector callback. While that callback ran,
        // the original effect owner might have withdrawn the commit. Re-query
        // the SAME original native owner by the SAME intent key, never Execute.
        // Its absence, timeout or changed receipt leaves Prepared ambiguous.
        self.port
            .verify_committed(&intent, &receipt)
            .map_err(|_| CellSplitExecutionErrorV1::Ambiguous)?;
        self.verify_local_prefix_after_callback()
            .map_err(|_| CellSplitExecutionErrorV1::Ambiguous)?;

        // The last native readback may itself race with Selector withdrawal.
        // Revalidate current selection again before local acknowledgment.
        // These alternating owner checks narrow but cannot eliminate a
        // cross-service race: only the original native Final-use/CAS fence
        // can enforce atomic mutation authorization.
        revalidate().map_err(|_| CellSplitExecutionErrorV1::Ambiguous)?;
        self.verify_local_prefix_after_callback()
            .map_err(|_| CellSplitExecutionErrorV1::Ambiguous)?;

        let committed_bytes =
            canonical_json(&receipt).map_err(|_| CellSplitExecutionErrorV1::Ambiguous)?;
        let committed_path = frame_path(&self.root, self.cursor, "committed");
        let committed_instance = write_private_new_with_snapshot(&committed_path, &committed_bytes)
            .map_err(|_| CellSplitExecutionErrorV1::Ambiguous)?;
        self.frame_instances[self.cursor].1 = Some(committed_instance);
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

pub(crate) fn validate_receipt(
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

fn decode_committed_receipt(
    bytes: &[u8],
) -> Result<CellSplitExecutionReceiptV1, CellSplitExecutionErrorV1> {
    let receipt: CellSplitExecutionReceiptV1 = serde_json::from_slice(bytes)?;
    if canonical_json(&receipt)? != bytes {
        return Err(CellSplitExecutionErrorV1::Invalid(
            "noncanonical committed receipt bytes",
        ));
    }
    Ok(receipt)
}

/// Original local instances are write-once. Equal JSON bytes on a newly
/// substituted inode are not proof of uninterrupted durable owner custody.
/// This is a live-session fence, not a cross-reboot anti-rollback witness.
fn verify_frame_instance(
    path: &Path,
    original: &fs::Metadata,
) -> Result<(), CellSplitExecutionErrorV1> {
    let current = fs::symlink_metadata(path)?;
    if current.file_type().is_symlink()
        || !current.is_file()
        || !same_file_snapshot(original, &current)
    {
        return Err(CellSplitExecutionErrorV1::Invalid(
            "original local split frame identity changed",
        ));
    }
    Ok(())
}

fn frame_path(root: &Path, index: usize, phase: &str) -> PathBuf {
    root.join(format!("cell-split-{index:02}-{phase}.json"))
}

/// A broken symlink is still a persisted path, never evidence of absence.
/// Do not use Path::exists here: it follows symlinks and can return false for
/// malicious/dangling successors, allowing a non-prefix history to advance.
/// Every split owns a deliberately small, write-once namespace. Unknown
/// cell-split frames (including a fifth step, alternative receipt suffix or
/// replay marker) are evidence of a corrupted ledger, never ignorable files.
/// Bound the scan itself so a hostile directory cannot make a global owner
/// lock perform unbounded work.
fn verify_split_frame_namespace(root: &Path) -> Result<(), CellSplitExecutionErrorV1> {
    const MAX_ENTRIES: usize = 32;
    let mut count = 0_usize;
    for entry in fs::read_dir(root)? {
        let entry = entry?;
        count += 1;
        if count > MAX_ENTRIES {
            return Err(CellSplitExecutionErrorV1::Invalid(
                "split ledger namespace exceeds bounded entry limit",
            ));
        }
        let filename = entry.file_name();
        let Some(name) = filename.to_str() else {
            return Err(CellSplitExecutionErrorV1::Invalid(
                "split ledger contains an invalid filename",
            ));
        };
        if !name.starts_with("cell-split-") {
            continue;
        }
        if name == "cell-split-frozen-plan.json" || name == "cell-split-owner-trust-pins.json" {
            continue;
        }
        let known = (0..STEP_COUNT).any(|index| {
            name == format!("cell-split-{index:02}-prepared.json")
                || name == format!("cell-split-{index:02}-committed.json")
        });
        if !known {
            return Err(CellSplitExecutionErrorV1::Invalid(
                "unknown cell split durable frame",
            ));
        }
    }
    Ok(())
}

fn has_successor_frame(root: &Path, from_index: usize) -> Result<bool, CellSplitExecutionErrorV1> {
    for index in from_index..STEP_COUNT {
        if read_frame(&frame_path(root, index, "prepared"))?.is_some()
            || read_frame(&frame_path(root, index, "committed"))?.is_some()
        {
            return Ok(true);
        }
    }
    Ok(false)
}

fn read_frame(path: &Path) -> Result<Option<Vec<u8>>, CellSplitExecutionErrorV1> {
    Ok(read_frame_with_snapshot(path)?.map(|(bytes, _)| bytes))
}

fn read_frame_with_snapshot(
    path: &Path,
) -> Result<Option<(Vec<u8>, fs::Metadata)>, CellSplitExecutionErrorV1> {
    match fs::symlink_metadata(path) {
        Ok(_) => Ok(Some(secure_read_with_snapshot(path, MAX_RECORD_BYTES)?)),
        Err(error) if error.kind() == ErrorKind::NotFound => Ok(None),
        Err(error) => Err(error.into()),
    }
}

#[cfg(test)]
#[path = "cell_split_execution_owner_tests.rs"]
mod tests;
