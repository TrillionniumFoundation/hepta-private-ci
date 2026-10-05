use std::collections::BTreeMap;
use std::io::Write;
use std::path::Path;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::COMPACTED_FILE;
use super::COMPACTED_MAGIC;
use super::CompactedPrefix;
use super::MAX_COMPACTED_BYTES;
use super::MAX_RUN_START_SEGMENTS;
use super::RunStartAnchor;
use super::RunStartAuthenticationV1;
use super::RunStartIndexEntryV1;
use super::RunStartIndexKindV1;
use super::RunStartObjectiveDispositionV1;
use super::RunStartStoreError;
use super::create_private;
use super::sync_directory;

const SUMMARY_FRAME_BYTES: usize = 8 + 32 + 1 + 40 + 32 + 40 + 32 + 4 + 32;
// Three nonempty length-prefixed IDs, authentication, chain identity, and the
// smaller conflict variant. Check before any attacker-controlled reservation.
const MIN_INDEX_ENTRY_BYTES: usize = 3 * 5 + 3 * 8 + 2 * 32 + 64 + 8 + 2 * 32 + 1 + 8;

fn encoded_compacted_length(entries: &[RunStartIndexEntryV1]) -> Result<usize, RunStartStoreError> {
    if entries.is_empty() || entries.len() > MAX_RUN_START_SEGMENTS * 4096 {
        return Err(RunStartStoreError::Capacity);
    }
    entries
        .iter()
        .try_fold(SUMMARY_FRAME_BYTES, |total, entry| {
            let kind_bytes = match entry.kind {
                RunStartIndexKindV1::Run { .. } => 1 + 8 + 8 + 32 + 1,
                RunStartIndexKindV1::Conflict { .. } => 1 + 8,
            };
            let entry_bytes = 236
                + entry.run_id.as_str().len()
                + entry.authentication.issuer_id.as_str().len()
                + entry.authentication.message_id.as_str().len()
                + kind_bytes;
            total
                .checked_add(entry_bytes)
                .filter(|size| *size as u64 <= MAX_COMPACTED_BYTES)
                .ok_or(RunStartStoreError::Capacity)
        })
}

pub(super) fn load_compacted_prefix(
    root: &Path,
    binding: Digest32,
) -> Result<CompactedPrefix, RunStartStoreError> {
    let path = root.join(COMPACTED_FILE);
    if !path.exists() {
        return Ok(CompactedPrefix::empty());
    }
    let metadata = std::fs::symlink_metadata(&path)?;
    if !metadata.is_file()
        || metadata.file_type().is_symlink()
        || metadata.len() == 0
        || metadata.len() > MAX_COMPACTED_BYTES
    {
        return Err(RunStartStoreError::Corrupt);
    }
    let bytes = std::fs::read(path)?;
    decode_compacted_prefix(&bytes, binding)
}

pub(super) fn write_compacted_prefix(
    root: &Path,
    binding: Digest32,
    compacted: &CompactedPrefix,
) -> Result<(), RunStartStoreError> {
    let bytes = encode_compacted_prefix(binding, compacted)?;
    let temporary = root.join(format!(
        ".{COMPACTED_FILE}.{}.{}.tmp",
        std::process::id(),
        compacted.prefix.sequence
    ));
    let target = root.join(COMPACTED_FILE);
    let result = (|| -> Result<(), RunStartStoreError> {
        let mut file = create_private(&temporary)?;
        file.write_all(&bytes)?;
        file.sync_all()?;
        std::fs::rename(&temporary, target)?;
        sync_directory(root)
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&temporary);
    }
    result
}

