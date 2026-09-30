use std::fmt;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::ErrorKind;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::ControlRuntimeOwnerErrorV1;
use super::ControlRuntimeOwnerV1;
use crate::TrustedClockV1;

const MAGIC: &[u8; 8] = b"HCPGEN01";
const VERSION: u32 = 1;
const MAX_OWNER_ID_BYTES: usize = 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
struct GenerationFenceRecordV1 {
    owner_id: StableId,
    generation: Generation,
    policy_digest: Digest32,
    external_anchor_digest: Digest32,
}

#[derive(Debug)]
enum GenerationFenceErrorV1 {
    Io(std::io::Error),
    Locked,
    Corrupt,
    OwnerMismatch,
    PolicyMismatch,
    RollbackDetected,
    NonSuccessorGeneration,
    MissingAnchor,
    LengthOverflow,
}

impl fmt::Display for GenerationFenceErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io(error) => write!(formatter, "I/O failed: {error}"),
            other => write!(formatter, "{other:?}"),
        }
    }
}

impl From<std::io::Error> for GenerationFenceErrorV1 {
    fn from(error: std::io::Error) -> Self {
        Self::Io(error)
    }
}

impl<C: TrustedClockV1> ControlRuntimeOwnerV1<C> {
    pub fn open_fenced(
        store_path: impl AsRef<Path>,
        fence_path: impl AsRef<Path>,
        owner_id: StableId,
        generation: Generation,
        policy_epoch: u64,
        policy_digest: Digest32,
        external_anchor_digest: Digest32,
        clock: C,
    ) -> Result<Self, ControlRuntimeOwnerErrorV1> {
        let owner = Self::open(
            store_path,
            owner_id.clone(),
            generation,
            policy_epoch,
            policy_digest,
            clock,
        )?;
        check_and_advance(
            fence_path.as_ref(),
            &owner_id,
            generation,
            policy_digest,
            external_anchor_digest,
        )
        .map_err(|error| {
            ControlRuntimeOwnerErrorV1::Store(format!("generation fence: {error}"))
        })?;
        Ok(owner)
    }
}

fn check_and_advance(
    path: &Path,
    owner_id: &StableId,
    generation: Generation,
    policy_digest: Digest32,
    external_anchor_digest: Digest32,
) -> Result<(), GenerationFenceErrorV1> {
    if policy_digest.is_zero() || external_anchor_digest.is_zero() {
        return Err(GenerationFenceErrorV1::MissingAnchor);
    }
    let parent = path.parent().unwrap_or_else(|| Path::new("."));
    fs::create_dir_all(parent)?;
    let lock_path = lock_path_for(path);
    let lock = match OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&lock_path)
    {
        Ok(lock) => lock,
        Err(error) if error.kind() == ErrorKind::AlreadyExists => {
            return Err(GenerationFenceErrorV1::Locked);
        }
        Err(error) => return Err(error.into()),
    };

    let result = check_and_advance_locked(
        path,
        owner_id,
        generation,
        policy_digest,
        external_anchor_digest,
    );
    drop(lock);
    let _ = fs::remove_file(&lock_path);
    let _ = sync_directory(parent);
    result
}

fn check_and_advance_locked(
    path: &Path,
    owner_id: &StableId,
    generation: Generation,
    policy_digest: Digest32,
    external_anchor_digest: Digest32,
) -> Result<(), GenerationFenceErrorV1> {
    if !path.exists() {
        return atomic_write(
            path,
            &GenerationFenceRecordV1 {
                owner_id: owner_id.clone(),
                generation,
                policy_digest,
                external_anchor_digest,
            },
        );
    }

    let current = read_record(path)?;
    if current.owner_id != *owner_id {
        return Err(GenerationFenceErrorV1::OwnerMismatch);
    }
    if current.generation > generation {
        return Err(GenerationFenceErrorV1::RollbackDetected);
    }
    if current.generation == generation {
        if current.policy_digest != policy_digest
            || current.external_anchor_digest != external_anchor_digest
        {
            return Err(GenerationFenceErrorV1::PolicyMismatch);
        }
        return Ok(());
    }
    if current.generation.next().ok() != Some(generation) {
        return Err(GenerationFenceErrorV1::NonSuccessorGeneration);
    }
    atomic_write(
        path,
        &GenerationFenceRecordV1 {
            owner_id: owner_id.clone(),
            generation,
            policy_digest,
            external_anchor_digest,
        },
    )
}

