//! Maintained codec adapter for the original syntect 5.3 dump wire format.
//!
//! The upstream bincode 1 free functions use little-endian fixed-width integer
//! encoding. Keep that explicit legacy configuration for every dump operation;
//! changing to the maintained codec's standard configuration would break the
//! existing syntect, two-face and user-created dump bytes.

pub(super) type Result<T> =
    std::result::Result<T, Box<dyn std::error::Error + Send + Sync + 'static>>;

#[cfg(feature = "dump-create")]
pub(super) fn serialize_into<W: std::io::Write, T: serde::Serialize>(
    mut writer: W,
    value: &T,
) -> Result<()> {
    // The maintained serde convenience writer drops its final buffer, which can
    // hide an I/O error during Drop. Explicitly flush while errors can propagate.
    let mut buffered = bincode::IoWriter::new(&mut writer);
    bincode::serde::encode_into_writer(value, &mut buffered, bincode::config::legacy())?;
    buffered.flush()?;
    Ok(())
}

#[cfg(feature = "dump-load")]
pub(super) fn deserialize_from<R: std::io::Read, T: serde::de::DeserializeOwned>(
    mut reader: R,
) -> Result<T> {
    bincode::serde::decode_from_std_read(&mut reader, bincode::config::legacy()).map_err(Into::into)
}

#[cfg(all(test, feature = "dump-create", feature = "dump-load"))]
#[path = "maintained_codec_tests.rs"]
mod tests;
