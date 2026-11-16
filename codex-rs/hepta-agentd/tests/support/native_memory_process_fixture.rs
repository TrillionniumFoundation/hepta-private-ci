//! Controlled external host preparation; the daemon independently verifies it.

use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;

use anyhow::Result;
use codex_hepta_agentd::*;
use codex_hepta_contracts::*;
use codex_hepta_fleet::*;
use codex_hepta_memory::*;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde::Serialize;
use serde_json::Value;
use serde_json::json;
use sha2::Digest;
use sha2::Sha256;

pub use super::native_memory_process_ndu::feed;
use super::native_memory_process_ndu::prepare_ndu;
use super::native_memory_process_ndu::shadow;
pub use super::native_memory_process_ndu::sign;
use super::native_memory_process_ndu::stub_model;
use super::native_memory_process_objective as objective;

pub struct Fixture {
    pub root: PathBuf,
    pub identity: AgentdIdentity,
    pub registry: FleetRegistry,
    pub bootstrap: PathBuf,
    pub bootstrap_sha256: Digest32,
    pub objective: objective::ObjectiveFixture,
    pub document: MemoryCellDocumentV1,
    pub model: NativeMemoryModelConfigV1,
}

pub fn now_ms() -> u64 {
    SystemAuthorityClock.now_unix_ms().unwrap()
}
fn d(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

pub fn retain(path: &Path, value: &impl Serialize) -> Result<()> {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)?;
    serde_json::to_writer_pretty(&mut file, value)?;
    file.write_all(b"\n")?;
    file.sync_all()?;
    Ok(())
}

pub fn pin(path: &Path) -> Result<Value> {
    Ok(json!({"path":path,"sha256":Digest32::of_bytes(&std::fs::read(path)?).to_string()}))
}

pub fn file_sha(path: &Path) -> Result<String> {
    let mut file = std::fs::File::open(path)?;
    let mut hasher = Sha256::new();
    let mut bytes = [0_u8; 65_536];
    loop {
        let count = file.read(&mut bytes)?;
        if count == 0 {
            break;
        }
        hasher.update(&bytes[..count]);
    }
    Ok(format!("{:x}", hasher.finalize()))
}

#[derive(Serialize)]
struct SourceLeasePayload {
    schema: String,
    signer_id: String,
    agent_id: AgentId,
    authority_epoch: u64,
    owner_epoch: u64,
    expires_at_unix_seconds: u64,
    opaque_token: String,
}

