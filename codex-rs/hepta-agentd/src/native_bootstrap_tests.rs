//! Startup composition checks reuse the original writer/owner fixtures. No
//! provider, runtime health probe, grant or native attach may run on rejection.

use super::*;
use crate::NativeHostedRuntimeConfig;
use crate::intelligence_product::tests::objective_queued_fixtures::CanonicalObjectiveTestOwners;
use pretty_assertions::assert_eq;

fn native_config(
    hosted_turn: Option<NativeHostedRuntimeConfig>,
    attached: Arc<AtomicUsize>,
) -> Result<AgentdNativeRuntimeConfig> {
    Ok(AgentdNativeRuntimeConfig {
        model: NativeResponsesTargetConfig {
            responses_url: "http://127.0.0.1:9/v1/responses".to_owned(),
            bearer: None,
            idle_timeout: Duration::from_secs(1),
            max_request_bytes: 8192,
            max_stream_bytes: 8192,
        },
        http: Arc::new(HttpClientFactory::new(OutboundProxyPolicy::ReqwestDefault)),
        runtime_destination: "destination:native-preflight".to_owned(),
        required_hosts: vec!["preflight-must-not-probe".to_owned()],
        max_tool_output_bytes: 4096,
        policy_generation: Generation::new(7)?,
        final_use_authority_destination: "destination:original-owner".to_owned(),
        compiler: Arc::new(NoToolCompiler),
        hosted_turn,
        attach: Box::new(move |_| {
            attached.fetch_add(1, Ordering::SeqCst);
            Ok(())
        }),
    })
}

fn canonical() -> Result<NativeHostedRuntimeConfig> {
    Ok(NativeHostedRuntimeConfig::CanonicalObjective {
        agent: Arc::new(agent()),
        scope: NativeTurnScope {
            cell_id: StableId::new("cell:native-preflight")?,
            organ_id: StableId::new("organ:native-preflight")?,
            final_scope_id: StableId::new("organ:native-preflight")?,
        },
    })
}

fn rejected(config: &AgentdConfig, expected: &str) -> Result<()> {
    let error = config
        .validate_native_composition()
        .err()
        .context("incomplete native composition was accepted")?;
    anyhow::ensure!(
        error.to_string().contains(expected),
        "unexpected native preflight error: {error}"
    );
    Ok(())
}

