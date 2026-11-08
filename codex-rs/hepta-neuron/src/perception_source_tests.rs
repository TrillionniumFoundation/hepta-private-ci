use super::*;
use crate::cell_test_support::checked;
use crate::cell_test_support::d;
use pretty_assertions::assert_eq;

fn source<'a>(bytes: &'a [u8], layout: PerceptionSourceLayoutV1) -> PerceptionActorSourceV1<'a> {
    checked(PerceptionActorSourceV1::new(
        PerceptionSourcePinV1 {
            source_id: "capture".to_owned(),
            origin_digest: d("original").into_array(),
            content_digest: Digest32::of_bytes(bytes).into_array(),
            byte_length: bytes.len() as u64,
            observed_at_micros: 7,
            layout,
        },
        bytes,
    ))
}

#[test]
fn perception_original_offsets_preserve_exact_unicode_numbers_and_negation() {
    let bytes = "金额=¥19.99；not_paid；v2.1".as_bytes();
    let source = source(
        bytes,
        PerceptionSourceLayoutV1::Bytes {
            origin_offset: 100,
            origin_length: 500,
        },
    );
    let evidence = checked(source.evidence(
        "invoice",
        PerceptionCoordinatesV1::Bytes {
            start: 100,
            end: 100 + bytes.len() as u64,
        },
    ));
    let decoded: PerceptionEvidenceV1 = checked(serde_json::from_slice(&checked(
        serde_json::to_vec(&evidence),
    )));
    assert_eq!(
        decoded,
        PerceptionEvidenceV1 {
            evidence_id: "invoice".to_owned(),
            source: source.pin().clone(),
            coordinates: PerceptionCoordinatesV1::Bytes {
                start: 100,
                end: 100 + bytes.len() as u64
            },
            raw_bytes: bytes.to_vec(),
        }
    );
    checked(source.matches(&decoded));
    let mut forged = decoded;
    forged.raw_bytes[0] ^= 1;
    assert_eq!(
        source.matches(&forged),
        Err(PerceptionErrorV1::SourceMismatch)
    );
}

#[test]
fn perception_uncaptured_source_bytes_are_unavailable_even_with_valid_original_coordinates() {
    let source = source(
        b"seen",
        PerceptionSourceLayoutV1::Bytes {
            origin_offset: 10,
            origin_length: 100,
        },
    );
    for coordinates in [
        PerceptionCoordinatesV1::Bytes { start: 0, end: 4 },
        PerceptionCoordinatesV1::Bytes { start: 10, end: 15 },
        PerceptionCoordinatesV1::Bytes { start: 12, end: 12 },
        PerceptionCoordinatesV1::Bytes {
            start: u64::MAX,
            end: 1,
        },
    ] {
        assert_eq!(
            source.evidence("unavailable", coordinates),
            Err(PerceptionErrorV1::InvalidCoordinates)
        );
    }
    let mut pin = source.pin().clone();
    pin.layout = PerceptionSourceLayoutV1::Bytes {
        origin_offset: u64::MAX,
        origin_length: u64::MAX,
    };
    assert!(matches!(
        PerceptionActorSourceV1::new(pin, b"seen"),
        Err(PerceptionErrorV1::InvalidSource)
    ));
    let mut pin = source.pin().clone();
    pin.content_digest = d("wrong").into_array();
    assert!(matches!(
        PerceptionActorSourceV1::new(pin, b"seen"),
        Err(PerceptionErrorV1::SourceMismatch)
    ));
}

#[test]
fn perception_image_and_video_regions_use_actual_rows_and_frame_timestamps() {
    let bytes: Vec<u8> = (0..16).collect();
    let image = source(
        &bytes[..8],
        PerceptionSourceLayoutV1::Raster {
            width: 4,
            height: 2,
            channels: 1,
        },
    );
    let evidence = checked(image.evidence(
        "crop",
        PerceptionCoordinatesV1::ImageRegion {
            x: 1,
            y: 0,
            width: 2,
            height: 2,
        },
    ));
    assert_eq!(evidence.raw_bytes, vec![1, 2, 5, 6]);
    let video = source(
        &bytes,
        PerceptionSourceLayoutV1::Frames {
            width: 4,
            height: 2,
            channels: 1,
            frame_count: 2,
            frame_period_micros: 10,
        },
    );
    let evidence = checked(video.evidence(
        "frame",
        PerceptionCoordinatesV1::VideoRegion {
            frame_index: 1,
            timestamp_micros: 10,
            x: 1,
            y: 0,
            width: 2,
            height: 2,
        },
    ));
    assert_eq!(evidence.raw_bytes, vec![9, 10, 13, 14]);
    for coordinates in [
        PerceptionCoordinatesV1::VideoRegion {
            frame_index: 1,
            timestamp_micros: 11,
            x: 1,
            y: 0,
            width: 2,
            height: 2,
        },
        PerceptionCoordinatesV1::VideoRegion {
            frame_index: 2,
            timestamp_micros: 20,
            x: 1,
            y: 0,
            width: 2,
            height: 2,
        },
        PerceptionCoordinatesV1::VideoRegion {
            frame_index: 0,
            timestamp_micros: 0,
            x: u32::MAX,
            y: 0,
            width: 2,
            height: 2,
        },
        PerceptionCoordinatesV1::Bytes { start: 0, end: 4 },
    ] {
        assert_eq!(
            video.evidence("bad", coordinates),
            Err(PerceptionErrorV1::InvalidCoordinates)
        );
    }
}

#[test]
fn perception_evidence_rejects_unknown_source_and_coordinate_fields() {
    let source = source(
        b"seen",
        PerceptionSourceLayoutV1::Bytes {
            origin_offset: 0,
            origin_length: 4,
        },
    );
    let evidence = checked(source.evidence(
        "capture",
        PerceptionCoordinatesV1::Bytes { start: 0, end: 4 },
    ));
    for path in ["source", "coordinates"] {
        let mut value = checked(serde_json::to_value(&evidence));
        value[path]["teacher_truth"] = serde_json::json!(true);
        assert!(serde_json::from_value::<PerceptionEvidenceV1>(value).is_err());
    }
    let mut value = checked(serde_json::to_value(&evidence));
    value["source"]["layout"]["evaluator"] = serde_json::json!(true);
    assert!(serde_json::from_value::<PerceptionEvidenceV1>(value).is_err());
}
