//! Actual PNP2 bytes through the sealed adapter. These are consensus-maintenance
//! blocks, never evidence of accepted external training or a model installation.
use super::super::AgentdProviderEffectAdapter;
use super::super::PonLocalProfile;
use super::super::PonLocalProviderEffectAdapter;
use super::super::pon_executable::PinnedExecutable;
use super::super::pon_growth::Context;
use super::Outcome;
use super::run;
use codex_hepta_agent_protocol::AutomationEffectTaskAcceptanceV1;
use codex_hepta_agent_protocol::ExpectedAutomationTaskAcceptanceV1;
use codex_hepta_contracts::ProviderEffectDispatch;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::ProviderEffectLookup;
use codex_hepta_contracts::Sha256Digest;
use serde_json::Value;
use std::fs;
use std::io;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

type TestResult = Result<(), Box<dyn std::error::Error>>;
const NAMESPACE: &str = "hepta-exact-growth-pair-v1";

struct Chain {
    binary: PathBuf,
    digest: Sha256Digest,
    genesis_time: u64,
}

impl Chain {
    async fn call(&self, operation: &str, store: &Path, args: &[String]) -> io::Result<Value> {
        let deadline = Instant::now() + Duration::from_secs(30);
        let executable = PinnedExecutable::prepare(&self.binary, self.digest.as_str(), deadline)?;
        let mut command = Command::new(executable.path());
        command
            .arg(format!("growth-{operation}"))
            .arg("--development")
            .arg("--store")
            .arg(store)
            .arg("--growth-namespace")
            .arg(NAMESPACE)
            .arg("--genesis-time")
            .arg(self.genesis_time.to_string())
            .args(args);
        let Outcome::Complete(bytes) = run(command, b"", deadline, 64 * 1024).await else {
            return Err(io::Error::other(format!(
                "native growth {operation} did not complete"
            )));
        };
        serde_json::from_slice(&bytes).map_err(io::Error::other)
    }

    fn adapter(&self, store: PathBuf, status: &Value) -> io::Result<PonLocalProviderEffectAdapter> {
        let hash = |field| {
            status["result"][field]
                .as_str()
                .map(str::to_owned)
                .ok_or_else(|| io::Error::other(format!("missing growth {field}")))
        };
        Ok(PonLocalProviderEffectAdapter {
            binary: self.binary.clone(),
            binary_sha256: self.digest.clone(),
            store,
            genesis_time: self.genesis_time,
            profile: PonLocalProfile::Growth(Context {
                namespace: NAMESPACE.into(),
                network: hash("network")?,
                parameters: hash("parameters")?,
                genesis: hash("genesis")?,
            }),
            min_confirmation_depth: 1,
            min_confirmation_work_depth_hex: format!("{}02", "00".repeat(63)),
            timeout: Duration::from_secs(30),
        })
    }

    async fn packet(
        &self,
        operation: &str,
        store: &Path,
        output: &Path,
        timestamp: u64,
    ) -> io::Result<Vec<u8>> {
        self.call(
            operation,
            store,
            &[
                "--timestamp".into(),
                timestamp.to_string(),
                "--miner".into(),
                "ab".repeat(32),
                "--output".into(),
                output
                    .to_str()
                    .ok_or_else(|| io::Error::other("non-UTF8 packet path"))?
                    .into(),
            ],
        )
        .await?;
        let bytes = fs::read(output)?;
        if bytes.len() > 1024 * 1024 || !bytes.starts_with(b"PNP2") {
            return Err(io::Error::other("growth packet dimensions or profile"));
        }
        Ok(bytes)
    }
}

fn intent(operation: &str, packet: &[u8]) -> io::Result<ProviderEffectIntent> {
    let key = ProviderEffectKey::for_operation("pon-exact-growth-pair", NAMESPACE, operation)
        .map_err(|error| io::Error::other(format!("{error:?}")))?;
    Ok(ProviderEffectIntent::new(
        key,
        Sha256Digest::for_bytes(packet),
    ))
}

