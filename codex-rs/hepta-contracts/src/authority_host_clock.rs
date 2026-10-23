//! Linux host clock protected by the separately retained root frontier.
//! OS time and boot identity are trusted; whole-host rollback is outside scope.

use crate::AuthorityClock;
use crate::AuthorityFrontierStore;
use crate::AuthorityTrustError;
use crate::HostAuthorityFrontierStore;
use crate::RootAuthorityDirectory;
use rustix::time::ClockId;
use rustix::time::DynamicClockId;
use rustix::time::Timespec;
use rustix::time::clock_gettime_dynamic;
use serde::Deserialize;
use serde::Serialize;
use std::fs::File;
use std::io::Read;
use std::sync::Arc;
use std::sync::Mutex;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct ClockRecord {
    boot_id: String,
    boottime_ns: u64,
    unix_ns: u64,
}

struct ClockSample {
    boot_id: String,
    before_ns: u64,
    after_ns: u64,
    realtime_ns: u64,
}

/// Root-broker clock with durable time highwater, not a TPM/attestation claim.
///
/// Within a boot, CLOCK_BOOTTIME counts suspend and projects elapsed time from
/// the retained value. Realtime may move forwards, but cannot be behind an
/// already published value. Across reboot, realtime must reach that retained
/// highwater before a new boot anchor can be accepted. The original authority
/// owners receive no timestamp until its CAS and directory fsync have succeeded.
pub struct HostAuthorityClock {
    store: HostAuthorityFrontierStore<ClockRecord>,
    owner_id: String,
    serial: Mutex<()>,
}

impl HostAuthorityClock {
    /// Explicitly register a new clock. Existing registrations are never reset.
    pub fn initialize(
        root: Arc<RootAuthorityDirectory>,
        owner_id: String,
    ) -> Result<Self, AuthorityTrustError> {
        let sample = sample_os_clock()?;
        let initial = ClockRecord {
            boot_id: sample.boot_id,
            boottime_ns: sample.after_ns,
            unix_ns: sample.realtime_ns,
        };
        let store = HostAuthorityFrontierStore::initialize(root, owner_id.clone(), initial)?;
        Ok(Self {
            store,
            owner_id,
            serial: Mutex::new(()),
        })
    }

    /// Open and verify existing state against the actual running host clock.
    pub fn open(
        root: Arc<RootAuthorityDirectory>,
        owner_id: String,
    ) -> Result<Self, AuthorityTrustError> {
        let clock = Self {
            store: HostAuthorityFrontierStore::open(root, owner_id.clone())?,
            owner_id,
            serial: Mutex::new(()),
        };
        clock.now_unix_ms()?;
        Ok(clock)
    }
}

impl AuthorityClock for HostAuthorityClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        let _serial = self
            .serial
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        let previous = self.store.load(&self.owner_id)?;
        let next = project(&previous, sample_os_clock()?)?;
        self.store
            .compare_and_set(&self.owner_id, &previous, &next)?;
        Ok(next.unix_ns / 1_000_000)
    }
}

fn project(
    previous: &ClockRecord,
    sample: ClockSample,
) -> Result<ClockRecord, AuthorityTrustError> {
    if sample.after_ns < sample.before_ns || sample.realtime_ns < previous.unix_ns {
        return Err(AuthorityTrustError::Invalid);
    }
    let unix_ns = if sample.boot_id == previous.boot_id {
        let elapsed = sample
            .before_ns
            .checked_sub(previous.boottime_ns)
            .ok_or(AuthorityTrustError::Invalid)?;
        previous
            .unix_ns
            .checked_add(elapsed)
            .ok_or(AuthorityTrustError::Invalid)?
            .max(sample.realtime_ns)
    } else {
        sample.realtime_ns
    };
    Ok(ClockRecord {
        boot_id: sample.boot_id,
        boottime_ns: sample.after_ns,
        unix_ns,
    })
}

