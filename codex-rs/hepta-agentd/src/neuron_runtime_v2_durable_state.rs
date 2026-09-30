/// Versioned, non-authorizing Agentd control-plane state for one Neuron owner
/// topology. It contains no model output, admission capability or result-use
/// grant; it only makes lifecycle and generation-handoff intent crash-visible.
pub const AGENTD_NEURON_GENERATION_STATE_SCHEMA_V2: u32 = 2;

const AGENTD_NEURON_GENERATION_STATE_DOMAIN_V2: &[u8] =
    b"hepta.agentd.neuron-generation-state.v2";
const MAX_AGENTD_NEURON_GENERATION_STATE_BYTES: u64 = 64 * 1024;
static AGENTD_NEURON_GENERATION_STATE_TEMP_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AgentdNeuronControlStateErrorV2 {
    Invalid,
    Corrupt,
    Io(io::ErrorKind),
}

impl AgentdNeuronControlStateErrorV2 {
    #[must_use]
    pub const fn stable_code(self) -> &'static str {
        match self {
            Self::Invalid => "control_state_invalid",
            Self::Corrupt => "control_state_corrupt",
            Self::Io(_) => "control_state_io",
        }
    }
}

impl fmt::Display for AgentdNeuronControlStateErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for AgentdNeuronControlStateErrorV2 {}

