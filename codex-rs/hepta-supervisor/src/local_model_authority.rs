//! Root-owned ordinary model issuer. Enrollment follows the actual Linux peer
//! and root-protected Fleet main cgroup, never a request's asserted identity.
//! This key signs only kernel final-use grants, not evaluation/acceptance.

use std::collections::BTreeSet;
use std::fs::File;
use std::io::Read;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use anyhow::Context;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::MODEL_ISSUER_MAX_REQUEST_BYTES;
use codex_hepta_contracts::MODEL_ISSUER_MAX_RESPONSE_BYTES;
use codex_hepta_contracts::MODEL_ISSUER_OPERATION;
use codex_hepta_contracts::MODEL_ISSUER_SCHEMA_VERSION;
use codex_hepta_contracts::ModelIssuerRequest;
use codex_hepta_contracts::ModelIssuerResponse;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_fleet::FleetExecutionVerifier;
use codex_hepta_fleet::FleetProcessBinding;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::UnixListener;
use tokio::net::UnixStream;
use zeroize::Zeroizing;

#[path = "local_model_executable.rs"]
mod executable;
#[path = "local_model_authority_store.rs"]
mod store;
use executable::ExecutableCache;
use executable::MAX_ENROLLED_EXECUTABLES;
use store::ProtectedClock;
use store::ProtectedFrontier;
use store::protected_directory;
use store::read_protected;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Config {
    schema_version: u32,
    signer_id: String,
    key_file: PathBuf,
    issuer_socket: PathBuf,
    process_identity_file: PathBuf,
    socket_gid: u32,
    workload_uid: u32,
    state_directory: PathBuf,
    trust_directory: PathBuf,
    revocations_file: PathBuf,
    cgroup_root: PathBuf,
    fleet_database: PathBuf,
    allowed_subject_ids: BTreeSet<String>,
    allowed_executable_sha256: BTreeSet<String>,
    allowed_executable_paths: BTreeSet<PathBuf>,
    grant_lifetime_ms: u64,
    request_timeout_ms: u64,
}

impl Config {
    fn validate(&self) -> anyhow::Result<()> {
        anyhow::ensure!(
            self.schema_version == 1 && self.workload_uid != 0,
            "invalid ordinary model authority schema or workload UID"
        );
        for path in [
            &self.key_file,
            &self.issuer_socket,
            &self.process_identity_file,
            &self.state_directory,
            &self.trust_directory,
            &self.revocations_file,
            &self.cgroup_root,
            &self.fleet_database,
        ]
        .into_iter()
        .chain(&self.allowed_executable_paths)
        {
            anyhow::ensure!(
                path.is_absolute()
                    && !path
                        .components()
                        .any(|part| matches!(part, std::path::Component::ParentDir)),
                "authority paths must be absolute and normalized"
            );
        }
        anyhow::ensure!(
            !self.trust_directory.starts_with(&self.state_directory)
                && !self.state_directory.starts_with(&self.trust_directory),
            "external trust and replaceable authority state must be separate"
        );
        anyhow::ensure!(
            self.cgroup_root.starts_with("/sys/fs/cgroup"),
            "Fleet cgroup must be in cgroup v2"
        );
        anyhow::ensure!(
            (1..=60_000).contains(&self.grant_lifetime_ms)
                && (1..=5_000).contains(&self.request_timeout_ms),
            "invalid grant or request lifetime"
        );
        anyhow::ensure!(
            !self.allowed_subject_ids.is_empty()
                && (1..=MAX_ENROLLED_EXECUTABLES).contains(&self.allowed_executable_sha256.len())
                && (1..=MAX_ENROLLED_EXECUTABLES).contains(&self.allowed_executable_paths.len()),
            "model issuer enrollment is empty or exceeds the immutable executable bound"
        );
        for subject in &self.allowed_subject_ids {
            anyhow::ensure!(
                uuid::Uuid::parse_str(subject)?.to_string() == *subject,
                "noncanonical enrolled AgentId"
            );
        }
        for digest in &self.allowed_executable_sha256 {
            anyhow::ensure!(
                digest.len() == 64
                    && digest != &"0".repeat(64)
                    && digest
                        .bytes()
                        .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte)),
                "invalid enrolled executable digest"
            );
        }
        Ok(())
    }

    fn admitted_subject(&self, uid: u32, cgroup: &str) -> anyhow::Result<String> {
        anyhow::ensure!(uid == self.workload_uid, "unenrolled model caller UID");
        let root = self.cgroup_root.strip_prefix("/sys/fs/cgroup")?;
        let prefix = format!("0::/{}/agent-", root.display());
        let suffix = cgroup
            .strip_prefix(&prefix)
            .context("caller is outside the Fleet cgroup")?;
        let (subject, execution) = suffix
            .split_once('/')
            .context("caller has no execution cgroup")?;
        let execution = execution
            .strip_prefix("main-")
            .context("only main executions may request model grants")?;
        anyhow::ensure!(
            uuid::Uuid::parse_str(execution)?.to_string() == execution
                && self.allowed_subject_ids.contains(subject),
            "unenrolled model execution"
        );
        Ok(subject.to_string())
    }
}