fn sample_os_clock() -> Result<ClockSample, AuthorityTrustError> {
    let mut boot_id = String::new();
    File::open("/proc/sys/kernel/random/boot_id")
        .map_err(|_| AuthorityTrustError::Unavailable)?
        .take(64)
        .read_to_string(&mut boot_id)
        .map_err(|_| AuthorityTrustError::Unavailable)?;
    let boot_id = boot_id.trim();
    if boot_id.len() != 36
        || !boot_id.bytes().enumerate().all(|(index, byte)| {
            if [8, 13, 18, 23].contains(&index) {
                byte == b'-'
            } else {
                byte.is_ascii_hexdigit()
            }
        })
    {
        return Err(AuthorityTrustError::Invalid);
    }
    let read = |id| {
        clock_gettime_dynamic(DynamicClockId::Known(id))
            .map_err(|_| AuthorityTrustError::Unavailable)
            .and_then(to_ns)
    };
    let before_ns = read(ClockId::Boottime)?;
    let realtime_ns = read(ClockId::Realtime)?;
    let after_ns = read(ClockId::Boottime)?;
    if after_ns < before_ns {
        return Err(AuthorityTrustError::Invalid);
    }
    Ok(ClockSample {
        boot_id: boot_id.to_owned(),
        before_ns,
        after_ns,
        realtime_ns,
    })
}

fn to_ns(value: Timespec) -> Result<u64, AuthorityTrustError> {
    let seconds = u64::try_from(value.tv_sec).map_err(|_| AuthorityTrustError::Invalid)?;
    let nanos = u64::try_from(value.tv_nsec).map_err(|_| AuthorityTrustError::Invalid)?;
    if nanos >= 1_000_000_000 {
        return Err(AuthorityTrustError::Invalid);
    }
    seconds
        .checked_mul(1_000_000_000)
        .and_then(|value| value.checked_add(nanos))
        .ok_or(AuthorityTrustError::Invalid)
}

#[cfg(test)]
mod tests {
    use super::*;
    use pretty_assertions::assert_eq;

    fn previous() -> ClockRecord {
        ClockRecord {
            boot_id: "first".into(),
            boottime_ns: 10,
            unix_ns: 100,
        }
    }

    fn sample(boot: &str, before_ns: u64, after_ns: u64, realtime_ns: u64) -> ClockSample {
        ClockSample {
            boot_id: boot.into(),
            before_ns,
            after_ns,
            realtime_ns,
        }
    }

    #[test]
    fn elapsed_projection_counts_suspend_and_is_persisted_conservatively() {
        assert_eq!(
            project(&previous(), sample("first", 30, 35, 110)),
            Ok(ClockRecord {
                boot_id: "first".into(),
                boottime_ns: 35,
                unix_ns: 120,
            })
        );
        assert_eq!(
            project(&previous(), sample("first", 30, 35, 150)),
            Ok(ClockRecord {
                boot_id: "first".into(),
                boottime_ns: 35,
                unix_ns: 150,
            })
        );
    }

    #[test]
    fn rollback_and_uncertain_samples_are_refused() {
        for sample in [
            sample("first", 9, 20, 110),
            sample("first", 20, 19, 110),
            sample("first", 20, 21, 99),
            sample("second", 1, 2, 99),
        ] {
            assert_eq!(
                project(&previous(), sample),
                Err(AuthorityTrustError::Invalid)
            );
        }
        let previous = ClockRecord {
            unix_ns: u64::MAX,
            ..previous()
        };
        assert_eq!(
            project(&previous, sample("first", 11, 12, u64::MAX)),
            Err(AuthorityTrustError::Invalid)
        );
    }

    #[test]
    fn a_reboot_requires_wall_clock_at_or_above_retained_highwater() {
        assert_eq!(
            project(&previous(), sample("second", 1, 2, 100)),
            Ok(ClockRecord {
                boot_id: "second".into(),
                boottime_ns: 2,
                unix_ns: 100,
            })
        );
    }

    #[test]
    fn actual_os_sample_is_bounded_and_ordered() {
        let sample = sample_os_clock().unwrap();
        assert!(sample.after_ns >= sample.before_ns);
        assert!(sample.realtime_ns > 0);
    }
}