fn read_record(path: &Path) -> Result<GenerationFenceRecordV1, GenerationFenceErrorV1> {
    let mut bytes = Vec::new();
    File::open(path)?.read_to_end(&mut bytes)?;
    if bytes.len() < 8 + 4 + 4 + 8 + 32 + 32 + 32 || &bytes[..8] != MAGIC {
        return Err(GenerationFenceErrorV1::Corrupt);
    }
    let mut cursor = 8;
    let version = read_u32(&bytes, &mut cursor)?;
    if version != VERSION {
        return Err(GenerationFenceErrorV1::Corrupt);
    }
    let owner_len = usize::try_from(read_u32(&bytes, &mut cursor)?)
        .map_err(|_| GenerationFenceErrorV1::LengthOverflow)?;
    if owner_len == 0 || owner_len > MAX_OWNER_ID_BYTES {
        return Err(GenerationFenceErrorV1::Corrupt);
    }
    let owner_end = cursor
        .checked_add(owner_len)
        .ok_or(GenerationFenceErrorV1::LengthOverflow)?;
    let owner_raw = bytes
        .get(cursor..owner_end)
        .ok_or(GenerationFenceErrorV1::Corrupt)?;
    let owner = std::str::from_utf8(owner_raw).map_err(|_| GenerationFenceErrorV1::Corrupt)?;
    let owner_id = StableId::new(owner).map_err(|_| GenerationFenceErrorV1::Corrupt)?;
    cursor = owner_end;
    let generation = Generation::new(read_u64(&bytes, &mut cursor)?)
        .map_err(|_| GenerationFenceErrorV1::Corrupt)?;
    let policy_digest = read_digest(&bytes, &mut cursor)?;
    let external_anchor_digest = read_digest(&bytes, &mut cursor)?;
    let stored_digest = read_digest(&bytes, &mut cursor)?;
    if cursor != bytes.len() {
        return Err(GenerationFenceErrorV1::Corrupt);
    }
    let record = GenerationFenceRecordV1 {
        owner_id,
        generation,
        policy_digest,
        external_anchor_digest,
    };
    if record_digest(&record) != stored_digest {
        return Err(GenerationFenceErrorV1::Corrupt);
    }
    Ok(record)
}

fn atomic_write(
    path: &Path,
    record: &GenerationFenceRecordV1,
) -> Result<(), GenerationFenceErrorV1> {
    let parent = path.parent().unwrap_or_else(|| Path::new("."));
    let bytes = encode_record(record)?;
    let file_name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("generation-fence");
    let temporary = parent.join(format!(".{file_name}.tmp-{}", std::process::id()));
    let mut file = OpenOptions::new()
        .create(true)
        .truncate(true)
        .write(true)
        .open(&temporary)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    fs::rename(&temporary, path)?;
    sync_directory(parent)?;
    Ok(())
}

fn encode_record(record: &GenerationFenceRecordV1) -> Result<Vec<u8>, GenerationFenceErrorV1> {
    let owner = record.owner_id.as_str().as_bytes();
    if owner.is_empty() || owner.len() > MAX_OWNER_ID_BYTES {
        return Err(GenerationFenceErrorV1::LengthOverflow);
    }
    let owner_len = u32::try_from(owner.len())
        .map_err(|_| GenerationFenceErrorV1::LengthOverflow)?;
    let mut bytes = MAGIC.to_vec();
    bytes.extend_from_slice(&VERSION.to_be_bytes());
    bytes.extend_from_slice(&owner_len.to_be_bytes());
    bytes.extend_from_slice(owner);
    bytes.extend_from_slice(&record.generation.get().to_be_bytes());
    bytes.extend_from_slice(record.policy_digest.as_array());
    bytes.extend_from_slice(record.external_anchor_digest.as_array());
    bytes.extend_from_slice(record_digest(record).as_array());
    Ok(bytes)
}

