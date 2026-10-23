//! Actual resident growth service and the sealed ordinary-client adapter.
//! This is a source-pinned integration test, not a fixture executable or a
//! throughput/independent-operator/model-installation qualification.
use super::super::AgentdProviderEffectAdapter;
use super::super::PonLocalProfile;
use super::super::PonLocalProviderEffectAdapter;
use super::super::pon_executable::PinnedExecutable;
use super::super::pon_growth::Context;
use super::super::pon_remote::Transport;
use super::CredentialPin;
use super::Outcome;
use super::read_bounded;
use super::run;
use codex_hepta_agent_protocol::AutomationEffectTaskAcceptanceV1;
use codex_hepta_agent_protocol::ExpectedAutomationTaskAcceptanceV1;
use codex_hepta_contracts::ProviderEffectDispatch;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::ProviderEffectLookup;
use codex_hepta_contracts::Sha256Digest;
use ed25519_dalek::SigningKey;
use serde_json::Value;
use std::fs;
use std::io;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;
use tokio::io::AsyncReadExt;

type TestResult = Result<(), Box<dyn std::error::Error>>;
const NAMESPACE: &str = "hepta-growth-resident-pair-v1";
const PROFILE: &str = "public-protected-growth-development-v1";
const OUTPUT_LIMIT: usize = 64 * 1024;

fn text(value: &Value, field: &str) -> io::Result<String> {
    value[field]
        .as_str()
        .map(str::to_owned)
        .ok_or_else(|| io::Error::other(format!("missing native field {field}")))
}

struct Chain {
    source: String,
    binary: PathBuf,
    digest: Sha256Digest,
    genesis_time: u64,
}
impl Chain {
    fn exact() -> Result<Self, Box<dyn std::error::Error>> {
        let source = std::env::var("HEPTA_PON_CHAIN_SOURCE")?;
        if source.len() != 40
            || !source
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        {
            return Err(io::Error::other("exact Chain source identity required").into());
        }
        let binary = PathBuf::from(std::env::var("HEPTA_PON_CHAIN_BINARY")?).canonicalize()?;
        let digest = Sha256Digest::parse(std::env::var("HEPTA_PON_CHAIN_SHA256")?)
            .map_err(io::Error::other)?;
        if Sha256Digest::for_bytes(&fs::read(&binary)?) != digest {
            return Err(io::Error::other("exact Chain binary hash mismatch").into());
        }
        let genesis_time = SystemTime::now()
            .duration_since(UNIX_EPOCH)?
            .as_secs()
            .checked_sub(3600)
            .ok_or_else(|| io::Error::other("fixture clock"))?;
        Ok(Self {
            source,
            binary,
            digest,
            genesis_time,
        })
    }

    fn local_command(&self, operation: &str, store: &Path, executable: &Path) -> Command {
        let mut command = Command::new(executable);
        command
            .arg(format!("growth-{operation}"))
            .arg("--development")
            .arg("--store")
            .arg(store)
            .arg("--growth-namespace")
            .arg(NAMESPACE)
            .arg("--genesis-time")
            .arg(self.genesis_time.to_string());
        command
    }

    async fn call(&self, operation: &str, store: &Path, args: &[String]) -> io::Result<Value> {
        let deadline = Instant::now() + Duration::from_secs(30);
        let executable = PinnedExecutable::prepare(&self.binary, self.digest.as_str(), deadline)?;
        let mut command = self.local_command(operation, store, executable.path());
        command.args(args);
        let Outcome::Complete(bytes) = run(command, b"", deadline, OUTPUT_LIMIT).await else {
            return Err(io::Error::other(format!(
                "native growth {operation} did not complete"
            )));
        };
        serde_json::from_slice(&bytes).map_err(io::Error::other)
    }

