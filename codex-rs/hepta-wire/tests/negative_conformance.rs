use std::error::Error;

use codex_hepta_wire::NegotiatedDecodeError;
use codex_hepta_wire::NegotiatedStreamingDecoder;
use codex_hepta_wire::NegotiationError;
use codex_hepta_wire::NegotiationOffer;
use codex_hepta_wire::WireCapabilities;
use codex_hepta_wire::WireEnvelopeV2;
use codex_hepta_wire::WireV2Error;
use codex_hepta_wire::negotiate;
use serde_json::Value;

const VECTORS: &str = include_str!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../docs/lane-a-foundation/platform.wire/NEGATIVE_CONFORMANCE_V1.json"
));

fn decode_hex(value: &str) -> Result<Vec<u8>, Box<dyn Error>> {
    let (pairs, remainder) = value.as_bytes().as_chunks::<2>();
    if !remainder.is_empty() {
        return Err("hex input has odd length".into());
    }
    pairs
        .iter()
        .map(|pair| {
            let pair = std::str::from_utf8(pair)?;
            Ok(u8::from_str_radix(pair, 16)?)
        })
        .collect()
}

fn wire_error_code(error: &WireV2Error) -> &'static str {
    match error {
        WireV2Error::Truncated => "truncated",
        WireV2Error::Magic => "magic",
        WireV2Error::Version(_) => "version",
        WireV2Error::IdentityLength => "identity_length",
        WireV2Error::IdentityEncoding => "identity_encoding",
        WireV2Error::Generation => "generation",
        WireV2Error::PayloadLength => "payload_length",
        WireV2Error::LengthMismatch => "length_mismatch",
        WireV2Error::DigestMismatch { .. } => "digest_mismatch",
    }
}

fn negotiation_error_code(error: &NegotiationError) -> &'static str {
    match error {
        NegotiationError::Truncated => "truncated",
        NegotiationError::Magic => "magic",
        NegotiationError::Format(_) => "format",
        NegotiationError::EmptyVersions => "empty_versions",
        NegotiationError::TooManyVersions(_) => "too_many_versions",
        NegotiationError::InvalidVersion(_) => "invalid_version",
        NegotiationError::Reserved(_) => "reserved",
        NegotiationError::UnknownCapabilities(_) => "unknown_capabilities",
        NegotiationError::IncoherentCapability { .. } => "incoherent_capability",
        NegotiationError::LengthMismatch => "length_mismatch",
        NegotiationError::NonCanonicalVersions => "noncanonical_versions",
        NegotiationError::NoCommonVersion => "no_common_version",
        NegotiationError::MissingRequiredCapabilities { .. } => {
            "missing_required_capabilities"
        }
    }
}

fn required_string<'a>(value: &'a Value, field: &str) -> Result<&'a str, Box<dyn Error>> {
    value
        .get(field)
        .and_then(Value::as_str)
        .ok_or_else(|| format!("missing string field {field}").into())
}

#[test]
fn machine_readable_negative_vectors_fail_with_stable_error_classes()
-> Result<(), Box<dyn Error>> {
    let vectors: Value = serde_json::from_str(VECTORS)?;
    assert_eq!(vectors["schemaVersion"].as_u64(), Some(1));

    let frame_cases = vectors["frameCases"]
        .as_array()
        .ok_or("frameCases must be an array")?;
    assert!(frame_cases.len() >= 10);
    for case in frame_cases {
        let name = required_string(case, "name")?;
        let decoder = required_string(case, "decoder")?;
        let expected = required_string(case, "expectedError")?;
        let frame = decode_hex(required_string(case, "frameHex")?)?;
        match decoder {
            "wire_v2" => {
                let error = WireEnvelopeV2::decode(&frame)
                    .expect_err("negative V2 vector unexpectedly decoded");
                assert_eq!(wire_error_code(&error), expected, "case {name}");
            }
            "negotiated_v2" => {
                let offer = NegotiationOffer::current();
                let negotiated = negotiate(
                    &offer,
                    &offer,
                    WireCapabilities::METADATA_BOUND_DIGEST,
                )?;
                let mut decoder = NegotiatedStreamingDecoder::new(negotiated);
                let batch = decoder.push(&frame);
                assert!(batch.frames().is_empty(), "case {name}");
                assert!(matches!(
                    batch.terminal_error(),
                    Some(NegotiatedDecodeError::VersionMismatch { .. })
                ));
                assert_eq!(expected, "negotiated_version_mismatch", "case {name}");
                assert!(decoder.is_poisoned(), "case {name}");
            }
            other => return Err(format!("unsupported frame decoder {other}").into()),
        }
    }

    let offer_cases = vectors["offerCases"]
        .as_array()
        .ok_or("offerCases must be an array")?;
    assert!(offer_cases.len() >= 8);
    for case in offer_cases {
        let name = required_string(case, "name")?;
        let expected = required_string(case, "expectedError")?;
        let offer = decode_hex(required_string(case, "offerHex")?)?;
        let error = NegotiationOffer::decode(&offer)
            .expect_err("negative HPTN vector unexpectedly decoded");
        assert_eq!(negotiation_error_code(&error), expected, "case {name}");
    }
    Ok(())
}
