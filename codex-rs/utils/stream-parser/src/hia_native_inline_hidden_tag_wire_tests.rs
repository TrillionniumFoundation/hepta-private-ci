use super::Decision;
use super::Frame;
use super::InlineTagSpec;
use super::decode_close;
use super::decode_open;
use pretty_assertions::assert_eq;

#[test]
fn opener_decoder_rejects_late_invalid_fields_before_host_effects() {
    let specs = [InlineTagSpec {
        tag: 1,
        open: "é",
        close: "!",
    }];
    let valid: Frame = [1, 2, 1, 1, 2, 0, 0, 2, 1, 3, 0, 0];
    assert_eq!(
        decode_open(valid, "xéz", &specs),
        Ok(Decision::Open {
            take: 1,
            consume: 3,
            spec_index: 0
        })
    );
    for (field, value) in [
        (0, 0),
        (1, 3),
        (2, 0),
        (3, 2),
        (4, 1),
        (5, 1),
        (6, 5),
        (7, 4),
        (8, 2),
        (9, 2),
        (10, 1),
        (11, 1),
    ] {
        let mut frame = valid;
        frame[field] = value;
        assert!(decode_open(frame, "xéz", &specs).is_err(), "field {field}");
    }
    let invalid = [1, 2, 1, u64::MAX, 0, 0, 2, 1, 2, 2, 0, 0];
    assert!(decode_open(invalid, "xéz", &specs).is_err());
}

#[test]
fn close_decoder_checks_geometry_and_whole_state_before_host_effects() {
    let valid: Frame = [1, 3, 0, 0, 0, 0, 0, 4, 1, 3, 0, 0];
    assert_eq!(
        decode_close(valid, "xéz", "é"),
        Ok(Decision::Close {
            take: 1,
            consume: 3
        })
    );
    for (field, value) in [
        (0, 0),
        (1, 2),
        (2, 1),
        (3, 1),
        (4, 1),
        (5, 1),
        (6, 1),
        (7, 2),
        (8, 2),
        (9, 2),
        (10, 1),
        (11, 1),
    ] {
        let mut frame = valid;
        frame[field] = value;
        assert!(decode_close(frame, "xéz", "é").is_err(), "field {field}");
    }
    let valid_body = [1, 3, 0, 0, 0, 0, 1, 3, 3, 3, 0, 0];
    assert_eq!(
        decode_close(valid_body, "xéz", "zy"),
        Ok(Decision::Body { take: 3 })
    );
}
