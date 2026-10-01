//! Bidirectional Rust↔Python negotiation and HPTA V2 loading over a binary pipe.
//!
//! This launches a second runtime, sends the negotiation hello and frame as raw
//! bytes, performs strict schema admission there, then decodes a Python-produced
//! negotiation offer and frame through the Rust negotiated-session decoder.

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_hepta_wire::DecodedEnvelope;
use codex_hepta_wire::NegotiatedStreamingDecoder;
use codex_hepta_wire::NegotiationOffer;
use codex_hepta_wire::WireCapabilities;
use codex_hepta_wire::WireEnvelopeV2;
use codex_hepta_wire::WireV2Error;
use codex_hepta_wire::negotiate;
use serde::Deserialize;
use serde_json::Value;
use std::error::Error;
use std::io::Write;
use std::process::Command;
use std::process::Stdio;

const PYTHON_SESSION: &str = r#"
import hashlib
import json
import struct
import sys


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SystemExit('duplicate critical field')
        result[key] = value
    return result


def encode_frame(schema, producer, generation, payload):
    prefix = struct.pack('!4sHHHQ', b'HPTA', 2, len(schema), len(producer), generation)
    payload_length = struct.pack('!I', len(payload))
    body = schema + producer + payload
    digest = hashlib.sha256(
        b'HPTA-WIRE-V2\x00' + prefix + payload_length + body
    ).digest()
    return prefix + digest + payload_length + body


raw = sys.stdin.buffer.read()
if len(raw) < 16:
    raise SystemExit('negotiation truncated')

magic, fmt, count, reserved, capabilities = struct.unpack('!4sHBBQ', raw[:16])
if magic != b'HPTN' or fmt != 1 or reserved != 0:
    raise SystemExit('negotiation header mismatch')
if count == 0 or count > 16:
    raise SystemExit('invalid version count')
offer_end = 16 + count * 2
if len(raw) < offer_end + 54:
    raise SystemExit('session truncated')
versions = list(struct.unpack('!' + ('H' * count), raw[16:offer_end]))
if 0 in versions:
    raise SystemExit('invalid version')
if versions != sorted(set(versions)):
    raise SystemExit('noncanonical versions')
unknown_caps = capabilities & ~0x7
if unknown_caps:
    raise SystemExit('unknown capabilities')

required_caps = 0x3  # metadata-bound digest + schema admission
if 2 in versions and capabilities & required_caps == required_caps:
    selected = 2
elif 1 in versions and capabilities & required_caps == required_caps:
    selected = 1
else:
    raise SystemExit('no secure common version')
if selected != 2:
    raise SystemExit('secure session downgraded')

frame = raw[offer_end:]
fixed = 54
magic, version, schema_len, producer_len, generation, expected, payload_len = struct.unpack(
    '!4sHHHQ32sI', frame[:fixed]
)
if magic != b'HPTA' or version != selected:
    raise SystemExit('frame header mismatch')
if not 1 <= schema_len <= 128 or not 1 <= producer_len <= 128:
    raise SystemExit('identity length')
if generation == 0 or not 1 <= payload_len <= 1048576:
    raise SystemExit('frame bounds')
end = fixed + schema_len + producer_len + payload_len
if len(frame) != end:
    raise SystemExit('frame length mismatch')

producer_start = fixed + schema_len
try:
    schema = frame[fixed:producer_start].decode('ascii')
    producer = frame[producer_start:producer_start + producer_len].decode('ascii')
except UnicodeDecodeError:
    raise SystemExit('identity encoding')
allowed_identity = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-:'
if any(character not in allowed_identity for identity in (schema, producer) for character in identity):
    raise SystemExit('identity encoding')
payload = frame[producer_start + producer_len:end]

preimage = (
    b'HPTA-WIRE-V2\x00'
    + frame[:18]
    + frame[50:54]
    + frame[54:]
)
observed = hashlib.sha256(preimage).digest()
if observed != expected:
    raise SystemExit('frame digest mismatch')

if schema != 'hepta.integration.v2':
    raise SystemExit('unknown schema')
message = json.loads(payload, object_pairs_hook=strict_object)
if type(message) is not dict or set(message) != {'objective', 'authority', 'step'}:
    raise SystemExit('unknown or missing critical field')
if type(message['objective']) is not str or type(message['step']) is not int:
    raise SystemExit('typed field mismatch')