#[tokio::test]
async fn native_bootstrap_rejects_missing_writer_before_runtime_setup() -> Result<()> {
    let (_temporary, config, _registry, recovered) =
        original_writer_fixture(AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c91")?).await?;
    let writer = recovered.writer();
    let before = writer.recovery_anchor().await?;
    let control_socket = config.identity().control_socket.clone();
    let attached = Arc::new(AtomicUsize::new(0));
    // Direct/External native composition is not forced into canonical owners.
    // Its missing original writer must still fail at the first run boundary.
    let config = config.with_native_runtime(native_config(None, attached.clone())?)?;
    let error = crate::run(config, codex_arg0::Arg0DispatchPaths::default())
        .await
        .err()
        .context("native runtime accepted no original writer")?;
    assert!(
        error
            .to_string()
            .contains("independently recovered production writer host")
    );
    assert_eq!(attached.load(Ordering::SeqCst), 0);
    assert_eq!(writer.recovery_anchor().await?, before);
    assert!(!control_socket.exists());
    Ok(())
}

#[tokio::test]
async fn native_bootstrap_requires_complete_canonical_inputs_before_owner_attachment() -> Result<()>
{
    let (temporary, config, _registry, recovered) =
        original_writer_fixture(AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c92")?).await?;
    let (owners, runner) =
        CanonicalObjectiveTestOwners::new(&temporary.path().join("original-authority.json"))?;
    let attached = Arc::new(AtomicUsize::new(0));
    let mut config =
        config.with_native_runtime(native_config(Some(canonical()?), attached.clone())?)?;
    rejected(&config, "requires both original intelligence owners")?;
    config = config.with_intelligence_product_runner(runner)?;
    rejected(
        &config,
        "runner and its host-owned invocation provider together",
    )?;
    config = config.with_intelligence_invocation_provider(owners.clone())?;
    rejected(&config, "requires the original objective profile")?;
    config = config.with_objective_profile_file(temporary.path().join("not-opened-profile.json"));
    rejected(
        &config,
        "requires original AuthBus trust and replay checkpoint together",
    )?;
    config = config.with_authbus_trust_file(temporary.path().join("not-opened-trust.json"));
    rejected(
        &config,
        "requires original AuthBus trust and replay checkpoint together",
    )?;
    config =
        config.with_authbus_checkpoint_file(temporary.path().join("not-opened-checkpoint.json"));
    rejected(&config, "independently recovered production writer host")?;
    config = config.with_production_writer_host(Arc::new(recovered))?;
    rejected(&config, "configured original production operation service")?;
    // These dependency checks inspect configuration only. The owner fixture's
    // seven-stage builder and all runtime callbacks remain untouched.
    assert_eq!(owners.calls.load(Ordering::SeqCst), 0);
    assert_eq!(attached.load(Ordering::SeqCst), 0);
    assert!(!temporary.path().join("not-opened-profile.json").exists());
    assert!(!temporary.path().join("not-opened-trust.json").exists());
    assert!(!temporary.path().join("not-opened-checkpoint.json").exists());
    Ok(())
}

#[tokio::test]
async fn native_bootstrap_rejects_missing_evaluation_trust_before_runtime_setup() -> Result<()> {
    let (temporary, config, _registry, recovered) =
        original_writer_fixture(AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c95")?).await?;
    let (owners, _trusted_runner) =
        CanonicalObjectiveTestOwners::new(&temporary.path().join("original-authority.json"))?;
    let authority_path = temporary.path().join("not-opened-authority.json");
    // A valid verifier does not supply activated evaluation trust. Startup
    // must reject the runner before attempting any authority-file read.
    let runner = Arc::new(crate::AgentdIntelligenceProductRunnerV1::new(
        authority_path.clone(),
        crate::IntelligenceAuthorityVerifierV1 {
            signer_id: "unused-preflight-verifier".to_owned(),
            verifying_key: SigningKey::from_bytes(&[29; 32]).verifying_key().to_bytes(),
        },
    )?);
    let writer = recovered.writer();
    let before = writer.recovery_anchor().await?;
    let control_socket = config.identity().control_socket.clone();
    let app_server_socket = config.identity().app_server_socket.clone();
    let attached = Arc::new(AtomicUsize::new(0));
    let config = config
        .with_intelligence_product_runner(runner)?
        .with_intelligence_invocation_provider(owners.clone())?;
    // Ordinary compatibility can hold these owners without selecting native
    // canonical preparation. The prerequisite belongs to that explicit mode.
    config.validate_native_composition()?;
    let config = config
        .with_native_runtime(native_config(Some(canonical()?), attached.clone())?)?
        .with_objective_profile_file(temporary.path().join("not-opened-profile.json"))
        .with_authbus_trust_file(temporary.path().join("not-opened-trust.json"))
        .with_authbus_checkpoint_file(temporary.path().join("not-opened-checkpoint.json"))
        .with_production_writer_host(Arc::new(recovered))?;
    let error = crate::run(config, codex_arg0::Arg0DispatchPaths::default())
        .await
        .err()
        .context("canonical native runtime accepted no configured evaluation trust")?;
    assert!(
        error
            .to_string()
            .contains("configured host-authenticated evaluation trust")
    );
    assert_eq!(owners.calls.load(Ordering::SeqCst), 0);
    assert_eq!(attached.load(Ordering::SeqCst), 0);
    assert_eq!(writer.recovery_anchor().await?, before);
    assert!(!control_socket.exists());
    assert!(!app_server_socket.exists());
    assert!(!authority_path.exists());
    assert!(!temporary.path().join("not-opened-profile.json").exists());
    assert!(!temporary.path().join("not-opened-trust.json").exists());
    assert!(!temporary.path().join("not-opened-checkpoint.json").exists());
    Ok(())
}

#[tokio::test]
async fn native_bootstrap_preserves_non_native_runner_only_compatibility() -> Result<()> {
    let (temporary, config, _registry, _recovered) =
        original_writer_fixture(AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c93")?).await?;
    let (owners, runner) =
        CanonicalObjectiveTestOwners::new(&temporary.path().join("original-authority.json"))?;
    let config = config.with_intelligence_product_runner(runner)?;
    config.validate_native_composition()?;
    let attached = Arc::new(AtomicUsize::new(0));
    let config = config.with_native_runtime(native_config(None, attached.clone())?)?;
    rejected(
        &config,
        "runner and its host-owned invocation provider together",
    )?;
    assert_eq!(owners.calls.load(Ordering::SeqCst), 0);
    assert_eq!(attached.load(Ordering::SeqCst), 0);
    Ok(())
}

#[tokio::test]
async fn native_bootstrap_rejects_provider_without_its_runner_only_when_native_selected()
-> Result<()> {
    let (temporary, config, _registry, _recovered) =
        original_writer_fixture(AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c94")?).await?;
    let (owners, _runner) =
        CanonicalObjectiveTestOwners::new(&temporary.path().join("original-authority.json"))?;
    let config = config.with_intelligence_invocation_provider(owners.clone())?;
    config.validate_native_composition()?;
    let attached = Arc::new(AtomicUsize::new(0));
    let config = config.with_native_runtime(native_config(None, attached.clone())?)?;
    rejected(
        &config,
        "runner and its host-owned invocation provider together",
    )?;
    assert_eq!(owners.calls.load(Ordering::SeqCst), 0);
    assert_eq!(attached.load(Ordering::SeqCst), 0);
    Ok(())
}
