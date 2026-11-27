use crate::cell_test_support::checked;
use crate::*;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;
use serde_json::Value;

pub(crate) fn fixture() -> (HcsnRecoveryContextV2, Vec<u8>, Vec<u8>) {
    let value: Value = checked(serde_json::from_str(include_str!(
        "../tests/fixtures/hcsn-streaming-ridge-v1.json"
    )));
    let parse = |name: &str| checked(value["binding"][name].as_str().ok_or("digest")).parse();
    let binding = HcsnRecoveryBindingV2 {
        request_digest: checked(parse("request_digest")),
        base_checkpoint_digest: checked(parse("base_checkpoint_digest")),
        code_digest: checked(parse("code_digest")),
        dataset_digest: checked(parse("dataset_digest")),
        runtime_digest: checked(parse("runtime_digest")),
        backend_state_schema_digest: checked(parse("backend_state_schema_digest")),
        parameter_mask_digest: checked(parse("parameter_mask_digest")),
        learning_rule_digest: checked(parse("learning_rule_digest")),
    };
    let hex = checked(value["state_hex"].as_str().ok_or("hex"));
    let bytes = (0..hex.len())
        .step_by(2)
        .map(|i| checked(u8::from_str_radix(&hex[i..i + 2], 16)))
        .collect::<Vec<_>>();
    assert_eq!(
        Digest32::of_bytes(&bytes).to_string(),
        value["state_digest"]
    );
    let profile = HcsnTimeProfileV1 {
        maximum_gap_micros: 1_000_000,
        forecast_horizon_micros: 100_000,
        integration: HcsnIntegrationV1::PopulationGrid {
            step_micros: 25_000,
            max_substeps: 40,
        },
    };
    let identity = HcsnClockIdentityV1 {
        clock_epoch: Digest32::of_bytes(b"streaming-unit-clock"),
        scope_digest: crate::cell_test_support::scope("run1").digest(),
        generation: checked(Generation::new(1)),
        writer_epoch: 1,
        model_digest: checked(
            checked(value["parameters_digest"].as_str().ok_or("parameters")).parse(),
        ),
    };
    let clock = checked(HcsnClockCheckpointV1::initial(
        &profile,
        identity,
        checked(value["time_micros"].as_u64().ok_or("clock")),
        Digest32::of_bytes(&bytes),
    ));
    let context = HcsnRecoveryContextV2 {
        profile,
        identity,
        binding,
        checkpoint_digest: clock.digest(),
    };
    (context, checked(clock.encode()), bytes)
}