if not 0 <= message['step'] <= 18446744073709551615:
    raise SystemExit('step outside u64')
if message['authority'] != 'deny_all':
    raise SystemExit('authority fixture mismatch')

python_offer = struct.pack('!4sHBBQHH', b'HPTN', 1, 2, 0, 0x7, 1, 2)
reply_payload = json.dumps(
    {'accepted_step': message['step'], 'runtime': 'python'},
    sort_keys=True,
    separators=(',', ':'),
).encode('utf-8')
python_frame = encode_frame(
    b'hepta.integration.reply.v2',
    b'python.reference',
    8,
    reply_payload,
)

sys.stdout.buffer.write(python_offer + python_frame)
"#;

// The reference schema has the same closed fields and integer domain in both
// runtimes. A JSON Value alone would silently collapse duplicate object keys.
#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct IntegrationRequest {
    objective: String,
    authority: String,
    step: u64,
}

fn run_python(session: &[u8]) -> Result<std::process::Output, Box<dyn Error>> {
    let mut child = Command::new(std::env::var_os("PYTHON").unwrap_or_else(|| "python3".into()))
        .args(["-c", PYTHON_SESSION])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?;
    let mut stdin = child.stdin.take().ok_or_else(|| {
        std::io::Error::new(std::io::ErrorKind::BrokenPipe, "python stdin unavailable")
    })?;
    stdin.write_all(session)?;
    drop(stdin);
    let output = child.wait_with_output()?;
    Ok(output)
}

fn session(payload: Vec<u8>) -> Result<(NegotiationOffer, WireEnvelopeV2), Box<dyn Error>> {
    Ok((
        NegotiationOffer::current(),
        WireEnvelopeV2::new(
            StableId::new("hepta.integration.v2")?,
            StableId::new("hepta-shadow-qualification")?,
            Generation::new(7)?,
            payload,
        )?,
    ))
}

fn encode_session(offer: &NegotiationOffer, envelope: &WireEnvelopeV2) -> Vec<u8> {
    let mut encoded = offer.encode();
    encoded.extend_from_slice(&envelope.encode());
    encoded
}

fn split_python_reply(bytes: &[u8]) -> Result<(NegotiationOffer, &[u8]), Box<dyn Error>> {
    let header = bytes.get(..16).ok_or("truncated Python HPTN header")?;
    let offer_length = 16 + usize::from(header[6]) * 2;
    let offer = bytes
        .get(..offer_length)
        .ok_or("truncated Python HPTN offer")?;
    Ok((NegotiationOffer::decode(offer)?, &bytes[offer_length..]))
}

