//! Opt-in execution against operator-provided real SmolLM material. This uses
//! the original owners with a controlled test issuer, and does not qualify,
//! select, install or publish a product artifact.

use std::error::Error;
use std::os::unix::fs::DirBuilderExt;

use serde::Deserialize;

use super::*;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct NativeInput {
    schema: String,
    python: PathBuf,
    chain: PathBuf,
    materials: PathBuf,
    parent: PathBuf,
    parent_sha256: String,
    output: PathBuf,
}

#[test]
#[ignore = "requires HEPTA_PN3_NEURAL_NATIVE_CONFIG with operator-provided pinned model material"]
fn real_smollm_parent_query_original_control_final_use_and_terminal_unload()
-> Result<(), Box<dyn Error>> {
    let input = std::env::var_os("HEPTA_PN3_NEURAL_NATIVE_CONFIG")
        .ok_or("explicit native configuration required")?;
    let input: NativeInput = serde_json::from_slice(&fs::read(input)?)?;
    if input.schema != "hepta-smollm-neural-native-check-v1"
        || [
            &input.python,
            &input.chain,
            &input.materials,
            &input.parent,
            &input.output,
        ]
        .iter()
        .any(|path| !path.is_absolute())
    {
        return Err("native check requires its explicit absolute project paths".into());
    }
    let raw_parent = fs::read(&input.parent)?;
    let parent_sha256: Digest32 = input.parent_sha256.parse()?;
    assert_eq!(Digest32::of_bytes(&raw_parent), parent_sha256);
    let parent: serde_json::Value = serde_json::from_slice(&raw_parent)?;
    let parent_directory = PathBuf::from(parent["directory"].as_str().ok_or("parent directory")?);
    if !parent_directory.is_absolute() {
        return Err("parent directory must be absolute".into());
    }
    let parameter_bytes = fs::read(parent_directory.join("artifact.safetensors"))?;
    let raw_contract = fs::read(parent_directory.join("target-contract.json"))?;
    let contract: serde_json::Value = serde_json::from_slice(&raw_contract)?;
    let wrapped_adapter = fs::read(parent_directory.join("wrapped-adapter.json"))?;
    let mut source_pins = BTreeMap::new();
    for relative in [
        "formal/pon-nakamoto-v1/llm_adapter_contract.py",
        "scripts/llm_inherited_runtime.py",
        "scripts/llm_neural_read_worker.py",
        "scripts/llm_parent_material.py",
        "scripts/llm_runtime_pilot.py",
        "config/pon/model-family-smollm2-135m-v1.json",
    ] {
        let path = input.chain.join(relative);
        source_pins.insert(path.clone(), Digest32::of_bytes(&fs::read(path)?));
    }
    let family = source_pins[&input
        .chain
        .join("config/pon/model-family-smollm2-135m-v1.json")];
    let actions = BTreeMap::from([
        (StableId::new("native-answer-no")?, "no".to_owned()),
        (StableId::new("native-answer-yes")?, "yes".to_owned()),
    ]);
    fs::DirBuilder::new().mode(0o700).create(&input.output)?;
    let config = SmolLmNeuralReadConfigV1 {
        python: input.python,
        script: input.chain.join("scripts/llm_neural_read_worker.py"),
        materials: input.materials,
        run_directory: input.output.join("owned-model-session"),
        source_pins,
        target_contract: raw_contract,
        wrapped_adapter,
        contract_digest: parent["contract"]
            .as_str()
            .ok_or("parent contract")?
            .parse()?,
        adapter_digest: parent["adapter"]
            .as_str()
            .ok_or("parent adapter")?
            .parse()?,
        backbone_digest: contract["backbone"]["index_root"]
            .as_str()
            .ok_or("backbone root")?
            .parse()?,
        tokenizer_digest: contract["tokenizer"]["files_root"]
            .as_str()
            .ok_or("tokenizer root")?
            .parse()?,
        action_completions: actions,
    };
    let pin = NeuralCognitivePinV1 {
        payload_digest: parent["file_sha256"]
            .as_str()
            .ok_or("parameter sha256")?
            .parse()?,
        objective_digest: Digest32::of_bytes(
            b"operator-controlled-native-owner-bridge-not-product-qualification",
        ),
        dataset_digest: Digest32::of_bytes(
            b"no-independent-evaluation-dataset-in-this-execution-check",
        ),
        generation: Generation::new(parent["generation"].as_u64().ok_or("parent generation")?)?,
        family_digest: family,
        execution_profile_digest: config.execution_profile_digest()?,
    };
    assert_eq!(Digest32::of_bytes(&parameter_bytes), pin.payload_digest);
    let runtime = runtime();
    let issuer = Arc::new(TestIssuer::open(
        &input.output.join("controlled-test-authority"),
    ));
    let journal_path = input.output.join("original-inference.control");
    let control = Arc::new(Mutex::new(DurableInferenceControl::open(&journal_path, 8)?));
    let port = SmolLmNeuralReadPortV1::start(
        config,
        pin.clone(),
        parameter_bytes.clone(),
        owner(),
        /*body_generation*/ 1,
        "controlled-neural-worker".to_owned(),
        grant(),
        control.clone(),
        issuer.clone(),
        runtime.handle().clone(),
    )?;
    let query = "Answer with only yes or no. Is 101 greater than 29?".to_owned();
    let request = NeuralCognitiveRequestV1 {
        owner_id: owner(),
        body_generation: 1,
        pin: pin.clone(),
        query_digest: Digest32::of_bytes(query.as_bytes()),
        query,
        action_ids: vec![
            StableId::new("native-answer-no")?,
            StableId::new("native-answer-yes")?,
        ],
    };
    let observed = port.execute(&request, &parameter_bytes)?;
    assert_eq!(observed.request, request);
    assert_eq!(observed.scores_q32.as_ref().map(Vec::len), Some(2));
    assert!(!observed.execution_receipt_digest.is_zero());
    assert_eq!(observed.authority, AuthorityPosture::DENY_ALL);
    assert!(
        port.execute(&request, b"different unadmitted bytes")
            .is_err()
    );
    let before_cross_owner = fs::read(&journal_path)?;
    let claims_before_cross_owner = issuer.bindings.lock().unwrap().len();
    let mut another_owner = request.clone();
    another_owner.owner_id = AgentId::parse("00000000-0000-4000-8000-000000000220")?;
    assert!(port.execute(&another_owner, &parameter_bytes).is_err());
    let mut another_body = request.clone();
    another_body.body_generation += 1;
    assert!(port.execute(&another_body, &parameter_bytes).is_err());
    assert_eq!(fs::read(&journal_path)?, before_cross_owner);
    assert_eq!(
        issuer.bindings.lock().unwrap().len(),
        claims_before_cross_owner
    );
    issuer.denied.store(true, Ordering::SeqCst);
    assert!(
        matches!(port.execute(&request, &parameter_bytes), Err(error) if error.contains("controlled original-authority denial"))
    );
    assert_eq!(issuer.bindings.lock().unwrap().len(), 3);
    port.shutdown()?;
    let journal = fs::read_to_string(&journal_path)?;
    let ids: Vec<_> = journal
        .lines()
        .filter_map(|line| line.strip_prefix("submit|"))
        .map(|line| line.split('|').next().unwrap().to_owned())
        .collect();
    assert_eq!(ids.len(), 3);
    let records: Vec<_> = {
        let control = control.lock().unwrap();
        ids.iter()
            .map(|id| control.get(id).unwrap().clone())
            .collect()
    };
    assert_eq!(
        records
            .iter()
            .map(|record| (record.state, record.consumed_tokens))
            .collect::<Vec<_>>(),
        vec![
            (RequestState::Completed, 0),
            (RequestState::Completed, 1),
            (RequestState::Failed, 0)
        ]
    );
    drop(port);
    drop(control);
    let recovered = DurableInferenceControl::open(&journal_path, 8)?;
    for record in &records {
        assert_eq!(recovered.get(&record.request.request_id), Some(record));
    }
    let evidence = serde_json::json!({
        "schema":"hepta-smollm-neural-native-check-result-v1",
        "parent_file_sha256":parent_sha256.to_string(), "generation":pin.generation.get(),
        "owner_id":request.owner_id.as_str(), "body_generation":request.body_generation,
        "cross_owner_rejected_before_admission":true,
        "cross_body_generation_rejected_before_admission":true,
        "parameters_sha256":pin.payload_digest.to_string(), "execution_profile_sha256":pin.execution_profile_digest.to_string(),
        "query_sha256":request.query_digest.to_string(), "actual_scores_q32":observed.scores_q32,
        "execution_receipt_sha256":observed.execution_receipt_digest.to_string(),
        "original_control_journal_sha256":Digest32::of_bytes(journal.as_bytes()).to_string(),
        "original_control_requests":ids, "original_control_reopen_exact":true,
        "original_final_use_claims":3, "denied_query_executed":false, "terminal_unload_observed":true,
        "controlled_test_issuer":true, "product_artifact_installed":false,
        "ordinary_cognitive_context_qualified":false, "independent_accepted":false,
        "prospective_accepted":false, "public_reward_eligible":false,
    });
    fs::write(
        input.output.join("native-owner-bridge-result.json"),
        serde_json::to_vec_pretty(&evidence)?,
    )?;
    Ok(())
}
