//! Real signed task acceptance through the sealed adapter and typed comparison.
//! The explicit paired CI supplies both source-pinned native executables. Missing
//! inputs fail this selected test; no mocked responses or model-install claim.

use super::super::AgentdProviderEffectAdapter;
use super::super::PonLocalProfile;
use super::super::PonLocalProviderEffectAdapter;
use super::super::pon_executable::PinnedExecutable;
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
const OUTPUT_LIMIT: usize = 64 * 1024;

#[derive(Clone)]
struct Binary {
    path: PathBuf,
    sha256: Sha256Digest,
}

impl Binary {
    fn from_env(path: &str, digest: &str) -> Result<Self, io::Error> {
        let path = PathBuf::from(std::env::var(path).map_err(io::Error::other)?).canonicalize()?;
        let sha256 = Sha256Digest::parse(std::env::var(digest).map_err(io::Error::other)?)
            .map_err(io::Error::other)?;
        Ok(Self { path, sha256 })
    }

    async fn call(&self, args: &[String]) -> Result<Value, io::Error> {
        let deadline = Instant::now() + Duration::from_secs(30);
        let executable = PinnedExecutable::prepare(&self.path, self.sha256.as_str(), deadline)?;
        let mut command = Command::new(executable.path());
        command.args(args);
        let Outcome::Complete(bytes) = run(command, b"", deadline, OUTPUT_LIMIT).await else {
            return Err(io::Error::other(
                "source-pinned task pair command incomplete",
            ));
        };
        serde_json::from_slice(&bytes).map_err(io::Error::other)
    }
}

struct Chain {
    binary: Binary,
    genesis_time: u64,
    backend: &'static str,
}

impl Chain {
    async fn call(
        &self,
        operation: &str,
        store: &Path,
        args: &[String],
    ) -> Result<Value, io::Error> {
        let mut command = vec![
            operation.into(),
            "--development".into(),
            "--store".into(),
            store.to_string_lossy().into_owned(),
            "--state-backend".into(),
            self.backend.into(),
            "--genesis-time".into(),
            self.genesis_time.to_string(),
            "--evaluation-policy".into(),
            "legacy-first-two-v3".into(),
            "--task-profile".into(),
            "legacy-task-v1".into(),
            "--model-profile".into(),
            "linear-expert-dev-v1".into(),
            "--workers".into(),
            "1".into(),
        ];
        command.extend_from_slice(args);
        self.binary.call(&command).await
    }

    fn adapter(&self, store: PathBuf) -> PonLocalProviderEffectAdapter {
        PonLocalProviderEffectAdapter {
            binary: self.binary.path.clone(),
            binary_sha256: self.binary.sha256.clone(),
            store,
            genesis_time: self.genesis_time,
            profile: PonLocalProfile::Legacy {
                state_backend: self.backend.into(),
                evaluation_policy: "legacy-first-two-v3".into(),
                task_profile: "legacy-task-v1".into(),
                model_profile: "linear-expert-dev-v1".into(),
                workers: 1,
            },
            min_confirmation_depth: 1,
            min_confirmation_work_depth_hex: format!("{}02", "00".repeat(63)),
            timeout: Duration::from_secs(30),
        }
    }

    async fn mine(
        &self,
        store: &Path,
        output: &Path,
        timestamp: u64,
    ) -> Result<Vec<u8>, io::Error> {
        self.call(
            "mine",
            store,
            &[
                "--timestamp".into(),
                timestamp.to_string(),
                "--output".into(),
                output.to_string_lossy().into_owned(),
            ],
        )
        .await?;
        let wire = fs::read(output)?;
        if wire.is_empty() || wire.len() > 1024 * 1024 {
            return Err(io::Error::other("native task pair packet dimensions"));
        }
        Ok(wire)
    }
}

