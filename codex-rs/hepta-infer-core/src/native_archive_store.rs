//! Immutable native terminal receipts with a sharded replay-prevention index.
//! This is storage of the existing control owner, not another authority owner.

use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::BufRead;
use std::io::BufReader;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::Error;
use super::native::NativeRunRecord;

const MAX_RECEIPT_BYTES: u64 = 4 * 1024 * 1024;
const MAX_INDEX_BYTES: u64 = 8 * 1024 * 1024;
const MAX_INDEX_LINE_BYTES: u64 = 2048;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct Tombstone {
    request_id: String,
    request_sha256: String,
    record_sha256: String,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Receipt {
    schema_version: u32,
    record: NativeRunRecord,
    record_sha256: String,
}

pub(super) fn record_digest(record: &NativeRunRecord) -> Result<String, Error> {
    let bytes = serde_json::to_vec(&("hepta.native.archive.record.v1", record))
        .map_err(|_| Error::CorruptJournal("archive encode"))?;
    Ok(Digest32::of_bytes(&bytes).to_string())
}

fn request_digest(record: &NativeRunRecord) -> Result<String, Error> {
    let bytes = serde_json::to_vec(&("hepta.native.archive.request.v1", &record.request))
        .map_err(|_| Error::CorruptJournal("archive request encode"))?;
    Ok(Digest32::of_bytes(&bytes).to_string())
}

pub(super) fn history_root(journal: &Path) -> PathBuf {
    let mut name = journal.file_name().unwrap_or_default().to_os_string();
    name.push(".native-history-v1");
    journal.with_file_name(name)
}

fn paths(journal: &Path, request_id: &str) -> (PathBuf, PathBuf) {
    let key = Digest32::of_bytes(request_id.as_bytes()).to_string();
    let root = history_root(journal);
    let shard = root.join(&key[..2]).join(&key[2..4]);
    (
        shard.join(format!("{key}.json")),
        shard.join("identities.jsonl"),
    )
}

fn read_tombstone(path: &Path, request_id: &str) -> Result<Option<Tombstone>, Error> {
    let file = match File::open(path) {
        Ok(file) => file,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.into()),
    };
    let mut reader = BufReader::new(file);
    let mut bytes = 0_u64;
    let mut found = None;
    loop {
        let mut line = Vec::new();
        let count = (&mut reader)
            .take(MAX_INDEX_LINE_BYTES + 1)
            .read_until(b'\n', &mut line)?;
        if count == 0 {
            break;
        }
        bytes += count as u64;
        if count as u64 > MAX_INDEX_LINE_BYTES || bytes > MAX_INDEX_BYTES {
            return Err(Error::CapacityExceeded);
        }
        if line.pop() != Some(b'\n') {
            return Err(Error::CorruptJournal("incomplete native archive index"));
        }
        let entry: Tombstone = serde_json::from_slice(&line)
            .map_err(|_| Error::CorruptJournal("native archive index"))?;
        super::validate_identity(&entry.request_id, "archived native request")?;
        super::validate_digest(&entry.request_sha256, "archived native request")?;
        super::validate_digest(&entry.record_sha256, "archived native record")?;
        if entry.request_id == request_id {
            if found.as_ref().is_some_and(|prior| prior != &entry) {
                return Err(Error::CorruptJournal("conflicting native archive index"));
            }
            found = Some(entry);
        }
    }
    Ok(found)
}

pub(super) fn lookup(journal: &Path, request_id: &str) -> Result<Option<NativeRunRecord>, Error> {
    super::validate_identity(request_id, "archived native request")?;
    let (receipt_path, index_path) = paths(journal, request_id);
    let tombstone = read_tombstone(&index_path, request_id)?;
    let file = match File::open(&receipt_path) {
        Ok(file) => file,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            return if tombstone.is_some() {
                Err(Error::CorruptJournal("native archive receipt missing"))
            } else {
                Ok(None)
            };
        }
        Err(error) => return Err(error.into()),
    };
    let mut bytes = Vec::new();
    file.take(MAX_RECEIPT_BYTES + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > MAX_RECEIPT_BYTES {
        return Err(Error::CapacityExceeded);
    }
    let receipt: Receipt = serde_json::from_slice(&bytes)
        .map_err(|_| Error::CorruptJournal("native archive receipt"))?;
    if receipt.schema_version != 1
        || receipt.record.request.request_id != request_id
        || record_digest(&receipt.record)? != receipt.record_sha256
        || !super::archive::eligible(&receipt.record)
    {
        return Err(Error::CorruptJournal("native archive receipt identity"));
    }
    if let Some(tombstone) = tombstone
        && (tombstone.record_sha256 != receipt.record_sha256
            || tombstone.request_sha256 != request_digest(&receipt.record)?)
    {
        return Err(Error::CorruptJournal(
            "native archive receipt/index mismatch",
        ));
    }
    // A complete immutable receipt without an index entry is a recoverable
    // cut before index fsync. It still prevents a second physical operation.
    Ok(Some(receipt.record))
}

