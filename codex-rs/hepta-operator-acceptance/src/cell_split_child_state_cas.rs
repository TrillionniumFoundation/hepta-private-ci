//! Durable, all-children-or-none publication of validated Neuron state migration.
//!
//! Canonical Q24 bytes come from CellStateMigrationV1, created from an
//! acknowledged parent checkpoint and the validated CellSplit contract.
//! Immutable child files are synced and re-read before a single create-only
//! batch commit marker becomes the sole route-visible authority.
//! Independent final-use, live parent journal and original CAS confirmation
//! are mandatory; their real owners are injected, never fabricated here.
//! Interrupted staging has no positive readback and cannot silently resume.

use std::fs;
use std::io::ErrorKind;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_neuron::CellStateBatchReceiptV1;
use codex_hepta_neuron::CellStateCasReceiptV1;
use codex_hepta_neuron::CellStateMigrationPhaseV1;
use codex_hepta_neuron::CellStateMigrationV1;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::encode_cell_state_v1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use thiserror::Error;

use crate::CellSplitDurableEffectBackendV1;
use crate::CellSplitExecutionIntentV1;
use crate::CellSplitExecutionPlanV1;
use crate::CellSplitExecutionStepV1;
use crate::CellSplitOwnedEffectV1;
use crate::durable::SIDECAR_LOCK_FILE;
use crate::durable::SidecarLock;
use crate::durable::canonical_json;
use crate::durable::lock_sidecar;
use crate::durable::reject_recreated_sidecar_for_owner_history;
use crate::durable::secure_hash_bounded;
use crate::durable::secure_read;
use crate::durable::secure_root;
use crate::durable::sha256;
use crate::durable::write_private_new;

const SCHEMA: &str = "hepta.learning.cell-split.child-state-batch-cas.v1";
const FROZEN: &str = "migration-frozen-plan.json";
const FROZEN_INPUT: &str = "migration-frozen-input.json";
const MAX_CHILD_BYTES: usize = 16 * 1024 * 1024;
const MAX_MANIFEST_BYTES: usize = 64 * 1024;

/// Production adapters must check real signed CAS predecessor state, live
/// acknowledged parent journal frontier, and NDU/Selector final-use authority.
/// A self-asserted digest or a coordinator-side cache is not sufficient.
pub trait CellSplitMigrationAuthorityPortV1 {
    type Error: std::fmt::Display;

    fn current_parent_anchor(
        &mut self,
        plan: &CellSplitExecutionPlanV1,
    ) -> Result<JournalAnchor, Self::Error>;

    fn verify_committed_artifact(
        &mut self,
        plan: &CellSplitExecutionPlanV1,
        cas_receipt_digest: &str,
    ) -> Result<(), Self::Error>;