#[test]
fn rust_python_bidirectional_session_negotiates_and_loads_typed_payload()
-> Result<(), Box<dyn Error>> {
    let (offer, envelope) =
        session(br#"{"objective":"ndu","authority":"deny_all","step":1}"#.to_vec())?;
    let request: IntegrationRequest = serde_json::from_slice(envelope.payload())?;
    assert_eq!(
        (
            request.objective.as_str(),
            request.authority.as_str(),
            request.step
        ),
        ("ndu", "deny_all", 1)
    );
    let output = run_python(&encode_session(&offer, &envelope))?;
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(output.status.success(), "python session failed: {stderr}");
    // The return direction is raw HPTN + HPTA bytes as well, not a JSON
    // report carrying a byte array that bypasses the peer's framing boundary.
    let (python_offer, python_frame) = split_python_reply(&output.stdout)?;
    let negotiated = negotiate(
        &NegotiationOffer::current(),
        &python_offer,
        WireCapabilities::METADATA_BOUND_DIGEST.union(WireCapabilities::SCHEMA_ADMISSION),
    )?;
    let mut decoder = NegotiatedStreamingDecoder::new(negotiated);
    let (decoded, terminal_error) = decoder.push_batch(python_frame).into_parts();
    assert_eq!(terminal_error, None);
    assert_eq!(decoded.len(), 1);
    let DecodedEnvelope::V2(reply) = &decoded[0] else {
        panic!("Python reply did not use HPTA V2");
    };
    assert_eq!(reply.schema().as_str(), "hepta.integration.reply.v2");
    assert_eq!(reply.producer().as_str(), "python.reference");
    assert_eq!(reply.generation().get(), 8);
    assert_eq!(
        serde_json::from_slice::<Value>(reply.payload())?,
        serde_json::json!({"accepted_step": 1, "runtime": "python"})
    );
    assert_eq!(reply.encode(), python_frame);

    let mut tampered = envelope.encode();
    let schema_last = 54 + "hepta.integration.v2".len() - 1;
    tampered[schema_last] = b'3';
    let mut tampered_session = offer.encode();
    tampered_session.extend_from_slice(&tampered);
    let python_fault = run_python(&tampered_session)?;
    assert!(!python_fault.status.success());
    let fault_stderr = String::from_utf8_lossy(&python_fault.stderr);
    assert!(
        fault_stderr.contains("frame digest mismatch"),
        "{fault_stderr}"
    );
    assert!(matches!(
        WireEnvelopeV2::decode(&tampered),
        Err(WireV2Error::DigestMismatch { .. })
    ));
    Ok(())
}

#[test]
fn python_reference_rejects_bool_integer_and_duplicate_critical_fields()
-> Result<(), Box<dyn Error>> {
    for (payload, expected) in [
        (
            br#"{"objective":"ndu","authority":"deny_all","step":true}"#.to_vec(),
            "typed field mismatch",
        ),
        (
            br#"{"objective":"ndu","authority":"deny_all","step":0,"step":1}"#.to_vec(),
            "duplicate critical field",
        ),
        (
            br#"{"objective":"ndu","authority":"deny_all","step":-1}"#.to_vec(),
            "step outside u64",
        ),
        (
            br#"{"objective":"ndu","authority":"deny_all","step":18446744073709551616}"#.to_vec(),
            "step outside u64",
        ),
        (
            br#"["objective","authority","step"]"#.to_vec(),
            "unknown or missing critical field",
        ),
    ] {
        assert!(serde_json::from_slice::<IntegrationRequest>(&payload).is_err());
        let (offer, envelope) = session(payload)?;
        let output = run_python(&encode_session(&offer, &envelope))?;
        assert!(!output.status.success());
        let stderr = String::from_utf8_lossy(&output.stderr);
        assert!(stderr.contains(expected), "{stderr}");
    }
    Ok(())
}

#[test]
fn rust_python_reject_invalid_hello_version_and_frame_identity() -> Result<(), Box<dyn Error>> {
    let (offer, envelope) =
        session(br#"{"objective":"ndu","authority":"deny_all","step":1}"#.to_vec())?;
    let mut invalid_offer = offer.encode();
    invalid_offer[16..18].copy_from_slice(&0_u16.to_be_bytes());
    assert!(NegotiationOffer::decode(&invalid_offer).is_err());
    invalid_offer.extend_from_slice(&envelope.encode());
    let rejected = run_python(&invalid_offer)?;
    assert!(!rejected.status.success());
    assert!(String::from_utf8_lossy(&rejected.stderr).contains("invalid version"));

    for invalid in [b'/', b' ', 0xff] {
        let mut frame = envelope.encode();
        frame[54 + envelope.schema().as_str().len()] = invalid;
        let digest = codex_hepta_types::Digest32::of_parts(&[
            b"HPTA-WIRE-V2\0",
            &frame[..18],
            &frame[50..54],
            &frame[54..],
        ]);
        frame[18..50].copy_from_slice(digest.as_array());
        assert!(matches!(
            WireEnvelopeV2::decode(&frame),
            Err(WireV2Error::IdentityEncoding)
        ));
        let mut bytes = offer.encode();
        bytes.extend_from_slice(&frame);
        let rejected = run_python(&bytes)?;
        assert!(!rejected.status.success());
        assert!(String::from_utf8_lossy(&rejected.stderr).contains("identity encoding"));
    }
    Ok(())
}

#[test]
fn rust_python_accept_both_u64_schema_boundaries() -> Result<(), Box<dyn Error>> {
    for step in [0_u64, u64::MAX] {
        let payload = serde_json::to_vec(&serde_json::json!({
            "objective": "ndu", "authority": "deny_all", "step": step,
        }))?;
        let request: IntegrationRequest = serde_json::from_slice(&payload)?;
        assert_eq!(request.step, step);
        let (offer, envelope) = session(payload)?;
        let output = run_python(&encode_session(&offer, &envelope))?;
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        let (_offer, frame) = split_python_reply(&output.stdout)?;
        let reply = WireEnvelopeV2::decode(frame)?;
        let reply: Value = serde_json::from_slice(reply.payload())?;
        assert_eq!(reply["accepted_step"].as_u64(), Some(step));
    }
    Ok(())
}