#[derive(Eq, PartialEq)]
struct Peer {
    pid: u32,
    start_ticks: u64,
    subject: String,
    cgroup: String,
    cgroup_device: u64,
    cgroup_inode: u64,
    executable_sha256: String,
}

fn read_proc(pid: u32, name: &str) -> anyhow::Result<String> {
    let mut value = String::new();
    Read::take(File::open(format!("/proc/{pid}/{name}"))?, 65_537).read_to_string(&mut value)?;
    anyhow::ensure!(
        value.len() <= 65_536,
        "peer process metadata exceeds its bound"
    );
    Ok(value.trim_end().to_string())
}

async fn capture_peer(
    config: &Config,
    verifier: &FleetExecutionVerifier,
    executables: &ExecutableCache,
    stream: &UnixStream,
) -> anyhow::Result<Peer> {
    let credentials = stream.peer_cred()?;
    let pid = credentials
        .pid()
        .and_then(|value| u32::try_from(value).ok())
        .context("model caller omitted Linux PID")?;
    anyhow::ensure!(
        std::fs::metadata(format!("/proc/{pid}/stat"))?.uid() == 0,
        "model caller permits same-UID process inspection or injection"
    );
    let cgroup = read_proc(pid, "cgroup")?;
    let subject = config.admitted_subject(credentials.uid(), &cgroup)?;
    let relative = cgroup
        .strip_prefix("0::/")
        .context("expected one cgroup v2 process membership")?;
    let directory = Path::new("/sys/fs/cgroup").join(relative);
    protected_directory(&directory)?;
    let metadata = std::fs::symlink_metadata(&directory)?;
    let members = std::fs::read_to_string(directory.join("cgroup.procs"))?;
    anyhow::ensure!(
        members.lines().any(|line| line.parse::<u32>() == Ok(pid)),
        "caller left its protected execution cgroup"
    );
    let stat = read_proc(pid, "stat")?;
    let (_, rest) = stat
        .rsplit_once(") ")
        .context("invalid peer process stat")?;
    let start_ticks = rest
        .split_whitespace()
        .nth(19)
        .context("peer start identity is missing")?
        .parse()?;
    let executable = File::open(format!("/proc/{pid}/exe"))?;
    let executable_sha256 = executables.verify(&executable)?;
    anyhow::ensure!(
        config
            .allowed_executable_sha256
            .contains(&executable_sha256),
        "unenrolled model caller executable"
    );
    let execution = directory
        .file_name()
        .and_then(|value| value.to_str())
        .and_then(|value| value.strip_prefix("main-"))
        .context("missing Fleet main execution identity")?;
    loop {
        match verifier
            .verify_bound_local_process(execution, &subject, pid)
            .await?
        {
            FleetProcessBinding::Bound(context) => {
                anyhow::ensure!(
                    context.containment == relative,
                    "model caller containment differs from its Fleet hold"
                );
                break;
            }
            FleetProcessBinding::PendingBinding => {
                // Spawn initialization may precede the parent's PID commit.
                // The enclosing request deadline bounds this wait; admission
                // requires the same existing owner record to become Bound.
                tokio::time::sleep(Duration::from_millis(20)).await;
            }
        }
    }
    Ok(Peer {
        pid,
        start_ticks,
        subject,
        cgroup,
        cgroup_device: metadata.dev(),
        cgroup_inode: metadata.ino(),
        executable_sha256,
    })
}

