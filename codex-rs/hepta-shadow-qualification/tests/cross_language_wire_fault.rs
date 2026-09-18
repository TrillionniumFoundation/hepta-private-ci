//! Real Rust↔Python HPTA product-boundary tests.
//!
//! V1 remains a payload-digest compatibility oracle. V2 exercises the actual
//! complete-frame integrity bytes in both directions across a live Python
//! process boundary. Neither digest is a signature or an authority token.

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_hepta_wire::WireEnvelope;
use codex_hepta_wire::WireEnvelopeV2;
use codex_hepta_wire::WireError;
use serde_json::Value;
use std::process::Command;
use std::process::Stdio;

const PYTHON_PARSER: &str = r#"
import hashlib, json, struct, sys

DOMAIN = b'HPTA-FRAME-V2\0'

def v2_digest(schema, producer, generation, payload):
    material = (
        DOMAIN
        + b'HPTA'
        + struct.pack('!H', 2)
        + struct.pack('!H', len(schema))
        + struct.pack('!H', len(producer))
        + struct.pack('!Q', generation)
        + struct.pack('!I', len(payload))
        + schema
        + producer
        + payload
    )
    return hashlib.sha256(material).digest()

raw = bytes.fromhex(sys.stdin.read().strip())
fixed = 54
if len(raw) < fixed:
    raise SystemExit('truncated')
magic, version, schema_len, producer_len, generation, expected, payload_len = struct.unpack(
    '!4sHHHQ32sI', raw[:fixed]
)
if magic != b'HPTA' or version not in (1, 2):
    raise SystemExit('header mismatch')
end = fixed + schema_len + producer_len + payload_len
if len(raw) != end:
    raise SystemExit('length mismatch')
schema = raw[fixed:fixed + schema_len]
producer_start = fixed + schema_len
producer = raw[producer_start:producer_start + producer_len]
payload = raw[producer_start + producer_len:end]
if version == 1:
    observed = hashlib.sha256(payload).digest()
    scope = 'payload'
else:
    observed = v2_digest(schema, producer, generation, payload)
    scope = 'complete_frame'
if observed != expected:
    raise SystemExit('digest mismatch')
print(json.dumps({
    'version': version,
    'schema': schema.decode('utf-8'),
    'producer': producer.decode('utf-8'),
    'generation': generation,
    'payload_hex': payload.hex(),
    'digest': observed.hex(),
    'integrity_scope': scope,
}, sort_keys=True))
"#;

const PYTHON_V2_ECHO: &str = r#"
import hashlib, json, struct, sys

DOMAIN = b'HPTA-FRAME-V2\0'

def digest(schema, producer, generation, payload):
    material = (
        DOMAIN
        + b'HPTA'
        + struct.pack('!H', 2)
        + struct.pack('!H', len(schema))
        + struct.pack('!H', len(producer))
        + struct.pack('!Q', generation)
        + struct.pack('!I', len(payload))
        + schema
        + producer
        + payload
    )
    return hashlib.sha256(material).digest()

raw = bytes.fromhex(sys.stdin.read().strip())
fixed = 54
if len(raw) < fixed:
    raise SystemExit('truncated')
magic, version, schema_len, producer_len, generation, expected, payload_len = struct.unpack(
    '!4sHHHQ32sI', raw[:fixed]
)
if magic != b'HPTA' or version != 2:
    raise SystemExit('header mismatch')
end = fixed + schema_len + producer_len + payload_len
if len(raw) != end:
    raise SystemExit('length mismatch')
schema = raw[fixed:fixed + schema_len]
producer_start = fixed + schema_len
producer = raw[producer_start:producer_start + producer_len]
payload = raw[producer_start + producer_len:end]
if digest(schema, producer, generation, payload) != expected:
    raise SystemExit('digest mismatch')

reply_payload = payload + b'|python'
reply_generation = generation + 1
reply_digest = digest(schema, producer, reply_generation, reply_payload)
reply = (
    b'HPTA'
    + struct.pack('!H', 2)
    + struct.pack('!H', len(schema))
    + struct.pack('!H', len(producer))
    + struct.pack('!Q', reply_generation)
    + reply_digest
    + struct.pack('!I', len(reply_payload))
    + schema
    + producer
    + reply_payload
)
print(json.dumps({'frame_hex': reply.hex()}, sort_keys=True))
"#;

fn encode_hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        output.push(HEX[(byte >> 4) as usize] as char);
        output.push(HEX[(byte & 0x0f) as usize] as char);
    }
    output
}

fn decode_hex(value: &str) -> Result<Vec<u8>, String> {
    if value.len() % 2 != 0 {
        return Err("odd hex length".to_owned());
    }
    let mut output = Vec::with_capacity(value.len() / 2);
    let bytes = value.as_bytes();
    for pair in bytes.chunks_exact(2) {
        let high = decode_nibble(pair[0]).ok_or_else(|| "invalid hex".to_owned())?;
        let low = decode_nibble(pair[1]).ok_or_else(|| "invalid hex".to_owned())?;
        output.push((high << 4) | low);
    }
    Ok(output)
}

