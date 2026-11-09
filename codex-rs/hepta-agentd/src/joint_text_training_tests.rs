//! Wire/readback tests use synthetic bytes and do not admit an owner or train.
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

use super::JointTextTrainingOutputBytesV1;
use super::readback;
use super::wire;
use super::wire::RequestWire;

#[path = "joint_text_training_fixture_tests.rs"]
mod fixture;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

fn request() -> TestResult<RequestWire> {
    Ok(wire::parse_json(fixture::REQUEST.as_bytes())?)
}

struct OutputFixture {
    request: RequestWire,
    request_bytes: Vec<u8>,
    started: Vec<u8>,
    candidate: Vec<u8>,
    observation: Vec<u8>,
    completed: Vec<u8>,
}

impl OutputFixture {
    fn new() -> TestResult<Self> {
        let mut request = request()?;
        request.execution_source_digest = fixture::SOURCES_DIGEST.to_owned();
        let request_bytes = request.encode()?;
        let started = serde_json::to_vec(&json!({
            "schema": "hepta.joint-text-worker.started.v1", "profile": wire::PROFILE,
            "status": "started", "request_sha256": wire::hex(Digest32::of_bytes(&request_bytes)),
        }))?;
        let mut result = Self {
            request,
            request_bytes,
            started,
            candidate: fixture::CANDIDATE.to_vec(),
            observation: fixture::OBSERVATION.as_bytes().to_vec(),
            completed: Vec::new(),
        };
        result.bind_completed()?;
        Ok(result)
    }

    fn bind_completed(&mut self) -> TestResult {
        self.completed = serde_json::to_vec(&json!({
            "schema": "hepta.joint-text-worker.completed.v1", "profile": wire::PROFILE,
            "status": "complete", "request_sha256": wire::hex(Digest32::of_bytes(&self.request_bytes)),
            "observation_sha256": wire::hex(Digest32::of_bytes(&self.observation)),
            "candidate_sha256": wire::hex(Digest32::of_bytes(&self.candidate)),
        }))?;
        Ok(())
    }

    fn change(&mut self, pointer: &str, value: Value) -> TestResult {
        let mut observation: Value = serde_json::from_slice(&self.observation)?;
        *observation.pointer_mut(pointer).ok_or("fixture pointer")? = value;
        self.observation = serde_json::to_vec(&observation)?;
        self.bind_completed()
    }

    fn output(&self) -> JointTextTrainingOutputBytesV1<'_> {
        JointTextTrainingOutputBytesV1 {
            started: &self.started,
            candidate: &self.candidate,
            observation: &self.observation,
            completed: &self.completed,
            failed: None,
        }
    }

    fn validate(&self) -> Result<readback::Observation, super::JointTextTrainingErrorV1> {
        readback::validate(&self.request, &self.request_bytes, &self.output())
    }
}

#[test]
fn wire_matches_independent_python_unicode_vector() -> TestResult {
    let value = request()?;
    let encoded = value.encode()?;
    assert_eq!(encoded, fixture::REQUEST.as_bytes());
    assert_eq!(
        (
            wire::hex(Digest32::of_bytes(&encoded)),
            wire::hex(value.binding_digest()?),
            wire::hex(value.update_rule()?),
            wire::hex(Digest32::of_bytes(wire::PROFILE_BYTES))
        ),
        (
            "c4bee93afbab8fbade4e378932955b25931b037968986950ec66d0d6952b912b".to_owned(),
            "a30a6d7b3d545908095e12ca3552eff1a4f1d2b04812521e9b8225e03ca1987b".to_owned(),
            "51ca950b52f68021304e2a484eae03f4ab6cdfa7385584229bba4900059c1219".to_owned(),
            "3f62d0827e9b16daf024d2454a3f94c2062588e41b9a2d5694e5bb6167823a1a".to_owned()
        ),
    );
    assert_eq!(wire::parse_json::<RequestWire>(&encoded)?, value);
    Ok(())
}

