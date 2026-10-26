use super::*;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

#[path = "../../../trained-cell-v5/actual-review-driver/src/positive_fixtures.rs"]
mod fixtures;
use fixtures::*;
#[path = "handoff_fixtures.rs"]
mod handoff_fixtures;

#[test]
fn external_signature_synthetic_fixture_publishes_reopens_serves_and_rolls_back() {
    let mut f = must(Fixture::new());
    must(handoff_fixtures::wrap(&mut f));
    let prepared = must(f.prepare());
    assert_eq!(prepared["candidate_published"], json!(false));
    let signature = must(f.signature(&f.signing_key));
    let result = must(run(
        "execute",
        &f.protocol,
        &f.inputs,
        &f.gate,
        f.paths(),
        &f.output,
        Some(&signature),
    ));
    assert_eq!(
        (
            result["candidate_published"].clone(),
            result["production_authority"].clone(),
            result["production_activation"].clone()
        ),
        (json!(true), json!(false), json!(false))
    );
    assert_eq!(
        result["roundtrip"]["owner_bytes_unchanged_during_serving_and_rollback"],
        json!(true)
    );
}

#[test]
fn wrong_external_key_or_changed_independent_evidence_cannot_publish() {
    let mut f = must(Fixture::new());
    must(handoff_fixtures::wrap(&mut f));
    must(f.prepare());
    let before = must(owner::inventory(&f.output.join("owner")));
    let signature = must(f.signature(&SigningKey::from_bytes(&[202; 32])));
    assert!(
        run(
            "execute",
            &f.protocol,
            &f.inputs,
            &f.gate,
            f.paths(),
            &f.output,
            Some(&signature)
        )
        .is_err()
    );
    assert_eq!(must(owner::inventory(&f.output.join("owner"))), before);
    let signature = must(f.signature(&f.signing_key));
    must(fs::write(&f.replay, b"{}"));
    assert!(
        run(
            "execute",
            &f.protocol,
            &f.inputs,
            &f.gate,
            f.paths(),
            &f.output,
            Some(&signature)
        )
        .is_err()
    );
    assert_eq!(must(owner::inventory(&f.output.join("owner"))), before);
}

#[test]
fn failed_actual_gate_cannot_prepare_even_with_present_audit_envelopes() {
    let mut f = must(Fixture::new());
    f.inputs.all_numeric_gates_pass = false;
    assert!(f.prepare().is_err());
    assert!(!f.output.exists());
}

// This deliberately abrupt subprocess leaves the real fenced owner's durable
// files in each publication phase. All science and keys are synthetic fixtures.
#[test]
#[ignore = "run only by publication_crash_matrix_recovers_exact_signed_operation"]
fn publication_crash_worker() {
    let mut f = must(Fixture::new());
    must(handoff_fixtures::wrap(&mut f));
    f.output = std::path::PathBuf::from(must(std::env::var("HEPTA_V7_RECOVERY_OUTPUT")));
    let phase: u8 = must(must(std::env::var("HEPTA_V7_RECOVERY_PHASE")).parse());
    let _host = seed_phase(&f, phase);
    std::process::exit(23); // intentionally no owner/fixture destructors
}

fn seed_phase(f: &Fixture, phase: u8) -> LearningArtifactOwnerHost {
    let prepared: Value = must(serde_json::from_slice(&must(report::read(
        &f.output.join("proposal.json"),
    ))));
    let issued = must(prepared["issued_at"].as_u64().ok_or("issued"));
    let audits = must(evidence(
        &f.protocol,
        &f.inputs,
        &f.gate,
        &f.replay,
        &f.statistics,
        &f.conversion,
    ));
    let context = must(positive_owner::open(
        &f.inputs,
        audits,
        &f.output.join("owner"),
        issued,
        positive_owner::Mode::Execute,
    ));
    let mut registry = context.owner.registry().clone();
    let config = context.config;
    let request = context.request;
    drop(context.owner);
    let host = must(LearningArtifactOwnerHost::open_with_required_current_head(
        &config.root,
        config.trust,
        config.writer_lease,
        must(config.required_current_head.ok_or("baseline anchor")),
        issued,
    ));
    let mut transaction = must(host.begin_publication(
        request.operation_id.clone(),
        request.admission.clone(),
        &config.withdrawal_registry,
        &registry,
        request.expected_registry_predecessor_head,
        issued,
    ));
    must(host.stage_compatibility_registration(&transaction, &mut registry, issued));
    if phase >= 1 {
        must(host.ensure_payload_durable(&mut transaction, &registry, &request.payload, issued));
    }
    if phase >= 2 {
        must(host.ensure_registry_durable(
            &mut transaction,
            &registry,
            &config.withdrawal_registry,
            config.storage_binding,
            issued,
        ));
    }
    if phase >= 3 {
        must(host.ensure_witness_durable(
            &mut transaction,
            &request.signed_current_head,
            &config.withdrawal_registry,
            issued,
        ));
    }
    if phase == 3 {
        // Reproduce the valid crash image after CURRENT became durable but
        // before its WitnessDurable checkpoint became durable.
        let operation = Digest32::of_bytes(request.operation_id.as_str().as_bytes());
        must(fs::remove_file(
            config
                .root
                .join("transactions")
                .join(format!("{operation}-3.checkpoint")),
        ));
    }
    if phase == 5 {
        must(host.acknowledge(&mut transaction, &config.withdrawal_registry, issued));
    }
    host
}

