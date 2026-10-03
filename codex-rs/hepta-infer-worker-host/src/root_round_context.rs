//! Original whole context preparation before and after Artifact publication.
//! Only the final phase installs a context on the same held Agentd owner.
use super::*;
use codex_hepta_agentd::ParameterInputContextProjectionV2;
use codex_hepta_agentd::project_parameter_input_context_v2;
use codex_hepta_agent_components::learning_artifacts::RegistrySnapshotReceipt;
use original_facts::OriginalFacts;

pub(super) fn project(
    blueprint: &blueprint::Blueprint,
    facts: &OriginalFacts,
    subject: &StableId,
    spawn: u64,
    round: &AgentdSelfIterationRoundV1,
    snapshot: &InstalledCpuSourceV1,
    receipt: RegistrySnapshotReceipt,
    phase: parameter_roles::AdmissionPhase,
) -> Result<InstalledCpuSourceV1> {
    facts.indexed.revalidate().map_err(|error| anyhow::anyhow!("{error}"))?;
    let template = configuration::source(&blueprint.plasticity_context_template, 1024 * 1024)?;
    let template_value: serde_json::Value = serde_json::from_slice(&template)?;
    let path = facts.public.join(match phase {
        parameter_roles::AdmissionPhase::BeforeRegistration => "pre-registration-context.json",
        parameter_roles::AdmissionPhase::AfterRegistration => "registered-context.json",
    });
    // Retry the original observation rather than changing a consumed role's
    // complete input merely because the authority clock has advanced.
    let existing = if path.try_exists()? {
        Some(codex_hepta_agent_components::learning_ledger::read_root_review_input(
            &path, 1024 * 1024).map_err(|error| anyhow::anyhow!("{error}"))?)
    } else { None };
    let (observed, expires) = if let Some(bytes) = &existing {
        let value: serde_json::Value = serde_json::from_slice(bytes)?;
        (value["artifacts"]["observed_at"].as_u64().context("whole retained context observation")?,
         value["artifacts"]["expires_at"].as_u64().context("whole retained context expiry")?)
    } else {
        (now_ms()?, round.deadline_ms().min(template_value["artifacts"]["expires_at"]
            .as_u64().context("original enrolled context expiry")?))
    };
    ensure!(now_ms()? < expires, "original complete context observation expired");
    let bytes = project_parameter_input_context_v2(&template, &ParameterInputContextProjectionV2 {
        subject, spawn_generation: spawn, round,
        baseline_artifact: &facts.baseline_id, baseline_material: &facts.indexed.material,
        baseline_material_source: (&facts.indexed.material_source.path,
            facts.indexed.material_source.digest.parse()?),
        artifact_snapshot_source: &snapshot.path, artifact_snapshot_receipt: receipt,
        dataset: &facts.dataset,
        ndu_journal_source: (&blueprint.ndu_journal.path, blueprint.ndu_journal.digest.parse()?),
        neuron_material: &facts.goal_material, neuron_anchor: facts.checkpoint.anchor,
        observed_at_unix_ms: observed, expires_at_unix_ms: expires,
    })?;
    if let Some(original) = existing {
        ensure!(bytes == original, "whole original context changed after first preparation");
    }
    let source = original_facts::publish(&facts.public,
        path.file_name().and_then(|name| name.to_str()).context("original context name")?,
        &bytes, 1024 * 1024)?;
    facts.indexed.revalidate().map_err(|error| anyhow::anyhow!("{error}"))?;
    ensure!(configuration::source(&blueprint.plasticity_context_template, 1024 * 1024)? == template,
        "whole enrolled context template changed during projection");
    Ok(source)
}