#[test]
fn request_rejects_duplicate_unknown_boolean_overflow_and_nonfinite_values() {
    for raw in [
        fixture::REQUEST.replacen("{", "{\"steps\":2,", /*count*/ 1),
        fixture::REQUEST.replacen("{", "{\"unexpected\":0,", /*count*/ 1),
        fixture::REQUEST.replace("\"steps\":2", "\"steps\":true"),
        fixture::REQUEST.replace(
            "\"source_revision\":1",
            "\"source_revision\":18446744073709551616",
        ),
        fixture::REQUEST.replace("\"steps\":2", "\"steps\":NaN"),
    ] {
        assert!(wire::parse_json::<RequestWire>(raw.as_bytes()).is_err());
    }
}

#[test]
fn request_preserves_full_u64_and_zero_revision_without_normalization() -> TestResult {
    let mut value = request()?;
    value.source_revision = (1_u64 << 63) + 123;
    value.source_policy_revision = 0;
    value.selected_generation = 0;
    assert_eq!(wire::parse_json::<RequestWire>(&value.encode()?)?, value);
    Ok(())
}

#[test]
fn request_rejects_changed_text_rate_profile_and_original_budget_overflow() -> TestResult {
    let original: Value = serde_json::from_str(fixture::REQUEST)?;
    for (key, value) in [
        ("source_content_sha256", json!("1".repeat(/*n*/ 64))),
        ("learning_rate_f64_be", json!("7ff0000000000000")),
        ("learning_rate_f64_be", json!("8000000000000000")),
        ("learning_rate_f64_be", json!("3ff0000000000001")),
        ("continuation", json!("")),
        ("maximum_training_steps", json!(1)),
        ("dataset_observed_rows", json!(11)),
        ("dataset_observed_bytes", json!(4609)),
        ("source_record_count", json!(0)),
        ("maximum_artifact_bytes", json!(1023)),
        ("profile", json!("unadmitted-profile")),
    ] {
        let mut value_json = original.clone();
        value_json[key] = value;
        let value: RequestWire = serde_json::from_value(value_json)?;
        assert!(value.encode().is_err(), "{key}");
    }
    assert!(wire::parse_json::<RequestWire>(&vec![b' '; wire::MAX_JSON_BYTES + 1]).is_err());
    Ok(())
}

#[test]
fn semantic_digest_binds_owner_counts_source_and_optimizer_independently() -> TestResult {
    let original = request()?;
    let expected = original.binding_digest()?;
    let original_json = serde_json::to_value(&original)?;
    for key in [
        "source_record_count",
        "dataset_observed_rows",
        "dataset_observed_bytes",
        "source_revision",
        "source_policy_revision",
        "selected_generation",
        "steps",
    ] {
        let mut changed = original_json.clone();
        changed[key] = json!(changed[key].as_u64().ok_or("u64 fixture")? + 1);
        let value: RequestWire = serde_json::from_value(changed)?;
        assert_ne!(value.binding_digest()?, expected, "{key}");
    }
    let mut changed = original.clone();
    changed.execution_source_digest = wire::hex(Digest32::of_bytes(b"different source"));
    assert_ne!(changed.binding_digest()?, expected);
    assert_ne!(changed.update_rule()?, original.update_rule()?);
    let mut changed = original.clone();
    changed.learning_rate_f64_be = "3f947ae147ae147b".to_owned();
    assert_ne!(changed.update_rule()?, original.update_rule()?);
    // JSON object order/whitespace affects its physical hash, not semantic fields.
    let reordered = serde_json::to_vec_pretty(&original_json)?;
    let decoded: RequestWire = wire::parse_json(&reordered)?;
    assert_ne!(
        Digest32::of_bytes(&reordered),
        Digest32::of_bytes(&original.encode()?)
    );
    assert_eq!(decoded, original);
    assert_eq!(decoded.binding_digest()?, expected);
    Ok(())
}

