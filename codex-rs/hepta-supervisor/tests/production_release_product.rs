#![cfg(all(unix, feature = "production-authority"))]

use std::fs::File;
use std::io::BufRead;
use std::io::BufReader;
use std::io::Write;
use std::os::unix::net::UnixListener;
use std::os::unix::process::CommandExt;
use std::path::Path;
use std::path::PathBuf;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_hepta_agent_protocol::AGENTD_CONTROL_SCHEMA_VERSION;
use codex_hepta_agent_protocol::AgentdMethod;
use codex_hepta_agent_protocol::AgentdPayload;
use codex_hepta_agent_protocol::AgentdRequest;
use codex_hepta_agent_protocol::AgentdResponse;
use codex_hepta_agent_protocol::DrainSnapshot;
use codex_hepta_agent_protocol::HealthSnapshot;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentLifecycleState;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ReleaseId;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_memory::H7ArtifactSigner;
use codex_hepta_memory::H7QualificationRuntime;
use codex_hepta_memory::H7SignedArtifactTransition;
use codex_hepta_memory::H7TrajectoryEvent;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_supervisor::H7H89ProductionGrantSigner;
use codex_hepta_supervisor::H7H89ProductionTransition;
use codex_hepta_supervisor::ProductionMutationStatus;
use codex_hepta_supervisor::ProductionReleaseCallerStatusV1;
use codex_hepta_supervisor::ProductionReleaseJournalV1;
use codex_hepta_supervisor::ProductionReleaseRequestV1;
use codex_hepta_supervisor::SupervisordClient;
use codex_hepta_supervisor::authority_epoch_for_supervisor_epoch;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const GRANT_SIGNER_ID: &str = "release-controller-grant-authority";
const GRANT_SIGNER_EPOCH: u64 = 17;
const H7_SIGNER_ID: &str = "release-controller-h7-authority";
const H7_SIGNER_EPOCH: u64 = 19;
const DRAIN_COUNT_FILE: &str = "release-controller-fixture-drain-count";

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn external_signer_caller_and_supervisor_recover_without_replay() -> Result<()> {
    let temp = tempfile::Builder::new()
        .prefix("hsrel-")
        .tempdir_in("/tmp")?;
    let root = temp.path().canonicalize()?;
    let fleet_root = HeptaFleetRoot::parse(root.join("fleet"))?;
    let registry = FleetRegistry::initialize(fleet_root.clone())?;
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace)?;
    let agent_id = AgentId::parse(AGENT_ID).map_err(anyhow::Error::msg)?;
    registry.register(AgentManifest::new(
        agent_id.clone(),
        WorkspaceBinding::new(workspace.canonicalize()?, &fleet_root)?,
        ResourceBudget::local_default(),
    )?)?;

    let real_agentd = std::env::var_os("HEPTA_SUPERVISOR_QUAL_AGENTD").map(PathBuf::from);
    let fixture_binary = real_agentd.clone().unwrap_or(std::env::current_exe()?);
    ensure!(
        fixture_binary.is_absolute() && fixture_binary.is_file(),
        "invalid qualification binary"
    );
    let backend = if real_agentd.is_some() {
        "real_agentd"
    } else {
        "native_protocol_fixture"
    };
    if real_agentd.is_some() {
        let home = registry
            .load_agent(&agent_id)?
            .layout
            .home_root()
            .to_path_buf();
        std::fs::create_dir_all(&home)?;
        // The test never reads the operator's CODEX_HOME or provider secrets.
        // No model turn is sent; the explicitly local endpoint cannot spend
        // external provider credentials even if startup probes it.
        std::fs::write(
            home.join("config.toml"),
            r#"model = "gpt-5.1"
model_provider = "qualification_local"
[model_providers.qualification_local]
name = "qualification_local"
base_url = "http://127.0.0.1:9/v1"
wire_api = "responses"
requires_openai_auth = false
"#,
        )?;
    }
    let source_release = ReleaseId::parse("release-controller-source-v1")?;
    let target_release = ReleaseId::parse("release-controller-target-v2")?;
    registry.install_release(
        source_release.clone(),
        &fixture_binary,
        if real_agentd.is_some() {
            Vec::new()
        } else {
            child_arguments(1)
        },
    )?;
    registry.install_release(
        target_release.clone(),
        &fixture_binary,
        if real_agentd.is_some() {
            Vec::new()
        } else {
            child_arguments(2)
        },
    )?;
    registry.allow_release(&agent_id, &source_release)?;
    registry.allow_release(&agent_id, &target_release)?;

    let grant_signer =
        H7H89ProductionGrantSigner::from_seed(GRANT_SIGNER_ID, GRANT_SIGNER_EPOCH, [31; 32])?;
    let h7_signer = H7ArtifactSigner::from_seed(H7_SIGNER_ID, H7_SIGNER_EPOCH, [41; 32])?;
    let grant_key_path = root.join("grant-verifier.key");
    let h7_key_path = root.join("h7-verifier.key");
    std::fs::write(&grant_key_path, grant_signer.verifying_key().to_bytes())?;
    std::fs::write(&h7_key_path, h7_signer.verifying_key().to_bytes())?;

    let mut daemon = DaemonGroup::spawn(fleet_root.as_path(), &grant_key_path, &h7_key_path)?;
    let client = wait_for_daemon(&registry).await?;
    let health = client.health().await.context("initial daemon health")?;
    ensure!(health.ready);
    let authority_epoch = authority_epoch_for_supervisor_epoch(health.supervisor_epoch.as_str());

    let initial = client
        .snapshot(agent_id.clone())
        .await
        .context("initial agent snapshot")?;
    if let Err(error) = client
        .start(initial.control_fence, source_release.clone())
        .await
    {
        eprintln!(
            "initial Start acknowledgement is indeterminate; observing without resend: {error}"
        );
    }
    eprintln!("product-stage: wait source release");
    let source_status =
        wait_for_release(&client, &agent_id, &source_release, Duration::from_secs(20)).await?;

    let issued_at = unix_seconds()?.saturating_sub(1).max(1);
    let expires_at = issued_at + 300;
    let h7_envelope = signed_h7_envelope(
        &h7_signer,
        H7SignedArtifactTransition::Reload,
        source_status
            .runtime_generation
            .context("source runtime generation")?,
        issued_at,
        expires_at,
    )?;
    // Invoke the existing independent signer binary with a disposable test
    // trust root. The controller and supervisord never receive the private key.
    let private_key_path = root.join("qualification-grant-seed");
    std::fs::write(&private_key_path, [31_u8; 32])?;
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&private_key_path, std::fs::Permissions::from_mode(0o600))?;
    }
    let signing_context = client.production_mutation_context(agent_id.clone()).await?;
    ensure!(signing_context.agent == source_status);
    let sign_request = codex_hepta_supervisor::SignRequest::ProductionGrant {
        signer_id: GRANT_SIGNER_ID.to_string(),
        signer_epoch: GRANT_SIGNER_EPOCH,
        h7_envelope: h7_envelope.clone(),
        agent_id: agent_id.to_string(),
        source_release: source_release.to_string(),
        target_release: target_release.to_string(),
        transition: H7H89ProductionTransition::Upgrade,
        expected_control_revision: signing_context.control_revision,
        expected_lifecycle_generation: source_status.lifecycle_generation,
        authority_epoch,
        issued_at_unix_seconds: issued_at,
        expires_at_unix_seconds: expires_at,
    };
    let sign_path = root.join("qualification-sign-request.json");
    std::fs::write(&sign_path, serde_json::to_vec(&sign_request)?)?;
    let signed = Command::new(env!("CARGO_BIN_EXE_hepta-authority-signer"))
        .args(["--sign", "--key-file"])
        .arg(&private_key_path)
        .arg("--request")
        .arg(&sign_path)
        .output()?;
    ensure!(
        signed.status.success(),
        "external fixture signer failed: {}",
        String::from_utf8_lossy(&signed.stderr)
    );
    let codex_hepta_supervisor::SignResponse::ProductionGrant { grant } =
        serde_json::from_slice(&signed.stdout)?
    else {
        anyhow::bail!("unexpected signer response");
    };
    let request = ProductionReleaseRequestV1 {
        schema_version: 1,
        operation_id: "release-controller-product-upgrade-1".to_string(),
        agent_id: agent_id.clone(),
        grant,
        h7_envelope,
    };
    let request_path = root.join("signed-release-request.json");
    let journal_path = root.join("signed-release-journal.json");
    std::fs::write(&request_path, serde_json::to_vec(&request)?)?;

    eprintln!("product-stage: forward signed grant, lose ACK and kill caller");
    let mut ack_proxy = ack_loss_proxy::AckLossProxy::start(
        &root,
        registry.layout().supervisor_socket().to_path_buf(),
    )
    .await?;
    ack_proxy
        .crash_caller_after_forward(&request_path, &journal_path)
        .await?;

    // This is a fresh caller process reading the durable journal. It may query
    // the Supervisor result, but must never send the signed mutation again.
    eprintln!("product-stage: recover signed grant");
    let recovered =
        run_release_controller("recover", &ack_proxy.root, &request_path, &journal_path, 30)
            .await?;
    ensure!(
        recovered.status == ProductionReleaseCallerStatusV1::Committed,
        "recovered caller status was {:?}",
        recovered.status
    );
    ensure!(
        recovered
            .production_state
            .as_ref()
            .is_some_and(|state| state.receipt.status == ProductionMutationStatus::Committed)
    );

    let target_status =
        wait_for_release(&client, &agent_id, &target_release, Duration::from_secs(10)).await?;
    ensure!(target_status.healthy && !target_status.release_change_pending);
    let mutation = client
        .production_mutation_status(agent_id.clone())
        .await?
        .context("durable production mutation state")?;
    ensure!(mutation.receipt.status == ProductionMutationStatus::Committed);

    let run_root = registry
        .load_agent(&agent_id)?
        .layout
        .run_root()
        .to_path_buf();
    if real_agentd.is_none() {
        ensure!(
            read_drain_count(&run_root.join(DRAIN_COUNT_FILE))? == 1,
            "caller recovery replayed the signed release operation"
        );
    }
    ensure!(
        target_status.process_id != source_status.process_id,
        "no physical replacement"
    );
    let repeated =
        run_release_controller("dispatch", &fleet_root, &request_path, &journal_path, 0).await?;
    ensure!(
        repeated == recovered,
        "duplicate dispatch changed terminal result"
    );
    ensure!(
        client.snapshot(agent_id.clone()).await?.process_id == target_status.process_id,
        "duplicate caller request replaced the process again"
    );
    ensure!(
        ack_proxy.signed_request_count() == 1,
        "caller recovery replayed the original signed request"
    );
    eprintln!("product-stage: signed rollback through independent caller");
    let context = client.production_mutation_context(agent_id.clone()).await?;
    let rollback_h7 = signed_h7_envelope(
        &h7_signer,
        H7SignedArtifactTransition::Rollback,
        context
            .agent
            .runtime_generation
            .context("rollback runtime generation")?,
        issued_at,
        expires_at,
    )?;
    let rollback_grant = external_grant(
        &codex_hepta_supervisor::SignRequest::ProductionGrant {
            signer_id: GRANT_SIGNER_ID.to_string(),
            signer_epoch: GRANT_SIGNER_EPOCH,
            h7_envelope: rollback_h7.clone(),
            agent_id: agent_id.to_string(),
            source_release: target_release.to_string(),
            target_release: source_release.to_string(),
            transition: H7H89ProductionTransition::Rollback,
            expected_control_revision: context.control_revision,
            expected_lifecycle_generation: context.agent.lifecycle_generation,
            authority_epoch: context.authority_epoch,
            issued_at_unix_seconds: issued_at,
            expires_at_unix_seconds: expires_at,
        },
        &private_key_path,
        &root.join("rollback-sign-request.json"),
    )?;
    let rollback_request = ProductionReleaseRequestV1 {
        schema_version: 1,
        operation_id: "release-controller-product-rollback-2".to_string(),
        agent_id: agent_id.clone(),
        grant: rollback_grant,
        h7_envelope: rollback_h7,
    };
    let rollback_path = root.join("rollback-request.json");
    let rollback_journal = root.join("rollback-journal.json");
    std::fs::write(&rollback_path, serde_json::to_vec(&rollback_request)?)?;
    run_release_controller(
        "dispatch",
        &fleet_root,
        &rollback_path,
        &rollback_journal,
        0,
    )
    .await?;
    let rolled_back = run_release_controller(
        "recover",
        &fleet_root,
        &rollback_path,
        &rollback_journal,
        30,
    )
    .await?;
    ensure!(
        rolled_back.status == ProductionReleaseCallerStatusV1::RolledBack,
        "rollback was {:?}",
        rolled_back.status
    );
    let rollback_status =
        wait_for_release(&client, &agent_id, &source_release, Duration::from_secs(10)).await?;
    ensure!(
        rollback_status.process_id != target_status.process_id,
        "rollback did not physically replace target"
    );
    let historical = client
        .production_mutation_lookup(agent_id.clone(), request.grant.grant_sha256.clone())
        .await?
        .context("previous grant retained after rollback")?;
    ensure!(
        historical.receipt == mutation.receipt,
        "new grant replaced an old terminal result"
    );

    eprintln!("product-stage: SIGKILL supervisor and adopt existing Agentd");
    daemon.crash()?;
    let mut recovered_daemon =
        DaemonGroup::spawn(fleet_root.as_path(), &grant_key_path, &h7_key_path)?;
    wait_for_daemon(&registry).await?;
    let adopted =
        wait_for_release(&client, &agent_id, &source_release, Duration::from_secs(10)).await?;
    ensure!(
        adopted.process_id == rollback_status.process_id,
        "daemon recovery replayed child spawn"
    );
    ensure!(
        client
            .production_mutation_lookup(agent_id.clone(), request.grant.grant_sha256.clone())
            .await?
            == Some(historical),
        "historical result changed across SIGKILL"
    );
    println!(
        "SUPERVISOR_PRODUCT_RECEIPT {}",
        serde_json::json!({
            "backend": backend, "agent_binary_sha256": Sha256Digest::for_bytes(&std::fs::read(&fixture_binary)?),
            "source_pid": source_status.process_id, "target_pid": target_status.process_id,
            "rollback_pid": rollback_status.process_id, "adopted_pid": adopted.process_id,
            "grant_sha256": request.grant.grant_sha256, "result": recovered,
            "rollback_result": rolled_back, "supervisord_sigkill_adopted": true,
            "caller_sigkill_after_send": true, "lost_ack_recovered": true,
            "original_signed_request_count": ack_proxy.signed_request_count(),
            "model_turns_submitted": 0, "deployment_qualified": false,
        })
    );

    // Completed caller history is local and monotone: after stopping the
    // Supervisor a new caller process still recovers the identical terminal.
    let terminal_before = recovered.clone();
    let final_status = client.snapshot(agent_id.clone()).await?;
    client.kill(final_status.control_fence).await?;
    wait_for_inactive(&client, &agent_id, Duration::from_secs(10)).await?;
    recovered_daemon.terminate()?;
    let retained =
        run_release_controller("recover", &fleet_root, &request_path, &journal_path, 0).await?;
    ensure!(
        retained == terminal_before,
        "terminal result changed while owner was unavailable"
    );
    Ok(())
}

#[path = "support/release_product.rs"]
mod support;
use support::*;

#[path = "support/ack_loss_proxy.rs"]
mod ack_loss_proxy;
