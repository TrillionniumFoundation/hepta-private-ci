//! Actual process and file-durability boundaries with synthetic numeric data.
#![allow(clippy::unwrap_used)]
use super::*;
use pretty_assertions::assert_eq;

fn fixture() -> (
    Vec<u8>,
    Vec<u8>,
    Model,
    serde_json::Value,
    serde_json::Value,
) {
    let pin = |text: &str| Digest32::of_bytes(text.as_bytes()).to_string();
    let model = Model {
        manifest: Source {
            path: "/not-read-manifest".into(),
            digest: pin("manifest"),
        },
        weights: Source {
            path: "/not-read-weights".into(),
            digest: pin("weights"),
        },
    };
    let manifest = serde_json::json!({"runtime_digest":pin("runtime"),"encoder_digest":pin("encoder"),"head_digest":pin("head"),"weights_filename":"not-read-weights"});
    let features = vec![1_i64; 512];
    let input=serde_json::to_string(&serde_json::json!({"request_id":"original-request","feature_vector_q24":features,"expected_output_width":10})).unwrap()+"\n";
    let feature_bytes = features
        .iter()
        .flat_map(|v| v.to_be_bytes())
        .collect::<Vec<_>>();
    let observation = serde_json::json!({"schema":"hepta.cpu-neuron.offline-observation.v1","request_id":"original-request",
        "input_line_digest":Digest32::of_bytes(input.as_bytes()).to_string(),"model_manifest_digest":model.manifest.digest,
        "input_digest":Digest32::of_bytes(&feature_bytes).to_string(),"executed_at_ms":101,
        "terminal_observed":true,"succeeded":true,"runtime_digest":manifest["runtime_digest"],
        "weights_digest":model.weights.digest,"encoder_digest":manifest["encoder_digest"],"head_digest":manifest["head_digest"],
        "drive_q24":[0,10,0,0,0,0,0,0,0,0],"prediction_q24":[0,1,0,0,0,0,0,0,0,0],"latency_micros":12,
        "resident_bytes":1024,"transient_allocation_bytes":128,"qualified":false,"authority_grants_any":false});
    let output = serde_json::to_string(&observation).unwrap() + "\n";
    let status = serde_json::json!({"started_ms":100,"finished_ms":102,"elapsed_micros":2012});
    (
        input.into_bytes(),
        output.into_bytes(),
        model,
        manifest,
        status,
    )
}
#[test]
fn original_numeric_identity_and_actual_clock_are_not_replaced_by_claimed_success() {
    let (input, output, model, manifest, status) = fixture();
    let parsed = parse(
        &output,
        std::slice::from_ref(&input),
        &model,
        &manifest,
        &status,
    )
    .unwrap();
    assert_eq!((parsed.rows[0].1.class(), parsed.started_ms), (1, 100));
    for (field, value) in [
        ("request_id", serde_json::json!("different-request")),
        (
            "weights_digest",
            serde_json::json!(Digest32::of_bytes(b"different-weights").to_string()),
        ),
        ("executed_at_ms", serde_json::json!(103)),
        ("latency_micros", serde_json::json!(2013)),
        ("authority_grants_any", serde_json::json!(true)),
        ("terminal_observed", serde_json::json!(false)),
        ("extra_success_field", serde_json::json!(true)),
    ] {
        let mut changed: serde_json::Value = serde_json::from_slice(&output).unwrap();
        changed[field] = value;
        let changed = (serde_json::to_string(&changed).unwrap() + "\n").into_bytes();
        assert!(
            parse(
                &changed,
                std::slice::from_ref(&input),
                &model,
                &manifest,
                &status
            )
            .is_err(),
            "{field}"
        );
    }
    assert!(
        parse(
            &output[..output.len() - 1],
            std::slice::from_ref(&input),
            &model,
            &manifest,
            &status
        )
        .is_err()
    );
    assert!(
        parse(
            &[output.clone(), output].concat(),
            std::slice::from_ref(&input),
            &model,
            &manifest,
            &status
        )
        .is_err()
    );
}

