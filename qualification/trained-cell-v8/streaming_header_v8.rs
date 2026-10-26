//! Bounded metadata and complete stream framing. Large arrays are never read
//! through the historical whole-file JSON/payload reader.
use crate::ensure;
use crate::report;
use crate::Result;
use codex_hepta_neuron::TrainedCellBundleV5;
use codex_hepta_types::Digest32;
use serde_json::Value;
use sha2::Digest;
use sha2::Sha256;
use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::fs::File;
use std::fs::{self};
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::path::Path;
use std::path::PathBuf;

pub const CHUNK_ROWS: usize = 1024;
const MAX_STREAM_BYTES: u64 = 1024 * 1024 * 1024;
pub struct Inputs {
    pub manifest: Value,
    pub header: Value,
    pub header_digest: Digest32,
    pub payloads: [Vec<u8>; 2],
    pub(crate) root: PathBuf,
}
pub(crate) fn open(path: &Path, length: u64) -> Result<File> {
    let meta = fs::symlink_metadata(path)?;
    ensure(
        meta.is_file()
            && !meta.file_type().is_symlink()
            && length > 0
            && length <= MAX_STREAM_BYTES
            && meta.len() == length,
        "bounded exact regular stream required",
    )?;
    let file = File::open(path)?;
    ensure(
        file.metadata()?.len() == length,
        "stream length changed while opening",
    )?;
    Ok(file)
}
pub(crate) fn hash_range(file: &mut File, offset: u64, length: u64) -> Result<Digest32> {
    file.seek(SeekFrom::Start(offset))?;
    let mut remaining = length;
    let mut hash = Sha256::new();
    let mut buffer = [0_u8; 65536];
    while remaining > 0 {
        let n = remaining.min(buffer.len() as u64) as usize;
        file.read_exact(&mut buffer[..n])?;
        hash.update(&buffer[..n]);
        remaining -= n as u64;
    }
    Ok(Digest32::from_array(hash.finalize().into()))
}
pub(crate) fn count(value: &Value, field: &str) -> Result<u64> {
    value[field]
        .as_u64()
        .ok_or_else(|| format!("missing integer {field}").into())
}