impl From<io::Error> for AgentdNeuronControlStateErrorV2 {
    fn from(error: io::Error) -> Self {
        Self::Io(error.kind())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AgentdNeuronGenerationStateV2 {
    pub schema_version: u32,
    pub lifecycle: AgentdNeuronLifecycleStateV2,
    pub active_generation: u64,
    pub retained_generations: Vec<u64>,
    pub reload_target_generation: Option<u64>,
    pub state_digest: String,
}

impl AgentdNeuronGenerationStateV2 {
    pub fn new(
        lifecycle: AgentdNeuronLifecycleStateV2,
        active_generation: u64,
        mut retained_generations: Vec<u64>,
        reload_target_generation: Option<u64>,
    ) -> Result<Self, AgentdNeuronControlStateErrorV2> {
        retained_generations.sort_unstable();
        let mut value = Self {
            schema_version: AGENTD_NEURON_GENERATION_STATE_SCHEMA_V2,
            lifecycle,
            active_generation,
            retained_generations,
            reload_target_generation,
            state_digest: String::new(),
        };
        value.state_digest = value.expected_digest()?.to_string();
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), AgentdNeuronControlStateErrorV2> {
        if self.schema_version != AGENTD_NEURON_GENERATION_STATE_SCHEMA_V2
            || self.active_generation == 0
            || self
                .retained_generations
                .iter()
                .any(|generation| *generation == 0 || *generation >= self.active_generation)
            || self
                .retained_generations
                .windows(2)
                .any(|pair| pair[0] >= pair[1])
        {
            return Err(AgentdNeuronControlStateErrorV2::Invalid);
        }
        match (self.lifecycle, self.reload_target_generation) {
            (AgentdNeuronLifecycleStateV2::Reloading, Some(target))
                if target > self.active_generation
                    && !self.retained_generations.contains(&target) => {}
            (AgentdNeuronLifecycleStateV2::Reloading, _) => {
                return Err(AgentdNeuronControlStateErrorV2::Invalid);
            }
            (_, None) => {}
            (_, Some(_)) => return Err(AgentdNeuronControlStateErrorV2::Invalid),
        }
        if self.state_digest.is_empty()
            || self.state_digest != self.expected_digest()?.to_string()
        {
            return Err(AgentdNeuronControlStateErrorV2::Corrupt);
        }
        Ok(())
    }

    fn expected_digest(&self) -> Result<Digest32, AgentdNeuronControlStateErrorV2> {
        let mut bytes = AGENTD_NEURON_GENERATION_STATE_DOMAIN_V2.to_vec();
        bytes.extend_from_slice(&self.schema_version.to_be_bytes());
        bytes.push(lifecycle_code(self.lifecycle));
        bytes.extend_from_slice(&self.active_generation.to_be_bytes());
        bytes.extend_from_slice(
            &u32::try_from(self.retained_generations.len())
                .map_err(|_| AgentdNeuronControlStateErrorV2::Invalid)?
                .to_be_bytes(),
        );
        for generation in &self.retained_generations {
            bytes.extend_from_slice(&generation.to_be_bytes());
        }
        match self.reload_target_generation {
            Some(generation) => {
                bytes.push(1);
                bytes.extend_from_slice(&generation.to_be_bytes());
            }
            None => bytes.push(0),
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

const fn lifecycle_code(value: AgentdNeuronLifecycleStateV2) -> u8 {
    match value {
        AgentdNeuronLifecycleStateV2::Starting => 0,
        AgentdNeuronLifecycleStateV2::Serving => 1,
        AgentdNeuronLifecycleStateV2::Quiescing => 2,
        AgentdNeuronLifecycleStateV2::Sealed => 3,
        AgentdNeuronLifecycleStateV2::Reloading => 4,
        AgentdNeuronLifecycleStateV2::Stopped => 5,
        AgentdNeuronLifecycleStateV2::Failed => 6,
    }
}

pub fn write_agentd_neuron_generation_state_v2(
    path: &Path,
    state: &AgentdNeuronGenerationStateV2,
) -> Result<(), AgentdNeuronControlStateErrorV2> {
    state.validate()?;
    let parent_before = validate_generation_state_path(path, false)?;
    let encoded = serde_json::to_vec_pretty(state)
        .map_err(|_| AgentdNeuronControlStateErrorV2::Corrupt)?;
    let encoded_bytes = u64::try_from(encoded.len())
        .map_err(|_| AgentdNeuronControlStateErrorV2::Invalid)?;
    if encoded.is_empty() || encoded_bytes > MAX_AGENTD_NEURON_GENERATION_STATE_BYTES {
        return Err(AgentdNeuronControlStateErrorV2::Invalid);
    }
    let parent = path
        .parent()
        .ok_or(AgentdNeuronControlStateErrorV2::Invalid)?;
    let final_name = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or(AgentdNeuronControlStateErrorV2::Invalid)?;
    if final_name.is_empty() || final_name == "." || final_name == ".." {
        return Err(AgentdNeuronControlStateErrorV2::Invalid);
    }
    let sequence =
        AGENTD_NEURON_GENERATION_STATE_TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let temporary = parent.join(format!(
        ".{final_name}.{}.{sequence}.tmp",
        std::process::id()
    ));
    let result = (|| {
        let mut options = OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut file = options.open(&temporary)?;
        file.write_all(&encoded)?;
        file.sync_all()?;
        let opened = file.metadata()?;
        validate_generation_state_metadata(&opened)?;
        let temporary_metadata = std::fs::symlink_metadata(&temporary)?;
        validate_generation_state_metadata(&temporary_metadata)?;
        validate_same_generation_state_identity(&opened, &temporary_metadata)?;
        drop(file);
        replace_generation_state_same_directory(&temporary, path)?;
        sync_generation_state_directory(parent)?;
        let published = read_generation_state_bytes(path)?;
        if published != encoded {
            return Err(AgentdNeuronControlStateErrorV2::Corrupt);
        }
        let parent_after = generation_state_parent_metadata(path)?;
        validate_same_generation_state_directory_identity(&parent_before, &parent_after)?;
        Ok::<(), AgentdNeuronControlStateErrorV2>(())
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&temporary);
    }
    result
}

pub fn read_agentd_neuron_generation_state_v2(
    path: &Path,
) -> Result<AgentdNeuronGenerationStateV2, AgentdNeuronControlStateErrorV2> {
    let bytes = read_generation_state_bytes(path)?;
    let state: AgentdNeuronGenerationStateV2 =
        serde_json::from_slice(&bytes).map_err(|_| AgentdNeuronControlStateErrorV2::Corrupt)?;
    state.validate()?;
    Ok(state)
}

fn read_generation_state_bytes(
    path: &Path,
) -> Result<Vec<u8>, AgentdNeuronControlStateErrorV2> {
    let parent_before = validate_generation_state_path(path, true)?;
    let before = std::fs::symlink_metadata(path)?;
    validate_generation_state_metadata(&before)?;

    let file = OpenOptions::new().read(true).open(path)?;
    let opened = file.metadata()?;
    validate_generation_state_metadata(&opened)?;
    validate_same_generation_state_identity(&before, &opened)?;

    let mut reader = file.take(
        MAX_AGENTD_NEURON_GENERATION_STATE_BYTES
            .checked_add(1)
            .ok_or(AgentdNeuronControlStateErrorV2::Invalid)?,
    );
    let mut bytes = Vec::new();
    reader.read_to_end(&mut bytes)?;
    let byte_count =
        u64::try_from(bytes.len()).map_err(|_| AgentdNeuronControlStateErrorV2::Invalid)?;
    if bytes.is_empty() || byte_count > MAX_AGENTD_NEURON_GENERATION_STATE_BYTES {
        return Err(AgentdNeuronControlStateErrorV2::Invalid);
    }

    let after = std::fs::symlink_metadata(path)?;
    validate_generation_state_metadata(&after)?;
    validate_same_generation_state_identity(&opened, &after)?;
    let parent_after = generation_state_parent_metadata(path)?;
    validate_same_generation_state_directory_identity(&parent_before, &parent_after)?;
    Ok(bytes)
}

fn generation_state_exists(path: &Path) -> Result<bool, AgentdNeuronControlStateErrorV2> {
    // Validate the host-owned parent before any controller constructor fences
    // caller handles. Missing, symlinked or non-directory parents therefore
    // fail without changing the caller's execution epoch.
    validate_generation_state_path(path, false)?;
    match std::fs::symlink_metadata(path) {
        Ok(metadata) => {
            if metadata.file_type().is_symlink() || !metadata.is_file() {
                Err(AgentdNeuronControlStateErrorV2::Invalid)
            } else {
                Ok(true)
            }
        }
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(false),
        Err(error) => Err(error.into()),
    }
}

fn persist_generation_state(
    path: Option<&Path>,
    lifecycle: AgentdNeuronLifecycleStateV2,
    active_generation: u64,
    retained_generations: Vec<u64>,
    reload_target_generation: Option<u64>,
) -> Result<AgentdNeuronGenerationStateV2, AgentdNeuronControlStateErrorV2> {
    let state = AgentdNeuronGenerationStateV2::new(
        lifecycle,
        active_generation,
        retained_generations,
        reload_target_generation,
    )?;
    if let Some(path) = path {
        write_agentd_neuron_generation_state_v2(path, &state)?;
    }
    Ok(state)
}

impl AgentdNeuronGenerationControllerStateV2 {
    fn generation_state(
        &self,
        lifecycle: AgentdNeuronLifecycleStateV2,
        reload_target_generation: Option<u64>,
    ) -> Result<AgentdNeuronGenerationStateV2, AgentdNeuronControlStateErrorV2> {
        AgentdNeuronGenerationStateV2::new(
            lifecycle,
            self.active
                .generation()
                .map_err(|_| AgentdNeuronControlStateErrorV2::Invalid)?,
            self.retained.keys().copied().collect(),
            reload_target_generation,
        )
    }

    fn persist_transition(
        &self,
        lifecycle: AgentdNeuronLifecycleStateV2,
        reload_target_generation: Option<u64>,
    ) -> Result<(), AgentdNeuronControlStateErrorV2> {
        persist_generation_state(
            self.state_path.as_deref(),
            lifecycle,
            self.active
                .generation()
                .map_err(|_| AgentdNeuronControlStateErrorV2::Invalid)?,
            self.retained.keys().copied().collect(),
            reload_target_generation,
        )?;
        Ok(())
    }
}

fn poison_control_state(
    error: AgentdNeuronControlStateErrorV2,
) -> AgentdNeuronControlErrorV2 {
    AgentdNeuronControlErrorV2::ControlState(error)
}

fn validate_generation_state_path(
    path: &Path,
    require_file: bool,
) -> Result<std::fs::Metadata, AgentdNeuronControlStateErrorV2> {
    let parent_metadata = generation_state_parent_metadata(path)?;
    match std::fs::symlink_metadata(path) {
        Ok(metadata) => {
            if metadata.file_type().is_symlink() || !metadata.is_file() {
                return Err(AgentdNeuronControlStateErrorV2::Invalid);
            }
        }
        Err(error) if !require_file && error.kind() == io::ErrorKind::NotFound => {}
        Err(error) => return Err(error.into()),
    }
    Ok(parent_metadata)
}

fn generation_state_parent_metadata(
    path: &Path,
) -> Result<std::fs::Metadata, AgentdNeuronControlStateErrorV2> {
    let parent = path
        .parent()
        .ok_or(AgentdNeuronControlStateErrorV2::Invalid)?;
    let metadata = std::fs::symlink_metadata(parent)?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(AgentdNeuronControlStateErrorV2::Invalid);
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if metadata.mode() & 0o077 != 0 {
            return Err(AgentdNeuronControlStateErrorV2::Invalid);
        }
    }
    Ok(metadata)
}

fn validate_generation_state_metadata(
    metadata: &std::fs::Metadata,
) -> Result<(), AgentdNeuronControlStateErrorV2> {
    if !metadata.is_file()
        || metadata.len() == 0
        || metadata.len() > MAX_AGENTD_NEURON_GENERATION_STATE_BYTES
    {
        return Err(AgentdNeuronControlStateErrorV2::Invalid);
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if metadata.nlink() != 1 || metadata.mode() & 0o077 != 0 {
            return Err(AgentdNeuronControlStateErrorV2::Invalid);
        }
    }
    Ok(())
}

#[cfg(unix)]
fn validate_same_generation_state_identity(
    left: &std::fs::Metadata,
    right: &std::fs::Metadata,
) -> Result<(), AgentdNeuronControlStateErrorV2> {
    use std::os::unix::fs::MetadataExt;
    if left.dev() != right.dev() || left.ino() != right.ino() {
        return Err(AgentdNeuronControlStateErrorV2::Invalid);
    }
    Ok(())
}

#[cfg(not(unix))]
fn validate_same_generation_state_identity(
    left: &std::fs::Metadata,
    right: &std::fs::Metadata,
) -> Result<(), AgentdNeuronControlStateErrorV2> {
    if left.len() != right.len() {
        return Err(AgentdNeuronControlStateErrorV2::Invalid);
    }
    Ok(())
}

#[cfg(unix)]
fn validate_same_generation_state_directory_identity(
    left: &std::fs::Metadata,
    right: &std::fs::Metadata,
) -> Result<(), AgentdNeuronControlStateErrorV2> {
    use std::os::unix::fs::MetadataExt;
    if left.dev() != right.dev() || left.ino() != right.ino() {
        return Err(AgentdNeuronControlStateErrorV2::Invalid);
    }
    Ok(())
}

#[cfg(not(unix))]
fn validate_same_generation_state_directory_identity(
    _left: &std::fs::Metadata,
    _right: &std::fs::Metadata,
) -> Result<(), AgentdNeuronControlStateErrorV2> {
    Ok(())
}

fn replace_generation_state_same_directory(
    temporary: &Path,
    destination: &Path,
) -> Result<(), io::Error> {
    #[cfg(unix)]
    {
        std::fs::rename(temporary, destination)
    }
    #[cfg(not(unix))]
    {
        if destination.exists() {
            std::fs::remove_file(destination)?;
        }
        std::fs::rename(temporary, destination)
    }
}

#[cfg(unix)]
fn sync_generation_state_directory(path: &Path) -> Result<(), io::Error> {
    File::open(path)?.sync_all()
}

#[cfg(not(unix))]
fn sync_generation_state_directory(_path: &Path) -> Result<(), io::Error> {
    Ok(())
}
