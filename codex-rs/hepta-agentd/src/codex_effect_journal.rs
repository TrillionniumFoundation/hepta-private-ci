//! The run owner's bounded append-only Abort/Enter frontier.
//!
//! No new authority or execution owner is introduced. The existing coordinator
//! holds this file under its mutex. Decisions are persisted before publication;
//! an uncertain write permanently fences this instance. Complete invalid frames
//! and torn tails fail closed, and are never silently discarded on recovery.

use std::collections::BTreeMap;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::BufRead;
use std::io::BufReader;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_agent_protocol::CodexEffectBinding;
use codex_hepta_agent_protocol::CodexEffectDecision;
use codex_hepta_agent_protocol::CodexEffectReceipt;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use crate::AgentRunError;

const MAX_FRAME: usize = 4096;
const MAX_BYTES: u64 = 32 * 1024 * 1024;
const MAX_RECORDS: usize = 16_384;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct Frame {
    schema: u32,
    agent_id: String,
    predecessor: String,
    receipt: CodexEffectReceipt,
    legacy: bool,
}

#[derive(Debug)]
pub(crate) struct CodexEffectJournal {
    path: PathBuf,
    file: File,
    agent_id: String,
    predecessor: String,
    bytes: u64,
    records: BTreeMap<String, Frame>,
    failed: bool,
}

impl CodexEffectJournal {
    pub(crate) fn open(path: &Path, agent_id: &str) -> Result<Self, AgentRunError> {
        if !path.is_absolute() || agent_id.is_empty() || agent_id.len() > 128 {
            return Err(AgentRunError::InvalidIdentity("effect frontier"));
        }
        let parent = path
            .parent()
            .ok_or(AgentRunError::EffectFrontierUnavailable)?;
        let directory = std::fs::symlink_metadata(parent).map_err(unavailable)?;
        if !directory.is_dir() {
            return Err(AgentRunError::EffectFrontierUnavailable);
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            if directory.mode() & 0o077 != 0 {
                return Err(AgentRunError::EffectFrontierUnavailable);
            }
        }
        let mut options = OpenOptions::new();
        options.read(true).append(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let file = match options.open(path) {
            Ok(file) => file,
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                let metadata = std::fs::symlink_metadata(path).map_err(unavailable)?;
                if !metadata.is_file() {
                    return Err(AgentRunError::EffectFrontierUnavailable);
                }
                OpenOptions::new()
                    .read(true)
                    .append(true)
                    .open(path)
                    .map_err(unavailable)?
            }
            Err(error) => return Err(unavailable(error)),
        };
        file.try_lock()
            .map_err(|_| AgentRunError::EffectFrontierUnavailable)?;
        let mut result = Self {
            path: path.to_path_buf(),
            file,
            agent_id: agent_id.to_string(),
            predecessor: "0".repeat(64),
            bytes: 0,
            records: BTreeMap::new(),
            failed: false,
        };
        result.validate_path()?;
        let mut reader = BufReader::new(result.file.try_clone().map_err(unavailable)?);
        loop {
            let mut bytes = Vec::new();
            let count = reader
                .by_ref()
                .take(MAX_FRAME as u64 + 1)
                .read_until(b'\n', &mut bytes)
                .map_err(unavailable)?;
            if count == 0 {
                break;
            }
            if count > MAX_FRAME || !bytes.ends_with(b"\n") {
                return Err(AgentRunError::EffectFrontierCorrupt);
            }
            result.bytes += count as u64;
            if result.bytes > MAX_BYTES || result.records.len() >= MAX_RECORDS {
                return Err(AgentRunError::CapacityExceeded);
            }
            let frame: Frame =
                serde_json::from_slice(&bytes).map_err(|_| AgentRunError::EffectFrontierCorrupt)?;
            validate_frame(&frame)?;
            if frame.agent_id != result.agent_id
                || frame.predecessor != result.predecessor
                || result.records.contains_key(&frame.receipt.binding.run_id)
            {
                return Err(AgentRunError::EffectFrontierCorrupt);
            }
            result.predecessor = Digest32::of_bytes(&bytes).to_string();
            result
                .records
                .insert(frame.receipt.binding.run_id.clone(), frame);
        }
        // A new directory entry and all replayed bytes must be durable before
        // this owner can acknowledge any decision.
        result.file.sync_all().map_err(unavailable)?;
        File::open(parent)
            .and_then(|file| file.sync_all())
            .map_err(unavailable)?;
        Ok(result)
    }

