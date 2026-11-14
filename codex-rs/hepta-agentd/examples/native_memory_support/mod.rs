//! Controlled qualification issuer and actual durable-owner bootstrap.
//! This issuer is not a production supervisor or GitHub permission verifier.

use std::io::Write;
use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_agentd::AgentdConfig;
use codex_hepta_agentd::AgentdProductionWriterHost;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_memory::*;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use serde::Serialize;

pub fn owner() -> anyhow::Result<AgentId> {
    Ok(AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2ceb")?)
}
pub fn now_ms() -> anyhow::Result<u64> {
    Ok(std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)?
        .as_millis()
        .try_into()?)
}
pub fn retain(path: &Path, value: &impl Serialize) -> anyhow::Result<()> {
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)?;
    serde_json::to_writer_pretty(&mut file, value)?;
    file.write_all(b"\n")?;
    file.sync_all()?;
    Ok(())
}

pub async fn prepare(root: &Path) -> anyhow::Result<()> {
    std::fs::create_dir(root)?;
    let fleet = HeptaFleetRoot::parse(root.join("fleet"))?;
    let registry = FleetRegistry::initialize(fleet.clone())?;
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace)?;
    let record = registry.register(AgentManifest::new(
        owner()?,
        WorkspaceBinding::new(&workspace, &fleet)?,
        ResourceBudget::local_default(),
    )?)?;
    registry.compare_and_transition(&owner()?, 0, AgentLifecycle::Starting)?;
    let store = CognitiveStore::open(&record.layout).await?;
    let anchor = store.recovery_anchor().await?;
    // Complete the database handoff before publishing the retained logical cut.
    store.close().await;
    retain(&root.join("anchor.json"), &anchor)?;
    let hash = Digest32::of_bytes(&std::fs::read(root.join("anchor.json"))?).to_string();
    retain(
        &root.join("prepare.json"),
        &serde_json::json!({"anchor_sha256": hash, "source_owner": "actual CognitiveStore", "authority": "controlled qualification issuer", "production_qualified": false}),
    )?;
    println!(
        "{}",
        serde_json::json!({"prepared": root, "anchor_sha256": hash})
    );
    Ok(())
}

pub fn config(root: &Path) -> anyhow::Result<(AgentdConfig, FleetRegistry)> {
    let fleet = HeptaFleetRoot::parse(root.join("fleet"))?;
    let registry = FleetRegistry::open_existing(fleet)?;
    let record = registry
        .load()?
        .agent(&owner()?)
        .cloned()
        .ok_or_else(|| anyhow::anyhow!("registered owner absent"))?;
    let config = AgentdConfig::load(
        root.join("fleet"),
        owner()?,
        1,
        record.layout.home_root().to_path_buf(),
        record.layout.run_root().to_path_buf(),
        record.layout.home_root().to_path_buf(),
        root.join("workspace"),
    )?;
    Ok((config, registry))
}

struct ControlledVerifier {
    expected: ProductionAuthorityLease,
    withdrawn: Arc<AtomicBool>,
}
impl ProductionAuthorityVerifier for ControlledVerifier {
    fn verify(
        &self,
        authority: &ProductionAuthorityLease,
        expected_agent: &AgentId,
    ) -> Result<(), String> {
        if authority != &self.expected
            || &authority.agent_id != expected_agent
            || self.withdrawn.load(Ordering::SeqCst)
        {
            Err("controlled qualification authority differs or is withdrawn".to_string())
        } else {
            Ok(())
        }
    }
}

pub async fn open_host(
    root: &Path,
    config: &AgentdConfig,
    anchor_sha256: &str,
) -> anyhow::Result<(Arc<AgentdProductionWriterHost>, Arc<AtomicBool>)> {
    let bytes = std::fs::read(root.join("anchor.json"))?;
    anyhow::ensure!(
        Digest32::of_bytes(&bytes).to_string() == anchor_sha256,
        "independently retained anchor differs"
    );
    let anchor: CognitiveRecoveryAnchor = serde_json::from_slice(&bytes)?;
    let token = ProductionAuthorityToken::from_verified_bytes(
        format!("controlled-native-trial:{anchor_sha256}").into_bytes(),
    )?;
    let authority = ProductionAuthorityLease::from_verified_parts(
        owner()?,
        Sha256Digest::for_bytes(b"controlled-native-ci-authority-v1"),
        1,
        1,
        now_ms()? / 1000 + 3600,
        token,
    )?;
    let withdrawn = Arc::new(AtomicBool::new(false));
    let verifier = Arc::new(ControlledVerifier {
        expected: authority.clone(),
        withdrawn: Arc::clone(&withdrawn),
    });
    let host = AgentdProductionWriterHost::open(
        config,
        CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
        authority,
        verifier,
        "native-ci-source-owner",
        1,
    )
    .await?;
    Ok((Arc::new(host), withdrawn))
}

pub fn source(bytes: Vec<u8>, event_key: &str) -> anyhow::Result<SourceDraft> {
    Ok(SourceDraft {
        scope: CognitiveScope::AgentPrivate,
        kind: LedgerSourceKind::ExplicitMemoryDirective,
        event_key: event_key.to_string(),
        content: bytes,
        observed_at_unix_seconds: (now_ms()? / 1000).try_into()?,
    })
}

pub fn revision(source: &SourceDraft) -> anyhow::Result<MemoryRevisionDraft> {
    Ok(MemoryRevisionDraft {
        scope: source.scope.clone(),
        content: String::from_utf8(source.content.clone())?,
        verification: MemoryVerification::Verified,
        lifecycle: MemoryLifecycleState::Active,
        valid_from_unix_seconds: source.observed_at_unix_seconds,
        valid_to_unix_seconds: None,
        citations: vec![],
    })
}

pub fn claim(
    document: &MemoryCellDocumentV1,
    production: ProductionCognitiveMutationReceiptV1,
) -> anyhow::Result<MemoryCellSourceClaimV1> {
    let hash = production.source_content_sha256.as_str();
    let misc = Digest32::of_bytes(b"native-ci-integration-profile-v1").to_string();
    let observed = production.source_observed_at_unix_seconds as u64 * 1000;
    let event = serde_json::from_value(serde_json::json!({
        "eventId": format!("hnmf:{hash}"), "episodeId": "episode:native-ci-import",
        "scope": {"kind":"agent_private", "agentId": production.owner_agent_id.as_str()},
        "observedInterval": {"startUnixMs": observed, "endUnixMs": null},
        "modalitySpans": [{"spanId": "span:imported-ci-document", "modality": "text", "assetSha256": hash,
            "range": {"kind":"byte_range", "start": 0, "end": production.write.memory.content.len()},
            "preprocessorManifestSha256": misc, "featureBlobSha256": null, "symbolicProjectionSha256": null,
            "uncertaintyPpm": 0, "privacyClass": "agent_private", "redactionMaskSha256": null}],
        "crossModalBindings": [], "semanticKeys": [document.key.stable_key()?],
        "provenance": [{"sourceId": production.write.source.source_id.as_str(), "sourceRevision": production.write.source.revision, "sourceSha256": hash, "observedAtUnixMs": observed}],
        "verification": "verified", "retentionPolicy": {"kind":"persistent", "retainUntilUnixMs": null},
        "objectiveDigest": misc, "nduStateDigest": misc, "causalParents": [], "temporalNeighbors": [],
        "behaviorPropensityPpm": null, "lifecycle": {"state":"active"}
    }))?;
    Ok(MemoryCellSourceClaimV1 { event, production })
}
