//! Canonical compatibility-bundle DATA, using the existing checkpoint codec.
//! Decoding does not authenticate Training or create a native evaluation receipt.

use super::*;

const BUNDLE_DATA_MAGIC: &[u8; 8] = b"HEPBDT01";

pub(crate) fn encode_original_bundle_data(
    bundle: &CellCompatibilityBundleV1,
) -> Result<Vec<u8>, Error> {
    bundle.digest().map_err(|_| Error::InvalidRecord)?;
    let mut writer = Writer(Vec::new());
    writer.put(BUNDLE_DATA_MAGIC)?;
    writer.bundle(bundle)?;
    Ok(writer.0)
}

pub(crate) fn decode_original_bundle_data(
    bytes: &[u8],
) -> Result<CellCompatibilityBundleV1, Error> {
    if bytes.is_empty() || bytes.len() > MAX_BYTES {
        return Err(Error::Capacity);
    }
    let mut reader = Reader { bytes, offset: 0 };
    if &reader.take::<8>()? != BUNDLE_DATA_MAGIC {
        return Err(Error::InvalidRecord);
    }
    let bundle = reader.bundle()?;
    if reader.offset != bytes.len() || encode_original_bundle_data(&bundle)? != bytes {
        return Err(Error::InvalidRecord);
    }
    Ok(bundle)
}
