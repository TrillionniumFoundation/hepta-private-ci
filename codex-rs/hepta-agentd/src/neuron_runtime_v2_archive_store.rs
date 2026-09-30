//! Cold generation truth is sealed before the control topology releases its
//! executable owner. Startup checks the small frontier and newest sealed blob;
//! older cold generations are never opened as executable owners.
use super::*;
use codex_hepta_agent_components::neuron::MAX_NEURON_GENERATION_ARCHIVE_BYTES_V1;
use codex_hepta_agent_components::neuron::NeuronGenerationArchiveV1;

pub(super) const DEFAULT_MAX_TOTAL_BYTES: u64 = 64 * 1024 * 1024 * 1024;
const RECEIPT_DOMAIN: &[u8] = b"hepta.agentd.generation-archive-receipt.v1";

#[derive(Clone, Default, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Frontier {
    generation: u64,
    count: u64,
    total_bytes: u64,
    receipt_digest: String,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Receipt {
    version: u32,
    generation: u64,
    archive_digest: String,
    archive_bytes: u64,
    previous: Frontier,
}

pub(super) struct GenerationArchiveStore {
    directory: PathBuf,
    frontier: Frontier,
    maximum_total_bytes: u64,
    _lock: std::fs::File,
}
impl GenerationArchiveStore {
    pub(super) fn open(
        control: &Path,
        maximum_total_bytes: u64,
    ) -> Result<Self, AgentdNeuronControlErrorV2> {
        if maximum_total_bytes == 0 {
            return Err(AgentdNeuronControlErrorV2::ControllerPoisoned);
        }
        let parent = control
            .parent()
            .ok_or(AgentdNeuronControlErrorV2::ControllerPoisoned)?;
        generation_state_parent_metadata(control).map_err(poison_control_state)?;
        let directory = parent.join("neuron-generation-archives");
        if !directory.exists() {
            let mut builder = std::fs::DirBuilder::new();
            #[cfg(unix)]
            {
                use std::os::unix::fs::DirBuilderExt;
                builder.mode(0o700);
            }
            builder.create(&directory).map_err(archive_io)?;
            sync_generation_state_directory(parent).map_err(archive_io)?;
        }
        let metadata = std::fs::symlink_metadata(&directory).map_err(archive_io)?;
        if !metadata.is_dir() || metadata.file_type().is_symlink() {
            return Err(AgentdNeuronControlErrorV2::ControllerPoisoned);
        }
        generation_state_parent_metadata(&directory.join("frontier.json"))
            .map_err(poison_control_state)?;
        let mut options = OpenOptions::new();
        options.read(true).write(true).create(true).truncate(false);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let lock = options
            .open(directory.join("owner.lock"))
            .map_err(archive_io)?;
        let metadata = lock.metadata().map_err(archive_io)?;
        let named = std::fs::symlink_metadata(directory.join("owner.lock")).map_err(archive_io)?;
        if named.file_type().is_symlink() {
            return Err(AgentdNeuronControlErrorV2::ControllerPoisoned);
        }
        validate_same_generation_state_identity(&metadata, &named).map_err(poison_control_state)?;
        if !metadata.is_file() {
            return Err(AgentdNeuronControlErrorV2::ControllerPoisoned);
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            if metadata.nlink() != 1 || metadata.mode() & 0o077 != 0 {
                return Err(AgentdNeuronControlErrorV2::ControllerPoisoned);
            }
        }
        lock.try_lock()
            .map_err(|_| AgentdNeuronControlErrorV2::ControllerBusy)?;
        let path = directory.join("frontier.json");
        let frontier = if path.exists() {
            serde_json::from_slice(&read_private(&path, 4096)?)
                .map_err(|_| AgentdNeuronControlErrorV2::ControllerPoisoned)?
        } else {
            Frontier::default()
        };
        let store = Self {
            directory,
            frontier,
            maximum_total_bytes,
            _lock: lock,
        };
        if store.frontier.generation != 0 {
            let receipt = store.read_receipt(store.frontier.generation)?;
            let receipt_bytes = serde_json::to_vec(&receipt)
                .map_err(|_| AgentdNeuronControlErrorV2::ControllerPoisoned)?;
            if receipt.previous.count.checked_add(1) != Some(store.frontier.count)
                || receipt
                    .previous
                    .total_bytes
                    .checked_add(receipt.archive_bytes)
                    .and_then(|total| total.checked_add(receipt_bytes.len() as u64))
                    != Some(store.frontier.total_bytes)
            {
                return Err(AgentdNeuronControlErrorV2::ControllerPoisoned);
            }
            // The newest frontier must point to a real intact immutable blob.
            store.read_archive(&receipt)?;
        } else if store.frontier.count != 0
            || store.frontier.total_bytes != 0
            || !store.frontier.receipt_digest.is_empty()
        {
            return Err(AgentdNeuronControlErrorV2::ControllerPoisoned);
        }
        Ok(store)
    }

