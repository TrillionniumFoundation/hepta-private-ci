use super::*;

#[test]
fn checkpoints_preserve_all_generation_shapes_and_never_reissue_tokens() -> Result<(), Error> {
    let fixture = Fixture::new()?;
    let mut control = DurableInferenceControl::open(fixture.path(), /*capacity*/ 16)?;
    control.submit(/*now_ms*/ 1, legacy("legacy"))?;
    control.reserve_native(native("native"), /*maximum_in_flight*/ 1)?;
    let mut saved_token = None;
    for shape in 0..6 {
        let request = binding(&format!("shape.{shape}"));
        let (_, mut token) =
            control.admit_generation(/*now_micros*/ 10, request.clone(), PAYLOAD)?;
        match shape {
            0 => saved_token = token,
            1 => {
                control.cancel_generation(&request)?;
            }
            2 => {
                control.dispatch_generation(/*now_micros*/ 11, &mut token)?;
            }
            3 => {
                control.dispatch_generation(/*now_micros*/ 11, &mut token)?;
                control.cancel_generation(&request)?;
            }
            4 => {
                control.dispatch_generation(/*now_micros*/ 11, &mut token)?;
                control.settle_generation(&request, b"actual terminal bytes".to_vec())?;
            }
            5 => {
                control.cancel_generation(&request)?;
                control.abort_generation(&mut token, b"actual pre-effect result".to_vec())?;
            }
            _ => unreachable!(),
        }
    }
    let generation = control.generation.records.clone();
    let legacy = control.records.clone();
    let native = control.native.records.clone();
    let reserved = control.journal_capacity_status().reserved_headroom_bytes;
    let receipt = control.compact_journal()?;
    assert_eq!(receipt.generation_records, generation.len());
    assert_eq!(receipt.reserved_headroom_bytes, reserved);
    assert_eq!(control.generation.records, generation);
    drop(control);
    let mut reopened = DurableInferenceControl::open(fixture.path(), /*capacity*/ 16)?;
    assert_eq!(reopened.generation.records, generation);
    assert_eq!(reopened.records, legacy);
    assert_eq!(reopened.native.records, native);
    assert_eq!(
        reopened.journal_capacity_status().reserved_headroom_bytes,
        reserved
    );
    assert_eq!(
        reopened.dispatch_generation(/*now_micros*/ 11, &mut saved_token),
        Err(Error::Conflict)
    );
    for expected in generation.values() {
        let (actual, token) = reopened.admit_generation(
            /*now_micros*/ 200,
            expected.binding.clone(),
            PAYLOAD,
        )?;
        assert_eq!(&actual, expected);
        assert!(token.is_none());
    }
    Ok(())
}

#[test]
fn checkpoint_generation_corruption_and_whole_identity_truncation_are_rejected() -> Result<(), Error>
{
    let fixture = Fixture::new()?;
    let mut control = DurableInferenceControl::open(fixture.path(), /*capacity*/ 8)?;
    let request = binding("generation");
    let (_, mut token) =
        control.admit_generation(/*now_micros*/ 10, request.clone(), PAYLOAD)?;
    control.dispatch_generation(/*now_micros*/ 11, &mut token)?;
    control.settle_generation(&request, b"actual result".to_vec())?;
    control.compact_journal()?;
    drop(control);
    let original = fs::read_to_string(fixture.path())?;
    let lines: Vec<_> = original.lines().collect();
    assert_eq!(lines.len(), 3);
    let value: serde_json::Value = serde_json::from_str(
        lines[1]
            .strip_prefix(CHECKPOINT_PREFIX)
            .expect("generation checkpoint"),
    )
    .map_err(|_| Error::CorruptJournal("test JSON"))?;
    for field in ["dispatched_at_micros", "aborted_before_dispatch", "result"] {
        let mut changed = value.clone();
        match field {
            "dispatched_at_micros" => changed[field] = serde_json::json!(100),
            "aborted_before_dispatch" => changed[field] = serde_json::json!(true),
            "result" => {
                let first = changed[field]["digest"][0].as_u64().expect("digest byte");
                changed[field]["digest"][0] = serde_json::json!(first ^ 1);
            }
            _ => unreachable!(),
        }
        let damaged = format!("{}\n{CHECKPOINT_PREFIX}{changed}\n{}\n", lines[0], lines[2]);
        fs::write(fixture.path(), &damaged)?;
        assert!(
            DurableInferenceControl::open(fixture.path(), /*capacity*/ 8).is_err(),
            "{field}"
        );
        assert_eq!(fs::read_to_string(fixture.path())?, damaged);
    }
    let truncated = format!("{}\n{}\n", lines[0], lines[2]);
    fs::write(fixture.path(), &truncated)?;
    assert!(DurableInferenceControl::open(fixture.path(), /*capacity*/ 8).is_err());
    assert_eq!(fs::read_to_string(fixture.path())?, truncated);
    fs::write(fixture.path(), original)?;
    assert!(DurableInferenceControl::open(fixture.path(), /*capacity*/ 8).is_ok());
    Ok(())
}
