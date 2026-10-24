//! Explicit Unix signer profile: real CLI -> immutable courier -> recovered
//! product host -> original ordinary Child owner. The signed source verifier is
//! a controlled fixture, not qualification of external production custody.
#![cfg(unix)]

use codex_hepta_agentd::AgentdConfig;
use codex_hepta_agentd::AgentdProductionWriterHost;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_infer_worker_host::OrdinaryCpuBinding;
use codex_hepta_infer_worker_host::OrdinaryCpuRegistration;
use codex_hepta_infer_worker_host::OrdinaryCpuTarget;
use codex_hepta_infer_worker_host::final_use_grant_courier::SignedFinalUseGrantCourier;
use codex_hepta_memory::CognitiveRecoveryRequirement;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::LocalOutcomeState;
use codex_hepta_memory::ProductionAuthorityLease;
use codex_hepta_memory::ProductionAuthorityToken;
use codex_hepta_memory::ProductionAuthorityVerifier;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use std::collections::BTreeSet;
use std::fs;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::process::Command;
use std::process::Stdio;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error + Send + Sync>>;
const DESTINATION: &str = "infer-worker-host.ordinary-cpu.v1";

fn private_file(path: &Path, bytes: &[u8]) -> TestResult {
    let mut file = fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(0o600)
        .open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}

fn sign_with_real_cli(path: &Path, grant: &FinalUseGrant) -> TestResult<SignedFinalUseGrant> {
    let mut child = Command::new(codex_utils_cargo_bin::cargo_bin("hepta-final-use-signer")?)
        .arg("sign")
        .arg("--key")
        .arg(path)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?;
    child
        .stdin
        .take()
        .ok_or("signer stdin absent")?
        .write_all(&serde_json::to_vec(grant)?)?;
    let deadline = Instant::now() + Duration::from_secs(8);
    let status = loop {
        if let Some(status) = child.try_wait()? {
            break status;
        }
        if Instant::now() >= deadline {
            child.kill()?;
            child.wait()?;
            return Err("real signer did not finish within original eight seconds".into());
        }
        std::thread::sleep(Duration::from_millis(5));
    };
    assert!(
        status.success(),
        "real external signer must accept protected exact proposal"
    );
    let mut output = Vec::new();
    child
        .stdout
        .take()
        .ok_or("signer stdout absent")?
        .take(16_385)
        .read_to_end(&mut output)?;
    assert!(output.len() <= 16_384);
    Ok(serde_json::from_slice(&output)?)
}

fn source_bytes(lease: &ProductionAuthorityLease) -> TestResult<Vec<u8>> {
    Ok(serde_json::to_vec(&(lease, lease.fencing_token_digest()?))?)
}

fn trace_cognitive_identity(stage: &str, root: &Path) -> TestResult {
    for entry in fs::read_dir(root)? {
        let entry = entry?;
        let m = entry.metadata()?;
        eprintln!(
            "COURIER_RECOVERY_IDENTITY stage={stage} file={:?} uid={} mode={:o} links={} len={} dev={} ino={} mtime={}.{} ctime={}.{}",
            entry.file_name(),
            m.uid(),
            m.mode() & 0o7777,
            m.nlink(),
            m.len(),
            m.dev(),
            m.ino(),
            m.mtime(),
            m.mtime_nsec(),
            m.ctime(),
            m.ctime_nsec()
        );
    }
    Ok(())
}

