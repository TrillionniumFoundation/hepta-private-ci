//! Root's fixed successor locations and physical identities. This is custody
//! data for an explicit later registration, never a completed task or grant.

use super::super::data::Mode;
use super::material::MaterialData;
use super::material::RetainedMaterial;
use super::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

/// All eight files are supplied by the private Root deployment before its
/// sealed offer. The daemon cannot choose an additional journal or ingress.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct RootSuccessorTaskFilesDataV1 {
    pub(crate) source_configuration: MaterialData,
    pub(crate) target_configuration: MaterialData,
    pub(crate) signed_ingress: MaterialData,
    pub(crate) source_journal: MaterialData,
    pub(crate) source_witness: MaterialData,
    pub(crate) cell_journal: MaterialData,
    pub(crate) cell_witness: MaterialData,
    pub(crate) inference_control: MaterialData,
    pub(crate) cell_witness_scope: [u8; 32],
    pub(crate) cell_witness_objective: [u8; 32],
    pub(crate) cell_witness_generation: u64,
    pub(crate) cell_witness_records: usize,
    pub(crate) maximum_cell_records: usize,
    pub(crate) inference_capacity: usize,
    pub(crate) worker_generation: u64,
}

impl RootSuccessorTaskFilesDataV1 {
    pub(crate) fn require_bounds(&self) -> io::Result<()> {
        if Digest32::from_array(self.cell_witness_scope).is_zero()
            || Digest32::from_array(self.cell_witness_objective).is_zero()
            || !(3..=4096).contains(&self.cell_witness_records)
            || !(3..=16).contains(&self.maximum_cell_records)
            || !(1..=64).contains(&self.inference_capacity)
            || self.worker_generation == 0
        {
            return Err(io::Error::other(
                "original bounded successor files required",
            ));
        }
        Generation::new(self.cell_witness_generation).map_err(io::Error::other)?;
        let files = self.files();
        for (index, file) in files.iter().enumerate() {
            super::super::files::require_absolute(&file.path)?;
            if file.device == 0 || file.inode == 0 || file.mode != 0o100600 {
                return Err(io::Error::other(
                    "original successor file identity required",
                ));
            }
            for previous in &files[..index] {
                if file.path == previous.path
                    || (file.device, file.inode) == (previous.device, previous.inode)
                {
                    return Err(io::Error::other("successor files must not alias"));
                }
            }
        }
        Ok(())
    }

    fn files(&self) -> [&MaterialData; 8] {
        [
            &self.source_configuration,
            &self.target_configuration,
            &self.signed_ingress,
            &self.source_journal,
            &self.source_witness,
            &self.cell_journal,
            &self.cell_witness,
            &self.inference_control,
        ]
    }
}

/// Only the Root0600 deployment loader constructs this holder. All descriptions
/// are O_RDONLY, retained before the daemon receives the original sealed route.
pub(crate) struct RootOriginalSuccessorFilesV1 {
    data: RootSuccessorTaskFilesDataV1,
    // Cold execution files are opened only inside the publication refusal arm.
    // Their expected identities still come from the same fixed Root metadata.
    files: Option<[RetainedMaterial; 8]>,
}

impl RootOriginalSuccessorFilesV1 {
    pub(super) fn open_original(
        data: RootSuccessorTaskFilesDataV1,
        uid: u32,
        gid: u32,
        mode: Mode,
    ) -> io::Result<Arc<Self>> {
        original_root()?;
        data.require_bounds()?;
        let files =
            match mode {
                Mode::Reserve => {
                    let mut files = Vec::with_capacity(8);
                    for file in data.files() {
                        files.push(RetainedMaterial::open_original(file.clone(), uid, gid)?);
                    }
                    Some(files.try_into().map_err(|_| {
                        io::Error::other("complete original successor files required")
                    })?)
                }
                Mode::Recover => None,
            };
        let held = Arc::new(Self { data, files });
        held.require_original()?;
        Ok(held)
    }

    pub(super) fn original_data(&self) -> io::Result<RootSuccessorTaskFilesDataV1> {
        self.require_original()?;
        Ok(self.data.clone())
    }

    pub(super) fn require_distinct(&self, other: &OriginalFile) -> io::Result<()> {
        use std::os::unix::fs::MetadataExt;
        let metadata = other.original_descriptor()?.metadata()?;
        if self
            .data
            .files()
            .iter()
            .any(|file| (file.device, file.inode) == (metadata.dev(), metadata.ino()))
        {
            return Err(io::Error::other("successor aliases publication owner"));
        }
        self.require_original()
    }

    pub(super) fn require_distinct_material(&self, other: &RetainedMaterial) -> io::Result<()> {
        let other = other.original_data()?;
        if self.data.files().iter().any(|file| {
            file.path == other.path || (file.device, file.inode) == (other.device, other.inode)
        }) {
            return Err(io::Error::other("successor aliases publication material"));
        }
        self.require_original()
    }

    pub(crate) fn require_original(&self) -> io::Result<()> {
        original_root()?;
        self.data.require_bounds()?;
        if let Some(files) = &self.files {
            for file in files {
                file.require_original()?;
            }
        }
        Ok(())
    }
}
