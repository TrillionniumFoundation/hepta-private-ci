use crate::MAX_AUTHENTICATED_FRAME_BYTES;

use super::context::FederationProductProfileV1;
use super::error::FederationProductErrorV1;

pub const MAX_FEDERATION_PRODUCT_BODY_BYTES: usize = 512 * 1024;
/// Registered encoding adds bounded schema metadata around the authenticated
/// frame payload.
pub const MAX_FEDERATION_PRODUCT_FRAME_BYTES: usize = MAX_AUTHENTICATED_FRAME_BYTES + 4096;
pub const MAX_FEDERATION_PRODUCT_PACKET_BYTES: usize =
    MAX_FEDERATION_PRODUCT_FRAME_BYTES + MAX_FEDERATION_PRODUCT_BODY_BYTES + 32;

const PACKET_MAGIC: [u8; 4] = *b"HFP1";
const PACKET_VERSION: u16 = 1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederationProductPacketV1 {
    authenticated_frame: Vec<u8>,
    body: Vec<u8>,
}

impl FederationProductPacketV1 {
    pub fn new(
        authenticated_frame: Vec<u8>,
        body: Vec<u8>,
    ) -> Result<Self, FederationProductErrorV1> {
        if authenticated_frame.is_empty()
            || authenticated_frame.len() > MAX_FEDERATION_PRODUCT_FRAME_BYTES
            || body.len() > MAX_FEDERATION_PRODUCT_BODY_BYTES
        {
            return Err(FederationProductErrorV1::PacketOversize);
        }
        Ok(Self {
            authenticated_frame,
            body,
        })
    }

    pub fn authenticated_frame(&self) -> &[u8] {
        &self.authenticated_frame
    }

    pub fn body(&self) -> &[u8] {
        &self.body
    }

    pub fn encode(&self) -> Result<Vec<u8>, FederationProductErrorV1> {
        let frame_len = u32::try_from(self.authenticated_frame.len())
            .map_err(|_| FederationProductErrorV1::PacketOversize)?;
        let body_len =
            u32::try_from(self.body.len()).map_err(|_| FederationProductErrorV1::PacketOversize)?;
        let mut bytes =
            Vec::with_capacity(4 + 2 + 4 + self.authenticated_frame.len() + 4 + self.body.len());
        bytes.extend_from_slice(&PACKET_MAGIC);
        bytes.extend_from_slice(&PACKET_VERSION.to_be_bytes());
        bytes.extend_from_slice(&frame_len.to_be_bytes());
        bytes.extend_from_slice(&self.authenticated_frame);
        bytes.extend_from_slice(&body_len.to_be_bytes());
        bytes.extend_from_slice(&self.body);
        if bytes.len() > MAX_FEDERATION_PRODUCT_PACKET_BYTES {
            return Err(FederationProductErrorV1::PacketOversize);
        }
        Ok(bytes)
    }

    pub fn decode(
        payload: &[u8],
        profile: &FederationProductProfileV1,
    ) -> Result<Self, FederationProductErrorV1> {
        if payload.is_empty()
            || payload.len() > profile.maximum_packet_bytes()
            || payload.len() > MAX_FEDERATION_PRODUCT_PACKET_BYTES
        {
            return Err(FederationProductErrorV1::PacketOversize);
        }
        let mut reader = PacketReader::new(payload);
        if reader.take_array::<4>()? != PACKET_MAGIC {
            return Err(FederationProductErrorV1::PacketMagic);
        }
        if reader.read_u16()? != PACKET_VERSION {
            return Err(FederationProductErrorV1::PacketVersion);
        }
        let frame_len = reader.read_len(MAX_FEDERATION_PRODUCT_FRAME_BYTES)?;
        if frame_len == 0 {
            return Err(FederationProductErrorV1::PacketOversize);
        }
        let authenticated_frame = reader.take(frame_len)?.to_vec();
        let body_len = reader.read_len(MAX_FEDERATION_PRODUCT_BODY_BYTES)?;
        let body = reader.take(body_len)?.to_vec();
        reader.require_eof()?;
        Self::new(authenticated_frame, body)
    }
}

pub(super) fn require_body_bound(bytes: &[u8]) -> Result<(), FederationProductErrorV1> {
    if bytes.is_empty() || bytes.len() > MAX_FEDERATION_PRODUCT_BODY_BYTES {
        return Err(FederationProductErrorV1::BodyOversize);
    }
    Ok(())
}

struct PacketReader<'a> {
    payload: &'a [u8],
    cursor: usize,
}

impl<'a> PacketReader<'a> {
    const fn new(payload: &'a [u8]) -> Self {
        Self { payload, cursor: 0 }
    }

    fn read_u16(&mut self) -> Result<u16, FederationProductErrorV1> {
        Ok(u16::from_be_bytes(self.take_array()?))
    }

    fn read_u32(&mut self) -> Result<u32, FederationProductErrorV1> {
        Ok(u32::from_be_bytes(self.take_array()?))
    }

    fn read_len(&mut self, maximum: usize) -> Result<usize, FederationProductErrorV1> {
        let value = usize::try_from(self.read_u32()?)
            .map_err(|_| FederationProductErrorV1::PacketOversize)?;
        if value > maximum {
            return Err(FederationProductErrorV1::PacketOversize);
        }
        Ok(value)
    }

    fn take(&mut self, length: usize) -> Result<&'a [u8], FederationProductErrorV1> {
        let end = self
            .cursor
            .checked_add(length)
            .ok_or(FederationProductErrorV1::PacketTruncated)?;
        let value = self
            .payload
            .get(self.cursor..end)
            .ok_or(FederationProductErrorV1::PacketTruncated)?;
        self.cursor = end;
        Ok(value)
    }

    fn take_array<const N: usize>(&mut self) -> Result<[u8; N], FederationProductErrorV1> {
        self.take(N)?
            .try_into()
            .map_err(|_| FederationProductErrorV1::PacketTruncated)
    }

    fn require_eof(&self) -> Result<(), FederationProductErrorV1> {
        if self.cursor == self.payload.len() {
            Ok(())
        } else {
            Err(FederationProductErrorV1::TrailingBytes)
        }
    }
}
