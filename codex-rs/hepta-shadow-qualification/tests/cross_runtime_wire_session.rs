//! Live Rust↔Python negotiation and HPTA V2 loading over a binary pipe.
//!
//! Unlike the frozen-vector test, this launches a second runtime, sends the
//! negotiation hello and frame as raw bytes, performs schema admission there,
//! and verifies that metadata tampering fails at both language boundaries.

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_hepta_wire::NegotiationOffer;
use codex_hepta_wire::WireEnvelopeV2;
use codex_hepta_wire::WireV2Error;
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
if magic != b'HPTA' or version != 2:
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
message = json.loads(payload)
if set(message) != {'objective', 'authority', 'step'}:
    raise SystemExit('unknown or missing critical field')
if not isinstance(message['objective'], str) or not isinstance(message['step'], int):
    raise SystemExit('typed field mismatch')
if message['authority'] != 'deny_all':
    raise SystemExit('authority fixture mismatch')

print(json.dumps({
    'selected_version': selected,
    'schema': schema,
    'producer': producer,
    'generation': generation,
    'objective': message['objective'],
    'step': message['step'],
    'frame_digest': observed.hex(),
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
    Ok(child.wait_with_output()?)
}

#[test]
fn rust_python_live_v2_session_negotiates_and_loads_typed_payload() -> Result<(), Box<dyn Error>> {
    let offer = NegotiationOffer::current().encode();
    let payload = br#"{"objective":"ndu","authority":"deny_all","step":1}"#.to_vec();
    let envelope = WireEnvelopeV2::new(
        StableId::new("hepta.integration.v2")?,
        StableId::new("hepta-shadow-qualification")?,
        Generation::new(7)?,
        payload,
    )?;

    let mut session = offer.clone();
    session.extend_from_slice(&envelope.encode());
    let output = run_python(&session)?;
    assert!(
        output.status.success(),
        "python session failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    let report: Value = serde_json::from_slice(&output.stdout)?;
    assert_eq!(report["selected_version"], 2);
    assert_eq!(report["schema"], "hepta.integration.v2");
    assert_eq!(report["producer"], "hepta-shadow-qualification");
    assert_eq!(report["generation"], 7);
    assert_eq!(report["objective"], "ndu");
    assert_eq!(report["step"], 1);
    assert_eq!(report["frame_digest"], envelope.frame_digest().to_string());

    let mut tampered = envelope.encode();
    let schema_last = 54 + "hepta.integration.v2".len() - 1;
    tampered[schema_last] = b'3';
    let mut tampered_session = offer;
    tampered_session.extend_from_slice(&tampered);
    let python_fault = run_python(&tampered_session)?;
    assert!(!python_fault.status.success());
    assert!(
        String::from_utf8_lossy(&python_fault.stderr).contains("frame digest mismatch"),
        "{}",
        String::from_utf8_lossy(&python_fault.stderr)
    );
    assert!(matches!(
        WireEnvelopeV2::decode(&tampered),
        Err(WireV2Error::DigestMismatch { .. })
    ));
    Ok(())
}
