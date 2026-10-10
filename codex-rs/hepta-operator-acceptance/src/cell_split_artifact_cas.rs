//! Concrete, create-only on-disk Artifact CAS owner for the first CellSplit step.
//!
//! This is a real file-operation backend, not an in-memory receipt fixture.
//! A production caller must provide a separate final-use verifier bound to
//! independently signed NDU/selector authority; this crate does not mint it.
//! Child migration, CNS routing and Supervisor fencing are NOT implemented
//! here and remain denied until their independent real owners are wired.

use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::io::ErrorKind;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use serde::Deserialize;
use serde::Serialize;
use sha2::Digest as _;
use sha2::Sha256;
use thiserror::Error;

use crate::CellSplitExecutionIntentV1;
use crate::CellSplitExecutionPlanV1;
use crate::CellSplitExecutionStepV1;
use crate::CellSplitDurableEffectBackendV1;
use crate::CellSplitOwnedEffectV1;
use crate::durable::canonical_json;
use crate::durable::secure_canonical_file_path;
use crate::durable::lock_sidecar;
use crate::durable::SidecarLock;
use crate::durable::secure_hash;
use crate::durable::secure_read;
use crate::durable::secure_root;
use crate::durable::sha256;
use crate::durable::write_private_new;

const SCHEMA: &str = "hepta.learning.cell-split.artifact-cas-commit.v1";
const FRONTIER_SCHEMA: &str = "hepta.learning.cell-split.artifact-cas-frontier.v1";
const MAX_RECEIPT_BYTES: usize = 64 * 1024;

