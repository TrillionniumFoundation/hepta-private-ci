//! Reuse the whole authenticated fixture and original Dataset socket facts.
use super::*;

pub(super) struct ProjectionInputs<'a> {
    pub(super) identity: &'a crate::AgentdIdentity,
    pub(super) round: &'a crate::AgentdSelfIterationRoundV1,
    pub(super) training: &'a NeuronGenerationMaterialV2,
    pub(super) goal: &'a NeuronGenerationMaterialV2,
    pub(super) anchor: JournalAnchor,
    pub(super) artifacts: &'a PublishedArtifacts,
    pub(super) dataset: &'a crate::PreparedParameterDatasetV1,
}

pub(super) fn project_and_check_context(
    context: &(PathBuf, Digest32),
    root: &Path,
    input: ProjectionInputs<'_>,
) -> (PathBuf, Digest32) {
    let template = fs::read(&context.0).expect("original whole Root template");
    assert_eq!(Digest32::of_bytes(&template), context.1);
    let original: Value = serde_json::from_slice(&template).expect("complete template");
    let path = |name: &str| {
        PathBuf::from(
            original[name]["path"]
                .as_str()
                .expect("actual pinned source"),
        )
    };
    let baseline_source = path("baseline_material");
    let baseline_pin = original["baseline_material"]["digest"]
        .as_str()
        .expect("whole baseline SHA")
        .parse()
        .expect("digest");
    let ndu_source = PathBuf::from(
        original["ndu"]["journal_path"]
            .as_str()
            .expect("actual NDU"),
    );
    let ndu_pin = original["ndu_journal_digest"]
        .as_str()
        .expect("whole NDU SHA")
        .parse()
        .expect("digest");
    let baseline = id("artifact.parameters.actual-head");
    let now = crate::authbus_ingress::now_ms().expect("actual clock");
    let expiry = original["artifacts"]["expires_at"]
        .as_u64()
        .expect("original expiry")
        .min(input.round.deadline_ms());
    let subject = id(input.identity.agent_id.as_str());
    let mut inputs = crate::ParameterInputContextProjectionV2 {
        subject: &subject,
        spawn_generation: input.identity.spawn_generation,
        round: input.round,
        baseline_artifact: &baseline,
        baseline_material: input.training,
        baseline_material_source: (&baseline_source, baseline_pin),
        artifact_snapshot_source: &input.artifacts.snapshot,
        artifact_snapshot_receipt: input.artifacts.receipt,
        dataset: input.dataset,
        ndu_journal_source: (&ndu_source, ndu_pin),
        neuron_material: input.goal,
        neuron_anchor: input.anchor,
        observed_at_unix_ms: now,
        expires_at_unix_ms: expiry,
    };
    assert_ne!(input.training.scope, input.goal.scope);
    assert_ne!(
        input.training.scope.objective_digest,
        input.goal.scope.objective_digest
    );
    let bytes = crate::project_parameter_input_context_v2(&template, &inputs)
        .expect("actual Dataset facts + separate full Training/Goal material");
    assert_eq!(
        crate::project_parameter_input_context_v2(&template, &inputs).expect("pure exact replay"),
        bytes
    );
    let projected: Value = serde_json::from_slice(&bytes).expect("original complete schema");
    for name in ["trust", "owner_policy", "signal_bindings"] {
        assert_eq!(projected[name], original[name], "preserve whole {name}");
    }
    assert_eq!(
        projected["artifacts"]["current_owner"],
        original["artifacts"]["current_owner"]
    );
    assert_eq!(projected["ndu"], original["ndu"]);
    assert_eq!(
        projected["baseline_material"],
        original["baseline_material"]
    );
    assert_eq!(projected["neuron"]["config"], original["neuron"]["config"]);
    assert_eq!(
        projected["neuron"]["objective_digest"],
        input.goal.scope.objective_digest.to_string()
    );
    assert_eq!(
        projected["objective_digest"],
        input.training.scope.objective_digest.to_string()
    );
    assert_eq!(
        projected["predecessor_registry_head_digest"],
        input.dataset.installed_artifact_head
    );
    assert_ne!(
        projected["predecessor_registry_head_digest"],
        input.dataset.proposal_registry_predecessor
    );
    assert_ne!(
        projected["predecessor_registry_head_digest"],
        projected["artifacts"]["receipt"]["head_digest"]
    );
    assert_eq!(
        projected["dataset"]["snapshot"]["dataset_digest"],
        input.dataset.dataset.dataset_digest
    );
    // Every mutation below occurs before any publication or owner effect.
    inputs.baseline_material_source.1 = digest("wrong complete material pin");
    assert!(crate::project_parameter_input_context_v2(&template, &inputs).is_err());
    inputs.baseline_material_source.1 = baseline_pin;
    inputs.expires_at_unix_ms = input.round.deadline_ms() + 1;
    assert!(crate::project_parameter_input_context_v2(&template, &inputs).is_err());
    inputs.expires_at_unix_ms = expiry;
    inputs.neuron_anchor.sequence = 0;
    assert!(crate::project_parameter_input_context_v2(&template, &inputs).is_err());
    inputs.neuron_anchor = input.anchor;
    let mut wrong_goal = input.goal.clone();
    wrong_goal.body.base_bundle_digest = digest("changed full Goal body");
    inputs.neuron_material = &wrong_goal;
    assert!(crate::project_parameter_input_context_v2(&template, &inputs).is_err());
    inputs.neuron_material = input.goal;
    for changed in [
        {
            let mut v = original.clone();
            v["trust"]["objective_digest"] = json!(input.goal.scope.objective_digest.to_string());
            v
        },
        {
            let mut v = original.clone();
            v["owner_policy"]["dataset_owner_id"] = json!("foreign.dataset.owner");
            v
        },
        {
            let mut v = original.clone();
            v["agent_id"] = json!("foreign.subject");
            v
        },
        {
            let mut v = original.clone();
            v["authority_grants_any"] = json!(true);
            v
        },
    ] {
        assert!(
            crate::project_parameter_input_context_v2(
                &serde_json::to_vec(&changed).expect("complete wrong template"),
                &inputs,
            )
            .is_err()
        );
    }
    assert!(crate::project_parameter_input_context_v2(&vec![b' '; 1_048_577], &inputs).is_err());
    assert_eq!(
        fs::read(&context.0).expect("template remains immutable"),
        template
    );
    write_source(root.join("projected-complete-context.json"), bytes)
}
