use std::error::Error;
use std::io;
use std::io::BufRead;
use std::io::BufReader;
use std::io::Read;
use std::io::Write;
use std::net::Shutdown;
use std::net::TcpStream;
use std::process::Command;
use std::process::Stdio;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_hepta_wire::WireEnvelopeV2;
use codex_hepta_wire::WireV2Error;

const PYTHON_V2_SERVER: &str = r#"
import hashlib, json, socket, struct

DOMAIN = b'HPTA-WIRE-V2\0'
listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
listener.bind(('127.0.0.1', 0))
listener.listen(1)
print(listener.getsockname()[1], flush=True)
conn, _ = listener.accept()

def read_exact(count):
    out = bytearray()
    while len(out) < count:
        chunk = conn.recv(count - len(out))
        if not chunk:
            raise SystemExit('truncated')
        out.extend(chunk)
    return bytes(out)

header = read_exact(54)
magic, version, schema_len, producer_len, generation, expected, payload_len = struct.unpack('!4sHHHQ32sI', header)
if magic != b'HPTA' or version != 2:
    raise SystemExit('header mismatch')
if not 1 <= schema_len <= 128 or not 1 <= producer_len <= 128 or not 1 <= payload_len <= 1048576:
    raise SystemExit('bounds mismatch')
body = read_exact(schema_len + producer_len + payload_len)
schema = body[:schema_len]
producer = body[schema_len:schema_len + producer_len]
payload = body[schema_len + producer_len:]
preimage = (DOMAIN + magic + struct.pack('!H', version) + struct.pack('!H', schema_len)
            + struct.pack('!H', producer_len) + struct.pack('!Q', generation)
            + struct.pack('!I', payload_len) + schema + producer + payload)
observed = hashlib.sha256(preimage).digest()
if observed != expected:
    raise SystemExit('frame digest mismatch')
print(json.dumps({'schema': schema.decode('utf-8'), 'producer': producer.decode('utf-8'),
                  'generation': generation, 'payload_hex': payload.hex()}, sort_keys=True), flush=True)
"#;

fn run_python_server(frame: &[u8]) -> Result<(bool, String, String), Box<dyn Error>> {
    let default_python = if cfg!(windows) { "python" } else { "python3" };
    let mut child = Command::new(
        std::env::var_os("PYTHON").unwrap_or_else(|| default_python.into()),
    )
    .args(["-c", PYTHON_V2_SERVER])
    .stdout(Stdio::piped())
    .stderr(Stdio::piped())
    .spawn()?;

    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| io::Error::other("python stdout unavailable"))?;
    let mut reader = BufReader::new(stdout);
    let mut port_line = String::new();
    reader.read_line(&mut port_line)?;
    let port: u16 = port_line.trim().parse()?;

    let mut stream = TcpStream::connect(("127.0.0.1", port))?;
    stream.write_all(frame)?;
    stream.shutdown(Shutdown::Write)?;

    let mut report = String::new();
    reader.read_to_string(&mut report)?;
    let status = child.wait()?;
    let mut stderr = String::new();
    child
        .stderr
        .take()
        .ok_or_else(|| io::Error::other("python stderr unavailable"))?
        .read_to_string(&mut stderr)?;
    Ok((status.success(), report, stderr))
}

#[test]
fn rust_python_live_tcp_v2_loads_and_binds_metadata_and_payload() -> Result<(), Box<dyn Error>> {
    let envelope = WireEnvelopeV2::new(
        StableId::new("hepta.counter.v1")?,
        StableId::new("rust.runtime")?,
        Generation::new(11)?,
        42_u32.to_be_bytes().to_vec(),
    )?;
    let frame = envelope.encode();

    let (success, report, stderr) = run_python_server(&frame)?;
    assert!(success, "python server failed: {stderr}");
    assert!(report.contains("\"schema\": \"hepta.counter.v1\""));
    assert!(report.contains("\"producer\": \"rust.runtime\""));
    assert!(report.contains("\"generation\": 11"));
    assert!(report.contains("\"payload_hex\": \"0000002a\""));

    let mut tampered = frame;
    tampered[54] = b'i';
    let (success, _report, stderr) = run_python_server(&tampered)?;
    assert!(!success);
    assert!(stderr.contains("frame digest mismatch"));
    assert!(matches!(
        WireEnvelopeV2::decode(&tampered),
        Err(WireV2Error::FrameDigestMismatch { .. })
    ));
    Ok(())
}