#[test]
fn unsigned_readback_accepts_increasing_loss_without_claiming_evaluation() -> TestResult {
    let fixture = OutputFixture::new()?;
    let original = fixture.request.clone();
    let observed = fixture.validate()?;
    assert_eq!(
        (
            observed.training.completed_steps,
            observed.training.core_changed_parameters,
            observed.cost.wall_nanoseconds,
            observed.cost.cpu_nanoseconds
        ),
        (2, 1, 1, 0)
    );
    assert_eq!(fixture.request, original);
    Ok(())
}

#[test]
fn output_requires_complete_raw_markers_and_rejects_any_failed_marker() -> TestResult {
    let mut fixture = OutputFixture::new()?;
    let mut output = fixture.output();
    output.failed = Some(b"");
    assert!(readback::validate(&fixture.request, &fixture.request_bytes, &output).is_err());
    fixture.completed.clear();
    assert!(fixture.validate().is_err());
    let mut fixture = OutputFixture::new()?;
    fixture.completed = fixture.started.clone();
    assert!(fixture.validate().is_err());
    let mut fixture = OutputFixture::new()?;
    fixture.observation.push(b' ');
    assert!(fixture.validate().is_err());
    Ok(())
}

#[test]
fn output_rejects_candidate_substitution_and_semantically_equal_request_reencoding() -> TestResult {
    let mut fixture = OutputFixture::new()?;
    fixture.candidate.push(0);
    fixture.bind_completed()?;
    assert!(fixture.validate().is_err());
    let mut fixture = OutputFixture::new()?;
    fixture.request_bytes.push(b' ');
    fixture.bind_completed()?;
    assert!(fixture.validate().is_err());
    Ok(())
}

#[test]
fn readback_rejects_stale_head_dataset_and_changed_owner_counters() -> TestResult {
    for pointer in [
        "/request_binding_digest",
        "/update_rule_digest",
        "/training_profile_digest",
        "/predecessor/sha256",
        "/predecessor/after_sha256",
    ] {
        let mut fixture = OutputFixture::new()?;
        fixture.change(pointer, json!(wire::hex(Digest32::of_bytes(b"stale"))))?;
        assert!(fixture.validate().is_err(), "{pointer}");
    }
    for (pointer, value) in [
        ("/training/source_samples", 7),
        ("/training/source_record_count", 7),
        ("/training/dataset_observed_rows", 3),
        ("/training/dataset_observed_bytes", 12),
        ("/training/continuation_scalars", 4),
        ("/training/completed_steps", 1),
    ] {
        let mut fixture = OutputFixture::new()?;
        fixture.change(pointer, json!(value))?;
        assert!(fixture.validate().is_err(), "{pointer}");
    }
    Ok(())
}

#[test]
fn execution_source_inventory_refuses_duplicates_omissions_and_initializer_reordering() -> TestResult
{
    let mut fixture = OutputFixture::new()?;
    let mut observation: Value = serde_json::from_slice(&fixture.observation)?;
    let sources = observation["execution_sources"]
        .as_array_mut()
        .ok_or("sources")?;
    sources[1] = sources[0].clone();
    fixture.change(
        "/execution_sources",
        observation["execution_sources"].clone(),
    )?;
    assert!(fixture.validate().is_err());
    let mut fixture = OutputFixture::new()?;
    fixture.change("/absent_source_paths", json!([]))?;
    assert!(fixture.validate().is_err());
    let mut fixture = OutputFixture::new()?;
    let mut observation: Value = serde_json::from_slice(&fixture.observation)?;
    observation["absent_source_paths"]
        .as_array_mut()
        .ok_or("absent")?
        .reverse();
    fixture.change(
        "/absent_source_paths",
        observation["absent_source_paths"].clone(),
    )?;
    assert!(fixture.validate().is_err());
    Ok(())
}