fn encode_compacted_prefix(
    binding: Digest32,
    compacted: &CompactedPrefix,
) -> Result<Vec<u8>, RunStartStoreError> {
    let encoded_length = encoded_compacted_length(&compacted.entries)?;
    validate_compacted_entries(compacted.prefix, &compacted.entries)?;
    let semantic = compacted_semantic_digest(binding, compacted.prefix, &compacted.entries)?;
    if semantic != compacted.digest {
        return Err(RunStartStoreError::Corrupt);
    }
    let mut bytes = Vec::new();
    bytes
        .try_reserve_exact(encoded_length)
        .map_err(|_| RunStartStoreError::Capacity)?;
    bytes.extend_from_slice(COMPACTED_MAGIC);
    push_digest(&mut bytes, binding);
    match compacted.pending_previous {
        Some((prefix, digest)) => {
            bytes.push(1);
            push_anchor(&mut bytes, prefix);
            push_digest(&mut bytes, digest);
        }
        None => {
            bytes.push(0);
            push_anchor(&mut bytes, RunStartAnchor::ZERO);
            push_digest(&mut bytes, Digest32::ZERO);
        }
    }
    push_anchor(&mut bytes, compacted.prefix);
    push_digest(&mut bytes, compacted.digest);
    push_u32(
        &mut bytes,
        u32::try_from(compacted.entries.len()).map_err(|_| RunStartStoreError::Capacity)?,
    );
    for entry in &compacted.entries {
        encode_index_entry(&mut bytes, entry)?;
    }
    let checksum = Digest32::of_bytes(&bytes);
    push_digest(&mut bytes, checksum);
    if bytes.len() as u64 > MAX_COMPACTED_BYTES {
        return Err(RunStartStoreError::Capacity);
    }
    Ok(bytes)
}

fn decode_compacted_prefix(
    bytes: &[u8],
    binding: Digest32,
) -> Result<CompactedPrefix, RunStartStoreError> {
    if bytes.len() < SUMMARY_FRAME_BYTES || bytes.len() as u64 > MAX_COMPACTED_BYTES {
        return Err(RunStartStoreError::Corrupt);
    }
    let (payload, supplied_checksum) = bytes.split_at(bytes.len() - 32);
    if Digest32::of_bytes(payload).as_array() != supplied_checksum {
        return Err(RunStartStoreError::Corrupt);
    }
    let mut reader = SummaryReader(payload);
    if reader.bytes(8)? != COMPACTED_MAGIC {
        return Err(RunStartStoreError::Corrupt);
    }
    if reader.digest()? != binding {
        return Err(RunStartStoreError::BindingMismatch);
    }
    let state = reader.byte()?;
    let previous_prefix = reader.anchor()?;
    let previous_digest = reader.digest()?;
    let prefix = reader.anchor()?;
    let digest = reader.digest()?;
    let count = reader.u32()? as usize;
    if count == 0 || count > MAX_RUN_START_SEGMENTS * 4096 {
        return Err(RunStartStoreError::Capacity);
    }
    if count > reader.0.len() / MIN_INDEX_ENTRY_BYTES {
        return Err(RunStartStoreError::Corrupt);
    }
    let mut entries = Vec::new();
    entries
        .try_reserve_exact(count)
        .map_err(|_| RunStartStoreError::Capacity)?;
    for _ in 0..count {
        entries.push(decode_index_entry(&mut reader)?);
    }
    if !reader.0.is_empty() {
        return Err(RunStartStoreError::Corrupt);
    }
    let pending_previous = match state {
        0 if previous_prefix == RunStartAnchor::ZERO && previous_digest.is_zero() => None,
        1 if previous_prefix.is_well_formed()
            && ((previous_prefix.sequence == 0) == previous_digest.is_zero()) =>
        {
            Some((previous_prefix, previous_digest))
        }
        _ => return Err(RunStartStoreError::Corrupt),
    };
    validate_compacted_entries(prefix, &entries)?;
    if compacted_semantic_digest(binding, prefix, &entries)? != digest {
        return Err(RunStartStoreError::Corrupt);
    }
    Ok(CompactedPrefix {
        prefix,
        digest,
        pending_previous,
        entries,
    })
}

