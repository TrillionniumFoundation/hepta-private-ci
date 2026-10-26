use super::*;
use hepta_handoff_recovery_v7::streaming_parity::Inputs as StreamInputs;
use pretty_assertions::assert_eq;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

#[test]
fn explicit_v8_report_and_stream_reach_signed_owner_reopen_and_rollback() {
    let study = must(studies::new_v8(-0.002, 32));
    let (profile, loaded) = must(study.load());
    assert_eq!(profile.version(), 8);
    let f = &study.fixture;
    must(admission::positive(
        "prepare",
        &profile,
        &loaded,
        f.paths(),
        &f.output,
        None,
    ));
    let signature = must(f.signature(&f.signing_key));
    let receipt = must(admission::positive(
        "execute",
        &profile,
        &loaded,
        f.paths(),
        &f.output,
        Some(&signature),
    ));
    assert_eq!(receipt["candidate_published"], json!(true));
    assert_eq!(
        receipt["roundtrip"]["candidate"]["prediction_rows"],
        json!(48)
    );
    assert_eq!(
        receipt["roundtrip"]["owner_bytes_unchanged_during_serving_and_rollback"],
        json!(true)
    );
    let dump: Value = must(serde_json::from_slice(&must(read(
        &f.output.join("checkpoint-candidate.json"),
    ))));
    assert_eq!(
        dump["schema"],
        json!("hepta.native-full-checkpoint-dump.v8")
    );
    let before = inventory(&f.output.join("owner"));
    must(admission::positive(
        "execute",
        &profile,
        &loaded,
        f.paths(),
        &f.output,
        Some(&signature),
    ));
    assert_eq!(inventory(&f.output.join("owner")), before);
}

#[test]
fn v8_incomplete_terminal_and_altered_external_stream_pin_reject_before_owner() {
    let study = must(studies::new_v8(-0.002, 17));
    let (profile, loaded) = must(study.load());
    let f = &study.fixture;
    assert!(admission::positive("prepare", &profile, &loaded, f.paths(), &f.output, None).is_err());
    assert!(!f.output.exists());
    let mut value: Value = must(serde_json::from_slice(&must(read(&study.profile))));
    value["parity_header_sha256"] = json!(owner::digest("unregistered data order").to_string());
    let pin = must(studies::write(&study.profile, &value));
    let changed = must(profile::Profile::load(&study.profile, pin));
    assert!(report::load(&changed, &study.paths()).is_err());
}

#[test]
fn complete_stream_exceeds_both_old_limits_and_checks_every_numeric_tail_row() {
    let study = must(studies::new_v8(-0.002, 32));
    let f = &study.fixture;
    let header_digest = must(stream_fixtures::build(f, [20000, 2000]));
    let inputs = must(StreamInputs::load(&f.parity));
    assert_eq!(inputs.header_digest, header_digest);
    assert!(inputs.header["vectors_bytes"].as_u64().unwrap() > 64 * 1024 * 1024);
    assert!(inputs.header["tasks"][0]["rows"].as_u64().unwrap() > 16384);
    let first = must(inputs.compare_unpublished(0));
    let second = must(inputs.compare_unpublished(1));
    assert_eq!(first["prediction_rows"], json!(132000));
    assert_eq!(second["prediction_rows"], json!(132000));
    assert_eq!(first["class_nlls_checked"], json!(528000));
    assert_eq!(second["argmax_predictions_checked"], json!(132000));
    // Tamper the actual final byte: the initial full-file hash must catch it.
    let references = f.parity.join("expected.bin");
    let mut file = must(fs::OpenOptions::new().write(true).open(&references));
    must(file.seek(SeekFrom::End(-1)));
    must(file.write_all(&[1]));
    must(file.sync_all());
    assert!(StreamInputs::load(&f.parity).is_err());
    must(file.seek(SeekFrom::End(-1)));
    must(file.write_all(&[0]));
    // Rehash a wrong last-row logit consistently, proving numeric inference
    // actually reaches that last row rather than only checking stored hashes.
    must(file.seek(SeekFrom::End(-64)));
    must(file.write_all(&0.2501_f64.to_be_bytes()));
    must(file.sync_all());
    let header_path = f.parity.join("parity-header.json");
    let mut header: Value = must(serde_json::from_slice(&must(read(&header_path))));
    let case = header["versions"][1]["cases"]
        .as_array_mut()
        .unwrap()
        .last_mut()
        .unwrap();
    let offset = case["offset_bytes"].as_u64().unwrap();
    let length = case["rows"].as_u64().unwrap() * 64;
    case["sha256"] =
        json!(must(stream_fixtures::hash_file(&references, offset, length)).to_string());
    header["expected_sha256"] = json!(
        must(stream_fixtures::hash_file(
            &references,
            0,
            header["expected_bytes"].as_u64().unwrap()
        ))
        .to_string()
    );
    let digest = must(studies::write(&header_path, &header));
    let mut manifest: Value = must(serde_json::from_slice(&must(read(&f.conversion))));
    manifest["parity_header_sha256"] = json!(digest.to_string());
    must(studies::write(&f.conversion, &manifest));
    let changed = must(StreamInputs::load(&f.parity));
    let error = changed.compare_unpublished(1).unwrap_err();
    assert!(error.to_string().contains("fixed tolerance"));
    // A truncated final vector is rejected; no missing row is silently omitted.
    let vectors = must(
        fs::OpenOptions::new()
            .write(true)
            .open(f.parity.join("vectors.bin")),
    );
    must(vectors.set_len(inputs.header["vectors_bytes"].as_u64().unwrap() - 8));
    assert!(StreamInputs::load(&f.parity).is_err());
    // Fixture Drop removes only these regenerable sparse/constant test streams.
    // CI stdout is the compact full-census receipt; no real research bytes enter.
    println!(
        "{}",
        json!({"scope":"SYNTHETIC full-stream mechanics","header_sha256":header_digest.to_string(),
        "logical_vectors_bytes":inputs.header["vectors_bytes"],"logical_reference_bytes":inputs.header["expected_bytes"],
        "vectors_sha256":inputs.header["vectors_sha256"],"expected_sha256":inputs.header["expected_sha256"],
        "versions":[first,second],"tail_byte_tamper_rejected":true,"self_rehashed_numeric_tail_rejected":true,
        "truncated_final_vector_rejected":true,"scientific_acceptance":false,"owner_opened":false})
    );
}
