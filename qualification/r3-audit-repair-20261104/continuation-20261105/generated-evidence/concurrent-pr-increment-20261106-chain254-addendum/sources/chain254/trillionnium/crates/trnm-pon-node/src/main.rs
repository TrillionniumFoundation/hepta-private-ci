//! Ordinary native development entrypoint. Signed transactions remain external inputs.
mod growth_cli;
mod host_public_guard;
use serde_json::{json, Value};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs::{File, OpenOptions},
    io::{Read, Write},
    os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt},
    path::Path,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    time::{Duration, Instant},
};
use trnm_crypto_primitives::qualified_work_task::{
    derive_matrices, verify_development_admission, TaskMaterial,
};
use trnm_pon_node::{development_public, digest, ingress, Error, Node, Packet, Result, Settings};
use trnm_pon_node::{
    mining::{run_pool_mining, MiningConfig, MiningMaterial},
    peer_polling::{run_pinned_peer_polling, PeerPollingConfig},
    PoolLimits,
};
use trnm_protocol::qualified_work_task::{SignedQualifiedWorkTask, TaskPurpose};
use zeroize::Zeroizing;
fn need<'a>(args: &'a BTreeMap<String, String>, key: &str) -> Result<&'a str> {
    args.get(key)
        .map(String::as_str)
        .ok_or_else(|| format!("missing {key}").into())
}
fn number(args: &BTreeMap<String, String>, key: &str, default: u64) -> Result<u64> {
    args.get(key)
        .map(|s| s.parse().map_err(|_| Error::from(format!("invalid {key}"))))
        .unwrap_or(Ok(default))
}
fn read(path: &str, limit: u64) -> Result<Vec<u8>> {
    let mut bytes = Vec::new();
    File::open(path)?.take(limit + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > limit {
        return Err("INPUT_LIMIT".into());
    }
    Ok(bytes)
}

/// Read one exact packet either from the existing file seam or from bounded
/// stdin. The stdin path exists so an external owner can hand off already
/// durable bytes without creating another mutable packet file or operation
/// ledger. Exactly one source is required.
fn packet_input(args: &BTreeMap<String, String>) -> Result<Vec<u8>> {
    let path = args.get("--packet");
    let stdin = args.get("--packet-stdin").map(String::as_str) == Some("true");
    if path.is_some() == stdin {
        return Err("PACKET_INPUT_EXACTLY_ONE".into());
    }
    if let Some(path) = path {
        return read(path, 1_048_576);
    }
    let mut bytes = Vec::new();
    std::io::stdin()
        .lock()
        .take(1_048_577)
        .read_to_end(&mut bytes)?;
    if bytes.len() > 1_048_576 {
        return Err("INPUT_LIMIT".into());
    }
    Ok(bytes)
}

fn growth_input_remaining(deadline: Instant) -> Result<Duration> {
    deadline
        .checked_duration_since(Instant::now())
        .filter(|remaining| !remaining.is_zero())
        .ok_or_else(|| "PUBLIC_CLIENT_DEADLINE".into())
}

/// The ordinary growth client's one command-start deadline includes its exact
/// packet input. Poll the original stdin descriptor; no helper reader can
/// outlive the command. Regular filesystem calls remain nonpreemptible, with
/// deadline checks before and after each call. Legacy packet_input is unchanged.
fn growth_packet_input(args: &BTreeMap<String, String>, deadline: Instant) -> Result<Vec<u8>> {
    const LIMIT: usize = 1_048_576;
    let path = args.get("--packet");
    let stdin = args.get("--packet-stdin").map(String::as_str) == Some("true");
    if path.is_some() == stdin {
        return Err("PACKET_INPUT_EXACTLY_ONE".into());
    }
    growth_input_remaining(deadline)?;
    let mut file = if let Some(path) = path {
        let opened = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK)
            .open(path);
        growth_input_remaining(deadline)?;
        let file = opened.map_err(|_| "PUBLIC_GROWTH_PACKET_FILE")?;
        let metadata = file.metadata();
        growth_input_remaining(deadline)?;
        let metadata = metadata.map_err(|_| "PUBLIC_GROWTH_PACKET_FILE")?;
        if !metadata.file_type().is_file() {
            return Err("PUBLIC_GROWTH_PACKET_FILE".into());
        }
        if metadata.len() > LIMIT as u64 {
            return Err("INPUT_LIMIT".into());
        }
        Some(file)
    } else {
        None
    };
    let mut bytes = Vec::new();
    let mut buffer = [0u8; 64 * 1024];
    loop {
        let remaining = growth_input_remaining(deadline)?;
        if file.is_none() {
            let mut descriptor = libc::pollfd {
                fd: libc::STDIN_FILENO,
                events: libc::POLLIN,
                revents: 0,
            };
            let milliseconds = remaining.as_millis().clamp(1, i32::MAX as u128) as i32;
            // SAFETY: one initialized descriptor remains live for this call.
            let ready = unsafe { libc::poll(&mut descriptor, 1, milliseconds) };
            let poll_error = (ready < 0).then(std::io::Error::last_os_error);
            growth_input_remaining(deadline)?;
            if let Some(error) = poll_error {
                if error.kind() == std::io::ErrorKind::Interrupted {
                    continue;
                }
                return Err(error.into());
            }
            if ready == 0 {
                continue;
            }
            if descriptor.revents & (libc::POLLERR | libc::POLLNVAL) != 0 {
                return Err("PUBLIC_GROWTH_PACKET_STDIN".into());
            }
            if descriptor.revents & (libc::POLLIN | libc::POLLHUP) == 0 {
                continue;
            }
        }
        let maximum = buffer.len().min(LIMIT + 1 - bytes.len());
        let read = if let Some(file) = file.as_mut() {
            file.read(&mut buffer[..maximum])
        } else {
            // SAFETY: the original stdin is the sole command input, and the
            // initialized writable slice has the stated bounded length. Poll
            // precedes this read; no other command thread consumes stdin.
            let count =
                unsafe { libc::read(libc::STDIN_FILENO, buffer.as_mut_ptr().cast(), maximum) };
            if count < 0 {
                Err(std::io::Error::last_os_error())
            } else {
                Ok(count as usize)
            }
        };
        growth_input_remaining(deadline)?;
        let count = match read {
            Err(error)
                if matches!(
                    error.kind(),
                    std::io::ErrorKind::Interrupted | std::io::ErrorKind::WouldBlock
                ) =>
            {
                continue
            }
            other => other?,
        };
        if count == 0 {
            return Ok(bytes);
        }
        bytes.extend_from_slice(&buffer[..count]);
        if bytes.len() > LIMIT {
            return Err("INPUT_LIMIT".into());
        }
    }
}
fn read_owned_configuration(
    path: &str,
    limit: u64,
    private: bool,
    file_error: &'static str,
    length_error: &'static str,
) -> Result<Vec<u8>> {
    // Inspect the opened descriptor, not a path checked before open. O_NOFOLLOW plus
    // the descriptor metadata closes the symlink/replacement window for these inputs.
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK)
        .open(path)
        .map_err(|_| Error::from(file_error))?;
    let metadata = file.metadata().map_err(|_| Error::from(file_error))?;
    let mode = metadata.permissions().mode();
    if !metadata.file_type().is_file()
        || metadata.nlink() != 1
        || (private && mode & 0o077 != 0)
        || (!private && mode & 0o022 != 0)
    {
        return Err(file_error.into());
    }
    // Partial reads and length errors must also clear an owned secret buffer.
    let mut bytes = Zeroizing::new(Vec::new());
    file.take(limit + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| Error::from(file_error))?;
    if bytes.len() as u64 > limit {
        return Err(length_error.into());
    }
    Ok(std::mem::take(&mut *bytes))
}

const OWNER_CONFIG_OPTIONS: [&str; 5] = [
    "--operator-task-config",
    "--operator-task-config-sha256",
    "--operator-task-source-commit",
    "--operator-task-policy-source-sha256",
    "--operator-task-registry2-package",
];
fn operator_task_inputs(
    args: &BTreeMap<String, String>,
) -> Result<Option<trnm_pon_node::operator_task_policy::RestrictedNodeInputs>> {
    let mode = args.get("--operator-task-mode");
    let any = OWNER_CONFIG_OPTIONS
        .iter()
        .any(|key| args.contains_key(*key));
    if mode.is_none() && !any {
        return Ok(None);
    }
    if mode.map(String::as_str) != Some(trnm_pon_node::operator_task_policy::MODE)
        || !OWNER_CONFIG_OPTIONS
            .iter()
            .all(|key| args.contains_key(*key))
    {
        return Err("OWNER_TASK_COMPLETE_CONFIG_REQUIRED".into());
    }
    let path = Path::new(need(args, "--operator-task-config")?);
    if !path.is_absolute() {
        return Err("OWNER_TASK_CONFIG_ABSOLUTE".into());
    }
    let before =
        std::fs::symlink_metadata(path).map_err(|_| Error::from("OWNER_TASK_CONFIG_FILE"))?;
    let uid = rustix::process::geteuid().as_raw();
    if !before.is_file()
        || before.uid() != uid
        || before.nlink() != 1
        || before.mode() & 0o7777 != 0o600
        || before.len() == 0
        || before.len() > 262_144
    {
        return Err("OWNER_TASK_CONFIG_FILE".into());
    }
    let mut file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK)
        .open(path)
        .map_err(|_| Error::from("OWNER_TASK_CONFIG_FILE"))?;
    let mut raw = Vec::new();
    (&mut file)
        .take(262_145)
        .read_to_end(&mut raw)
        .map_err(|_| Error::from("OWNER_TASK_CONFIG_FILE"))?;
    let after = file
        .metadata()
        .map_err(|_| Error::from("OWNER_TASK_CONFIG_FILE"))?;
    let visible =
        std::fs::symlink_metadata(path).map_err(|_| Error::from("OWNER_TASK_CONFIG_FILE"))?;
    let identity = |m: &std::fs::Metadata| {
        (
            m.dev(),
            m.ino(),
            m.len(),
            m.mode(),
            m.uid(),
            m.nlink(),
            m.mtime(),
            m.mtime_nsec(),
            m.ctime(),
            m.ctime_nsec(),
        )
    };
    if identity(&before) != identity(&after)
        || identity(&after) != identity(&visible)
        || raw.len() as u64 != before.len()
    {
        return Err("OWNER_TASK_CONFIG_CHANGED".into());
    }
    use sha2::{Digest, Sha256};
    let expected = digest(need(args, "--operator-task-config-sha256")?)?;
    if <[u8; 32]>::from(Sha256::digest(&raw)) != expected {
        return Err("OWNER_TASK_CONFIG_SHA".into());
    }
    let inputs: trnm_pon_node::operator_task_policy::RestrictedNodeInputs =
        serde_json::from_slice(&raw).map_err(|_| Error::from("OWNER_TASK_CONFIG_SCHEMA"))?;
    if inputs.expected_uid != uid {
        return Err("OWNER_TASK_CONFIG_UID".into());
    }
    trnm_pon_node::operator_task_policy::validate_protected_inputs(
        &inputs,
        need(args, "--operator-task-source-commit")?,
        need(args, "--operator-task-policy-source-sha256")?,
        need(args, "--operator-task-registry2-package")?,
    )
    .map_err(|_| Error::from("OWNER_TASK_CONFIG_AUTHORITY"))?;
    Ok(Some(inputs))
}
fn open_operator_node(
    path: &Path,
    settings: Settings,
    workers: usize,
    inputs: Option<trnm_pon_node::operator_task_policy::RestrictedNodeInputs>,
    authenticated_state: bool,
) -> Result<Node> {
    match (inputs, authenticated_state) {
        (Some(_), true) => Err("NATIVE_STATE_BACKEND_EXTERNAL_OWNER".into()),
        (Some(inputs), false) => {
            Node::open_with_operator_task_policy(path, settings, workers, inputs)
        }
        (None, true) => Node::open_with_authenticated_state(path, settings, workers),
        (None, false) => Node::open(path, settings, workers),
    }
}

/// Select an actual local-store implementation before reading outside owner
/// configuration or opening a namespace. An unrelated command cannot ignore it.
fn authenticated_state_backend(command: &str, args: &BTreeMap<String, String>) -> Result<bool> {
    let Some(choice) = args.get("--state-backend") else {
        return Ok(false);
    };
    let authenticated = match choice.as_str() {
        "legacy-v2" => false,
        "authenticated-v1" => true,
        "permanent-account-growth-native-v2"
            if command == "serve" && public_growth_profile(args) =>
        {
            false
        }
        _ => return Err("NATIVE_STATE_BACKEND".into()),
    };
    if !matches!(
        command,
        "status"
            | "recover"
            | "pool-status"
            | "capacity-observe"
            | "evaluation-observe"
            | "evaluation-round-observe"
            | "pool-submit"
            | "mine-loop"
            | "mine"
            | "make"
            | "submit"
            | "packet-status"
            | "export"
            | "confirm"
            | "confirm-batch"
            | "sync"
            | "serve"
    ) {
        return Err("NATIVE_STATE_BACKEND_COMMAND".into());
    }
    if authenticated
        && (args.contains_key("--operator-task-mode")
            || OWNER_CONFIG_OPTIONS
                .iter()
                .any(|key| args.contains_key(*key)))
    {
        return Err("NATIVE_STATE_BACKEND_EXTERNAL_OWNER".into());
    }
    Ok(authenticated)
}

const MAX_REQUEST_OBSERVATION_OUTPUT_BYTES: usize = 16 * 1024 * 1024;

/// Local diagnostics only. Keep one descriptor from before Node::open until
/// after all scoped workers join; never reopen a mutable output path.
struct RequestObservationExport {
    file: File,
    observer: ingress::public_v3::PublicRequestObserver,
}

