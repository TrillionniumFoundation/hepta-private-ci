use std::path::PathBuf;

use codex_hepta_agentd::AgentdConfig;
use codex_hepta_agentd::AgentdIntelligenceProductRunnerV1;
use codex_hepta_agentd::EvidenceProductionAdmissionFiles;
use codex_hepta_agentd::EvidenceRuntimeMode;
use codex_hepta_agentd::EvidenceRuntimePolicy;
use codex_hepta_agentd::IntelligenceAuthorityVerifierV1;
use codex_hepta_agentd::configure_evidence_runtime_policy;
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
        let mut intelligence_authority_signer = None;
        let mut intelligence_authority_verifying_key = None;
        let mut plasticity_bootstrap_descriptor: Option<PathBuf> = None;
        let mut plasticity_bootstrap_descriptor_digest: Option<Digest32> = None;
        let mut objective_profile = None;
        let mut authbus_checkpoint = None;
        let mut evidence_trust = None;
        let mut automation_effect_host = None;
        let mut evidence_recovery_frontier = None;
        let mut evidence_recovery_frontier_trust = None;
        let mut evidence_mode = None;
        let mut evidence_backend_identity = None;
        let mut evidence_build_identity = None;
        let mut evidence_qualification_status = None;
        let mut evidence_backup_publication = None;
        let mut evidence_local_rollback_domain = None;
        while let Some(flag) = args.next() {
            let value = args
                .next()
                .ok_or_else(|| anyhow::anyhow!("{flag:?} requires a value"))?;
            if flag == "--authbus-trust-file" {
                anyhow::ensure!(authbus_trust.is_none(), "duplicate --authbus-trust-file");
                authbus_trust = Some(value);
            } else if flag == "--plasticity-bootstrap-descriptor" {
                anyhow::ensure!(
                    plasticity_bootstrap_descriptor.is_none(),
                    "duplicate --plasticity-bootstrap-descriptor"
                );
                plasticity_bootstrap_descriptor = Some(value.into());
            } else if flag == "--plasticity-bootstrap-descriptor-digest" {
                anyhow::ensure!(
                    plasticity_bootstrap_descriptor_digest.is_none(),
                    "duplicate --plasticity-bootstrap-descriptor-digest"
                );
                let value = value
                    .into_string()
                    .map_err(|_| anyhow::anyhow!("plasticity descriptor digest must be UTF-8"))?;
                plasticity_bootstrap_descriptor_digest =
                    Some(value.parse::<Digest32>().map_err(|error| {
                        anyhow::anyhow!("invalid plasticity descriptor digest: {error}")
                    })?);
            } else if flag == "--intelligence-authority-file" {
                anyhow::ensure!(
                    intelligence_authority_file.is_none(),
                    "duplicate --intelligence-authority-file"
                );
                intelligence_authority_file = Some(PathBuf::from(value));
            } else if flag == "--intelligence-authority-signer" {
                anyhow::ensure!(
                    intelligence_authority_signer.is_none(),
                    "duplicate --intelligence-authority-signer"
                );
                intelligence_authority_signer = Some(
                    value
                        .into_string()
                        .map_err(|_| anyhow::anyhow!("intelligence signer must be UTF-8"))?,
                );
            } else if flag == "--intelligence-authority-verifying-key" {
                anyhow::ensure!(
                    intelligence_authority_verifying_key.is_none(),
                    "duplicate --intelligence-authority-verifying-key"
                );
                intelligence_authority_verifying_key = Some(parse_verifying_key_hex(value)?);
            } else if flag == "--objective-profile-file" {
                anyhow::ensure!(
                    objective_profile.is_none(),
                    "duplicate --objective-profile-file"
                );
                objective_profile = Some(value);
            } else if flag == "--automation-effect-host-file" {
                anyhow::ensure!(
                    automation_effect_host.is_none(),
                    "duplicate --automation-effect-host-file"
                );
                automation_effect_host = Some(value);
            } else if flag == "--authbus-checkpoint-file" {
                anyhow::ensure!(
                    authbus_checkpoint.is_none(),
                    "duplicate --authbus-checkpoint-file"
                );
                authbus_checkpoint = Some(value);
            } else if flag == "--evidence-trust-file" {
                anyhow::ensure!(evidence_trust.is_none(), "duplicate --evidence-trust-file");
                evidence_trust = Some(value);
            } else if flag == "--evidence-recovery-frontier-file" {
                anyhow::ensure!(
                    evidence_recovery_frontier.is_none(),
                    "duplicate --evidence-recovery-frontier-file"
                );
                evidence_recovery_frontier = Some(value);
            } else if flag == "--evidence-recovery-frontier-trust-file" {
                anyhow::ensure!(
                    evidence_recovery_frontier_trust.is_none(),
                    "duplicate --evidence-recovery-frontier-trust-file"
                );
                evidence_recovery_frontier_trust = Some(value);
            } else if flag == "--evidence-mode" {
                anyhow::ensure!(evidence_mode.is_none(), "duplicate --evidence-mode");
                evidence_mode = Some(
                    value
                        .into_string()
                        .map_err(|_| anyhow::anyhow!("evidence mode must be UTF-8"))?,
                );
            } else if flag == "--evidence-frontier-backend-identity-file" {
                anyhow::ensure!(
                    evidence_backend_identity.is_none(),
                    "duplicate --evidence-frontier-backend-identity-file"
                );
                evidence_backend_identity = Some(PathBuf::from(value));
            } else if flag == "--evidence-build-identity-file" {
                anyhow::ensure!(
                    evidence_build_identity.is_none(),
                    "duplicate --evidence-build-identity-file"
                );
                evidence_build_identity = Some(PathBuf::from(value));
            } else if flag == "--evidence-qualification-status-file" {
                anyhow::ensure!(
                    evidence_qualification_status.is_none(),
                    "duplicate --evidence-qualification-status-file"
                );
                evidence_qualification_status = Some(PathBuf::from(value));
            } else if flag == "--evidence-backup-publication-file" {
                anyhow::ensure!(
                    evidence_backup_publication.is_none(),
                    "duplicate --evidence-backup-publication-file"
                );
                evidence_backup_publication = Some(PathBuf::from(value));
            } else if flag == "--evidence-local-rollback-domain" {
                anyhow::ensure!(
                    evidence_local_rollback_domain.is_none(),
                    "duplicate --evidence-local-rollback-domain"
                );
                evidence_local_rollback_domain = Some(value.into_string().map_err(|_| {
                    anyhow::anyhow!("evidence local rollback-domain id must be UTF-8")
                })?);
            } else {
                anyhow::bail!("unknown Agentd argument {flag:?}");
            }
        }
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
                config = config.with_intelligence_product_runner(Arc::new(runner))?;
            }
            _ => {
                return Err(anyhow::anyhow!(
                    "--intelligence-authority-file, --intelligence-authority-signer and --intelligence-authority-verifying-key must be supplied together"
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
        if let Some(path) = objective_profile {
            config = config.with_objective_profile_file(path.into());
        }

        let parsed_evidence_mode = EvidenceRuntimeMode::parse(
            evidence_mode.as_deref().unwrap_or("development"),
        )?;
        let has_production_inputs = evidence_backend_identity.is_some()
            || evidence_build_identity.is_some()
            || evidence_qualification_status.is_some()
            || evidence_backup_publication.is_some()
            || evidence_local_rollback_domain.is_some();
        let evidence_policy = match parsed_evidence_mode {
            EvidenceRuntimeMode::Development => {
                anyhow::ensure!(
                    !has_production_inputs,
                    "kernel.evidence production admission inputs are forbidden in development mode"
                );
                EvidenceRuntimePolicy::development()
            }
            EvidenceRuntimeMode::Production => {
                anyhow::ensure!(
                    evidence_trust.is_some(),
                    "kernel.evidence production mode requires --evidence-trust-file"
                );
                anyhow::ensure!(
                    evidence_recovery_frontier.is_some()
                        && evidence_recovery_frontier_trust.is_some(),
                    "kernel.evidence production mode requires signed recovery-frontier files"
                );
                EvidenceRuntimePolicy::production(EvidenceProductionAdmissionFiles {
                    backend_identity_file: evidence_backend_identity.ok_or_else(|| {
                        anyhow::anyhow!(
                            "production mode requires --evidence-frontier-backend-identity-file"
                        )
                    })?,
                    build_identity_file: evidence_build_identity.ok_or_else(|| {
                        anyhow::anyhow!(
                            "production mode requires --evidence-build-identity-file"
                        )
                    })?,
                    qualification_status_file: evidence_qualification_status.ok_or_else(|| {
                        anyhow::anyhow!(
                            "production mode requires --evidence-qualification-status-file"
                        )
                    })?,
                    backup_publication_file: evidence_backup_publication.ok_or_else(|| {
                        anyhow::anyhow!(
                            "production mode requires --evidence-backup-publication-file"
                        )
                    })?,
                    local_rollback_domain_id: evidence_local_rollback_domain.ok_or_else(|| {
                        anyhow::anyhow!(
                            "production mode requires --evidence-local-rollback-domain"
                        )
                    })?,
                })?
            }
        };
        configure_evidence_runtime_policy(evidence_policy)?;

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
