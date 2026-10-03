//! Bounded raw material primitives; these bytes grant no admission.
use super::*;
use codex_hepta_types::FixedQ32;
pub(super) const MAX: usize = 16 * 1024 * 1024;
pub(super) type Result<T> = std::result::Result<T, ParameterPlasticityProductErrorV1>;
pub(super) fn invalid() -> ParameterPlasticityProductErrorV1 {
    ParameterPlasticityProductErrorV1::Binding("raw plasticity material codec")
}
pub(super) struct Writer(pub(super) Vec<u8>);
impl Writer {
    pub(super) fn put(&mut self, bytes: &[u8]) -> Result<()> {
        if self
            .0
            .len()
            .checked_add(bytes.len())
            .is_none_or(|size| size > MAX)
        {
            return Err(invalid());
        }
        self.0.extend_from_slice(bytes);
        Ok(())
    }
    pub(super) fn u8(&mut self, value: u8) -> Result<()> {
        self.put(&[value])
    }
    pub(super) fn u32(&mut self, value: usize) -> Result<()> {
        self.put(&u32::try_from(value).map_err(|_| invalid())?.to_be_bytes())
    }
    pub(super) fn u64(&mut self, value: u64) -> Result<()> {
        self.put(&value.to_be_bytes())
    }
    pub(super) fn q(&mut self, value: FixedQ32) -> Result<()> {
        self.put(&value.raw().to_be_bytes())
    }
    pub(super) fn digest(&mut self, value: Digest32) -> Result<()> {
        self.put(value.as_array())
    }
    pub(super) fn blob(&mut self, value: &[u8]) -> Result<()> {
        self.u32(value.len())?;
        self.put(value)
    }
    pub(super) fn id(&mut self, value: &StableId) -> Result<()> {
        self.blob(value.as_str().as_bytes())
    }
    pub(super) fn window(&mut self, value: &ProposalWindowV2) -> Result<()> {
        self.id(&value.window_id)?;
        self.digest(value.window_digest)
    }
    pub(super) fn finish(mut self) -> Result<Vec<u8>> {
        let hash = Digest32::of_bytes(&self.0);
        self.digest(hash)?;
        Ok(self.0)
    }
}
pub(super) struct Reader<'a>(&'a [u8]);
impl<'a> Reader<'a> {
    pub(super) fn new(bytes: &'a [u8], magic: &[u8]) -> Result<Self> {
        if bytes.len() > MAX
            || bytes.len() < magic.len() + 32
            || !bytes.starts_with(magic)
            || Digest32::of_bytes(&bytes[..bytes.len() - 32]).as_array()
                != &bytes[bytes.len() - 32..]
        {
            return Err(invalid());
        }
        Ok(Self(&bytes[magic.len()..bytes.len() - 32]))
    }
    pub(super) fn take(&mut self, size: usize) -> Result<&'a [u8]> {
        let (head, tail) = self.0.split_at_checked(size).ok_or_else(invalid)?;
        self.0 = tail;
        Ok(head)
    }
    pub(super) fn u8(&mut self) -> Result<u8> {
        Ok(self.take(1)?[0])
    }
    pub(super) fn u32(&mut self) -> Result<usize> {
        Ok(u32::from_be_bytes(self.take(4)?.try_into().map_err(|_| invalid())?) as usize)
    }
    pub(super) fn len(&mut self, max: usize) -> Result<usize> {
        let n = self.u32()?;
        if n > max {
            return Err(invalid());
        }
        Ok(n)
    }
    pub(super) fn u64(&mut self) -> Result<u64> {
        Ok(u64::from_be_bytes(
            self.take(8)?.try_into().map_err(|_| invalid())?,
        ))
    }
    pub(super) fn q(&mut self) -> Result<FixedQ32> {
        Ok(FixedQ32::from_raw(i64::from_be_bytes(
            self.take(8)?.try_into().map_err(|_| invalid())?,
        )))
    }
    pub(super) fn digest(&mut self) -> Result<Digest32> {
        Ok(Digest32::from_array(
            self.take(32)?.try_into().map_err(|_| invalid())?,
        ))
    }
    pub(super) fn blob(&mut self) -> Result<&'a [u8]> {
        let n = self.len(MAX)?;
        self.take(n)
    }
    pub(super) fn id(&mut self) -> Result<StableId> {
        let raw = self.blob()?;
        StableId::new(std::str::from_utf8(raw).map_err(|_| invalid())?).map_err(|_| invalid())
    }
    pub(super) fn window(&mut self) -> Result<ProposalWindowV2> {
        Ok(ProposalWindowV2 {
            window_id: self.id()?,
            window_digest: self.digest()?,
        })
    }
    pub(super) fn finish(self) -> Result<()> {
        if self.0.is_empty() {
            Ok(())
        } else {
            Err(invalid())
        }
    }
}
