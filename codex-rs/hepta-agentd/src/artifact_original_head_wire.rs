//! Canonical bounded requests contain only purpose, action, original context
//! and a monotonic frame number. All material bytes originate at the source.

use codex_hepta_types::Digest32;
use super::Error;

const MAGIC: &[u8; 8] = b"HARPC001";
pub(super) const MAX_BYTES: usize = 16_384;
const HEADER: usize = 50;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum Purpose { Registry = 1, Head = 2 }
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum Action { Readback = 1, Sign = 2 }
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum Status { Completed = 1, Missing = 2, Pending = 3, Unavailable = 4, ReadbackRequired = 5 }

#[derive(Clone, Debug, Eq, PartialEq)]
pub(super) struct Request {
    purpose: Purpose,
    pub(super) action: Action,
    nonce: u64,
    binding: Digest32,
}

impl Request {
    pub(super) fn new(purpose: Purpose, action: Action, nonce: u64, binding: Digest32) -> Result<Self, Error> {
        if nonce == 0 || nonce > 128 || binding.is_zero()
            || purpose == Purpose::Registry && action != Action::Readback
        {
            return Err(Error::Binding("bounded fixed original Artifact purpose"));
        }
        Ok(Self { purpose, action, nonce, binding })
    }

    pub(super) fn encode(&self) -> Vec<u8> {
        let mut bytes = MAGIC.to_vec();
        bytes.push(self.purpose as u8);
        bytes.push(self.action as u8);
        bytes.extend_from_slice(&self.nonce.to_be_bytes());
        bytes.extend_from_slice(self.binding.as_array());
        bytes
    }

    pub(super) fn decode(bytes: &[u8], purpose: Purpose, nonce: u64, binding: Digest32) -> Result<Self, Error> {
        if bytes.len() != HEADER || bytes.get(..8) != Some(MAGIC.as_slice()) || bytes[8] != purpose as u8 {
            return Err(Error::Binding("exact original Artifact request"));
        }
        let action = match bytes[9] {
            1 => Action::Readback, 2 => Action::Sign,
            _ => return Err(Error::Binding("original Artifact action")),
        };
        let observed_nonce = u64::from_be_bytes(bytes[10..18].try_into().map_err(|_| Error::Unavailable)?);
        let observed_binding = Digest32::from_array(bytes[18..50].try_into().map_err(|_| Error::Unavailable)?);
        if observed_nonce != nonce || observed_binding != binding {
            return Err(Error::Binding("same original Artifact nonce and context"));
        }
        Self::new(purpose, action, nonce, binding)
    }

    pub(super) fn response(&self, status: Status, payload: &[u8]) -> Result<Vec<u8>, Error> {
        if status != Status::Completed && !payload.is_empty() {
            return Err(Error::Binding("no material in unresolved original state"));
        }
        let length = HEADER.checked_add(5).and_then(|n| n.checked_add(payload.len())).ok_or(Error::Unavailable)?;
        if length > MAX_BYTES || status == Status::Completed && payload.is_empty() {
            return Err(Error::Binding("bounded complete original Artifact response"));
        }
        let mut bytes = self.encode();
        bytes.push(status as u8);
        bytes.extend_from_slice(&(payload.len() as u32).to_be_bytes());
        bytes.extend_from_slice(payload);
        Ok(bytes)
    }

    pub(super) fn read_response<'a>(&self, bytes: &'a [u8]) -> Result<&'a [u8], Error> {
        if bytes.len() < HEADER + 5 || bytes.len() > MAX_BYTES
            || bytes[..HEADER] != self.encode()
        {
            return Err(Error::Binding("same original Artifact response"));
        }
        let length = u32::from_be_bytes(bytes[51..55].try_into().map_err(|_| Error::Unavailable)?) as usize;
        if bytes.len() != HEADER + 5 + length { return Err(Error::Unavailable); }
        match bytes[50] {
            1 if length > 0 => Ok(&bytes[55..]),
            2 if length == 0 => Err(Error::Missing),
            3 if length == 0 => Err(Error::Pending),
            4 if length == 0 => Err(Error::Unavailable),
            5 if length == 0 => Err(Error::ReadbackRequired),
            _ => Err(Error::Binding("canonical original Artifact state")),
        }
    }
}
