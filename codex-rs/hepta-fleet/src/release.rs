use std::collections::BTreeSet;
use std::fmt;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::ErrorKind;
use std::io::Read;
use std::io::Write;
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;
use std::str::FromStr;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::AgentId;
use serde::Deserialize;
use serde::Deserializer;
use serde::Serialize;
use serde::Serializer;
use serde::de::Error as _;
use sha2::Digest;
use sha2::Sha256;

use crate::FleetRegistry;
use crate::FleetRegistryError;

pub const RELEASE_METADATA_SCHEMA_VERSION: u32 = 2;
pub const AGENT_RELEASE_STATE_SCHEMA_VERSION: u32 = 1;
const RELEASE_MANIFEST_FILE: &str = "release.json";
const AGENTD_RELEASE_PROGRAM: &str = "bin/hepta-agentd";
const MATRIXD_RELEASE_PROGRAM: &str = "bin/hepta-matrixd";
const RELEASE_ALLOW_PREFIX: &str = "allow-";
const RELEASE_ALLOW_SUFFIX: &str = ".json";
const RELEASE_STATE_PREFIX: &str = "release-state-";
const RELEASE_STATE_SUFFIX: &str = ".json";
const MAX_RELEASE_MANIFEST_BYTES: u64 = 32 * 1024;
const MAX_RELEASE_ARGUMENTS: usize = 128;
const MAX_RELEASE_ARGUMENT_BYTES: usize = 65_536;
const MAX_ALLOWED_RELEASES: usize = 256;
static RELEASE_SEQUENCE: AtomicU64 = AtomicU64::new(1);

/// Opaque identity of one administrator-installed immutable agentd release.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct ReleaseId(String);

impl ReleaseId {
    pub fn parse(value: impl Into<String>) -> Result<Self, FleetRegistryError> {
        let value = value.into();
        if value.is_empty()
            || value.len() > 128
            || !value.is_ascii()
            || !value
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
        {
            return Err(FleetRegistryError::Invalid(
                "release id must be 1..=128 ASCII letters, digits, '.', '_' or '-'".to_string(),
            ));
        }
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for ReleaseId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.as_str())
    }
}

impl FromStr for ReleaseId {
    type Err = FleetRegistryError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Self::parse(value)
    }
}

impl Serialize for ReleaseId {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_str(self.as_str())
    }
}