#[tokio::test]
async fn real_signer_courier_and_recovered_agentd_reach_original_child_once_within_eight_seconds()
-> TestResult {
    let temp = tempfile::tempdir()?;
    let root = temp.path().canonicalize()?;
    let fleet_path = root.join("fleet");
    let fleet = HeptaFleetRoot::parse(fleet_path.clone())?;
    let registry = FleetRegistry::initialize(fleet.clone())?;
    let workspace = root.join("workspace");
    fs::create_dir(&workspace)?;
    let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2cfe")?;
    let manifest = AgentManifest::new(
        agent.clone(),
        WorkspaceBinding::new(workspace.clone(), &fleet)?,
        ResourceBudget::local_default(),
    )?;
    let record = registry.register(manifest)?;
    registry.compare_and_transition(&agent, 0, AgentLifecycle::Starting)?;
    let config = AgentdConfig::load(
        fleet_path,
        agent.clone(),
        1,
        record.layout.home_root().to_path_buf(),
        record.layout.run_root().to_path_buf(),
        record.layout.home_root().to_path_buf(),
        workspace.clone(),
    )?;
    let store = CognitiveStore::open(&config.identity().layout).await?;
    let cut = store.recovery_anchor().await?;
    trace_cognitive_identity(
        "before-explicit-close",
        config.identity().layout.cognitive_root(),
    )?;
    store.close().await;
    trace_cognitive_identity(
        "after-explicit-close",
        config.identity().layout.cognitive_root(),
    )?;
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?;
    let source_lease = ProductionAuthorityLease::from_verified_parts(
        agent.clone(),
        Sha256Digest::for_bytes(b"external-controlled-source-lease"),
        1,
        1,
        now.as_secs() + 300,
        ProductionAuthorityToken::from_verified_bytes(b"exact-source-token".to_vec())?,
    )?;
    let source_key = SigningKey::from_bytes(&[139; 32]);
    let source_signature = source_key.sign(&source_bytes(&source_lease)?);
    let source_verifying_key = source_key.verifying_key();
    let expected_lease = source_lease.clone();
    // Real signature verification over the exact original source lease/token;
    // this controlled fixture supplies no claim of production issuer custody.
    let verifier: Arc<dyn ProductionAuthorityVerifier> = Arc::new(
        move |lease: &ProductionAuthorityLease, owner: &AgentId| -> Result<(), String> {
            if lease != &expected_lease || owner != &expected_lease.agent_id {
                return Err("source lease binding differs".to_owned());
            }
            source_verifying_key
                .verify_strict(
                    &source_bytes(lease).map_err(|e| e.to_string())?,
                    &source_signature,
                )
                .map_err(|e| e.to_string())
        },
    );
    trace_cognitive_identity("before-recovery", config.identity().layout.cognitive_root())?;
    let host = AgentdProductionWriterHost::open_with_recovery(
        &config,
        CognitiveRecoveryRequirement::ExactCurrentCut(&cut),
        source_lease,
        verifier,
        "courier-live-writer",
        1,
    )
    .await?;
    assert!(host.production_mutation().is_some());
    let authority_path = root.join("final-use");
    fs::create_dir(&authority_path)?;
    fs::set_permissions(&authority_path, fs::Permissions::from_mode(0o700))?;
    let issuer = SigningKey::from_bytes(&[141; 32]);
    let authority = FinalUseAuthority::open_state_dir(
        &authority_path,
        "external-cli-issuer".to_owned(),
        issuer.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )?;
    let program = Path::new("/usr/bin/true").canonicalize()?;
    let registration = OrdinaryCpuRegistration::new(
        OrdinaryCpuBinding {
            subject_id: StableId::new(agent.as_str())?,
            scope_digest: Digest32::of_bytes(b"ordinary-child-exit-only"),
            policy_generation: Generation::new(1)?,
            source_digest: Digest32::of_bytes(&fs::read(&program)?),
            worker_id: StableId::new("external-cli-child")?,
            profile_id: StableId::new("ordinary-exit-only")?,
            working_directory: workspace,
            observer_deadline: Duration::from_secs(8),
        },
        program,
        Vec::new(),
    )?;
    let queued = host
        .writer()
        .prepare_operation(
            registration.operation(StableId::new("external-cli-effect")?)?,
            "hepta.ordinary-cpu.exit.v1",
            &registration.payload_json()?,
        )
        .await?;
    let binding = host
        .writer()
        .final_use_binding(&queued, DESTINATION)
        .await?;
    let proposal = FinalUseGrant {
        schema_version: 1,
        signer_id: "external-cli-issuer".to_owned(),
        authority_epoch: 1,
        grant_id: "external-cli-exact-grant".to_owned(),
        nonce: [143; 32],
        binding: binding.clone(),
        not_before_unix_ms: u64::try_from(now.as_millis())? - 100,
        expires_at_unix_ms: u64::try_from(now.as_millis())? + 60_000,
    };
    let seed_path = root.join("issuer.seed");
    private_file(&seed_path, &[141; 32])?;
    let signed = sign_with_real_cli(&seed_path, &proposal)?;
    issuer.verifying_key().verify_strict(
        &signed.grant.signing_bytes()?,
        &ed25519_dalek::Signature::from_slice(&signed.signature)?,
    )?;
    assert_eq!(signed.grant, proposal);
    let grant_path = root.join("signed-grant.json");
    private_file(&grant_path, &serde_json::to_vec(&signed)?)?;
    let courier = SignedFinalUseGrantCourier::open(
        &grant_path,
        rustix::process::geteuid().as_raw(),
        authority.clone(),
        &binding,
    )?;
    let pool = SqliteConfig::from_sqlite_home(AbsolutePathBuf::try_from(root.clone())?)
        .open_durable_evidence_pool(&root.join("original-child-owner.sqlite"))
        .await?;
    sqlx::raw_sql(include_str!(
        "../../hepta-infer-worker-host/ordinary_cpu_owner.sql"
    ))
    .execute(&pool)
    .await?;
    let target = Arc::new(
        OrdinaryCpuTarget::from_migrated_pool(registration, authority.clone(), pool.clone())
            .await?,
    );
    let host = courier.attach_to_host(host, target)?;
    let dispatched = host
        .dispatch_to_with_grant_provider(DESTINATION, queued.clone())
        .await?;
    assert_eq!(dispatched.state, LocalOutcomeState::Indeterminate);
    let deadline = tokio::time::Instant::now() + Duration::from_secs(8);
    tokio::time::timeout_at(deadline, async {
        loop {
            host.reconcile(1).await?;
            if host.writer().status("external-cli-effect").await? == LocalOutcomeState::Committed {
                break;
            }
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
        TestResult::Ok(())
    })
    .await??;
    assert_eq!(
        host.writer().status("external-cli-effect").await?,
        LocalOutcomeState::Committed
    );
    assert!(
        host.dispatch_to_with_grant_provider(DESTINATION, queued)
            .await
            .is_err(),
        "original nonce must refuse replay even after observed exit"
    );
    let counts: (i64, i64, i64) = sqlx::query_as("SELECT (SELECT COUNT(*) FROM ordinary_cpu_entries), (SELECT COUNT(*) FROM destination_operation_dedupe), (SELECT COUNT(*) FROM ordinary_cpu_entries WHERE terminal_receipt IS NOT NULL)").fetch_one(&pool).await?;
    assert_eq!(counts, (1, 1, 1));
    assert_eq!(authority.capacity()?.used_nonces, 1);
    host.writer().release().await?;
    // This is only a real ordinary Child exit. No U/C/A quota refund, model
    // efficacy, aggregate terminality or installed beneficial release follows.
    Ok(())
}