fn request_observation_export(
    command: &str,
    args: &BTreeMap<String, String>,
) -> Result<Option<RequestObservationExport>> {
    let Some(path) = args.get("--request-observation-output") else {
        if args.contains_key("--request-observation-capacity") {
            return Err("REQUEST_OBSERVATION_OUTPUT_REQUIRED".into());
        }
        return Ok(None);
    };
    if command != "serve"
        || !public_v3_service_profile(args)
        || args.get("--public-development-network").map(String::as_str) != Some("true")
    {
        return Err("REQUEST_OBSERVATION_EXPLICIT_PUBLIC_V3_REQUIRED".into());
    }
    let capacity = number(args, "--request-observation-capacity", 1024)?;
    if !(1..=ingress::public_v3::MAX_REQUEST_OBSERVATION_RECORDS as u64).contains(&capacity) {
        return Err("PUBLIC_OBSERVATION_CAPACITY".into());
    }
    let observer = ingress::public_v3::PublicRequestObserver::new(capacity as usize)?;
    let file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK)
        .open(path)
        .map_err(|_| Error::from("REQUEST_OBSERVATION_OUTPUT_FILE"))?;
    file.set_permissions(std::fs::Permissions::from_mode(0o600))
        .map_err(|_| Error::from("REQUEST_OBSERVATION_OUTPUT_FILE"))?;
    check_request_observation_descriptor(&file)?;
    Ok(Some(RequestObservationExport { file, observer }))
}

fn check_request_observation_descriptor(file: &File) -> Result<()> {
    let metadata = file
        .metadata()
        .map_err(|_| Error::from("REQUEST_OBSERVATION_OUTPUT_FILE"))?;
    if !metadata.is_file()
        || metadata.nlink() != 1
        || metadata.permissions().mode() & 0o7777 != 0o600
    {
        return Err("REQUEST_OBSERVATION_OUTPUT_FILE".into());
    }
    Ok(())
}