    async fn packet(&self, store: &Path, output: &Path, timestamp: u64) -> io::Result<Vec<u8>> {
        self.call(
            "mine",
            store,
            &[
                "--timestamp".into(),
                timestamp.to_string(),
                "--miner".into(),
                "ab".repeat(32),
                "--output".into(),
                output.to_string_lossy().into_owned(),
            ],
        )
        .await?;
        let bytes = fs::read(output)?;
        if bytes.len() > 1024 * 1024 || !bytes.starts_with(b"PNP2") {
            return Err(io::Error::other("native growth packet dimensions/profile"));
        }
        Ok(bytes)
    }

    fn adapter(
        &self,
        listening: &Value,
        context: &Value,
        credential: CredentialPin,
    ) -> io::Result<PonLocalProviderEffectAdapter> {
        Ok(PonLocalProviderEffectAdapter {
            binary: self.binary.clone(),
            binary_sha256: self.digest.clone(),
            store: PathBuf::new(),
            genesis_time: self.genesis_time,
            profile: PonLocalProfile::GrowthRemote(Transport {
                context: Context {
                    namespace: NAMESPACE.into(),
                    network: text(context, "network")?,
                    parameters: text(context, "parameters")?,
                    genesis: text(context, "genesis")?,
                },
                peer: text(listening, "address")?
                    .parse()
                    .map_err(io::Error::other)?,
                server_public: text(listening, "server_public")?,
                resource_profile: text(listening, "admission_profile_digest")?,
                admission_bits: 8,
                admission_ttl_ms: 2000,
                credential,
            }),
            min_confirmation_depth: 1,
            min_confirmation_work_depth_hex: format!("{}02", "00".repeat(63)),
            timeout: Duration::from_secs(30),
        })
    }

    async fn assert_cold_observer_locked(&self, store: &Path, packet: &Path) -> io::Result<()> {
        let deadline = Instant::now() + Duration::from_secs(30);
        let executable = PinnedExecutable::prepare(&self.binary, self.digest.as_str(), deadline)?;
        let mut command = self.local_command("packet-status", store, executable.path());
        command
            .arg("--packet")
            .arg(packet)
            .env_clear()
            .env("LC_ALL", "C")
            .env("TZ", "UTC");
        let mut child = tokio::process::Command::from(command)
            .kill_on_drop(true)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| io::Error::other("cold stdout"))?;
        let stderr = child
            .stderr
            .take()
            .ok_or_else(|| io::Error::other("cold stderr"))?;
        let (out, err, status) =
            tokio::time::timeout_at(tokio::time::Instant::from_std(deadline), async {
                tokio::try_join!(
                    read_bounded(stdout, OUTPUT_LIMIT),
                    read_bounded(stderr, OUTPUT_LIMIT),
                    child.wait()
                )
            })
            .await
            .map_err(io::Error::other)??;
        assert_eq!(status.code(), Some(2));
        assert!(out.is_empty());
        assert!(String::from_utf8_lossy(&err).contains("WRITER_BUSY"));
        Ok(())
    }
}

async fn fixture(binary: &Path, digest: &Sha256Digest, args: &[String]) -> io::Result<Value> {
    let deadline = Instant::now() + Duration::from_secs(30);
    let executable = PinnedExecutable::prepare(binary, digest.as_str(), deadline)?;
    let mut command = Command::new(executable.path());
    command.args(args);
    let Outcome::Complete(bytes) = run(command, b"", deadline, OUTPUT_LIMIT).await else {
        return Err(io::Error::other(
            "native growth task fixture did not complete",
        ));
    };
    serde_json::from_slice(&bytes).map_err(io::Error::other)
}

fn secret(path: &Path, seed: u8) -> io::Result<([u8; 32], Sha256Digest)> {
    let bytes = format!("{seed:02x}").repeat(32).into_bytes();
    fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)?
        .write_all(&bytes)?;
    Ok((
        SigningKey::from_bytes(&[seed; 32])
            .verifying_key()
            .to_bytes(),
        Sha256Digest::for_bytes(&bytes),
    ))
}

