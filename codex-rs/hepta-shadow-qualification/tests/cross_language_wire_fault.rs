//! A real Rust↔Python product-boundary test.
//!
//! The Rust producer emits the HPTA v1 frame consumed by a tiny Python
//! boundary parser.  Python recomputes the payload digest and rejects a
//! one-byte fault.  This exercises the actual wire bytes, rather than merely
//! proving two Rust functions agree with one another.

use codex_hepta_types::{Generation, StableId};
use codex_hepta_wire::{WireEnvelope, WireError};
use serde_json::Value;
use std::process::{Command, Stdio};

const PYTHON_PARSER: &str = r#"
import hashlib, json, struct, sys
raw = bytes.fromhex(sys.stdin.read().strip())
fixed = 54
if len(raw) < fixed:
    raise SystemExit('truncated')
magic, version, schema_len, producer_len, generation, expected, payload_len = struct.unpack('!4sHHHQ32sI', raw[:fixed])
if magic != b'HPTA' or version != 1:
    raise SystemExit('header mismatch')
end = fixed + schema_len + producer_len + payload_len
if len(raw) != end:
    raise SystemExit('length mismatch')
schema = raw[fixed:fixed + schema_len].decode('utf-8')
producer_start = fixed + schema_len
producer = raw[producer_start:producer_start + producer_len].decode('utf-8')
payload = raw[producer_start + producer_len:end]
observed = hashlib.sha256(payload).digest()
if observed != expected:
    raise SystemExit('digest mismatch')
print(json.dumps({'schema': schema, 'producer': producer, 'generation': generation,
                  'payload_hex': payload.hex(), 'payload_sha256': observed.hex()},
                 sort_keys=True))
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
        .write_all(encode_hex(frame).as_bytes())
        .expect("write frame to python");
    child.wait_with_output().expect("python parser result")
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
    assert_eq!(report["schema"], schema.as_str());
    assert_eq!(report["producer"], producer.as_str());
    assert_eq!(report["generation"], generation.get());
    assert_eq!(report["payload_hex"], encode_hex(&payload));
    assert_eq!(
        report["payload_sha256"],
        envelope.payload_digest().to_string()
    );

    // Mutating the payload without changing the signed digest must be rejected
    // by both language boundaries.
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
