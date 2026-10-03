//! Real original signed history and the same actual Root transport; no fake ACK.
use super::*;
use crate::plasticity_runtime::parameter_dataset::parameter_dataset_window::*;

fn plan(snapshot: &LedgerSnapshot) -> DatasetWindowFreezePlanV3 {
    DatasetWindowFreezePlanV3 {
        snapshot_id: id("dataset.actual.window.round"),
        objective_digest: match &snapshot.records()[0].event {
            LedgerEvent::AuthenticatedDecisionV2(d) => d.objective_digest,
            _ => panic!("original admitted decision"),
        },
        inclusion_policy_digest: digest("actual pinned window inclusion"),
        decision_sequence_start: 1,
        decision_sequence_end: 2,
        maximum_episodes: 1,
        maximum_source_records: 2,
        maximum_encoded_bytes: 8192,
    }
}
#[test]
fn whole_window_codec_retains_real_complete_history_above_ordinary_frame_without_signing() {
    let root = tempfile::tempdir().expect("independent root");
    let mut fixture = clock_fixture(crate::authbus_ingress::now_ms);
    let now = crate::authbus_ingress::now_ms().expect("clock");
    let scope = JournalScope {
        scope_digest: digest("window fixture scope"),
        objective_digest: fixture.parameter.admission.objective_digest,
    };
    let (trust, _) = learning_trust(scope, now, now + 120_000);
    populate_original_dataset_ledger_count(&mut fixture, root.path(), &trust, now, 64);
    let snapshot = fixture.owner.ledger.snapshot().expect("held original");
    let source_before = fs::read(&fixture.files.ledger).expect("original file");
    assert!(source_before.len() > crate::MAX_CONTROL_FRAME_BYTES as usize);
    assert!(
        crate::parameter_admission_query::decode_hex(&crate::client::encode_hex(&source_before))
            .is_err(),
        "the original ordinary decoder stays bounded"
    );
    let original_e = dataset_support::sign(
        &trust,
        2,
        LearningEvidenceRoleV1::Evaluator,
        b"genuine independent fixture producer",
        now,
    );
    let producer = trust
        .verifier()
        .verify(
            LearningEvidenceRoleV1::Evaluator,
            &original_e,
            b"genuine independent fixture producer",
            now,
        )
        .expect("real original E")
        .principal()
        .clone();
    let explicit = plan(&snapshot);
    let result = derive(
        &fixture.owner.ledger,
        &snapshot,
        DatasetPlan::WindowV3(explicit.clone()),
        producer.clone(),
        now,
        Digest32::ZERO,
        fixture.owner.artifacts.head_digest(),
    )
    .expect("same owner derives");
    result.verify_at(now).expect("whole original receipt");
    let crate::plasticity_runtime::parameter_dataset::PreparedDataset::WindowV3(facts) =
        result.finish().expect("whole bound")
    else {
        panic!("explicit purpose")
    };
    let bytes = facts
        .canonical_source_bytes()
        .expect("sole original result codec");
    assert!(bytes.len() > crate::MAX_CONTROL_FRAME_BYTES as usize);
    let retained = crate::PreparedParameterDatasetWindowV3::from_source_bytes(&bytes)
        .expect("whole retained result");
    assert_eq!(
        retained
            .canonical_source_bytes()
            .expect("same original bytes"),
        bytes
    );
    assert_eq!(
        retained.ledger_source_bytes().expect("whole source"),
        source_before
    );
    let native = retained.window.native().expect("native original window");
    verify_dataset_window_snapshot_against_ledger_v3(&native, &explicit, &snapshot, now)
        .expect("actual same source");
    assert_eq!(native.receipt.snapshot.source_record_digests.len(), 2);
    assert_eq!(
        bounded_hex(&retained.freeze_payload_hex, 262_144).expect("full signed-purpose bytes"),
        dataset_window_freeze_signing_payload_v3(&snapshot, &explicit)
            .expect("sole original derivation")
    );
    assert_eq!(
        fs::read(&fixture.files.ledger).expect("same held file"),
        source_before
    );
    let mut too_small = explicit;
    too_small.maximum_source_records = 1;
    assert!(
        derive(
            &fixture.owner.ledger,
            &snapshot,
            DatasetPlan::WindowV3(too_small),
            producer,
            now,
            Digest32::ZERO,
            fixture.owner.artifacts.head_digest()
        )
        .is_err()
    );
    assert!(
        crate::PreparedParameterDatasetWindowV3::from_source_bytes(&vec![
            b' ';
            MAX_PREPARED_DATASET_WINDOW_BYTES_V3
                + 1
        ])
        .is_err()
    );
    assert!(bounded_hex("0", 16).is_err());
    assert!(bounded_hex("GG", 16).is_err());
}

pub(super) async fn verify_actual_window_socket(
    client: &AgentdClient,
    round: &crate::AgentdSelfIterationRoundV1,
    context: &(PathBuf, Digest32),
    root: &Path,
    snapshot: &LedgerSnapshot,
    expected_source: &[u8],
) {
    assert!(expected_source.len() > crate::MAX_CONTROL_FRAME_BYTES as usize);
    let context: Value = serde_json::from_slice(&fs::read(&context.0).expect("protected context"))
        .expect("whole context");
    let producer: PrincipalWire = serde_json::from_value(context["dataset"]["producer"].clone())
        .expect("whole original producer");
    let producer_source = write_source(
        root.join("window-producer.json"),
        serde_json::to_vec(&producer).expect("pure original codec"),
    );
    let explicit = plan(snapshot);
    let plan_source = write_source(
        root.join("window-plan.json"),
        serde_json::to_vec(&DatasetWindowFreezePlanWireV3::from_native(&explicit))
            .expect("sole whole plan codec"),
    );
    let (generation, facts) = client
        .prepare_parameter_dataset_window_v3(
            round.clone(),
            producer_source.0.clone(),
            producer_source.1,
            plan_source.0.clone(),
            plan_source.1,
        )
        .await
        .expect("actual Root whole-source response within original 2s");
    assert_eq!(
        generation, 2,
        "actual runtime; original send verifies spawn1 separately"
    );
    let original = facts.canonical_source_bytes().expect("whole result");
    assert!(original.len() > crate::MAX_CONTROL_FRAME_BYTES as usize);
    assert_eq!(
        facts.ledger_source_bytes().expect("same original binary"),
        expected_source
    );
    assert_eq!(facts.ledger_head_digest, snapshot.head_digest.to_string());
    let native = facts.window.native().expect("original untrusted codec");
    verify_dataset_window_snapshot_against_ledger_v3(
        &native,
        &explicit,
        snapshot,
        crate::authbus_ingress::now_ms().expect("fresh clock"),
    )
    .expect("same full actual facts");
    let (_, repeated) = client
        .prepare_parameter_dataset_window_v3(
            round.clone(),
            producer_source.0.clone(),
            producer_source.1,
            plan_source.0.clone(),
            plan_source.1,
        )
        .await
        .expect("same bounded readonly query");
    assert_eq!(
        repeated.canonical_source_bytes().expect("whole repeat"),
        original
    );
    assert!(
        client
            .prepare_parameter_dataset_window_v3(
                round.clone(),
                producer_source.0,
                producer_source.1,
                plan_source.0,
                digest("foreign whole plan pin")
            )
            .await
            .is_err()
    );
    assert_eq!(
        crate::canary_operation_receipt::response_limit(&crate::AgentdMethod::Health),
        crate::MAX_CONTROL_FRAME_BYTES
    );
}