fn string(value: &Value, field: &str) -> Result<String, io::Error> {
    value[field]
        .as_str()
        .map(str::to_owned)
        .ok_or_else(|| io::Error::other(format!("task fixture missing {field}")))
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires the exact Chain and signed-task fixture executables; mandatory in paired native CI"]
async fn real_chain_signed_task_acceptance_confirm_and_reorg() -> TestResult {
    let source = std::env::var("HEPTA_PON_CHAIN_SOURCE")?;
    if source.len() != 40
        || !source
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(io::Error::other("exact task-pair Chain source required").into());
    }
    let binary = Binary::from_env("HEPTA_PON_CHAIN_BINARY", "HEPTA_PON_CHAIN_SHA256")?;
    let fixture = Binary::from_env("HEPTA_PON_TASK_FIXTURE", "HEPTA_PON_TASK_FIXTURE_SHA256")?;
    let genesis_time = SystemTime::now()
        .duration_since(UNIX_EPOCH)?
        .as_secs()
        .checked_sub(3600)
        .ok_or_else(|| io::Error::other("task pair fixture clock"))?;
    // This read-only plan precedes preparation and any packet dispatch. Expected
    // task/owner/provider facts never come from the observed acceptance response.
    let plan = fixture
        .call(&["plan".into(), genesis_time.to_string()])
        .await?;
    let output = Sha256Digest::for_bytes(b"owner-retained development task output binding");
    for backend in ["legacy-v2", "authenticated-v1"] {
        let temp = tempfile::tempdir()?;
        let root = temp.path().canonicalize()?;
        let prepared_path = root.join("prepared");
        let prepared = fixture
            .call(&[
                "prepare".into(),
                prepared_path.to_string_lossy().into_owned(),
                genesis_time.to_string(),
                backend.into(),
                output.as_str().into(),
            ])
            .await?;
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
        let wire = fs::read(prepared_path.join("accept.packet"))?;
        assert!(!wire.is_empty() && wire.len() <= 1024 * 1024);
        assert_eq!(
            string(&prepared, "accept_packet_sha256")?,
            Sha256Digest::for_bytes(&wire).as_str()
        );
        let chain = Chain {
            binary: binary.clone(),
            genesis_time,
            backend,
        };
        let adapter = chain.adapter(store.clone());
        let intent = ProviderEffectIntent::new(
            ProviderEffectKey::for_operation("pon-task-exact-pair", backend, "accept-submit")
                .map_err(|error| io::Error::other(format!("{error:?}")))?,
            Sha256Digest::for_bytes(&wire),
        );
        // Transaction and block ids are retained from real signed packet
        // construction before submission, never copied from packet-status.
        let expected = ExpectedAutomationTaskAcceptanceV1 {
            effect: intent.clone(),
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
        let host = AgentdProviderEffectAdapter::Pon(adapter.clone());
        let missing = host
            .current_chain_observation(&intent, Some(&wire))
            .await
            .ok_or_else(|| io::Error::other("missing pre-submit task observation"))?;
        assert!(!missing.stored_exact && missing.accepted_task.is_none());
        assert!(!missing.matches_expected_task_acceptance(&expected));
        let dispatched = {
            let adapter = adapter.clone();
            let intent = intent.clone();
            let wire = wire.clone();
            tokio::task::spawn_blocking(move || adapter.dispatch_blocking(intent, wire)).await?
        };
        let ProviderEffectDispatch::Ack(ack) = dispatched else {
            return Err(io::Error::other("native signed acceptance was not acknowledged").into());
        };
        ack.validate_for(&intent)
            .map_err(|error| io::Error::other(format!("{error:?}")))?;
        let included = host
            .current_chain_observation(&intent, Some(&wire))
            .await
            .ok_or_else(|| io::Error::other("missing included task observation"))?;
        assert_eq!(included.accepted_task, Some(expected_task.clone()));
        assert_eq!(included.active_depth, Some(0));
        assert!(!included.matches_expected_task_acceptance(&expected));
        chain
            .mine(&store, &root.join("confirm.packet"), genesis_time + 40)
            .await?;
        let confirmed = host
            .current_chain_observation(&intent, Some(&wire))
            .await
            .ok_or_else(|| io::Error::other("missing confirmed task observation"))?;
        assert_eq!(confirmed.accepted_task, Some(expected_task));
        assert!(confirmed.matches_expected_task_acceptance(&expected));
        let mut foreign = expected.clone();
        foreign.output_sha256 = Sha256Digest::for_bytes(b"another task output")
            .as_str()
            .into();
        assert!(!confirmed.matches_expected_task_acceptance(&foreign));
        let alternate = root.join("alternate");
        chain.call("status", &alternate, &[]).await?;
        for height in 1..=5_u64 {
            let fork_wire = chain
                .mine(
                    &alternate,
                    &root.join(format!("fork-{height}.packet")),
                    genesis_time + height * 10 + 1,
                )
                .await?;
            let fork_intent = ProviderEffectIntent::new(
                ProviderEffectKey::for_operation(
                    "pon-task-exact-pair",
                    backend,
                    &format!("fork-{height}"),
                )
                .map_err(|error| io::Error::other(format!("{error:?}")))?,
                Sha256Digest::for_bytes(&fork_wire),
            );
            let adapter = adapter.clone();
            let sent = tokio::task::spawn_blocking(move || {
                adapter.dispatch_blocking(fork_intent, fork_wire)
            })
            .await?;
            assert!(matches!(sent, ProviderEffectDispatch::Ack(_)));
        }
        let orphaned = host
            .current_chain_observation(&intent, Some(&wire))
            .await
            .ok_or_else(|| io::Error::other("missing reorged task observation"))?;
        assert!(orphaned.stored_exact && !orphaned.active_chain_member);
        assert_eq!(orphaned.accepted_task, None);
        assert!(!orphaned.matches_expected_task_acceptance(&expected));
        assert!(orphaned.owner_generation > confirmed.owner_generation);
        let terminal = {
            let adapter = chain.adapter(store);
            let intent = intent.clone();
            let wire = wire.clone();
            tokio::task::spawn_blocking(move || adapter.lookup_blocking(intent, wire)).await?
        };
        assert_eq!(terminal, ProviderEffectLookup::Ack(ack));
        println!(
            "PON_TASK_ACCEPTANCE_PAIR {}",
            serde_json::json!({
                "chain_source": source, "binary_sha256": binary.sha256.as_str(),
                "fixture_sha256": fixture.sha256.as_str(), "backend": backend,
                "expected": {"task_id":expected.task_id,"owner":expected.owner,
                    "provider":expected.provider,"output_sha256":expected.output_sha256,
                    "accept_tx_id":expected.accept_tx_id,"block":expected.block_id},
                "included": included, "confirmed": confirmed, "orphaned": orphaned,
                "terminal_ack_preserved_after_reorg": true, "actual_model_installation_verified": false,
                "independent_operators": false, "production_activation": false
            })
        );
    }
    Ok(())
}
