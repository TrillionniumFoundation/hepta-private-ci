//! Freeze one original held Window, then obtain its genuine finite E signature.
//! This route copies complete original Sources and never manufactures a witness.
use super::*;
use codex_hepta_agent_components::intelligence_eval::*;
use codex_hepta_agent_components::learning_ledger::*;
use codex_hepta_agentd::PreparedParameterDatasetV1;
use codex_hepta_agentd::PreparedParameterDatasetWindowV3;
use std::io::Read;
use std::io::Seek;

pub(super) enum PreparedDataset {
    OriginalV2(PreparedParameterDatasetV1),
    WindowV3 {
        facts: PreparedParameterDatasetWindowV3,
        evaluation: FixedDatasetWindowEvaluationV3,
    },
}

// Inspect the same protected descriptor whose complete original bytes were
// admitted; a second path read cannot pin the descriptor used by the parser.
fn pinned_source_file(source: &InstalledCpuSourceV1, expected: &[u8]) -> Result<std::fs::File> {
    let mut file =
        open_root_review_input(&source.path).map_err(|error| anyhow::anyhow!("{error}"))?;
    let maximum = u64::try_from(expected.len())?
        .checked_add(1)
        .context("whole original Window Source size")?;
    let mut bytes = Vec::new();
    (&mut file).take(maximum).read_to_end(&mut bytes)?;
    ensure!(
        bytes == expected && Digest32::of_bytes(&bytes) == source.digest.parse()?,
        "whole original Window Source differs on inspected descriptor"
    );
    file.rewind()?;
    Ok(file)
}