#[test]
fn readback_rejects_authority_stage_and_integer_boolean_claims() -> TestResult {
    for (pointer, value) in [
        ("/authority", json!("ALLOW")),
        ("/claims/content_loss_training", json!(1)),
        ("/claims/ndu_training", json!(true)),
        ("/claims/evaluation", json!(true)),
        ("/claims/product_loading", json!(true)),
        ("/claims/selection", json!(true)),
        ("/claims/stage_advanced", json!(true)),
        ("/input_files_unchanged", json!(false)),
        ("/source_files_unchanged", json!(false)),
    ] {
        let mut fixture = OutputFixture::new()?;
        fixture.change(pointer, value)?;
        assert!(fixture.validate().is_err(), "{pointer}");
    }
    Ok(())
}

#[test]
fn unique_scalar_accounting_rejects_step_multiplication_and_absent_core_gradient() -> TestResult {
    for (pointer, value) in [
        (
            "/training/parameter_groups/0/gradient_present_parameters",
            json!(11),
        ),
        (
            "/training/parameter_groups/0/gradient_nonzero_parameters",
            json!(2),
        ),
        ("/training/parameter_groups/0/changed_parameters", json!(2)),
        (
            "/training/parameter_groups/0/max_abs_gradient_f64_be",
            json!("0000000000000000"),
        ),
        (
            "/training/parameter_groups/0/max_abs_delta_f64_be",
            json!("7ff8000000000000"),
        ),
        ("/training/core_gradient_nonzero", json!(false)),
        ("/training/core_changed_parameters", json!(2)),
    ] {
        let mut fixture = OutputFixture::new()?;
        fixture.change(pointer, value)?;
        assert!(fixture.validate().is_err(), "{pointer}");
    }
    Ok(())
}

#[test]
fn numerical_profile_rejects_nonfinite_loss_wrong_runtime_and_unscoped_cost() -> TestResult {
    for (pointer, value) in [
        ("/training/losses_f64_be/0", json!("7ff0000000000000")),
        ("/runtime/threads", json!(2)),
        ("/runtime/dtype", json!("float32")),
        ("/runtime/torch_version", json!("x".repeat(/*n*/ 257))),
        ("/cost/wall_nanoseconds", json!(0)),
        ("/cost/wall_nanoseconds", json!(5_000_000_001_u64)),
        ("/cost/scope", json!("complete training cost")),
        ("/cost/physical_energy_joules", json!(0)),
        ("/cost/full_history_cost", json!({})),
    ] {
        let mut fixture = OutputFixture::new()?;
        fixture.change(pointer, value)?;
        assert!(fixture.validate().is_err(), "{pointer}");
    }
    for field in ["physical_energy_joules", "full_history_cost"] {
        let mut fixture = OutputFixture::new()?;
        let mut observation: Value = serde_json::from_slice(&fixture.observation)?;
        observation["cost"]
            .as_object_mut()
            .ok_or("cost")?
            .remove(field);
        fixture.observation = serde_json::to_vec(&observation)?;
        fixture.bind_completed()?;
        assert!(fixture.validate().is_err(), "missing {field}");
    }
    Ok(())
}

#[test]
fn readback_rejects_unknown_and_duplicate_fields_even_with_rebound_completion() -> TestResult {
    let mut fixture = OutputFixture::new()?;
    let mut observation: Value = serde_json::from_slice(&fixture.observation)?;
    observation["extra"] = json!(0);
    fixture.observation = serde_json::to_vec(&observation)?;
    fixture.bind_completed()?;
    assert!(fixture.validate().is_err());
    let mut fixture = OutputFixture::new()?;
    fixture.observation = String::from_utf8(fixture.observation)?
        .replacen("{", "{\"status\":\"candidate\",", /*count*/ 1)
        .into_bytes();
    fixture.bind_completed()?;
    assert!(fixture.validate().is_err());
    Ok(())
}