async fn dispatch(
    adapter: &PonLocalProviderEffectAdapter,
    intent: &ProviderEffectIntent,
    packet: &[u8],
) -> io::Result<ProviderEffectDispatch> {
    let adapter = adapter.clone();
    let intent = intent.clone();
    let packet = packet.to_vec();
    tokio::task::spawn_blocking(move || adapter.dispatch_blocking(intent, packet))
        .await
        .map_err(io::Error::other)
}

async fn lookup(
    adapter: &PonLocalProviderEffectAdapter,
    intent: &ProviderEffectIntent,
    packet: &[u8],
) -> io::Result<ProviderEffectLookup> {
    let adapter = adapter.clone();
    let intent = intent.clone();
    let packet = packet.to_vec();
    tokio::task::spawn_blocking(move || adapter.lookup_blocking(intent, packet))
        .await
        .map_err(io::Error::other)
}

fn native_chain() -> Result<(String, Chain), Box<dyn std::error::Error>> {
    let source = std::env::var("HEPTA_PON_CHAIN_SOURCE")?;
    if source.len() != 40
        || !source
            .bytes()
            .all(|v| v.is_ascii_digit() || (b'a'..=b'f').contains(&v))
    {
        return Err(io::Error::other("missing exact Chain source identity").into());
    }
    let binary = PathBuf::from(std::env::var("HEPTA_PON_CHAIN_BINARY")?).canonicalize()?;
    let digest =
        Sha256Digest::parse(std::env::var("HEPTA_PON_CHAIN_SHA256")?).map_err(io::Error::other)?;
    if Sha256Digest::for_bytes(&fs::read(&binary)?) != digest {
        return Err(io::Error::other("exact Chain binary hash mismatch").into());
    }
    let genesis_time = SystemTime::now()
        .duration_since(UNIX_EPOCH)?
        .as_secs()
        .checked_sub(3600)
        .ok_or_else(|| io::Error::other("fixture clock"))?;
    Ok((
        source,
        Chain {
            binary,
            digest,
            genesis_time,
        },
    ))
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires the exact growth-capable Chain release binary; mandatory in the paired native CI lane"]
async fn real_growth_chain_submit_lost_ack_confirm_reorg_cold_reopen() -> TestResult {
    let (source, chain) = native_chain()?;
    let genesis_time = chain.genesis_time;
    let temp = tempfile::tempdir()?;
    let root = temp.path().canonicalize()?;
    let store = root.join("receiver");
    let alternate = root.join("alternate");
    let status = chain.call("status", &store, &[]).await?;
    chain.call("status", &alternate, &[]).await?;
    let packet = chain
        .packet("make", &store, &root.join("first.pnp2"), genesis_time + 10)
        .await?;
    let first = intent("maintenance-submit", &packet)?;
    let adapter = chain.adapter(store.clone(), &status)?;
    assert_eq!(
        lookup(&adapter, &first, &packet).await?,
        ProviderEffectLookup::Unknown
    );

    // A wrong signed expected context fails before send, even with a valid
    // namespace and exact native binary. The receiver remains at its genesis.
    let mut wrong = adapter.clone();
    let PonLocalProfile::Growth(context) = &mut wrong.profile else {
        unreachable!()
    };
    context.parameters = "44".repeat(32);
    assert!(matches!(
        dispatch(&wrong, &first, &packet).await?,
        ProviderEffectDispatch::NotDispatched { .. }
    ));
    assert_eq!(chain.call("status", &store, &[]).await?, status);

    let ProviderEffectDispatch::Ack(ack) = dispatch(&adapter, &first, &packet).await? else {
        return Err(io::Error::other("growth submit was not acknowledged").into());
    };
    ack.validate_for(&first)
        .map_err(|error| io::Error::other(format!("{error:?}")))?;
    // Discard the ACK, then use a fresh adapter and fresh native process to
    // recover retained bytes. No second submit is used for lost-ACK recovery.
    let reopened = chain.adapter(store.clone(), &status)?;
    assert_eq!(
        lookup(&reopened, &first, &packet).await?,
        ProviderEffectLookup::Ack(ack.clone())
    );
    let host = AgentdProviderEffectAdapter::Pon(reopened.clone());
    let included = host
        .current_chain_observation(&first, Some(&packet))
        .await
        .ok_or_else(|| io::Error::other("missing growth inclusion"))?;
    assert!(included.stored_exact && included.active_chain_member);
    assert_eq!(included.active_depth, Some(0));
    assert_eq!(included.active_membership_sql_lookups, Some(1));
    assert_eq!(included.accepted_task, None);
    assert!(!included.confirmation_policy_satisfied);
    chain
        .packet("mine", &store, &root.join("second.pnp2"), genesis_time + 20)
        .await?;
    let confirmed = host
        .current_chain_observation(&first, Some(&packet))
        .await
        .ok_or_else(|| io::Error::other("missing growth confirmation"))?;
    assert_eq!(confirmed.active_depth, Some(1));
    assert!(confirmed.confirmation_policy_satisfied);
    assert_eq!(confirmed.accepted_task, None);
    assert!(!confirmed.finality_authority && !confirmed.execution_authority);
    assert!(confirmed.owner_generation > included.owner_generation);

    for height in 1..=3u64 {
        let fork = chain
            .packet(
                "mine",
                &alternate,
                &root.join(format!("fork-{height}.pnp2")),
                genesis_time + height * 10 + 1,
            )
            .await?;
        let fork_intent = intent(&format!("fork-{height}"), &fork)?;
        assert!(matches!(
            dispatch(&reopened, &fork_intent, &fork).await?,
            ProviderEffectDispatch::Ack(_)
        ));
    }
    let orphan = host
        .current_chain_observation(&first, Some(&packet))
        .await
        .ok_or_else(|| io::Error::other("missing growth orphan observation"))?;
    assert!(orphan.stored_exact && !orphan.active_chain_member);
    assert_eq!(orphan.active_depth, None);
    assert_eq!(orphan.active_work_depth_hex, None);
    assert!(!orphan.confirmation_policy_satisfied);
    assert_eq!(orphan.accepted_task, None);
    assert!(orphan.owner_generation > confirmed.owner_generation);
    let cold = chain.adapter(store.clone(), &status)?;
    assert_eq!(
        lookup(&cold, &first, &packet).await?,
        ProviderEffectLookup::Ack(ack)
    );
    let cold_observation = AgentdProviderEffectAdapter::Pon(cold.clone())
        .current_chain_observation(&first, Some(&packet))
        .await;
    assert_eq!(cold_observation, Some(orphan.clone()));

    let mut changed = packet.clone();
    *changed
        .last_mut()
        .ok_or_else(|| io::Error::other("empty packet"))? ^= 1;
    let changed_intent = intent("changed-packet", &changed)?;
    assert_eq!(
        lookup(&cold, &changed_intent, &changed).await?,
        ProviderEffectLookup::Unknown
    );
    assert!(
        host.current_chain_observation(&changed_intent, Some(&packet))
            .await
            .is_none()
    );
    assert!(host.current_chain_observation(&first, None).await.is_none());
    println!(
        "PON_GROWTH_EXACT_PAIR {}",
        serde_json::json!({
            "chain_source":source, "binary_sha256":chain.digest.as_str(), "namespace":NAMESPACE,
            "included":included, "confirmed":confirmed, "orphaned":orphan,
            "lost_ack_reconciled":true, "terminal_ack_preserved_after_reorg":true,
            "cold_observation_unchanged":true, "consensus_maintenance_only":true,
            "accepted_external_task":false, "useful_model_output_qualified":false,
            "actual_model_installation_verified":false, "production_activation":false
        })
    );
    Ok(())
}

async fn task_fixture(binary: &Path, digest: &Sha256Digest, args: &[String]) -> io::Result<Value> {
    let deadline = Instant::now() + Duration::from_secs(30);
    let executable = PinnedExecutable::prepare(binary, digest.as_str(), deadline)?;
    let mut command = Command::new(executable.path());
    command.args(args);
    let Outcome::Complete(bytes) = run(command, b"", deadline, 64 * 1024).await else {
        return Err(io::Error::other(
            "native growth task fixture did not complete",
        ));
    };
    serde_json::from_slice(&bytes).map_err(io::Error::other)
}

fn string(value: &Value, field: &str) -> io::Result<String> {
    value[field]
        .as_str()
        .map(str::to_owned)
        .ok_or_else(|| io::Error::other(format!("missing task fixture {field}")))
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires exact growth Chain and signed-task fixture executables; mandatory in paired native CI"]
async fn real_growth_chain_signed_task_acceptance_confirm_reorg() -> TestResult {
    let (source, chain) = native_chain()?;
    let fixture = PathBuf::from(std::env::var("HEPTA_PON_TASK_FIXTURE")?).canonicalize()?;
    let fixture_digest = Sha256Digest::parse(std::env::var("HEPTA_PON_TASK_FIXTURE_SHA256")?)
        .map_err(io::Error::other)?;
    // Owner/task identities exist before preparation; output is independently
    // retained here, never read back from an acceptance observation.
    let plan = task_fixture(
        &fixture,
        &fixture_digest,
        &[
            "growth-plan".into(),
            chain.genesis_time.to_string(),
            NAMESPACE.into(),
        ],
    )
    .await?;
    let output = Sha256Digest::for_bytes(b"owner-retained development task output binding");
    let temp = tempfile::tempdir()?;
    let root = temp.path().canonicalize()?;
    let prepared_path = root.join("prepared");
    let prepared = task_fixture(
        &fixture,
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
    assert_eq!(prepared["packet_profile"], "PNP2");
    assert_eq!(
        prepared["state_profile"],
        "permanent-account-growth-native-v2"
    );
    assert_eq!(prepared["growth_namespace"], NAMESPACE);
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
    assert_eq!(prepared["acceptance_submitted"], false);
    assert_eq!(prepared["prepared_state"]["height"], 2);
    assert_eq!(prepared["output_sha256"], output.as_str());
    let store = prepared_path.join("node");
    assert_eq!(PathBuf::from(string(&prepared, "store")?), store);
    let packet_path = prepared_path.join("accept.pnp2");
    assert_eq!(
        PathBuf::from(string(&prepared, "accept_packet")?),
        packet_path
    );
    let packet = fs::read(packet_path)?;
    assert!(packet.len() <= 1024 * 1024 && packet.starts_with(b"PNP2"));
    assert_eq!(
        string(&prepared, "accept_packet_sha256")?,
        Sha256Digest::for_bytes(&packet).as_str()
    );
    let first = intent("signed-task-accept-submit", &packet)?;
    let expected = ExpectedAutomationTaskAcceptanceV1 {
        effect: first.clone(),
        min_confirmation_depth: 1,
        min_confirmation_work_depth_hex: format!("{}02", "00".repeat(63)),
        block_id: string(&prepared, "accept_block")?,
        task_id: string(&plan, "task_id")?,
        owner: string(&plan, "owner")?,
        provider: string(&plan, "provider")?,
        output_sha256: output.as_str().into(),
        accept_tx_id: string(&prepared, "accept_tx_id")?,
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
    let status = chain.call("status", &store, &[]).await?;
    for field in ["network", "parameters", "genesis"] {
        assert_eq!(status["result"][field], plan[field]);
    }
    let adapter = chain.adapter(store.clone(), &status)?;
    let host = AgentdProviderEffectAdapter::Pon(adapter.clone());
    let missing = host
        .current_chain_observation(&first, Some(&packet))
        .await
        .ok_or_else(|| io::Error::other("missing pre-submit growth task observation"))?;
    assert!(!missing.stored_exact && missing.accepted_task.is_none());
    assert!(!missing.matches_expected_task_acceptance(&expected));
    let ProviderEffectDispatch::Ack(ack) = dispatch(&adapter, &first, &packet).await? else {
        return Err(io::Error::other("growth task acceptance not acknowledged").into());
    };
    ack.validate_for(&first)
        .map_err(|error| io::Error::other(format!("{error:?}")))?;
    let included = host
        .current_chain_observation(&first, Some(&packet))
        .await
        .ok_or_else(|| io::Error::other("missing included growth task"))?;
    assert_eq!(included.accepted_task, Some(expected_task.clone()));
    assert_eq!(included.active_depth, Some(0));
    assert!(!included.matches_expected_task_acceptance(&expected));
    chain
        .packet(
            "mine",
            &store,
            &root.join("confirm.pnp2"),
            chain.genesis_time + 40,
        )
        .await?;
    let confirmed = host
        .current_chain_observation(&first, Some(&packet))
        .await
        .ok_or_else(|| io::Error::other("missing confirmed growth task"))?;
    assert_eq!(confirmed.accepted_task, Some(expected_task));
    assert!(confirmed.matches_expected_task_acceptance(&expected));
    let mut foreign = expected.clone();
    foreign.output_sha256 = Sha256Digest::for_bytes(b"another output").as_str().into();
    assert!(!confirmed.matches_expected_task_acceptance(&foreign));
    let cold = chain.adapter(store.clone(), &status)?;
    assert_eq!(
        lookup(&cold, &first, &packet).await?,
        ProviderEffectLookup::Ack(ack.clone())
    );

    let alternate = root.join("alternate");
    chain.call("status", &alternate, &[]).await?;
    for height in 1..=5_u64 {
        let fork = chain
            .packet(
                "mine",
                &alternate,
                &root.join(format!("task-fork-{height}.pnp2")),
                chain.genesis_time + height * 10 + 1,
            )
            .await?;
        let fork_intent = intent(&format!("task-fork-{height}"), &fork)?;
        assert!(matches!(
            dispatch(&adapter, &fork_intent, &fork).await?,
            ProviderEffectDispatch::Ack(_)
        ));
    }
    let orphan = host
        .current_chain_observation(&first, Some(&packet))
        .await
        .ok_or_else(|| io::Error::other("missing orphan growth task"))?;
    assert!(orphan.stored_exact && !orphan.active_chain_member);
    assert_eq!(orphan.accepted_task, None);
    assert!(!orphan.matches_expected_task_acceptance(&expected));
    assert!(orphan.owner_generation > confirmed.owner_generation);
    let cold = chain.adapter(store, &status)?;
    assert_eq!(
        lookup(&cold, &first, &packet).await?,
        ProviderEffectLookup::Ack(ack)
    );
    let cold_observation = AgentdProviderEffectAdapter::Pon(cold)
        .current_chain_observation(&first, Some(&packet))
        .await;
    assert_eq!(cold_observation, Some(orphan.clone()));
    println!(
        "PON_GROWTH_TASK_ACCEPTANCE_PAIR {}",
        serde_json::json!({
            "chain_source":source, "binary_sha256":chain.digest.as_str(),
            "fixture_sha256":fixture_digest.as_str(), "namespace":NAMESPACE,
            "expected":{"block":expected.block_id, "task_id":expected.task_id,
                "owner":expected.owner, "provider":expected.provider,
                "output_sha256":expected.output_sha256, "accept_tx_id":expected.accept_tx_id},
            "included":included, "confirmed":confirmed, "orphaned":orphan,
            "accepted_external_task_binding_verified":true, "terminal_ack_preserved_after_reorg":true,
            "useful_model_output_qualified":false, "actual_model_installation_verified":false,
            "production_activation":false
        })
    );
    Ok(())
}
