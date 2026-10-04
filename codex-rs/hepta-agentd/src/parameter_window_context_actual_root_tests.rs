//! Real full E signature and original frozen checkpoint Sources in Goal mode.
use super::*;

pub(super) async fn project_signed_window_context(
    client: &AgentdClient,
    context: &(PathBuf, Digest32),
    root: &Path,
    identity: &crate::AgentdIdentity,
    round: &crate::AgentdSelfIterationRoundV1,
    training: &NeuronGenerationMaterialV2,
    goal: &NeuronGenerationMaterialV2,
    anchor: JournalAnchor,
    artifacts: &PublishedArtifacts,
    facts: &crate::PreparedParameterDatasetWindowV3,
    trust: &ActivatedLearningTrustV1,
) -> (PathBuf, Digest32) {
    let template = fs::read(&context.0).expect("whole original protected context");
    let mut original: Value = serde_json::from_slice(&template).expect("original complete DTO");
    let path = |name: &str| PathBuf::from(original[name]["path"].as_str().expect("Source path"));
    let baseline_path = path("baseline_material");
    let baseline_pin = original["baseline_material"]["digest"]
        .as_str()
        .unwrap()
        .parse()
        .unwrap();
    let ndu_path = PathBuf::from(original["ndu"]["journal_path"].as_str().unwrap());
    let ndu_pin = original["ndu_journal_digest"]
        .as_str()
        .unwrap()
        .parse()
        .unwrap();
    let now = crate::authbus_ingress::now_ms().expect("fresh clock");
    let payload = facts.freeze_payload_hex.clone();
    let payload =
        crate::plasticity_runtime::parameter_dataset::parameter_dataset_window::bounded_hex(
            &payload,
            4096 * 32 + 4096,
        )
        .unwrap();
    let evidence =
        dataset_support::sign(trust, 2, LearningEvidenceRoleV1::Evaluator, &payload, now);
    let producer = trust
        .verifier()
        .verify(LearningEvidenceRoleV1::Evaluator, &evidence, &payload, now)
        .unwrap()
        .principal()
        .clone();
    let plan = facts.plan.native().unwrap();
    // Decode only original held source bytes; independent signature is genuine.
    // The original ledger snapshot itself is pinned by the actual Root port.
    let original_window = facts.window.native().unwrap();
    let mut window = original_window.clone();
    window.receipt = freeze_dataset_receipt_v3(
        DatasetFreezeRequestV1 {
            snapshot_id: window.receipt.snapshot.snapshot_id.clone(),
            producer,
            ledger_head_digest: window.receipt.snapshot.ledger_head_digest,
            objective_digest: window.receipt.snapshot.objective_digest,
            eligible_frontier: window.receipt.snapshot.eligible_frontier,
            outcome_watermark: window.receipt.snapshot.outcome_watermark,
            correction_cut_digest: window.receipt.correction_cut_digest,
            revocation_cut_digest: window.receipt.revocation_cut_digest,
            inclusion_policy_digest: window.receipt.inclusion_policy_digest,
            source_record_digests: window.receipt.snapshot.source_record_digests.clone(),
            pending_outcomes: window.receipt.snapshot.pending_outcomes,
            censored_outcomes: window.receipt.snapshot.censored_outcomes,
        },
        now,
    )
    .expect("sole original receipt codec with actual E producer");
    // The independently enrolled fixture template authorizes the actual E
    // principal. The projection must preserve this whole policy; it cannot
    // turn the unsigned original port producer into the signed issuer.
    original["owner_policy"]["dataset_owner_id"] =
        json!(window.receipt.producer.principal_id.as_str());
    let template =
        serde_json::to_vec(&original).expect("complete independently enrolled E template");
    let goal_source = write_source(
        root.join("whole-frozen-Goal.hptngm02"),
        encode_neuron_generation_material_v2(goal).unwrap(),
    );
    let (generation, checkpoint, raw) = client
        .prepare_parameter_checkpoint_source_v1(round.clone(), goal_source.0.clone(), goal_source.1)
        .await
        .expect("one original complete response");
    assert_eq!(generation, 2);
    assert_eq!(checkpoint.anchor, anchor);
    let checkpoint_source = write_source(root.join("whole-frozen-checkpoint-response.json"), raw);
    let subject = id(identity.agent_id.as_str());
    let baseline = id("artifact.parameters.actual-head");
    let inputs = crate::ParameterInputContextProjectionV3 {
        subject: &subject,
        spawn_generation: identity.spawn_generation,
        round,
        baseline_artifact: &baseline,
        baseline_material: training,
        baseline_material_source: (&baseline_path, baseline_pin),
        artifact_snapshot_source: &artifacts.snapshot,
        artifact_snapshot_receipt: artifacts.receipt,
        dataset: crate::ParameterInputContextDatasetV3::WindowV3 {
            facts,
            plan: &plan,
            window: &window,
            evaluator: &evidence,
        },
        frozen_neuron: Some(crate::ParameterInputContextFrozenNeuronV3 {
            checkpoint_response: (&checkpoint_source.0, checkpoint_source.1),
            goal_material: (&goal_source.0, goal_source.1),
        }),
        ndu_journal_source: (&ndu_path, ndu_pin),
        neuron_material: goal,
        neuron_anchor: anchor,
        observed_at_unix_ms: now,
        expires_at_unix_ms: original["artifacts"]["expires_at"]
            .as_u64()
            .unwrap()
            .min(round.deadline_ms()),
    };
    let bytes = crate::project_parameter_input_context_v3(&template, &inputs)
        .expect("whole signed Window + actual Goal frozen Sources");
    let decoded: Value = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(
        decoded["dataset_window"]["evaluator"]["signature_hex"],
        crate::client::encode_hex(&evidence.signature)
    );
    assert_eq!(
        decoded["frozen_neuron"]["checkpoint_response"]["digest"],
        checkpoint_source.1.to_string()
    );
    for preserved in ["trust", "owner_policy", "signal_bindings", "ndu"] {
        assert_eq!(decoded[preserved], original[preserved]);
    }
    assert_ne!(training.scope, goal.scope);
    let mut tampered = evidence.clone();
    tampered.signature[0] ^= 1;
    let invalid = crate::ParameterInputContextProjectionV3 {
        dataset: crate::ParameterInputContextDatasetV3::WindowV3 {
            facts,
            plan: &plan,
            window: &window,
            evaluator: &tampered,
        },
        ..inputs
    };
    assert!(crate::project_parameter_input_context_v3(&template, &invalid).is_err());
    write_source(
        root.join("projected-signed-window-frozen-context-v3.json"),
        bytes,
    )
}
