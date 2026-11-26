//! Cold receipt storage belonging to inference.control's sole writer. Budget
//! and retirement intent live in that journal; these files issue no authority.
use std::fs::File;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::Error;
use super::FeatureOperationRecordV1;
use super::FeatureOperationStateV1;
use super::codec;

pub(super) const MAX_RECEIPT_BYTES: u64 = 64 * 1024;
const MAX_INDEX_BYTES: u64 = 8 * 1024 * 1024;

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Receipt {
    version: u32,
    request: codec::Request,
    receipt: codec::Receipt,
    record_digest: String,
}
#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct Identity {
    request_id: String,
    request_digest: String,
    record_digest: String,
}

pub(super) struct Prepared {
    journal_path: PathBuf,
    receipt_path: PathBuf,
    index_path: PathBuf,
    receipt_bytes: Vec<u8>,
    index_bytes: Vec<u8>,
    pub(super) digest: String,
    pub(super) delta_bytes: u64,
    pub(super) temporary_bytes: u64,
}

pub(super) fn record_digest(record: &FeatureOperationRecordV1) -> Result<String, Error> {
    let FeatureOperationStateV1::Observed(receipt) = &record.state else {
        return Err(Error::InvalidTransition);
    };
    crate::verify_neuron_feature_receipt_v1(&record.request, receipt)
        .map_err(|_| Error::InvalidDigest("cold feature receipt"))?;
    let raw = serde_json::to_vec(&(
        "hepta.feature.archive.record.v1",
        codec::Request::from(&record.request),
        codec::Receipt::from(receipt.as_ref()),
    ))
    .map_err(|_| Error::CorruptJournal("cold feature encode"))?;
    Ok(Digest32::of_bytes(&raw).to_string())
}

fn paths(journal: &Path, id: &str) -> (PathBuf, PathBuf) {
    let key = Digest32::of_bytes(id.as_bytes()).to_string();
    let mut name = journal.file_name().unwrap_or_default().to_os_string();
    name.push(".feature-history-v1");
    let shard = journal
        .with_file_name(name)
        .join(&key[..2])
        .join(&key[2..4]);
    (
        shard.join(format!("{key}.json")),
        shard.join("identities.jsonl"),
    )
}

fn read_private(path: &Path, maximum: u64) -> Result<Option<Vec<u8>>, Error> {
    let metadata = match std::fs::symlink_metadata(path) {
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        value => value?,
    };
    if !metadata.is_file() || metadata.file_type().is_symlink() || metadata.len() > maximum {
        return Err(Error::CorruptJournal("cold feature file bounds"));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        let parent = path
            .parent()
            .ok_or(Error::InvalidIdentity("cold feature parent"))?;
        if metadata.nlink() != 1
            || metadata.mode() & 0o077 != 0
            || metadata.uid() != std::fs::metadata(parent)?.uid()
        {
            return Err(Error::CorruptJournal("cold feature file permissions"));
        }
    }
    let file = File::open(path)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        let opened = file.metadata()?;
        if opened.dev() != metadata.dev() || opened.ino() != metadata.ino() {
            return Err(Error::WriterUnavailable);
        }
    }
    let mut bytes = Vec::new();
    file.take(maximum + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 != metadata.len() {
        return Err(Error::CorruptJournal("cold feature file changed"));
    }
    Ok(Some(bytes))
}

fn index_entry(bytes: &[u8], id: &str) -> Result<Option<Identity>, Error> {
    if !bytes.is_empty() && bytes.last() != Some(&b'\n') {
        return Err(Error::CorruptJournal("cold feature incomplete index"));
    }
    let mut found = None;
    for line in bytes
        .split(|byte| *byte == b'\n')
        .filter(|line| !line.is_empty())
    {
        if line.len() > 2048 {
            return Err(Error::CapacityExceeded);
        }
        let entry: Identity = serde_json::from_slice(line)
            .map_err(|_| Error::CorruptJournal("cold feature identity index"))?;
        super::super::validate_identity(&entry.request_id, "cold feature identity")?;
        super::super::validate_digest(&entry.request_digest, "cold feature request")?;
        super::super::validate_digest(&entry.record_digest, "cold feature record")?;
        if entry.request_id == id {
            if found.as_ref().is_some_and(|prior| prior != &entry) {
                return Err(Error::CorruptJournal("cold feature conflicting identity"));
            }
            found = Some(entry);
        }
    }
    Ok(found)
}

