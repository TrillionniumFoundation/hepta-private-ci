//! A real Rust↔Python product-boundary test.
//!
//! The Rust producer emits the HPTA v1 frame consumed by a tiny Python
//! boundary parser.  Python recomputes the payload digest and rejects a
//! one-byte fault.  This exercises the actual wire bytes, rather than merely
//! proving two Rust functions agree with one another.

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_hepta_wire::WireEnvelope;
use codex_hepta_wire::WireError;
use serde_json::Value;
use std::process::Command;
use std::process::Stdio;

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

fn run_python(frame: &[u8]) -> std::io::Result<std::process::Output> {
    let mut child = Command::new(std::env::var_os("PYTHON").unwrap_or_else(|| "python3".into()))
        .args(["-c", PYTHON_PARSER])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?;
    use std::io::Write;
    let Some(mut stdin) = child.stdin.take() else {
        return Err(std::io::Error::other("python stdin is unavailable"));
    };
    stdin.write_all(encode_hex(frame).as_bytes())?;
    drop(stdin);
    child.wait_with_output()
}

#[test]
fn rust_python_wire_roundtrip_and_payload_fault_reject() {
    let Ok(schema) = StableId::new("hepta.integration.v1") else {
        panic!("test schema identifier must be valid");
    };
    let Ok(producer) = StableId::new("hepta-shadow-qualification") else {
        panic!("test producer identifier must be valid");
    };
    let Ok(generation) = Generation::new(7) else {
        panic!("test generation must be valid");
    };
    let payload = br#"{"objective":"ndu","authority":"deny_all","step":1}"#.to_vec();
    let Ok(envelope) = WireEnvelope::new(
        schema.clone(),
        producer.clone(),
        generation,
        payload.clone(),
    ) else {
        panic!("test product envelope must be valid");
    };
    let frame = envelope.encode();

    let Ok(output) = run_python(&frame) else {
        panic!("python3 is required for the Rust↔Python product boundary test");
    };
    assert!(
        output.status.success(),
        "python parser failed: {output:?}"
    );
    let Ok(report): Result<Value, _> = serde_json::from_slice(&output.stdout) else {
        panic!("python JSON receipt must parse");
    };
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
    let mut tampered = frame;
    let Some(last) = tampered.last_mut() else {
        panic!("encoded frame must contain a payload");
    };
    *last ^= 0x01;
    let Ok(python_fault) = run_python(&tampered) else {
        panic!("python parser process must execute");
    };
    assert!(!python_fault.status.success());
    assert!(String::from_utf8_lossy(&python_fault.stderr).contains("digest mismatch"));
    assert!(matches!(
        WireEnvelope::decode(&tampered),
        Err(WireError::DigestMismatch { .. })
    ));
}
