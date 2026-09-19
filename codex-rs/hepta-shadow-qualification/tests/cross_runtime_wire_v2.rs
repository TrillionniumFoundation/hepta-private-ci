//! Live Rust↔Python HPTA V2 transport qualification.
//!
//! A separate Python runtime connects over TCP, reads the bounded HPTA header,
//! verifies payload + complete-frame digests, performs strict schema admission,
//! and returns a typed receipt. This is deliberately stronger than comparing
//! two encoders in one process.

use std::error::Error;
use std::io::Read;
use std::io::Write;
use std::net::Shutdown;
use std::net::TcpListener;
use std::process::Command;
use std::process::Stdio;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_hepta_wire::HPTA_V2_HEADER_BYTES;
use codex_hepta_wire::WireEnvelopeV2;
use codex_hepta_wire::WireV2Error;
use serde_json::Value;

const PYTHON_TCP_CONSUMER: &str = r#"
import hashlib, json, socket, struct, sys

def recv_exact(sock, size):
    out = bytearray()
    while len(out) < size:
        chunk = sock.recv(size - len(out))
        if not chunk:
            raise SystemExit('truncated')
        out.extend(chunk)
    return bytes(out)

port = int(sys.argv[1])
sock = socket.create_connection(('127.0.0.1', port), timeout=5)
header = recv_exact(sock, 86)
magic, version, schema_len, producer_len, generation = struct.unpack('!4sHHHQ', header[:18])
if magic != b'HPTA' or version != 2:
    raise SystemExit('header mismatch')
payload_digest = header[18:50]
frame_digest = header[50:82]
payload_len = struct.unpack('!I', header[82:86])[0]
if schema_len < 1 or schema_len > 128 or producer_len < 1 or producer_len > 128:
    raise SystemExit('identity bounds')
if payload_len < 1 or payload_len > 1048576:
    raise SystemExit('payload bounds')
body = recv_exact(sock, schema_len + producer_len + payload_len)
schema = body[:schema_len].decode('utf-8')
producer = body[schema_len:schema_len + producer_len].decode('utf-8')
payload = body[schema_len + producer_len:]
observed_payload = hashlib.sha256(payload).digest()
if observed_payload != payload_digest:
    raise SystemExit('payload digest mismatch')
material = b'HPTA-FRAME-V2\x00' + header[:18] + payload_digest + header[82:86] + body
observed_frame = hashlib.sha256(material).digest()
if observed_frame != frame_digest:
    raise SystemExit('frame digest mismatch')
if schema != 'hepta.integration-live.v2':
    raise SystemExit('unknown schema')
value = json.loads(payload)
required = {'objective', 'authority', 'step'}
if set(value.keys()) != required:
    raise SystemExit('schema admission mismatch')
if not isinstance(value['objective'], str) or not isinstance(value['authority'], str) or not isinstance(value['step'], int):
    raise SystemExit('typed payload mismatch')
receipt = json.dumps({
    'schema': schema,
    'producer': producer,
    'generation': generation,
    'frame_sha256': hashlib.sha256(header + body).hexdigest(),
    'objective': value['objective'],
}, sort_keys=True).encode() + b'\n'
sock.sendall(receipt)
sock.shutdown(socket.SHUT_WR)
sock.close()
"#;

fn id(value: &str) -> Result<StableId, Box<dyn Error>> {
    Ok(StableId::new(value)?)
}

fn run_python_tcp(
    frame: &[u8],
) -> Result<(std::process::ExitStatus, String, String), Box<dyn Error>> {
    let listener = TcpListener::bind(("127.0.0.1", 0))?;
    let port = listener.local_addr()?.port();
    let child = Command::new(std::env::var_os("PYTHON").unwrap_or_else(|| "python3".into()))
        .args(["-c", PYTHON_TCP_CONSUMER, &port.to_string()])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?;
    let (mut stream, _) = listener.accept()?;
    stream.write_all(frame)?;
    stream.shutdown(Shutdown::Write)?;
    let mut receipt = String::new();
    stream.read_to_string(&mut receipt)?;
    let output = child.wait_with_output()?;
    Ok((
        output.status,
        receipt,
        String::from_utf8_lossy(&output.stderr).into_owned(),
    ))
}

#[test]
fn live_tcp_runtime_loads_v2_and_rejects_metadata_and_schema_faults() -> Result<(), Box<dyn Error>>
{
    let envelope = WireEnvelopeV2::new(
        id("hepta.integration-live.v2")?,
        id("hepta-shadow-qualification")?,
        Generation::new(7)?,
        br#"{"authority":"deny_all","objective":"ndu","step":1}"#.to_vec(),
    )?;
    let frame = envelope.encode();
    let (status, receipt, stderr) = run_python_tcp(&frame)?;
    assert!(status.success(), "python failed: {stderr}");
    let value: Value = serde_json::from_str(receipt.trim())?;
    assert_eq!(value["schema"], "hepta.integration-live.v2");
    assert_eq!(value["producer"], "hepta-shadow-qualification");
    assert_eq!(value["generation"], 7);
    assert_eq!(value["objective"], "ndu");

    let mut metadata_tamper = frame.clone();
    metadata_tamper[HPTA_V2_HEADER_BYTES] = b'i';
    assert!(matches!(
        WireEnvelopeV2::decode(&metadata_tamper),
        Err(WireV2Error::FrameDigestMismatch { .. })
    ));
    let (status, _, stderr) = run_python_tcp(&metadata_tamper)?;
    assert!(!status.success());
    assert!(stderr.contains("frame digest mismatch"));

    let unknown_field = WireEnvelopeV2::new(
        id("hepta.integration-live.v2")?,
        id("hepta-shadow-qualification")?,
        Generation::new(7)?,
        br#"{"authority":"deny_all","objective":"ndu","step":1,"unknown":true}"#.to_vec(),
    )?;
    let (status, _, stderr) = run_python_tcp(&unknown_field.encode())?;
    assert!(!status.success());
    assert!(stderr.contains("schema admission mismatch"));
    Ok(())
}
