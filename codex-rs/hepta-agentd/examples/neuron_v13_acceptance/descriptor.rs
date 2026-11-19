use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;

use anyhow::Result;
use anyhow::ensure;
use codex_hepta_neuron::CellEvolutionBindingV2;
use codex_hepta_neuron::V13GenerationAssetFileV1;
use codex_hepta_neuron::V13GenerationProcessFilesV1;
use codex_hepta_neuron::V13LearningClosureV1;
use codex_hepta_neuron::V13TaskInputV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde_json::Value;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Asset {
    pub path: PathBuf,
    #[serde(deserialize_with = "hex_digest")]
    pub sha256: Digest32,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct NamedAsset {
    name: String,
    path: PathBuf,
    #[serde(deserialize_with = "hex_digest")]
    sha256: Digest32,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Descriptor {
    schema: String,
    authority: String,
    pub interpreter_argv0: PathBuf,
    pub interpreter: Asset,
    pub worker: Asset,
    assets: Vec<NamedAsset>,
    pub closure: V13LearningClosureV1,
    pub source_digest: [u8; 32],
    pub evolution: CellEvolutionBindingV2,
    historical_publication: Asset,
    pub task: V13TaskInputV1,
}

pub(super) struct Input {
    pub descriptor: Descriptor,
    pub digest: Digest32,
    pub files: V13GenerationProcessFilesV1,
    pub retained: [File; 2],
}

fn hex_digest<'de, D: serde::Deserializer<'de>>(value: D) -> Result<Digest32, D::Error> {
    String::deserialize(value)?
        .parse()
        .map_err(serde::de::Error::custom)
}

fn open(path: &Path) -> Result<File> {
    ensure!(
        path.is_absolute() && path.file_name().is_some(),
        "asset requires an absolute file path"
    );
    let parent = path
        .parent()
        .ok_or_else(|| anyhow::anyhow!("asset parent missing"))?;
    ensure!(
        parent.canonicalize()? == parent,
        "asset parent must be canonical"
    );
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(path)?;
    ensure!(
        file.metadata()?.is_file(),
        "asset is not an actual regular file"
    );
    Ok(file)
}

fn read(file: &File, maximum: u64) -> Result<Vec<u8>> {
    let metadata = file.metadata()?;
    ensure!(
        metadata.len() > 0 && metadata.len() <= maximum,
        "input exceeds size bound"
    );
    let mut bytes = Vec::new();
    file.take(maximum + 1).read_to_end(&mut bytes)?;
    ensure!(
        bytes.len() as u64 == metadata.len(),
        "input changed while reading"
    );
    Ok(bytes)
}

pub(super) fn load(path: &Path, expected: Digest32) -> Result<Input> {
    let descriptor_file = open(path)?;
    let raw = read(&descriptor_file, 262_144)?;
    ensure!(
        !expected.is_zero() && Digest32::of_bytes(&raw) == expected,
        "descriptor digest differs"
    );
    let descriptor: Descriptor = serde_json::from_slice(&raw)?;
    ensure!(
        descriptor.schema == "hepta.v13.owner-acceptance.v1"
            && descriptor.authority == "DENY_ALL"
            && descriptor.source_digest != [0; 32]
            && descriptor.assets.len() == 24,
        "unsupported acceptance descriptor"
    );
    descriptor.task.encode()?;
    let publication_file = open(&descriptor.historical_publication.path)?;
    let publication_raw = read(&publication_file, 131_072)?;
    ensure!(
        Digest32::of_bytes(&publication_raw) == descriptor.historical_publication.sha256
            && descriptor.evolution.adoption_receipt
                == descriptor.historical_publication.sha256.into_array(),
        "historical publication reference differs"
    );
    let publication: Value = serde_json::from_slice(&publication_raw)?;
    let release = descriptor
        .assets
        .iter()
        .find(|asset| asset.name == "release.json")
        .ok_or_else(|| anyhow::anyhow!("release asset missing"))?;
    for (name, expected) in [
        (
            "candidate_file_sha256",
            descriptor.closure.checkpoint_digest,
        ),
        ("source_version", descriptor.closure.source_version),
        ("state_sha256", descriptor.closure.state_digest),
        ("candidate_artifact", release.sha256.into_array()),
    ] {
        let observed = publication
            .get(name)
            .and_then(Value::as_str)
            .and_then(|value| value.parse::<Digest32>().ok());
        ensure!(
            observed == Some(Digest32::from_array(expected)),
            "historical {name} differs"
        );
    }
    ensure!(
        publication["publication"]["status"] == "published"
            && publication["publication"]["epoch"].as_u64() == Some(1)
            && publication["active_release"]["artifact"] == publication["candidate_artifact"]
            && descriptor.evolution.source_dependencies == descriptor.closure.source_version,
        "historical publication content does not match closure"
    );
    let files = V13GenerationProcessFilesV1 {
        interpreter: open(&descriptor.interpreter.path)?,
        worker: open(&descriptor.worker.path)?,
        assets: descriptor
            .assets
            .iter()
            .map(|asset| {
                Ok(V13GenerationAssetFileV1 {
                    name: asset.name.clone(),
                    digest: asset.sha256.into_array(),
                    file: open(&asset.path)?,
                })
            })
            .collect::<Result<_>>()?,
    };
    let mut identities = Vec::new();
    for file in [
        &descriptor_file,
        &publication_file,
        &files.interpreter,
        &files.worker,
    ]
    .into_iter()
    .chain(files.assets.iter().map(|asset| &asset.file))
    {
        let metadata = file.metadata()?;
        let id = (metadata.dev(), metadata.ino());
        ensure!(
            !identities.contains(&id),
            "descriptor, publication and actual worker assets alias"
        );
        identities.push(id);
    }
    Ok(Input {
        descriptor,
        digest: expected,
        files,
        retained: [descriptor_file, publication_file],
    })
}