#[test]
#[ignore = "requires an isolated actual Root-owned numeric fixture namespace"]
fn retained_numeric_intent_forbids_reexecution_after_real_timeout_and_physical_join() {
    use std::os::unix::fs::PermissionsExt;
    assert!(std::fs::read_to_string("/proc/self/status").unwrap().lines().any(|line|line.split_whitespace().collect::<Vec<_>>()==["Uid:","0","0","0","0"]));
    let directory =
        std::path::PathBuf::from(std::env::var_os("TMPDIR").expect("isolated Root fixture parent"))
            .join(format!(
                "hepta-paired-numeric-native-{}-{}",
                std::process::id(),
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap()
                    .as_nanos()
            ));
    std::fs::create_dir(&directory).unwrap();
    std::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o700)).unwrap();
    let (input, _, _, manifest, _) = fixture();
    let bytes = b"#!/bin/sh\nprintf 'numeric-child-started\\n'\nexec /usr/bin/sleep 10\n";
    let scorer_path = directory.join("fixed-numeric-fixture");
    create_private(&scorer_path, bytes).unwrap();
    std::fs::set_permissions(&scorer_path, std::fs::Permissions::from_mode(0o700)).unwrap();
    let scorer = Source {
        path: scorer_path,
        digest: Digest32::of_bytes(bytes).to_string(),
    };
    let weights = b"synthetic-numeric-test-only-no-scientific-weights";
    let weights_path = directory.join("weights");
    create_private(&weights_path, weights).unwrap();
    let mut manifest = manifest;
    manifest["weights_digest"] = Digest32::of_bytes(weights).to_string().into();
    manifest["weights_filename"] = "weights".into();
    let manifest = serde_json::to_vec(&manifest).unwrap();
    let manifest_path = directory.join("manifest.json");
    create_private(&manifest_path, &manifest).unwrap();
    let model = Model {
        manifest: Source {
            path: manifest_path,
            digest: Digest32::of_bytes(&manifest).to_string(),
        },
        weights: Source {
            path: weights_path,
            digest: Digest32::of_bytes(weights).to_string(),
        },
    };
    let execution_dir = directory.join("operation");
    std::fs::create_dir(&execution_dir).unwrap();
    std::fs::set_permissions(&execution_dir, std::fs::Permissions::from_mode(0o700)).unwrap();
    assert!(
        execute(
            &scorer,
            &model,
            std::slice::from_ref(&input),
            &execution_dir,
            Instant::now() + Duration::from_millis(150)
        )
        .is_err()
    );
    let intent = std::fs::read(execution_dir.join("intent.json")).unwrap();
    let output = std::fs::read(execution_dir.join("observations.jsonl")).unwrap();
    assert_eq!(output, b"numeric-child-started\n");
    assert!(
        execute(
            &scorer,
            &model,
            &[input],
            &execution_dir,
            Instant::now() + Duration::from_secs(1)
        )
        .is_err()
    );
    assert_eq!(
        std::fs::read(execution_dir.join("intent.json")).unwrap(),
        intent
    );
    assert_eq!(
        std::fs::read(execution_dir.join("observations.jsonl")).unwrap(),
        output
    );
    assert!(!execution_dir.join("status.json").exists());
    std::fs::remove_dir_all(directory).unwrap();
}

#[test]
#[ignore = "requires an isolated actual Root-owned numeric fixture namespace"]
fn completed_numeric_recovery_reads_original_full_output_without_another_process() {
    use std::os::unix::fs::PermissionsExt;
    let directory =
        std::path::PathBuf::from(std::env::var_os("TMPDIR").expect("isolated Root fixture parent"))
            .join(format!(
                "hepta-paired-numeric-completed-native-{}-{}",
                std::process::id(),
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap()
                    .as_nanos()
            ));
    std::fs::create_dir(&directory).unwrap();
    std::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o700)).unwrap();
    let (input, _, _, mut manifest, _) = fixture();
    let program=br#"#!/usr/bin/python3.12