    pub(super) fn contains(&self, generation: u64) -> Result<bool, AgentdNeuronControlErrorV2> {
        if generation == 0 || generation > self.frontier.generation {
            return Ok(false);
        }
        let path = self.directory.join(format!("{generation}.receipt.json"));
        if !path.exists() {
            return Ok(false);
        }
        self.read_receipt(generation)?;
        Ok(true)
    }
    pub(super) fn commit(
        &mut self,
        archive: &NeuronGenerationArchiveV1,
    ) -> Result<(), AgentdNeuronControlErrorV2> {
        let generation = archive.generation();
        if self.contains(generation)? {
            let existing = self.read_archive(&self.read_receipt(generation)?)?;
            return if existing.digest() == archive.digest() {
                Ok(())
            } else {
                Err(AgentdNeuronControlErrorV2::GenerationConflict)
            };
        }
        if generation <= self.frontier.generation {
            return Err(AgentdNeuronControlErrorV2::GenerationConflict);
        }
        let receipt = Receipt {
            version: 1,
            generation,
            archive_digest: archive.digest().to_string(),
            archive_bytes: archive.bytes().len() as u64,
            previous: self.frontier.clone(),
        };
        let encoded = serde_json::to_vec(&receipt)
            .map_err(|_| AgentdNeuronControlErrorV2::ControllerPoisoned)?;
        let total_bytes = self
            .frontier
            .total_bytes
            .checked_add(archive.bytes().len() as u64)
            .and_then(|bytes| bytes.checked_add(encoded.len() as u64))
            .filter(|bytes| *bytes <= self.maximum_total_bytes)
            .ok_or(AgentdNeuronControlErrorV2::StoragePressure)?;
        publish(
            &self.directory,
            &format!("{generation}.archive"),
            archive.bytes(),
            Publication::Immutable,
        )?;
        publish(
            &self.directory,
            &format!("{generation}.receipt.json"),
            &encoded,
            Publication::Immutable,
        )?;
        let frontier = Frontier {
            generation,
            count: self
                .frontier
                .count
                .checked_add(1)
                .ok_or(AgentdNeuronControlErrorV2::ControllerPoisoned)?,
            total_bytes,
            receipt_digest: Digest32::of_parts(&[RECEIPT_DOMAIN, &encoded]).to_string(),
        };
        publish(
            &self.directory,
            "frontier.json",
            &serde_json::to_vec(&frontier)
                .map_err(|_| AgentdNeuronControlErrorV2::ControllerPoisoned)?,
            Publication::MutableFrontier,
        )?;
        self.frontier = frontier;
        Ok(())
    }
    pub(super) fn query(
        &self,
        generation: u64,
        tick_id: &StableId,
        digest: Digest32,
    ) -> Result<NeuronOperationStatusV2, AgentdNeuronControlErrorV2> {
        if !self.contains(generation)? {
            return Err(AgentdNeuronControlErrorV2::UnknownGeneration);
        }
        self.read_archive(&self.read_receipt(generation)?)?
            .query_operation(tick_id, digest)
            .map_err(AgentdNeuronControlErrorV2::Runtime)
    }
    fn read_receipt(&self, generation: u64) -> Result<Receipt, AgentdNeuronControlErrorV2> {
        let bytes = read_private(
            &self.directory.join(format!("{generation}.receipt.json")),
            4096,
        )?;
        let receipt: Receipt = serde_json::from_slice(&bytes)
            .map_err(|_| AgentdNeuronControlErrorV2::ControllerPoisoned)?;
        if receipt.version != 1
            || receipt.generation != generation
            || receipt.archive_bytes == 0
            || receipt.archive_bytes > MAX_NEURON_GENERATION_ARCHIVE_BYTES_V1 as u64
            || receipt.previous.generation >= generation
            || generation == self.frontier.generation
                && self.frontier.receipt_digest
                    != Digest32::of_parts(&[RECEIPT_DOMAIN, &bytes]).to_string()
        {
            return Err(AgentdNeuronControlErrorV2::ControllerPoisoned);
        }
        Ok(receipt)
    }
    fn read_archive(
        &self,
        receipt: &Receipt,
    ) -> Result<NeuronGenerationArchiveV1, AgentdNeuronControlErrorV2> {
        let bytes = read_private(
            &self
                .directory
                .join(format!("{}.archive", receipt.generation)),
            receipt.archive_bytes,
        )?;
        let digest = receipt
            .archive_digest
            .parse::<Digest32>()
            .map_err(|_| AgentdNeuronControlErrorV2::ControllerPoisoned)?;
        let archive = NeuronGenerationArchiveV1::from_bytes(bytes, digest)
            .map_err(AgentdNeuronControlErrorV2::Runtime)?;
        if archive.generation() != receipt.generation {
            return Err(AgentdNeuronControlErrorV2::GenerationConflict);
        }
        Ok(archive)
    }
}
fn archive_io(error: io::Error) -> AgentdNeuronControlErrorV2 {
    poison_control_state(error.into())
}
fn read_private(path: &Path, maximum: u64) -> Result<Vec<u8>, AgentdNeuronControlErrorV2> {
    generation_state_parent_metadata(path).map_err(poison_control_state)?;
    let before = std::fs::symlink_metadata(path).map_err(archive_io)?;
    if before.file_type().is_symlink()
        || !before.is_file()
        || before.len() == 0
        || before.len() > maximum
    {
        return Err(AgentdNeuronControlErrorV2::ControllerPoisoned);
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if before.nlink() != 1 || before.mode() & 0o077 != 0 {
            return Err(AgentdNeuronControlErrorV2::ControllerPoisoned);
        }
    }
    let mut options = OpenOptions::new();
    options.read(true);
    let file = options.open(path).map_err(archive_io)?;
    validate_same_generation_state_identity(&before, &file.metadata().map_err(archive_io)?)
        .map_err(poison_control_state)?;
    let mut bytes = Vec::new();
    file.take(maximum + 1)
        .read_to_end(&mut bytes)
        .map_err(archive_io)?;
    if bytes.len() as u64 != before.len() {
        return Err(AgentdNeuronControlErrorV2::ControllerPoisoned);
    }
    Ok(bytes)
}
enum Publication {
    Immutable,
    MutableFrontier,
}
fn publish(
    directory: &Path,
    filename: &str,
    bytes: &[u8],
    publication: Publication,
) -> Result<(), AgentdNeuronControlErrorV2> {
    let destination = directory.join(filename);
    if matches!(publication, Publication::Immutable) && destination.exists() {
        if read_private(&destination, bytes.len() as u64)? != bytes {
            return Err(AgentdNeuronControlErrorV2::GenerationConflict);
        }
        // Recover an exact pre-frontier publication without overwriting bytes.
        std::fs::File::open(&destination)
            .map_err(archive_io)?
            .sync_all()
            .map_err(archive_io)?;
        return sync_generation_state_directory(directory).map_err(archive_io);
    }
    let temporary = directory.join(format!("{filename}.pending"));
    let mut options = OpenOptions::new();
    if let Ok(stale) = std::fs::symlink_metadata(&temporary) {
        if stale.file_type().is_symlink() || !stale.is_file() {
            return Err(AgentdNeuronControlErrorV2::ControllerPoisoned);
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            if stale.nlink() != 1 || stale.mode() & 0o077 != 0 {
                return Err(AgentdNeuronControlErrorV2::ControllerPoisoned);
            }
        }
        // This exact uncommitted slot is replaced only under the archive-owner
        // lock. No committed archive or receipt is removed.
        std::fs::remove_file(&temporary).map_err(archive_io)?;
    }
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(&temporary).map_err(archive_io)?;
    file.write_all(bytes).map_err(archive_io)?;
    file.sync_all().map_err(archive_io)?;
    drop(file);
    match publication {
        Publication::MutableFrontier => {
            std::fs::rename(&temporary, &destination).map_err(archive_io)?
        }
        Publication::Immutable => {
            std::fs::hard_link(&temporary, &destination).map_err(archive_io)?;
            std::fs::remove_file(&temporary).map_err(archive_io)?;
        }
    }
    sync_generation_state_directory(directory).map_err(archive_io)?;
    if read_private(&destination, bytes.len() as u64)? != bytes {
        return Err(AgentdNeuronControlErrorV2::ControllerPoisoned);
    }
    Ok(())
}
