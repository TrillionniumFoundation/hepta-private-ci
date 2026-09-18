//! Live Rust↔Python HPTA V2 loading with strict schema admission.

use std::error::Error;
use std::io;
use std::io::Write;
use std::process::Command;
use std::process::Stdio;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_hepta_wire::AdmissionPolicy;
use codex_hepta_wire::PayloadCodec;
use codex_hepta_wire::PayloadCodecError;
use codex_hepta_wire::PayloadValidationError;
use codex_hepta_wire::ProducerAdmission;
use codex_hepta_wire::SchemaRegistry;
use codex_hepta_wire::SchemaRule;
use codex_hepta_wire::WireCapability;
use codex_hepta_wire::WireVersion;
use codex_hepta_wire::decode_envelope;
use codex_hepta_wire::decode_typed;
use codex_hepta_wire::encode_typed;
use codex_hepta_wire::negotiate;
use serde::Deserialize;
use serde::Serialize;

const PYTHON_V2_PEER: &str = r#"
import hashlib, json, struct, sys

DOMAIN = b'hepta.platform.wire.hpta.v2.frame-digest\x00'

def digest(schema, producer, generation, payload):
    preimage = (
        DOMAIN + b'HPTA' + struct.pack('!H', 2)
        + struct.pack('!H', len(schema)) + struct.pack('!H', len(producer))
        + struct.pack('!Q', generation) + struct.pack('!I', len(payload))
        + schema + producer + payload
    )
    return hashlib.sha256(preimage).digest()

def decode(raw):
    if len(raw) < 54:
        raise SystemExit('truncated')
    magic, version, slen, plen, generation, expected, payload_len = struct.unpack(
        '!4sHHHQ32sI', raw[:54]
    )
    if magic != b'HPTA' or version != 2:
        raise SystemExit('header mismatch')
    end = 54 + slen + plen + payload_len
    if len(raw) != end:
        raise SystemExit('length mismatch')
    schema = raw[54:54+slen]
    producer = raw[54+slen:54+slen+plen]
    payload = raw[54+slen+plen:end]
    if digest(schema, producer, generation, payload) != expected:
        raise SystemExit('frame digest mismatch')
    return schema, producer, generation, payload

def encode(schema, producer, generation, payload):
    frame_digest = digest(schema, producer, generation, payload)
    return (
        b'HPTA' + struct.pack('!H', 2)
        + struct.pack('!H', len(schema)) + struct.pack('!H', len(producer))
        + struct.pack('!Q', generation) + frame_digest
        + struct.pack('!I', len(payload)) + schema + producer + payload
    )

raw = bytes.fromhex(sys.stdin.read().strip())
schema, producer, generation, payload = decode(raw)
if schema != b'hepta.integration.request.v1':
    raise SystemExit('unknown request schema')
message = json.loads(payload)
if set(message) != {'objective', 'step'}:
    raise SystemExit('unknown request fields')
reply = json.dumps(
    {'accepted': True, 'step': message['step']},
    sort_keys=True,
    separators=(',', ':'),
).encode()
sys.stdout.write(encode(
    b'hepta.integration.reply.v1',
    b'python.peer',
    generation,
    reply,
).hex())
"#;

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Request {
    objective: String,
    step: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Reply {
    accepted: bool,
    step: u64,
}

#[derive(Debug)]
struct JsonCodec<T> {
    schema: StableId,
    marker: std::marker::PhantomData<T>,
}

impl<T> JsonCodec<T> {
    fn new(schema: &str) -> Result<Self, Box<dyn Error>> {
        Ok(Self {
            schema: StableId::new(schema)?,
            marker: std::marker::PhantomData,
        })
    }
}

impl<T> PayloadCodec for JsonCodec<T>
where
    T: Serialize + for<'de> Deserialize<'de>,
{
    type Value = T;

    fn schema(&self) -> &StableId {
        &self.schema
    }

    fn encode_payload(&self, value: &Self::Value) -> Result<Vec<u8>, PayloadCodecError> {
        serde_json::to_vec(value).map_err(|error| PayloadCodecError::new(error.to_string()))
    }

    fn decode_payload(&self, payload: &[u8]) -> Result<Self::Value, PayloadCodecError> {
        serde_json::from_slice(payload).map_err(|error| PayloadCodecError::new(error.to_string()))
    }
}

fn validate_reply(payload: &[u8]) -> Result<(), PayloadValidationError> {
    serde_json::from_slice::<Reply>(payload)
        .map(|_| ())
        .map_err(|_| PayloadValidationError::new("invalid reply schema"))
}

fn encode_hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        output.push(HEX[(byte >> 4) as usize] as char);
        output.push(HEX[(byte & 0x0f) as usize] as char);
    }
    output
}

fn decode_hex(value: &[u8]) -> Result<Vec<u8>, Box<dyn Error>> {
    let text = std::str::from_utf8(value)?;
    if text.len() % 2 != 0 {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "odd-length hex reply").into());
    }
    let mut output = Vec::with_capacity(text.len() / 2);
    for pair in text.as_bytes().chunks_exact(2) {
        let pair = std::str::from_utf8(pair)?;
        output.push(u8::from_str_radix(pair, 16)?);
    }
    Ok(output)
}

#[test]
fn negotiated_v2_cross_runtime_schema_loading_round_trip() -> Result<(), Box<dyn Error>> {
    let negotiated = negotiate(
        &[WireVersion::V1, WireVersion::V2],
        &[WireVersion::V1, WireVersion::V2],
        &[WireCapability::MetadataBoundIntegrity],
    )?;
    assert_eq!(negotiated.version(), WireVersion::V2);

    let request_codec = JsonCodec::<Request>::new("hepta.integration.request.v1")?;
    let request = Request {
        objective: "ndu".to_string(),
        step: 7,
    };
    let generation = Generation::new(12)?;
    let frame = encode_typed(
        &request_codec,
        StableId::new("rust.peer")?,
        generation,
        &request,
        negotiated.version(),
    )?;

    let mut child = Command::new(std::env::var_os("PYTHON").unwrap_or_else(|| "python3".into()))
        .args(["-c", PYTHON_V2_PEER])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?;
    let mut stdin = child
        .stdin
        .take()
        .ok_or_else(|| io::Error::new(io::ErrorKind::BrokenPipe, "python stdin unavailable"))?;
    stdin.write_all(encode_hex(&frame).as_bytes())?;
    drop(stdin);
    let output = child.wait_with_output()?;
    if !output.status.success() {
        return Err(io::Error::other(format!(
            "python peer failed: {}",
            String::from_utf8_lossy(&output.stderr)
        ))
        .into());
    }

    let reply_bytes = decode_hex(&output.stdout)?;
    let reply_frame = decode_envelope(&reply_bytes)?;
    let reply_codec = JsonCodec::<Reply>::new("hepta.integration.reply.v1")?;
    let mut registry = SchemaRegistry::new();
    registry.register(SchemaRule::new(
        reply_codec.schema().clone(),
        4096,
        validate_reply,
    )?)?;
    let producers = ProducerAdmission::allow_list([StableId::new("python.peer")?])?;
    let admitted = AdmissionPolicy::new(&registry, &producers).admit(&reply_frame)?;
    let typed = decode_typed(&reply_codec, admitted)?;
    assert_eq!(
        typed.value,
        Reply {
            accepted: true,
            step: request.step,
        }
    );
    assert_eq!(typed.generation, generation);
    Ok(())
}
