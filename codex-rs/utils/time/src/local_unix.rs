//! TZ discovery and invalidation retain the former Local configuration policy.

use super::LocalTimeError;
use crate::Timestamp;
use std::cell::RefCell;
use std::collections::hash_map::DefaultHasher;
use std::env;
use std::fs;
use std::hash::Hasher;
use std::io::Read;
use std::time::SystemTime;
use zone::ConfigurationError;
use zone::Zone;

#[path = "local_posix_compat.rs"]
mod compatibility;
#[path = "local_zone.rs"]
mod zone;

#[cfg(any(target_os = "android", target_env = "ohos", test))]
#[path = "local_mobile.rs"]
mod mobile;

thread_local! {
    static CACHE: RefCell<Option<Cache>> = const { RefCell::new(None) };
}

#[derive(Eq, PartialEq)]
enum Source {
    Environment(u64),
    LocalFile(SystemTime),
}

impl Source {
    fn read(value: Option<&str>) -> Self {
        match value {
            Some(value) => {
                let mut hash = DefaultHasher::new();
                hash.write(value.as_bytes());
                Self::Environment(hash.finish())
            }
            None => Self::LocalFile(
                fs::symlink_metadata("/etc/localtime")
                    .and_then(|metadata| metadata.modified())
                    .unwrap_or_else(|_| SystemTime::now()),
            ),
        }
    }
}

struct Cache {
    zone: Result<Zone, LocalTimeError>,
    source: Source,
    checked: SystemTime,
}

impl Cache {
    fn new() -> Self {
        let value = env::var("TZ").ok();
        Self {
            checked: SystemTime::now(),
            source: Source::read(value.as_deref()),
            zone: discover(value.as_deref()),
        }
    }

    fn offset(&mut self, seconds: i64) -> Result<i32, LocalTimeError> {
        let now = SystemTime::now();
        if !matches!(now.duration_since(self.checked), Ok(age) if age.as_secs() < 1) {
            let value = env::var("TZ").ok();
            let source = Source::read(value.as_deref());
            if source != self.source {
                self.zone = discover(value.as_deref());
            }
            self.checked = now;
            self.source = source;
        }
        let zone = self.zone.as_ref().map_err(|error| *error)?;
        zone.offset(seconds)
    }
}

pub(super) fn offset(value: Timestamp) -> Result<i32, LocalTimeError> {
    CACHE.with(|cache| {
        cache
            .borrow_mut()
            .get_or_insert_with(Cache::new)
            .offset(value.seconds)
    })
}

fn discover(value: Option<&str>) -> Result<Zone, LocalTimeError> {
    match configured_zone(value) {
        Ok(zone) => return Ok(zone),
        Err(ConfigurationError::Compatibility) => {
            return Err(LocalTimeError::UnsupportedConfiguration);
        }
        Err(ConfigurationError::Invalid) => {}
    }
    // Only discovery and historically invalid configuration retry IANA then UTC.
    // A selected zone's query/range/offset errors are handled after discovery.
    if let Ok(name) = iana_time_zone::get_timezone() {
        #[cfg(not(any(target_os = "android", target_env = "ohos")))]
        let bytes = {
            #[cfg(target_os = "aix")]
            let directory = "/usr/share/lib/zoneinfo";
            #[cfg(not(target_os = "aix"))]
            let directory = "/usr/share/zoneinfo";
            fs::read(format!("{directory}/{name}"))
        };
        #[cfg(any(target_os = "android", target_env = "ohos"))]
        let bytes = mobile::read_zone(&name);
        if let Ok(bytes) = bytes {
            match Zone::tzif(&bytes) {
                Ok(zone) => return Ok(zone),
                Err(ConfigurationError::Compatibility) => {
                    return Err(LocalTimeError::UnsupportedConfiguration);
                }
                Err(ConfigurationError::Invalid) => {}
            }
        }
    }
    Ok(Zone::utc())
}

fn configured_zone(value: Option<&str>) -> Result<Zone, ConfigurationError> {
    let value = value.unwrap_or("localtime");
    if value.is_empty() {
        return Ok(Zone::utc());
    }
    if value == "localtime" {
        return Zone::tzif(&fs::read("/etc/localtime").map_err(|_| ConfigurationError::Invalid)?);
    }
    #[cfg(any(target_os = "android", target_env = "ohos"))]
    if let Ok(bytes) = mobile::read_zone(value) {
        return Zone::tzif(&bytes);
    }
    if let Some(path) = value.strip_prefix(':') {
        let bytes = read_zone_file(path)
            .map_err(|_| ConfigurationError::Invalid)?
            .ok_or(ConfigurationError::Invalid)?;
        return Zone::tzif(&bytes);
    }
    match read_zone_file(value) {
        Ok(Some(bytes)) => Zone::tzif(&bytes),
        Ok(None) => {
            Zone::posix(value.trim_matches(|character: char| character.is_ascii_whitespace()))
        }
        Err(_) => Err(ConfigurationError::Invalid),
    }
}

fn read_zone_file(value: &str) -> std::io::Result<Option<Vec<u8>>> {
    let path = std::path::Path::new(value);
    let file = if path.is_absolute() {
        fs::File::open(path).ok()
    } else {
        [
            "/usr/share/zoneinfo",
            "/share/zoneinfo",
            "/etc/zoneinfo",
            "/usr/share/lib/zoneinfo",
        ]
        .into_iter()
        .find_map(|directory| fs::File::open(std::path::Path::new(directory).join(path)).ok())
    };
    let Some(mut file) = file else {
        return Ok(None);
    };
    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes)?;
    Ok(Some(bytes))
}

#[cfg(test)]
#[path = "local_unix_tests.rs"]
mod tests;