struct Issuer {
    config: Config,
    signer: SigningKey,
    clock: Arc<dyn AuthorityClock>,
    authority: FinalUseAuthority,
    verifier: FleetExecutionVerifier,
    executables: ExecutableCache,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ClientTrust {
    signer_id: String,
    verifying_key: [u8; 32],
    subject_id: String,
    frontier: FinalUseFrontier,
    revocations: FinalUseRevocations,
}

#[derive(Deserialize)]
#[serde(untagged)]
enum Exchange {
    Grant(ModelIssuerRequest),
    Trust(codex_hepta_contracts::ModelTrustRequest),
}

impl Issuer {
    fn client_trust(
        &self,
        request: codex_hepta_contracts::ModelTrustRequest,
        peer: &Peer,
    ) -> anyhow::Result<codex_hepta_contracts::ModelTrustResponse> {
        use codex_hepta_contracts::MODEL_TRUST_CAS;
        use codex_hepta_contracts::MODEL_TRUST_LOAD;
        anyhow::ensure!(
            request.schema_version == 1 && request.signer_id == self.config.signer_id,
            "invalid client trust owner"
        );
        let head = self.synchronize_head()?;
        let path = self
            .config
            .trust_directory
            .join(format!("client-{}.json", peer.subject));
        let mut state: ClientTrust = if path.try_exists()? {
            serde_json::from_slice(&read_protected(&path, 128 * 1024, true)?)?
        } else {
            anyhow::ensure!(
                request.operation == MODEL_TRUST_LOAD
                    && request.expected.is_none()
                    && request.next.is_none(),
                "client trust must be enrolled before CAS"
            );
            let state = ClientTrust {
                signer_id: self.config.signer_id.clone(),
                verifying_key: self.signer.verifying_key().to_bytes(),
                subject_id: peer.subject.clone(),
                frontier: FinalUseFrontier::for_initial_head(&head)?,
                revocations: head.clone(),
            };
            store::write_atomic(&path, &serde_json::to_vec(&state)?)?;
            state
        };
        anyhow::ensure!(
            state.signer_id == self.config.signer_id
                && state.verifying_key == self.signer.verifying_key().to_bytes()
                && state.subject_id == peer.subject,
            "client trust enrollment changed"
        );
        match request.operation.as_str() {
            MODEL_TRUST_LOAD => anyhow::ensure!(
                request.expected.is_none() && request.next.is_none(),
                "load cannot mutate client trust"
            ),
            MODEL_TRUST_CAS => {
                let expected = request.expected.context("trust CAS omitted predecessor")?;
                let next = request.next.context("trust CAS omitted successor")?;
                anyhow::ensure!(
                    expected == state.frontier && next.state_sha256 != [0; 32],
                    "trust CAS conflict"
                );
                anyhow::ensure!(
                    next.authority_epoch >= expected.authority_epoch
                        && next.authority_epoch <= head.authority_epoch,
                    "invalid trust epoch transition"
                );
                if (next.authority_epoch, next.revocation_revision)
                    == (
                        state.revocations.authority_epoch,
                        state.revocations.revision,
                    )
                {
                    // Ordinary nonce mutation keeps the already pinned revocation head.
                } else {
                    anyhow::ensure!(
                        (next.authority_epoch, next.revocation_revision)
                            == (head.authority_epoch, head.revision)
                            && (next.authority_epoch > expected.authority_epoch
                                || next.revocation_revision > expected.revocation_revision),
                        "trust successor does not match the root revocation head"
                    );
                    state.revocations = head;
                }
                state.frontier = next;
                store::write_atomic(&path, &serde_json::to_vec(&state)?)?;
            }
            _ => anyhow::bail!("unsupported ordinary trust operation"),
        }
        Ok(codex_hepta_contracts::ModelTrustResponse {
            schema_version: 1,
            frontier: state.frontier,
            revocations: state.revocations,
            now_unix_ms: self.clock.now_unix_ms()?,
        })
    }

    fn synchronize_head(&self) -> anyhow::Result<FinalUseRevocations> {
        let next: FinalUseRevocations = serde_json::from_slice(&read_protected(
            &self.config.revocations_file,
            64 * 1024,
            true,
        )?)?;
        if self.authority.revocation_head()? != next {
            self.authority.update_revocations(next)?;
        }
        Ok(self.authority.revocation_head()?)
    }

