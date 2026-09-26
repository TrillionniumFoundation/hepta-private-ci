use std::path::PathBuf;

use codex_hepta_agentd::AgentdConfig;
use codex_hepta_agentd::AgentdIntelligenceProductRunnerV1;
use codex_hepta_agentd::IntelligenceAuthorityVerifierV1;
use codex_hepta_agentd::load_intuition_policy_bootstrap_v1;
use codex_hepta_agentd::load_plasticity_process_bootstrap_v1;
use codex_hepta_types::Digest32;
use codex_utils_absolute_path::AbsolutePathBuf;
use std::ffi::OsString;
use std::sync::Arc;

fn main() -> anyhow::Result<()> {
    let mut config = AgentdConfig::from_process_environment()?;
    let codex_home = AbsolutePathBuf::from_absolute_path(&config.identity().home_root)?;
    codex_utils_home_dir::set_process_codex_home_override(codex_home)?;
    codex_arg0::arg0_dispatch_or_else(move |arg0_paths| async move {
        // Helper re-execs must reach arg0 dispatch before daemon-only flags.
        let mut args = std::env::args_os().skip(1);
        let mut authbus_trust = None;
        let mut intelligence_authority_file = None;
        let mut intuition_policy_file: Option<PathBuf> = None;
        let mut intuition_policy_digest: Option<Digest32> = None;
        let mut intelligence_authority_signer = None;
        let mut intelligence_authority_verifying_key = None;
        let mut memory_retrieval_context_file = None;
        let mut memory_retrieval_context_signer = None;
        let mut memory_retrieval_context_verifying_key = None;
        let mut plasticity_bootstrap_descriptor: Option<PathBuf> = None;
        let mut plasticity_bootstrap_descriptor_digest: Option<Digest32> = None;
        let mut objective_profile = None;
        let mut prompt_registry_recovery_checkpoint = None;
        let mut authbus_checkpoint = None;
        let mut evidence_trust = None;
        let mut automation_effect_host = None;
        let mut evidence_recovery_frontier = None;
        let mut evidence_recovery_frontier_trust = None;
        while let Some(flag) = args.next() {
            let path = args
                .next()
                .ok_or_else(|| anyhow::anyhow!("{flag:?} requires a path"))?;
            if flag == "--authbus-trust-file" {
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
            } else if flag == "--intuition-policy-file" {
                anyhow::ensure!(
                    intuition_policy_file.is_none(),
                    "duplicate --intuition-policy-file"
                );
                intuition_policy_file = Some(PathBuf::from(path));
            } else if flag == "--intuition-policy-digest" {
                anyhow::ensure!(
                    intuition_policy_digest.is_none(),
                    "duplicate --intuition-policy-digest"
                );
                intuition_policy_digest = Some(
                    path.into_string()
                        .map_err(|_| anyhow::anyhow!("intuition digest must be UTF-8"))?
                        .parse::<Digest32>()
                        .map_err(|error| anyhow::anyhow!("invalid intuition digest: {error}"))?,
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
                intelligence_authority_verifying_key =
                    Some(parse_verifying_key_hex(path, "intelligence authority")?);
            } else if flag == "--memory-retrieval-context-file" {
                anyhow::ensure!(
                    memory_retrieval_context_file.is_none(),
                    "duplicate --memory-retrieval-context-file"
                );
                memory_retrieval_context_file = Some(PathBuf::from(path));
            } else if flag == "--memory-retrieval-context-signer" {
                anyhow::ensure!(
                    memory_retrieval_context_signer.is_none(),
                    "duplicate --memory-retrieval-context-signer"
                );
                memory_retrieval_context_signer = Some(path.into_string().map_err(|_| {
                    anyhow::anyhow!("memory retrieval context signer must be UTF-8")
                })?);
            } else if flag == "--memory-retrieval-context-verifying-key" {
                anyhow::ensure!(
                    memory_retrieval_context_verifying_key.is_none(),
                    "duplicate --memory-retrieval-context-verifying-key"
                );
                memory_retrieval_context_verifying_key =
                    Some(parse_verifying_key_hex(path, "memory retrieval context")?);
            } else if flag == "--prompt-registry-recovery-checkpoint-file" {
                anyhow::ensure!(
                    prompt_registry_recovery_checkpoint.is_none(),
                    "duplicate --prompt-registry-recovery-checkpoint-file"
                );
                prompt_registry_recovery_checkpoint = Some(PathBuf::from(path));
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
        anyhow::ensure!(
            intuition_policy_file.is_some() == intuition_policy_digest.is_some(),
            "--intuition-policy-file and --intuition-policy-digest must be supplied together"
        );
        anyhow::ensure!(
            intuition_policy_file.is_none() || intelligence_authority_file.is_some(),
            "intuition policy requires the intelligence authority configuration"
        );
        match (
            intelligence_authority_file,
            intelligence_authority_signer,
            intelligence_authority_verifying_key,
        ) {
            (None, None, None) => {}
            (Some(path), Some(signer_id), Some(verifying_key)) => {
                let runner = AgentdIntelligenceProductRunnerV1::new(
                    path,
                    IntelligenceAuthorityVerifierV1 {
                        signer_id,
                        verifying_key,
                    },
                )?;
                let runner = match (intuition_policy_file, intuition_policy_digest) {
                    (Some(path), Some(pin)) => {
                        let identity = config.identity();
                        let now = u64::try_from(
                            std::time::SystemTime::now()
                                .duration_since(std::time::UNIX_EPOCH)?
                                .as_millis(),
                        )?;
                        let host = load_intuition_policy_bootstrap_v1(
                            &path,
                            pin,
                            identity.agent_id.clone(),
                            identity.spawn_generation,
                            now,
                        )?;
                        runner.with_intuition_policy_host(host)?
                    }
                    (None, None) => runner,
                    _ => anyhow::bail!("incomplete intuition bootstrap configuration"),
                };
                config = config.with_intelligence_product_runner(Arc::new(runner))?;
            }
            _ => {
                return Err(anyhow::anyhow!(
                    "--intelligence-authority-file, --intelligence-authority-signer and --intelligence-authority-verifying-key must be supplied together"
                ));
            }
        }
        match (
            memory_retrieval_context_file,
            memory_retrieval_context_signer,
            memory_retrieval_context_verifying_key,
        ) {
            (None, None, None) => {}
            (Some(path), Some(signer_id), Some(verifying_key)) => {
                config = config.with_signed_memory_retrieval_context_file(
                    path,
                    signer_id,
                    verifying_key,
                )?;
            }
            _ => {
                return Err(anyhow::anyhow!(
                    "--memory-retrieval-context-file, --memory-retrieval-context-signer and --memory-retrieval-context-verifying-key must be supplied together"
                ));
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
        if let Some(path) = prompt_registry_recovery_checkpoint {
            config = config.with_prompt_registry_recovery_checkpoint_file(path)?;
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

        codex_hepta_agentd::run(config, arg0_paths).await?;
        Ok(())
    })
}

fn parse_verifying_key_hex(value: OsString, label: &str) -> anyhow::Result<[u8; 32]> {
    let value = value
        .into_string()
        .map_err(|_| anyhow::anyhow!("{label} verifying key must be UTF-8 hex"))?;
    anyhow::ensure!(
        value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit()),
        "{label} verifying key must contain exactly 64 hex characters"
    );
    let mut output = [0_u8; 32];
    for (index, slot) in output.iter_mut().enumerate() {
        let offset = index * 2;
        *slot = u8::from_str_radix(&value[offset..offset + 2], 16)
            .map_err(|_| anyhow::anyhow!("invalid {label} verifying key hex"))?;
    }
    Ok(output)
}
