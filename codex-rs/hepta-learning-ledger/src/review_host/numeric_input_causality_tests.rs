//! Projection fixtures are not signed evidence or production withdrawals.
use super::*;
use pretty_assertions::assert_eq;

fn line(request: &str, time: u64, model: &str) -> ReviewResult<Vec<u8>> {
    let input = Digest32::of_bytes(
        &vec![1_i64; 512]
            .into_iter()
            .flat_map(i64::to_be_bytes)
            .collect::<Vec<_>>(),
    );
    let pin = Digest32::of_bytes(model.as_bytes()).to_string();
    let mut bytes = serde_json::to_vec(&serde_json::json!({
        "schema":"hepta.cpu-neuron.offline-observation.v1","request_id":request,
        "executed_at_ms":time,"input_line_digest":Digest32::of_bytes(request.as_bytes()).to_string(),
        "input_digest":input.to_string(),"model_manifest_digest":pin,
        "runtime_digest":pin,"weights_digest":pin,"encoder_digest":pin,"head_digest":pin,
        "terminal_observed":true,"succeeded":true,"qualified":false,"authority_grants_any":false,
        "drive_q24":vec![0_i64;10],"prediction_q24":vec![0_i64;10],
        "latency_micros":12,"resident_bytes":1024,"transient_allocation_bytes":128}))?;
    bytes.push(b'\n');
    Ok(bytes)
}

#[test]
fn original_input_cause_is_stable_across_new_request_time_and_candidate_weights() -> ReviewResult<()>
{
    let first = line("first", /*time*/ 100, "original-model")?;
    let second = line("another", /*time*/ 200, "different-model")?;
    let first_support = Digest32::of_bytes(&first);
    let second_support = Digest32::of_bytes(&second);
    assert_ne!(first_support, second_support);
    assert_eq!(
        original_numeric_input_digest_v1(
            &first,
            first_support,
            Digest32::of_bytes(b"original-model")
        )?,
        original_numeric_input_digest_v1(
            &second,
            second_support,
            Digest32::of_bytes(b"different-model")
        )?
    );
    assert!(
        original_numeric_input_digest_v1(
            &second,
            first_support,
            Digest32::of_bytes(b"different-model")
        )
        .is_err()
    );
    assert!(
        original_numeric_input_digest_v1(&first, first_support, Digest32::of_bytes(b"wrong-model"))
            .is_err()
    );
    Ok(())
}

#[test]
fn missing_invalid_or_self_authorizing_numeric_material_cannot_supply_an_input_cause()
-> ReviewResult<()> {
    let bytes = line("original", /*time*/ 100, "model")?;
    for (field, changed) in [
        (
            "input_digest",
            serde_json::json!(Digest32::ZERO.to_string()),
        ),
        ("input_digest", serde_json::json!("wrong-input")),
        ("terminal_observed", serde_json::json!(false)),
        ("succeeded", serde_json::json!(false)),
        ("qualified", serde_json::json!(true)),
        ("authority_grants_any", serde_json::json!(true)),
        ("prediction_q24", serde_json::json!([])),
        ("unknown_feature_assertion", serde_json::json!("fake-input")),
    ] {
        let mut value: serde_json::Value = serde_json::from_slice(&bytes)?;
        value[field] = changed;
        let mut altered = serde_json::to_vec(&value)?;
        altered.push(b'\n');
        assert!(
            original_numeric_input_digest_v1(
                &altered,
                Digest32::of_bytes(&altered),
                Digest32::of_bytes(b"model")
            )
            .is_err()
        );
    }
    assert!(
        original_numeric_input_digest_v1(
            &bytes[..bytes.len() - 1],
            Digest32::of_bytes(&bytes[..bytes.len() - 1]),
            Digest32::of_bytes(b"model")
        )
        .is_err()
    );
    Ok(())
}

#[test]
fn original_g_carrier_and_o_jsonl_join_only_authenticated_exact_supports() -> ReviewResult<()> {
    use super::super::generator_wire::GeneratorBatch;
    use super::super::generator_wire::SignedDecisionRow;
    let first = line("first", /*time*/ 100, "model")?;
    let second = line("second", /*time*/ 101, "model")?;
    let support = Digest32::of_bytes(&first);
    let expected = BTreeMap::from([(support, Digest32::of_bytes(b"model"))]);
    // This carrier has no signature verification role. The expected supports
    // come from the independently authenticated original ledger, not it.
    let batch = GeneratorBatch {
        schema: "hepta.native-generator-decisions.v1".into(),
        contract_digest: String::new(),
        program_digest: String::new(),
        uid: 1000,
        no_new_privileges: true,
        supplementary_groups_empty: true,
        capabilities_zero: true,
        cgroup: String::new(),
        private_custody_denied: 0,
        issued_at_ms: 100,
        rows: vec![SignedDecisionRow {
            index: 0,
            policy: "candidate".into(),
            observation_line: String::from_utf8(first.clone())?,
            payload_digest: String::new(),
            signature_hex: String::new(),
        }],
    };
    let mut archive = serde_json::to_vec(&batch)?;
    archive.push(b'\n');
    assert_eq!(
        original_numeric_input_causes_v1(&archive, &expected)?,
        original_numeric_input_causes_v1(&[first, second.clone()].concat(), &expected)?
    );
    assert!(original_numeric_input_causes_v1(&second, &expected)?.is_empty());
    assert!(original_numeric_input_causes_v1(&archive[..archive.len() - 1], &expected).is_err());
    Ok(())
}