    fn sign(
        config: &Config,
        signer: &SigningKey,
        clock: &dyn AuthorityClock,
        request: ModelIssuerRequest,
        peer: &Peer,
        head: &FinalUseRevocations,
    ) -> anyhow::Result<SignedFinalUseGrant> {
        anyhow::ensure!(
            request.schema_version == MODEL_ISSUER_SCHEMA_VERSION
                && request.operation == MODEL_ISSUER_OPERATION,
            "unsupported ordinary model operation"
        );
        anyhow::ensure!(
            request.binding.subject_id == peer.subject,
            "model binding does not match enrolled peer"
        );
        let connection = request
            .binding
            .destination_id
            .strip_prefix("codex-app-server:")
            .context("model destination is not an App Server connection")?
            .parse::<u64>()?;
        anyhow::ensure!(
            connection > 0
                && request.binding.destination_id == format!("codex-app-server:{connection}"),
            "model destination does not identify a canonical connection"
        );
        let now = clock.now_unix_ms()?;
        let mut nonce = [0_u8; 32];
        nonce[..16].copy_from_slice(uuid::Uuid::new_v4().as_bytes());
        nonce[16..].copy_from_slice(uuid::Uuid::new_v4().as_bytes());
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: config.signer_id.clone(),
            authority_epoch: head.authority_epoch,
            grant_id: format!("model-{}", uuid::Uuid::new_v4()),
            nonce,
            binding: request.binding,
            not_before_unix_ms: now,
            expires_at_unix_ms: now
                .checked_add(config.grant_lifetime_ms)
                .context("model grant time overflow")?,
        };
        let signature = signer.sign(&grant.signing_bytes()?).to_bytes().to_vec();
        Ok(SignedFinalUseGrant { grant, signature })
    }

    async fn exchange(&self, mut stream: UnixStream) -> anyhow::Result<()> {
        let peer = capture_peer(&self.config, &self.verifier, &self.executables, &stream).await?;
        let mut length = [0_u8; 4];
        stream.read_exact(&mut length).await?;
        let length = usize::try_from(u32::from_be_bytes(length))?;
        anyhow::ensure!(
            (1..=MODEL_ISSUER_MAX_REQUEST_BYTES).contains(&length),
            "model issuer request exceeds its bound"
        );
        let mut bytes = vec![0_u8; length];
        stream.read_exact(&mut bytes).await?;
        let request: Exchange = serde_json::from_slice(&bytes)?;
        if let Exchange::Trust(request) = request {
            let response = self.client_trust(request, &peer)?;
            anyhow::ensure!(
                capture_peer(&self.config, &self.verifier, &self.executables, &stream).await?
                    == peer,
                "model caller identity changed during trust mutation"
            );
            let bytes = serde_json::to_vec(&response)?;
            anyhow::ensure!(
                bytes.len() <= MODEL_ISSUER_MAX_RESPONSE_BYTES,
                "trust response exceeds its bound"
            );
            stream
                .write_all(&u32::try_from(bytes.len())?.to_be_bytes())
                .await?;
            stream.write_all(&bytes).await?;
            stream.flush().await?;
            return Ok(());
        }
        let Exchange::Grant(request) = request else {
            anyhow::bail!("invalid model exchange")
        };
        let head = self.synchronize_head()?;
        let outcome = Self::sign(
            &self.config,
            &self.signer,
            self.clock.as_ref(),
            request,
            &peer,
            &head,
        );
        anyhow::ensure!(
            capture_peer(&self.config, &self.verifier, &self.executables, &stream).await? == peer,
            "model caller identity changed during issuance"
        );
        let (grant, denial_reason) = match outcome {
            Ok(grant) => (Some(grant), None),
            Err(_) => (
                None,
                Some("ordinary model binding is not authorized".to_string()),
            ),
        };
        let bytes = serde_json::to_vec(&ModelIssuerResponse {
            schema_version: MODEL_ISSUER_SCHEMA_VERSION,
            revocations: head,
            grant,
            denial_reason,
        })?;
        anyhow::ensure!(
            bytes.len() <= MODEL_ISSUER_MAX_RESPONSE_BYTES,
            "model issuer response exceeds its bound"
        );
        stream
            .write_all(&u32::try_from(bytes.len())?.to_be_bytes())
            .await?;
        stream.write_all(&bytes).await?;
        stream.flush().await?;
        Ok(())
    }
}

