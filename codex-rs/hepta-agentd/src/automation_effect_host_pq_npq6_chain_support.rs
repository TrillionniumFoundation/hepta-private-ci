//! Strict public test material + the real signed ordinary provider configuration.
use super::*;
use serde::Deserialize;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Manifest {
    schema: String,
    chain_source: String,
    configuration_sha256: String,
    application_profile: String,
    network: String,
    parameters: String,
    genesis: String,
    network_policy: String,
    cases: Vec<Case>,
    public_test_material: bool,
    target_admitted: bool,
    production_activation: bool,
}
#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct Case {
    name: String,
    target_block: String,
    packet_sha256: String,
    expected_success: bool,
}
pub(super) struct Material {
    root: PathBuf,
    binary: PathBuf,
    digest: Sha256Digest,
    manifest: Manifest,
}
pub(super) struct Ready {
    pub fixture: Fixture,
    pub setup: PqFixture,
    pub host: Arc<AgentdAutomationEffectHost>,
    pub intent: AuthorizedEffectIntent,
    pub grant: SignedFinalUseGrant,
    pub wire: Vec<u8>,
    pub provider_intent: ProviderEffectIntent,
    pub namespace: PathBuf,
    pub block: String,
    pub now: u64,
}
impl Material {
    pub fn read() -> anyhow::Result<Self> {
        let source = std::env::var("HEPTA_PON_CHAIN_SOURCE")?;
        anyhow::ensure!(
            source.len() == 40
                && source
                    .bytes()
                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        );
        let binary = PathBuf::from(std::env::var("HEPTA_PON_CHAIN_BINARY")?).canonicalize()?;
        let digest = Sha256Digest::parse(std::env::var("HEPTA_PON_CHAIN_SHA256")?)
            .map_err(anyhow::Error::msg)?;
        anyhow::ensure!(Sha256Digest::for_bytes(&fs::read(&binary)?) == digest);
        let selected = PathBuf::from(std::env::var("HEPTA_PON_NPQ6_FIXTURE_OUT")?);
        let root = selected.canonicalize()?;
        anyhow::ensure!(selected.is_absolute() && selected == root);
        let expected = Sha256Digest::parse(std::env::var("HEPTA_PON_NPQ6_MATERIAL_SHA256")?)
            .map_err(anyhow::Error::msg)?;
        let bytes = read_protected_file(&root.join("manifest.json"), 32_768, "NPQ6 test material")?;
        anyhow::ensure!(Sha256Digest::for_bytes(&bytes) == expected);
        let manifest: Manifest = serde_json::from_slice(&bytes)?;
        anyhow::ensure!(
            manifest.schema == "ordinary-pon-npq6-paired-material-v1"
                && manifest.chain_source == source
                && manifest.public_test_material
                && !manifest.target_admitted
                && !manifest.production_activation
                && manifest.application_profile == "pon-native-pq-application-v6"
                && manifest.cases.len() == 4
        );
        for (case, (name, succeeds)) in manifest.cases.iter().zip([
            ("task", true),
            ("evaluator", true),
            ("owner-mismatch", false),
            ("provider-loader", true),
        ]) {
            anyhow::ensure!(case.name == name && case.expected_success == succeeds);
            Sha256Digest::parse(case.target_block.clone()).map_err(anyhow::Error::msg)?;
            Sha256Digest::parse(case.packet_sha256.clone()).map_err(anyhow::Error::msg)?;
        }
        for digest in [
            &manifest.configuration_sha256,
            &manifest.network,
            &manifest.parameters,
            &manifest.genesis,
            &manifest.network_policy,
        ] {
            Sha256Digest::parse(digest.clone()).map_err(anyhow::Error::msg)?;
        }
        let config = read_protected_file(
            &root.join("application.json"),
            262_144,
            "NPQ6 public configuration",
        )?;
        anyhow::ensure!(Sha256Digest::for_bytes(&config).as_str() == manifest.configuration_sha256);
        Ok(Self {
            root,
            binary,
            digest,
            manifest,
        })
    }

