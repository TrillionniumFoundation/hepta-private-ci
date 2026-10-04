//! Synthetic keys with the actual original durable writer/witness and V3 purpose.
use super::*;
use crate::paired_supervised_test_support::SigningFixture;
use crate::paired_supervised_test_support::digest;
use crate::paired_supervised_test_support::id;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use std::fs::File;
use std::fs::OpenOptions;

fn decision(signing: &SigningFixture, name: &str) -> ProductionDecisionV2 {
    let candidates = vec![id("answer"), id("abstain")];
    ProductionDecisionV2 {
        record_id: id(&format!("decision-{name}")),
        episode_id: id(&format!("episode-{name}")),
        run_snapshot_digest: digest("original-run"),
        objective_digest: digest("paired-objective"),
        policy_digest: digest("policy"),
        candidate_ids: candidates.clone(),
        selected_candidate_id: candidates[0].clone(),
        selected_propensity: ProbabilityQ32::ONE,
        completeness: CandidateSetCompletenessReceiptV1 {
            set_id: id(&format!("frontier-{name}")),
            state_digest: digest("state"),
            generator_id: signing.principals[0].principal_id.clone(),
            generator_code_digest: digest("generator-code"),
            grammar_digest: digest("grammar"),
            hard_filter_digest: digest("filters"),
            truncation_digest: digest("truncation"),
            candidates_digest: candidate_ids_digest_v2(&candidates),
            candidate_count: 2,
            omitted_count_bound: 0,
            canonical_order_digest: candidate_order_digest_v2(&candidates),
            complete_for_generator: true,
        },
        support_digest: digest("support"),
    }
}
fn append(writer: &mut LedgerWriter, signing: &SigningFixture, name: &str) {
    let request = decision(signing, name);
    let evidence = signing.sign(0, &decision_signing_payload_v2(&request).unwrap(), 30);
    writer
        .append_decision(
            writer.snapshot().unwrap().head_digest,
            request,
            &evidence,
            30,
        )
        .unwrap();
    let outcome = AuthenticatedOutcomeV1 {
        record_id: id(&format!("outcome-record-{name}")),
        outcome_id: id(&format!("outcome-{name}")),
        episode_id: id(&format!("episode-{name}")),
        observer: signing.principals[1].clone(),
        observed_at: Some(25),
        value: Some(FixedQ32::ZERO),
        unit_profile_digest: digest("units"),
        support_digest: digest("outcome-support"),
        watermark: OutcomeWatermarkV1 {
            latest_observable_at: 26,
            expected_delay_profile_digest: digest("delay"),
            terminality: OutcomeTerminalityV1::Terminal,
            censoring_reason: None,
            correction_predecessor: None,
            finalized_at: Some(27),
        },
    };
    let evidence = signing.sign(1, &outcome_signing_payload_v2(&outcome), 30);
    writer
        .append_outcome(
            writer.snapshot().unwrap().head_digest,
            outcome,
            &evidence,
            30,
        )
        .unwrap();
}
struct Fixture {
    directory: std::path::PathBuf,
    signing: SigningFixture,
    writer: Option<LedgerWriter>,
}
impl Fixture {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let directory = std::env::temp_dir().join(format!(
            "hepta-original-window-e-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        std::fs::create_dir(&directory).unwrap();
        let file = |name: &str| {
            OpenOptions::new()
                .create_new(true)
                .read(true)
                .write(true)
                .open(directory.as_path().join(name))
                .unwrap()
        };
        let signing = SigningFixture::new(false);
        let ledger =
            DurableLedger::create(file("ledger"), digest("actual-ledger-binding"), 4096).unwrap();
        let witness =
            LedgerWitnessStore::create(file("witness"), digest("actual-ledger-binding")).unwrap();
        let dir = File::open(directory.as_path()).unwrap();
        let mut writer =
            LedgerWriter::from_durable(ledger, witness, signing.trust.clone(), &dir, &dir).unwrap();
        append(&mut writer, &signing, "selected");
        Self {
            directory,
            signing,
            writer: Some(writer),
        }
    }
    fn inputs(&self) -> FixedDatasetWindowEvaluatorInputsV3 {
        let snapshot = self.writer.as_ref().unwrap().snapshot().unwrap();
        let source = |name| ParameterRoleSourceV3 {
            path: self.directory.as_path().join(name),
            digest: Digest32::of_bytes(
                &std::fs::read(self.directory.as_path().join(name)).unwrap(),
            )
            .to_string(),
        };
        FixedDatasetWindowEvaluatorInputsV3 {
            schema: "hepta.fixed-dataset-window-inputs.v3".into(),
            round: ParameterPreRegistrationRoundV1 {
                round_digest: digest("round").to_string(),
                round_payload_digest: digest("whole-round").to_string(),
                canonical_policy_digest: digest("canonical").to_string(),
                execution_digest: digest("execution").to_string(),
                admitted_at_ms: 20,
                deadline_ms: 950,
            },
            plan: DatasetWindowFreezePlanWireV3::from_native(&DatasetWindowFreezePlanV3 {
                snapshot_id: id("original-bounded-window"),
                objective_digest: digest("paired-objective"),
                inclusion_policy_digest: digest("original-inclusion"),
                decision_sequence_start: 1,
                decision_sequence_end: 1,
                maximum_episodes: 1,
                maximum_source_records: 16,
                maximum_encoded_bytes: 65_536,
            }),
            ledger: source("ledger"),
            witness: source("witness"),
            ledger_binding: digest("actual-ledger-binding").to_string(),
            maximum_records: 4096,
            maximum_witness_frames: 4096,
            acknowledged_sequence: snapshot.records().len() as u64,
            acknowledged_chain_digest: snapshot.head_digest.to_string(),
        }
    }
    fn output(&self, inputs: &FixedDatasetWindowEvaluatorInputsV3, role: usize) -> Vec<u8> {
        let snapshot = self.writer.as_ref().unwrap().snapshot().unwrap();
        let plan = inputs.plan.native().unwrap();
        let payload = dataset_window_freeze_signing_payload_v3(&snapshot, &plan).unwrap();
        let mut evidence = self.signing.sign(role, &payload, 30);
        evidence.evidence_id = window_evidence_id(
            &encode_fixed_dataset_window_evaluator_inputs_v3(inputs).unwrap(),
            &payload,
        )
        .unwrap();
        let original_test_key = match role {
            0 => 71,
            1 => 72,
            _ => 73,
        };
        evidence.signature = ed25519_dalek::SigningKey::from_bytes(&[original_test_key; 32])
            .sign(&evidence.signing_bytes())
            .to_bytes();
        let window = freeze_dataset_window_from_ledger_v3(
            &snapshot,
            plan.clone(),
            self.signing.principals[2].clone(),
            30,
        )
        .unwrap();
        serde_json::to_vec(&Output {
            schema: "hepta.fixed-dataset-window-evaluation.v3".into(),
            inputs_digest: Digest32::of_bytes(
                &encode_fixed_dataset_window_evaluator_inputs_v3(inputs).unwrap(),
            )
            .to_string(),
            plan: DatasetWindowFreezePlanWireV3::from_native(&plan),
            window: DatasetWindowSnapshotWireV3::from_native(&window),
            signing_payload_hex: payload.iter().map(|b| format!("{b:02x}")).collect(),
            evaluator_evidence: ReviewEvidenceWireV1::from_native(&evidence),
        })
        .unwrap()
    }
}
#[test]
fn dataset_window_e_requires_actual_e_signature_and_recomputes_every_original_fact() {
    let fixture = Fixture::new();
    let inputs = fixture.inputs();
    let snapshot = fixture.writer.as_ref().unwrap().snapshot().unwrap();
    let bytes = fixture.output(&inputs, 2);
    let observed = decode_fixed_dataset_window_evaluator_output_v3(
        &bytes,
        &inputs,
        &snapshot,
        &fixture.signing.trust,
        30,
    )
    .unwrap();
    assert_eq!(
        observed.window.window_policy_digest,
        inputs.plan.native().unwrap().policy_digest()
    );
    assert_eq!(
        observed.window.receipt.snapshot.ledger_head_digest,
        snapshot.head_digest
    );
    let generator = fixture.output(&inputs, 0);
    assert!(
        decode_fixed_dataset_window_evaluator_output_v3(
            &generator,
            &inputs,
            &snapshot,
            &fixture.signing.trust,
            30
        )
        .is_err()
    );
    let mut changed: Output = serde_json::from_slice(&bytes).unwrap();
    changed.plan.maximum_source_records += 1;
    assert!(
        decode_fixed_dataset_window_evaluator_output_v3(
            &serde_json::to_vec(&changed).unwrap(),
            &inputs,
            &snapshot,
            &fixture.signing.trust,
            30
        )
        .is_err()
    );
    let mut changed: Output = serde_json::from_slice(&bytes).unwrap();
    changed.window.receipt.correction_cut_digest = digest("substituted-cut").to_string();
    assert!(
        decode_fixed_dataset_window_evaluator_output_v3(
            &serde_json::to_vec(&changed).unwrap(),
            &inputs,
            &snapshot,
            &fixture.signing.trust,
            30
        )
        .is_err()
    );
    let mut changed: Output = serde_json::from_slice(&bytes).unwrap();
    changed.signing_payload_hex.push_str("00");
    assert!(
        decode_fixed_dataset_window_evaluator_output_v3(
            &serde_json::to_vec(&changed).unwrap(),
            &inputs,
            &snapshot,
            &fixture.signing.trust,
            30
        )
        .is_err()
    );
    assert!(
        decode_fixed_dataset_window_evaluator_output_v3(
            &bytes,
            &inputs,
            &snapshot,
            &fixture.signing.trust,
            950
        )
        .is_err()
    );
    let mut expired: Output = serde_json::from_slice(&bytes).unwrap();
    let mut actual = expired.evaluator_evidence.native().unwrap();
    actual.expires_at = 35;
    actual.signature = ed25519_dalek::SigningKey::from_bytes(&[73; 32])
        .sign(&actual.signing_bytes())
        .to_bytes();
    expired.evaluator_evidence = ReviewEvidenceWireV1::from_native(&actual);
    assert!(
        decode_fixed_dataset_window_evaluator_output_v3(
            &serde_json::to_vec(&expired).unwrap(),
            &inputs,
            &snapshot,
            &fixture.signing.trust,
            36
        )
        .is_err()
    );
}
#[test]
fn complete_frozen_window_is_inspected_with_real_witness_and_never_rewritten_to_later_head() {
    let mut fixture = Fixture::new();
    let inputs = fixture.inputs();
    let output = fixture.output(&inputs, 2);
    let original = fixture.writer.as_ref().unwrap().snapshot().unwrap();
    append(
        fixture.writer.as_mut().unwrap(),
        &fixture.signing,
        "unrelated-later",
    );
    let later = fixture.writer.as_ref().unwrap().snapshot().unwrap();
    assert!(
        decode_fixed_dataset_window_evaluator_output_v3(
            &output,
            &inputs,
            &later,
            &fixture.signing.trust,
            30
        )
        .is_err()
    );
    // The later consumer may validate a historical prefix through its separate
    // original purpose. The issuer cannot relabel that frozen signature as latest.
    decode_fixed_dataset_window_evaluator_output_v3(
        &output,
        &inputs,
        &original,
        &fixture.signing.trust,
        30,
    )
    .unwrap();
    drop(fixture.writer.take());
    let witness = inspect_ledger_witness_frontier(
        File::open(&inputs.witness.path).unwrap(),
        digest("actual-ledger-binding"),
        4096,
    )
    .unwrap();
    assert_eq!(witness.anchor.chain_digest, later.head_digest);
    let reopened = inspect_ledger(
        File::open(&inputs.ledger.path).unwrap(),
        digest("actual-ledger-binding"),
        4096,
        witness.anchor,
    )
    .unwrap();
    assert_eq!(reopened, later);
    assert!(
        inspect_ledger(
            File::open(&inputs.ledger.path).unwrap(),
            digest("actual-ledger-binding"),
            4096,
            LedgerAnchor {
                sequence: inputs.acknowledged_sequence,
                chain_digest: original.head_digest
            }
        )
        .is_err()
    );
}

impl Drop for Fixture {
    fn drop(&mut self) {
        drop(self.writer.take());
        let _ = std::fs::remove_dir_all(&self.directory);
    }
}

#[test]
fn dataset_window_e_rejects_unsigned_round_and_source_substitution_with_original_signature() {
    let fixture = Fixture::new();
    let original_inputs = fixture.inputs();
    let snapshot = fixture.writer.as_ref().unwrap().snapshot().unwrap();
    let original_output = fixture.output(&original_inputs, 2);
    let substitutions: [fn(&mut FixedDatasetWindowEvaluatorInputsV3); 9] = [
        |i| i.round.round_digest = digest("other-original-round").to_string(),
        |i| i.round.round_payload_digest = digest("other-full-original-round").to_string(),
        |i| i.round.canonical_policy_digest = digest("other-window-policy").to_string(),
        |i| i.round.execution_digest = digest("other-execution").to_string(),
        |i| i.ledger.digest = digest("other-protected-ledger-source").to_string(),
        |i| i.witness.digest = digest("other-independent-witness-source").to_string(),
        |i| i.ledger_binding = digest("other-original-ledger-binding").to_string(),
        |i| i.maximum_records -= 1,
        |i| i.maximum_witness_frames -= 1,
    ];
    for (index, substitute) in substitutions.iter().enumerate() {
        let mut inputs = fixture.inputs();
        substitute(&mut inputs);
        let mut output: Output = serde_json::from_slice(&original_output).unwrap();
        output.inputs_digest =
            Digest32::of_bytes(&encode_fixed_dataset_window_evaluator_inputs_v3(&inputs).unwrap())
                .to_string();
        assert!(
            decode_fixed_dataset_window_evaluator_output_v3(
                &serde_json::to_vec(&output).unwrap(),
                &inputs,
                &snapshot,
                &fixture.signing.trust,
                30,
            )
            .is_err(),
            "accepted unsigned original request substitution {index}"
        );
    }
}
