//! Protocol boundary tests; these model-port doubles claim no real model effect.
use super::*;
use codex_hepta_infer_core::SelfIterationModelAssessmentV1;
use codex_hepta_infer_core::SelfIterationModelErrorV1;

fn summary() -> HistoricalSummary {
    let digest = Digest32::of_bytes(b"original signed historical context").to_string();
    HistoricalSummary {
        schema: "hepta.historical-calibration-rejection.v1".into(),
        config_digest: digest.clone(),
        completion_digest: digest.clone(),
        result_digest: digest.clone(),
        objective_digest: digest.clone(),
        candidate_weights_digest: digest.clone(),
        baseline_weights_digest: digest.clone(),
        dataset_digest: digest,
        completed_at_ms: 10,
        labeled_pairs: 99,
        candidate_correct: 59,
        baseline_correct: 66,
        qualified: false,
        current_authentication: false,
        authority_grants_any: false,
        holdout_consumed: false,
        production_activation: false,
    }
}

#[test]
fn historical_feedback_rejects_current_qualification_future_time_and_unbounded_counts()
-> Result<(), Box<dyn std::error::Error>> {
    let original = summary();
    validate_summary(&original, &original.objective_digest, 20)?;
    for flag in [
        "qualified",
        "current_authentication",
        "authority_grants_any",
        "holdout_consumed",
        "production_activation",
    ] {
        let mut value = serde_json::to_value(&original)?;
        value[flag] = serde_json::json!(true);
        let changed = serde_json::from_value(value)?;
        assert!(validate_summary(&changed, &original.objective_digest, 20).is_err());
    }
    assert!(validate_summary(&original, &original.objective_digest, 9).is_err());
    let mut changed = original.clone();
    changed.candidate_correct = 100;
    assert!(validate_summary(&changed, &original.objective_digest, 20).is_err());
    assert!(
        validate_summary(
            &original,
            &Digest32::of_bytes(b"other objective").to_string(),
            20
        )
        .is_err()
    );
    Ok(())
}

fn fixture() -> Result<
    (
        tempfile::TempDir,
        AgentdIdentity,
        SelfIterationHostConfigV1,
        RejectedFeedback,
    ),
    Box<dyn std::error::Error>,
> {
    use codex_hepta_agent_components::contracts::AgentId;
    use codex_hepta_agent_components::fleet::AgentManifest;
    use codex_hepta_agent_components::fleet::FleetRegistry;
    use codex_hepta_agent_components::fleet::ResourceBudget;
    use codex_hepta_agent_components::fleet::WorkspaceBinding;
    use codex_hepta_agent_components::paths::HeptaFleetRoot;
    let directory = tempfile::tempdir()?;
    let root = directory.path().canonicalize()?;
    let fleet_path = root.join("fleet");
    let fleet_root = HeptaFleetRoot::parse(fleet_path.clone())?;
    let registry = FleetRegistry::initialize(fleet_root.clone())?;
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace)?;
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let registered = registry.register(AgentManifest::new(
        agent_id.clone(),
        WorkspaceBinding::new(&workspace, &fleet_root)?,
        ResourceBudget::local_default(),
    )?)?;
    let identity = AgentdIdentity {
        agent_id,
        layout: registered.layout.clone(),
        spawn_generation: 1,
        fleet_root: fleet_path,
        workspace,
        resources: registered.manifest.resources,
        home_root: registered.layout.home_root().to_path_buf(),
        run_root: registered.layout.run_root().to_path_buf(),
        control_socket: registered.layout.agentd_control_socket().to_path_buf(),
        app_server_socket: registered.layout.app_server_socket().to_path_buf(),
    };
    let pin = Digest32::of_bytes(b"historical summary");
    let host_pin = Digest32::of_bytes(b"installed host");
    let installed: SelfIterationHostConfigV1 = serde_json::from_value(serde_json::json!({
        "version":1,"agent_id":identity.agent_id.to_string(),"model":"protocol-test-model",
        "objective_prompt":"Propose the next lawful bounded candidate",
        "objective_digest":pin.to_string(),"base_commit_digest":pin.to_string(),
        "base_tree_digest":pin.to_string(),"grammar_digest":pin.to_string(),
        "trusted_inputs_directory":root,"inputs_manifest_filename":"inputs.json","inputs_manifest_digest":pin.to_string(),
        "candidate_generation":1,"native_journal":identity.home_root.join("native"),
        "native_record_capacity":128,"maximum_in_flight":1,"final_use_authority_config":root.join("authority"),
        "proposal_timeout_seconds":30,"status_file":identity.home_root.join("status.json"),
    }))?;
    let feedback = RejectedFeedback {
        config: RejectedCalibrationFeedbackConfigV1 {
            summary_path: root.join("unused-root-summary"),
            summary_digest: pin.to_string(),
            historical_objective_digest: summary().objective_digest,
            proposal_receipt_path: identity.home_root.join("rejected-proposal.json"),
        },
        summary: summary(),
        pin,
        host_pin,
    };
    Ok((directory, identity, installed, feedback))
}

struct UncertainPort(usize);
impl SelfIterationModelPortV1 for UncertainPort {
    async fn assess(
        &mut self,
        _request: SelfIterationModelRequestV1,
    ) -> Result<SelfIterationModelAssessmentV1, SelfIterationModelErrorV1> {
        self.0 += 1;
        Err(SelfIterationModelErrorV1::Provider(
            "original native effect uncertain".into(),
        ))
    }
}

#[tokio::test]
async fn uncertain_proposal_keeps_original_receipt_and_does_not_issue_another_model_effect_after_restart()
-> Result<(), Box<dyn std::error::Error>> {
    let (_directory, mut identity, installed, feedback) = fixture()?;
    let mut model = UncertainPort(0);
    let original = feedback.run_step(&mut model, &installed, &identity).await?;
    assert_eq!(original["state"], "pending_original_native_proposal");
    assert_eq!(model.0, 1);
    identity.spawn_generation = 2;
    let resumed = feedback.run_step(&mut model, &installed, &identity).await?;
    assert_eq!(resumed, original);
    assert_eq!(model.0, 1);
    assert_eq!(resumed["worker_generation"], 1);
    assert_eq!(resumed["qualified"], false);
    assert_eq!(resumed["authority_grants_any"], false);
    Ok(())
}

#[test]
fn original_identity_binds_history_and_installed_host_while_receipt_retains_the_original_deadline()
-> Result<(), Box<dyn std::error::Error>> {
    let (_directory, identity, installed, feedback) = fixture()?;
    let first = request(
        &installed,
        &identity,
        &feedback.summary,
        feedback.pin,
        feedback.host_pin,
        100,
    )?;
    let later = request(
        &installed,
        &identity,
        &feedback.summary,
        feedback.pin,
        feedback.host_pin,
        200,
    )?;
    assert_eq!(first.request_id, later.request_id);
    assert_ne!(first.deadline_ms, later.deadline_ms);
    let different = request(
        &installed,
        &identity,
        &feedback.summary,
        Digest32::of_bytes(b"different rejection"),
        feedback.host_pin,
        100,
    )?;
    assert_ne!(first.request_id, different.request_id);
    assert!(!first.prompt.contains("calibration-pairs.jsonl"));
    Ok(())
}