pub(in crate::durable_control) fn lookup(
    journal: &Path,
    id: &str,
) -> Result<Option<FeatureOperationRecordV1>, Error> {
    super::super::validate_identity(id, "cold feature request")?;
    let (receipt_path, index_path) = paths(journal, id);
    if !directories(
        journal,
        receipt_path
            .parent()
            .ok_or(Error::InvalidIdentity("cold feature parent"))?,
        false,
    )? {
        return Ok(None);
    }
    let index = read_private(&index_path, MAX_INDEX_BYTES)?.unwrap_or_default();
    let identity = index_entry(&index, id)?;
    let raw = read_private(&receipt_path, MAX_RECEIPT_BYTES)?;
    match (identity, raw) {
        (None, None) => Ok(None),
        (Some(identity), Some(raw)) => {
            let stored: Receipt = serde_json::from_slice(&raw)
                .map_err(|_| Error::CorruptJournal("cold feature receipt decode"))?;
            let request = stored.request.decode()?;
            let receipt = stored.receipt.decode(&request)?;
            let record = FeatureOperationRecordV1 {
                request,
                state: FeatureOperationStateV1::Observed(Box::new(receipt)),
            };
            if stored.version != 1
                || record.request.request_id.as_str() != id
                || record_digest(&record)? != stored.record_digest
                || identity.record_digest != stored.record_digest
                || identity.request_digest
                    != crate::neuron_feature_request_digest_v1(&record.request)
                        .map_err(|_| Error::InvalidDigest("cold feature request"))?
                        .to_string()
            {
                return Err(Error::CorruptJournal("cold feature receipt binding"));
            }
            Ok(Some(record))
        }
        // The hot Observed record and durable archive intent remain available
        // at a cut between the two files. A missing receipt is never absence.
        _ => Err(Error::CorruptJournal("cold feature receipt/index missing")),
    }
}

pub(super) fn prepare(
    journal: &Path,
    record: &FeatureOperationRecordV1,
) -> Result<Prepared, Error> {
    let digest = record_digest(record)?;
    let FeatureOperationStateV1::Observed(receipt) = &record.state else {
        return Err(Error::InvalidTransition);
    };
    let (receipt_path, index_path) = paths(journal, record.request.request_id.as_str());
    directories(
        journal,
        receipt_path
            .parent()
            .ok_or(Error::InvalidIdentity("cold feature parent"))?,
        false,
    )?;
    let stored = Receipt {
        version: 1,
        request: (&record.request).into(),
        receipt: receipt.as_ref().into(),
        record_digest: digest.clone(),
    };
    let receipt_bytes = serde_json::to_vec(&stored)
        .map_err(|_| Error::CorruptJournal("cold feature receipt encode"))?;
    if receipt_bytes.len() as u64 > MAX_RECEIPT_BYTES {
        return Err(Error::CapacityExceeded);
    }
    if let Some(prior) = read_private(&receipt_path, MAX_RECEIPT_BYTES)?
        && prior != receipt_bytes
    {
        return Err(Error::Conflict);
    }
    let identity = Identity {
        request_id: record.request.request_id.to_string(),
        request_digest: crate::neuron_feature_request_digest_v1(&record.request)
            .map_err(|_| Error::InvalidDigest("cold feature request"))?
            .to_string(),
        record_digest: digest.clone(),
    };
    let mut entry = serde_json::to_vec(&identity)
        .map_err(|_| Error::CorruptJournal("cold feature index encode"))?;
    entry.push(b'\n');
    let delta_bytes = (receipt_bytes.len() + entry.len()) as u64;
    let mut index_bytes = read_private(&index_path, MAX_INDEX_BYTES)?.unwrap_or_default();
    match index_entry(&index_bytes, &identity.request_id)? {
        Some(prior) if prior == identity => {}
        Some(_) => return Err(Error::Conflict),
        None => index_bytes.extend(entry),
    }
    if index_bytes.len() as u64 > MAX_INDEX_BYTES {
        return Err(Error::CapacityExceeded);
    }
    Ok(Prepared {
        journal_path: journal.to_path_buf(),
        receipt_path,
        index_path,
        receipt_bytes,
        temporary_bytes: index_bytes.len() as u64,
        index_bytes,
        digest,
        delta_bytes,
    })
}