    fn validate_path(&self) -> Result<(), AgentRunError> {
        let current = std::fs::symlink_metadata(&self.path).map_err(unavailable)?;
        let opened = self.file.metadata().map_err(unavailable)?;
        if !current.is_file() || !opened.is_file() || opened.len() > MAX_BYTES {
            return Err(AgentRunError::EffectFrontierUnavailable);
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            let directory =
                std::fs::symlink_metadata(self.path.parent().unwrap()).map_err(unavailable)?;
            if current.dev() != opened.dev()
                || current.ino() != opened.ino()
                || opened.nlink() != 1
                || opened.mode() & 0o077 != 0
                || opened.uid() != directory.uid()
                || directory.mode() & 0o077 != 0
            {
                return Err(AgentRunError::EffectFrontierUnavailable);
            }
        }
        Ok(())
    }

    pub(crate) fn contains(&self, run_id: &str) -> bool {
        self.records.contains_key(run_id)
    }

    pub(crate) fn replay(
        &self,
        binding: &CodexEffectBinding,
        decision: CodexEffectDecision,
        reason: Option<&str>,
    ) -> Result<Option<CodexEffectReceipt>, AgentRunError> {
        if self.failed {
            return Err(AgentRunError::EffectFrontierUnavailable);
        }
        self.validate_path()?;
        let Some(frame) = self.records.get(&binding.run_id) else {
            return Ok(None);
        };
        if frame.legacy
            || &frame.receipt.binding != binding
            || frame.receipt.decision != decision
            || frame.receipt.reason.as_deref() != reason
        {
            return Err(AgentRunError::Conflict);
        }
        let mut receipt = frame.receipt.clone();
        receipt.idempotent = true;
        Ok(Some(receipt))
    }

    pub(crate) fn commit(
        &mut self,
        receipt: &CodexEffectReceipt,
        legacy: bool,
    ) -> Result<(), AgentRunError> {
        if self.failed {
            return Err(AgentRunError::EffectFrontierUnavailable);
        }
        self.validate_path()?;
        if self.records.contains_key(&receipt.binding.run_id) {
            return Err(AgentRunError::Conflict);
        }
        if self.records.len() >= MAX_RECORDS {
            return Err(AgentRunError::CapacityExceeded);
        }
        let frame = Frame {
            schema: 1,
            agent_id: self.agent_id.clone(),
            predecessor: self.predecessor.clone(),
            receipt: receipt.clone(),
            legacy,
        };
        validate_frame(&frame)?;
        let mut bytes =
            serde_json::to_vec(&frame).map_err(|_| AgentRunError::EffectFrontierCorrupt)?;
        bytes.push(b'\n');
        if bytes.len() > MAX_FRAME || self.bytes + bytes.len() as u64 > MAX_BYTES {
            return Err(AgentRunError::CapacityExceeded);
        }
        // Poison BEFORE attempting the write: after write/fsync uncertainty no
        // mutation, duplicate acknowledgement or new Enter is permitted here.
        self.failed = true;
        #[cfg(test)]
        crash_cut("owner-before-write");
        self.file.write_all(&bytes).map_err(unavailable)?;
        #[cfg(test)]
        crash_cut("owner-after-write");
        self.file.sync_all().map_err(unavailable)?;
        #[cfg(test)]
        crash_cut("owner-after-fsync");
        self.validate_path()?;
        self.bytes += bytes.len() as u64;
        self.predecessor = Digest32::of_bytes(&bytes).to_string();
        self.records.insert(receipt.binding.run_id.clone(), frame);
        self.failed = false;
        Ok(())
    }
}

fn validate_frame(frame: &Frame) -> Result<(), AgentRunError> {
    frame
        .receipt
        .binding
        .validate()
        .map_err(|_| AgentRunError::EffectFrontierCorrupt)?;
    if frame.schema != 1
        || frame.receipt.idempotent
        || frame.receipt.owner_revision != frame.receipt.binding.expected_revision + 1
        || (frame.legacy && frame.receipt.decision != CodexEffectDecision::Entered)
    {
        return Err(AgentRunError::EffectFrontierCorrupt);
    }
    match (frame.receipt.decision, frame.receipt.reason.as_deref()) {
        (CodexEffectDecision::Entered, None) => Ok(()),
        (CodexEffectDecision::AbortedBeforeEffect, Some(reason))
            if !reason.trim().is_empty() && reason.len() <= 512 && !reason.contains('\0') =>
        {
            Ok(())
        }
        _ => Err(AgentRunError::EffectFrontierCorrupt),
    }
}

fn unavailable(_: std::io::Error) -> AgentRunError {
    AgentRunError::EffectFrontierUnavailable
}

#[cfg(test)]
pub(crate) fn crash_cut(cut: &str) {
    if std::env::var("HEPTA_CODEX_OWNER_CRASH_CUT").ok().as_deref() == Some(cut) {
        println!("HEPTA_CODEX_CUT_REACHED");
        std::io::stdout().flush().unwrap();
        loop {
            std::thread::park();
        }
    }
}