fn record_digest(record: &GenerationFenceRecordV1) -> Digest32 {
    let mut bytes = b"hepta.control.generation-fence.v1\0".to_vec();
    bytes.extend_from_slice(&(record.owner_id.as_str().len() as u64).to_be_bytes());
    bytes.extend_from_slice(record.owner_id.as_str().as_bytes());
    bytes.extend_from_slice(&record.generation.get().to_be_bytes());
    bytes.extend_from_slice(record.policy_digest.as_array());
    bytes.extend_from_slice(record.external_anchor_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn read_u32(bytes: &[u8], cursor: &mut usize) -> Result<u32, GenerationFenceErrorV1> {
    let end = cursor
        .checked_add(4)
        .ok_or(GenerationFenceErrorV1::LengthOverflow)?;
    let value = u32::from_be_bytes(
        bytes
            .get(*cursor..end)
            .ok_or(GenerationFenceErrorV1::Corrupt)?
            .try_into()
            .map_err(|_| GenerationFenceErrorV1::Corrupt)?,
    );
    *cursor = end;
    Ok(value)
}

fn read_u64(bytes: &[u8], cursor: &mut usize) -> Result<u64, GenerationFenceErrorV1> {
    let end = cursor
        .checked_add(8)
        .ok_or(GenerationFenceErrorV1::LengthOverflow)?;
    let value = u64::from_be_bytes(
        bytes
            .get(*cursor..end)
            .ok_or(GenerationFenceErrorV1::Corrupt)?
            .try_into()
            .map_err(|_| GenerationFenceErrorV1::Corrupt)?,
    );
    *cursor = end;
    Ok(value)
}

fn read_digest(
    bytes: &[u8],
    cursor: &mut usize,
) -> Result<Digest32, GenerationFenceErrorV1> {
    let end = cursor
        .checked_add(32)
        .ok_or(GenerationFenceErrorV1::LengthOverflow)?;
    let raw: [u8; 32] = bytes
        .get(*cursor..end)
        .ok_or(GenerationFenceErrorV1::Corrupt)?
        .try_into()
        .map_err(|_| GenerationFenceErrorV1::Corrupt)?;
    *cursor = end;
    Ok(Digest32::from_array(raw))
}

fn lock_path_for(path: &Path) -> PathBuf {
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("generation-fence");
    path.with_file_name(format!("{name}.writer.lock"))
}

fn sync_directory(path: &Path) -> Result<(), GenerationFenceErrorV1> {
    File::open(path)?.sync_all()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ManualTrustedClockV1;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    #[test]
    fn fence_survives_restart_and_rejects_rollback() {
        let directory = tempfile::tempdir().expect("tempdir");
        let store = directory.path().join("planner.store");
        let fence = directory.path().join("generation.fence");
        let owner_id = id("owner");
        let generation_one = Generation::new(1).expect("generation");
        let generation_two = Generation::new(2).expect("generation");
        let policy_one = digest("policy-one");
        let policy_two = digest("policy-two");
        let anchor_one = digest("anchor-one");
        let anchor_two = digest("anchor-two");

        drop(
            ControlRuntimeOwnerV1::open_fenced(
                &store,
                &fence,
                owner_id.clone(),
                generation_one,
                1,
                policy_one,
                anchor_one,
                ManualTrustedClockV1::new(10),
            )
            .expect("initial owner"),
        );
        let old_bytes = fs::read(&fence).expect("old fence");
        drop(
            ControlRuntimeOwnerV1::open_fenced(
                &store,
                &fence,
                owner_id.clone(),
                generation_two,
                2,
                policy_two,
                anchor_two,
                ManualTrustedClockV1::new(20),
            )
            .expect("advanced owner"),
        );
        fs::write(&fence, old_bytes).expect("restore stale fence");
        assert!(matches!(
            ControlRuntimeOwnerV1::open_fenced(
                &store,
                &fence,
                owner_id,
                generation_two,
                2,
                policy_two,
                anchor_two,
                ManualTrustedClockV1::new(30),
            ),
            Err(ControlRuntimeOwnerErrorV1::Store(message))
                if message.contains("NonSuccessorGeneration")
                    || message.contains("PolicyMismatch")
        ));
    }
}