impl<'de> Deserialize<'de> for ReleaseId {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        Self::parse(value).map_err(D::Error::custom)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ReleaseProgramMetadata {
    pub program_relative_path: PathBuf,
    pub program_sha256: String,
    pub program_size_bytes: u64,
    pub args: Vec<String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RegisteredProgram {
    pub program: PathBuf,
    pub args: Vec<String>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ReleaseMetadata {
    pub schema_version: u32,
    pub release_id: ReleaseId,
    pub agentd: ReleaseProgramMetadata,
    pub matrixd: Option<ReleaseProgramMetadata>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct LegacyReleaseMetadataV1 {
    schema_version: u32,
    release_id: ReleaseId,
    program_relative_path: PathBuf,
    program_sha256: String,
    program_size_bytes: u64,
    args: Vec<String>,
}

#[derive(Debug, Deserialize)]
#[serde(untagged)]
enum CatalogReleaseMetadata {
    V2(ReleaseMetadata),
    V1(LegacyReleaseMetadataV1),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RegisteredRelease {
    pub release_id: ReleaseId,
    /// Compatibility view of the required agentd program.
    pub program: PathBuf,
    pub args: Vec<String>,
    /// Optional per-Agent Matrix companion shipped in the exact same
    /// immutable release bundle.
    pub matrixd: Option<RegisteredProgram>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AgentReleaseState {
    pub schema_version: u32,
    pub agent_id: AgentId,
    pub generation: u64,
    pub current: Option<ReleaseId>,
    pub previous: Option<ReleaseId>,
}

impl AgentReleaseState {
    pub(crate) fn initial(agent_id: AgentId) -> Self {
        Self {
            schema_version: AGENT_RELEASE_STATE_SCHEMA_VERSION,
            agent_id,
            generation: 0,
            current: None,
            previous: None,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct ReleaseAllowance {
    schema_version: u32,
    agent_id: AgentId,
    release_id: ReleaseId,
    manifest_sha256: String,
}

impl FleetRegistry {
    /// Copies one executable into the fleet-owned immutable release catalog.
    /// This is an administrator/install-time API and is never exposed by the
    /// supervisor control socket.
    pub fn install_release(
        &self,
        release_id: ReleaseId,
        source_program: &Path,
        args: Vec<String>,
    ) -> Result<RegisteredRelease, FleetRegistryError> {
        self.install_release_bundle(
            release_id,
            source_program,
            args,
            /*source_matrixd*/ None,
            /*matrixd_args*/ Vec::new(),
        )
    }

    /// Installs one closed-world release containing the required agentd and,
    /// when configured, its exact matrixd companion. Control clients still
    /// select only the opaque [`ReleaseId`]; executable paths never cross the
    /// supervisor wire.
    pub fn install_release_bundle(
        &self,
        release_id: ReleaseId,
        source_agentd: &Path,
        agentd_args: Vec<String>,
        source_matrixd: Option<&Path>,
        matrixd_args: Vec<String>,
    ) -> Result<RegisteredRelease, FleetRegistryError> {
        validate_arguments(&agentd_args)?;
        validate_arguments(&matrixd_args)?;
        if source_matrixd.is_none() && !matrixd_args.is_empty() {
            return Err(FleetRegistryError::Invalid(
                "matrixd arguments require a matrixd release program".to_string(),
            ));
        }
        let source_agentd = validate_source_program(source_agentd)?;
        let source_matrixd = source_matrixd.map(validate_source_program).transpose()?;
        let final_root = self.layout().releases_root().join(release_id.as_str());
        if final_root.exists() {
            return Err(FleetRegistryError::Invalid(format!(
                "release {release_id} is already installed"
            )));
        }
        let staging = self.layout().releases_root().join(format!(
            ".staging-{release_id}-{}-{}",
            std::process::id(),
            RELEASE_SEQUENCE.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir(&staging)?;
        let result = (|| {
            let bin_root = staging.join("bin");
            std::fs::create_dir(&bin_root)?;
            let agentd_program = staging.join(AGENTD_RELEASE_PROGRAM);
            std::fs::copy(&source_agentd, &agentd_program)?;
            set_mode(&agentd_program, /*mode*/ 0o555)?;
            File::open(&agentd_program)?.sync_all()?;
            let matrixd = source_matrixd
                .as_ref()
                .map(
                    |source| -> Result<ReleaseProgramMetadata, FleetRegistryError> {
                        let matrixd_program = staging.join(MATRIXD_RELEASE_PROGRAM);
                        std::fs::copy(source, &matrixd_program)?;
                        set_mode(&matrixd_program, /*mode*/ 0o555)?;
                        File::open(&matrixd_program)?.sync_all()?;
                        Ok(ReleaseProgramMetadata {
                            program_relative_path: PathBuf::from(MATRIXD_RELEASE_PROGRAM),
                            program_sha256: sha256_file(&matrixd_program)?,
                            program_size_bytes: std::fs::metadata(&matrixd_program)?.len(),
                            args: matrixd_args,
                        })
                    },
                )
                .transpose()?;
            let metadata = ReleaseMetadata {
                schema_version: RELEASE_METADATA_SCHEMA_VERSION,
                release_id: release_id.clone(),
                agentd: ReleaseProgramMetadata {
                    program_relative_path: PathBuf::from(AGENTD_RELEASE_PROGRAM),
                    program_sha256: sha256_file(&agentd_program)?,
                    program_size_bytes: std::fs::metadata(&agentd_program)?.len(),
                    args: agentd_args,
                },
                matrixd,
            };
            let manifest = staging.join(RELEASE_MANIFEST_FILE);
            write_new_json(&manifest, &metadata)?;
            set_mode(&manifest, /*mode*/ 0o444)?;
            set_mode(&bin_root, /*mode*/ 0o555)?;
            sync_directory(&bin_root)?;
            sync_directory(&staging)?;
            set_mode(&staging, /*mode*/ 0o555)?;
            std::fs::rename(&staging, &final_root)?;
            sync_directory(self.layout().releases_root())?;
            Ok(())
        })();
        if let Err(error) = result {
            make_tree_removable(&staging);
            let _ = std::fs::remove_dir_all(&staging);
            return Err(error);
        }
        resolve_catalog_release(self.layout().releases_root(), &release_id)
    }

    /// Allows one registered agent to use an already installed release. The
    /// marker binds the exact release manifest digest, so replacing metadata
    /// cannot silently widen the executable allowlist.
    pub fn allow_release(
        &self,
        agent_id: &AgentId,
        release_id: &ReleaseId,
    ) -> Result<(), FleetRegistryError> {
        let record = self.load()?.agent(agent_id).cloned().ok_or_else(|| {
            FleetRegistryError::Invalid(format!("unknown fleet agent {agent_id}"))
        })?;
        let _ = resolve_catalog_release(self.layout().releases_root(), release_id)?;
        let manifest = release_manifest_path(self.layout().releases_root(), release_id);
        let allowance = ReleaseAllowance {
            schema_version: RELEASE_METADATA_SCHEMA_VERSION,
            agent_id: agent_id.clone(),
            release_id: release_id.clone(),
            manifest_sha256: sha256_file(&manifest)?,
        };
        let path = allowance_path(record.layout.releases_root(), release_id);
        if path.exists() {
            let actual: ReleaseAllowance = read_bounded_json(&path, MAX_RELEASE_MANIFEST_BYTES)?;
            if matches!(actual.schema_version, 1 | RELEASE_METADATA_SCHEMA_VERSION)
                && actual.agent_id == allowance.agent_id
                && actual.release_id == allowance.release_id
                && actual.manifest_sha256 == allowance.manifest_sha256
            {
                return Ok(());
            }
            return Err(FleetRegistryError::Corrupt(format!(
                "release allowance changed for agent {agent_id} release {release_id}"
            )));
        }
        write_new_json(&path, &allowance)?;
        set_mode(&path, /*mode*/ 0o444)?;
        sync_directory(record.layout.releases_root())
    }

    pub fn resolve_release(
        &self,
        agent_id: &AgentId,
        release_id: &ReleaseId,
    ) -> Result<RegisteredRelease, FleetRegistryError> {
        let record = self.load()?.agent(agent_id).cloned().ok_or_else(|| {
            FleetRegistryError::Invalid(format!("unknown fleet agent {agent_id}"))
        })?;
        let allowance_path = allowance_path(record.layout.releases_root(), release_id);
        let allowance: ReleaseAllowance =
            match read_bounded_json(&allowance_path, MAX_RELEASE_MANIFEST_BYTES) {
                Ok(allowance) => allowance,
                Err(FleetRegistryError::Io(error)) if error.kind() == ErrorKind::NotFound => {
                    return Err(FleetRegistryError::ReleaseNotAllowed {
                        agent_id: agent_id.clone(),
                        release_id: release_id.to_string(),
                    });
                }
                Err(error) => return Err(error),
            };
        if !matches!(
            allowance.schema_version,
            1 | RELEASE_METADATA_SCHEMA_VERSION
        ) || allowance.agent_id != *agent_id
            || allowance.release_id != *release_id
            || !is_sha256(&allowance.manifest_sha256)
        {
            return Err(FleetRegistryError::Corrupt(format!(
                "invalid release allowance for agent {agent_id} release {release_id}"
            )));
        }
        let manifest = release_manifest_path(self.layout().releases_root(), release_id);
        if sha256_file(&manifest)? != allowance.manifest_sha256 {
            return Err(FleetRegistryError::Corrupt(format!(
                "allowed release manifest changed for agent {agent_id} release {release_id}"
            )));
        }
        resolve_catalog_release(self.layout().releases_root(), release_id)
    }

    pub fn allowed_releases(
        &self,
        agent_id: &AgentId,
    ) -> Result<Vec<ReleaseId>, FleetRegistryError> {
        let record = self.load()?.agent(agent_id).cloned().ok_or_else(|| {
            FleetRegistryError::Invalid(format!("unknown fleet agent {agent_id}"))
        })?;
        let mut releases = BTreeSet::new();
        for entry in std::fs::read_dir(record.layout.releases_root())? {
            let entry = entry?;
            let Some(name) = entry.file_name().to_str().map(str::to_owned) else {
                return Err(FleetRegistryError::Corrupt(
                    "release allowance filename is not UTF-8".to_string(),
                ));
            };
            let Some(value) = name
                .strip_prefix(RELEASE_ALLOW_PREFIX)
                .and_then(|value| value.strip_suffix(RELEASE_ALLOW_SUFFIX))
            else {
                continue;
            };
            let release_id = ReleaseId::parse(value)?;
            self.resolve_release(agent_id, &release_id)?;
            if !releases.insert(release_id) || releases.len() > MAX_ALLOWED_RELEASES {
                return Err(FleetRegistryError::Corrupt(
                    "agent release allowance set is duplicate or exceeds its bound".to_string(),
                ));
            }
        }
        Ok(releases.into_iter().collect())
    }

    pub fn compare_and_set_release_state(
        &self,
        agent_id: &AgentId,
        expected_generation: u64,
        current: Option<ReleaseId>,
        previous: Option<ReleaseId>,
    ) -> Result<AgentReleaseState, FleetRegistryError> {
        if current.is_some() && current == previous {
            return Err(FleetRegistryError::Invalid(
                "current and previous release identities must differ".to_string(),
            ));
        }
        let record = self.load()?.agent(agent_id).cloned().ok_or_else(|| {
            FleetRegistryError::Invalid(format!("unknown fleet agent {agent_id}"))
        })?;
        if record.release_state.generation != expected_generation {
            return Err(FleetRegistryError::StaleReleaseGeneration {
                agent_id: agent_id.clone(),
                expected: expected_generation,
                current: record.release_state.generation,
            });
        }
        let generation = expected_generation.checked_add(1).ok_or_else(|| {
            FleetRegistryError::Corrupt("agent release-state generation overflow".to_string())
        })?;
        let state = AgentReleaseState {
            schema_version: AGENT_RELEASE_STATE_SCHEMA_VERSION,
            agent_id: agent_id.clone(),
            generation,
            current,
            previous,
        };
        publish_release_state(record.layout.releases_root(), &state)?;
        Ok(state)
    }
}

pub(crate) fn initialize_release_state(
    releases_root: &Path,
    agent_id: &AgentId,
) -> Result<(), FleetRegistryError> {
    publish_release_state(releases_root, &AgentReleaseState::initial(agent_id.clone()))
}

pub(crate) fn load_release_state(
    releases_root: &Path,
    agent_id: &AgentId,
) -> Result<AgentReleaseState, FleetRegistryError> {
    let mut states = Vec::new();
    for entry in std::fs::read_dir(releases_root)? {
        let entry = entry?;
        let Some(name) = entry.file_name().to_str().map(str::to_owned) else {
            return Err(FleetRegistryError::Corrupt(
                "release-state filename is not UTF-8".to_string(),
            ));
        };
        if name.starts_with('.') || !name.starts_with(RELEASE_STATE_PREFIX) {
            continue;
        }
        let generation = parse_release_state_generation(&name)?;
        let state: AgentReleaseState =
            read_bounded_json(&entry.path(), MAX_RELEASE_MANIFEST_BYTES)?;
        if state.schema_version != AGENT_RELEASE_STATE_SCHEMA_VERSION
            || state.agent_id != *agent_id
            || state.generation != generation
            || (state.current.is_some() && state.current == state.previous)
        {
            return Err(FleetRegistryError::Corrupt(format!(
                "release state does not match agent {agent_id} generation {generation}"
            )));
        }
        states.push((generation, state));
    }
    states.sort_by_key(|(generation, _)| *generation);
    for (expected, (generation, state)) in states.iter().enumerate() {
        if *generation != expected as u64 {
            return Err(FleetRegistryError::Corrupt(
                "agent release-state generations are not contiguous".to_string(),
            ));
        }
        if expected == 0 && state != &AgentReleaseState::initial(agent_id.clone()) {
            return Err(FleetRegistryError::Corrupt(
                "agent release state has an invalid initial value".to_string(),
            ));
        }
    }
    states
        .pop()
        .map(|(_, state)| state)
        .ok_or_else(|| FleetRegistryError::Corrupt("agent release state is missing".to_string()))
}

fn resolve_catalog_release(
    catalog_root: &Path,
    release_id: &ReleaseId,
) -> Result<RegisteredRelease, FleetRegistryError> {
    validate_physical_directory(catalog_root, /*immutable*/ false)?;
    let release_root = catalog_root.join(release_id.as_str());
    let bin_root = release_root.join("bin");
    validate_physical_directory(&release_root, /*immutable*/ true)?;
    validate_physical_directory(&bin_root, /*immutable*/ true)?;
    let actual_root_entries = directory_names(&release_root)?;
    if actual_root_entries != BTreeSet::from(["bin".to_string(), RELEASE_MANIFEST_FILE.to_string()])
    {
        return Err(FleetRegistryError::Corrupt(format!(
            "release {release_id} contains an unexpected closed-world entry"
        )));
    }
    let manifest_path = release_root.join(RELEASE_MANIFEST_FILE);
    validate_immutable_regular_file(&manifest_path, /*executable*/ false)?;
    let metadata: CatalogReleaseMetadata =
        read_bounded_json(&manifest_path, MAX_RELEASE_MANIFEST_BYTES)?;
    let (release_id_from_manifest, agentd, matrixd) = match metadata {
        CatalogReleaseMetadata::V2(metadata) => {
            validate_metadata(&metadata, release_id)?;
            (metadata.release_id, metadata.agentd, metadata.matrixd)
        }
        CatalogReleaseMetadata::V1(metadata) => {
            validate_legacy_metadata(&metadata, release_id)?;
            (
                metadata.release_id,
                ReleaseProgramMetadata {
                    program_relative_path: metadata.program_relative_path,
                    program_sha256: metadata.program_sha256,
                    program_size_bytes: metadata.program_size_bytes,
                    args: metadata.args,
                },
                None,
            )
        }
    };
    let mut expected_bin_entries = BTreeSet::from(["hepta-agentd".to_string()]);
    if matrixd.is_some() {
        expected_bin_entries.insert("hepta-matrixd".to_string());
    }
    if directory_names(&bin_root)? != expected_bin_entries {
        return Err(FleetRegistryError::Corrupt(format!(
            "release {release_id} contains an unexpected closed-world entry"
        )));
    }
    let program = resolve_program(&release_root, &agentd, release_id)?;
    let matrixd = match matrixd {
        Some(metadata) => Some(RegisteredProgram {
            program: resolve_program(&release_root, &metadata, release_id)?,
            args: metadata.args,
        }),
        None => None,
    };
    Ok(RegisteredRelease {
        release_id: release_id_from_manifest,
        program,
        args: agentd.args,
        matrixd,
    })
}

fn resolve_program(
    release_root: &Path,
    metadata: &ReleaseProgramMetadata,
    release_id: &ReleaseId,
) -> Result<PathBuf, FleetRegistryError> {
    let program = release_root.join(&metadata.program_relative_path);
    validate_immutable_regular_file(&program, /*executable*/ true)?;
    if std::fs::metadata(&program)?.len() != metadata.program_size_bytes
        || sha256_file(&program)? != metadata.program_sha256
    {
        return Err(FleetRegistryError::Corrupt(format!(
            "release {release_id} program differs from immutable metadata"
        )));
    }
    Ok(program)
}

fn validate_metadata(
    metadata: &ReleaseMetadata,
    expected: &ReleaseId,
) -> Result<(), FleetRegistryError> {
    if metadata.schema_version != RELEASE_METADATA_SCHEMA_VERSION
        || &metadata.release_id != expected
        || !valid_program_metadata(&metadata.agentd, AGENTD_RELEASE_PROGRAM)
        || metadata
            .matrixd
            .as_ref()
            .is_some_and(|program| !valid_program_metadata(program, MATRIXD_RELEASE_PROGRAM))
    {
        return Err(FleetRegistryError::Corrupt(format!(
            "invalid immutable metadata for release {expected}"
        )));
    }
    validate_arguments(&metadata.agentd.args)?;
    if let Some(matrixd) = &metadata.matrixd {
        validate_arguments(&matrixd.args)?;
    }
    Ok(())
}

fn validate_legacy_metadata(
    metadata: &LegacyReleaseMetadataV1,
    expected: &ReleaseId,
) -> Result<(), FleetRegistryError> {
    if metadata.schema_version != 1
        || &metadata.release_id != expected
        || metadata.program_relative_path != Path::new(AGENTD_RELEASE_PROGRAM)
        || metadata.program_size_bytes == 0
        || !is_sha256(&metadata.program_sha256)
    {
        return Err(FleetRegistryError::Corrupt(format!(
            "invalid legacy immutable metadata for release {expected}"
        )));
    }
    validate_arguments(&metadata.args)
}

fn valid_program_metadata(metadata: &ReleaseProgramMetadata, expected_path: &str) -> bool {
    metadata.program_relative_path == Path::new(expected_path)
        && metadata.program_size_bytes != 0
        && is_sha256(&metadata.program_sha256)
}

fn validate_arguments(args: &[String]) -> Result<(), FleetRegistryError> {
    let bytes = args
        .iter()
        .try_fold(0_usize, |total, value| total.checked_add(value.len()));
    if args.len() > MAX_RELEASE_ARGUMENTS
        || bytes.is_none_or(|count| count > MAX_RELEASE_ARGUMENT_BYTES)
        || args.iter().any(|value| value.contains('\0'))
    {
        return Err(FleetRegistryError::Invalid(
            "release arguments exceed bounded direct-exec limits".to_string(),
        ));
    }
    Ok(())
}

fn validate_source_program(path: &Path) -> Result<PathBuf, FleetRegistryError> {
    if !path.is_absolute()
        || path
            .components()
            .any(|component| matches!(component, Component::CurDir | Component::ParentDir))
    {
        return Err(FleetRegistryError::Invalid(
            "release source program must be an absolute normalized path".to_string(),
        ));
    }
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.file_type().is_file() || metadata.file_type().is_symlink() {
        return Err(FleetRegistryError::Invalid(
            "release source program must be a non-symlink regular file".to_string(),
        ));
    }
    Ok(path.to_path_buf())
}

fn allowance_path(root: &Path, release_id: &ReleaseId) -> PathBuf {
    root.join(format!(
        "{RELEASE_ALLOW_PREFIX}{release_id}{RELEASE_ALLOW_SUFFIX}"
    ))
}

fn release_manifest_path(root: &Path, release_id: &ReleaseId) -> PathBuf {
    root.join(release_id.as_str()).join(RELEASE_MANIFEST_FILE)
}

fn release_state_path(root: &Path, generation: u64) -> PathBuf {
    root.join(format!(
        "{RELEASE_STATE_PREFIX}{generation:020}{RELEASE_STATE_SUFFIX}"
    ))
}

fn publish_release_state(
    releases_root: &Path,
    state: &AgentReleaseState,
) -> Result<(), FleetRegistryError> {
    let final_path = release_state_path(releases_root, state.generation);
    let temp_path = releases_root.join(format!(
        ".release-state-{}-{}-{}.tmp",
        state.generation,
        std::process::id(),
        RELEASE_SEQUENCE.fetch_add(1, Ordering::Relaxed)
    ));
    write_new_json(&temp_path, state)?;
    match std::fs::hard_link(&temp_path, &final_path) {
        Ok(()) => {}
        Err(error) if error.kind() == ErrorKind::AlreadyExists => {
            let _ = std::fs::remove_file(&temp_path);
            return Err(FleetRegistryError::StaleReleaseGeneration {
                agent_id: state.agent_id.clone(),
                expected: state.generation.saturating_sub(1),
                current: state.generation,
            });
        }
        Err(error) => {
            let _ = std::fs::remove_file(&temp_path);
            return Err(error.into());
        }
    }
    let _ = std::fs::remove_file(temp_path);
    sync_directory(releases_root)
}

fn parse_release_state_generation(name: &str) -> Result<u64, FleetRegistryError> {
    let value = name
        .strip_prefix(RELEASE_STATE_PREFIX)
        .and_then(|value| value.strip_suffix(RELEASE_STATE_SUFFIX))
        .filter(|value| value.len() == 20 && value.bytes().all(|byte| byte.is_ascii_digit()))
        .ok_or_else(|| {
            FleetRegistryError::Corrupt(format!("invalid release-state filename {name:?}"))
        })?;
    value.parse().map_err(|_| {
        FleetRegistryError::Corrupt(format!("invalid release-state generation {value}"))
    })
}

fn directory_names(path: &Path) -> Result<BTreeSet<String>, FleetRegistryError> {
    std::fs::read_dir(path)?
        .map(|entry| {
            entry?.file_name().into_string().map_err(|_| {
                FleetRegistryError::Corrupt(format!(
                    "release entry name is not UTF-8 in {}",
                    path.display()
                ))
            })
        })
        .collect()
}

fn write_new_json<T: Serialize>(path: &Path, value: &T) -> Result<(), FleetRegistryError> {
    let mut bytes = serde_json::to_vec(value)
        .map_err(|error| FleetRegistryError::Corrupt(format!("encode release state: {error}")))?;
    bytes.push(b'\n');
    let mut file = OpenOptions::new().write(true).create_new(true).open(path)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    Ok(())
}

fn read_bounded_json<T: for<'de> Deserialize<'de>>(
    path: &Path,
    max_bytes: u64,
) -> Result<T, FleetRegistryError> {
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.file_type().is_file()
        || metadata.file_type().is_symlink()
        || metadata.len() > max_bytes
    {
        return Err(FleetRegistryError::Corrupt(format!(
            "release control path is not a bounded regular file: {}",
            path.display()
        )));
    }
    serde_json::from_slice(&std::fs::read(path)?)
        .map_err(|error| FleetRegistryError::Corrupt(format!("invalid release JSON: {error}")))
}

fn sha256_file(path: &Path) -> Result<String, FleetRegistryError> {
    let mut file = File::open(path)?;
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let count = file.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        hasher.update(&buffer[..count]);
    }
    Ok(hasher
        .finalize()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect())
}

fn is_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| matches!(byte, b'0'..=b'9' | b'a'..=b'f'))
}

fn validate_physical_directory(path: &Path, immutable: bool) -> Result<(), FleetRegistryError> {
    let metadata = std::fs::symlink_metadata(path).map_err(|error| {
        if error.kind() == ErrorKind::NotFound {
            FleetRegistryError::UnknownRelease(
                path.file_name()
                    .and_then(|name| name.to_str())
                    .unwrap_or("unknown")
                    .to_string(),
            )
        } else {
            error.into()
        }
    })?;
    if !metadata.file_type().is_dir() || metadata.file_type().is_symlink() {
        return Err(FleetRegistryError::Corrupt(format!(
            "release path is not a physical directory: {}",
            path.display()
        )));
    }
    if immutable && is_writable(&metadata) {
        return Err(FleetRegistryError::Corrupt(format!(
            "immutable release directory is writable: {}",
            path.display()
        )));
    }
    Ok(())
}

fn validate_immutable_regular_file(
    path: &Path,
    executable: bool,
) -> Result<(), FleetRegistryError> {
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.file_type().is_file()
        || metadata.file_type().is_symlink()
        || is_writable(&metadata)
        || (executable && !is_executable(&metadata))
    {
        return Err(FleetRegistryError::Corrupt(format!(
            "immutable release file has unsafe type or mode: {}",
            path.display()
        )));
    }
    Ok(())
}

#[cfg(unix)]
fn is_writable(metadata: &std::fs::Metadata) -> bool {
    use std::os::unix::fs::PermissionsExt;
    metadata.permissions().mode() & 0o222 != 0
}

#[cfg(not(unix))]
fn is_writable(metadata: &std::fs::Metadata) -> bool {
    !metadata.permissions().readonly()
}

#[cfg(unix)]
fn is_executable(metadata: &std::fs::Metadata) -> bool {
    use std::os::unix::fs::PermissionsExt;
    metadata.permissions().mode() & 0o111 != 0
}

#[cfg(not(unix))]
fn is_executable(_metadata: &std::fs::Metadata) -> bool {
    true
}

#[cfg(unix)]
fn set_mode(path: &Path, mode: u32) -> Result<(), FleetRegistryError> {
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(mode))?;
    Ok(())
}

#[cfg(not(unix))]
fn set_mode(path: &Path, mode: u32) -> Result<(), FleetRegistryError> {
    let mut permissions = std::fs::metadata(path)?.permissions();
    permissions.set_readonly(mode & 0o200 == 0);
    std::fs::set_permissions(path, permissions)?;
    Ok(())
}

fn make_tree_removable(path: &Path) {
    if path.exists() {
        let _ = set_mode(path, /*mode*/ 0o755);
        let _ = set_mode(&path.join("bin"), /*mode*/ 0o755);
        let _ = set_mode(&path.join(AGENTD_RELEASE_PROGRAM), /*mode*/ 0o755);
        let _ = set_mode(&path.join(MATRIXD_RELEASE_PROGRAM), /*mode*/ 0o755);
        let _ = set_mode(&path.join(RELEASE_MANIFEST_FILE), /*mode*/ 0o644);
    }
}

#[cfg(unix)]
fn sync_directory(path: &Path) -> Result<(), FleetRegistryError> {
    File::open(path)?.sync_all()?;
    Ok(())
}

#[cfg(not(unix))]
fn sync_directory(_path: &Path) -> Result<(), FleetRegistryError> {
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::path::Path;

    use codex_hepta_paths::HeptaFleetRoot;
    use tempfile::TempDir;

    use super::*;
    use crate::AgentManifest;
    use crate::ResourceBudget;
    use crate::WorkspaceBinding;

    const FIRST_AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
    const SECOND_AGENT_ID: &str = "019153a4-3088-7e03-a56a-9b1964f75dd3";

    struct Fixture {
        _temp: TempDir,
        root: HeptaFleetRoot,
        registry: FleetRegistry,
        first: AgentId,
        second: AgentId,
        source: PathBuf,
    }

    impl Fixture {
        fn new() -> Result<Self, FleetRegistryError> {
            let temp = tempfile::tempdir()?;
            let root = HeptaFleetRoot::parse(temp.path().join("fleet"))
                .map_err(|error| FleetRegistryError::Invalid(error.to_string()))?;
            let registry = FleetRegistry::initialize(root.clone())?;
            let first = register(&registry, &root, temp.path(), FIRST_AGENT_ID, "workspace-a")?;
            let second = register(
                &registry,
                &root,
                temp.path(),
                SECOND_AGENT_ID,
                "workspace-b",
            )?;
            let source = temp.path().join("hepta-agentd");
            std::fs::write(&source, b"#!/bin/sh\nexit 0\n")?;
            Ok(Self {
                _temp: temp,
                root,
                registry,
                first,
                second,
                source,
            })
        }
    }

    #[test]
    fn catalog_resolves_only_digest_bound_per_agent_allowances() -> Result<(), FleetRegistryError> {
        let fixture = Fixture::new()?;
        let release_id = ReleaseId::parse("agentd-v1")?;
        let installed = fixture.registry.install_release(
            release_id.clone(),
            &fixture.source,
            vec!["--fixed".to_string()],
        )?;
        assert_eq!(installed.release_id, release_id);
        assert!(matches!(
            fixture
                .registry
                .resolve_release(&fixture.first, &release_id),
            Err(FleetRegistryError::ReleaseNotAllowed { .. })
        ));
        fixture
            .registry
            .allow_release(&fixture.first, &release_id)?;
        let resolved = fixture
            .registry
            .resolve_release(&fixture.first, &release_id)?;
        assert_eq!(resolved.args, vec!["--fixed"]);
        assert!(
            resolved
                .program
                .starts_with(fixture.registry.layout().releases_root())
        );
        assert!(matches!(
            fixture
                .registry
                .resolve_release(&fixture.second, &release_id),
            Err(FleetRegistryError::ReleaseNotAllowed { .. })
        ));
        assert_eq!(
            fixture.registry.allowed_releases(&fixture.first)?,
            vec![release_id]
        );
        Ok(())
    }

    #[test]
    fn schema_v2_bundle_binds_both_exact_programs_and_closed_world()
    -> Result<(), FleetRegistryError> {
        let fixture = Fixture::new()?;
        let matrix_source = fixture._temp.path().join("hepta-matrixd");
        std::fs::write(&matrix_source, b"#!/bin/sh\nexit 0\n# matrix\n")?;
        let release_id = ReleaseId::parse("paired-v2")?;
        let installed = fixture.registry.install_release_bundle(
            release_id.clone(),
            &fixture.source,
            vec!["--agent".to_string()],
            Some(&matrix_source),
            vec!["--matrix".to_string()],
        )?;
        assert_eq!(installed.args, vec!["--agent"]);
        assert_eq!(
            installed
                .matrixd
                .as_ref()
                .map(|program| program.args.clone()),
            Some(vec!["--matrix".to_string()])
        );
        fixture
            .registry
            .allow_release(&fixture.first, &release_id)?;
        let resolved = fixture
            .registry
            .resolve_release(&fixture.first, &release_id)?;
        assert!(resolved.matrixd.is_some());

        let release_root = fixture
            .registry
            .layout()
            .releases_root()
            .join(release_id.as_str());
        set_mode(&release_root, 0o755)?;
        std::fs::write(release_root.join("unexpected"), b"not allowed")?;
        set_mode(&release_root, 0o555)?;
        assert!(matches!(
            fixture
                .registry
                .resolve_release(&fixture.first, &release_id),
            Err(FleetRegistryError::Corrupt(_))
        ));
        Ok(())
    }

    #[test]
    fn strict_schema_v1_catalog_and_allowance_remain_agentd_only_compatible()
    -> Result<(), FleetRegistryError> {
        let fixture = Fixture::new()?;
        let release_id = ReleaseId::parse("legacy-v1")?;
        let release_root = fixture
            .registry
            .layout()
            .releases_root()
            .join(release_id.as_str());
        let bin_root = release_root.join("bin");
        std::fs::create_dir(&release_root)?;
        std::fs::create_dir(&bin_root)?;
        let program = release_root.join(AGENTD_RELEASE_PROGRAM);
        std::fs::copy(&fixture.source, &program)?;
        set_mode(&program, 0o555)?;
        let metadata = LegacyReleaseMetadataV1 {
            schema_version: 1,
            release_id: release_id.clone(),
            program_relative_path: PathBuf::from(AGENTD_RELEASE_PROGRAM),
            program_sha256: sha256_file(&program)?,
            program_size_bytes: std::fs::metadata(&program)?.len(),
            args: vec!["--legacy".to_string()],
        };
        let manifest = release_root.join(RELEASE_MANIFEST_FILE);
        write_new_json(&manifest, &metadata)?;
        set_mode(&manifest, /*mode*/ 0o444)?;
        set_mode(&bin_root, /*mode*/ 0o555)?;
        set_mode(&release_root, 0o555)?;

        let manifest_sha256 = sha256_file(&manifest)?;
        let allowance = ReleaseAllowance {
            schema_version: 1,
            agent_id: fixture.first.clone(),
            release_id: release_id.clone(),
            manifest_sha256,
        };
        let agent = fixture
            .registry
            .load()?
            .agent(&fixture.first)
            .unwrap()
            .clone();
        let allowance_path = allowance_path(agent.layout.releases_root(), &release_id);
        write_new_json(&allowance_path, &allowance)?;
        set_mode(&allowance_path, 0o444)?;

        let resolved = fixture
            .registry
            .resolve_release(&fixture.first, &release_id)?;
        assert_eq!(resolved.args, vec!["--legacy"]);
        assert!(resolved.matrixd.is_none());
        fixture
            .registry
            .allow_release(&fixture.first, &release_id)?;
        Ok(())
    }

    #[test]
    fn program_mutation_is_detected_and_release_state_survives_reopen()
    -> Result<(), FleetRegistryError> {
        let fixture = Fixture::new()?;
        let v1 = ReleaseId::parse("agentd-v1")?;
        let v2 = ReleaseId::parse("agentd-v2")?;
        fixture
            .registry
            .install_release(v1.clone(), &fixture.source, Vec::new())?;
        fixture
            .registry
            .install_release(v2.clone(), &fixture.source, Vec::new())?;
        fixture.registry.allow_release(&fixture.first, &v1)?;
        fixture.registry.allow_release(&fixture.first, &v2)?;
        let first = fixture.registry.compare_and_set_release_state(
            &fixture.first,
            0,
            Some(v1.clone()),
            None,
        )?;
        let second = fixture.registry.compare_and_set_release_state(
            &fixture.first,
            first.generation,
            Some(v2.clone()),
            Some(v1),
        )?;
        let reopened = FleetRegistry::open_existing(fixture.root.clone())?;
        assert_eq!(
            reopened
                .load()?
                .agent(&fixture.first)
                .unwrap()
                .release_state,
            second
        );

        let program = fixture
            .registry
            .layout()
            .releases_root()
            .join(v2.as_str())
            .join(AGENTD_RELEASE_PROGRAM);
        set_mode(&program, 0o755)?;
        std::fs::write(&program, b"changed")?;
        set_mode(&program, 0o555)?;
        assert!(matches!(
            fixture.registry.resolve_release(&fixture.first, &v2),
            Err(FleetRegistryError::Corrupt(_))
        ));
        Ok(())
    }

    fn register(
        registry: &FleetRegistry,
        root: &HeptaFleetRoot,
        parent: &Path,
        value: &str,
        workspace_name: &str,
    ) -> Result<AgentId, FleetRegistryError> {
        let workspace = parent.join(workspace_name);
        std::fs::create_dir(&workspace)?;
        let workspace = workspace.canonicalize()?;
        let agent_id = AgentId::parse(value)
            .map_err(|error| FleetRegistryError::Invalid(error.to_string()))?;
        registry.register(AgentManifest::new(
            agent_id.clone(),
            WorkspaceBinding::new(workspace, root)?,
            ResourceBudget::local_default(),
        )?)?;
        Ok(agent_id)
    }
}
