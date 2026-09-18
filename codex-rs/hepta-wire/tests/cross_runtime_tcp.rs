//! Live Rust-Python TCP qualification for HPTA V2.
//!
//! Python independently constructs V2 bytes and writes them over a real TCP
//! socket. Rust performs bounded stream framing, V2 integrity verification,
//! schema admission and typed JSON loading. A second connection changes schema
//! metadata without recomputing the integrity digest and must fail closed.

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_hepta_wire::PayloadCodec;
use codex_hepta_wire::WireCapability;
use codex_hepta_wire::PayloadCodecError;
use codex_hepta_wire::SchemaDefinition;
use codex_hepta_wire::SchemaRegistry;
use codex_hepta_wire::SchemaValidationError;
use codex_hepta_wire::WireError;
use codex_hepta_wire::WireReadError;
use codex_hepta_wire::WireVersion;
use codex_hepta_wire::negotiate;
use codex_hepta_wire::read_frame_for;
use serde::Deserialize;
use serde::Serialize;
use std::error::Error;
use std::net::TcpListener;
use std::process::Command;
use std::process::Stdio;

const PYTHON_CLIENT: &str = r#"
import hashlib, socket, struct, sys

host, port = sys.argv[1].rsplit(':', 1)
port = int(port)
magic = b'HPTA'
version = 2
schema = b'hepta.integration.v2'
producer = b'python.runtime'
generation = 7
payload = b'{"objective":"ndu","authority":"deny_all","step":1}'
domain = b'HPTA-FRAME-V2\x00'

preimage = (
    domain
    + magic
    + struct.pack('!H', version)
    + struct.pack('!H', len(schema))
    + struct.pack('!H', len(producer))
    + struct.pack('!Q', generation)
    + struct.pack('!I', len(payload))
    + schema
    + producer
    + payload
)
digest = hashlib.sha256(preimage).digest()
frame = (
    magic
    + struct.pack('!H', version)
    + struct.pack('!H', len(schema))
    + struct.pack('!H', len(producer))
    + struct.pack('!Q', generation)
    + digest
    + struct.pack('!I', len(payload))
    + schema
    + producer
    + payload
)

with socket.create_connection((host, port), timeout=5) as sock:
    sock.sendall(frame)

tampered = bytearray(frame)
tampered[54] = ord('i')
with socket.create_connection((host, port), timeout=5) as sock:
    sock.sendall(tampered)
"#;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct IntegrationPayload {
    objective: String,
    authority: String,
    step: u64,
}

struct IntegrationCodec {
    schema: StableId,
}

impl IntegrationCodec {
    fn new() -> Result<Self, Box<dyn Error>> {
        Ok(Self {
            schema: StableId::new("hepta.integration.v2")?,
        })
    }
}

impl PayloadCodec for IntegrationCodec {
    type Value = IntegrationPayload;

    fn schema(&self) -> &StableId {
        &self.schema
    }

    fn encode(&self, value: &Self::Value) -> Result<Vec<u8>, PayloadCodecError> {
        serde_json::to_vec(value).map_err(|error| PayloadCodecError::new(error.to_string()))
    }

    fn decode(&self, payload: &[u8]) -> Result<Self::Value, PayloadCodecError> {
        serde_json::from_slice(payload).map_err(|error| PayloadCodecError::new(error.to_string()))
    }
}

fn validate_integration_payload(payload: &[u8]) -> Result<(), SchemaValidationError> {
    serde_json::from_slice::<IntegrationPayload>(payload)
        .map(|_| ())
        .map_err(|error| SchemaValidationError::new(error.to_string()))
}

#[test]
fn python_tcp_v2_is_admitted_and_metadata_tamper_rejects() -> Result<(), Box<dyn Error>> {
    let listener = TcpListener::bind("127.0.0.1:0")?;
    let address = listener.local_addr()?.to_string();

    let mut child = Command::new(std::env::var_os("PYTHON").unwrap_or_else(|| "python3".into()))
        .args(["-c", PYTHON_CLIENT, &address])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?;

    let negotiated = negotiate(
        &[WireVersion::V1, WireVersion::V2],
        &[WireVersion::V2],
        &[WireCapability::FullFrameIntegrity],
    )?;

    let (mut first_stream, _) = listener.accept()?;
    let frame = read_frame_for(&mut first_stream, negotiated)?;

    let codec = IntegrationCodec::new()?;
    let mut registry = SchemaRegistry::new();
    registry.register(SchemaDefinition::new(
        codec.schema().clone(),
        WireVersion::V2,
        WireVersion::V2,
        4_096,
        validate_integration_payload,
    )?)?;
    let admitted = registry.admit(&frame)?;
    let loaded = admitted.decode_with(&codec)?;
    assert_eq!(
        loaded,
        IntegrationPayload {
            objective: "ndu".to_string(),
            authority: "deny_all".to_string(),
            step: 1,
        }
    );
    assert_eq!(admitted.generation(), Generation::new(7)?);
    assert_eq!(admitted.producer().as_str(), "python.runtime");

    let (mut second_stream, _) = listener.accept()?;
    assert!(matches!(
        read_frame_for(&mut second_stream, negotiated),
        Err(WireReadError::Wire(WireError::IntegrityMismatch { .. }))
    ));

    let output = child.wait_with_output()?;
    assert!(
        output.status.success(),
        "python client failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    Ok(())
}