    pub async fn prepare(&self, name: &str) -> anyhow::Result<Ready> {
        let case = self
            .manifest
            .cases
            .iter()
            .find(|case| case.name == name)
            .context("fixed fixture case")?;
        let fixture = Fixture::new().await?;
        let scope = Sha256Digest::for_bytes(format!("ordinary-npq6-{name}").as_bytes());
        let directory = self.root.join(name);
        anyhow::ensure!(directory.canonicalize()? == directory);
        let namespace = directory.join("receiver");
        anyhow::ensure!(namespace.canonicalize()? == namespace);
        let wire = read_protected_file(
            &directory.join("packet.bin"),
            crate::MAX_AUTOMATION_EFFECT_PACKET_V1_BYTES as u64,
            "actual NPQ6 fixture packet",
        )?;
        anyhow::ensure!(
            wire.starts_with(b"PQP6")
                && !wire.is_empty()
                && wire.len() <= crate::MAX_AUTOMATION_EFFECT_PACKET_V1_BYTES
        );
        anyhow::ensure!(Sha256Digest::for_bytes(&wire).as_str() == case.packet_sha256);
        let mut setup = PqFixture::http("http://127.0.0.1:9", &scope)?;
        setup.config["contract_id"] = serde_json::json!(format!("ordinary-npq6-{name}"));
        setup.config["provider"] = serde_json::json!({
            "provider_kind":"trillionnium-pon-local-npq6-v1",
            "chain_binary":self.binary,"chain_binary_sha256":self.digest.as_str(),
            "chain_store":namespace,"chain_application":{
                "configuration":self.root.join("application.json"),
                "configuration_sha256":self.manifest.configuration_sha256,
                "application_profile":self.manifest.application_profile,
                "network":self.manifest.network,"parameters":self.manifest.parameters,
                "genesis":self.manifest.genesis,"network_policy":self.manifest.network_policy,
                "owner":{"profile":"network_v2"}},
            "chain_workers":1,"chain_min_confirmation_depth":1,
            "chain_min_confirmation_work_depth_hex":format!("{}02","00".repeat(63)),
            "timeout_ms":30000
        });
        let provider: ProviderConfig = serde_json::from_value(setup.config["provider"].clone())?;
        let mut contract = b"hepta.agentd.pon-provider-contract.pq.npq6.v1\0".to_vec();
        contract.extend(serde_json::to_vec(&serde_json::json!({
            "provider_scope":setup.config["provider_scope"],"destination_id":setup.config["destination_id"],
            "final_use_scope_sha256":setup.config["final_use_scope_sha256"],"provider":provider}))?);
        setup.sign_contract(&Sha256Digest::for_bytes(&contract))?;
        let now = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
        setup.now.store(now, Ordering::SeqCst);
        setup.publish_feed(&setup.feed(setup.head.clone(), now - 1000, now + 60000)?)?;
        let mut intent = effect_intent(&scope);
        intent.payload_digest = Sha256Digest::for_bytes(&wire);
        prepare_effect(&fixture, now.saturating_sub(10), &intent).await?;
        let grant = setup.grant_at(&intent, now - 1000, now + 30000)?;
        let host = Arc::new(AgentdAutomationEffectHost::open(
            &fixture.identity,
            &setup.config_path,
        )?);
        anyhow::ensure!(
            host.authority.authentication_profile() == FinalUseAuthenticationProfile::MlDsa65V2
        );
        let key = ProviderEffectKey::for_taskflow_v2(
            "provider/fixture-v1",
            &fixture.identity.agent_id,
            &intent.run_id,
            &intent.step_id,
        )
        .map_err(|error| anyhow::anyhow!("{error:?}"))?;
        let provider_intent = ProviderEffectIntent::new(key, intent.payload_digest.clone());
        Ok(Ready {
            fixture,
            setup,
            host,
            intent,
            grant,
            wire,
            provider_intent,
            namespace,
            block: case.target_block.clone(),
            now,
        })
    }
}
pub(super) async fn owner_released(host: &Arc<AgentdAutomationEffectHost>) -> anyhow::Result<()> {
    tokio::time::timeout(Duration::from_secs(2), async {
        while Arc::strong_count(host) != 1 {
            tokio::task::yield_now().await;
        }
    })
    .await?;
    Ok(())
}

pub(super) fn resign_provider(setup: &mut PqFixture) -> anyhow::Result<()> {
    let provider: ProviderConfig = serde_json::from_value(setup.config["provider"].clone())?;
    let mut bytes = b"hepta.agentd.pon-provider-contract.pq.npq6.v1\0".to_vec();
    bytes.extend(serde_json::to_vec(&serde_json::json!({
        "provider_scope":setup.config["provider_scope"],"destination_id":setup.config["destination_id"],
        "final_use_scope_sha256":setup.config["final_use_scope_sha256"],"provider":provider}))?);
    setup.sign_contract(&Sha256Digest::for_bytes(&bytes))
}
