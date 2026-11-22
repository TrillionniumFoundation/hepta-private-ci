//! One-component NT names, shared with the original State recovery admission.

use std::ffi::OsStr;
use std::io;
use std::os::windows::ffi::OsStrExt;

/// Validate one ordinary child name, returning only its UTF-16 data.
///
/// This supplies no filesystem authority. Separators, ADS, device names, dot
/// components, trailing aliases and overlong NT names are always refused.
pub fn validate_private_windows_child_name(name: &OsStr) -> io::Result<Vec<u16>> {
    let units: Vec<_> = name.encode_wide().collect();
    let base = name
        .to_string_lossy()
        .split('.')
        .next()
        .unwrap_or_default()
        .to_ascii_uppercase();
    let reserved = matches!(base.as_str(), "CON" | "PRN" | "AUX" | "NUL" | "CLOCK$")
        || base
            .strip_prefix("COM")
            .or_else(|| base.strip_prefix("LPT"))
            .is_some_and(|suffix| {
                matches!(suffix.as_bytes(), [b'1'..=b'9']) || matches!(suffix, "¹" | "²" | "³")
            });
    if reserved
        || units.is_empty()
        || units.iter().any(|unit| matches!(*unit, 0 | 47 | 58 | 92))
        || units == [46]
        || units == [46, 46]
        || matches!(units.last(), Some(32 | 46))
        || units.len() > (u16::MAX as usize / 2)
    {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "invalid private Windows child name",
        ));
    }
    Ok(units)
}