impl Inputs {
    pub fn load(root: &Path) -> Result<Self> {
        let manifest_bytes = report::read(&root.join("manifest.json"))?;
        let header_bytes = report::read(&root.join("parity-header.json"))?;
        ensure(
            manifest_bytes.len() <= 1_048_576 && header_bytes.len() <= 1_048_576,
            "bounded stream headers required",
        )?;
        let manifest: Value = serde_json::from_slice(&manifest_bytes)?;
        let header: Value = serde_json::from_slice(&header_bytes)?;
        let header_digest = Digest32::of_bytes(&header_bytes);
        ensure(
            manifest["schema"] == "hepta.trained-cell-stream-parity.v8"
                && header["schema"] == "hepta.trained-cell-stream-header.v8"
                && report::hash(&manifest, "parity_header_sha256")? == header_digest
                && header["protocol_sha256"] == manifest["protocol_sha256"]
                && header["scope"] == manifest["scope"]
                && header["format"] == "float64-big-endian"
                && header["input_width"] == 384
                && header["reference_width"] == 8
                && header["chunk_rows"] == CHUNK_ROWS
                && header["authority"] == "DENY_ALL"
                && header["production_authority"] == false
                && header["scientific_acceptance"] == false
                && header["labels_in_stream"] == false
                && report::number(&header, "absolute_tolerance")? == 1e-12
                && header["output_contract"] == "logits4-probabilities4-all-class-nll-argmax-first"
                && report::hash(&header, "compatibility_sha256")?
                    == codex_hepta_neuron::trained_cell_compatibility_digest_v5(),
            "stream profile or numerical contract differs",
        )?;
        let tasks = report::array(&header, "tasks")?;
        ensure(tasks.len() == 2, "two complete task streams required")?;
        let mut task_map = BTreeMap::new();
        let mut offset = 0;
        for task in tasks {
            let name = report::string(task, "task")?;
            let rows = count(task, "rows")?;
            ensure(
                report::TASKS.contains(&name)
                    && task_map.insert(name, task).is_none()
                    && (1..=65536).contains(&rows)
                    && count(task, "offset_bytes")? == offset,
                "stream task family, row bound or framing differs",
            )?;
            report::hash(task, "sha256")?;
            offset += rows * 384 * 8;
        }
        ensure(
            count(&header, "vectors_bytes")? == offset,
            "complete raw stream length differs",
        )?;
        let mut vectors = open(&root.join("vectors.bin"), offset)?;
        ensure(
            hash_range(&mut vectors, 0, offset)? == report::hash(&header, "vectors_sha256")?,
            "complete raw stream digest differs",
        )?;
        for task in tasks {
            ensure(
                hash_range(
                    &mut vectors,
                    count(task, "offset_bytes")?,
                    count(task, "rows")? * 384 * 8,
                )? == report::hash(task, "sha256")?,
                "task stream digest differs",
            )?;
        }
        let payloads = [
            report::read(&root.join("predecessor.bin"))?,
            report::read(&root.join("candidate.bin"))?,
        ];
        let versions = report::array(&header, "versions")?;
        ensure(versions.len() == 2, "both serving versions required")?;
        let family: BTreeSet<_> = report::TASKS
            .iter()
            .flat_map(|task| {
                report::HEADS.iter().flat_map(move |head| {
                    report::SEEDS
                        .iter()
                        .map(move |seed| format!("{task}-{head}-seed{seed}"))
                })
            })
            .collect();
        offset = 0;
        for (index, version) in versions.iter().enumerate() {
            let bundle = TrainedCellBundleV5::decode(
                &payloads[index],
                report::hash(version, "payload_sha256")?,
            )?;
            ensure(
                bundle.generation().get() == index as u64 + 1
                    && version["generation"] == index as u64 + 1
                    && version["artifact_id"] == bundle.artifact_id().as_str()
                    && bundle.heads().len() == 12,
                "stream serving identity differs",
            )?;
            let heads = report::array(version, "heads")?;
            let cases = report::array(version, "cases")?;
            ensure(
                heads.len() == 12 && cases.len() == 12,
                "complete head and case census required",
            )?;
            let mut seen = BTreeSet::new();
            for head in heads {
                let cell = report::string(head, "cell_id")?;
                let native = bundle
                    .heads()
                    .iter()
                    .find(|h| h.cell_id().as_str() == cell)
                    .ok_or("stream head absent")?;
                let task = report::string(head, "task")?;
                let mode = report::string(head, "head")?;
                let seed = count(head, "seed")?;
                ensure(
                    seen.insert(cell.to_owned())
                        && family.contains(cell)
                        && cell == format!("{task}-{mode}-seed{seed}")
                        && native.training_state_digest()
                            == report::hash(head, "training_state_sha256")?
                        && native.feature_identity_digest()
                            == report::hash(head, "feature_identity_sha256")?,
                    "stream head provenance differs",
                )?;
            }
            ensure(seen == family, "stream head family differs")?;
            seen.clear();
            for case in cases {
                let cell = report::string(case, "cell_id")?;
                let head = heads
                    .iter()
                    .find(|h| h["cell_id"] == cell)
                    .ok_or("case head absent")?;
                let task = task_map
                    .get(report::string(case, "task")?)
                    .ok_or("case task absent")?;
                ensure(
                    seen.insert(cell.to_owned())
                        && case["task"] == head["task"]
                        && case["rows"] == task["rows"]
                        && count(case, "offset_bytes")? == offset,
                    "full-row case coverage or framing differs",
                )?;
                report::hash(case, "sha256")?;
                offset += count(case, "rows")? * 8 * 8;
            }
            ensure(seen == family, "case family differs")?;
        }
        ensure(
            count(&header, "expected_bytes")? == offset,
            "complete reference stream length differs",
        )?;
        let mut expected = open(&root.join("expected.bin"), offset)?;
        ensure(
            hash_range(&mut expected, 0, offset)? == report::hash(&header, "expected_sha256")?,
            "complete reference stream digest differs",
        )?;
        // Each consumed case is checked again during inference. These hashes also
        // prevent a post-preflight file change from silently changing references.
        for version in versions {
            for case in report::array(version, "cases")? {
                ensure(
                    hash_range(
                        &mut expected,
                        count(case, "offset_bytes")?,
                        count(case, "rows")? * 8 * 8,
                    )? == report::hash(case, "sha256")?,
                    "reference case digest differs",
                )?;
            }
        }
        Ok(Self {
            manifest,
            header,
            header_digest,
            payloads,
            root: root.to_path_buf(),
        })
    }
}
