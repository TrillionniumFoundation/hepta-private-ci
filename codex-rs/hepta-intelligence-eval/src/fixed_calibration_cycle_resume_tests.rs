use super::*;

#[test]
fn begun_evaluation_never_reexecutes_and_only_complete_original_output_can_reconcile() {
    assert_eq!(
        resume_action(RecoveryMarker::Absent, EvaluatorOutput::Absent).unwrap(),
        ResumeAction::ExecuteIndependentEvaluation
    );
    assert!(resume_action(RecoveryMarker::Matching, EvaluatorOutput::Absent).is_err());
    for marker in [RecoveryMarker::Absent, RecoveryMarker::Matching] {
        assert_eq!(
            resume_action(marker, EvaluatorOutput::Complete).unwrap(),
            ResumeAction::AuthenticateOriginalResult
        );
        assert!(resume_action(marker, EvaluatorOutput::Partial).is_err());
    }
}

fn original() -> (Value, Value, Digest32, Digest32, Vec<u8>, Vec<u8>) {
    let config = Digest32::of_bytes(b"unchanged-original-begun-config");
    let request = Digest32::of_bytes(b"unchanged-original-observer-request");
    let old = b"actual-original-acknowledged-prefix".to_vec();
    let mut full = old.clone();
    full.extend_from_slice(b"fresh-original-cycle-suffix");
    let begin = serde_json::json!({
        "schema":"hepta.fixed-calibration-cycle.begin.v1",
        "config_digest":config.to_string(),"started_at_ms":100,
        "previous_ledger_digest":Digest32::of_bytes(&old).to_string(),
        "qualified":false,"holdout_consumed":false
    });
    let observer = serde_json::json!({
        "request_digest":request.to_string(),"qualified":false,
        "authority_grants_any":false,"holdout_consumed":false,"production_activation":false
    });
    (begin, observer, config, request, full, old)
}

#[test]
fn resume_preserves_original_begun_configuration_request_and_acknowledged_prefix() {
    let (begin, observer, config, request, full, old) = original();
    assert_eq!(
        require_resume_history(&begin, &observer, config, request, &full, &old, 110).unwrap(),
        100
    );
    assert!(
        require_resume_history(
            &begin,
            &observer,
            Digest32::of_bytes(b"new cycle"),
            request,
            &full,
            &old,
            110
        )
        .is_err()
    );
    assert!(
        require_resume_history(
            &begin,
            &observer,
            config,
            Digest32::of_bytes(b"new IDs"),
            &full,
            &old,
            110
        )
        .is_err()
    );
    let mut changed_prefix = full.clone();
    changed_prefix[0] ^= 1;
    assert!(
        require_resume_history(
            &begin,
            &observer,
            config,
            request,
            &changed_prefix,
            &old,
            110
        )
        .is_err()
    );
    assert!(
        require_resume_history(
            &begin,
            &observer,
            config,
            request,
            &full,
            b"reset prefix",
            110
        )
        .is_err()
    );
    assert!(require_resume_history(&begin, &observer, config, request, &full, &[], 110).is_err());
    assert!(require_resume_history(&begin, &observer, config, request, &full, &old, 99).is_err());
}

#[test]
fn resume_refuses_qualification_gold_consumption_and_authority_claims() {
    let (begin, observer, config, request, full, old) = original();
    for field in [
        "qualified",
        "authority_grants_any",
        "holdout_consumed",
        "production_activation",
    ] {
        let mut changed = observer.clone();
        changed[field] = Value::from(true);
        assert!(
            require_resume_history(&begin, &changed, config, request, &full, &old, 110).is_err(),
            "{field}"
        );
        changed.as_object_mut().unwrap().remove(field);
        assert!(
            require_resume_history(&begin, &changed, config, request, &full, &old, 110).is_err(),
            "missing {field}"
        );
    }
    for field in [
        "schema",
        "config_digest",
        "previous_ledger_digest",
        "qualified",
        "holdout_consumed",
        "started_at_ms",
    ] {
        let mut changed = begin.clone();
        changed.as_object_mut().unwrap().remove(field);
        assert!(
            require_resume_history(&changed, &observer, config, request, &full, &old, 110).is_err(),
            "missing {field}"
        );
    }
}

#[test]
fn resume_readonly_native_witness_refuses_torn_tail_without_reset_or_truncation() {
    use std::io::Read;
    let temp = std::env::temp_dir().join(format!(
        "hepta-resume-witness-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir(&temp).unwrap();
    let path = temp.join("original-witness.bin");
    let binding = Digest32::of_bytes(b"actual-original-witness-binding");
    let original = LedgerWitnessStore::create(
        OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(&path)
            .unwrap(),
        binding,
    )
    .unwrap();
    drop(original);
    let witness = LedgerWitnessStore::recover(File::open(&path).unwrap(), binding).unwrap();
    assert_eq!(witness.frontier().unwrap().anchor.sequence, 0);
    drop(witness);
    OpenOptions::new()
        .append(true)
        .open(&path)
        .unwrap()
        .write_all(b"torn-original-tail")
        .unwrap();
    let mut before = Vec::new();
    File::open(&path).unwrap().read_to_end(&mut before).unwrap();
    assert!(LedgerWitnessStore::recover(File::open(&path).unwrap(), binding).is_err());
    let mut after = Vec::new();
    File::open(&path).unwrap().read_to_end(&mut after).unwrap();
    assert_eq!(after, before);
    std::fs::remove_file(&path).unwrap();
    std::fs::remove_dir(&temp).unwrap();
}
