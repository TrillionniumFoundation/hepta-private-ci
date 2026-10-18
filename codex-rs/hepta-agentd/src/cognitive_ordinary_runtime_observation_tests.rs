//! Actual Agentd choices, then original durable decision/outcome/dataset owners.
//! The 32 offered application tasks are separate from the larger final cohort
//! used by the statistical evaluator; they do not independently qualify it.
use super::*;
use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_hepta_learning_ledger as ledger;

pub(super) async fn collect(
    root: &std::path::Path,
    client: &crate::AgentdClient,
    installed: &crate::CognitiveModelReadback,
    payload: &std::path::Path,
    actions: &[(CognitiveContextItem, String)],
    roles: &mut Roles,
) -> Result<Value> {
    std::fs::create_dir(root)?;
    let started = std::time::Instant::now();
    let before = client
        .cognitive_model_status()
        .await?
        .installed
        .context("running observed model")?;
    ensure!(
        &before == installed,
        "runtime observation starts from another installed model"
    );
    let offered = roles.processes[6].call(
        json!({"command":"offer_runtime","name":"ordinary-installed-runtime",
        "candidate":payload,"model":before}),
    );
    save(&root.join("offered.json"), &offered);
    let tasks = offered["body"]["tasks"]
        .as_array()
        .context("actual offered runtime cohort")?;
    ensure!(
        tasks.len() == 32 && offered["body"]["offered_count"] == 32,
        "complete bounded runtime offer required"
    );
    let mut writer = roles.writer(&root.join("ledger-owner"));
    let mut candidates: Vec<_> = actions
        .iter()
        .map(|(item, _)| cognitive_action_id(item))
        .collect::<std::result::Result<_, _>>()
        .map_err(anyhow::Error::msg)?;
    candidates.push(id("abstain"));
    let expected_actions: std::collections::BTreeSet<_> = candidates
        .iter()
        .filter(|action| action.as_str() != "abstain")
        .cloned()
        .collect();
    let mut terminal = Vec::new();
    for (index, task) in tasks.iter().enumerate() {
        let context = client
            .cognitive_context(
                task["query"]
                    .as_str()
                    .context("actual task query")?
                    .to_owned(),
                4,
            )
            .await?;
        let observed_actions = context
            .items
            .iter()
            .map(cognitive_action_id)
            .collect::<std::result::Result<std::collections::BTreeSet<_>, _>>()
            .map_err(anyhow::Error::msg)?;
        ensure!(
            observed_actions == expected_actions && context.items.len() == 4,
            "actual runtime candidate set was incomplete"
        );
        let chosen = context
            .items
            .first()
            .context("actual selected runtime context")?;
        let operation = chosen
            .content
            .split_whitespace()
            .last()
            .context("native selected operation")?;
        let selected = cognitive_action_id(chosen).map_err(anyhow::Error::msg)?;
        let episode = id(&format!("ordinary-runtime-{index}"));
        let actual_context = serde_json::to_value(&context)?;
        let snapshot_digest = Digest32::of_bytes(&serde_json::to_vec(
            &json!({"task":task,"context":actual_context,"installed":installed}),
        )?);
        let support_digest = Digest32::of_bytes(&serde_json::to_vec(&offered)?);
        let decision = ledger::ProductionDecisionV2 {
            record_id: id(&format!("ordinary-runtime-{index}-decision")),
            episode_id: episode.clone(),
            run_snapshot_digest: snapshot_digest,
            objective_digest: roles.trust.objective_digest,
            policy_digest: hash("actual-agentd-four-memory-instruction-policy"),
            candidate_ids: candidates.clone(),
            selected_candidate_id: selected,
            selected_propensity: ProbabilityQ32::ONE,
            completeness: ledger::CandidateSetCompletenessReceiptV1 {
                set_id: id("original-four-memory-instructions-plus-abstain"),
                state_digest: snapshot_digest,
                generator_id: roles.principals[0].principal_id.clone(),
                generator_code_digest: hash("actual-agentd-cognitive-read"),
                grammar_digest: hash("four-declared-memory-instructions"),
                hard_filter_digest: hash("original-agent-private-memory"),
                truncation_digest: hash("exact-four-returned-memories"),
                candidates_digest: ledger::candidate_ids_digest_v2(&candidates),
                candidate_count: candidates.len().try_into()?,
                omitted_count_bound: 0,
                canonical_order_digest: ledger::candidate_order_digest_v2(&candidates),
                complete_for_generator: true,
            },
            support_digest,
        };
        let signed = roles.evidence(
            0,
            &ledger::decision_signing_payload_v2(&decision)?,
            support::micros(),
        );
        let head = writer.witness_frontier()?.anchor.chain_digest;
        let durable = writer.append_decision(head, decision, &signed, support::micros())?;
        // The real current reader is checked again after the durable decision,
        // before the independent application consumer executes its instruction.
        client.revalidate_cognitive_context(&context).await?;
        ensure!(
            client.cognitive_model_status().await?.installed == Some(installed.clone()),
            "installed model changed before task execution"
        );
        let observation=roles.processes[2].call(json!({"command":"observe_runtime","offered":offered,
            "task_id":task["id"],"operation":operation,"decision_evidence_sha256":durable.event_digest.to_string()}));
        ensure!(
            observation["body"]["task"] == task["id"]
                && observation["body"]["decision_evidence_sha256"]
                    == durable.event_digest.to_string(),
            "independent runtime outcome lost original decision binding"
        );
        let at = observation["observed_unix_micros"]
            .as_u64()
            .context("actual observer clock")?;
        let outcome = ledger::AuthenticatedOutcomeV1 {
            record_id: id(&format!("ordinary-runtime-{index}-outcome")),
            outcome_id: id(&format!("ordinary-runtime-{index}-result")),
            episode_id: episode,
            observer: roles.principals[2].clone(),
            observed_at: Some(at),
            value: Some(
                if observation["body"]["correct"]
                    .as_bool()
                    .context("independent task outcome")?
                {
                    FixedQ32::ONE
                } else {
                    FixedQ32::ZERO
                },
            ),
            unit_profile_digest: hash("exact-answer-0-or-1"),
            support_digest: Digest32::of_bytes(&serde_json::to_vec(&observation)?),
            watermark: ledger::OutcomeWatermarkV1 {
                latest_observable_at: at,
                expected_delay_profile_digest: hash("synchronous-local-arithmetic"),
                terminality: ledger::OutcomeTerminalityV1::Terminal,
                censoring_reason: None,
                correction_predecessor: None,
                finalized_at: Some(at),
            },
        };
        let signed = roles.evidence(
            2,
            &ledger::outcome_signing_payload_v2(&outcome),
            support::micros(),
        );
        let receipt =
            writer.append_outcome(durable.chain_digest, outcome, &signed, support::micros())?;
        save(
            &root.join(format!("task-{index}.json")),
            &json!({"task":task,"context":actual_context,"observation":observation,
            "decision_event_sha256":durable.event_digest.to_string(),"outcome_event_sha256":receipt.event_digest.to_string()}),
        );
        terminal.push(task["id"].clone());
    }
    let plan = ledger::DatasetFreezePlanV2 {
        snapshot_id: id("ordinary-installed-runtime-dataset"),
        objective_digest: roles.trust.objective_digest,
        inclusion_policy_digest: hash("all-offered-runtime-tasks-with-terminal-outcomes"),
    };
    let signed = roles.evidence(
        1,
        &ledger::dataset_freeze_signing_payload_v2(&writer.snapshot()?, &plan)?,
        support::micros(),
    );
    let dataset = writer.freeze_dataset(plan, &signed, support::micros())?;
    let snapshot = writer.snapshot()?;
    ledger::verify_dataset_snapshot_receipt_against_ledger_v3(
        &dataset,
        &snapshot,
        support::micros(),
    )?;
    ensure!(
        client.cognitive_model_status().await?.installed == Some(installed.clone()),
        "model changed during actual runtime task cohort"
    );
    let output = json!({"schema":"hepta.ordinary-installed-runtime-observation.v1","model":installed,
        "offered":tasks.iter().map(|task|task["id"].clone()).collect::<Vec<_>>(),"terminal":terminal,"pending":[],"censored":[],
        "dataset":crate::cognitive_process_evidence::DatasetSnapshotReceiptV3Raw::from(dataset),
        "ledger_head_sha256":snapshot.head_digest.to_string(),"monotonic_elapsed_micros":started.elapsed().as_micros(),
        "task_execution":"actual Agentd-selected instruction executed by independent role process after original durable decision",
        "statistical_qualification":false,"independent_operators":false});
    save(&root.join("observed.json"), &output);
    Ok(output)
}