pub async fn prepare(
    root: PathBuf,
    trained: Option<(NativeMemoryModelConfigV1, Vec<u8>)>,
) -> Result<Fixture> {
    std::fs::create_dir(&root)?;
    std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700))?;
    let fleet = HeptaFleetRoot::parse(root.join("fleet"))?;
    let registry = FleetRegistry::initialize(fleet.clone())?;
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace)?;
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c71")?;
    let record = registry.register(AgentManifest::new(
        owner.clone(),
        WorkspaceBinding::new(&workspace, &fleet)?,
        ResourceBudget::local_default(),
    )?)?;
    registry.compare_and_transition(
        &owner,
        /*expected_generation*/ 0,
        AgentLifecycle::Starting,
    )?;
    let config = AgentdConfig::load(
        root.join("fleet"),
        owner.clone(),
        /*spawn_generation*/ 1,
        record.layout.home_root().into(),
        record.layout.run_root().into(),
        record.layout.home_root().into(),
        workspace,
    )?;
    let identity = config.identity().clone();
    let home = &identity.home_root;
    std::fs::set_permissions(home, std::fs::Permissions::from_mode(0o700))?;
    let now = now_ms();
    let payload = SourceLeasePayload {
        schema: "hepta.memory-cell.source-lease.v1".into(),
        signer_id: "process.source.issuer".into(),
        agent_id: owner.clone(),
        authority_epoch: 23,
        owner_epoch: 31,
        expires_at_unix_seconds: now / 1000 + 600,
        opaque_token: "controlled-external-process-source-token".into(),
    };
    let signing_bytes = serde_json::to_vec(&payload)?;
    let signer = SigningKey::from_bytes(&[116; 32]);
    retain(
        &home.join("source-grant.json"),
        &json!({"payload":payload,"signature":signer.sign(&signing_bytes).to_bytes().to_vec()}),
    )?;
    let authority = ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        Sha256Digest::for_bytes(&signing_bytes),
        /*authority_epoch*/ 23,
        /*owner_epoch*/ 31,
        now / 1000 + 600,
        ProductionAuthorityToken::from_verified_bytes(
            b"controlled-external-process-source-token".to_vec(),
        )?,
    )?;
    let expected = authority.clone();
    let verifier = Arc::new(move |lease: &ProductionAuthorityLease, agent: &AgentId| {
        if lease == &expected && &expected.agent_id == agent {
            Ok(())
        } else {
            Err("external fixture lease mismatch".into())
        }
    });
    let store = CognitiveStore::open(&identity.layout).await?;
    let empty = store.recovery_anchor().await?;
    store.close().await;
    let host = AgentdProductionWriterHost::open(
        &config,
        CognitiveRecoveryRequirement::ExactCurrentCut(&empty),
        authority,
        verifier,
        "process-source",
        /*lease_generation*/ 1,
    )
    .await?;
    let (mut model, document_bytes) = trained.unwrap_or_else(|| {
        (
            stub_model(home),
            serde_json::to_vec(&MemoryCellDocumentV1 {
                schema_version: 1,
                key: MemoryCellKeyV1 {
                    role: MemoryCellRoleV1::Procedural,
                    entity: "case-one".into(),
                    relation: "repair".into(),
                },
                value: "order".into(),
            })
            .unwrap(),
        )
    });
    let document: MemoryCellDocumentV1 = serde_json::from_slice(&document_bytes)?;
    let source = SourceDraft {
        scope: CognitiveScope::AgentPrivate,
        kind: LedgerSourceKind::ExplicitMemoryDirective,
        event_key: "process-fixture-source".into(),
        content: document_bytes,
        observed_at_unix_seconds: (now / 1000).try_into()?,
    };
    let production = host
        .remember_with_kg(
            &CognitiveAccess::agent_private(owner.clone()),
            &source,
            &MemoryDraft {
                stable_key: document.key.stable_key()?,
                revision: MemoryRevisionDraft {
                    scope: source.scope.clone(),
                    content: String::from_utf8(source.content.clone())?,
                    verification: MemoryVerification::Verified,
                    lifecycle: MemoryLifecycleState::Active,
                    valid_from_unix_seconds: source.observed_at_unix_seconds,
                    valid_to_unix_seconds: None,
                    citations: vec![],
                },
            },
            &KgFactSetDraft::default(),
        )
        .await?;
    let root_hash = production.source_content_sha256.as_str();
    let observed = production.source_observed_at_unix_seconds as u64 * 1000;
    let misc = d("process fixture source profile").to_string();
    let event = json!({"eventId":format!("hnmf:{root_hash}"),"episodeId":"process.source.episode",
        "scope":{"kind":"agent_private","agentId":owner.as_str()},"observedInterval":{"startUnixMs":observed,"endUnixMs":null},
        "modalitySpans":[{"spanId":"process.source.span","modality":"text","assetSha256":root_hash,
            "range":{"kind":"byte_range","start":0,"end":production.write.memory.content.len()},"preprocessorManifestSha256":misc,
            "featureBlobSha256":null,"symbolicProjectionSha256":null,"uncertaintyPpm":0,"privacyClass":"agent_private","redactionMaskSha256":null}],
        "crossModalBindings":[],"semanticKeys":[document.key.stable_key()?],"provenance":[{"sourceId":production.write.source.source_id.as_str(),
            "sourceRevision":production.write.source.revision,"sourceSha256":root_hash,"observedAtUnixMs":observed}],
        "verification":"verified","retentionPolicy":{"kind":"persistent","retainUntilUnixMs":null},"objectiveDigest":misc,"nduStateDigest":misc,
        "causalParents":[],"temporalNeighbors":[],"behaviorPropensityPpm":null,"lifecycle":{"state":"active"}});
    retain(
        &home.join("source-claim.json"),
        &json!({"event":event,"production":production}),
    )?;
    retain(
        &home.join("source-anchor.json"),
        &host.writer().recovery_anchor().await?,
    )?;
    drop(host);
    std::fs::create_dir(&model.receipt_directory)?;
    if !model.checkpoint.exists() {
        std::fs::create_dir(&model.checkpoint)?;
        retain(
            &model.checkpoint.join("lineage.json"),
            &json!({"roots":[root_hash],"scope":model.scope}),
        )?;
        model.pins.manifest_sha256 =
            Digest32::of_bytes(&std::fs::read(model.checkpoint.join("lineage.json"))?).to_string();
    }
    retain(&home.join("model.json"), &model)?;
    let objective = objective::prepare(&identity, &root, now).await?;
    let ndu = prepare_ndu(home, &identity, objective.digest, now)?;
    let descriptor = json!({"schema":"hepta.memory-cell.process-bootstrap.v1","trust_profile":"linux-local-compatibility-v1",
        "agent_id":owner.as_str(),"spawn_generation":1,"linux_boot_id":std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?.trim(),
        "control_socket":home.join("memory-current.sock"),"source":{"anchor":pin(&home.join("source-anchor.json"))?,
            "grant":pin(&home.join("source-grant.json"))?,"signer_id":"process.source.issuer","verifying_key":signer.verifying_key().to_bytes(),
            "lease_id":"process-source","lease_generation":1,"key":document.key,"claim":pin(&home.join("source-claim.json"))?,"model":pin(&home.join("model.json"))?},
        "ndu":ndu,"shadow":shadow(home)});
    let bootstrap = home.join("memory-bootstrap.json");
    retain(&bootstrap, &descriptor)?;
    let bootstrap_sha256 = Digest32::of_bytes(&std::fs::read(&bootstrap)?);
    drop(config);
    Ok(Fixture {
        root,
        identity,
        registry,
        bootstrap,
        bootstrap_sha256,
        objective,
        document,
        model,
    })
}