struct BoundedObservationBuffer(Vec<u8>);
impl Write for BoundedObservationBuffer {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        if bytes.len() > MAX_REQUEST_OBSERVATION_OUTPUT_BYTES.saturating_sub(self.0.len()) {
            return Err(std::io::Error::other("REQUEST_OBSERVATION_OUTPUT_LIMIT"));
        }
        self.0.extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

impl RequestObservationExport {
    fn write_after_join(
        &mut self,
        context: Value,
        service_succeeded: bool,
        mining_succeeded: Option<bool>,
        polling_succeeded: Option<bool>,
    ) -> Result<()> {
        let snapshot = self.observer.snapshot();
        let coverage_complete = snapshot.coverage_complete();
        let value = json!({
            "schema":"public-v3-local-cli-request-observation-v1",
            "context":context,
            "source_claim":{"commit":null,"tree":null,"runtime_source_attestation":false,
                "scope":"Externally bind the actual binary and exact source; this mutable local process does not attest Git bytes."},
            "completion":{"service_returned":true,"all_scoped_workers_joined":true,
                "service_succeeded":service_succeeded,"mining_succeeded":mining_succeeded,
                "peer_polling_succeeded":polling_succeeded,"capture_coverage_complete":coverage_complete},
            "snapshot":snapshot,
            "scope":{"unsigned_local_observation":true,"operation_body_digest_is_commitment_only":true,
                "guest_identity_or_body_or_peer_locator_exported":false,
                "application_syscall_bytes_not_physical_network_bytes":true,
                "full_work_CPU_nested_in_dispatch_not_additive":true,
                "reactor_authentication_response_signing_CPU_excluded":true,
                "native_stages_nonpreemptive":true,"ledger_effects_not_rolled_back_by_export_failure":true,
                "kill_before_join_or_during_write_leaves_empty_or_incomplete_output":true},
            "public_network_ready":false,"production_activation":false,"independent_accepted":false,
            "work_profile_qualified":false,"model_quality_qualified":false,"public_sla_qualified":false
        });
        let mut write = || -> Result<()> {
            check_request_observation_descriptor(&self.file)?;
            let mut bytes = BoundedObservationBuffer(Vec::new());
            serde_json::to_writer(&mut bytes, &value)
                .map_err(|_| Error::from("REQUEST_OBSERVATION_OUTPUT_LIMIT"))?;
            bytes.write_all(b"\n")?;
            self.file.write_all(&bytes.0)?;
            self.file.flush()?;
            self.file.sync_all()?;
            check_request_observation_descriptor(&self.file)?;
            Ok(())
        };
        write().map_err(|_| Error::from(format!(
            "REQUEST_OBSERVATION_OUTPUT_IO:service_returned=true:all_scoped_workers_joined=true:service_succeeded={service_succeeded}:mining_succeeded={mining_succeeded:?}:peer_polling_succeeded={polling_succeeded:?}:ledger_effects_not_rolled_back=true"
        )))
    }
}

fn secret_identity(path: &str) -> Result<ingress::DevelopmentIdentity> {
    let bytes = Zeroizing::new(read_owned_configuration(
        path,
        65,
        true,
        "AUTH_SECRET_FILE",
        "AUTH_SECRET_LENGTH",
    )?);
    let text = std::str::from_utf8(&bytes).map_err(|_| Error::from("AUTH_SECRET_ENCODING"))?;
    let secret = text.strip_suffix('\n').unwrap_or(text);
    if secret.len() != 64 || secret.contains(char::is_whitespace) {
        return Err("AUTH_SECRET_LENGTH".into());
    }
    // Never let a provider/parser's formatted diagnostic carry secret input to
    // the CLI error sink. Public identity output is separately derived from the
    // opaque signing key; no secret string is retained in DevelopmentIdentity.
    ingress::DevelopmentIdentity::from_secret_hex(secret)
        .map_err(|_| Error::from("AUTH_KEY_INVALID"))
}

fn peer_roster(path: &str) -> Result<Vec<String>> {
    let bytes = read_owned_configuration(
        path,
        16_384,
        false,
        "AUTH_ROSTER_FILE",
        "AUTH_ROSTER_LENGTH",
    )?;
    let peers: Vec<String> = serde_json::from_slice(&bytes)?;
    let unique: BTreeSet<_> = peers.iter().cloned().collect();
    if peers.is_empty() || peers.len() > 64 || unique.len() != peers.len() {
        return Err("AUTH_ROSTER".into());
    }
    Ok(peers)
}

fn session_generation(args: &BTreeMap<String, String>) -> Result<u64> {
    let generation: u64 = need(args, "--session-generation")?
        .parse()
        .map_err(|_| Error::from("AUTH_GENERATION"))?;
    if generation == 0 || generation > i64::MAX as u64 {
        return Err("AUTH_GENERATION".into());
    }
    Ok(generation)
}

fn authenticated_client(
    args: &BTreeMap<String, String>,
) -> Result<Option<ingress::AuthenticatedClient>> {
    let present = [
        args.contains_key("--auth-secret"),
        args.contains_key("--server-public"),
        args.contains_key("--session-generation"),
    ];
    if present.iter().all(|value| !value) {
        return Ok(None);
    }
    if !present.iter().all(|value| *value) {
        return Err("AUTH_CLIENT_OPTIONS".into());
    }
    Ok(Some(ingress::AuthenticatedClient::new(
        secret_identity(need(args, "--auth-secret")?)?,
        need(args, "--server-public")?.to_owned(),
        session_generation(args)?,
    )?))
}

fn authenticated_server(
    args: &BTreeMap<String, String>,
) -> Result<Option<ingress::AuthenticatedServer>> {
    let present = [
        args.contains_key("--auth-secret"),
        args.contains_key("--peer-roster"),
        args.contains_key("--session-generation"),
    ];
    if present.iter().all(|value| !value) {
        return Ok(None);
    }
    if !present.iter().all(|value| *value)
        || args
            .get("--authenticated-development-network")
            .map(String::as_str)
            != Some("true")
    {
        return Err("AUTH_SERVER_OPTIONS".into());
    }
    Ok(Some(ingress::AuthenticatedServer::new(
        secret_identity(need(args, "--auth-secret")?)?,
        peer_roster(need(args, "--peer-roster")?)?,
        session_generation(args)?,
    )?))
}

fn admission_profile(args: &BTreeMap<String, String>) -> Result<bool> {
    match args.get("--admission-profile").map(String::as_str) {
        None | Some("legacy-development") => Ok(false),
        Some("connection-work-v1") => Ok(true),
        _ => Err("ADMISSION_PROFILE".into()),
    }
}
fn public_profile(args: &BTreeMap<String, String>) -> bool {
    matches!(
        args.get("--admission-profile").map(String::as_str),
        Some(
            ingress::public_v2::PROFILE
                | ingress::public_v3::PROFILE
                | ingress::public_v3::GROWTH_PROFILE
        )
    )
}
fn public_pool_profile(args: &BTreeMap<String, String>) -> bool {
    args.get("--admission-profile").map(String::as_str) == Some(ingress::public_v3::PROFILE)
}

fn public_growth_profile(args: &BTreeMap<String, String>) -> bool {
    args.get("--admission-profile").map(String::as_str) == Some(ingress::public_v3::GROWTH_PROFILE)
}
fn public_v3_service_profile(args: &BTreeMap<String, String>) -> bool {
    public_pool_profile(args) || public_growth_profile(args)
}
// Explicit fixed growth namespace/profile before owner configuration or store I/O.
fn growth_network_options(command: &str, args: &BTreeMap<String, String>) -> Result<bool> {
    let growth = public_growth_profile(args);
    if !growth {
        if args.contains_key("--growth-namespace")
            || args.contains_key("--resource-profile-sha256")
            || args.contains_key("--request-deadline-ms")
            || command == "packet-status" && args.contains_key("--peer")
        {
            return Err("PUBLIC_GROWTH_PROFILE".into());
        }
        return Ok(false);
    }
    if !matches!(command, "serve" | "push" | "packet-status" | "head") {
        return Err("PUBLIC_GROWTH_PROFILE".into());
    }
    if command == "serve" {
        if args.get("--state-backend").map(String::as_str)
            != Some("permanent-account-growth-native-v2")
            || args.get("--public-development-network").map(String::as_str) != Some("true")
        {
            return Err("PUBLIC_GROWTH_PROFILE".into());
        }
    } else if [
        "--store",
        "--state-backend",
        "--workers",
        "--logical-now",
        "--reliable-submit",
        "--submit-deadline-ms",
        "--submit-attempts",
        "--submit-call-cap",
        "--submit-parent-depth",
    ]
    .iter()
    .any(|key| args.contains_key(*key))
    {
        return Err("PUBLIC_GROWTH_CLIENT_OPTIONS".into());
    }
    need(args, "--growth-namespace")?;
    if ![1, 2, 4, 8].contains(&number(args, "--workers", 1)?) {
        return Err("PUBLIC_GROWTH_WORKERS".into());
    }
    if args.keys().any(|key| {
        key.starts_with("--operator-task-")
            || matches!(
                key.as_str(),
                "--evaluation-policy"
                    | "--task-profile"
                    | "--model-profile"
                    | "--model-task-windows"
                    | "--model-task-windows-sha256"
                    | "--model-data-owner"
                    | "--actor-profile"
                    | "--deployment-spec"
                    | "--deployment-bootstrap"
                    | "--deployment-model"
                    | "--deployment-input"
                    | "--deployment-checkpoint"
                    | "--deployment-activation"
                    | "--pool-policy"
                    | "--mine"
                    | "--peers"
                    | "--peer-poll-ms"
                    | "--peer-pages"
                    | "--authenticated-development-network"
                    | "--peer-roster"
                    | "--session-generation"
            )
    }) {
        return Err("PUBLIC_GROWTH_UNSUPPORTED_OPTIONS".into());
    }
    Ok(true)
}

// Refuse an option/profile mismatch BEFORE opening a Node or service
// ledger, rather than silently accepting a kernel-cap claim on another lane.
fn priced_sync_context(args: &BTreeMap<String, String>) -> bool {
    // A signed authenticated peer proves identity, not CPU payment. Incomplete
    // authentication options will be refused later but must never become a
    // free loopback import in the meantime.
    public_profile(args)
        || ["--auth-secret", "--server-public", "--session-generation"]
            .iter()
            .any(|option| args.contains_key(*option))
}

/// A public History source remains untrusted even if its configured transport
/// address is loopback: a local proxy can forward arbitrary WAN proof bytes.
/// Public sync always joins the SAME fixed, root-owned host CPU/memory/pid
/// envelope as V3. Plain development sync retains its existing locality
/// contract; this is a host resource check, not verified work authority.
fn sync_host_kernel_owner(
    address: std::net::SocketAddr,
    selected_public: bool,
) -> Result<Option<trnm_pon_node::host_kernel_parent::HostKernelBudget>> {
    if selected_public {
        let owner = trnm_pon_node::host_kernel_parent::require_host_kernel_budget(
            address,
            Some(trnm_pon_node::host_kernel_parent::FIXED_PUBLIC_KERNEL_PARENT),
        )?
        .ok_or("PUBLIC_HOST_KERNEL_REQUIRED")?;
        owner.verify()?;
        Ok(Some(owner))
    } else {
        trnm_pon_node::host_kernel_parent::require_for_listener(address)
    }
}

/// A pinned peer can return arbitrary W1 bytes to the same process even
/// when the public V3 listener itself binds loopback. The entire combined
/// service must use the ONE administrator-pinned Host cgroup once polling is
/// configured: no separate listener, relay, PID or peer budget is granted.
fn pinned_peer_service_host_kernel(
    listener: std::net::SocketAddr,
    configured_parent: Option<&str>,
    polling_enabled: bool,
) -> Result<Option<trnm_pon_node::host_kernel_parent::HostKernelBudget>> {
    let parent = configured_parent.or_else(|| {
        polling_enabled.then_some(trnm_pon_node::host_kernel_parent::FIXED_PUBLIC_KERNEL_PARENT)
    });
    let owner = host_public_guard::require_host_kernel_budget(listener, parent)?;
    if polling_enabled && owner.is_none() {
        return Err("PUBLIC_HOST_KERNEL_REQUIRED".into());
    }
    if let Some(kernel) = &owner {
        kernel.verify()?;
    }
    Ok(owner)
}

fn validate_host_kernel_profile(command: &str, args: &BTreeMap<String, String>) -> Result<()> {
    if args.contains_key("--host-kernel-parent")
        && (command != "serve"
            || !public_v3_service_profile(args)
            || args.get("--public-development-network").map(String::as_str) != Some("true"))
    {
        return Err("PUBLIC_HOST_KERNEL_PROFILE".into());
    }
    Ok(())
}

fn reliable_submit_plan(
    command: &str,
    args: &BTreeMap<String, String>,
    started: Instant,
) -> Result<Option<trnm_pon_node::public_submit::SubmitRecoveryPlan>> {
    use trnm_pon_node::public_submit::SubmitRecoveryPlan;
    let options = [
        "--submit-deadline-ms",
        "--submit-attempts",
        "--submit-call-cap",
        "--submit-parent-depth",
    ];
    if !args.contains_key("--reliable-submit") {
        if options.iter().any(|option| args.contains_key(*option)) {
            return Err("SUBMIT_RECOVERY_OPT_IN_REQUIRED".into());
        }
        return Ok(None);
    }
    if command != "push" || !public_pool_profile(args) {
        return Err("SUBMIT_RECOVERY_PUBLIC_V3_PUSH_REQUIRED".into());
    }
    let budget = Duration::from_millis(number(args, "--submit-deadline-ms", 60_000)?);
    let plan = SubmitRecoveryPlan {
        started,
        deadline: started
            .checked_add(budget)
            .ok_or("SUBMIT_RECOVERY_LIMITS")?,
        max_submit_attempts: number(args, "--submit-attempts", 3)?
            .try_into()
            .map_err(|_| "SUBMIT_RECOVERY_LIMITS")?,
        max_calls: number(args, "--submit-call-cap", 16)?
            .try_into()
            .map_err(|_| "SUBMIT_RECOVERY_LIMITS")?,
        max_parent_packets: number(args, "--submit-parent-depth", 1)?
            .try_into()
            .map_err(|_| "SUBMIT_RECOVERY_LIMITS")?,
        retry_pause: Duration::from_millis(100),
    };
    plan.validate()?;
    Ok(Some(plan))
}
fn public_policy(args: &BTreeMap<String, String>) -> Result<ingress::public_v2::PublicPolicy> {
    ingress::public_v2::PublicPolicy::new(
        u8::try_from(number(args, "--admission-bits", 16)?)
            .map_err(|_| Error::from("PUBLIC_POLICY"))?,
        Duration::from_millis(number(args, "--admission-ttl-ms", 2000)?),
    )
}
/// Ordinary client commands keep the original protected TCP implementation.
/// The explicit profile pins PNP2/context and never opens a local Node/store.
fn growth_network_call(
    command: &str,
    args: &BTreeMap<String, String>,
    settings: &Settings,
    started: Instant,
) -> Result<Value> {
    let policy = ingress::public_v3::PublicPolicy::new(
        u8::try_from(number(args, "--admission-bits", 16)?).map_err(|_| "PUBLIC_POLICY")?,
        Duration::from_millis(number(args, "--admission-ttl-ms", 2000)?),
    )?;
    let profile = digest(need(args, "--resource-profile-sha256")?)?;
    if profile != policy.growth_id() {
        return Err("PUBLIC_GROWTH_RESOURCE_PIN".into());
    }
    let milliseconds = number(args, "--request-deadline-ms", 30000)?;
    if !(1..=30000).contains(&milliseconds) {
        return Err("PUBLIC_CLIENT_DEADLINE_LIMIT".into());
    }
    let deadline = started + Duration::from_millis(milliseconds);
    let (operation, request) = match command {
        "push" | "packet-status" => {
            let raw = growth_packet_input(args, deadline)?;
            let packet = trnm_pon_node::GrowthPacket::decode(&raw)?;
            if packet.header.ledger.network != settings.network()
                || packet.header.ledger.parameters != settings.parameters()
            {
                return Err("NETWORK".into());
            }
            let text = hex::encode(raw); // Preserve the exact supplied canonical bytes.
            if command == "push" {
                (
                    "growth_submit_v1",
                    ingress::public_v3::Request::GrowthSubmitV1 { packet: text },
                )
            } else {
                (
                    "growth_packet_status_v1",
                    ingress::public_v3::Request::GrowthPacketStatusV1 { packet: text },
                )
            }
        }
        "head" => ("growth_head_v1", ingress::public_v3::Request::GrowthHeadV1),
        _ => return Err("PUBLIC_OPERATION_PROFILE".into()),
    };
    growth_input_remaining(deadline)?;
    let identity = public_identity(args)?;
    growth_input_remaining(deadline)?;
    let pinned_server = need(args, "--server-public")?;
    let (reply, metrics) = ingress::public_v3::call_public_protected_growth_v1(
        need(args, "--peer")?.parse().map_err(|_| "ADDRESS")?,
        &request,
        settings,
        pinned_server,
        &identity,
        policy,
        Some(deadline),
    );
    let reply = reply?; // Includes exact signed profile/N/P/G/server/body/response checks.
    let mut value = json!({
        "schema":"pon-native-growth-remote-client-result-v1",
        "transport_profile":ingress::public_v3::GROWTH_PROFILE,
        "resource_profile":hex::encode(profile), "server_public":pinned_server,
        "network":hex::encode(settings.network()), "parameters":hex::encode(settings.parameters()),
        "genesis":hex::encode(settings.genesis()), "operation":operation,
        "verified_signed_response":true, "response":reply,
        "production_activation":false
    });
    if args.contains_key("--client-observations") {
        value["client_observation"] = json!({"metrics":metrics,"unsigned_local_observation":true,
            "transport_phase_authority":false,"public_ready":false});
    }
    Ok(value)
}

fn public_identity(args: &BTreeMap<String, String>) -> Result<ingress::DevelopmentIdentity> {
    if args.contains_key("--peer-roster")
        || args.contains_key("--session-generation")
        || args.contains_key("--authenticated-development-network")
    {
        return Err("PUBLIC_IDENTITY_OPTIONS".into());
    }
    secret_identity(need(args, "--auth-secret")?)
}
fn public_call(
    args: &BTreeMap<String, String>,
    request: &ingress::Request,
    settings: &Settings,
) -> Result<ingress::public_v2::PublicReply> {
    public_call_before(args, request, settings, None)
}
fn public_call_before(
    args: &BTreeMap<String, String>,
    request: &ingress::Request,
    settings: &Settings,
    deadline: Option<Instant>,
) -> Result<ingress::public_v2::PublicReply> {
    if public_pool_profile(args) {
        let request = match request {
            ingress::Request::Submit { packet } => ingress::public_v3::Request::Submit {
                packet: packet.clone(),
            },
            ingress::Request::Head => ingress::public_v3::Request::Head,
            ingress::Request::History { tip, after } => ingress::public_v3::Request::History {
                tip: tip.clone(),
                after: after.clone(),
            },
            _ => return Err("PUBLIC_OPERATION".into()),
        };
        let reply = public_pool_call_before(args, &request, settings, deadline)?;
        return Ok(ingress::public_v2::PublicReply {
            ok: reply.ok,
            value: reply.value,
            solve_trials: reply.solve_trials,
            solve_elapsed_ns: reply.solve_elapsed_ns,
            body_bytes_sent: reply.body_bytes_sent,
            public_network_ready: reply.public_network_ready,
            identity_authority: reply.identity_authority,
        });
    }
    ingress::public_v2::call_public_protected_v2_with_deadline(
        need(args, "--peer")?
            .parse()
            .map_err(|_| Error::from("PEER_ADDRESS"))?,
        request,
        settings,
        need(args, "--server-public")?,
        &public_identity(args)?,
        public_policy(args)?,
        deadline,
    )
}

fn public_pool_call(
    args: &BTreeMap<String, String>,
    request: &ingress::public_v3::Request,
    settings: &Settings,
) -> Result<ingress::public_v3::PublicReply> {
    public_pool_call_before(args, request, settings, None)
}
fn public_pool_call_before(
    args: &BTreeMap<String, String>,
    request: &ingress::public_v3::Request,
    settings: &Settings,
    deadline: Option<Instant>,
) -> Result<ingress::public_v3::PublicReply> {
    if !public_pool_profile(args) {
        return Err("PUBLIC_V3_REQUIRED".into());
    }
    let (reply, observations) = ingress::public_v3::call_public_protected_v3_with_deadline(
        need(args, "--peer")?.parse().map_err(|_| "PEER_ADDRESS")?,
        request,
        settings,
        need(args, "--server-public")?,
        &public_identity(args)?,
        ingress::public_v3::PublicPolicy::new(
            u8::try_from(number(args, "--admission-bits", 16)?).map_err(|_| "PUBLIC_POLICY")?,
            Duration::from_millis(number(args, "--admission-ttl-ms", 2000)?),
        )?,
        deadline,
    );
    if args.contains_key("--client-observations") {
        eprintln!(
            "{}",
            json!({"schema":"public-v3-cli-client-observation-v1","observations":observations,
            "scope":"local elapsed stage time including failed calls; not server CPU or cost authority",
            "public_network_ready":false})
        );
    }
    reply
}
fn pool_policy(args: &BTreeMap<String, String>) -> Result<PoolLimits> {
    Ok(serde_json::from_slice(&read_owned_configuration(
        need(args, "--pool-policy")?,
        4096,
        false,
        "POOL_POLICY_FILE",
        "POOL_POLICY_LENGTH",
    )?)?)
}
fn mining_configuration(
    args: &BTreeMap<String, String>,
    settings: &Settings,
    policy: &PoolLimits,
    default_seconds: u64,
) -> Result<MiningConfig> {
    let miner = args
        .get("--miner")
        .map(|s| digest(s))
        .transpose()?
        .unwrap_or(policy.preview_miner);
    if miner != policy.preview_miner {
        return Err("POOL_MINER".into());
    }
    let bootstrap = args.contains_key("--task-bootstrap");
    let files = ["--task-model", "--task-input"].map(|key| args.contains_key(key));
    let material = if args.contains_key("--consensus-maintenance") {
        if bootstrap || files.iter().any(|present| *present) {
            return Err("TASK_OPTIONS".into());
        }
        let (model, input, _, _) = settings.consensus_maintenance_material()?;
        MiningMaterial::Registered { model, input }
    } else if settings.task_profile() != "legacy-task-v1" {
        if bootstrap && files.iter().any(|p| *p) {
            return Err("TASK_OPTIONS".into());
        }
        let (model, input) = if bootstrap {
            let (model, input, _, _) = settings.bootstrap_task_material()?;
            (model, input)
        } else {
            if !files.iter().all(|p| *p) {
                return Err("TASK_MATERIAL_REQUIRED".into());
            }
            (
                read(need(args, "--task-model")?, 16384)?,
                read(need(args, "--task-input")?, 16384)?,
            )
        };
        MiningMaterial::Registered { model, input }
    } else {
        if bootstrap || files.iter().any(|p| *p) {
            return Err("SIGNED_TASK_PROFILE_REQUIRED".into());
        }
        MiningMaterial::LegacyDevelopment
    };
    let config = MiningConfig {
        miner,
        material,
        max_transactions: number(args, "--max-transactions", 256)?
            .try_into()
            .map_err(|_| "MINING_LIMITS")?,
        max_transaction_bytes: number(args, "--max-transaction-bytes", 524288)?
            .try_into()
            .map_err(|_| "MINING_LIMITS")?,
        search_attempts: number(args, "--search-attempts", 4096)?,
        pace: Duration::from_millis(number(args, "--pace-ms", 10000)?),
        runtime: Duration::from_secs(number(
            args,
            "--mining-seconds",
            number(args, "--seconds", default_seconds)?,
        )?),
        max_blocks: number(args, "--blocks", 100000)?,
    };
    config.validate()?;
    Ok(config)
}

fn output(path: &str, bytes: &[u8]) -> Result<()> {
    let mut file = OpenOptions::new().create_new(true).write(true).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    File::open(
        Path::new(path)
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
            .unwrap_or(Path::new(".")),
    )?
    .sync_all()?;
    Ok(())
}
fn operator_inputs(
    args: &BTreeMap<String, String>,
) -> Result<(
    trnm_pon_node::operator_deployment::OperatorDeploymentSpec,
    Vec<u8>,
    Vec<u8>,
)> {
    use trnm_pon_node::operator_deployment::{self as actors, offline};
    if need(args, "--actor-profile")? != actors::PROFILE {
        return Err("ACTOR_PROFILE".into());
    }
    let spec = actors::OperatorDeploymentSpec::decode(&offline::read_public(
        Path::new(need(args, "--deployment-spec")?),
        actors::SPEC_BYTES as u64,
    )?)?;
    let model = offline::read_public(Path::new(need(args, "--deployment-model")?), 16384)?;
    let input = offline::read_public(Path::new(need(args, "--deployment-input")?), 16384)?;
    Ok((spec, model, input))
}
fn operator_command(command: &str, args: &BTreeMap<String, String>) -> Result<Value> {
    if args.get("--actor-profile").map(String::as_str)
        == Some(trnm_pon_node::operator_checkpoint_tile::PROFILE)
    {
        return checkpoint_operator_command(command, args);
    }
    if args.contains_key("--deployment-checkpoint") || args.contains_key("--deployment-activation")
    {
        return Err("CHECKPOINT_ACTOR_PROFILE".into());
    }
    use trnm_pon_node::operator_deployment::{self as actors, offline};
    let (spec, model, input) = operator_inputs(args)?;
    let expected = actors::prepare(&spec, &model, &input)?;
    let value = match command {
        "genesis-prepare" => serde_json::to_value(expected)?,
        "genesis-sign" => {
            let template: actors::BootstrapTemplate = actors::decode(&offline::read_public(
                Path::new(need(args, "--deployment-template")?),
                actors::BOOTSTRAP_BYTES as u64,
            )?)?;
            serde_json::to_value(offline::sign_approval_from_file(
                &spec,
                &template,
                &model,
                &input,
                need(args, "--role")?,
                Path::new(need(args, "--signer-secret")?),
            )?)?
        }
        "genesis-finalize" => {
            let template: actors::BootstrapTemplate = actors::decode(&offline::read_public(
                Path::new(need(args, "--deployment-template")?),
                actors::BOOTSTRAP_BYTES as u64,
            )?)?;
            if template != expected {
                return Err("ACTOR_TEMPLATE".into());
            }
            let source = actors::decode(&offline::read_public(
                Path::new(need(args, "--source-approval")?),
                actors::BOOTSTRAP_BYTES as u64,
            )?)?;
            let requester = actors::decode(&offline::read_public(
                Path::new(need(args, "--requester-approval")?),
                actors::BOOTSTRAP_BYTES as u64,
            )?)?;
            let bundle = actors::assemble(&expected, &source, &requester)?;
            // Finalization independently constructs the full public state; a forged
            // template or merely well-shaped approval cannot produce a genesis.
            Settings::development_with_operator_actors(&spec, &bundle, &model, &input)?;
            serde_json::to_value(bundle)?
        }
        _ => return Err("UNKNOWN_COMMAND".into()),
    };
    if let Some(path) = args.get("--output") {
        offline::write_new_public(Path::new(path), &actors::canonical(&value)?)?;
    }
    Ok(value)
}
fn checkpoint_operator_inputs(
    args: &BTreeMap<String, String>,
) -> Result<(
    trnm_pon_node::operator_checkpoint_tile::OperatorCheckpointTileSpecV1,
    Vec<u8>,
    Vec<u8>,
    trnm_pon_node::operator_checkpoint_tile::CheckpointTileRuntimePaths,
)> {
    use trnm_pon_node::{operator_checkpoint_tile as tile, operator_deployment::offline};
    if need(args, "--actor-profile")? != tile::PROFILE {
        return Err("CHECKPOINT_ACTOR_PROFILE".into());
    }
    let spec = tile::OperatorCheckpointTileSpecV1::decode(&offline::read_public(
        Path::new(need(args, "--deployment-spec")?),
        tile::SPEC_BYTES as u64,
    )?)?;
    let model = offline::read_public(Path::new(need(args, "--deployment-model")?), 16384)?;
    let input = offline::read_public(Path::new(need(args, "--deployment-input")?), 16384)?;
    let paths = tile::CheckpointTileRuntimePaths::new(
        need(args, "--deployment-checkpoint")?.into(),
        need(args, "--deployment-activation")?.into(),
    );
    Ok((spec, model, input, paths))
}
fn checkpoint_operator_command(command: &str, args: &BTreeMap<String, String>) -> Result<Value> {
    use trnm_pon_node::{
        operator_checkpoint_tile as tile,
        operator_deployment::{self as actors, offline},
    };
    let (spec, model, input, paths) = checkpoint_operator_inputs(args)?;
    let expected = tile::prepare(&spec, &model, &input, &paths)?;
    let value = match command {
        "genesis-prepare" => serde_json::to_value(expected)?,
        "genesis-sign" => {
            let template: actors::BootstrapTemplate = actors::decode(&offline::read_public(
                Path::new(need(args, "--deployment-template")?),
                8192,
            )?)?;
            serde_json::to_value(tile::sign_approval_from_file(
                &spec,
                &template,
                &model,
                &input,
                &paths,
                need(args, "--role")?,
                Path::new(need(args, "--signer-secret")?),
            )?)?
        }
        "genesis-finalize" => {
            let template: actors::BootstrapTemplate = actors::decode(&offline::read_public(
                Path::new(need(args, "--deployment-template")?),
                8192,
            )?)?;
            if template != expected {
                return Err("CHECKPOINT_TEMPLATE".into());
            }
            let source = actors::decode(&offline::read_public(
                Path::new(need(args, "--source-approval")?),
                8192,
            )?)?;
            let requester = actors::decode(&offline::read_public(
                Path::new(need(args, "--requester-approval")?),
                8192,
            )?)?;
            let bundle = tile::assemble(&expected, &source, &requester)?;
            Settings::development_with_operator_checkpoint_tile(
                &spec, &bundle, &model, &input, paths,
            )?;
            serde_json::to_value(bundle)?
        }
        _ => return Err("UNKNOWN_COMMAND".into()),
    };
    if let Some(path) = args.get("--output") {
        offline::write_new_public(Path::new(path), &actors::canonical(&value)?)?;
    }
    Ok(value)
}

fn continuous_next_frame(pending: &mut Vec<u8>, deadline: Instant) -> Result<Option<Vec<u8>>> {
    use trnm_pon_node::operator_continuous_controller::MAX_FRAME_BYTES;
    loop {
        if let Some(end) = pending.iter().position(|b| *b == b'\n') {
            let frame: Vec<_> = pending.drain(..=end).collect();
            if frame.len() > MAX_FRAME_BYTES {
                return Err("OWNER_CONTINUOUS_FRAME_LIMIT".into());
            }
            return Ok(Some(frame));
        }
        if pending.len() > MAX_FRAME_BYTES || Instant::now() >= deadline {
            return Err("OWNER_CONTINUOUS_FRAME_DEADLINE".into());
        }
        let mut descriptor = libc::pollfd {
            fd: libc::STDIN_FILENO,
            events: libc::POLLIN,
            revents: 0,
        };
        let wait = deadline
            .saturating_duration_since(Instant::now())
            .min(Duration::from_millis(50));
        // SAFETY: initialized one-element storage remains valid for this synchronous call.
        let ready = unsafe { libc::poll(&mut descriptor, 1, wait.as_millis().max(1) as i32) };
        if ready < 0 {
            let error = std::io::Error::last_os_error();
            if error.kind() == std::io::ErrorKind::Interrupted {
                continue;
            }
            return Err(error.into());
        }
        if ready == 0 {
            continue;
        }
        if descriptor.revents & (libc::POLLERR | libc::POLLNVAL) != 0 {
            return Err("OWNER_CONTINUOUS_STDIN".into());
        }
        let mut bytes = [0u8; 4096];
        // SAFETY: writable initialized buffer and Root-owned stdin FD are valid during read.
        let n = unsafe { libc::read(libc::STDIN_FILENO, bytes.as_mut_ptr().cast(), bytes.len()) };
        if n < 0 {
            let error = std::io::Error::last_os_error();
            if error.kind() == std::io::ErrorKind::Interrupted {
                continue;
            }
            return Err(error.into());
        }
        if n == 0 {
            return if pending.is_empty() {
                Ok(None)
            } else {
                Ok(Some(std::mem::take(pending)))
            };
        }
        pending.extend_from_slice(&bytes[..n as usize]);
    }
}
fn continuous_publish(value: &Value) -> Result<()> {
    let raw = serde_json::to_vec(value)?;
    if raw.len() > 2 * 1024 * 1024 {
        return Err("OWNER_CONTINUOUS_OUTPUT_LIMIT".into());
    }
    let mut out = std::io::stdout().lock();
    out.write_all(&raw)?;
    out.write_all(b"\n")?;
    out.flush()?;
    Ok(())
}
fn continuous_command(
    args: &BTreeMap<String, String>,
    started: Instant,
    recovery: bool,
) -> Result<Value> {
    use trnm_pon_node::operator_continuous_controller::{Controller, OutsideLaunch};
    const OPTIONS: [&str; 7] = [
        "--launch",
        "--launch-sha256",
        "--registry-key",
        "--task-key",
        "--source-commit",
        "--policy-source",
        "--registry2-package",
    ];
    if args.len() != OPTIONS.len() || args.keys().any(|k| !OPTIONS.contains(&k.as_str())) {
        return Err("OWNER_CONTINUOUS_ARGUMENTS".into());
    }
    if recovery {
        return trnm_pon_node::operator_continuous_controller::prepare_known_unclean_restart(
            OutsideLaunch {
                path: Path::new(need(args, "--launch")?),
                sha256: need(args, "--launch-sha256")?,
                registry_key: need(args, "--registry-key")?,
                task_key: need(args, "--task-key")?,
                source_commit: need(args, "--source-commit")?,
                node_policy_source: need(args, "--policy-source")?,
                registry2_package: need(args, "--registry2-package")?,
            },
        );
    }
    let mut controller = Controller::open_pinned(
        OutsideLaunch {
            path: Path::new(need(args, "--launch")?),
            sha256: need(args, "--launch-sha256")?,
            registry_key: need(args, "--registry-key")?,
            task_key: need(args, "--task-key")?,
            source_commit: need(args, "--source-commit")?,
            node_policy_source: need(args, "--policy-source")?,
            registry2_package: need(args, "--registry2-package")?,
        },
        started,
    )?;
    continuous_publish(
        &json!({"schema":"restricted-owner-continuous-startup-v1","startup_scope":controller.startup(),"public_network_ready":false,"original8193_qualification":false}),
    )?;
    let mut pending = Vec::new();
    while let Some(frame) = continuous_next_frame(&mut pending, controller.deadline())? {
        continuous_publish(&controller.apply(&frame)?)?;
    }
    controller.close()
}

fn run() -> Result<Value> {
    let command_started = Instant::now();
    let mut raw = std::env::args().skip(1);
    let command = raw.next().ok_or(
        "command: status|mine|submit|packet-status|export|confirm|sync|serve|push|head|history",
    )?;
    let mut args = BTreeMap::new();
    while let Some(key) = raw.next() {
        let value = if matches!(
            key.as_str(),
            "--development"
                | "--authenticated-development-network"
                | "--public-development-network"
                | "--task-bootstrap"
                | "--consensus-maintenance"
                | "--mine"
                | "--client-observations"
                | "--reliable-submit"
                | "--packet-stdin"
        ) {
            "true".into()
        } else {
            raw.next().ok_or("missing argument value")?
        };
        if args.insert(key, value).is_some() {
            return Err("DUPLICATE_OPTION".into());
        }
    }
    if command == "operator-continuous" {
        return continuous_command(&args, command_started, false);
    }
    if command == "operator-continuous-recover" {
        return continuous_command(&args, command_started, true);
    }
    if args.get("--development").map(String::as_str) != Some("true") {
        return Err(
            "EXPLICIT_DEVELOPMENT_REQUIRED: public test identities; no monetary value".into(),
        );
    }
    if command.starts_with("growth-") {
        return growth_cli::run(&command, &args);
    }
    let extra = match command.as_str() {
        "genesis-prepare" => "--output",
        "genesis-sign" => "--deployment-template --role --signer-secret --output",
        "genesis-finalize" => "--deployment-template --source-approval --requester-approval --output",
        "status" | "recover" | "pool-status" | "capacity-observe" => "",
        "evaluation-observe" => "--candidate --ancestry-blocks",
        "evaluation-round-observe" => "--candidate --round-blocks",
        "pool-submit" => "--transactions --pool-policy",
        "pool-push" => "--peer --transactions --pool-context",
        "pool-status-remote" => "--peer",
        "mine-loop" => "--miner --pool-policy --seconds --blocks --pace-ms --search-attempts --max-transactions --max-transaction-bytes --task-bootstrap --task-model --task-input --consensus-maintenance",
        "mine" | "make" => "--transactions --timestamp --output --parent --miner --task-bootstrap --task-manifest --task-model --task-input --consensus-maintenance",
        "task-fixture" => "--task-model --task-input --demand-index --purpose --not-before --expires --demand-nonce --output",
        "submit" => "--packet --packet-stdin --peer",
        "packet-status" => "--packet --packet-stdin --peer",
        "push" => "--packet --packet-stdin --peer --reliable-submit --submit-deadline-ms --submit-attempts --submit-call-cap --submit-parent-depth",
        "export" => "--block --output",
        "confirm" => "--transaction --block",
        "confirm-batch" => "--queries",
        "sync" => "--peer --tip --after --pages --evaluation-candidate --evaluation-round-blocks",
        "head" => "--peer",
        "history" => "--peer --tip --after",
        "serve" => "--listen --seconds --mining-seconds --pool-policy --mine --miner --blocks --pace-ms --search-attempts --max-transactions --max-transaction-bytes --task-bootstrap --task-model --task-input --consensus-maintenance --peers --peer-poll-ms --peer-pages --request-observation-output --request-observation-capacity --host-kernel-parent --growth-namespace",
        _ => return Err("UNKNOWN_COMMAND".into()),
    };
    let authentication_options = match command.as_str() {
        "serve" => {
            "--authenticated-development-network --public-development-network --auth-secret --peer-roster --session-generation"
        }
        "push" | "sync" => "--auth-secret --server-public --session-generation",
        "head" | "history" | "pool-push" | "pool-status-remote" | "packet-status" => "--auth-secret --server-public",
        _ => "",
    };
    let admission_options = match command.as_str() {
        "serve" => "--admission-profile --admission-bits --admission-ttl-ms",
        "push" | "head" | "packet-status" => {
            "--admission-profile --admission-bits --admission-ttl-ms --client-observations --growth-namespace --resource-profile-sha256 --request-deadline-ms"
        }
        "sync" | "history" | "pool-push" | "pool-status-remote" => {
            "--admission-profile --admission-bits --admission-ttl-ms --client-observations"
        }
        _ => "",
    };
    let allowed = format!(
        "--development --store --state-backend --genesis-time --workers --logical-now --evaluation-policy --task-profile --model-profile --model-task-windows --model-task-windows-sha256 --model-data-owner --actor-profile --deployment-spec --deployment-bootstrap --deployment-model --deployment-input --deployment-checkpoint --deployment-activation --operator-task-mode --operator-task-config --operator-task-config-sha256 --operator-task-source-commit --operator-task-policy-source-sha256 --operator-task-registry2-package {authentication_options} {admission_options} {extra}"
    );
    for key in args.keys() {
        if !allowed.split_whitespace().any(|k| k == key) {
            return Err(format!("UNKNOWN_OPTION:{key}").into());
        }
    }
    let growth_network = growth_network_options(&command, &args)?;
    validate_host_kernel_profile(&command, &args)?;
    let authenticated_state = authenticated_state_backend(&command, &args)?;
    // Fixed outside authority is authenticated before any model/material loader.
    let owner_task_config = operator_task_inputs(&args)?;
    if owner_task_config.is_some()
        && (matches!(
            command.as_str(),
            "genesis-prepare"
                | "genesis-sign"
                | "genesis-finalize"
                | "task-fixture"
                | "mine"
                | "make"
                | "mine-loop"
        ) || args.contains_key("--mine"))
    {
        return Err("OWNER_TASK_BUILDER_PENDING".into());
    }
    // Invalid option/profile/capacity combinations and output descriptor checks
    // must precede any Node::open creation or recovery. Later initialization
    // errors may leave this new file empty: that is explicitly not a completion.
    let mut request_observation = request_observation_export(&command, &args)?;
    let recovery_plan = reliable_submit_plan(&command, &args, command_started)?;
    // Local evaluation query inputs reject before Node::open can create/recover a
    // store. Existing --logical-now is explicit trusted test input, never height.
    let evaluation_query = if command == "evaluation-observe" {
        let candidate = digest(need(&args, "--candidate")?)?;
        let bound = number(&args, "--ancestry-blocks", 4096)?;
        if !(1..=4096).contains(&bound) {
            return Err("EVALUATION_OBSERVATION_LIMIT".into());
        }
        Some((candidate, bound))
    } else {
        None
    };
    let evaluation_round_query = if command == "evaluation-round-observe" {
        let candidate = digest(need(&args, "--candidate")?)?;
        let bound = number(&args, "--round-blocks", 4096)?;
        if !(1..=4096).contains(&bound) {
            return Err("EVALUATION_OBSERVATION_LIMIT".into());
        }
        Some((candidate, bound))
    } else {
        None
    };
    let sync_evaluation_query = if command == "sync" {
        match args.get("--evaluation-candidate") {
            Some(candidate) => {
                let candidate = digest(candidate)?;
                let bound = number(&args, "--evaluation-round-blocks", 4096)?;
                if !(1..=4096).contains(&bound) {
                    return Err("EVALUATION_OBSERVATION_LIMIT".into());
                }
                if !public_profile(&args) {
                    return Err("EVALUATION_SYNC_PUBLIC_PROFILE".into());
                }
                Some((candidate, bound))
            }
            None => {
                if args.contains_key("--evaluation-round-blocks") {
                    return Err("EVALUATION_SYNC_CANDIDATE_REQUIRED".into());
                }
                None
            }
        }
    } else {
        None
    };
    if matches!(
        command.as_str(),
        "genesis-prepare" | "genesis-sign" | "genesis-finalize"
    ) {
        if args.keys().any(|key| {
            matches!(
                key.as_str(),
                "--store"
                    | "--genesis-time"
                    | "--workers"
                    | "--logical-now"
                    | "--evaluation-policy"
                    | "--task-profile"
                    | "--model-profile"
                    | "--model-task-windows"
                    | "--model-task-windows-sha256"
                    | "--model-data-owner"
                    | "--deployment-bootstrap"
            )
        }) {
            return Err("ACTOR_PREPARATION_OPTIONS".into());
        }
        return operator_command(&command, &args);
    }
    if !public_profile(&args) {
        admission_profile(&args)?;
    }
    if args.contains_key("--client-observations") && !public_pool_profile(&args) && !growth_network
    {
        return Err("PUBLIC_V3_REQUIRED".into());
    }
    if matches!(
        command.as_str(),
        "serve"
            | "sync"
            | "push"
            | "head"
            | "history"
            | "mine-loop"
            | "pool-push"
            | "pool-status-remote"
    ) && args.contains_key("--logical-now")
    {
        return Err("NETWORK_USES_LOCAL_WALL_CLOCK".into());
    }
    let evaluation_policy = args
        .get("--evaluation-policy")
        .map(String::as_str)
        .unwrap_or("legacy-first-two-v3");
    if !matches!(
        evaluation_policy,
        "legacy-first-two-v3"
            | "closed-round-all-eligible-min-v1"
            | "native-public-evaluation-dev-v1"
            | "native-public-evaluation-quorum-dev-v2"
    ) {
        return Err("EVALUATION_POLICY".into());
    }
    let actor_options = [
        "--actor-profile",
        "--deployment-spec",
        "--deployment-bootstrap",
        "--deployment-model",
        "--deployment-input",
    ];
    let actor_present = actor_options.iter().any(|key| args.contains_key(*key));
    let settings = if growth_network {
        Settings::development_with_profiles(
            Some(number(&args, "--genesis-time", 1)?),
            "native-public-evaluation-dev-v1",
            trnm_mvcc_fee::continuity_v1::PROFILE,
        )?
        .with_permanent_account_growth_v2(need(&args, "--growth-namespace")?)?
    } else if actor_present {
        if !actor_options.iter().all(|key| args.contains_key(*key))
            || [
                "--genesis-time",
                "--evaluation-policy",
                "--task-profile",
                "--model-profile",
                "--model-task-windows",
                "--model-task-windows-sha256",
                "--model-data-owner",
            ]
            .iter()
            .any(|key| args.contains_key(*key))
        {
            return Err("ACTOR_DEPLOYMENT_OPTIONS".into());
        }
        if command == "task-fixture" {
            return Err("ACTOR_EXPLICIT_SIGNATURE_REQUIRED".into());
        }
        if (matches!(command.as_str(), "mine" | "make" | "mine-loop")
            || command == "serve" && args.contains_key("--mine"))
            && !args.contains_key("--miner")
        {
            return Err("ACTOR_EXPLICIT_MINER_REQUIRED".into());
        }
        if args.get("--actor-profile").map(String::as_str)
            == Some(trnm_pon_node::operator_checkpoint_tile::PROFILE)
        {
            let (spec, model, input, paths) = checkpoint_operator_inputs(&args)?;
            let bundle = trnm_pon_node::operator_deployment::decode(
                &trnm_pon_node::operator_deployment::offline::read_public(
                    Path::new(need(&args, "--deployment-bootstrap")?),
                    8192,
                )?,
            )?;
            Settings::development_with_operator_checkpoint_tile(
                &spec, &bundle, &model, &input, paths,
            )?
        } else {
            if args.contains_key("--deployment-checkpoint")
                || args.contains_key("--deployment-activation")
            {
                return Err("CHECKPOINT_ACTOR_PROFILE".into());
            }
            let (spec, model, input) = operator_inputs(&args)?;
            let bundle = trnm_pon_node::operator_deployment::decode(
                &trnm_pon_node::operator_deployment::offline::read_public(
                    Path::new(need(&args, "--deployment-bootstrap")?),
                    8192,
                )?,
            )?;
            Settings::development_with_operator_actors(&spec, &bundle, &model, &input)?
        }
    } else {
        if args.contains_key("--deployment-checkpoint")
            || args.contains_key("--deployment-activation")
        {
            return Err("CHECKPOINT_ACTOR_PROFILE".into());
        }
        let window_flags = [
            "--model-task-windows",
            "--model-task-windows-sha256",
            "--model-data-owner",
        ];
        let present = window_flags
            .iter()
            .filter(|flag| args.contains_key(**flag))
            .count();
        if present != 0 && present != window_flags.len() {
            return Err("TASK_WINDOW_COMPLETE_CONFIG_REQUIRED".into());
        }
        let raw = if present != 0 {
            Some(read_owned_configuration(
                need(&args, "--model-task-windows")?,
                trnm_mvcc_fee::model_task_windows_v1::MAX_MANIFEST_BYTES as u64,
                false,
                "TASK_WINDOW_FILE",
                "TASK_WINDOW_LENGTH",
            )?)
        } else {
            None
        };
        let windows = raw
            .as_ref()
            .map(|raw| -> Result<_> {
                Ok(trnm_mvcc_fee::model_task_windows_v1::PinnedTaskWindows {
                    raw,
                    sha256: digest(need(&args, "--model-task-windows-sha256")?)?,
                    owner: digest(need(&args, "--model-data-owner")?)?,
                })
            })
            .transpose()?;
        Settings::development_with_model_profiles_and_task_windows(
            args.get("--genesis-time")
                .map(|s| s.parse().map_err(|_| Error::from("GENESIS_TIME")))
                .transpose()?,
            evaluation_policy,
            args.get("--task-profile")
                .map(String::as_str)
                .unwrap_or("legacy-task-v1"),
            args.get("--model-profile")
                .map(String::as_str)
                .unwrap_or("linear-expert-dev-v1"),
            windows,
        )?
    };
    if growth_network && command != "serve" {
        return growth_network_call(&command, &args, &settings, command_started);
    }
    // This local observation has no peer request or signed response counterpart.
    // Reject other profiles before opening or creating a store.
    if command == "capacity-observe"
        && settings.task_profile() != trnm_mvcc_fee::continuity_v1::PROFILE
    {
        return Err("CONTINUITY_PROFILE".into());
    }
    if command == "serve" {
        let mining_options = [
            "--mining-seconds",
            "--miner",
            "--blocks",
            "--pace-ms",
            "--search-attempts",
            "--max-transactions",
            "--max-transaction-bytes",
            "--task-bootstrap",
            "--consensus-maintenance",
            "--task-model",
            "--task-input",
        ];
        if !public_pool_profile(&args)
            && (args.contains_key("--pool-policy")
                || args.contains_key("--mine")
                || args.contains_key("--peers")
                || args.contains_key("--peer-poll-ms")
                || args.contains_key("--peer-pages")
                || mining_options.iter().any(|key| args.contains_key(*key)))
        {
            return Err("PUBLIC_V3_REQUIRED".into());
        }
        if !args.contains_key("--mine") && mining_options.iter().any(|key| args.contains_key(*key))
        {
            return Err("MINING_OPTIONS_REQUIRE_MINE".into());
        }
        if args.contains_key("--mining-seconds") {
            let mining_seconds = number(&args, "--mining-seconds", 30)?;
            let service_seconds = number(&args, "--seconds", 30)?;
            if !(1..=259200).contains(&mining_seconds) || mining_seconds > service_seconds {
                return Err("MINING_RUNTIME".into());
            }
        }
        if !args.contains_key("--peers")
            && (args.contains_key("--peer-poll-ms") || args.contains_key("--peer-pages"))
        {
            return Err("PEER_OPTIONS_REQUIRE_PEERS".into());
        }
    }
    // Validate the opened, bounded operator configuration before creating a store.
    // The context below binds effective overrides, rather than an unused file value.
    let polling = if command == "serve" && args.contains_key("--peers") {
        let raw = read_owned_configuration(
            need(&args, "--peers")?,
            16384,
            false,
            "PEER_CONFIG_FILE",
            "PEER_CONFIG_LIMIT",
        )?;
        let mut config: PeerPollingConfig = serde_json::from_slice(&raw)?;
        let service_ms = number(&args, "--seconds", 30)?
            .checked_mul(1000)
            .ok_or("PUBLIC_LIFETIME")?;
        config.runtime_ms = config.runtime_ms.min(service_ms);
        config.poll_interval_ms = number(&args, "--peer-poll-ms", config.poll_interval_ms)?;
        config.max_pages_per_cycle = usize::try_from(number(
            &args,
            "--peer-pages",
            config.max_pages_per_cycle as u64,
        )?)
        .map_err(|_| "PEER_CONFIG_LIMIT")?;
        config.validate(&settings)?;
        if config.bits
            != u8::try_from(number(&args, "--admission-bits", 16)?).map_err(|_| "PUBLIC_POLICY")?
            || config.lifetime_ms != number(&args, "--admission-ttl-ms", 2000)?
        {
            return Err("PEER_CONFIG_CONTEXT".into());
        }
        Some(config)
    } else {
        None
    };
    if matches!(command.as_str(), "pool-push" | "pool-status-remote") {
        let request = if command == "pool-status-remote" {
            ingress::public_v3::Request::PoolStatus
        } else {
            ingress::public_v3::Request::PoolSubmitBundle {
                pool_context: need(&args, "--pool-context")?.to_owned(),
                transactions: serde_json::from_slice(&read(
                    need(&args, "--transactions")?,
                    65536,
                )?)?,
            }
        };
        return Ok(serde_json::to_value(public_pool_call(
            &args, &request, &settings,
        )?)?);
    }
    if !public_profile(&args)
        && (args.contains_key("--public-development-network")
            || (command != "serve"
                && (args.contains_key("--admission-bits")
                    || args.contains_key("--admission-ttl-ms"))))
    {
        return Err("PUBLIC_PROFILE_REQUIRED".into());
    }
    if matches!(command.as_str(), "head" | "history") {
        if !public_profile(&args) {
            return Err("PUBLIC_PROFILE_REQUIRED".into());
        }
        let request = if command == "head" {
            ingress::Request::Head
        } else {
            ingress::Request::History {
                tip: need(&args, "--tip")?.into(),
                after: args
                    .get("--after")
                    .cloned()
                    .unwrap_or(hex::encode(settings.genesis())),
            }
        };
        return Ok(serde_json::to_value(public_call(
            &args, &request, &settings,
        )?)?);
    }
    if command == "task-fixture" {
        if settings.task_profile() != "signed-task-dev-v1" {
            return Err("SIGNED_TASK_PROFILE_REQUIRED".into());
        }
        let model = read(need(&args, "--task-model")?, 16384)?;
        let input = read(need(&args, "--task-input")?, 16384)?;
        let purpose = match need(&args, "--purpose")? {
            "maintenance" => TaskPurpose::Maintenance,
            "adapter" => TaskPurpose::AdapterContraction,
            "evaluation" => TaskPurpose::EvaluationContraction,
            "inference" => TaskPurpose::InferenceContraction,
            _ => return Err("TASK_PURPOSE".into()),
        };
        let signed = settings.development_task_manifest(
            number(&args, "--demand-index", 0)?,
            purpose,
            &model,
            &input,
            number(&args, "--not-before", 1)?,
            number(&args, "--expires", 1000)?,
            number(&args, "--demand-nonce", 1)?,
        )?;
        let wire = signed
            .encode()
            .map_err(|e| Error::from(format!("TASK_MANIFEST:{e:?}")))?;
        output(need(&args, "--output")?, &wire)?;
        return Ok(
            json!({"scope":"public-key development fixture; no real-world demand or consent certificate","signed_manifest":need(&args,"--output")?,"matrix_task":hex::encode(signed.manifest.matrix_task),"production_activation":false}),
        );
    }
    if command == "push" {
        let packet = Packet::decode(&packet_input(&args)?)?;
        let address = need(&args, "--peer")?
            .parse()
            .map_err(|_| Error::from("PEER_ADDRESS"))?;
        if let Some(plan) = recovery_plan {
            use trnm_pon_node::public_submit::{
                submit_with_verified_parent_recovery, PinnedPublicClient,
            };
            let pinned_server = need(&args, "--server-public")?;
            digest(pinned_server)?;
            let identity = public_identity(&args)?;
            let policy = ingress::public_v3::PublicPolicy::new(
                u8::try_from(number(&args, "--admission-bits", 16)?)
                    .map_err(|_| "PUBLIC_POLICY")?,
                Duration::from_millis(number(&args, "--admission-ttl-ms", 2000)?),
            )?;
            let store = Path::new(need(&args, "--store")?);
            if !store.join("native.sqlite").is_file() {
                return Err("SUBMIT_RECOVERY_EXISTING_PRODUCER_REQUIRED".into());
            }
            if Instant::now() >= plan.deadline {
                return Err("SUBMIT_RECOVERY_DEADLINE".into());
            }
            let owner = open_operator_node(
                store,
                settings,
                number(&args, "--workers", 1)? as usize,
                owner_task_config,
                authenticated_state,
            )?;
            let outcome = submit_with_verified_parent_recovery(
                &owner,
                PinnedPublicClient {
                    address,
                    server_public: pinned_server,
                    identity: &identity,
                    policy,
                },
                &packet,
                plan,
            );
            return Ok(serde_json::to_value(outcome)?);
        }
        let request = ingress::Request::Submit {
            packet: hex::encode(packet.encode()?),
        };
        if public_profile(&args) {
            return Ok(serde_json::to_value(public_call(
                &args, &request, &settings,
            )?)?);
        }
        let protected = admission_profile(&args)?;
        if let Some(authentication) = authenticated_client(&args)? {
            let mut owner = open_operator_node(
                Path::new(need(&args, "--store")?),
                settings.clone(),
                number(&args, "--workers", 1)? as usize,
                owner_task_config,
                authenticated_state,
            )?;
            let response = if protected {
                ingress::call_authenticated_durable_protected(
                    &mut owner,
                    address,
                    &request,
                    &authentication,
                )?
            } else {
                ingress::call_authenticated_durable(&mut owner, address, &request, &authentication)?
            };
            return Ok(json!({
                "response":response,
                "state":owner.stats()?,
                "production_activation":false
            }));
        }
        return if protected {
            ingress::call_protected(address, &request, &settings)
        } else {
            ingress::call(address, &request)
        };
    }
    if command == "packet-status"
        && !Path::new(need(&args, "--store")?)
            .join("native.sqlite")
            .is_file()
    {
        return Err("PACKET_STATUS_EXISTING_STORE_REQUIRED".into());
    }
    let clock = number(&args, "--logical-now", ingress::now()?)?;
    let mut node = if growth_network {
        Node::open_with_permanent_account_growth_v2_and_workers(
            Path::new(need(&args, "--store")?),
            settings,
            number(&args, "--workers", 1)? as usize,
        )?
    } else {
        open_operator_node(
            Path::new(need(&args, "--store")?),
            settings,
            number(&args, "--workers", 1)? as usize,
            owner_task_config,
            authenticated_state,
        )?
    };
    let value = match command.as_str() {
        "status" | "recover" => node.stats()?,
        "packet-status" => {
            let packet = Packet::decode(&packet_input(&args)?)?;
            node.exact_packet_observation(&packet)?
        }
        "capacity-observe" => serde_json::to_value(node.capacity_observation()?)?,
        "evaluation-observe" => {
            let (candidate, bound) = evaluation_query.ok_or("EVALUATION_OBSERVATION_LIMIT")?;
            serde_json::to_value(node.evaluation_observation(candidate, clock, bound)?)?
        }
        "evaluation-round-observe" => {
            let (candidate, bound) =
                evaluation_round_query.ok_or("EVALUATION_OBSERVATION_LIMIT")?;
            serde_json::to_value(node.evaluation_round_observation(candidate, clock, bound)?)?
        }
        "pool-status" => serde_json::to_value(node.pool_status()?)?,
        "pool-submit" => {
            let policy: PoolLimits = serde_json::from_slice(&read_owned_configuration(
                need(&args, "--pool-policy")?,
                4096,
                false,
                "POOL_POLICY_FILE",
                "POOL_POLICY_LENGTH",
            )?)?;
            node.enable_local_mempool(policy)?;
            let hexes: Vec<String> =
                serde_json::from_slice(&read(need(&args, "--transactions")?, 65536)?)?;
            if !(1..=16).contains(&hexes.len()) {
                return Err("POOL_GROUP_LIMIT".into());
            }
            let raws = hexes
                .iter()
                .map(|s| {
                    if !(318..=4096).contains(&s.len()) {
                        return Err("TRANSACTION_LIMIT".into());
                    }
                    let raw = hex::decode(s).map_err(|_| Error::from("TRANSACTION_HEX"))?;
                    if hex::encode(&raw) != *s {
                        return Err("TRANSACTION_HEX".into());
                    }
                    Ok(raw)
                })
                .collect::<Result<Vec<_>>>()?;
            serde_json::to_value(node.pool_submit_bundle(raws)?)?
        }
        "mine-loop" => {
            let policy = pool_policy(&args)?;
            let config = mining_configuration(&args, node.settings(), &policy, 60)?;
            node.enable_local_mempool(policy)?;
            let report = run_pool_mining(
                Arc::new(Mutex::new(node)),
                config,
                Arc::new(AtomicBool::new(false)),
                |event| {
                    println!("{}", serde_json::to_string(event)?);
                    std::io::stdout().flush()?;
                    Ok(())
                },
            )?;
            return Ok(
                json!({"result":report,"clock_scope":"local-wall","public_network_ready":false,"production_activation":false}),
            );
        }
        "submit" => {
            let packet = Packet::decode(&packet_input(&args)?)?;
            let id = node.admit(&packet, clock)?;
            node.activate_observed(id, clock)?;
            json!({"block":hex::encode(id),"state":node.stats()?})
        }
        "mine" | "make" => {
            let transactions = if let Some(path) = args.get("--transactions") {
                let text: Vec<String> = serde_json::from_slice(&read(path, 2_097_152)?)?;
                if text.len() > 256 {
                    return Err("TRANSACTION_LIMIT".into());
                }
                text.iter()
                    .map(|s| hex::decode(s).map_err(|_| Error::from("TRANSACTION_HEX")))
                    .collect::<Result<Vec<_>>>()?
            } else {
                Vec::new()
            };
            let timestamp = number(&args, "--timestamp", clock)?;
            let packet = {
                let parent = args
                    .get("--parent")
                    .map(|s| digest(s))
                    .transpose()?
                    .unwrap_or(node.active()?.0);
                let miner = args
                    .get("--miner")
                    .map(|s| digest(s))
                    .transpose()?
                    .unwrap_or(development_public(0)?);
                let files_present = ["--task-manifest", "--task-model", "--task-input"]
                    .map(|key| args.contains_key(key));
                let bootstrap = args.contains_key("--task-bootstrap");
                if args.contains_key("--consensus-maintenance") {
                    if bootstrap || files_present.iter().any(|present| *present) {
                        return Err("TASK_OPTIONS".into());
                    }
                    node.make_consensus_maintenance(parent, transactions, miner, timestamp, 4096)?
                } else if matches!(
                    node.settings().task_profile(),
                    "signed-task-dev-v1"
                        | "signed-task-lifecycle-dev-v2"
                        | "signed-task-lifecycle-dev-v3"
                        | "signed-task-lifecycle-dev-v4"
                        | "consensus-maintenance-continuity-dev-v1"
                        | "signed-checkpoint-tile-maintenance-dev-v1"
                ) {
                    if bootstrap && files_present.iter().any(|present| *present) {
                        return Err("TASK_OPTIONS".into());
                    }
                    let (wire, model, input) = if bootstrap {
                        let wire = if matches!(
                            node.settings().task_profile(),
                            "signed-task-lifecycle-dev-v2"
                                | "signed-task-lifecycle-dev-v3"
                                | "signed-task-lifecycle-dev-v4"
                                | "consensus-maintenance-continuity-dev-v1"
                                | "signed-checkpoint-tile-maintenance-dev-v1"
                        ) {
                            node.settings()
                                .bootstrap_lifecycle_task()?
                                .signed
                                .encode()
                                .map_err(|e| Error::from(format!("TASK_MANIFEST:{e:?}")))?
                        } else {
                            node.settings()
                                .bootstrap_task_statement()?
                                .encode()
                                .map_err(|e| Error::from(format!("TASK_MANIFEST:{e:?}")))?
                        };
                        let (model, input, _, _) = node.settings().bootstrap_task_material()?;
                        (wire, model, input)
                    } else {
                        if !files_present.iter().all(|present| *present) {
                            return Err("TASK_MATERIAL_REQUIRED".into());
                        }
                        (
                            read(need(&args, "--task-manifest")?, 684)?,
                            read(need(&args, "--task-model")?, 16384)?,
                            read(need(&args, "--task-input")?, 16384)?,
                        )
                    };
                    let lifecycle = matches!(
                        node.settings().task_profile(),
                        "signed-task-lifecycle-dev-v2"
                            | "signed-task-lifecycle-dev-v3"
                            | "signed-task-lifecycle-dev-v4"
                            | "consensus-maintenance-continuity-dev-v1"
                            | "signed-checkpoint-tile-maintenance-dev-v1"
                    );
                    let manifest = if lifecycle {
                        trnm_protocol::qualified_work_task::lifecycle_v2::SignedLifecycleTaskV2::decode(&wire).map_err(|e|Error::from(format!("TASK_MANIFEST:{e:?}")))?.manifest
                    } else {
                        SignedQualifiedWorkTask::decode(&wire)
                            .map_err(|e| Error::from(format!("TASK_MANIFEST:{e:?}")))?
                            .manifest
                    };
                    let (a, b) = derive_matrices(&model, &input)
                        .map_err(|e| Error::from(format!("TASK_MATERIAL:{e:?}")))?;
                    let height = node.parent_height(parent)?.checked_add(1).ok_or("HEIGHT")?;
                    let material = TaskMaterial {
                        model: &model,
                        input: &input,
                        a: &a,
                        b: &b,
                    };
                    let verification_material = TaskMaterial {
                        model: &model,
                        input: &input,
                        a: &a,
                        b: &b,
                    };
                    let admitted = if lifecycle {
                        let lease =
                            node.lifecycle_task_lease(parent, manifest.matrix_task, height)?;
                        trnm_crypto_primitives::qualified_work_task::lifecycle_v2::verify_lifecycle_admission(&wire,verification_material,&lease,height).map_err(|e|Error::from(format!("TASK_ADMISSION:{e:?}")))?
                    } else {
                        let context = node
                            .settings()
                            .qualified_task_context(manifest.demand_id, height)?;
                        verify_development_admission(&wire, verification_material, &context)
                            .map_err(|e| Error::from(format!("TASK_ADMISSION:{e:?}")))?
                    };
                    node.make_with_task(
                        parent,
                        transactions,
                        miner,
                        timestamp,
                        4096,
                        &admitted,
                        material,
                    )?
                } else {
                    if bootstrap || files_present.iter().any(|present| *present) {
                        return Err("SIGNED_TASK_PROFILE_REQUIRED".into());
                    }
                    node.make(parent, transactions, miner, timestamp, 4096)?
                }
            };
            output(need(&args, "--output")?, &packet.encode()?)?;
            if command == "mine" {
                let id = node.admit(&packet, clock)?;
                node.activate_observed(id, clock)?;
            }
            json!({"block":hex::encode(packet.id()?),"attempts":packet.header.nonce+1,"admitted":command=="mine","state":node.stats()?})
        }
        "export" => {
            let packet = node.packet(digest(need(&args, "--block")?)?)?;
            output(need(&args, "--output")?, &packet.encode()?)?;
            json!({"block":hex::encode(packet.id()?)})
        }
        "confirm" => serde_json::to_value(node.confirmation(
            digest(need(&args, "--transaction")?)?,
            digest(need(&args, "--block")?)?,
            clock,
        )?)?,
        "confirm-batch" => {
            let queries: Vec<ingress::ConfirmationQuery> =
                serde_json::from_slice(&read(need(&args, "--queries")?, 65_536)?)?;
            serde_json::to_value(
                node.confirmations(&ingress::confirmation_queries(&queries)?, clock)?,
            )?
        }
        "sync" => {
            // One business deadline for every page's transport and native
            // import. Per-packet CPU refill/W1 never renew this allowance.
            let sync_deadline = Instant::now() + Duration::from_secs(300);
            let address = need(&args, "--peer")?
                .parse()
                .map_err(|_| Error::from("PEER_ADDRESS"))?;
            // Public V3 History and authenticated legacy History both carry
            // arbitrary remote W1 proofs into this existing Node. A WAN sync
            // must join the SAME fixed kernel parent as the public receiver.
            // Loopback-only developer sync retains its original behavior.
            let host_kernel = sync_host_kernel_owner(address, priced_sync_context(&args))?;
            if let Some(kernel) = &host_kernel {
                kernel.verify()?;
            }
            let tip = digest(need(&args, "--tip")?)?;
            let after = args
                .get("--after")
                .map(|s| digest(s))
                .transpose()?
                .unwrap_or(node.settings().genesis());
            if public_profile(&args) {
                let pages = number(&args, "--pages", 256)?;
                if !(1..=4096).contains(&pages) {
                    return Err("SYNC_BUDGET".into());
                }
                let mut cursor = after;
                let mut complete = cursor == tip;
                let mut trials = 0u64;
                for _ in 0..pages {
                    if complete {
                        break;
                    }
                    if let Some(kernel) = &host_kernel {
                        kernel.verify()?;
                    }
                    let reply = public_call_before(
                        &args,
                        &ingress::Request::History {
                            tip: hex::encode(tip),
                            after: hex::encode(cursor),
                        },
                        node.settings(),
                        Some(sync_deadline),
                    )?;
                    trials = trials
                        .checked_add(reply.solve_trials)
                        .ok_or("PUBLIC_TRIALS")?;
                    if !reply.ok {
                        return Err(format!("PUBLIC_REMOTE_REFUSED:{}", reply.value).into());
                    }
                    let page: ingress::Page = serde_json::from_value(reply.value)?;
                    complete = page.complete;
                    cursor = ingress::receive_public_page_from_before(
                        &mut node,
                        address,
                        page,
                        tip,
                        cursor,
                        ingress::now()?,
                        sync_deadline,
                    )?;
                    if let Some(kernel) = &host_kernel {
                        kernel.verify()?;
                    }
                }
                if !complete {
                    return Err(format!(
                        "INCOMPLETE_HISTORY:page_budget:after={}",
                        hex::encode(cursor)
                    )
                    .into());
                }
                // A signed remote page is only transport evidence; receive_page owns
                // complete native verification and activation of the fixed tip.
                let mut result = json!({"verified_tip":hex::encode(cursor),"state":node.stats()?,"transport_solve_trials":trials,"public_network_ready":false});
                if let Some((candidate, bound)) = sync_evaluation_query {
                    // The same exclusive local owner has completed native sync.
                    // A refused query cannot undo those committed sync facts.
                    let (active_tip, generation) = node.active()?;
                    let observed_now = ingress::now()?;
                    let observation = node
                        .evaluation_round_observation(candidate, observed_now, bound)
                        .map_err(|error| Error::from(format!(
                            "SYNC_COMPLETED_EVALUATION_OBSERVATION_REFUSED:verified_tip={}:active_tip={}:generation={generation}:{error}",
                            hex::encode(cursor), hex::encode(active_tip),
                        )))?;
                    result["evaluation_observation"] = serde_json::to_value(observation)?;
                    result["evaluation_observation_scope"] = json!({
                        "schema":"native-sync-evaluation-observation-v1",
                        "same_exclusive_local_owner":true,
                        "complete_native_sync":true,
                        "unsigned_local_observation":true,
                        "transport_phase_authority":false,
                        "public_ready":false,
                    });
                }
                result
            } else if let Some(authentication) = authenticated_client(&args)? {
                let verified = ingress::sync_from_authenticated_durable(
                    &mut node,
                    address,
                    tip,
                    after,
                    number(&args, "--pages", 256)? as usize,
                    &authentication,
                )?;
                json!({"verified_tip":hex::encode(verified),"state":node.stats()?})
            } else {
                let verified = ingress::sync_from(
                    &mut node,
                    address,
                    tip,
                    after,
                    number(&args, "--pages", 256)? as usize,
                )?;
                json!({"verified_tip":hex::encode(verified),"state":node.stats()?})
            }
        }
        "serve" => {
            if public_profile(&args) {
                if args.get("--public-development-network").map(String::as_str) != Some("true")
                    || args.contains_key("--server-public")
                {
                    return Err("EXPLICIT_PUBLIC_DEVELOPMENT_REQUIRED".into());
                }
                let identity = public_identity(&args)?;
                let server_public = identity.public_key().to_owned();
                let lifetime = Duration::from_secs(number(&args, "--seconds", 30)?);
                if public_v3_service_profile(&args) {
                    if lifetime == Duration::ZERO || lifetime > Duration::from_secs(259200) {
                        return Err("PUBLIC_LIFETIME".into());
                    }
                    let pool = if growth_network {
                        None
                    } else {
                        Some(pool_policy(&args)?)
                    };
                    let mining = if args.contains_key("--mine") {
                        Some(mining_configuration(
                            &args,
                            node.settings(),
                            pool.as_ref().ok_or("PUBLIC_GROWTH_UNSUPPORTED_OPTIONS")?,
                            30,
                        )?)
                    } else {
                        None
                    };
                    let policy = ingress::public_v3::PublicPolicy::new(
                        u8::try_from(number(&args, "--admission-bits", 16)?)
                            .map_err(|_| "PUBLIC_POLICY")?,
                        Duration::from_millis(number(&args, "--admission-ttl-ms", 2000)?),
                    )?;
                    let polling_identity = identity.clone();
                    let polling_context = polling
                        .as_ref()
                        .map(PeerPollingConfig::context)
                        .transpose()?
                        .map(hex::encode);
                    // This CLI acquires one of four Linux netns-scoped service
                    // slots for its whole lifetime, including miner/peer workers.
                    // Legitimate multiple local peers retain independent Nodes;
                    // a fifth same-namespace CLI cannot mint another budget.
                    let _host_guard = host_public_guard::Guard::acquire()?;
                    // A new process starts with zero CPU/challenge credit. A
                    // kill-and-relaunch cannot reclaim the historical 2s burst.
                    let server =
                        ingress::public_v3::PublicServer::new_process_cold(identity, policy)?;
                    let server = if growth_network {
                        server.with_native_growth()?
                    } else {
                        server
                    };
                    let resource_profile = server.resource_profile();
                    let profile = if growth_network {
                        ingress::public_v3::GROWTH_PROFILE
                    } else {
                        ingress::public_v3::PROFILE
                    };
                    let listener = std::net::TcpListener::bind(
                        args.get("--listen")
                            .map(String::as_str)
                            .unwrap_or("127.0.0.1:0"),
                    )?;
                    // Existing root-provisioned cgroup v2 parent: the actual
                    // kernel, not another local counter, enforces aggregate
                    // CPU/memory/task ceilings across independent processes.
                    let host_kernel = pinned_peer_service_host_kernel(
                        listener.local_addr()?,
                        args.get("--host-kernel-parent").map(String::as_str),
                        polling.is_some(),
                    )?;
                    // Host counters aggregate ALL child processes of this same
                    // parent; never interpret them as one client's paid CPU.
                    let host_resources_before = host_kernel
                        .as_ref()
                        .map(|budget| budget.resource_sample())
                        .transpose()?;
                    let pool_context = pool
                        .map(|pool| node.enable_local_mempool(pool))
                        .transpose()?;
                    let state = if growth_network {
                        node.growth_head_observation_with_progress(&|_| Ok(()))?
                    } else {
                        node.stats()?
                    };
                    println!(
                        "{}",
                        json!({"event":"listening","address":listener.local_addr()?.to_string(),
                        "state":state,"server_public":server_public,"scope":"public-development-unqualified",
                        "host_process_slot":_host_guard.slot,
                        "host_process_budget_scope":"cooperative-local-service-processes-4",
                        "root_kernel_parent_checked":host_kernel.is_some(),
                        "root_kernel_resources_before":host_resources_before,
                        "initial_paid_cpu_credit_ns":server.mutation_cpu_domain().observe()?.stored_credit_ns,
                        "admission_profile":profile,"admission_profile_digest":hex::encode(resource_profile),
                        "pool_context":pool_context.map(hex::encode),"mining_enabled":mining.is_some(),
                        "peer_polling_enabled":polling.is_some(),"peer_polling_context":polling_context,
                        "confidentiality":false,"identity_authority":false,"public_network_ready":false,"production_activation":false})
                    );
                    std::io::stdout().flush()?;
                    let owner = Arc::new(Mutex::new(node));
                    let stop = Arc::new(AtomicBool::new(false));
                    let observation_context = if request_observation.is_some() {
                        let owner = owner.lock().map_err(|_| "PUBLIC_OWNER")?;
                        Some(json!({"network":hex::encode(owner.settings().network()),
                            "parameters":hex::encode(owner.settings().parameters()),
                            "genesis":hex::encode(owner.settings().genesis()),
                            "task_profile":owner.settings().task_profile(),
                            "admission_profile":profile,
                            "admission_policy_id":hex::encode(resource_profile),
                            "pool_context":pool_context.map(hex::encode)}))
                    } else {
                        None
                    };
                    let (service, mining_result, polling_result, kernel_result) =
                        std::thread::scope(|scope| {
                            // The trusted parent must remain the same and its
                            // aggregate limits must not be widened while serving.
                            let kernel_observer = host_kernel.as_ref().map(|budget| {
                                let stop = stop.clone();
                                scope.spawn(move || -> Result<()> {
                                    while !stop.load(Ordering::Acquire) {
                                        if let Err(error) = budget.verify() {
                                            stop.store(true, Ordering::Release);
                                            eprintln!("PUBLIC_HOST_KERNEL_LIMIT_VIOLATION:{error}");
                                            return Err(error);
                                        }
                                        std::thread::sleep(Duration::from_millis(50));
                                    }
                                    budget.verify()
                                })
                            });
                            let miner = mining.map(|config| {
                                let owner = owner.clone();
                                let stop = stop.clone();
                                scope.spawn(move || {
                                    let result =
                                        run_pool_mining(owner, config, stop.clone(), |event| {
                                            println!("{}", serde_json::to_string(event)?);
                                            std::io::stdout().flush()?;
                                            Ok(())
                                        });
                                    // A finite successful miner limit leaves ingress
                                    // serving retained blocks for peer catch-up. An
                                    // operational failure stops the shared runtime.
                                    if result.is_err() {
                                        stop.store(true, Ordering::Release);
                                    }
                                    result
                                })
                            });
                            let poller = polling.map(|config| {
                                let owner = owner.clone();
                                let stop = stop.clone();
                                scope.spawn(move || {
                                    let result = run_pinned_peer_polling(
                                        owner,
                                        config,
                                        polling_identity,
                                        stop.clone(),
                                        |event| {
                                            println!("{}", serde_json::to_string(event)?);
                                            std::io::stdout().flush()?;
                                            Ok(())
                                        },
                                    );
                                    if result.is_err() {
                                        stop.store(true, Ordering::Release);
                                    }
                                    result
                                })
                            });
                            let service = if let Some(output) = request_observation.as_ref() {
                                ingress::public_v3::serve_public_protected_v3_with_request_observer(
                                    listener,
                                    owner,
                                    lifetime,
                                    stop.clone(),
                                    server,
                                    Arc::new(Mutex::new(
                                        ingress::public_v3::PublicMetrics::default(),
                                    )),
                                    output.observer.clone(),
                                )
                            } else {
                                ingress::public_v3::serve_public_protected_v3(
                                    listener,
                                    owner,
                                    lifetime,
                                    stop.clone(),
                                    server,
                                )
                            };
                            stop.store(true, Ordering::Release);
                            let mining_result = miner.map(|handle| {
                                handle
                                    .join()
                                    .map_err(|_| Error::from("MINING_THREAD"))
                                    .and_then(|result| result)
                            });
                            let polling_result = poller.map(|handle| {
                                handle
                                    .join()
                                    .map_err(|_| Error::from("PEER_POLL_THREAD"))
                                    .and_then(|result| result)
                            });
                            let kernel_result = kernel_observer.map(|handle| {
                                handle
                                    .join()
                                    .map_err(|_| Error::from("PUBLIC_HOST_KERNEL_THREAD"))
                                    .and_then(|result| result)
                            });
                            (service, mining_result, polling_result, kernel_result)
                        });
                    // All scoped workers have stopped before returning any error.
                    // Capture diagnostics before propagating service/miner/poller
                    // failures, without changing their native effects or authority.
                    if let Some(output) = request_observation.as_mut() {
                        output.write_after_join(
                            observation_context.ok_or("REQUEST_OBSERVATION_CONTEXT")?,
                            service.is_ok(),
                            mining_result.as_ref().map(|result| result.is_ok()),
                            polling_result.as_ref().map(|result| result.is_ok()),
                        )?;
                    }
                    let metrics = service?;
                    kernel_result.transpose()?;
                    let mining_report = mining_result.transpose()?;
                    let polling_report = polling_result.transpose()?;
                    // Read after ALL owned workers joined; this remains
                    // aggregate across any other processes under the parent.
                    // Counter rewind is an error, not a falsely qualified CPU
                    // receipt or a reason to roll back committed Native work.
                    let host_resources_after = host_kernel
                        .as_ref()
                        .map(|budget| budget.resource_sample())
                        .transpose()?;
                    let host_kernel_cpu_delta = match (host_resources_before, host_resources_after)
                    {
                        (Some(before), Some(after)) => Some(after.cpu_delta_since(before)?),
                        (None, None) => None,
                        _ => return Err("PUBLIC_HOST_KERNEL_COUNTERS".into()),
                    };
                    return Ok(
                        json!({"result":metrics,"mining":mining_report,"peer_polling":polling_report,
                        "host_kernel_resources_after":host_resources_after,
                        "host_kernel_cpu_delta":host_kernel_cpu_delta,
                        "host_kernel_qualification":false,
                        "public_network_ready":false,"production_activation":false}),
                    );
                }
                let listener = std::net::TcpListener::bind(
                    args.get("--listen")
                        .map(String::as_str)
                        .unwrap_or("127.0.0.1:0"),
                )?;
                if !listener.local_addr()?.ip().is_loopback() {
                    return Err("PUBLIC_V2_NONLOOPBACK_DISABLED".into());
                }
                if args.contains_key("--host-kernel-parent") {
                    return Err("PUBLIC_V2_HOST_KERNEL_UNSUPPORTED".into());
                }
                let policy = public_policy(&args)?;
                println!(
                    "{}",
                    json!({"event":"listening","address":listener.local_addr()?.to_string(),
                    "state":node.stats()?,"server_public":server_public,"scope":"public-development-unqualified",
                    "admission_profile":ingress::public_v2::PROFILE,"admission_profile_digest":hex::encode(policy.id()),
                    "confidentiality":false,"identity_authority":false,"public_network_ready":false,"production_activation":false})
                );
                std::io::stdout().flush()?;
                let metrics = ingress::public_v2::serve_public_protected_v2(
                    listener,
                    node,
                    lifetime,
                    Arc::new(AtomicBool::new(false)),
                    ingress::public_v2::PublicServer::new(identity, policy)?,
                )?;
                return Ok(
                    json!({"result":metrics,"public_network_ready":false,"production_activation":false}),
                );
            }
            let protected = admission_profile(&args)?;
            if !protected
                && (args.contains_key("--admission-bits")
                    || args.contains_key("--admission-ttl-ms"))
            {
                return Err("ADMISSION_PROFILE_REQUIRED".into());
            }
            let admission = if protected {
                Some(ingress::AdmissionPolicy::new(
                    u8::try_from(number(&args, "--admission-bits", 16)?)
                        .map_err(|_| Error::from("ADMISSION_POLICY"))?,
                    Duration::from_millis(number(&args, "--admission-ttl-ms", 2000)?),
                )?)
            } else {
                None
            };
            let address = args
                .get("--listen")
                .map(String::as_str)
                .unwrap_or("127.0.0.1:0");
            let address: std::net::SocketAddr =
                address.parse().map_err(|_| Error::from("LISTEN_ADDRESS"))?;
            let authentication = authenticated_server(&args)?;
            if authentication.is_none() && !address.ip().is_loopback() {
                return Err("DEVELOPMENT_LOOPBACK_ONLY".into());
            }
            let listener = std::net::TcpListener::bind(address)?;
            let server_public = authentication
                .as_ref()
                .map(|value| value.public_key().to_owned());
            println!(
                "{}",
                json!({
                    "event":"listening",
                    "address":listener.local_addr()?.to_string(),
                    "state":node.stats()?,
                    "scope":if authentication.is_some(){"authenticated-development-private"}else{"native-development-loopback"},
                    "server_public":server_public,
                    "admission_profile":if protected {"connection-work-v1"} else {"legacy-development"},
                    "confidentiality":false,
                    "production_activation":false
                })
            );
            std::io::stdout().flush()?;
            let lifetime = Duration::from_secs(number(&args, "--seconds", 30)?);
            let stop = Arc::new(AtomicBool::new(false));
            let metrics = match (authentication, admission) {
                (Some(authentication), Some(policy)) => ingress::serve_authenticated_protected(
                    listener,
                    node,
                    lifetime,
                    stop,
                    authentication,
                    policy,
                )?,
                (None, Some(policy)) => {
                    ingress::serve_protected(listener, node, lifetime, stop, policy)?
                }
                (Some(authentication), None) => {
                    ingress::serve_authenticated(listener, node, lifetime, stop, authentication)?
                }
                (None, None) => ingress::serve(listener, node, lifetime, stop)?,
            };
            serde_json::to_value(metrics)?
        }
        _ => return Err("UNKNOWN_COMMAND".into()),
    };
    Ok(
        json!({"result":value,"clock_scope":if args.contains_key("--logical-now"){"logical-test"}else{"local-wall"},"production_activation":false}),
    )
}
/// Render untrusted diagnostics as one terminal line without changing the
/// underlying error, its typed identity, or any authenticated protocol bytes.
fn cli_error_line(error: &impl std::fmt::Display) -> String {
    let mut line = String::new();
    for character in error.to_string().chars() {
        if character.is_control() {
            line.extend(character.escape_default());
        } else {
            line.push(character);
        }
    }
    line
}

fn main() {
    match run() {
        Ok(value) => {
            let refused = value.get("ok") == Some(&Value::Bool(false));
            println!("{value}");
            // Preserve the authenticated denial as structured stdout while making
            // the command unsuccessful for shell callers and campaign supervisors.
            if refused {
                std::process::exit(2);
            }
        }
        Err(error) => {
            eprintln!("{}", cli_error_line(&error));
            std::process::exit(2);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::{symlink, PermissionsExt};

    #[test]
    fn cli_error_line_escapes_remote_log_and_terminal_controls() {
        let message =
            "REMOTE_TERMINAL:denied\nforged entry\r\t\u{1b}[2J\u{7f}\u{85}\u{9b}31m\u{9d}title";
        let error = Error::from(message);
        let original_kind = error.kind();
        let original_code = error.code();
        assert_eq!(
            cli_error_line(&error),
            r"REMOTE_TERMINAL:denied\nforged entry\r\t\u{1b}[2J\u{7f}\u{85}\u{9b}31m\u{9d}title"
        );
        assert_eq!(error.to_string(), message);
        assert_eq!(error.kind(), original_kind);
        assert_eq!(error.code(), original_code);
    }

    #[test]
    fn cli_error_line_removes_every_c0_del_and_c1_control() {
        let controls = (0..=0x1f).chain(0x7f..=0x9f);
        for codepoint in controls {
            let character = char::from_u32(codepoint).unwrap();
            let message = format!("before{character}after");
            let rendered = cli_error_line(&message);
            assert!(!rendered.chars().any(char::is_control));
            assert!(rendered.starts_with("before\\"));
            assert!(rendered.ends_with("after"));
            assert_ne!(rendered, message);
        }
    }

    #[test]
    fn cli_error_line_preserves_ordinary_unicode_quotes_and_backslashes() {
        let message = r#"拒绝: café é 🦀 'quoted' "double" C:\keys\node.key literal\n"#;
        assert_eq!(cli_error_line(&message), message);
        let error = Error::new(trnm_pon_node::ErrorCode::PublicMutationCpuBudget);
        assert_eq!(cli_error_line(&error), "PUBLIC_MUTATION_CPU_BUDGET");
        assert_eq!(error.to_string(), "PUBLIC_MUTATION_CPU_BUDGET");
        assert!(error.is(trnm_pon_node::ErrorCode::PublicMutationCpuBudget));
    }

    #[test]
    fn public_sync_cannot_use_loopback_proxy_to_avoid_fixed_host_cpu_owner() {
        use trnm_pon_node::host_kernel_parent::{
            require_host_kernel_budget, FIXED_PUBLIC_KERNEL_PARENT,
        };
        let loopback: std::net::SocketAddr = "127.0.0.1:11223".parse().unwrap();
        // This preserved plain-developer profile never claims a public
        // network resource budget or public-network readiness.
        assert!(matches!(sync_host_kernel_owner(loopback, false), Ok(None)));
        let original = require_host_kernel_budget(loopback, Some(FIXED_PUBLIC_KERNEL_PARENT));
        let protected = sync_host_kernel_owner(loopback, true);
        match (protected, original) {
            (Ok(Some(a)), Ok(Some(b))) => {
                a.verify().unwrap();
                b.verify().unwrap();
            }
            (Err(left), Err(right)) => {
                assert_eq!(left.to_string(), right.to_string());
            }
            _ => panic!("public History cannot bypass fixed Host resource owner"),
        }
        // Signed authenticated and public V2/V3 transports are untrusted
        // sources regardless of their loopback destination or caller identity.
        let mut args = BTreeMap::new();
        assert!(!priced_sync_context(&args));
        for profile in [
            ingress::public_v2::PROFILE,
            ingress::public_v3::PROFILE,
            ingress::public_v3::GROWTH_PROFILE,
        ] {
            args.insert("--admission-profile".into(), profile.into());
            assert!(priced_sync_context(&args));
        }
        args.clear();
        for option in ["--auth-secret", "--server-public", "--session-generation"] {
            args.insert(option.into(), "test-selection".into());
            assert!(priced_sync_context(&args));
            args.clear();
        }
    }

    #[test]
    fn pinned_peer_remote_history_must_share_fixed_host_even_with_loopback_listener() {
        let listen: std::net::SocketAddr = "127.0.0.1:44222".parse().unwrap();
        // A genuinely local V3 development listener without a poller keeps
        // the existing original exemption (not a public WAN qualification).
        assert!(matches!(
            pinned_peer_service_host_kernel(listen, None, false),
            Ok(None)
        ));
        let strict = pinned_peer_service_host_kernel(listen, None, true);
        let original = host_public_guard::require_host_kernel_budget(
            listen,
            Some(trnm_pon_node::host_kernel_parent::FIXED_PUBLIC_KERNEL_PARENT),
        );
        match (strict, original) {
            (Ok(Some(a)), Ok(Some(b))) => {
                a.verify().unwrap();
                b.verify().unwrap();
            }
            (Err(a), Err(b)) => assert_eq!(a.to_string(), b.to_string()),
            _ => panic!("pinned peer cannot evade fixed host by local listener"),
        }
        // A configured foreign parent cannot create an alternative allowance;
        // the original fixed-parent validation remains authoritative.
        assert!(pinned_peer_service_host_kernel(
            listen,
            Some("/sys/fs/cgroup/not-the-approved-parent.slice"),
            true
        )
        .is_err());
    }

    #[test]
    fn host_kernel_parent_is_not_silently_accepted_for_other_profiles() {
        let mut opts = BTreeMap::new();
        opts.insert(
            "--host-kernel-parent".into(),
            "/sys/fs/cgroup/system.slice/trnmpondev.slice".into(),
        );
        assert_eq!(
            validate_host_kernel_profile("serve", &opts)
                .unwrap_err()
                .to_string(),
            "PUBLIC_HOST_KERNEL_PROFILE"
        );
        opts.insert("--public-development-network".into(), "true".into());
        opts.insert(
            "--admission-profile".into(),
            ingress::public_v2::PROFILE.into(),
        );
        assert_eq!(
            validate_host_kernel_profile("serve", &opts)
                .unwrap_err()
                .to_string(),
            "PUBLIC_HOST_KERNEL_PROFILE"
        );
        opts.insert(
            "--admission-profile".into(),
            ingress::public_v3::PROFILE.into(),
        );
        assert!(validate_host_kernel_profile("serve", &opts).is_ok());
        assert_eq!(
            validate_host_kernel_profile("head", &opts)
                .unwrap_err()
                .to_string(),
            "PUBLIC_HOST_KERNEL_PROFILE"
        );
    }

    #[test]
    fn request_observation_output_has_a_closed_byte_limit() {
        let mut bytes = BoundedObservationBuffer(Vec::new());
        bytes
            .write_all(&vec![b'x'; MAX_REQUEST_OBSERVATION_OUTPUT_BYTES])
            .unwrap();
        assert_eq!(bytes.0.len(), MAX_REQUEST_OBSERVATION_OUTPUT_BYTES);
        assert!(bytes.write_all(b"\n").is_err());
        assert_eq!(bytes.0.len(), MAX_REQUEST_OBSERVATION_OUTPUT_BYTES);
    }

    #[test]
    fn request_observation_descriptor_refuses_special_permission_bits() {
        let temp = tempfile::tempdir().unwrap();
        let file = File::create(temp.path().join("new-output")).unwrap();
        file.set_permissions(std::fs::Permissions::from_mode(0o600))
            .unwrap();
        assert!(check_request_observation_descriptor(&file).is_ok());
        file.set_permissions(std::fs::Permissions::from_mode(0o4600))
            .unwrap();
        assert!(check_request_observation_descriptor(&file).is_err());
    }

    #[test]
    fn test_authentication_configuration_uses_the_opened_file_identity() {
        let temp = tempfile::tempdir().unwrap();
        let key = temp.path().join("peer.key");
        let seed = "11".repeat(32);
        std::fs::write(&key, format!("{seed}\n")).unwrap();
        std::fs::set_permissions(&key, std::fs::Permissions::from_mode(0o600)).unwrap();
        assert!(secret_identity(key.to_str().unwrap()).is_ok());

        let link = temp.path().join("peer-link.key");
        symlink(&key, &link).unwrap();
        assert_eq!(
            secret_identity(link.to_str().unwrap())
                .err()
                .unwrap()
                .to_string(),
            "AUTH_SECRET_FILE"
        );

        let public = temp.path().join("public.key");
        std::fs::write(&public, format!("{seed}\n")).unwrap();
        std::fs::set_permissions(&public, std::fs::Permissions::from_mode(0o644)).unwrap();
        assert_eq!(
            secret_identity(public.to_str().unwrap())
                .err()
                .unwrap()
                .to_string(),
            "AUTH_SECRET_FILE"
        );

        let hard = temp.path().join("hard.key");
        std::fs::hard_link(&key, &hard).unwrap();
        assert_eq!(
            secret_identity(hard.to_str().unwrap())
                .err()
                .unwrap()
                .to_string(),
            "AUTH_SECRET_FILE"
        );

        let roster = temp.path().join("peers.json");
        let peer = ingress::DevelopmentIdentity::from_secret_hex(&"22".repeat(32)).unwrap();
        std::fs::write(
            &roster,
            serde_json::to_vec(&vec![peer.public_key().to_owned()]).unwrap(),
        )
        .unwrap();
        std::fs::set_permissions(&roster, std::fs::Permissions::from_mode(0o644)).unwrap();
        assert_eq!(peer_roster(roster.to_str().unwrap()).unwrap().len(), 1);
        let writable_roster = temp.path().join("writable-peers.json");
        std::fs::write(
            &writable_roster,
            serde_json::to_vec(&vec![peer.public_key().to_owned()]).unwrap(),
        )
        .unwrap();
        std::fs::set_permissions(&writable_roster, std::fs::Permissions::from_mode(0o666)).unwrap();
        assert_eq!(
            peer_roster(writable_roster.to_str().unwrap())
                .unwrap_err()
                .to_string(),
            "AUTH_ROSTER_FILE"
        );
        let roster_link = temp.path().join("peers-link.json");
        symlink(&roster, &roster_link).unwrap();
        assert_eq!(
            peer_roster(roster_link.to_str().unwrap())
                .unwrap_err()
                .to_string(),
            "AUTH_ROSTER_FILE"
        );
    }
}

#[cfg(test)]
#[path = "operator_task_cli_tests.rs"]
mod operator_task_cli_tests;