pub(super) fn compacted_semantic_digest(
    binding: Digest32,
    prefix: RunStartAnchor,
    entries: &[RunStartIndexEntryV1],
) -> Result<Digest32, RunStartStoreError> {
    encoded_compacted_length(entries)?;
    let mut bytes = b"hepta.run-start.compacted.v1\0".to_vec();
    push_digest(&mut bytes, binding);
    push_anchor(&mut bytes, prefix);
    push_u32(
        &mut bytes,
        u32::try_from(entries.len()).map_err(|_| RunStartStoreError::Capacity)?,
    );
    for entry in entries {
        encode_index_entry(&mut bytes, entry)?;
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn validate_compacted_entries(
    prefix: RunStartAnchor,
    entries: &[RunStartIndexEntryV1],
) -> Result<(), RunStartStoreError> {
    if entries.is_empty() || !prefix.is_well_formed() || prefix.sequence != entries.len() as u64 {
        return Err(RunStartStoreError::Corrupt);
    }
    let mut predecessor = Digest32::ZERO;
    let mut identities = BTreeMap::new();
    for (offset, entry) in entries.iter().enumerate() {
        let expected_sequence = offset as u64 + 1;
        if entry.sequence != expected_sequence
            || entry.record_digest.is_zero()
            || entry.chain_digest
                != super::super::digest_chain(predecessor, entry.sequence, entry.record_digest)
            || identities.insert(entry.run_id.clone(), ()).is_some()
            || entry.authentication.key_epoch == 0
            || entry.authentication.sequence == 0
            || entry.authentication.expires_at_ms == 0
            || entry.authentication.scope_digest.is_zero()
            || entry.authentication.signed_body_digest.is_zero()
            || entry.authentication.signature.iter().all(|byte| *byte == 0)
        {
            return Err(RunStartStoreError::Corrupt);
        }
        match entry.kind {
            RunStartIndexKindV1::Run {
                deadline_unix_micros,
                generation,
                fence_digest,
                ..
            } if deadline_unix_micros > 0 && generation > 0 && !fence_digest.is_zero() => {}
            RunStartIndexKindV1::Conflict {
                deadline_unix_micros,
            } if deadline_unix_micros > 0 => {}
            _ => return Err(RunStartStoreError::Corrupt),
        }
        predecessor = entry.chain_digest;
    }
    if prefix.chain_digest != predecessor {
        return Err(RunStartStoreError::Corrupt);
    }
    Ok(())
}

fn encode_index_entry(
    bytes: &mut Vec<u8>,
    entry: &RunStartIndexEntryV1,
) -> Result<(), RunStartStoreError> {
    push_id(bytes, &entry.run_id)?;
    push_id(bytes, &entry.authentication.issuer_id)?;
    push_u64(bytes, entry.authentication.key_epoch);
    push_id(bytes, &entry.authentication.message_id)?;
    push_u64(bytes, entry.authentication.sequence);
    push_u64(bytes, entry.authentication.expires_at_ms);
    push_digest(bytes, entry.authentication.scope_digest);
    push_digest(bytes, entry.authentication.signed_body_digest);
    bytes.extend_from_slice(&entry.authentication.signature);
    push_u64(bytes, entry.sequence);
    push_digest(bytes, entry.record_digest);
    push_digest(bytes, entry.chain_digest);
    match entry.kind {
        RunStartIndexKindV1::Run {
            deadline_unix_micros,
            generation,
            fence_digest,
            disposition,
        } => {
            bytes.push(1);
            push_u64(bytes, deadline_unix_micros);
            push_u64(bytes, generation);
            push_digest(bytes, fence_digest);
            bytes.push(match disposition {
                RunStartObjectiveDispositionV1::Compiled => 1,
                RunStartObjectiveDispositionV1::ExplicitAbstain => 2,
            });
        }
        RunStartIndexKindV1::Conflict {
            deadline_unix_micros,
        } => {
            bytes.push(2);
            push_u64(bytes, deadline_unix_micros);
        }
    }
    Ok(())
}

fn decode_index_entry(
    reader: &mut SummaryReader<'_>,
) -> Result<RunStartIndexEntryV1, RunStartStoreError> {
    let run_id = reader.id()?;
    let authentication = RunStartAuthenticationV1 {
        issuer_id: reader.id()?,
        key_epoch: reader.u64()?,
        message_id: reader.id()?,
        sequence: reader.u64()?,
        expires_at_ms: reader.u64()?,
        scope_digest: reader.digest()?,
        signed_body_digest: reader.digest()?,
        signature: reader.take()?,
    };
    let sequence = reader.u64()?;
    let record_digest = reader.digest()?;
    let chain_digest = reader.digest()?;
    let kind = match reader.byte()? {
        1 => {
            let deadline_unix_micros = reader.u64()?;
            let generation = reader.u64()?;
            let fence_digest = reader.digest()?;
            let disposition = match reader.byte()? {
                1 => RunStartObjectiveDispositionV1::Compiled,
                2 => RunStartObjectiveDispositionV1::ExplicitAbstain,
                _ => return Err(RunStartStoreError::Corrupt),
            };
            RunStartIndexKindV1::Run {
                deadline_unix_micros,
                generation,
                fence_digest,
                disposition,
            }
        }
        2 => RunStartIndexKindV1::Conflict {
            deadline_unix_micros: reader.u64()?,
        },
        _ => return Err(RunStartStoreError::Corrupt),
    };
    Ok(RunStartIndexEntryV1 {
        run_id,
        authentication,
        sequence,
        record_digest,
        chain_digest,
        kind,
    })
}

fn push_anchor(bytes: &mut Vec<u8>, anchor: RunStartAnchor) {
    push_u64(bytes, anchor.sequence);
    push_digest(bytes, anchor.chain_digest);
}

fn push_digest(bytes: &mut Vec<u8>, digest: Digest32) {
    bytes.extend_from_slice(digest.as_array());
}

fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

fn push_u32(bytes: &mut Vec<u8>, value: u32) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), RunStartStoreError> {
    let raw = value.as_str().as_bytes();
    push_u32(
        bytes,
        u32::try_from(raw.len()).map_err(|_| RunStartStoreError::Capacity)?,
    );
    bytes.extend_from_slice(raw);
    Ok(())
}

struct SummaryReader<'a>(&'a [u8]);