impl Prepared {
    pub(super) fn persist(self) -> Result<(), Error> {
        let parent = self
            .receipt_path
            .parent()
            .ok_or(Error::InvalidIdentity("cold feature parent"))?;
        directories(&self.journal_path, parent, true)?;
        replace_from_intent(&self.receipt_path, &self.receipt_bytes, MAX_RECEIPT_BYTES)?;
        replace_from_intent(&self.index_path, &self.index_bytes, MAX_INDEX_BYTES)
    }
}

fn directories(journal: &Path, leaf: &Path, create: bool) -> Result<bool, Error> {
    let middle = leaf
        .parent()
        .ok_or(Error::InvalidIdentity("cold feature shard"))?;
    let root = middle
        .parent()
        .ok_or(Error::InvalidIdentity("cold feature root"))?;
    for directory in [root, middle, leaf] {
        if create {
            let mut builder = std::fs::DirBuilder::new();
            #[cfg(unix)]
            {
                use std::os::unix::fs::DirBuilderExt;
                builder.mode(0o700);
            }
            match builder.create(directory) {
                Ok(()) => {
                    File::open(
                        directory
                            .parent()
                            .ok_or(Error::InvalidIdentity("cold feature parent"))?,
                    )?
                    .sync_all()?;
                }
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {}
                Err(error) => return Err(error.into()),
            }
        }
        let metadata = match std::fs::symlink_metadata(directory) {
            Err(error) if !create && error.kind() == std::io::ErrorKind::NotFound => {
                return Ok(false);
            }
            value => value?,
        };
        if !metadata.is_dir() || metadata.file_type().is_symlink() {
            return Err(Error::CorruptJournal("cold feature directory"));
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            if metadata.mode() & 0o077 != 0 || metadata.uid() != std::fs::metadata(journal)?.uid() {
                return Err(Error::CorruptJournal("cold feature directory permissions"));
            }
        }
        if create {
            File::open(directory)?.sync_all()?;
        }
    }
    Ok(true)
}

/// A single durable archive intent owns these deterministic temporary files.
/// Partial writes resume only if their exact prefix matches original bytes.
fn replace_from_intent(path: &Path, bytes: &[u8], maximum: u64) -> Result<(), Error> {
    if read_private(path, maximum)?.as_deref() == Some(bytes) {
        return Ok(());
    }
    let temporary = path.with_extension("feature-pending");
    let prior = read_private(&temporary, maximum)?.unwrap_or_default();
    if !bytes.starts_with(&prior) {
        return Err(Error::Conflict);
    }
    let mut options = super::super::archive_store::private_options();
    let mut file = options
        .create(true)
        .truncate(false)
        .append(true)
        .open(&temporary)?;
    file.write_all(&bytes[prior.len()..])?;
    file.sync_all()?;
    std::fs::rename(&temporary, path)?;
    File::open(
        path.parent()
            .ok_or(Error::InvalidIdentity("cold feature parent"))?,
    )?
    .sync_all()?;
    Ok(())
}
