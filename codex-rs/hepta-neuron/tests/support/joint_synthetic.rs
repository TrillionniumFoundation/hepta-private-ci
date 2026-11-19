//! Test-only fixed artificial assets and bounded independent wire inspection.
//! No trained checkpoint, production fixture command or model execution lives here.

use std::collections::BTreeMap;
use std::io;

use codex_hepta_types::Digest32;
use serde::Deserialize;

const FIXTURE: &str = include_str!("../fixtures/joint-synthetic-v1.json");
const WEIGHTS_SHA256: &str = "f358e6073cac89c9680e6c9041c4b03480354236f91beabf6cd0bc9025b6c0fc";
const PUBLIC_SHA256: &str = "393a86d68b17de8290eecc4399c18006a6c5e467a66e8cb8eae85c98cbc114d5";
pub(crate) const TOTAL_UNITS: [u32; 4] = [16, 1024, 4, 2];

pub(crate) struct Assets {
    pub(crate) weights: Vec<u8>,
    pub(crate) public: Vec<u8>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Document {
    schema_version: u32,
    synthetic: bool,
    source_fixture: String,
    description: String,
    weights: Encoded,
    public: Encoded,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Encoded {
    expanded_bytes: usize,
    sha256: String,
    tensor_count: usize,
    runs: Vec<(usize, String)>,
}

fn invalid(message: &str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message)
}

pub(crate) fn assets() -> io::Result<Assets> {
    if FIXTURE.len() > 64 * 1024 {
        return Err(invalid("synthetic fixture JSON exceeds bound"));
    }
    let document: Document = serde_json::from_str(FIXTURE)?;
    if document.schema_version != 1
        || !document.synthetic
        || document.source_fixture
            != "hepta-infer-worker-host/src/joint_generation/proposal_test_support.rs"
        || !document.description.starts_with("Artificial 67-tensor")
    {
        return Err(invalid("synthetic fixture provenance mismatch"));
    }
    Ok(Assets {
        weights: expand(
            document.weights,
            /*bytes*/ 4_778_904,
            WEIGHTS_SHA256,
            /*tensors*/ 67,
        )?,
        public: expand(
            document.public,
            /*bytes*/ 78_180,
            PUBLIC_SHA256,
            /*tensors*/ 7,
        )?,
    })
}

fn expand(encoded: Encoded, bytes: usize, digest: &str, tensors: usize) -> io::Result<Vec<u8>> {
    if encoded.expanded_bytes != bytes
        || encoded.sha256 != digest
        || encoded.tensor_count != tensors
        || encoded.runs.len() > 1024
        || bytes > 8 * 1024 * 1024
    {
        return Err(invalid("synthetic fixture expansion metadata"));
    }
    let mut output = Vec::with_capacity(bytes);
    for (zeros, literal) in encoded.runs {
        let next = output
            .len()
            .checked_add(zeros)
            .and_then(|length| length.checked_add(literal.len() / 2))
            .ok_or_else(|| invalid("synthetic fixture size overflow"))?;
        if !literal.len().is_multiple_of(2) || literal.len() > 16_384 || next > bytes {
            return Err(invalid("synthetic fixture run exceeds bound"));
        }
        output.resize(output.len() + zeros, 0);
        for pair in literal.as_bytes().chunks_exact(2) {
            let text = std::str::from_utf8(pair).map_err(|_| invalid("fixture hex UTF-8"))?;
            output.push(u8::from_str_radix(text, 16).map_err(|_| invalid("fixture hex byte"))?);
        }
    }
    if output.len() != bytes || Digest32::of_bytes(&output).to_string() != digest {
        return Err(invalid("synthetic fixture expanded hash mismatch"));
    }
    checked_packet_body(&output)?;
    Ok(output)
}

#[derive(Debug, Eq, PartialEq)]
pub(crate) struct Prefix {
    pub(crate) cursors: [u32; 4],
    pub(crate) bytes: [Vec<u8>; 4],
}

pub(crate) fn prefix(bytes: &[u8]) -> io::Result<Prefix> {
    if bytes.len() > 262_144 {
        return Err(invalid("prefix exceeds bound"));
    }
    let mut input = Reader(bytes);
    let mut output = Prefix {
        cursors: [0; 4],
        bytes: std::array::from_fn(|_| Vec::new()),
    };
    while !input.0.is_empty() {
        if input.take(4)? != b"HGC1" {
            return Err(invalid("output frame magic"));
        }
        let modality = usize::from(input.take(1)?[0]);
        if modality >= TOTAL_UNITS.len() {
            return Err(invalid("output modality"));
        }
        let start = input.integer()?;
        let units = input.integer()?;
        let length = input.integer()? as usize;
        let next = start
            .checked_add(units)
            .ok_or_else(|| invalid("cursor overflow"))?;
        if units == 0 || start != output.cursors[modality] || next > TOTAL_UNITS[modality] {
            return Err(invalid("output cursor continuity"));
        }
        let expected = match modality {
            0 => units as usize * 48,
            1 => units as usize * 2,
            2 => units as usize * 768,
            _ => {
                if length > 32 {
                    return Err(invalid("text frame bound"));
                }
                length
            }
        };
        if length != expected {
            return Err(invalid("output payload length"));
        }
        output.bytes[modality].extend(input.take(length)?);
        output.cursors[modality] = next;
    }
    Ok(output)
}

#[derive(Debug, Eq, PartialEq)]
pub(crate) struct StateFacts {
    pub(crate) steps: u32,
    pub(crate) stopped: bool,
    pub(crate) cursors: [u32; 4],
}

pub(crate) fn state(bytes: &[u8], emitted: &[u8], assets: &Assets) -> io::Result<StateFacts> {
    if bytes.len() > 65_536 {
        return Err(invalid("state packet exceeds bound"));
    }
    let mut input = Reader(checked_packet_body(bytes)?);
    input.take(8)?;
    let mut metadata = BTreeMap::new();
    let count = input.count(64)?;
    for _ in 0..count {
        let name = input.string()?;
        if metadata.insert(name, input.string()?).is_some() {
            return Err(invalid("duplicate state metadata"));
        }
    }
    let text = |name: &str| {
        metadata
            .get(name)
            .map(String::as_str)
            .ok_or_else(|| invalid("missing state metadata"))
    };
    for (name, expected) in [
        ("kind", "joint-generation-proposal-state-v1".to_owned()),
        ("seed", "17".to_owned()),
        ("sampler", "mean".to_owned()),
        ("weights", Digest32::of_bytes(&assets.weights).to_string()),
        ("input", Digest32::of_bytes(&assets.public).to_string()),
        (
            "bridge.prefix_sha256",
            Digest32::of_bytes(emitted).to_string(),
        ),
    ] {
        if text(name)? != expected {
            return Err(invalid("state asset, sampler or actual-prefix binding"));
        }
    }
    let emitted = prefix(emitted)?;
    let count = input.count(32)?;
    let mut tensors = BTreeMap::new();
    for _ in 0..count {
        let name = input.string()?;
        if input.count(8)? != 1 {
            return Err(invalid("state vector shape"));
        }
        let length = input.count(8192)?;
        if input.count(8192)? != length {
            return Err(invalid("state vector length"));
        }
        let mut values = Vec::with_capacity(length);
        for _ in 0..length {
            let word = input
                .take(8)?
                .try_into()
                .map_err(|_| invalid("state f64 width"))?;
            let value = f64::from_le_bytes(word);
            if !value.is_finite() {
                return Err(invalid("nonfinite state scalar"));
            }
            values.push(value);
        }
        if tensors.insert(name, values).is_some() {
            return Err(invalid("duplicate state tensor"));
        }
    }
    for (index, modality) in ["image", "audio", "video", "text"].iter().enumerate() {
        if text(&format!("cursor.{modality}"))? != emitted.cursors[index].to_string()
            || tensors.get(&format!("prefix.{modality}"))
                != Some(
                    &emitted.bytes[index]
                        .iter()
                        .map(|byte| f64::from(*byte))
                        .collect(),
                )
        {
            return Err(invalid("state prefix tensor/cursor mismatch"));
        }
    }
    if !input.0.is_empty() {
        return Err(invalid("state trailing bytes"));
    }
    Ok(StateFacts {
        steps: text("steps")?.parse().map_err(|_| invalid("state steps"))?,
        stopped: text("stopped")?
            .parse()
            .map_err(|_| invalid("state stopped"))?,
        cursors: emitted.cursors,
    })
}

fn checked_packet_body(bytes: &[u8]) -> io::Result<&[u8]> {
    if bytes.len() < 76 || bytes.get(..8) != Some(b"HEPTAPK3".as_slice()) {
        return Err(invalid("packet magic/length"));
    }
    let end = bytes.len() - 64;
    if Digest32::of_bytes(&bytes[..end]).to_string().as_bytes() != &bytes[end..] {
        return Err(invalid("packet checksum"));
    }
    Ok(&bytes[..end])
}

struct Reader<'a>(&'a [u8]);

impl<'a> Reader<'a> {
    fn take(&mut self, count: usize) -> io::Result<&'a [u8]> {
        if count > self.0.len() {
            return Err(invalid("truncated fixture wire"));
        }
        let (bytes, rest) = self.0.split_at(count);
        self.0 = rest;
        Ok(bytes)
    }

    fn integer(&mut self) -> io::Result<u32> {
        Ok(u32::from_le_bytes(
            self.take(4)?.try_into().map_err(|_| invalid("u32 width"))?,
        ))
    }

    fn count(&mut self, limit: usize) -> io::Result<usize> {
        let count = self.integer()? as usize;
        if count > limit {
            return Err(invalid("fixture count exceeds bound"));
        }
        Ok(count)
    }

    fn string(&mut self) -> io::Result<String> {
        let count = self.count(256)?;
        String::from_utf8(self.take(count)?.to_vec()).map_err(|_| invalid("fixture string UTF-8"))
    }
}