fn decode_nibble(value: u8) -> Option<u8> {
    match value {
        b'0'..=b'9' => Some(value - b'0'),
        b'a'..=b'f' => Some(value - b'a' + 10),
        _ => None,
    }
}

fn run_python_script(script: &str, frame: &[u8]) -> std::process::Output {
    let mut child = Command::new(std::env::var_os("PYTHON").unwrap_or_else(|| "python3".into()))
        .args(["-c", script])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("python3 is required for the Rust↔Python product boundary test");
    use std::io::Write;
    child
        .stdin
        .take()
        .expect("python stdin")
        .write_all(encode_hex(frame).as_bytes())
        .expect("write frame to python");
    child.wait_with_output().expect("python parser result")
}

fn run_python(frame: &[u8]) -> std::process::Output {
    run_python_script(PYTHON_PARSER, frame)
}

#[test]
fn rust_python_wire_roundtrip_and_payload_fault_reject() {
    let schema = StableId::new("hepta.integration.v1").unwrap();
    let producer = StableId::new("hepta-shadow-qualification").unwrap();
    let generation = Generation::new(7).unwrap();
    let payload = br#"{"objective":"ndu","authority":"deny_all","step":1}"#.to_vec();
    let envelope = WireEnvelope::new(
        schema.clone(),
        producer.clone(),
        generation,
        payload.clone(),
    )
    .expect("valid product envelope");
    let frame = envelope.encode();

    let output = run_python(&frame);
    assert!(
        output.status.success(),
        "python parser failed: {:?}",
        output
    );
    let report: Value = serde_json::from_slice(&output.stdout).expect("python JSON receipt");
    assert_eq!(report["version"], 1);
    assert_eq!(report["schema"], schema.as_str());
    assert_eq!(report["producer"], producer.as_str());
    assert_eq!(report["generation"], generation.get());
    assert_eq!(report["payload_hex"], encode_hex(&payload));
    assert_eq!(report["integrity_scope"], "payload");
    assert_eq!(report["digest"], envelope.payload_digest().to_string());

    // Mutating the payload without changing the V1 payload digest must be
    // rejected by both language boundaries.
    let mut tampered = frame.clone();
    *tampered.last_mut().expect("non-empty payload") ^= 0x01;
    let python_fault = run_python(&tampered);
    assert!(!python_fault.status.success());
    assert!(String::from_utf8_lossy(&python_fault.stderr).contains("digest mismatch"));
    assert!(matches!(
        WireEnvelope::decode(&tampered),
        Err(WireError::DigestMismatch { .. })
    ));
}

#[test]
fn rust_python_v2_bidirectional_process_boundary_and_metadata_fault_reject() {
    let schema = StableId::new("hepta.integration.v2").unwrap();
    let producer = StableId::new("hepta-shadow-qualification").unwrap();
    let generation = Generation::new(7).unwrap();
    let payload = br#"{"objective":"ndu","authority":"deny_all","step":2}"#.to_vec();
    let envelope = WireEnvelopeV2::new(
        schema.clone(),
        producer.clone(),
        generation,
        payload.clone(),
    )
    .expect("valid V2 envelope");
    let frame = envelope.encode();

    let parsed = run_python(&frame);
    assert!(
        parsed.status.success(),
        "python V2 parser failed: {:?}",
        parsed
    );
    let report: Value = serde_json::from_slice(&parsed.stdout).expect("python V2 JSON receipt");
    assert_eq!(report["version"], 2);
    assert_eq!(report["schema"], schema.as_str());
    assert_eq!(report["producer"], producer.as_str());
    assert_eq!(report["generation"], generation.get());
    assert_eq!(report["integrity_scope"], "complete_frame");
    assert_eq!(report["digest"], envelope.frame_digest().to_string());

    let echoed = run_python_script(PYTHON_V2_ECHO, &frame);
    assert!(
        echoed.status.success(),
        "python V2 echo failed: {:?}",
        echoed
    );
    let echo_report: Value =
        serde_json::from_slice(&echoed.stdout).expect("python V2 echo receipt");
    let reply_hex = echo_report["frame_hex"]
        .as_str()
        .expect("python V2 echo frame hex");
    let reply = decode_hex(reply_hex).expect("valid python V2 frame hex");
    let decoded = WireEnvelopeV2::decode(&reply).expect("Rust accepts Python V2 reply");
    assert_eq!(decoded.schema(), &schema);
    assert_eq!(decoded.producer(), &producer);
    assert_eq!(decoded.generation().get(), generation.get() + 1);
    let mut expected_payload = payload;
    expected_payload.extend_from_slice(b"|python");
    assert_eq!(decoded.payload(), expected_payload.as_slice());

    let mut metadata_tampered = frame;
    metadata_tampered[54] ^= 0x01;
    let python_fault = run_python(&metadata_tampered);
    assert!(!python_fault.status.success());
    assert!(String::from_utf8_lossy(&python_fault.stderr).contains("digest mismatch"));
    assert!(matches!(
        WireEnvelopeV2::decode(&metadata_tampered),
        Err(WireError::FrameDigestMismatch { .. })
    ));
}
