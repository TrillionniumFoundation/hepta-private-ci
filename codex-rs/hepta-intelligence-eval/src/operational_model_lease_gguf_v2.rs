//! The original fixed-encoder GGUF tokenizer digest, bounded to metadata only.
use crate::initial_neuron_operational_source::HostResult;
use codex_hepta_types::Digest32;
use std::collections::BTreeSet;
use std::io::Read;

struct MetadataReader<R> {
    stream: R,
    consumed: u64,
    captured: Vec<u8>,
}
impl<R: Read> MetadataReader<R> {
    fn bytes(&mut self, size: usize, record: bool) -> HostResult<Vec<u8>> {
        self.consumed = self
            .consumed
            .checked_add(u64::try_from(size)?)
            .ok_or("GGUF size overflow")?;
        if self.consumed > 8 * 1024 * 1024 || size > 1024 * 1024 {
            return Err("GGUF metadata budget".into());
        }
        let mut bytes = vec![0; size];
        self.stream.read_exact(&mut bytes)?;
        if record {
            self.captured.extend_from_slice(&bytes);
        }
        Ok(bytes)
    }
    fn u32(&mut self, record: bool) -> HostResult<u32> {
        Ok(u32::from_le_bytes(
            self.bytes(4, record)?
                .try_into()
                .map_err(|_| "GGUF integer")?,
        ))
    }
    fn u64(&mut self, record: bool) -> HostResult<u64> {
        Ok(u64::from_le_bytes(
            self.bytes(8, record)?
                .try_into()
                .map_err(|_| "GGUF integer")?,
        ))
    }
    fn string(&mut self, record: bool) -> HostResult<Vec<u8>> {
        let count = self.u64(record)?;
        if count > 1024 * 1024 {
            return Err("GGUF string budget".into());
        }
        self.bytes(usize::try_from(count)?, record)
    }
    fn value(&mut self, kind: u32, record: bool) -> HostResult<()> {
        match kind {
            0 | 1 | 7 => {
                self.bytes(1, record)?;
            }
            2 | 3 => {
                self.bytes(2, record)?;
            }
            4..=6 => {
                self.bytes(4, record)?;
            }
            10..=12 => {
                self.bytes(8, record)?;
            }
            8 => {
                self.string(record)?;
            }
            9 => {
                let element = self.u32(record)?;
                let count = self.u64(record)?;
                if count > 65_536 || !matches!(element, 0..=8 | 10..=12) {
                    return Err("GGUF array budget/type".into());
                }
                for _ in 0..count {
                    self.value(element, record)?;
                }
            }
            _ => return Err("GGUF metadata type".into()),
        }
        Ok(())
    }
}

pub(super) fn tokenizer_digest(stream: impl Read) -> HostResult<Digest32> {
    let mut reader = MetadataReader {
        stream,
        consumed: 0,
        captured: Vec::new(),
    };
    if reader.bytes(4, false)? != b"GGUF" || reader.u32(false)? != 3 {
        return Err("GGUF magic/version".into());
    }
    let tensors = reader.u64(false)?;
    let count = reader.u64(false)?;
    if tensors > 4096 || !(1..=256).contains(&count) {
        return Err("GGUF header budget".into());
    }
    let mut seen = BTreeSet::new();
    for _ in 0..count {
        let key = reader.string(false)?;
        if !seen.insert(key.clone()) {
            return Err("duplicate GGUF metadata".into());
        }
        let record = key.starts_with(b"tokenizer.");
        if record {
            reader
                .captured
                .extend_from_slice(&u64::try_from(key.len())?.to_le_bytes());
            reader.captured.extend_from_slice(&key);
        }
        let kind = reader.u32(record)?;
        reader.value(kind, record)?;
    }
    if reader.captured.is_empty() {
        return Err("missing original tokenizer metadata".into());
    }
    Ok(Digest32::of_bytes(&reader.captured))
}

#[cfg(test)]
#[path = "operational_model_lease_gguf_v2_tests.rs"]
mod tests;