impl SummaryReader<'_> {
    fn bytes(&mut self, count: usize) -> Result<&[u8], RunStartStoreError> {
        let Some((value, remaining)) = self.0.split_at_checked(count) else {
            return Err(RunStartStoreError::Corrupt);
        };
        self.0 = remaining;
        Ok(value)
    }

    fn take<const N: usize>(&mut self) -> Result<[u8; N], RunStartStoreError> {
        self.bytes(N)?
            .try_into()
            .map_err(|_| RunStartStoreError::Corrupt)
    }

    fn byte(&mut self) -> Result<u8, RunStartStoreError> {
        Ok(self.take::<1>()?[0])
    }

    fn u32(&mut self) -> Result<u32, RunStartStoreError> {
        Ok(u32::from_be_bytes(self.take()?))
    }

    fn u64(&mut self) -> Result<u64, RunStartStoreError> {
        Ok(u64::from_be_bytes(self.take()?))
    }

    fn digest(&mut self) -> Result<Digest32, RunStartStoreError> {
        Ok(Digest32::from_array(self.take()?))
    }

    fn anchor(&mut self) -> Result<RunStartAnchor, RunStartStoreError> {
        Ok(RunStartAnchor {
            sequence: self.u64()?,
            chain_digest: self.digest()?,
        })
    }

    fn id(&mut self) -> Result<StableId, RunStartStoreError> {
        let length = self.u32()? as usize;
        if !(1..=128).contains(&length) {
            return Err(RunStartStoreError::Corrupt);
        }
        let text =
            std::str::from_utf8(self.bytes(length)?).map_err(|_| RunStartStoreError::Corrupt)?;
        StableId::new(text).map_err(|_| RunStartStoreError::Corrupt)
    }
}