    fn verify_final_use(
        &mut self,
        plan: &CellSplitExecutionPlanV1,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<(), Self::Error>;
}

#[derive(Debug, Error)]
pub enum CellSplitChildStateCasErrorV1 {
    #[error("child batch CAS binding, plan, or current state mismatch")]
    Invalid,
    #[error("child migration authority or parent readback denied: {0}")]
    Denied(String),
    #[error("Neuron child migration receipt rejected: {0}")]
    Migration(String),
    #[error("uncommitted child files remain after an ambiguous execution")]
    Ambiguous,
    #[error(transparent)]
    Durable(#[from] crate::AcceptanceError),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ChildCasEntryV1 {
    child_id: String,
    state_digest: String,
    payload_digest: String,
    payload_bytes: u64,
    cas_receipt_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ChildStateBatchCommitV1 {
    schema: String,
    intent: CellSplitExecutionIntentV1,
    parent_anchor_sequence: u64,
    parent_checkpoint_digest: String,
    split_digest: String,
    fence_digest: String,
    children: Vec<ChildCasEntryV1>,
    commit_witness_digest: String,
    batch_receipt_digest: String,
    migration_receipt_digest: String,
}

/// Single writer of one frozen split. No disk path is built from child IDs:
/// object names only contain derived bounded hashes and numeric ordinals.
pub struct CellSplitChildStateCasOwnerV1<A: CellSplitMigrationAuthorityPortV1> {
    root: PathBuf,
    plan: CellSplitExecutionPlanV1,
    plan_digest: String,
    migration: CellStateMigrationV1,
    frozen_input_bytes: Vec<u8>,
    authority: A,
    _lock: SidecarLock,
}

impl<A: CellSplitMigrationAuthorityPortV1> CellSplitChildStateCasOwnerV1<A> {
    pub fn open(
        root: &Path,
        plan: CellSplitExecutionPlanV1,
        migration: CellStateMigrationV1,
        authority: A,
    ) -> Result<Self, CellSplitChildStateCasErrorV1> {
        // Require the coordinator's complete frozen-plan contract even when
        // this effect owner is opened independently of Agentd.
        let plan_digest = plan
            .digest()
            .map_err(|_| CellSplitChildStateCasErrorV1::Invalid)?;
        if migration.phase() != CellStateMigrationPhaseV1::Prepared
            || migration.operation_id().as_str() != plan.split_id
            || migration.parent_anchor().sequence == 0
            || migration.parent_anchor().sequence == u64::MAX
            || migration.parent_anchor().checkpoint_digest.is_zero()
            || migration.split_digest().is_zero()
            || migration.fence_digest().is_zero()
            || !(2..=64).contains(&migration.children().len())
            || plan.parent_generation == 0
            || plan.parent_generation.checked_add(1) != Some(plan.child_generation)
            || plan.owner_ids[1].is_empty()
        {
            return Err(CellSplitChildStateCasErrorV1::Invalid);
        }
        for child in migration.children() {
            if child.parent_generation.get() != plan.parent_generation
                || child.candidate_generation.get() != plan.child_generation
                || child.parent_scope.to_string() != plan.scope_digest
                || child.parent_checkpoint_digest != migration.parent_anchor().checkpoint_digest
                || !child.verify_digest()
            {
                return Err(CellSplitChildStateCasErrorV1::Invalid);
            }
            let length = encode_cell_state_v1(child).len();
            if length == 0 || length > MAX_CHILD_BYTES {
                return Err(CellSplitChildStateCasErrorV1::Invalid);
            }
        }
        let root = secure_root(root, "child migration CAS root")?;
        // Once an owner lock has existed, the two frozen manifests cannot be
        // recreated after deletion. A lost manifest may conceal an already
        // staged or published child batch: only external reconciliation may
        // recover it, never implicit reinitialization from caller inputs.
        let initialized_before = match fs::symlink_metadata(root.join(SIDECAR_LOCK_FILE)) {
            Ok(_) => true,
            Err(error) if error.kind() == ErrorKind::NotFound => false,
            Err(error) => return Err(error.into()),
        };
        reject_recreated_sidecar_for_owner_history(
            &root,
            initialized_before,
            &[FROZEN, FROZEN_INPUT],
            &["migration-", "child-"],
        )?;
        let lock = lock_sidecar(&root)?;
        reject_recreated_sidecar_for_owner_history(
            &root,
            initialized_before,
            &[FROZEN, FROZEN_INPUT],
            &["migration-", "child-"],
        )?;

        let frozen_path = root.join(FROZEN);
        let frozen_bytes = canonical_json(&plan)?;
        let frozen_input_bytes = frozen_migration_bytes(&migration, &plan_digest)?;
        match fs::symlink_metadata(&frozen_path) {
            Ok(_) if secure_read(&frozen_path, MAX_MANIFEST_BYTES)? != frozen_bytes => {
                return Err(CellSplitChildStateCasErrorV1::Invalid);
            }
            Ok(_) => {}
            Err(error) if error.kind() == ErrorKind::NotFound => {
                if initialized_before {
                    return Err(CellSplitChildStateCasErrorV1::Ambiguous);
                }
                write_private_new(&frozen_path, &frozen_bytes)?;
            }
            Err(error) => return Err(error.into()),
        }
        let input_path = root.join(FROZEN_INPUT);
        match fs::symlink_metadata(&input_path) {
            Ok(_) if secure_read(&input_path, MAX_MANIFEST_BYTES)? != frozen_input_bytes => {
                return Err(CellSplitChildStateCasErrorV1::Invalid);
            }
            Ok(_) => {}
            Err(error) if error.kind() == ErrorKind::NotFound => {
                if initialized_before {
                    return Err(CellSplitChildStateCasErrorV1::Ambiguous);
                }
                write_private_new(&input_path, &frozen_input_bytes)?;
            }
            Err(error) => return Err(error.into()),
        }
        Ok(Self {
            root,
            plan,
            plan_digest,
            migration,
            frozen_input_bytes,
            authority,
            _lock: lock,
        })
    }

    fn binding(
        &self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<(), CellSplitChildStateCasErrorV1> {
        let expected_key = sha256(
            format!(
                "hepta.learning.cell-split.execution-owner.v1\0{}\0{}\0{}",
                self.plan_digest,
                CellSplitExecutionStepV1::ChildStateMigration.index(),
                intent.previous_receipt_digest,
            )
            .as_bytes(),
        );
        if intent.schema != "hepta.learning.cell-split.execution-owner.v1"
            || intent.step != CellSplitExecutionStepV1::ChildStateMigration
            || intent.owner_id != self.plan.owner_ids[1]
            || intent.plan_digest != self.plan_digest
            || intent.idempotency_key != expected_key
            || !digest_shape(&intent.previous_receipt_digest)
            || !digest_shape(&intent.idempotency_key)
            || secure_read(&self.root.join(FROZEN), MAX_MANIFEST_BYTES)?
                != canonical_json(&self.plan)?
            || secure_read(&self.root.join(FROZEN_INPUT), MAX_MANIFEST_BYTES)?
                != self.frozen_input_bytes
        {
            return Err(CellSplitChildStateCasErrorV1::Invalid);
        }
        Ok(())
    }

    fn verify_live(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<(), CellSplitChildStateCasErrorV1> {
        self.binding(intent)?;
        self.authority
            .verify_committed_artifact(&self.plan, &intent.previous_receipt_digest)
            .map_err(|e| CellSplitChildStateCasErrorV1::Denied(e.to_string()))?;
        if self
            .authority
            .current_parent_anchor(&self.plan)
            .map_err(|e| CellSplitChildStateCasErrorV1::Denied(e.to_string()))?
            != self.migration.parent_anchor()
        {
            return Err(CellSplitChildStateCasErrorV1::Invalid);
        }
        Ok(())
    }

    fn commit_path(&self, intent: &CellSplitExecutionIntentV1) -> PathBuf {
        self.root
            .join(format!("migration-{}.json", intent.idempotency_key))
    }

    fn child_path(
        &self,
        index: usize,
        intent: &CellSplitExecutionIntentV1,
        digest: Digest32,
    ) -> PathBuf {
        self.root.join(format!(
            "child-{}-{index:02}-{digest}.q24",
            intent.idempotency_key
        ))
    }

    /// Reconstruct every typed receipt from the frozen Neuron projection.
    /// Actual child bytes MUST always be re-read before the batch witness
    /// becomes a committed fact; there is no digest-only bypass.
    fn expected_manifest(
        &self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<ChildStateBatchCommitV1, CellSplitChildStateCasErrorV1> {
        let mut entries = Vec::with_capacity(self.migration.children().len());
        let mut receipts = Vec::with_capacity(self.migration.children().len());
        for (index, child) in self.migration.children().iter().enumerate() {
            let payload = encode_cell_state_v1(child);
            if payload.is_empty() || payload.len() > MAX_CHILD_BYTES {
                return Err(CellSplitChildStateCasErrorV1::Invalid);
            }
            let payload_digest = Digest32::of_bytes(&payload);
            // Read and hash the real child CAS file, not a declared digest.
            // Reopening up to 64 children must not materialize a second
            // 16 MiB Vec per child merely to compare identical Q24 bytes.
            // The secure reader checks inode, mode, ownership and path drift,
            // and rejects an oversized file before streaming it.
            let (disk_digest, disk_size) = secure_hash_bounded(
                &self.child_path(index, intent, payload_digest),
                MAX_CHILD_BYTES as u64,
            )?;
            if disk_digest != payload_digest.to_string() || disk_size != payload.len() as u64 {
                return Err(CellSplitChildStateCasErrorV1::Invalid);
            }
            let mut receipt = CellStateCasReceiptV1 {
                operation_id: self.migration.operation_id().clone(),
                child_cell_id: child.child_cell_id.clone(),
                parent_anchor: self.migration.parent_anchor(),
                payload_digest,
                encoded_size_bytes: payload.len() as u64,
                fence_digest: self.migration.fence_digest(),
                receipt_digest: Digest32::ZERO,
            };
            receipt.receipt_digest = receipt.content_digest();
            entries.push(ChildCasEntryV1 {
                child_id: child.child_cell_id.to_string(),
                state_digest: child.state_digest.to_string(),
                payload_digest: payload_digest.to_string(),
                payload_bytes: payload.len() as u64,
                cas_receipt_digest: receipt.receipt_digest.to_string(),
            });
            receipts.push(receipt);
        }
        let witness = Digest32::of_bytes(&canonical_json(&(
            SCHEMA,
            &self.plan_digest,
            intent,
            self.migration.parent_anchor().sequence,
            self.migration.parent_anchor().checkpoint_digest.to_string(),
            self.migration.fence_digest().to_string(),
            &entries,
        ))?);
        let mut typed = self.migration.clone();
        typed
            .record_payloads_durable(receipts.clone())
            .map_err(|e| CellSplitChildStateCasErrorV1::Migration(e.to_string()))?;
        let batch = CellStateBatchReceiptV1::new(
            self.migration.operation_id().clone(),
            self.migration.parent_anchor(),
            self.migration.fence_digest(),
            receipts.iter().map(|r| r.receipt_digest).collect(),
            witness,
        );
        typed
            .commit_children(batch.clone())
            .map_err(|e| CellSplitChildStateCasErrorV1::Migration(e.to_string()))?;
        let acknowledged = typed
            .acknowledge()
            .map_err(|e| CellSplitChildStateCasErrorV1::Migration(e.to_string()))?;
        Ok(ChildStateBatchCommitV1 {
            schema: SCHEMA.into(),
            intent: intent.clone(),
            parent_anchor_sequence: self.migration.parent_anchor().sequence,
            parent_checkpoint_digest: self.migration.parent_anchor().checkpoint_digest.to_string(),
            split_digest: self.migration.split_digest().to_string(),
            fence_digest: self.migration.fence_digest().to_string(),
            children: entries,
            commit_witness_digest: witness.to_string(),
            batch_receipt_digest: batch.receipt_digest.to_string(),
            migration_receipt_digest: acknowledged.receipt_digest.to_string(),
        })
    }

    fn read_manifest(
        &self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<Option<Vec<u8>>, CellSplitChildStateCasErrorV1> {
        self.binding(intent)?;
        match fs::symlink_metadata(self.commit_path(intent)) {
            Ok(_) => Ok(Some(secure_read(
                &self.commit_path(intent),
                MAX_MANIFEST_BYTES,
            )?)),
            Err(error) if error.kind() == ErrorKind::NotFound => Ok(None),
            Err(error) => Err(error.into()),
        }
    }

    fn verify_manifest(
        &self,
        intent: &CellSplitExecutionIntentV1,
        bytes: &[u8],
    ) -> Result<bool, CellSplitChildStateCasErrorV1> {
        let recorded: ChildStateBatchCommitV1 = serde_json::from_slice(bytes)?;
        let expected = self.expected_manifest(intent)?;
        Ok(recorded == expected && canonical_json(&recorded)? == bytes)
    }
}

impl<A: CellSplitMigrationAuthorityPortV1> CellSplitDurableEffectBackendV1
    for CellSplitChildStateCasOwnerV1<A>
{
    type Error = CellSplitChildStateCasErrorV1;

    fn authorize_execute(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<(), Self::Error> {
        self.verify_live(intent)?;
        self.authority
            .verify_final_use(&self.plan, intent)
            .map_err(|e| CellSplitChildStateCasErrorV1::Denied(e.to_string()))
    }

    fn commit_once(&mut self, intent: &CellSplitExecutionIntentV1) -> Result<(), Self::Error> {
        self.authorize_execute(intent)?;
        if let Some(bytes) = self.read_manifest(intent)? {
            if self.verify_manifest(intent, &bytes)? {
                // A signed prior child batch is available through ReadBack,
                // but must not be adopted as a new Execute effect.
                return Err(CellSplitChildStateCasErrorV1::Ambiguous);
            }
            return Err(CellSplitChildStateCasErrorV1::Invalid);
        }
        // Never resume partial external effects or forge an absent batch marker.
        for (index, child) in self.migration.children().iter().enumerate() {
            let digest = CellStateMigrationV1::child_payload_digest(child);
            match fs::symlink_metadata(self.child_path(index, intent, digest)) {
                Ok(_) => return Err(CellSplitChildStateCasErrorV1::Ambiguous),
                Err(error) if error.kind() == ErrorKind::NotFound => {}
                Err(error) => return Err(error.into()),
            }
        }
        for (index, child) in self.migration.children().iter().enumerate() {
            let path = self.child_path(
                index,
                intent,
                CellStateMigrationV1::child_payload_digest(child),
            );
            let mut options = fs::OpenOptions::new();
            options.write(true).create_new(true);
            #[cfg(unix)]
            {
                use std::os::unix::fs::OpenOptionsExt as _;
                options
                    .mode(0o600)
                    .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW);
            }
            let file = options.open(&path)?;
            let receipt = self
                .migration
                .persist_child_state(&child.child_cell_id, file)
                .map_err(|e| CellSplitChildStateCasErrorV1::Migration(e.to_string()))?;
            if receipt.payload_digest != CellStateMigrationV1::child_payload_digest(child) {
                return Err(CellSplitChildStateCasErrorV1::Invalid);
            }
        }
        // All files are fsync'd by Neuron. Directory sync must occur before
        // any commit marker is visible to CNS or Supervisor.
        fs::File::open(&self.root)?.sync_all()?;
        let manifest = self.expected_manifest(intent)?;
        self.verify_live(intent)?;
        self.authority
            .verify_final_use(&self.plan, intent)
            .map_err(|e| CellSplitChildStateCasErrorV1::Denied(e.to_string()))?;
        write_private_new(&self.commit_path(intent), &canonical_json(&manifest)?)?;
        Ok(())
    }

    fn read_committed(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<Option<CellSplitOwnedEffectV1>, Self::Error> {
        let Some(bytes) = self.read_manifest(intent)? else {
            return Ok(None);
        };
        // The raw backend port is also reachable without the surrounding
        // RPC service. Never expose an acknowledged migration if its original
        // commit marker no longer matches every child file on disk.
        if !self.verify_manifest(intent, &bytes)? {
            return Err(CellSplitChildStateCasErrorV1::Invalid);
        }
        let committed_sequence = self
            .migration
            .parent_anchor()
            .sequence
            .checked_add(1)
            .ok_or(CellSplitChildStateCasErrorV1::Invalid)?;
        Ok(Some(CellSplitOwnedEffectV1 {
            owner_sequence: committed_sequence,
            owner_receipt_bytes: bytes,
        }))
    }

    fn verify_current(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
        effect: &CellSplitOwnedEffectV1,
    ) -> Result<bool, Self::Error> {
        self.verify_live(intent)?;
        // A persisted old batch never bypasses a revoked Selector/NDU
        // decision when the coordinator is about to advance the CNS stage.
        self.authority
            .verify_final_use(&self.plan, intent)
            .map_err(|e| CellSplitChildStateCasErrorV1::Denied(e.to_string()))?;
        let Some(bytes) = self.read_manifest(intent)? else {
            return Ok(false);
        };
        Ok(
            effect.owner_sequence == self.current_sequence_for_intent(intent)?
                && effect.owner_receipt_bytes == bytes
                && self.verify_manifest(intent, &bytes)?,
        )
    }

    fn current_sequence(&mut self) -> Result<u64, Self::Error> {
        Ok(self.migration.parent_anchor().sequence)
    }

    fn current_sequence_for_intent(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<u64, Self::Error> {
        let predecessor = self.migration.parent_anchor().sequence;
        // A durable all-child commit marker advances this split's revision,
        // not the immutable parent Neuron checkpoint. Orphaned child payloads
        // must never advance the frontier or be adopted by a fresh Execute.
        match self.read_manifest(intent)? {
            Some(bytes) if self.verify_manifest(intent, &bytes)? => predecessor
                .checked_add(1)
                .ok_or(CellSplitChildStateCasErrorV1::Invalid),
            Some(_) => Err(CellSplitChildStateCasErrorV1::Invalid),
            None => Ok(predecessor),
        }
    }
}

/// The validated projection is frozen independently of the coordinator plan.
/// This prevents an alternate parent checkpoint or alternate Q24 children
/// from being replayed under the same split ID after a lost acknowledgement.
fn frozen_migration_bytes(
    migration: &CellStateMigrationV1,
    plan_digest: &str,
) -> Result<Vec<u8>, CellSplitChildStateCasErrorV1> {
    let children = migration
        .children()
        .iter()
        .map(|child| {
            let encoded = encode_cell_state_v1(child);
            (
                child.child_cell_id.to_string(),
                child.state_digest.to_string(),
                sha256(&encoded),
                encoded.len() as u64,
            )
        })
        .collect::<Vec<_>>();
    canonical_json(&(
        "hepta.learning.cell-split.frozen-migration-input.v1",
        plan_digest,
        migration.operation_id().as_str(),
        migration.parent_anchor().sequence,
        migration.parent_anchor().checkpoint_digest.to_string(),
        migration.split_digest().to_string(),
        migration.fence_digest().to_string(),
        children,
    ))
    .map_err(Into::into)
}

fn digest_shape(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
        && value.bytes().any(|b| b != b'0')
}

#[cfg(test)]
#[path = "cell_split_child_state_cas_tests.rs"]
mod tests;