struct Resident {
    child: tokio::process::Child,
    _executable: PinnedExecutable,
    stdout: Option<tokio::io::BufReader<tokio::process::ChildStdout>>,
    stderr: Option<tokio::process::ChildStderr>,
    finish_deadline: Instant,
    listening: Value,
}
impl Resident {
    async fn start(
        chain: &Chain,
        store: &Path,
        secret: &Path,
        address: &str,
        seconds: u64,
    ) -> io::Result<Self> {
        let startup = Instant::now() + Duration::from_secs(30);
        let executable = PinnedExecutable::prepare(&chain.binary, chain.digest.as_str(), startup)?;
        let mut command = Command::new(executable.path());
        command
            .args([
                "serve",
                "--development",
                "--public-development-network",
                "--state-backend",
                "permanent-account-growth-native-v2",
                "--admission-profile",
                PROFILE,
                "--growth-namespace",
                NAMESPACE,
                "--admission-bits",
                "8",
                "--admission-ttl-ms",
                "2000",
            ])
            .arg("--genesis-time")
            .arg(chain.genesis_time.to_string())
            .arg("--store")
            .arg(store)
            .arg("--auth-secret")
            .arg(secret)
            .arg("--listen")
            .arg(address)
            .arg("--seconds")
            .arg(seconds.to_string())
            .env_clear()
            .env("LC_ALL", "C")
            .env("TZ", "UTC");
        let mut child = tokio::process::Command::from(command)
            .kill_on_drop(true)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| io::Error::other("resident stdout"))?;
        let stderr = child
            .stderr
            .take()
            .ok_or_else(|| io::Error::other("resident stderr"))?;
        let mut resident = Self {
            child,
            _executable: executable,
            stdout: Some(tokio::io::BufReader::new(stdout)),
            stderr: Some(stderr),
            finish_deadline: startup + Duration::from_secs(seconds + 10),
            listening: Value::Null,
        };
        let first_line = tokio::time::timeout_at(tokio::time::Instant::from_std(startup), async {
            let stream = resident
                .stdout
                .as_mut()
                .ok_or_else(|| io::Error::other("resident stdout missing"))?;
            let mut bytes = Vec::new();
            loop {
                let mut byte = [0_u8; 1];
                if stream.read(&mut byte).await? == 0 {
                    return Err(io::Error::other("resident exited before listening"));
                }
                bytes.push(byte[0]);
                if bytes.len() > OUTPUT_LIMIT {
                    return Err(io::Error::other("resident first-line bound"));
                }
                if byte[0] == b'\n' {
                    return Ok(bytes);
                }
            }
        })
        .await;
        let line = match first_line {
            Ok(Ok(line)) => line,
            failure => {
                let _ = resident.child.start_kill();
                let stderr = resident
                    .stderr
                    .take()
                    .ok_or_else(|| io::Error::other("resident stderr missing"))?;
                let cleanup = tokio::time::timeout(Duration::from_millis(500), async {
                    tokio::try_join!(read_bounded(stderr, OUTPUT_LIMIT), resident.child.wait())
                })
                .await;
                let error = match cleanup {
                    Ok(Ok((bytes, _))) => String::from_utf8_lossy(&bytes).into_owned(),
                    _ => "startup child cleanup incomplete".into(),
                };
                return Err(io::Error::other(format!(
                    "resident startup {failure:?}: {error}"
                )));
            }
        };
        resident.listening = serde_json::from_slice(&line).map_err(io::Error::other)?;
        assert_eq!(resident.listening["event"], "listening");
        assert_eq!(resident.listening["admission_profile"], PROFILE);
        assert_eq!(resident.listening["initial_paid_cpu_credit_ns"], 0);
        assert_eq!(resident.listening["production_activation"], false);
        Ok(resident)
    }

    async fn finish(mut self) -> io::Result<Value> {
        let stdout = self
            .stdout
            .take()
            .ok_or_else(|| io::Error::other("resident stdout missing"))?;
        let stderr = self
            .stderr
            .take()
            .ok_or_else(|| io::Error::other("resident stderr missing"))?;
        // Normal timer shutdown, worker join and original epoch settlement are
        // required. Kill-on-drop is error cleanup only, never restart evidence.
        let (out, err, status) = tokio::time::timeout_at(
            tokio::time::Instant::from_std(self.finish_deadline),
            async {
                tokio::try_join!(
                    read_bounded(stdout, OUTPUT_LIMIT),
                    read_bounded(stderr, OUTPUT_LIMIT),
                    self.child.wait()
                )
            },
        )
        .await
        .map_err(io::Error::other)??;
        if !status.success() {
            return Err(io::Error::other(format!(
                "resident failed: {}",
                String::from_utf8_lossy(&err)
            )));
        }
        let value: Value = serde_json::from_slice(&out).map_err(io::Error::other)?;
        assert_eq!(value["result"]["mutation_cpu_in_flight_after_shutdown"], 0);
        assert_eq!(
            value["result"]["paid_body_reserved_bytes_after_shutdown"],
            0
        );
        assert_eq!(value["result"]["output_reserved_bytes_after_shutdown"], 0);
        Ok(value)
    }
}

