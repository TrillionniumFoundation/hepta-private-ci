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

schema = frame[fixed:fixed + schema_len].decode('utf-8')
producer_start = fixed + schema_len
producer = frame[producer_start:producer_start + producer_len].decode('utf-8')
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
if set(message) != {'objective', 'authority', 'step'}:
    raise SystemExit('unknown or missing critical field')
if type(message['objective']) is not str or type(message['step']) is not int:
    raise SystemExit('typed field mismatch')
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

print(json.dumps({
    'selected_version': selected,
    'schema': schema,
    'producer': producer,
    'generation': generation,
    'objective': message['objective'],
    'step': message['step'],
    'frame_digest': observed.hex(),
    'python_offer': list(python_offer),
    'python_frame': list(python_frame),
}, sort_keys=True))
"#;

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

fn value_bytes(value: &Value, field: &str) -> Result<Vec<u8>, Box<dyn Error>> {
    value[field]
        .as_array()
        .ok_or_else(|| format!("{field} is not a byte array"))?
        .iter()
        .map(|value| {
            value
                .as_u64()
                .and_then(|value| u8::try_from(value).ok())
                .ok_or_else(|| format!("{field} contains a non-byte value").into())
        })
        .collect()
}

#[test]
fn rust_python_bidirectional_session_negotiates_and_loads_typed_payload()
-> Result<(), Box<dyn Error>> {
    let (offer, envelope) =
        session(br#"{"objective":"ndu","authority":"deny_all","step":1}"#.to_vec())?;
    let output = run_python(&encode_session(&offer, &envelope))?;
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(output.status.success(), "python session failed: {stderr}");
    let report: Value = serde_json::from_slice(&output.stdout)?;
    assert_eq!(report["selected_version"], 2);
    assert_eq!(report["schema"], "hepta.integration.v2");
    assert_eq!(report["producer"], "hepta-shadow-qualification");
    assert_eq!(report["generation"], 7);
    assert_eq!(report["objective"], "ndu");
    assert_eq!(report["step"], 1);
    assert_eq!(report["frame_digest"], envelope.frame_digest().to_string());

    let python_offer = NegotiationOffer::decode(&value_bytes(&report, "python_offer")?)?;
    let negotiated = negotiate(
        &NegotiationOffer::current(),
        &python_offer,
        WireCapabilities::METADATA_BOUND_DIGEST.union(WireCapabilities::SCHEMA_ADMISSION),
    )?;
    let python_frame = value_bytes(&report, "python_frame")?;
    let mut decoder = NegotiatedStreamingDecoder::new(negotiated);
    let decoded = decoder.push(&python_frame)?;
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
    ] {
        let (offer, envelope) = session(payload)?;
        let output = run_python(&encode_session(&offer, &envelope))?;
        assert!(!output.status.success());
        let stderr = String::from_utf8_lossy(&output.stderr);
        assert!(stderr.contains(expected), "{stderr}");
    }
    Ok(())
}
