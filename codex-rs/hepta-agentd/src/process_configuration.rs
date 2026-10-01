use std::path::PathBuf;

use crate::AgentdConfig;
use crate::CanonicalIntelligenceProviderProfileV1;
use crate::IntelligenceAuthorityVerifierV1;
use crate::LeasedMemoryRetrievalProviderV1;
use crate::compose_durable_abstain_intelligence_profile_v1;
use crate::load_plasticity_process_bootstrap_v1;
use crate::load_retrieval_learning_bootstrap_v1;
use codex_hepta_agent_components::types::Digest32;
use codex_utils_absolute_path::AbsolutePathBuf;
use std::ffi::OsString;

pub fn run_with_process_configuration<F>(configure: F) -> anyhow::Result<()>
where
    F: FnOnce(AgentdConfig) -> anyhow::Result<AgentdConfig> + Send + 'static,
{
    // Re-exec helpers share the daemon image but do not acquire its writer
    // authority. Preserve its alias home before dispatch without loading the
    // Fleet configuration or taking the parent's already-held writer flock.
    if let Some(home) =
        std::env::var_os(crate::HEPTA_AGENT_HOME_ENV).filter(|value| !value.is_empty())
    {
        let codex_home = AbsolutePathBuf::from_absolute_path(PathBuf::from(home))?;
        codex_utils_home_dir::set_process_codex_home_override(codex_home)?;
    }
    codex_arg0::arg0_dispatch_or_else(move |arg0_paths| async move {
        let mut config = AgentdConfig::from_process_environment()?;
        // Helper re-execs must reach arg0 dispatch before daemon-only flags.
        let mut args = std::env::args_os().skip(1);
        let mut authbus_trust = None;
        let mut runtime_module_profile = None;
        let mut intelligence_authority_file = None;
        let mut intelligence_authority_signer = None;
        let mut intelligence_authority_verifying_key = None;
        let mut canonical_intelligence_provider_profile = None;
        let mut plasticity_bootstrap_descriptor: Option<PathBuf> = None;
        let mut plasticity_bootstrap_descriptor_digest: Option<Digest32> = None;
        let mut retrieval_bootstrap_descriptor: Option<PathBuf> = None;
        let mut retrieval_bootstrap_descriptor_digest: Option<Digest32> = None;
        let mut retrieval_learning_descriptor: Option<PathBuf> = None;
        let mut retrieval_learning_descriptor_digest: Option<Digest32> = None;
        let mut objective_profile = None;
        let mut authbus_checkpoint = None;
        let mut evidence_trust = None;
        let mut automation_effect_host = None;
        let mut evidence_recovery_frontier = None;
        let mut evidence_recovery_frontier_trust = None;
        while let Some(flag) = args.next() {
            let path = args
                .next()
                .ok_or_else(|| anyhow::anyhow!("{flag:?} requires a path"))?;
            if flag == "--runtime-module-profile" {
                anyhow::ensure!(
                    runtime_module_profile.is_none(),
                    "duplicate --runtime-module-profile"
                );
                let value = path
                    .into_string()
                    .map_err(|_| anyhow::anyhow!("runtime module profile must be UTF-8"))?;
                runtime_module_profile = Some(value.parse::<crate::RuntimeModuleProfileV1>()?);
            } else if flag == "--authbus-trust-file" {
                anyhow::ensure!(authbus_trust.is_none(), "duplicate --authbus-trust-file");
                authbus_trust = Some(path);
            } else if flag == "--plasticity-bootstrap-descriptor" {
                anyhow::ensure!(
                    plasticity_bootstrap_descriptor.is_none(),
                    "duplicate --plasticity-bootstrap-descriptor"
                );
                plasticity_bootstrap_descriptor = Some(path.into());
            } else if flag == "--plasticity-bootstrap-descriptor-digest" {
                anyhow::ensure!(
                    plasticity_bootstrap_descriptor_digest.is_none(),
                    "duplicate --plasticity-bootstrap-descriptor-digest"
                );
                let value = path
                    .into_string()
                    .map_err(|_| anyhow::anyhow!("plasticity descriptor digest must be UTF-8"))?;
                plasticity_bootstrap_descriptor_digest =
                    Some(value.parse::<Digest32>().map_err(|error| {
                        anyhow::anyhow!("invalid plasticity descriptor digest: {error}")
                    })?);
            } else if flag == "--retrieval-bootstrap-descriptor" {
                anyhow::ensure!(
                    retrieval_bootstrap_descriptor.is_none(),
                    "duplicate --retrieval-bootstrap-descriptor"
                );
                retrieval_bootstrap_descriptor = Some(path.into());
            } else if flag == "--retrieval-bootstrap-descriptor-digest" {
                anyhow::ensure!(
                    retrieval_bootstrap_descriptor_digest.is_none(),
                    "duplicate --retrieval-bootstrap-descriptor-digest"
                );
                let value = path
                    .into_string()
                    .map_err(|_| anyhow::anyhow!("retrieval descriptor digest must be UTF-8"))?;
                retrieval_bootstrap_descriptor_digest =
                    Some(value.parse::<Digest32>().map_err(|error| {
                        anyhow::anyhow!("invalid retrieval descriptor digest: {error}")
                    })?);
            } else if flag == "--retrieval-learning-descriptor" {
                anyhow::ensure!(
                    retrieval_learning_descriptor.is_none(),
                    "duplicate --retrieval-learning-descriptor"
                );
                retrieval_learning_descriptor = Some(path.into());
            } else if flag == "--retrieval-learning-descriptor-digest" {
                anyhow::ensure!(
                    retrieval_learning_descriptor_digest.is_none(),
                    "duplicate --retrieval-learning-descriptor-digest"
                );
                retrieval_learning_descriptor_digest = Some(
                    path.into_string()
                        .map_err(|_| anyhow::anyhow!("retrieval learning digest must be UTF-8"))?
                        .parse::<Digest32>()?,
                );
            } else if flag == "--intelligence-authority-file" {
                anyhow::ensure!(
                    intelligence_authority_file.is_none(),
                    "duplicate --intelligence-authority-file"
                );
                intelligence_authority_file = Some(PathBuf::from(path));
            } else if flag == "--intelligence-authority-signer" {
                anyhow::ensure!(
                    intelligence_authority_signer.is_none(),
                    "duplicate --intelligence-authority-signer"
                );
                intelligence_authority_signer = Some(
                    path.into_string()
                        .map_err(|_| anyhow::anyhow!("intelligence signer must be UTF-8"))?,
                );
            } else if flag == "--intelligence-authority-verifying-key" {
                anyhow::ensure!(
                    intelligence_authority_verifying_key.is_none(),
                    "duplicate --intelligence-authority-verifying-key"
                );
                intelligence_authority_verifying_key = Some(parse_verifying_key_hex(path)?);
            } else if flag == "--canonical-intelligence-provider-profile" {
                anyhow::ensure!(
                    canonical_intelligence_provider_profile.is_none(),
                    "duplicate --canonical-intelligence-provider-profile"
                );
                let value = path.into_string().map_err(|_| {
                    anyhow::anyhow!("canonical intelligence provider profile must be UTF-8")
                })?;
                canonical_intelligence_provider_profile = Some(
                    value
                        .parse::<CanonicalIntelligenceProviderProfileV1>()
                        .map_err(anyhow::Error::from)?,
                );
            } else if flag == "--objective-profile-file" {
                anyhow::ensure!(
                    objective_profile.is_none(),
                    "duplicate --objective-profile-file"
                );
                objective_profile = Some(path);
            } else if flag == "--automation-effect-host-file" {
                anyhow::ensure!(
                    automation_effect_host.is_none(),
                    "duplicate --automation-effect-host-file"
                );
                automation_effect_host = Some(path);
            } else if flag == "--authbus-checkpoint-file" {
                anyhow::ensure!(
                    authbus_checkpoint.is_none(),
                    "duplicate --authbus-checkpoint-file"
                );
                authbus_checkpoint = Some(path);
            } else if flag == "--evidence-trust-file" {
                anyhow::ensure!(evidence_trust.is_none(), "duplicate --evidence-trust-file");
                evidence_trust = Some(path);
            } else if flag == "--evidence-recovery-frontier-file" {
                anyhow::ensure!(
                    evidence_recovery_frontier.is_none(),
                    "duplicate --evidence-recovery-frontier-file"
                );
                evidence_recovery_frontier = Some(path);
            } else if flag == "--evidence-recovery-frontier-trust-file" {
                anyhow::ensure!(
                    evidence_recovery_frontier_trust.is_none(),
                    "duplicate --evidence-recovery-frontier-trust-file"
                );
                evidence_recovery_frontier_trust = Some(path);
            } else {
                anyhow::bail!("unknown Agentd argument {flag:?}");
            }
        }
        if let Some(profile) = runtime_module_profile {
            config = config.with_runtime_module_profile(profile);
        }
        match (
            intelligence_authority_file,
            intelligence_authority_signer,
            intelligence_authority_verifying_key,
            canonical_intelligence_provider_profile,
        ) {
            (None, None, None, None) => {}
            (
                Some(path),
                Some(signer_id),
                Some(verifying_key),
                Some(CanonicalIntelligenceProviderProfileV1::DurableSafeAbstainV1),
            ) => {
                config = compose_durable_abstain_intelligence_profile_v1(
                    config,
                    path,
                    IntelligenceAuthorityVerifierV1 {
                        signer_id,
                        verifying_key,
                    },
                )?;
            }
            (Some(_), Some(_), Some(_), None) => {
                anyhow::bail!(
                    "canonical intelligence authority requires --canonical-intelligence-provider-profile durable-safe-abstain-v1"
                );
            }
            _ => {
                anyhow::bail!(
                    "--intelligence-authority-file, --intelligence-authority-signer, --intelligence-authority-verifying-key and --canonical-intelligence-provider-profile must be supplied together"
                );
            }
        }
        anyhow::ensure!(
            authbus_trust.is_some() == authbus_checkpoint.is_some(),
            "--authbus-trust-file and --authbus-checkpoint-file must be configured together"
        );
        if let (Some(trust), Some(checkpoint)) = (authbus_trust, authbus_checkpoint) {
            config = config
                .with_authbus_trust_file(trust.into())
                .with_authbus_checkpoint_file(checkpoint.into());
        }
        if let Some(path) = automation_effect_host {
            config = config.with_automation_effect_host_file(path.into());
        }
        if let Some(path) = objective_profile {
            config = config.with_objective_profile_file(path.into());
        }
        if let Some(path) = evidence_trust {
            config = config.with_evidence_trust_file(path.into());
        }
        match (evidence_recovery_frontier, evidence_recovery_frontier_trust) {
            (Some(frontier), Some(trust)) => {
                config =
                    config.with_evidence_recovery_frontier_files(frontier.into(), trust.into());
            }
            (None, None) => {}
            _ => anyhow::bail!(
                "--evidence-recovery-frontier-file and --evidence-recovery-frontier-trust-file must be supplied together"
            ),
        }

        match (
            plasticity_bootstrap_descriptor,
            plasticity_bootstrap_descriptor_digest,
        ) {
            (Some(path), Some(expected_digest)) => {
                let bootstrap = load_plasticity_process_bootstrap_v1(
                    &path,
                    expected_digest,
                    config.identity(),
                )?;
                config = config.with_plasticity_runtime_bootstrap(bootstrap)?;
            }
            (None, None) => {}
            _ => anyhow::bail!(
                "--plasticity-bootstrap-descriptor and its digest must be supplied together"
            ),
        }

        match (
            retrieval_bootstrap_descriptor,
            retrieval_bootstrap_descriptor_digest,
        ) {
            (Some(path), Some(expected_digest)) => {
                let provider = LeasedMemoryRetrievalProviderV1::load_process_bootstrap(
                    &path,
                    expected_digest,
                    config.identity(),
                )
                .map_err(anyhow::Error::msg)?;
                config = config.with_cognitive_retrieval_context(provider)?;
            }
            (None, None) => {}
            _ => anyhow::bail!(
                "--retrieval-bootstrap-descriptor and its digest must be supplied together"
            ),
        }

        match (
            retrieval_learning_descriptor,
            retrieval_learning_descriptor_digest,
        ) {
            (Some(path), Some(pin)) => {
                let sink = load_retrieval_learning_bootstrap_v1(&path, pin, config.identity())
                    .map_err(anyhow::Error::msg)?;
                config = config.with_cognitive_retrieval_learning(sink)?;
            }
            (None, None) => {}
            _ => anyhow::bail!(
                "--retrieval-learning-descriptor and its digest must be supplied together"
            ),
        }
        let config = configure(config)?;
        crate::run(config, arg0_paths).await?;
        Ok(())
    })
}

fn parse_verifying_key_hex(value: OsString) -> anyhow::Result<[u8; 32]> {
    let value = value
        .into_string()
        .map_err(|_| anyhow::anyhow!("intelligence verifying key must be UTF-8 hex"))?;
    anyhow::ensure!(
        value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit()),
        "intelligence verifying key must contain exactly 64 hex characters"
    );
    let mut output = [0_u8; 32];
    for (index, slot) in output.iter_mut().enumerate() {
        let offset = index * 2;
        *slot = u8::from_str_radix(&value[offset..offset + 2], 16)
            .map_err(|_| anyhow::anyhow!("invalid intelligence verifying key hex"))?;
    }
    Ok(output)
}