fn intent(operation: &str, packet: &[u8]) -> io::Result<ProviderEffectIntent> {
    let key = ProviderEffectKey::for_operation("pon-growth-resident-pair", NAMESPACE, operation)
        .map_err(|error| io::Error::other(format!("{error:?}")))?;
    Ok(ProviderEffectIntent::new(
        key,
        Sha256Digest::for_bytes(packet),
    ))
}
async fn dispatch(
    adapter: &PonLocalProviderEffectAdapter,
    effect: &ProviderEffectIntent,
    packet: &[u8],
) -> io::Result<ProviderEffectDispatch> {
    let (adapter, effect, packet) = (adapter.clone(), effect.clone(), packet.to_vec());
    tokio::task::spawn_blocking(move || adapter.dispatch_blocking(effect, packet))
        .await
        .map_err(io::Error::other)
}
async fn lookup(
    adapter: &PonLocalProviderEffectAdapter,
    effect: &ProviderEffectIntent,
    packet: &[u8],
) -> io::Result<ProviderEffectLookup> {
    let (adapter, effect, packet) = (adapter.clone(), effect.clone(), packet.to_vec());
    tokio::task::spawn_blocking(move || adapter.lookup_blocking(effect, packet))
        .await
        .map_err(io::Error::other)
}
async fn observe(
    adapter: &PonLocalProviderEffectAdapter,
    effect: &ProviderEffectIntent,
    packet: &[u8],
) -> io::Result<crate::AutomationEffectChainObservation> {
    AgentdProviderEffectAdapter::Pon(adapter.clone())
        .current_chain_observation(effect, Some(packet))
        .await
        .ok_or_else(|| io::Error::other("missing remote exact observation"))
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires exact resident-capable Chain and growth task fixture binaries; mandatory in paired native CI"]
async fn real_growth_remote_chain_resident_task_lost_ack_confirm_reorg_restart() -> TestResult {
    let chain = Chain::exact()?;
    let fixture_binary = PathBuf::from(std::env::var("HEPTA_PON_TASK_FIXTURE")?).canonicalize()?;
    let fixture_digest = Sha256Digest::parse(std::env::var("HEPTA_PON_TASK_FIXTURE_SHA256")?)
        .map_err(io::Error::other)?;
    let plan = fixture(
        &fixture_binary,
        &fixture_digest,
        &[
            "growth-plan".into(),
            chain.genesis_time.to_string(),
            NAMESPACE.into(),
        ],
    )
    .await?;
    let output = Sha256Digest::for_bytes(b"independently retained live growth task output");
    let temporary = tempfile::tempdir()?;
    let root = temporary.path().canonicalize()?;
    let prepared_path = root.join("prepared");
    let prepared = fixture(
        &fixture_binary,
        &fixture_digest,
        &[
            "growth-prepare".into(),
            prepared_path.to_string_lossy().into_owned(),
            chain.genesis_time.to_string(),
            NAMESPACE.into(),
            output.as_str().into(),
        ],
    )
    .await?;
    assert_eq!(
        prepared["schema"],
        "hepta-native-development-growth-task-fixture-v1"
    );
    assert_eq!(prepared["acceptance_submitted"], false);
    assert_eq!(prepared["prepared_state"]["height"], 2);
    assert_eq!(prepared["packet_profile"], "PNP2");
    assert_eq!(
        prepared["state_profile"],
        "permanent-account-growth-native-v2"
    );
    assert_eq!(prepared["growth_namespace"], NAMESPACE);
    assert_eq!(prepared["output_sha256"], output.as_str());
    for field in [
        "network",
        "parameters",
        "genesis",
        "task_id",
        "owner",
        "provider",
    ] {
        assert_eq!(prepared[field], plan[field]);
    }
    let store = prepared_path.join("node");
    assert_eq!(PathBuf::from(text(&prepared, "store")?), store);
    let packet_path = prepared_path.join("accept.pnp2");
    assert_eq!(
        PathBuf::from(text(&prepared, "accept_packet")?),
        packet_path
    );
    let packet = fs::read(&packet_path)?;
    assert!(packet.starts_with(b"PNP2") && packet.len() <= 1024 * 1024);
    assert_eq!(
        text(&prepared, "accept_packet_sha256")?,
        Sha256Digest::for_bytes(&packet).as_str()
    );
    let effect = intent("signed-task-acceptance", &packet)?;
    let expected = ExpectedAutomationTaskAcceptanceV1 {
        effect: effect.clone(),
        min_confirmation_depth: 1,
        min_confirmation_work_depth_hex: format!("{}02", "00".repeat(63)),
        block_id: text(&prepared, "accept_block")?,
        task_id: text(&plan, "task_id")?,
        owner: text(&plan, "owner")?,
        provider: text(&plan, "provider")?,
        output_sha256: output.as_str().into(),
        accept_tx_id: text(&prepared, "accept_tx_id")?,
    };
    let expected_task = AutomationEffectTaskAcceptanceV1 {
        schema_version: 1,
        task_id: expected.task_id.clone(),
        owner: expected.owner.clone(),
        provider: expected.provider.clone(),
        output_sha256: expected.output_sha256.clone(),
        accept_tx_id: expected.accept_tx_id.clone(),
        accepted_in_exact_packet: true,
        current_status: "settled".into(),
    };

    // Build genuine successors/forks in separate native namespaces before the
    // receiver's sole owner starts. No writes race its live SQLite connection.
    let builder = root.join("builder");
    chain.call("status", &builder, &[]).await?;
    for path in [
        prepared_path.join("prefix-1.pnp2"),
        prepared_path.join("prefix-2.pnp2"),
        packet_path.clone(),
    ] {
        chain
            .call(
                "submit",
                &builder,
                &["--packet".into(), path.to_string_lossy().into_owned()],
            )
            .await?;
    }
    let maintenance = chain
        .packet(
            &builder,
            &root.join("confirm.pnp2"),
            chain.genesis_time + 40,
        )
        .await?;
    let maintenance_effect = intent("maintenance-confirmation", &maintenance)?;
    let alternate = root.join("alternate");
    chain.call("status", &alternate, &[]).await?;
    let mut fork = Vec::new();
    for height in 1..=5_u64 {
        fork.push(
            chain
                .packet(
                    &alternate,
                    &root.join(format!("fork-{height}.pnp2")),
                    chain.genesis_time + height * 10 + 1,
                )
                .await?,
        );
    }
    let server_secret = root.join("server.secret");
    let (server_public, _) = secret(&server_secret, 161)?;
    let caller_secret = root.join("caller.secret");
    let (caller_public, caller_digest) = secret(&caller_secret, 178)?;
    let snapshot_root = root.join("credential-snapshots");
    fs::create_dir(&snapshot_root)?;
    fs::set_permissions(&snapshot_root, fs::Permissions::from_mode(0o700))?;
    let credential = CredentialPin {
        source: caller_secret.canonicalize()?,
        sha256: caller_digest,
        public_key: caller_public,
        snapshot_root: snapshot_root.canonicalize()?,
    };
    let resident = Resident::start(&chain, &store, &server_secret, "127.0.0.1:0", 30).await?;
    let address = text(&resident.listening, "address")?;
    let public_hex: String = server_public
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect();
    assert_eq!(resident.listening["server_public"], public_hex);
    for field in ["network", "parameters", "genesis"] {
        assert_eq!(resident.listening["state"][field], plan[field]);
    }
    let adapter = chain.adapter(&resident.listening, &plan, credential.clone())?;
    assert!(adapter.store.as_os_str().is_empty());
    chain
        .assert_cold_observer_locked(&store, &packet_path)
        .await?;
    let absent = observe(&adapter, &effect, &packet).await?;
    assert!(!absent.stored_exact && absent.accepted_task.is_none());
    assert!(!absent.matches_expected_task_acceptance(&expected));
    assert_eq!(
        lookup(&adapter, &effect, &packet).await?,
        ProviderEffectLookup::Unknown
    );
    let PonLocalProfile::GrowthRemote(transport) = &adapter.profile else {
        unreachable!()
    };
    let mut local_v4 = adapter.clone();
    local_v4.store = store.clone();
    local_v4.profile = PonLocalProfile::Growth(transport.context.clone());
    assert_eq!(
        lookup(&local_v4, &effect, &packet).await?,
        ProviderEffectLookup::Unknown
    );
    assert!(observe(&local_v4, &effect, &packet).await.is_err());
    assert!(matches!(
        dispatch(&local_v4, &effect, &packet).await?,
        ProviderEffectDispatch::NotDispatched { .. }
    ));
    for wrong_field in ["context", "server", "resource"] {
        let mut wrong = adapter.clone();
        let PonLocalProfile::GrowthRemote(transport) = &mut wrong.profile else {
            unreachable!()
        };
        match wrong_field {
            "context" => transport.context.parameters = "44".repeat(32),
            "server" => transport.server_public = "55".repeat(32),
            "resource" => transport.resource_profile = "66".repeat(32),
            _ => unreachable!(),
        }
        assert!(
            matches!(
                dispatch(&wrong, &effect, &packet).await?,
                ProviderEffectDispatch::NotDispatched { .. }
            ),
            "{wrong_field}"
        );
    }
    assert_eq!(observe(&adapter, &effect, &packet).await?, absent);

    let ProviderEffectDispatch::Ack(ack) = dispatch(&adapter, &effect, &packet).await? else {
        return Err(io::Error::other("resident task submit was not acknowledged").into());
    };
    ack.validate_for(&effect)
        .map_err(|error| io::Error::other(format!("{error:?}")))?;
    // The consumer loses its ACK observation. Only a fresh adapter's lookup is
    // used for recovery; actual server submit counters below detect redispatch.
    // This does not claim TCP ACK-drop fault injection.
    let reconciler = chain.adapter(&resident.listening, &plan, credential.clone())?;
    assert_eq!(
        lookup(&reconciler, &effect, &packet).await?,
        ProviderEffectLookup::Ack(ack.clone())
    );
    let included = observe(&reconciler, &effect, &packet).await?;
    assert_eq!(included.accepted_task, Some(expected_task.clone()));
    assert_eq!(included.active_depth, Some(0));
    assert_eq!(included.active_membership_sql_lookups, Some(1));
    assert!(!included.matches_expected_task_acceptance(&expected));
    assert!(matches!(
        dispatch(&adapter, &maintenance_effect, &maintenance).await?,
        ProviderEffectDispatch::Ack(_)
    ));
    let pure_maintenance = observe(&adapter, &maintenance_effect, &maintenance).await?;
    assert!(pure_maintenance.active_chain_member && pure_maintenance.accepted_task.is_none());
    let confirmed = observe(&adapter, &effect, &packet).await?;
    assert_eq!(confirmed.accepted_task, Some(expected_task));
    assert_eq!(confirmed.active_depth, Some(1));
    assert_eq!(confirmed.active_membership_sql_lookups, Some(3));
    assert!(confirmed.matches_expected_task_acceptance(&expected));
    let mut foreign = expected.clone();
    foreign.output_sha256 = Sha256Digest::for_bytes(b"different independently held output")
        .as_str()
        .into();
    assert!(!confirmed.matches_expected_task_acceptance(&foreign));
    for (index, packet) in fork.iter().enumerate() {
        assert!(matches!(
            dispatch(&adapter, &intent(&format!("fork-{index}"), packet)?, packet).await?,
            ProviderEffectDispatch::Ack(_)
        ));
    }
    let orphan = observe(&adapter, &effect, &packet).await?;
    assert!(orphan.stored_exact && !orphan.active_chain_member);
    assert!(orphan.accepted_task.is_none());
    assert!(!orphan.matches_expected_task_acceptance(&expected));
    assert!(orphan.owner_generation > confirmed.owner_generation);
    assert_eq!(
        lookup(&reconciler, &effect, &packet).await?,
        ProviderEffectLookup::Ack(ack.clone())
    );
    let metrics = resident.finish().await?;
    assert_eq!(
        metrics["result"]["completed_submit"], 7,
        "lookup must not issue another submit"
    );
    assert!(
        metrics["result"]["mutation_cpu_charged_ns"]
            .as_u64()
            .unwrap_or(0)
            > 0
    );
    let cold = chain
        .call(
            "packet-status",
            &store,
            &[
                "--packet".into(),
                packet_path.to_string_lossy().into_owned(),
            ],
        )
        .await?;
    assert_eq!(cold["result"]["stored_exact"], true);
    assert_eq!(cold["result"]["active_chain_member"], false);
    assert_eq!(cold["result"]["generation"], orphan.owner_generation);

    // Same endpoint/key/resource/context, cleanly reopened original store. A
    // new original process starts cold; lookup grants no extra execution credit.
    let restarted = Resident::start(&chain, &store, &server_secret, &address, 8).await?;
    assert_eq!(restarted.listening["address"], address);
    let after_restart = chain.adapter(&restarted.listening, &plan, credential)?;
    let PonLocalProfile::GrowthRemote(first) = &adapter.profile else {
        unreachable!()
    };
    let PonLocalProfile::GrowthRemote(second) = &after_restart.profile else {
        unreachable!()
    };
    assert_eq!(first.server_public, second.server_public);
    assert_eq!(first.resource_profile, second.resource_profile);
    assert_eq!(
        lookup(&after_restart, &effect, &packet).await?,
        ProviderEffectLookup::Ack(ack)
    );
    assert_eq!(observe(&after_restart, &effect, &packet).await?, orphan);
    let restarted_metrics = restarted.finish().await?;
    assert_eq!(restarted_metrics["result"]["completed_submit"], 0);
    assert_eq!(
        fs::read_dir(&snapshot_root)?.count(),
        0,
        "credential snapshots outlived joined client processes"
    );
    println!(
        "PON_GROWTH_REMOTE_RESIDENT_PAIR {}",
        serde_json::json!({
            "chain_source":chain.source, "binary_sha256":chain.digest.as_str(),
            "fixture_sha256":fixture_digest.as_str(), "namespace":NAMESPACE,
            "transport_profile":PROFILE, "included":included, "confirmed":confirmed, "orphaned":orphan,
            "cold_observer_busy_while_resident":true, "consumer_lost_ack_lookup_only":true,
            "local_v4_unavailable_while_resident":true, "wrong_pins_not_dispatched":true,
            "actual_first_service_submits":7, "actual_restart_submits":0,
            "same_endpoint_clean_restart":true, "maintenance_task_acceptance":false,
            "accepted_external_task_binding_verified":true, "useful_model_output_qualified":false,
            "actual_model_installation_verified":false, "production_activation":false
        })
    );
    Ok(())
}