import hashlib,json,pathlib,struct,sys,time
manifest=json.loads(pathlib.Path(sys.argv[1]).read_bytes())
for line in sys.stdin.buffer:
    start=time.monotonic_ns()
    at=time.time_ns()//1000000
    request=json.loads(line)
    features=b''.join(struct.pack('>q',item) for item in request['feature_vector_q24'])
    result={'schema':'hepta.cpu-neuron.offline-observation.v1','request_id':request['request_id'],
      'input_line_digest':hashlib.sha256(line).hexdigest(),'input_digest':hashlib.sha256(features).hexdigest(),
      'model_manifest_digest':sys.argv[2],'executed_at_ms':at,'terminal_observed':True,'succeeded':True,
      'runtime_digest':manifest['runtime_digest'],'weights_digest':manifest['weights_digest'],
      'encoder_digest':manifest['encoder_digest'],'head_digest':manifest['head_digest'],
      'drive_q24':[0,10,0,0,0,0,0,0,0,0],'prediction_q24':[0,1,0,0,0,0,0,0,0,0],
      'latency_micros':max(1,(time.monotonic_ns()-start)//1000),'resident_bytes':1024,
      'transient_allocation_bytes':128,'qualified':False,'authority_grants_any':False}
    print(json.dumps(result,separators=(',',':')),flush=True)
"#;
    let scorer_path = directory.join("fixed-synthetic-numeric");
    create_private(&scorer_path, program).unwrap();
    std::fs::set_permissions(&scorer_path, std::fs::Permissions::from_mode(0o700)).unwrap();
    let scorer = Source {
        path: scorer_path,
        digest: Digest32::of_bytes(program).to_string(),
    };
    let weights = b"synthetic-test-weights-not-a-scientific-model";
    let weights_path = directory.join("weights");
    create_private(&weights_path, weights).unwrap();
    manifest["weights_digest"] = Digest32::of_bytes(weights).to_string().into();
    manifest["weights_filename"] = "weights".into();
    let manifest = serde_json::to_vec(&manifest).unwrap();
    let manifest_path = directory.join("manifest.json");
    create_private(&manifest_path, &manifest).unwrap();
    let model = Model {
        manifest: Source {
            path: manifest_path,
            digest: Digest32::of_bytes(&manifest).to_string(),
        },
        weights: Source {
            path: weights_path,
            digest: Digest32::of_bytes(weights).to_string(),
        },
    };
    let operation = directory.join("operation");
    std::fs::create_dir(&operation).unwrap();
    std::fs::set_permissions(&operation, std::fs::Permissions::from_mode(0o700)).unwrap();
    let copied_weights = directory.join("copied-weights");
    create_private(&copied_weights, weights).unwrap();
    let mut wrong_path = model.clone();
    wrong_path.weights.path = copied_weights;
    assert!(
        execute(
            &scorer,
            &wrong_path,
            std::slice::from_ref(&input),
            &operation,
            Instant::now() + Duration::from_secs(2)
        )
        .is_err()
    );
    assert!(!operation.join("intent.json").exists());
    let completed = execute(
        &scorer,
        &model,
        std::slice::from_ref(&input),
        &operation,
        Instant::now() + Duration::from_secs(2),
    )
    .unwrap();
    let files = ["intent.json", "observations.jsonl", "status.json"]
        .map(|name| std::fs::read(operation.join(name)).unwrap());
    // An elapsed deadline forbids spawn, but permits reading the exact already
    // completed operation. This proves recovery does not dispatch the child.
    let recovered = execute(
        &scorer,
        &model,
        std::slice::from_ref(&input),
        &operation,
        Instant::now(),
    )
    .unwrap();
    assert_eq!(completed.rows[0].0, recovered.rows[0].0);
    assert_eq!(
        ["intent.json", "observations.jsonl", "status.json"]
            .map(|name| std::fs::read(operation.join(name)).unwrap()),
        files
    );
    std::fs::write(operation.join("observations.jsonl"), b"torn\n").unwrap();
    assert!(
        execute(
            &scorer,
            &model,
            &[input],
            &operation,
            Instant::now() + Duration::from_secs(2)
        )
        .is_err()
    );
    assert_eq!(
        std::fs::read(operation.join("intent.json")).unwrap(),
        files[0]
    );
    assert_eq!(
        std::fs::read(operation.join("status.json")).unwrap(),
        files[2]
    );
    std::fs::remove_dir_all(directory).unwrap();
}

#[test]
#[ignore = "requires an isolated actual Root-owned numeric fixture namespace"]
fn canonical_private_journal_is_checked_before_any_recovery_write() {
    use std::os::unix::fs::PermissionsExt;
    let directory =
        std::path::PathBuf::from(std::env::var_os("TMPDIR").expect("isolated Root fixture parent"))
            .join(format!(
                "hepta-paired-canonical-file-{}-{}",
                std::process::id(),
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap()
                    .as_nanos()
            ));
    std::fs::create_dir(&directory).unwrap();
    std::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o700)).unwrap();
    let path = directory.join("original-journal");
    create_private(&path, b"original-bytes").unwrap();
    let held = crate::fixed_holdout_custody::open_retained_private_file(&path).unwrap();
    assert_eq!(held.metadata().unwrap().len(), 14);
    let alias = directory.join("alias");
    std::fs::hard_link(&path, &alias).unwrap();
    assert!(crate::fixed_holdout_custody::open_retained_private_file(&path).is_err());
    std::fs::remove_file(&alias).unwrap();
    std::os::unix::fs::symlink(&path, &alias).unwrap();
    assert!(crate::fixed_holdout_custody::open_retained_private_file(&alias).is_err());
    assert_eq!(std::fs::read(&path).unwrap(), b"original-bytes");
    std::fs::remove_dir_all(directory).unwrap();
}