pub async fn run_local_model_authority(config_path: &Path) -> anyhow::Result<()> {
    anyhow::ensure!(
        rustix::process::geteuid().as_raw() == 0,
        "ordinary model issuer must run as root"
    );
    let config: Config = serde_json::from_slice(&read_protected(config_path, 64 * 1024, true)?)?;
    config.validate()?;
    // Full-file hashing is a startup obligation, before any authority endpoint
    // becomes reachable. RPCs retain exact inode and protected path checks.
    let executables = ExecutableCache::prewarm(
        &config.allowed_executable_paths,
        &config.allowed_executable_sha256,
    )?;
    protected_directory(&config.state_directory)?;
    protected_directory(&config.trust_directory)?;
    protected_directory(&config.cgroup_root)?;
    let verifier = FleetExecutionVerifier::open(&config.fleet_database).await?;
    let seed = Zeroizing::new(read_protected(&config.key_file, 32, true)?);
    let seed_bytes: Zeroizing<[u8; 32]> = Zeroizing::new(
        seed.as_slice()
            .try_into()
            .context("model issuer seed must be 32 bytes")?,
    );
    let signer = SigningKey::from_bytes(&seed_bytes);
    let head: FinalUseRevocations =
        serde_json::from_slice(&read_protected(&config.revocations_file, 64 * 1024, true)?)?;
    let empty_state = std::fs::read_dir(&config.state_directory)?.next().is_none();
    let frontier = Arc::new(ProtectedFrontier::open(
        &config.trust_directory,
        FinalUseFrontier::for_initial_head(&head)?,
        empty_state,
    )?);
    let clock = Arc::new(ProtectedClock::open(
        config.trust_directory.join("clock-floor"),
    )?);
    let authority = FinalUseAuthority::open_state_dir_with_recovered_trust(
        &config.state_directory,
        config.signer_id.clone(),
        signer.verifying_key().to_bytes(),
        head,
        clock.clone(),
        frontier,
    )?;
    let parent = config
        .issuer_socket
        .parent()
        .context("issuer socket has no parent")?;
    protected_directory(parent)?;
    if config.issuer_socket.try_exists()? {
        use std::os::unix::fs::FileTypeExt;
        let metadata = std::fs::symlink_metadata(&config.issuer_socket)?;
        anyhow::ensure!(
            metadata.file_type().is_socket() && metadata.uid() == 0,
            "unexpected issuer socket identity"
        );
        anyhow::ensure!(
            std::os::unix::net::UnixStream::connect(&config.issuer_socket).is_err(),
            "model issuer already active"
        );
        std::fs::remove_file(&config.issuer_socket)?;
    }
    let listener = UnixListener::bind(&config.issuer_socket)?;
    std::fs::set_permissions(
        &config.issuer_socket,
        std::fs::Permissions::from_mode(0o660),
    )?;
    std::os::unix::fs::chown(&config.issuer_socket, Some(0), Some(config.socket_gid))?;
    let pid = std::process::id();
    let stat = read_proc(pid, "stat")?;
    let (_, fields) = stat
        .rsplit_once(") ")
        .context("invalid issuer process stat")?;
    let start_time_ticks = fields
        .split_whitespace()
        .nth(19)
        .context("issuer start identity missing")?
        .parse()?;
    let executable_sha256 = format!("{:x}", Sha256::digest(std::fs::read("/proc/self/exe")?));
    let identity = codex_hepta_contracts::ModelIssuerProcessIdentity {
        schema_version: 1,
        pid,
        start_time_ticks,
        executable_sha256,
        cgroup_sha256: format!("{:x}", Sha256::digest(read_proc(pid, "cgroup")?.as_bytes())),
        boot_id_sha256: format!(
            "{:x}",
            Sha256::digest(
                std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?
                    .trim_end()
                    .as_bytes()
            )
        ),
    };
    store::publish_identity(
        &config.process_identity_file,
        &serde_json::to_vec(&identity)?,
        config.socket_gid,
    )?;
    let timeout = Duration::from_millis(config.request_timeout_ms);
    let issuer = Issuer {
        config,
        signer,
        clock,
        authority,
        verifier,
        executables,
    };
    loop {
        tokio::select! {
            result = listener.accept() => {
                let (stream, _) = result?;
                // Serial and bounded: no caller can create unbounded issuer tasks.
                // A disconnect or denial never changes qualification state.
                if tokio::time::timeout(timeout, issuer.exchange(stream)).await.is_err() {
                    eprintln!("ordinary model issuer exchange timed out");
                }
            }
            signal = tokio::signal::ctrl_c() => { signal?; return Ok(()); }
        }
    }
}

#[cfg(test)]
#[path = "local_model_authority_tests.rs"]
mod tests;
