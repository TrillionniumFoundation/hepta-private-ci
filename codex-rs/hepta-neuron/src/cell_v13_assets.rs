//! Host-opened immutable V13 assets. Buffered bytes, not mutable pathnames, are
//! transported to the phase process; retained descriptors support owner alias checks.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::fs::File;
use std::io::Read;
use std::os::fd::AsRawFd;
use std::os::unix::fs::FileExt;
use std::os::unix::fs::MetadataExt;

use codex_hepta_types::Digest32;

use crate::CellGenerationErrorV2;
use crate::cell_joint_process::executable_digest;
use crate::cell_v13_protocol::AssetBytes;
use crate::cell_v13_protocol::MAX_ASSET_BYTES;

pub struct V13GenerationAssetFileV1 {
    pub name: String,
    pub digest: [u8; 32],
    pub file: File,
}

pub struct V13GenerationProcessFilesV1 {
    pub interpreter: File,
    pub worker: File,
    pub assets: Vec<V13GenerationAssetFileV1>,
}

pub(crate) struct PreparedFiles {
    pub(crate) interpreter: File,
    pub(crate) script: String,
    pub(crate) assets: BTreeMap<String, AssetBytes>,
    retained_files: Vec<File>,
}

impl PreparedFiles {
    pub(crate) fn identities(&self) -> Result<Vec<(u64, u64)>, CellGenerationErrorV2> {
        std::iter::once(&self.interpreter)
            .chain(&self.retained_files)
            .map(|file| {
                let metadata = file
                    .metadata()
                    .map_err(|_| CellGenerationErrorV2::Unavailable)?;
                Ok((metadata.dev(), metadata.ino()))
            })
            .collect()
    }
}

const SOURCE_NAMES: [&str; 11] = [
    "bounded_npz.py",
    "closure_common.py",
    "closure_inputs.py",
    "closure_io.py",
    "verify_closure.py",
    "PROVENANCE.json",
    "reference/adapter.py.source",
    "reference/backend.py.source",
    "reference/download_model.py.source",
    "reference/lifecycle.py.source",
    "reference/tasks.py.source",
];

fn limit(name: &str) -> Option<u64> {
    if name
        .strip_prefix("vendor/")
        .is_some_and(|name| SOURCE_NAMES.contains(&name))
    {
        return Some(65_536);
    }
    match name {
        "model.npz" => Some(64 * 1024 * 1024),
        "sources.json" => Some(2 * 1024 * 1024),
        "training.npz" => Some(128 * 1024 * 1024),
        "encoder.json" | "release.json" => Some(131_072),
        "encoder/onnx/model.onnx" => Some(90_405_214),
        "encoder/tokenizer.json" => Some(466_247),
        "encoder/config.json" => Some(612),
        "encoder/sentence_bert_config.json" => Some(53),
        "encoder/modules.json" => Some(349),
        "encoder/1_Pooling/config.json" => Some(190),
        "encoder/tokenizer_config.json" => Some(350),
        "encoder/special_tokens_map.json" => Some(112),
        _ => None,
    }
}

fn readonly(file: &File) -> Result<(), CellGenerationErrorV2> {
    let path = format!("/proc/self/fdinfo/{}", file.as_raw_fd());
    let mut bytes = String::new();
    File::open(path)
        .map_err(|_| CellGenerationErrorV2::Unavailable)?
        .take(8193)
        .read_to_string(&mut bytes)
        .map_err(|_| CellGenerationErrorV2::Unavailable)?;
    let mut flags = bytes
        .lines()
        .filter_map(|line| line.strip_prefix("flags:\t"));
    let value = flags
        .next()
        .and_then(|value| u64::from_str_radix(value.trim(), 8).ok());
    if bytes.len() > 8192 || flags.next().is_some() || value.is_none_or(|flags| flags & 3 != 0) {
        return Err(CellGenerationErrorV2::InvalidBinding);
    }
    if !file
        .metadata()
        .map_err(|_| CellGenerationErrorV2::Unavailable)?
        .is_file()
    {
        return Err(CellGenerationErrorV2::InvalidBinding);
    }
    Ok(())
}

fn read(file: &File, maximum: u64, expected: [u8; 32]) -> Result<Vec<u8>, CellGenerationErrorV2> {
    readonly(file)?;
    let before = file
        .metadata()
        .map_err(|_| CellGenerationErrorV2::Unavailable)?;
    if before.len() == 0 || before.len() > maximum || expected == [0; 32] {
        return Err(CellGenerationErrorV2::Capacity);
    }
    let length = usize::try_from(before.len()).map_err(|_| CellGenerationErrorV2::Capacity)?;
    let mut bytes = vec![0; length];
    file.read_exact_at(&mut bytes, 0)
        .map_err(|_| CellGenerationErrorV2::Unavailable)?;
    let after = file
        .metadata()
        .map_err(|_| CellGenerationErrorV2::Unavailable)?;
    let identity = |meta: &std::fs::Metadata| {
        (
            meta.dev(),
            meta.ino(),
            meta.len(),
            meta.mtime(),
            meta.mtime_nsec(),
            meta.ctime(),
            meta.ctime_nsec(),
        )
    };
    if identity(&before) != identity(&after) || Digest32::of_bytes(&bytes).into_array() != expected
    {
        return Err(CellGenerationErrorV2::InvalidBinding);
    }
    Ok(bytes)
}

pub(crate) fn prepare(
    files: V13GenerationProcessFilesV1,
    interpreter_digest: [u8; 32],
    worker_digest: [u8; 32],
) -> Result<PreparedFiles, CellGenerationErrorV2> {
    readonly(&files.interpreter)?;
    if executable_digest(&files.interpreter)? != interpreter_digest || files.assets.len() != 24 {
        return Err(CellGenerationErrorV2::InvalidBinding);
    }
    let script = String::from_utf8(read(&files.worker, 65_536, worker_digest)?)
        .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
    let mut assets = BTreeMap::new();
    let mut retained_files = vec![files.worker];
    let mut total = 0_usize;
    for asset in files.assets {
        let maximum = limit(&asset.name).ok_or(CellGenerationErrorV2::InvalidBinding)?;
        if assets.contains_key(&asset.name) {
            return Err(CellGenerationErrorV2::Conflict);
        }
        let bytes = read(&asset.file, maximum, asset.digest)?;
        total = total
            .checked_add(bytes.len())
            .ok_or(CellGenerationErrorV2::Capacity)?;
        if total > MAX_ASSET_BYTES {
            return Err(CellGenerationErrorV2::Capacity);
        }
        assets.insert(
            asset.name,
            AssetBytes {
                bytes,
                digest: asset.digest,
            },
        );
        retained_files.push(asset.file);
    }
    let prepared = PreparedFiles {
        interpreter: files.interpreter,
        script,
        assets,
        retained_files,
    };
    let identities = prepared.identities()?;
    if identities.iter().copied().collect::<BTreeSet<_>>().len() != identities.len() {
        return Err(CellGenerationErrorV2::InvalidBinding);
    }
    Ok(prepared)
}