/// Actual final-use check supplied by the deployment authority. In production
/// it must independently reread the NDU frontier and Selector authorization,
/// not merely compare a plan digest. No default allow-all implementation.
pub trait CellSplitCasFinalUsePortV1 {
    type Error: std::fmt::Display;
    fn verify_current_authority(
        &mut self,
        plan: &CellSplitExecutionPlanV1,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<(), Self::Error>;
}

#[derive(Debug, Error)]
pub enum CellSplitArtifactCasErrorV1 {
    #[error("artifact CAS frozen binding, operation, or state mismatch")]
    Invalid,
    #[error("artifact CAS final-use authority rejected effect: {0}")]
    Denied(String),
    #[error(transparent)]
    Io(#[from] io::Error),
    #[error(transparent)]
    Durable(#[from] crate::AcceptanceError),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ArtifactCasCommitV1 {
    schema: String,
    intent: CellSplitExecutionIntentV1,
    parent_digest: String,
    child_digest: String,
    object_bytes: u64,
    sequence: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ArtifactCasFrontierV1 {
    schema: String,
    plan_digest: String,
    sequence: u64,
}

/// One private CAS root per pinned split. The source file is hashed against
/// the frozen child artifact; the predecessor file must match the frozen
/// parent artifact. Object publication is create-new + fsync + directory
/// fsync, followed by a separately durable, intent-bound commit receipt.
/// A crash between these writes leaves a partial, unacknowledged effect: the
/// coordinator stays ambiguous and never forges a readback or retries it.
pub struct CellSplitArtifactCasOwnerV1<A: CellSplitCasFinalUsePortV1> {
    root: PathBuf,
    parent: PathBuf,
    child_source: PathBuf,
    plan: CellSplitExecutionPlanV1,
    plan_digest: String,
    authority: A,
    _lock: SidecarLock,
}

impl<A: CellSplitCasFinalUsePortV1> CellSplitArtifactCasOwnerV1<A> {
    pub fn open(
        root: &Path,
        parent: &Path,
        child_source: &Path,
        plan: CellSplitExecutionPlanV1,
        authority: A,
    ) -> Result<Self, CellSplitArtifactCasErrorV1> {
        let root = secure_root(root, "artifact CAS owner root")?;
        let lock = lock_sidecar(&root)?;
        let parent = secure_canonical_file_path(parent, "parent artifact")?;
        let child_source = secure_canonical_file_path(child_source, "child source artifact")?;
        if parent == child_source || plan.parent_generation == 0 ||
            plan.parent_generation.checked_add(1) != Some(plan.child_generation) ||
            plan.owner_ids[0].is_empty() {
            return Err(CellSplitArtifactCasErrorV1::Invalid);
        }
        let plan_digest = sha256(&canonical_json(&plan)?);
        let frontier = ArtifactCasFrontierV1 {
            schema: FRONTIER_SCHEMA.into(), plan_digest: plan_digest.clone(), sequence: 1
        };
        let path = root.join("cas-frontier.json");
        let expected = canonical_json(&frontier)?;
        match fs::symlink_metadata(&path) {
            Ok(_) if secure_read(&path, MAX_RECEIPT_BYTES)? != expected => {
                return Err(CellSplitArtifactCasErrorV1::Invalid);
            }
            Ok(_) => {}
            Err(error) if error.kind() == ErrorKind::NotFound => write_private_new(&path, &expected)?,
            Err(error) => return Err(error.into()),
        }
        Ok(Self { root, parent, child_source, plan, plan_digest, authority, _lock: lock })
    }

    fn binding(&self, intent: &CellSplitExecutionIntentV1)
        -> Result<(), CellSplitArtifactCasErrorV1>
    {
        let predecessor = &self.plan_digest;
        let expected = sha256(format!(
            "hepta.learning.cell-split.execution-owner.v1\0{}\0{}\0{}",
            self.plan_digest, CellSplitExecutionStepV1::ArtifactCas.index(), predecessor
        ).as_bytes());
        if intent.schema != "hepta.learning.cell-split.execution-owner.v1" ||
            intent.step != CellSplitExecutionStepV1::ArtifactCas ||
            intent.owner_id != self.plan.owner_ids[0] ||
            intent.plan_digest != self.plan_digest ||
            intent.previous_receipt_digest != *predecessor ||
            intent.idempotency_key != expected {
            return Err(CellSplitArtifactCasErrorV1::Invalid);
        }
        Ok(())
    }

    fn object_path(&self) -> PathBuf {
        self.root.join(format!("sha256-{}", self.plan.child_artifact_digest))
    }

    fn commit_path(&self, intent: &CellSplitExecutionIntentV1) -> PathBuf {
        self.root.join(format!("cas-{}.json", intent.idempotency_key))
    }

    fn verify_hash(path: &Path, expected: &str) -> Result<u64, CellSplitArtifactCasErrorV1> {
        let (actual, size) = secure_hash(path)?;
        if actual != expected || size == 0 {
            return Err(CellSplitArtifactCasErrorV1::Invalid);
        }
        Ok(size)
    }

    fn verify_parent(&self) -> Result<(), CellSplitArtifactCasErrorV1> {
        Self::verify_hash(&self.parent, &self.plan.parent_artifact_digest)?;
        Ok(())
    }

    fn object_size(&self) -> Result<u64, CellSplitArtifactCasErrorV1> {
        Self::verify_hash(&self.object_path(), &self.plan.child_artifact_digest)
    }

    /// Copy an actual artifact into a create-only immutable CAS object. Never
    /// use rename-overwrite; a partial object fails readback after a crash.
    fn publish_object(&self) -> Result<u64, CellSplitArtifactCasErrorV1> {
        let path = self.object_path();
        match fs::symlink_metadata(&path) {
            Ok(_) => return self.object_size(),
            Err(error) if error.kind() == ErrorKind::NotFound => {}
            Err(error) => return Err(error.into()),
        }
        let expected_size = Self::verify_hash(
            &self.child_source, &self.plan.child_artifact_digest
        )?;
        let mut source = OpenOptions::new().read(true);
        let mut target = OpenOptions::new();
        target.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            source.custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC);
            target.mode(0o600).custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC);
        }
        let mut source = source.open(&self.child_source)?;
        let mut target = target.open(&path)?;
        let mut buffer = [0u8; 128 * 1024];
        let mut sha = Sha256::new();
        let mut size = 0_u64;
        loop {
            let count = source.read(&mut buffer)?;
            if count == 0 {
                break;
            }
            size = size.checked_add(count as u64).ok_or(CellSplitArtifactCasErrorV1::Invalid)?;
            if size > crate::durable::MAX_ARTIFACT_BYTES {
                return Err(CellSplitArtifactCasErrorV1::Invalid);
            }
            sha.update(&buffer[..count]);
            target.write_all(&buffer[..count])?;
        }
        target.sync_all()?;
        if size != expected_size || format!("{:x}", sha.finalize()) != self.plan.child_artifact_digest {
            return Err(CellSplitArtifactCasErrorV1::Invalid);
        }
        File::open(&self.root)?.sync_all()?;
        if self.object_size()? != size {
            return Err(CellSplitArtifactCasErrorV1::Invalid);
        }
        Ok(size)
    }

