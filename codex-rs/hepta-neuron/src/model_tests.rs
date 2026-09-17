use super::*;
use pretty_assertions::assert_eq;

fn must<T, E: fmt::Debug>(value: Result<T, E>) -> T {
    match value {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn manifest() -> FrozenModelManifestV1 {
    FrozenModelManifestV1 {
        model_id: id("neuron:model:1"),
        encoder_digest: digest(b"encoder"),
        head_digest: digest(b"head"),
        weights_digest: digest(b"weights"),
        tokenizer_digest: digest(b"tokenizer"),
        preprocessor_digest: digest(b"preprocessor"),
        quantization_digest: digest(b"quantization"),
        license_sbom_digest: digest(b"license-sbom"),
        runtime_digest: digest(b"runtime"),
        device_digest: digest(b"device"),
        input_width: 3,
        output_width: 5,
    }
}

fn request() -> FrozenHeadRequestV1 {
    FrozenHeadRequestV1 {
        request_id: id("request:1"),
        approved_input_digest: digest(b"approved-input"),
        approved_features_q24: vec![Q, Q / 2, -Q / 2],
    }
}

#[derive(Clone, Copy)]
enum ReceiptMutation {
    None,
    Output,
    NonTerminal,
    Authority,
}

struct FixtureHead {
    mutation: ReceiptMutation,
}

impl FrozenSignalHead for FixtureHead {
    fn execute(
        &mut self,
        manifest: &FrozenModelManifestV1,
        request: &FrozenHeadRequestV1,
    ) -> Result<(FrozenHeadOutputV1, LocalModelRuntimeReceiptV1), ModelError> {
        let output = FrozenHeadOutputV1 {
            drive_q24: vec![Q, Q / 2, 0, -Q / 2, -Q],
            prediction_q24: vec![Q / 2, Q / 2, 0, 0, -Q / 2],
            ood_score_q24: Q / 8,
        };
        let mut receipt = LocalModelRuntimeReceiptV1 {
            request_id: request.request_id.clone(),
            manifest_digest: manifest.digest()?,
            input_digest: request.digest(manifest)?,
            output_digest: output.digest(manifest)?,
            runtime_digest: manifest.runtime_digest,
            device_digest: manifest.device_digest,
            execution_micros: 77,
            observed_memory_bytes: 4096,
            terminal_observed: true,
            succeeded: true,
            authority: AuthorityPosture::DENY_ALL,
        };
        match self.mutation {
            ReceiptMutation::None => {}
            ReceiptMutation::Output => receipt.output_digest = digest(b"substituted-output"),
            ReceiptMutation::NonTerminal => receipt.terminal_observed = false,
            ReceiptMutation::Authority => receipt.authority.runtime = true,
        }
        Ok((output, receipt))
    }
}

#[test]
fn verified_executor_binds_exact_model_and_numerical_output() {
    let manifest = manifest();
    let request = request();
    let mut executor = FixtureHead {
        mutation: ReceiptMutation::None,
    };
    let first = must(execute_verified_head(&mut executor, &manifest, &request));
    let mut executor = FixtureHead {
        mutation: ReceiptMutation::None,
    };
    let second = must(execute_verified_head(&mut executor, &manifest, &request));
    assert_eq!(first, second);
    assert_eq!(first.0.ood_score_q24, Q / 8);
    assert_eq!(first.1.authority, AuthorityPosture::DENY_ALL);
}

#[test]
fn exact_artifact_metadata_is_part_of_the_manifest_digest() {
    let original = manifest();
    let original_digest = must(original.digest());
    for field in ["weights", "tokenizer", "preprocessor", "quantization", "runtime", "device"] {
        let mut changed = original.clone();
        let replacement = digest(format!("changed-{field}").as_bytes());
        match field {
            "weights" => changed.weights_digest = replacement,
            "tokenizer" => changed.tokenizer_digest = replacement,
            "preprocessor" => changed.preprocessor_digest = replacement,
            "quantization" => changed.quantization_digest = replacement,
            "runtime" => changed.runtime_digest = replacement,
            "device" => changed.device_digest = replacement,
            _ => unreachable!(),
        }
        assert_ne!(must(changed.digest()), original_digest);
    }
}

#[test]
fn substituted_or_unfinished_execution_receipts_fail_closed() {
    for (mutation, expected) in [
        (
            ReceiptMutation::Output,
            ModelError::ReceiptMismatch("output"),
        ),
        (ReceiptMutation::NonTerminal, ModelError::RuntimeNotTerminal),
        (ReceiptMutation::Authority, ModelError::AuthorityGranted),
    ] {
        let mut executor = FixtureHead { mutation };
        assert_eq!(
            execute_verified_head(&mut executor, &manifest(), &request()),
            Err(expected)
        );
    }
}

#[test]
fn malformed_dimensions_and_unbounded_values_are_rejected_before_use() {
    let mut bad_manifest = manifest();
    bad_manifest.output_width = 4;
    assert_eq!(bad_manifest.digest(), Err(ModelError::InvalidManifest));

    let mut bad_request = request();
    bad_request.approved_features_q24[0] = H + 1;
    assert_eq!(
        bad_request.digest(&manifest()),
        Err(ModelError::InvalidRequest)
    );

    let mut bad_output = FrozenHeadOutputV1 {
        drive_q24: vec![0; 5],
        prediction_q24: vec![0; 5],
        ood_score_q24: 0,
    };
    bad_output.ood_score_q24 = Q + 1;
    assert_eq!(
        bad_output.digest(&manifest()),
        Err(ModelError::InvalidOutput)
    );
}