pub(super) async fn collect(
    blueprint: &blueprint::Blueprint,
    client: &AgentdClient,
    before: &codex_hepta_supervisor::SupervisordAgentStatus,
    round: &AgentdSelfIterationRoundV1,
    public: &Path,
    effects: &Path,
) -> Result<Option<PreparedDataset>> {
    let Some(window) = &blueprint.dataset_window else {
        let (generation, facts) = client
            .prepare_parameter_dataset_v1(
                round.clone(),
                blueprint.dataset_producer.path.clone(),
                blueprint.dataset_producer.digest.parse()?,
                blueprint.dataset_plan.path.clone(),
                blueprint.dataset_plan.digest.parse()?,
            )
            .await?;
        current::validate_runtime_generation(before, generation)?;
        return Ok(Some(PreparedDataset::OriginalV2(facts)));
    };
    let name = "dataset-window-facts.json";
    let path = public.join(name);
    let facts = if path.try_exists()? {
        let bytes = read_root_review_input(
            &path,
            codex_hepta_agentd::MAX_PREPARED_DATASET_WINDOW_BYTES_V3 as u64,
        )
        .map_err(|error| anyhow::anyhow!("{error}"))?;
        let facts = PreparedParameterDatasetWindowV3::from_source_bytes(&bytes)?;
        ensure!(
            facts.canonical_source_bytes()? == bytes,
            "whole retained Window facts codec"
        );
        facts
    } else {
        let (generation, facts) = client
            .prepare_parameter_dataset_window_v3(
                round.clone(),
                blueprint.dataset_producer.path.clone(),
                blueprint.dataset_producer.digest.parse()?,
                blueprint.dataset_plan.path.clone(),
                blueprint.dataset_plan.digest.parse()?,
            )
            .await?;
        current::validate_runtime_generation(before, generation)?;
        facts
    };
    original_facts::publish(
        public,
        name,
        &facts.canonical_source_bytes()?,
        codex_hepta_agentd::MAX_PREPARED_DATASET_WINDOW_BYTES_V3,
    )?;
    let plan_bytes = configuration::source(&blueprint.dataset_plan, 8192)?;
    let plan: DatasetWindowFreezePlanWireV3 = serde_json::from_slice(&plan_bytes)?;
    ensure!(
        plan.native().map_err(|error| anyhow::anyhow!("{error}"))?
            == facts
                .plan
                .native()
                .map_err(|error| anyhow::anyhow!("{error}"))?,
        "whole enrolled Window plan differs from original held facts"
    );
    let ledger_bytes = facts.ledger_source_bytes()?;
    let witness_bytes = configuration::source(&window.witness, 8 * 1024 * 1024)?;
    let binding = facts.ledger_binding.parse()?;
    let ledger = original_facts::publish(
        public,
        "frozen-ledger.bin",
        &ledger_bytes,
        MAX_LEDGER_CANONICAL_SOURCE_BYTES_V1,
    )?;
    let witness_source = original_facts::publish(
        public,
        "original-witness.bin",
        &witness_bytes,
        8 * 1024 * 1024,
    )?;
    let witness = inspect_ledger_witness_frontier(
        pinned_source_file(&witness_source, &witness_bytes)?,
        binding,
        window.maximum_witness_frames as usize,
    )
    .map_err(|error| anyhow::anyhow!("{error}"))?;
    ensure!(
        witness.segment.is_none()
            && !witness.sealed
            && witness.anchor.sequence == facts.ledger_record_count
            && witness.anchor.chain_digest.to_string() == facts.ledger_head_digest,
        "independent whole witness differs from the actual held Window frontier"
    );
    let maximum_records = u32::try_from(facts.maximum_ledger_records)?;
    let snapshot = inspect_ledger(
        pinned_source_file(&ledger, &ledger_bytes)?,
        binding,
        maximum_records as usize,
        witness.anchor,
    )
    .map_err(|error| anyhow::anyhow!("{error}"))?;
    let role = |source: &InstalledCpuSourceV1| ParameterRoleSourceV3 {
        path: source.path.clone(),
        digest: source.digest.clone(),
    };
    let inputs = FixedDatasetWindowEvaluatorInputsV3 {
        schema: "hepta.fixed-dataset-window-inputs.v3".into(),
        round: ParameterPreRegistrationRoundV1 {
            round_digest: round.identity_digest().to_string(),
            round_payload_digest: Digest32::of_bytes(&round.canonical_bytes()?).to_string(),
            canonical_policy_digest: round.canonical_policy_digest().to_string(),
            execution_digest: round.execution_envelope_digest().to_string(),
            admitted_at_ms: round.admitted_at_ms(),
            deadline_ms: round.deadline_ms(),
        },
        plan,
        ledger: role(&ledger),
        witness: role(&witness_source),
        ledger_binding: facts.ledger_binding.clone(),
        maximum_records,
        maximum_witness_frames: window.maximum_witness_frames,
        acknowledged_sequence: witness.anchor.sequence,
        acknowledged_chain_digest: witness.anchor.chain_digest.to_string(),
    };
    let inputs_bytes = encode_fixed_dataset_window_evaluator_inputs_v3(&inputs)
        .map_err(|error| anyhow::anyhow!("{error}"))?;
    let inputs_source = original_facts::publish(
        public,
        "window-evaluator-inputs.json",
        &inputs_bytes,
        32 * 1024,
    )?;
    let trust_bytes = configuration::source(&blueprint.learning_trust, 64 * 1024)?;
    let trust_wire: ReviewTrustWireV1 = serde_json::from_slice(&trust_bytes)?;
    let (root, distribution) = trust_wire
        .native()
        .map_err(|error| anyhow::anyhow!("{error}"))?;
    let trust = activate_learning_trust(&root, distribution, None, now_ms()?)?;
    let template_bytes =
        configuration::source(&window.evaluator.configuration_template, 32 * 1024)?;
    let mut config: serde_json::Value = serde_json::from_slice(&template_bytes)?;
    config["inputs_path"] = serde_json::to_value(&inputs_source.path)?;
    config["inputs_digest"] = inputs_source.digest.into();
    config["program_digest"] = window.evaluator.program.digest.clone().into();
    let config_bytes = serde_json::to_vec(&config)?;
    let actual: FixedParameterEvaluatorConfigV1 = serde_json::from_slice(&config_bytes)?;
    ensure!(
        actual.schema == "hepta.fixed-dataset-window-evaluator-config.v3"
            && actual.uid == window.evaluator.uid
            && actual.gid == window.evaluator.gid
            && actual.inaccessible_paths == window.evaluator.inaccessible_paths
            && actual.trust_path == blueprint.learning_trust.path
            && actual.trust_digest == blueprint.learning_trust.digest,
        "whole enrolled finite Window E custody/trust changed"
    );
    let config_source =
        original_facts::publish(public, "window-evaluator.json", &config_bytes, 32 * 1024)?;
    let revalidate = || -> Result<()> {
        ensure!(
            configuration::source(&blueprint.dataset_plan, 8192)? == plan_bytes
                && configuration::source(&window.witness, 8 * 1024 * 1024)? == witness_bytes
                && configuration::source(&window.evaluator.configuration_template, 32 * 1024)?
                    == template_bytes
                && configuration::source(&blueprint.learning_trust, 64 * 1024)? == trust_bytes,
            "whole original Window E inputs changed"
        );
        Ok(())
    };
    let verify = |bytes: &[u8]| -> std::result::Result<(), Box<dyn std::error::Error>> {
        revalidate().map_err(|error| format!("{error}"))?;
        decode_fixed_dataset_window_evaluator_output_v3(
            bytes,
            &inputs,
            &snapshot,
            &trust,
            now_ms()?,
        )?;
        Ok(())
    };
    let Some(output) = crate::execute_retained_parameter_role_v1(
        &crate::ParameterRoleExecutionV1 {
            purpose: crate::ParameterRoleExecutionPurposeV1::EvaluatorDatasetWindowV3,
            program: role(&window.evaluator.program),
            configuration: role(&config_source),
            uid: window.evaluator.uid,
            gid: window.evaluator.gid,
            inaccessible_paths: window.evaluator.inaccessible_paths.clone(),
            original_effect_digest: Digest32::of_parts(&[
                round.identity_digest().as_array(),
                config_source.digest.as_bytes(),
            ]),
        },
        &effects.join("dataset-window.output"),
        verify,
    )
    .map_err(|error| anyhow::anyhow!("{error}"))?
    else {
        return Ok(None);
    };
    let evaluation = decode_fixed_dataset_window_evaluator_output_v3(
        &output,
        &inputs,
        &snapshot,
        &trust,
        now_ms()?,
    )
    .map_err(|error| anyhow::anyhow!("{error}"))?;
    ensure!(
        evaluation.signing_payload
            == decode_review_payload_hex(&facts.freeze_payload_hex)
                .map_err(|error| anyhow::anyhow!("{error}"))?,
        "genuine E signature differs from original held Window payload"
    );
    Ok(Some(PreparedDataset::WindowV3 { facts, evaluation }))
}