    fn committed_record(
        &self, intent: &CellSplitExecutionIntentV1
    ) -> Result<Option<(ArtifactCasCommitV1, Vec<u8>)>, CellSplitArtifactCasErrorV1> {
        self.binding(intent)?;
        let path = self.commit_path(intent);
        let bytes = match fs::symlink_metadata(&path) {
            Ok(_) => secure_read(&path, MAX_RECEIPT_BYTES)?,
            Err(error) if error.kind() == ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(error.into()),
        };
        let record: ArtifactCasCommitV1 = serde_json::from_slice(&bytes)?;
        if record.schema != SCHEMA || record.intent != *intent ||
            record.parent_digest != self.plan.parent_artifact_digest ||
            record.child_digest != self.plan.child_artifact_digest ||
            record.sequence != 1 || record.object_bytes == 0 ||
            canonical_json(&record)? != bytes {
            return Err(CellSplitArtifactCasErrorV1::Invalid);
        }
        Ok(Some((record, bytes)))
    }

    fn frontier(&self) -> Result<u64, CellSplitArtifactCasErrorV1> {
        let bytes = secure_read(&self.root.join("cas-frontier.json"), MAX_RECEIPT_BYTES)?;
        let state: ArtifactCasFrontierV1 = serde_json::from_slice(&bytes)?;
        if state.schema != FRONTIER_SCHEMA || state.plan_digest != self.plan_digest ||
            state.sequence != 1 || canonical_json(&state)? != bytes {
            return Err(CellSplitArtifactCasErrorV1::Invalid);
        }
        Ok(state.sequence)
    }
}

impl<A: CellSplitCasFinalUsePortV1> CellSplitDurableEffectBackendV1 for CellSplitArtifactCasOwnerV1<A> {
    type Error = CellSplitArtifactCasErrorV1;

    fn authorize_execute(&mut self, intent: &CellSplitExecutionIntentV1)
        -> Result<(), Self::Error>
    {
        self.binding(intent)?;
        self.verify_parent()?;
        Self::verify_hash(&self.child_source, &self.plan.child_artifact_digest)?;
        self.frontier()?;
        self.authority.verify_current_authority(&self.plan, intent)
            .map_err(|e| CellSplitArtifactCasErrorV1::Denied(e.to_string()))
    }

    fn commit_once(&mut self, intent: &CellSplitExecutionIntentV1) -> Result<(), Self::Error> {
        self.authorize_execute(intent)?;
        if let Some((record, bytes)) = self.committed_record(intent)? {
            let existing = CellSplitOwnedEffectV1 {
                owner_sequence: record.sequence,
                owner_receipt_bytes: bytes,
            };
            if self.verify_current(intent, &existing)? {
                return Ok(());
            }
            return Err(CellSplitArtifactCasErrorV1::Invalid);
        }
        let size = self.publish_object()?;
        self.verify_parent()?;
        // Recheck independently owned selection/NDU authority at the final
        // durable publication boundary, after the potentially long file copy.
        self.authority.verify_current_authority(&self.plan, intent)
            .map_err(|e| CellSplitArtifactCasErrorV1::Denied(e.to_string()))?;
        let record = ArtifactCasCommitV1 {
            schema: SCHEMA.into(), intent: intent.clone(),
            parent_digest: self.plan.parent_artifact_digest.clone(),
            child_digest: self.plan.child_artifact_digest.clone(),
            object_bytes: size, sequence: self.frontier()?,
        };
        write_private_new(&self.commit_path(intent), &canonical_json(&record)?)?;
        Ok(())
    }

    fn read_committed(&mut self, intent: &CellSplitExecutionIntentV1)
        -> Result<Option<CellSplitOwnedEffectV1>, Self::Error>
    {
        Ok(self.committed_record(intent)?.map(|(record, bytes)| CellSplitOwnedEffectV1 {
            owner_sequence: record.sequence,
            owner_receipt_bytes: bytes,
        }))
    }

    fn verify_current(&mut self, intent: &CellSplitExecutionIntentV1,
        effect: &CellSplitOwnedEffectV1) -> Result<bool, Self::Error>
    {
        let Some((record, bytes)) = self.committed_record(intent)? else {
            return Ok(false);
        };
        self.verify_parent()?;
        Ok(effect.owner_sequence == self.frontier()? &&
            record.object_bytes == self.object_size()? &&
            effect.owner_receipt_bytes == bytes)
    }

    fn current_sequence(&mut self) -> Result<u64, Self::Error> {
        self.frontier()
    }
}

#[cfg(test)]
#[path = "cell_split_artifact_cas_tests.rs"]
mod tests;