pub(super) fn persist(journal: &Path, record: &NativeRunRecord) -> Result<String, Error> {
    let (receipt_path, index_path) = paths(journal, &record.request.request_id);
    let record_sha256 = record_digest(record)?;
    if let Some(prior) = lookup(journal, &record.request.request_id)? {
        if &prior != record {
            return Err(Error::Conflict);
        }
    } else {
        let parent = receipt_path
            .parent()
            .ok_or(Error::InvalidIdentity("archive path"))?;
        fs::create_dir_all(parent)?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let root = history_root(journal);
            for directory in [root.as_path(), parent.parent().unwrap_or(parent), parent] {
                fs::set_permissions(directory, fs::Permissions::from_mode(0o700))?;
            }
        }
        // Persist each newly created directory link before a later journal
        // retirement can depend on the receipt path surviving a crash.
        let root = history_root(journal);
        for directory in [
            root.parent().unwrap_or_else(|| Path::new(".")),
            root.as_path(),
            parent.parent().unwrap_or(parent),
            parent,
        ] {
            File::open(directory)?.sync_all()?;
        }
        let receipt = Receipt {
            schema_version: 1,
            record: record.clone(),
            record_sha256: record_sha256.clone(),
        };
        let bytes = serde_json::to_vec(&receipt)
            .map_err(|_| Error::CorruptJournal("native archive encode"))?;
        if bytes.len() as u64 > MAX_RECEIPT_BYTES {
            return Err(Error::CapacityExceeded);
        }
        replace_synced(&receipt_path, &bytes)?;
    }
    let entry = Tombstone {
        request_id: record.request.request_id.clone(),
        request_sha256: request_digest(record)?,
        record_sha256: record_sha256.clone(),
    };
    match read_tombstone(&index_path, &entry.request_id)? {
        Some(prior) if prior == entry => {}
        Some(_) => return Err(Error::Conflict),
        None => {
            let mut bytes = serde_json::to_vec(&entry)
                .map_err(|_| Error::CorruptJournal("native archive index encode"))?;
            bytes.push(b'\n');
            let mut prior = Vec::new();
            match File::open(&index_path) {
                Ok(file) => {
                    file.take(MAX_INDEX_BYTES + 1).read_to_end(&mut prior)?;
                }
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
                Err(error) => return Err(error.into()),
            }
            if prior.len().saturating_add(bytes.len()) as u64 > MAX_INDEX_BYTES {
                return Err(Error::CapacityExceeded);
            }
            prior.extend(bytes);
            // Atomic index replacement keeps a crash before/after fsync from
            // leaving an incomplete tombstone append. The receipt is written
            // first and already prevents replay at that intermediate cut.
            replace_synced(&index_path, &prior)?;
        }
    }
    Ok(record_sha256)
}

fn replace_synced(path: &Path, bytes: &[u8]) -> Result<(), Error> {
    let temporary = path.with_extension(format!("{:032x}.tmp", rand::random::<u128>()));
    let result = (|| {
        let mut file = private_options()
            .create_new(true)
            .write(true)
            .open(&temporary)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        fs::rename(&temporary, path)?;
        File::open(
            path.parent()
                .ok_or(Error::InvalidIdentity("archive parent"))?,
        )?
        .sync_all()?;
        Ok::<(), Error>(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(temporary);
    }
    result
}

pub(super) fn private_options() -> OpenOptions {
    let mut options = OpenOptions::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    options
}
