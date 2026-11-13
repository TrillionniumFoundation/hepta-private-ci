//! Bounded data encoding for one original Root task handoff. No decoder here
//! constructs a task receipt, admission, source owner or publication authority.

use codex_hepta_types::{Digest32, Generation, StableId};
use serde::Serialize;
use serde::de::DeserializeOwned;

use super::CircuitTaskErrorV1 as Error;

pub(crate) const BOUND: usize = 65_536;

pub(crate) struct Writer(Vec<u8>);

impl Writer {
    pub(crate) fn new(domain: &[u8]) -> Self { Self(domain.to_vec()) }
    pub(crate) fn raw(&mut self, data: &[u8]) -> Result<(), Error> {
        if self.0.len().checked_add(data.len()).is_none_or(|n| n > BOUND) {
            return Err(Error::InvalidBinding);
        }
        self.0.extend_from_slice(data);
        Ok(())
    }
    pub(crate) fn byte(&mut self, value: u8) -> Result<(), Error> { self.raw(&[value]) }
    pub(crate) fn u32(&mut self, value: u32) -> Result<(), Error> { self.raw(&value.to_be_bytes()) }
    pub(crate) fn u64(&mut self, value: u64) -> Result<(), Error> { self.raw(&value.to_be_bytes()) }
    pub(crate) fn i64(&mut self, value: i64) -> Result<(), Error> { self.raw(&value.to_be_bytes()) }
    pub(crate) fn size(&mut self, value: usize) -> Result<(), Error> {
        self.u64(u64::try_from(value).map_err(|_| Error::InvalidBinding)?)
    }
    pub(crate) fn count(&mut self, value: usize, bound: usize) -> Result<(), Error> {
        if value > bound { return Err(Error::InvalidBinding); }
        self.u32(u32::try_from(value).map_err(|_| Error::InvalidBinding)?)
    }
    pub(crate) fn bytes(&mut self, value: &[u8]) -> Result<(), Error> {
        self.u32(u32::try_from(value.len()).map_err(|_| Error::InvalidBinding)?)?;
        self.raw(value)
    }
    pub(crate) fn text(&mut self, value: &str) -> Result<(), Error> {
        if value.is_empty() || value.len() > 128 || value.chars().any(char::is_control) {
            return Err(Error::InvalidBinding);
        }
        self.bytes(value.as_bytes())
    }
    pub(crate) fn id(&mut self, value: &StableId) -> Result<(), Error> { self.text(value.as_str()) }
    pub(crate) fn digest(&mut self, value: Digest32) -> Result<(), Error> { self.raw(value.as_array()) }
    pub(crate) fn generation(&mut self, value: Generation) -> Result<(), Error> { self.u64(value.get()) }
    pub(crate) fn json<T: Serialize>(&mut self, value: &T) -> Result<(), Error> {
        self.bytes(&serde_json::to_vec(value).map_err(|_| Error::InvalidBinding)?)
    }
    pub(crate) fn finish(self) -> Vec<u8> { self.0 }
}

pub(crate) struct Reader<'a>(&'a [u8]);

impl<'a> Reader<'a> {
    pub(crate) fn new(data: &'a [u8], domain: &[u8]) -> Result<Self, Error> {
        if data.len() > BOUND { return Err(Error::InvalidBinding); }
        Ok(Self(data.strip_prefix(domain).ok_or(Error::InvalidBinding)?))
    }
    pub(crate) fn take<const N: usize>(&mut self) -> Result<[u8; N], Error> {
        let (value, rest) = self.0.split_at_checked(N).ok_or(Error::InvalidBinding)?;
        self.0 = rest;
        value.try_into().map_err(|_| Error::InvalidBinding)
    }
    pub(crate) fn byte(&mut self) -> Result<u8, Error> { Ok(self.take::<1>()?[0]) }
    pub(crate) fn u32(&mut self) -> Result<u32, Error> { Ok(u32::from_be_bytes(self.take()?)) }
    pub(crate) fn u64(&mut self) -> Result<u64, Error> { Ok(u64::from_be_bytes(self.take()?)) }
    pub(crate) fn i64(&mut self) -> Result<i64, Error> { Ok(i64::from_be_bytes(self.take()?)) }
    pub(crate) fn size(&mut self) -> Result<usize, Error> {
        usize::try_from(self.u64()?).map_err(|_| Error::InvalidBinding)
    }
    pub(crate) fn count(&mut self, bound: usize) -> Result<usize, Error> {
        let n = self.u32()? as usize;
        if n > bound || n > self.0.len() { return Err(Error::InvalidBinding); }
        Ok(n)
    }
    pub(crate) fn bytes(&mut self) -> Result<&'a [u8], Error> {
        let n = self.u32()? as usize;
        let (value, rest) = self.0.split_at_checked(n).ok_or(Error::InvalidBinding)?;
        self.0 = rest;
        Ok(value)
    }
    pub(crate) fn text(&mut self) -> Result<String, Error> {
        let value = std::str::from_utf8(self.bytes()?).map_err(|_| Error::InvalidBinding)?;
        if value.is_empty() || value.len() > 128 || value.chars().any(char::is_control) {
            return Err(Error::InvalidBinding);
        }
        Ok(value.to_owned())
    }
    pub(crate) fn id(&mut self) -> Result<StableId, Error> {
        StableId::new(self.text()?).map_err(|_| Error::InvalidBinding)
    }
    pub(crate) fn digest(&mut self) -> Result<Digest32, Error> { Ok(Digest32::from_array(self.take()?)) }
    pub(crate) fn generation(&mut self) -> Result<Generation, Error> {
        Generation::new(self.u64()?).map_err(|_| Error::InvalidBinding)
    }
    pub(crate) fn json<T: DeserializeOwned + Serialize>(&mut self) -> Result<T, Error> {
        let bytes = self.bytes()?;
        let value: T = serde_json::from_slice(bytes).map_err(|_| Error::InvalidBinding)?;
        if serde_json::to_vec(&value).map_err(|_| Error::InvalidBinding)? != bytes {
            return Err(Error::InvalidBinding);
        }
        Ok(value)
    }
    pub(crate) fn end(self) -> Result<(), Error> {
        if self.0.is_empty() { Ok(()) } else { Err(Error::InvalidBinding) }
    }
}
