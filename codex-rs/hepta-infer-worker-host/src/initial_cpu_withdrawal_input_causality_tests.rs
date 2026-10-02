//! Exact support/material joins, not scientific measurements or live authority.
use super::*;
use pretty_assertions::assert_eq;

fn line(request: &str, time: u64, input: i64) -> HostResult<Vec<u8>> {
    let input = Digest32::of_bytes(
        &vec![input; 512]
            .into_iter()
            .flat_map(i64::to_be_bytes)
            .collect::<Vec<_>>(),
    );
    let pin = Digest32::of_bytes(b"actual-model").to_string();
    let mut bytes = serde_json::to_vec(&serde_json::json!({
        "schema":"hepta.cpu-neuron.offline-observation.v1","request_id":request,
        "executed_at_ms":time,"input_line_digest":Digest32::of_bytes(request.as_bytes()).to_string(),
        "input_digest":input.to_string(),"model_manifest_digest":pin,"runtime_digest":pin,
        "weights_digest":pin,"encoder_digest":pin,"head_digest":pin,"terminal_observed":true,
        "succeeded":true,"qualified":false,"authority_grants_any":false,"drive_q24":vec![0_i64;10],
        "prediction_q24":vec![0_i64;10],"latency_micros":1,"resident_bytes":1024,"transient_allocation_bytes":128}))?;
    bytes.push(b'\n');
    Ok(bytes)
}

#[test]
fn renamed_numeric_runs_share_one_input_but_genuine_distinct_inputs_remain_two() -> HostResult<()> {
    let first = line("first", /*time*/ 100, /*input*/ 1)?;
    let renamed = line("renamed", /*time*/ 200, /*input*/ 1)?;
    let other = line("independent", /*time*/ 300, /*input*/ 2)?;
    let supports = BTreeMap::from([
        (
            Digest32::of_bytes(&first),
            Digest32::of_bytes(b"actual-model"),
        ),
        (
            Digest32::of_bytes(&renamed),
            Digest32::of_bytes(b"actual-model"),
        ),
    ]);
    let shared = original_inputs(
        [first.as_slice(), renamed.as_slice()].into_iter(),
        &supports,
    )?;
    assert_eq!(shared.len(), 1);
    let independent = BTreeMap::from([
        (
            Digest32::of_bytes(&first),
            Digest32::of_bytes(b"actual-model"),
        ),
        (
            Digest32::of_bytes(&other),
            Digest32::of_bytes(b"actual-model"),
        ),
    ]);
    assert_eq!(
        original_inputs(
            [first.as_slice(), other.as_slice()].into_iter(),
            &independent
        )?
        .len(),
        2
    );
    Ok(())
}

#[test]
fn missing_original_line_model_mismatch_or_support_substitution_is_closed() -> HostResult<()> {
    let first = line("first", /*time*/ 100, /*input*/ 1)?;
    let other = line("other", /*time*/ 200, /*input*/ 2)?;
    let expected = BTreeMap::from([(
        Digest32::of_bytes(&first),
        Digest32::of_bytes(b"actual-model"),
    )]);
    assert!(original_inputs([other.as_slice()].into_iter(), &expected).is_err());
    assert!(original_inputs([].into_iter(), &expected).is_err());
    assert!(original_inputs([first.as_slice()].into_iter(), &BTreeMap::new()).is_err());
    let wrong_model = BTreeMap::from([(
        Digest32::of_bytes(&first),
        Digest32::of_bytes(b"another-model"),
    )]);
    assert!(original_inputs([first.as_slice()].into_iter(), &wrong_model).is_err());
    let replaced_hash = BTreeMap::from([(
        Digest32::of_bytes(b"forged-support"),
        Digest32::of_bytes(b"actual-model"),
    )]);
    assert!(original_inputs([first.as_slice()].into_iter(), &replaced_hash).is_err());
    Ok(())
}