#[test]
fn publication_crash_matrix_recovers_exact_signed_operation() {
    for phase in 0..=5 {
        let mut f = must(Fixture::new());
        must(handoff_fixtures::wrap(&mut f));
        must(f.prepare());
        let signature = must(f.signature(&f.signing_key));
        let child = must(
            std::process::Command::new(must(std::env::current_exe()))
                .args([
                    "positive::tests::publication_crash_worker",
                    "--exact",
                    "--ignored",
                    "--nocapture",
                ])
                .env("HEPTA_V7_RECOVERY_OUTPUT", &f.output)
                .env("HEPTA_V7_RECOVERY_PHASE", phase.to_string())
                .stdout(std::process::Stdio::piped())
                .stderr(std::process::Stdio::piped())
                .spawn(),
        );
        let pid = child.id();
        let result = must(child.wait_with_output());
        let worker_root =
            std::env::temp_dir().join(format!("hepta-v5-external-review-unit-{pid}-1"));
        if worker_root.is_dir() {
            must(fs::remove_dir_all(worker_root));
        }
        assert_eq!(
            result.status.code(),
            Some(23),
            "phase {phase}: {}",
            String::from_utf8_lossy(&result.stderr)
        );
        let first = must(run(
            "execute",
            &f.protocol,
            &f.inputs,
            &f.gate,
            f.paths(),
            &f.output,
            Some(&signature),
        ));
        assert_eq!(first["candidate_published"], json!(true));
        assert_eq!(
            first["roundtrip"]["checkpoint_exports"]
                .as_array()
                .map(Vec::len),
            Some(2)
        );
        let before = must(owner::inventory(&f.output.join("owner")));
        let retried = must(run(
            "execute",
            &f.protocol,
            &f.inputs,
            &f.gate,
            f.paths(),
            &f.output,
            Some(&signature),
        ));
        assert_eq!(retried, first);
        assert_eq!(must(owner::inventory(&f.output.join("owner"))), before);
    }
}

#[test]
fn changed_proposal_or_payload_cannot_recover_another_operation() {
    let mut f = must(Fixture::new());
    must(handoff_fixtures::wrap(&mut f));
    must(f.prepare());
    let signature = must(f.signature(&f.signing_key));
    drop(seed_phase(&f, 2));
    let before = must(owner::inventory(&f.output.join("owner")));
    f.inputs.candidate[0] ^= 1;
    assert!(
        run(
            "execute",
            &f.protocol,
            &f.inputs,
            &f.gate,
            f.paths(),
            &f.output,
            Some(&signature)
        )
        .is_err()
    );
    assert_eq!(must(owner::inventory(&f.output.join("owner"))), before);
}

#[test]
fn valid_mid17_transport_cannot_borrow_terminal32_science_before_any_owner_write() {
    let mut f = must(Fixture::new());
    must(handoff_fixtures::wrap(&mut f));
    must(f.prepare());
    let signature = must(f.signature(&f.signing_key));
    let before = must(owner::inventory(&f.output.join("owner")));
    let mut midpoint = must(Fixture::new());
    must(handoff_fixtures::wrap_at(&mut midpoint, 17));
    let decoded = must(codex_hepta_neuron::TrainingHandoffBundleV7::decode(
        &midpoint.inputs.candidate,
        Digest32::of_bytes(&midpoint.inputs.candidate),
    ));
    assert!(
        decoded
            .checkpoints()
            .iter()
            .all(|cell| cell.pending_actions().len() == 7)
    );
    assert!(midpoint.prepare().is_err());
    assert!(!midpoint.output.exists());
    f.inputs.candidate = midpoint.inputs.candidate.clone();
    let error = run(
        "execute",
        &f.protocol,
        &f.inputs,
        &f.gate,
        f.paths(),
        &f.output,
        Some(&signature),
    )
    .expect_err("midpoint must not obtain terminal scientific admission");
    assert!(
        error
            .to_string()
            .contains("completed exact32 terminal candidate")
    );
    assert_eq!(must(owner::inventory(&f.output.join("owner"))), before);
}

#[test]
fn self_consistently_rehashed_wrong_terminal_state_review_cannot_touch_owner() {
    let mut f = must(Fixture::new());
    must(handoff_fixtures::wrap(&mut f));
    must(f.prepare());
    let signature = must(f.signature(&f.signing_key));
    let before = must(owner::inventory(&f.output.join("owner")));
    let mut expected = must(terminal_review::commitment(&f.inputs, &f.gate));
    let cell = expected["cells"]
        .as_object()
        .expect("cells")
        .keys()
        .next()
        .expect("first cell")
        .clone();
    expected["cells"][cell]["state_sha256"] =
        json!(owner::digest("another terminal state").to_string());
    // Update all envelope hashes, so rejection must compare the reviewed state
    // map to the actual decoded payload rather than merely noticing stale hashes.
    must(handoff_fixtures::install_terminal_review(&mut f, expected));
    let error = run(
        "execute",
        &f.protocol,
        &f.inputs,
        &f.gate,
        f.paths(),
        &f.output,
        Some(&signature),
    )
    .expect_err("different reviewed terminal state must reject");
    assert!(
        error
            .to_string()
            .contains("reviewed terminal checkpoint map differs")
    );
    assert_eq!(must(owner::inventory(&f.output.join("owner"))), before);
}
