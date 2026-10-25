//! Additional assertions on the original actual worker/control native case.
use super::*;

pub(super) fn loaded(
    port: &SmolLmNeuralReadPortV1,
    output: &std::path::Path,
    pin: &NeuralCognitivePinV1,
) -> Result<(Digest32, String), Box<dyn Error>> {
    let raw = fs::read(output.join("owned-model-session/session/worker/ready.json"))?;
    let actual: serde_json::Value = serde_json::from_slice(&raw)?;
    Ok(port.with_measurements(|load, forward| {
        let fixed = load
            .fixed_initial_backbone()
            .expect("actual fixed backbone proof");
        assert_eq!(fixed.measured().ready_digest(), Digest32::of_bytes(&raw));
        assert_eq!(load.parameter_file_digest(), pin.payload_digest);
        assert_eq!(load.generation(), pin.generation.get());
        assert_eq!(
            load.adapter_digest().to_string(),
            actual["actual_loaded_parent"].as_str().unwrap()
        );
        assert_eq!(
            load.backbone_digest().to_string(),
            actual["backbone"].as_str().unwrap()
        );
        assert_eq!(
            load.tokenizer_digest().to_string(),
            actual["tokenizer"].as_str().unwrap()
        );
        assert_eq!(
            load.contract_digest().to_string(),
            actual["contract"].as_str().unwrap()
        );
        assert_eq!(load.sources().len(), 6);
        assert!(forward.is_none());
        (
            load.ready_digest(),
            load.control_load_ids().unwrap().0.to_owned(),
        )
    })?)
}

pub(super) fn forwarded(
    port: &SmolLmNeuralReadPortV1,
    observed: &NeuralCognitiveObservationV1,
    ready: Digest32,
    output: &std::path::Path,
) -> Result<String, String> {
    let (request_id, evidence) = port.with_measurements(|load, forward| {
        let forward = forward.expect("actual successfully settled forward measurement");
        assert_eq!(load.ready_digest(), ready);
        assert_eq!(forward.ready_digest(), ready);
        assert_eq!(forward.response_digest(), observed.execution_receipt_digest);
        let (request, reservation) = forward.control_ids();
        assert_eq!(reservation, format!("reservation-{request}"));
        let input = serde_json::to_vec(&serde_json::json!({
            "schema":"hepta-smollm-inference-input-v1", "request_id":request,
            "prompt":observed.request.query,
        }))
        .unwrap();
        assert_eq!(forward.input_digest(), Digest32::of_bytes(&input));
        assert!(!forward.logits_digest().is_zero());
        assert!(
            forward.execution_ns() > 0
                && forward.input_tokens() > 0
                && forward.observed_rss_bytes() > 0
        );
        let evidence = serde_json::json!({
            "schema":"hepta-smollm-settled-measurement-observation-v1",
            "actual_ready_sha256":ready.to_string(), "actual_parameter_file_sha256":load.parameter_file_digest().to_string(),
            "actual_adapter_digest":load.adapter_digest().to_string(), "actual_contract_digest":load.contract_digest().to_string(),
            "actual_backbone_digest":load.backbone_digest().to_string(), "actual_tokenizer_digest":load.tokenizer_digest().to_string(),
            "actual_generation":load.generation(), "query_sha256":observed.request.query_digest.to_string(), "actual_response_sha256":forward.response_digest().to_string(),
            "actual_input_sha256":forward.input_digest().to_string(), "actual_logits_sha256":forward.logits_digest().to_string(),
            "actual_execution_ns":forward.execution_ns(), "actual_input_tokens":forward.input_tokens(), "actual_rss_bytes":forward.observed_rss_bytes(),
            "control_load_ids":load.control_load_ids().unwrap(), "control_forward_ids":forward.control_ids(),
            "authority_posture":"DENY_ALL", "product_artifact_installed":false, "public_reward_eligible":false,
        });
        (request.to_owned(), evidence)
    })?;
    let bytes = serde_json::to_vec_pretty(&evidence).map_err(|error| error.to_string())?;
    fs::write(output.join("actual-neural-measurement-v1.json"), bytes)
        .map_err(|error| error.to_string())?;
    Ok(request_id)
}
