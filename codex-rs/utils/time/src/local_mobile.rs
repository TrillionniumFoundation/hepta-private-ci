//! Read a named TZif entry from the Android or OpenHarmony system database.
//!
//! The database has a 24-byte header and 40-byte names followed by a relative
//! offset and length. Android retains one additional legacy-offset field.

use std::io;
#[cfg(target_os = "android")]
use std::io::Read;

#[cfg(any(target_os = "android", target_env = "ohos"))]
pub(super) fn read_zone(name: &str) -> io::Result<Vec<u8>> {
    #[cfg(target_env = "ohos")]
    let (bytes, width) = (std::fs::read("/system/etc/zoneinfo/tzdata")?, 48);
    #[cfg(target_os = "android")]
    let (bytes, width) = {
        let mut file = [
            ("ANDROID_TZDATA_ROOT", "/etc/tz/tzdata"),
            ("ANDROID_DATA", "/misc/zoneinfo/current/tzdata"),
            ("ANDROID_ROOT", "/usr/share/zoneinfo/tzdata"),
        ]
        .into_iter()
        .find_map(|(variable, suffix)| {
            std::env::var(variable)
                .ok()
                .and_then(|root| std::fs::File::open(format!("{root}{suffix}")).ok())
        })
        .ok_or(io::ErrorKind::NotFound)?;
        let mut bytes = Vec::new();
        file.read_to_end(&mut bytes)?;
        (bytes, 52)
    };
    find_zone(&bytes, width, name.as_bytes())?.ok_or_else(|| io::ErrorKind::NotFound.into())
}

fn find_zone(bytes: &[u8], width: usize, name: &[u8]) -> io::Result<Option<Vec<u8>>> {
    let invalid = || io::Error::from(io::ErrorKind::InvalidData);
    let header = bytes.get(..24).ok_or_else(invalid)?;
    if !header.starts_with(b"tzdata") || header[11] != 0 || !matches!(width, 48 | 52) {
        return Err(invalid());
    }
    let index_start =
        u32::from_be_bytes(header[12..16].try_into().map_err(|_| invalid())?) as usize;
    let data_start = u32::from_be_bytes(header[16..20].try_into().map_err(|_| invalid())?) as usize;
    if index_start < 24 || data_start < index_start {
        return Err(invalid());
    }
    let index = bytes.get(index_start..data_start).ok_or_else(invalid)?;
    if index.len() % width != 0 {
        return Err(invalid());
    }
    for entry in index.chunks_exact(width) {
        let Some(end) = entry[..40].iter().position(|&byte| byte == 0) else {
            continue;
        };
        if &entry[..end] != name {
            continue;
        }
        let offset = u32::from_be_bytes(entry[40..44].try_into().map_err(|_| invalid())?) as usize;
        let length = u32::from_be_bytes(entry[44..48].try_into().map_err(|_| invalid())?) as usize;
        let start = data_start.checked_add(offset).ok_or_else(invalid)?;
        let end = start.checked_add(length).ok_or_else(invalid)?;
        return bytes
            .get(start..end)
            .map(|entry| Some(entry.to_vec()))
            .ok_or_else(invalid);
    }
    Ok(None)
}

#[cfg(test)]
#[path = "local_mobile_tests.rs"]
mod tests;
