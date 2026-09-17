//! Live Rust↔Python HPTA V2 product-boundary qualification.
//!
//! Rust emits raw binary HPTA V2 bytes over a real process pipe. Python parses
//! the frame independently, recomputes the full-frame integrity digest, admits
//! the registered schema and loads the typed JSON payload. Metadata and payload
//! faults are rejected on both runtime boundaries.

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_hepta_wire::WireEnvelopeV2;
use codex_hepta_wire::WireV2Error;
use serde_json::Value;
use std::process::Command;
use std::process::Stdio;

const PYTHON_PARSER: &str = r#"
import hashlib, json, struct, sys
raw = sys.stdin.buffer.read()
fixed = 54
if len(raw) < fixed:
    raise SystemExit('truncated')
magic, version, schema_len, producer_len, generation, expected, payload_len = struct.unpack('!4sHHHQ32sI', raw[:fixed])
if magic != b'HPTA' or version != 2:
    raise SystemExit('header mismatch')
if not (1 <= schema_len <= 128 and 1 <= producer_len <= 128 and 1 <= payload_len <= 1048576):
    raise SystemExit('bounds mismatch')
end = fixed + schema_len + producer_len + payload_len
if len(raw) != end:
    raise SystemExit('length mismatch')
schema_bytes = raw[fixed:fixed + schema_len]
producer_start = fixed + schema_len
producer_bytes = raw[producer_start:producer_start + producer_len]
payload = raw[producer_start + producer_len:end]
schema = schema_bytes.decode('utf-8')
producer = producer_bytes.decode('utf-8')
preimage = (b'hepta.hpta.v2.frame\x00' +
            struct.pack('!4sHHHQI', magic, version, schema_len, producer_len, generation, payload_len) +
            schema_bytes + producer_bytes + payload)
observed = hashlib.sha256(preimage).digest()
if observed != expected:
    raise SystemExit('frame digest mismatch')
if schema != 'hepta.integration.v2':
    raise SystemExit('unknown schema')
value = json.loads(payload.decode('utf-8'))
if set(value) != {'objective', 'authority', 'step'}:
    raise SystemExit('schema fields mismatch')
if not isinstance(value['objective'], str) or not isinstance(value['authority'], str):
    raise SystemExit('schema type mismatch')
if type(value['step']) is not int:
    raise SystemExit('schema type mismatch')
print(json.dumps({'schema': schema, 'producer': producer, 'generation': generation,
                  'frame_sha256': hashlib.sha256(raw).hexdigest(), 'value': value},
                 sort_keys=True))
"#;

fn run_python(frame: &[u8]) -> std::process::Output {
    let mut child = Command::new(std::env::var_os("PYTHON").unwrap_or_else(|| "python3".into()))
        .args(["-c", PYTHON_PARSER])
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
        .write_all(frame)
        .expect("write raw HPTA frame to python");
    child.wait_with_output().expect("python parser result")
}

#[test]
fn rust_python_v2_frame_schema_load_and_fault_reject() {
    let schema = StableId::new("hepta.integration.v2").unwrap();
    let producer = StableId::new("hepta-shadow-qualification").unwrap();
    let generation = Generation::new(7).unwrap();
    let payload = br#"{"objective":"ndu","authority":"deny_all","step":1}"#;
    let payload = payload
        .strip_prefix(br#"\""#)
        .and_then(|value| value.strip_suffix(br#"\""#))
        .unwrap_or(payload);
    let payload = payload.to_vec();
    let envelope = WireEnvelopeV2::new(
        schema.clone(),
        producer.clone(),
        generation,
        payload,
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
    assert_eq!(report["schema"], schema.as_str());
    assert_eq!(report["producer"], producer.as_str());
    assert_eq!(report["generation"], generation.get());
    assert_eq!(report["value"]["objective"], "ndu");
    assert_eq!(report["value"]["authority"], "deny_all");
    assert_eq!(report["value"]["step"], 1);

    let mut metadata_tamper = frame.clone();
    metadata_tamper[54] = b'i';
    let python_metadata_fault = run_python(&metadata_tamper);
    assert!(!python_metadata_fault.status.success());
    assert!(
        String::from_utf8_lossy(&python_metadata_fault.stderr)
            .contains("frame digest mismatch")
    );
    assert!(matches!(
        WireEnvelopeV2::decode(&metadata_tamper),
        Err(WireV2Error::DigestMismatch { .. })
    ));

    let mut payload_tamper = frame;
    *payload_tamper.last_mut().expect("non-empty payload") ^= 0x01;
    let python_payload_fault = run_python(&payload_tamper);
    assert!(!python_payload_fault.status.success());
    assert!(
        String::from_utf8_lossy(&python_payload_fault.stderr)
            .contains("frame digest mismatch")
    );
    assert!(matches!(
        WireEnvelopeV2::decode(&payload_tamper),
        Err(WireV2Error::DigestMismatch { .. })
    ));
}
