//! Bounded metadata-only encoding. No original receipt or owner is decoded.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::Error;

pub(super) const MAX_POLICY_BYTES: usize = 131_072;

pub(super) fn put_bytes(out: &mut Vec<u8>, value: &[u8]) {
    out.extend_from_slice(&(value.len() as u64).to_be_bytes());
    out.extend_from_slice(value);
}

pub(super) fn put_id(out: &mut Vec<u8>, value: &StableId) {
    put_bytes(out, value.as_str().as_bytes());
}

pub(super) struct Read<'a> {
    bytes: &'a [u8],
    offset: usize,
}

impl<'a> Read<'a> {
    pub(super) fn new(bytes: &'a [u8]) -> Result<Self, Error> {
        if bytes.is_empty() || bytes.len() > MAX_POLICY_BYTES {
            return Err(Error::Binding("bounded complete V2 policy preimage"));
        }
        Ok(Self { bytes, offset: 0 })
    }

    pub(super) fn take(&mut self, count: usize) -> Result<&'a [u8], Error> {
        let end = self.offset.checked_add(count)
            .ok_or(Error::Binding("policy metadata offset"))?;
        let value = self.bytes.get(self.offset..end)
            .ok_or(Error::Binding("complete policy metadata"))?;
        self.offset = end;
        Ok(value)
    }

    pub(super) fn literal(&mut self, value: &[u8]) -> Result<(), Error> {
        if self.take(value.len())? != value {
            return Err(Error::Binding("explicit V2 policy domain"));
        }
        Ok(())
    }

    pub(super) fn u8(&mut self) -> Result<u8, Error> {
        Ok(self.take(1)?[0])
    }

    pub(super) fn u64(&mut self) -> Result<u64, Error> {
        Ok(u64::from_be_bytes(self.take(8)?.try_into()
            .map_err(|_| Error::Binding("policy metadata integer"))?))
    }

    pub(super) fn count(&mut self, maximum: usize) -> Result<usize, Error> {
        let count = usize::try_from(self.u64()?)
            .map_err(|_| Error::Binding("policy metadata count"))?;
        if count > maximum {
            return Err(Error::Binding("bounded policy metadata count"));
        }
        Ok(count)
    }

    pub(super) fn bytes(&mut self) -> Result<&'a [u8], Error> {
        let count = self.count(MAX_POLICY_BYTES)?;
        self.take(count)
    }

    pub(super) fn id(&mut self) -> Result<StableId, Error> {
        let count = self.count(128)?;
        StableId::new(std::str::from_utf8(self.take(count)?)
            .map_err(|_| Error::Binding("UTF-8 policy identity"))?)
            .map_err(|_| Error::Binding("valid original policy identity"))
    }

    pub(super) fn array(&mut self) -> Result<[u8; 32], Error> {
        self.take(32)?.try_into().map_err(|_| Error::Binding("policy digest"))
    }

    pub(super) fn digest(&mut self) -> Result<Digest32, Error> {
        Ok(Digest32::from_array(self.array()?))
    }

    pub(super) fn finish(self) -> Result<(), Error> {
        if self.offset != self.bytes.len() {
            return Err(Error::Binding("no trailing policy metadata"));
        }
        Ok(())
    }
}
