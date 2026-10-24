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

const HORIZON_NS: u64 = 1_000_000_000;
const MAX_SAMPLE_SPAN_NS: u64 = 10_000_000;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct ClockRecord {
    boot_id: String,
    boottime_ns: u64,
    unix_ns: u64,
    wall_ns: u64,
    ceiling_ns: u64,
}

struct ClockSample {
    boot_id: String,
    before_ns: u64,
    after_ns: u64,
    realtime_ns: u64,
}

/// Public read-only projection, containing no signing material or grant.
/// `ceiling_unix_ms` is a durable upper bound, never a current timestamp. A
/// receiver must match the actual Linux boot ID, project elapsed BOOTTIME from
/// the anchor, and refuse observations beyond this ceiling. Feed freshness and
/// revocation-head/authority-epoch binding remain the host loader's responsibility.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostAuthorityClockProjection {
    pub schema_version: u32,
    pub boot_id: String,
    pub anchor_boottime_ns: u64,
    pub anchor_unix_ms: u64,
    pub ceiling_unix_ms: u64,
}

/// An actual post-I/O clock reading within its already durable projection.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HostAuthorityClockObservation {
    pub projection: HostAuthorityClockProjection,
    pub observed_unix_ms: u64,
}

/// Root-broker clock with durable time highwater, not a TPM/attestation claim.
///
/// Within a boot, CLOCK_BOOTTIME counts suspend and projects elapsed time from
/// the retained value. Realtime may move forwards, but cannot be behind an
/// retained anchor. Across reboot, realtime must reach the previous durable
/// ceiling, which bounds all values previously returned. A fixed one-second
/// horizon is persisted before publication. Time is sampled again after CAS
/// and fsync; slow I/O cannot return the earlier pre-I/O timestamp.
pub struct HostAuthorityClock {
    store: Arc<dyn AuthorityFrontierStore<ClockRecord>>,
    owner_id: String,
    serial: Mutex<()>,
}

impl HostAuthorityClock {
    /// Explicitly register a new clock. Existing registrations are never reset.
    pub fn initialize(
        root: Arc<RootAuthorityDirectory>,
        owner_id: String,
    ) -> Result<Self, AuthorityTrustError> {
        #[cfg(debug_assertions)]
        let mut timing = ClockPhaseTiming::new("initialize");
        #[cfg(debug_assertions)]
        timing.stage("initial_os_sample_enter");
        let initial = initial_record(sample_os_clock()?)?;
        #[cfg(debug_assertions)]
        timing.stage("initial_record_complete");
        let store = Arc::new(HostAuthorityFrontierStore::initialize(
            root,
            owner_id.clone(),
            initial.clone(),
        )?);
        #[cfg(debug_assertions)]
        timing.stage("frontier_initialize_complete");
        let observed_sample = sample_os_clock()?;
        #[cfg(debug_assertions)]
        timing.stage("post_io_os_sample_complete");
        #[cfg(debug_assertions)]
        let diagnostic = ClockInitializationObservation::capture(&initial, &observed_sample);
        let observed = observe_after_io(&initial, observed_sample);
        #[cfg(debug_assertions)]
        {
            if let Err(error) = &observed {
                diagnostic.rejected(error);
            }
            timing.finish(observed.is_ok());
        }
        observed?;
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
            store: Arc::new(HostAuthorityFrontierStore::open(root, owner_id.clone())?),
            owner_id,
            serial: Mutex::new(()),
        };
        clock.now_unix_ms()?;
        Ok(clock)
    }

    /// Renew one bounded observation window and return a post-durability
    /// sample plus its public projection. No future ceiling is returned as now.
    pub fn refresh_projection(&self) -> Result<HostAuthorityClockObservation, AuthorityTrustError> {
        #[cfg(debug_assertions)]
        let mut timing = ClockPhaseTiming::new("refresh_projection");
        let _serial = self
            .serial
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        #[cfg(debug_assertions)]
        timing.stage("clock_serial_acquired");
        let previous = self.store.load(&self.owner_id)?;
        #[cfg(debug_assertions)]
        timing.stage("durable_clock_loaded");
        let result = self.renew_after_load(&previous);
        #[cfg(debug_assertions)]
        timing.finish(result.is_ok());
        result
    }

    fn renew_after_load(
        &self,
        previous: &ClockRecord,
    ) -> Result<HostAuthorityClockObservation, AuthorityTrustError> {
        #[cfg(debug_assertions)]
        let mut timing = ClockPhaseTiming::new("renew_after_load");
        let next = project(previous, sample_os_clock()?)?;
        #[cfg(debug_assertions)]
        timing.stage("fresh_clock_projected");
        self.store
            .compare_and_set(&self.owner_id, previous, &next)?;
        #[cfg(debug_assertions)]
        timing.stage("durable_clock_cas_finished");
        let result = observe_after_io(&next, sample_os_clock()?);
        #[cfg(debug_assertions)]
        timing.finish(result.is_ok());
        result
    }
}

impl AuthorityClock for HostAuthorityClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        #[cfg(debug_assertions)]
        let mut timing = ClockPhaseTiming::new("now_unix_ms");
        let _serial = self
            .serial
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        #[cfg(debug_assertions)]
        timing.stage("clock_serial_acquired");
        // Read the complete protected record on every call. Its already durable
        // ceiling bounds actual post-I/O time; it is never returned as "now".
        let previous = self.store.load(&self.owner_id)?;
        #[cfg(debug_assertions)]
        timing.stage("durable_clock_loaded");
        let result = match observe_after_io(&previous, sample_os_clock()?) {
            Ok(observation) => Ok(observation.observed_unix_ms),
            Err(AuthorityTrustError::Unavailable) => {
                // Expiry, a forward wall step or a legal reboot needs the same
                // original durable renewal and post-CAS check. Invalid state
                // is never repaired, retried or replaced by genesis.
                Ok(self.renew_after_load(&previous)?.observed_unix_ms)
            }
            Err(error) => Err(error),
        };
        #[cfg(debug_assertions)]
        timing.finish(result.is_ok());
        result
    }
}

fn initial_record(sample: ClockSample) -> Result<ClockRecord, AuthorityTrustError> {
    Ok(ClockRecord {
        boot_id: sample.boot_id,
        boottime_ns: sample.before_ns,
        unix_ns: sample.realtime_ns,
        wall_ns: sample.realtime_ns,
        ceiling_ns: sample
            .realtime_ns
            .checked_add(HORIZON_NS)
            .ok_or(AuthorityTrustError::Invalid)?,
    })
}

fn observe_after_io(
    durable: &ClockRecord,
    sample: ClockSample,
) -> Result<HostAuthorityClockObservation, AuthorityTrustError> {
    if sample.boot_id != durable.boot_id {
        return Err(AuthorityTrustError::Unavailable);
    }
    let after_ns = sample.after_ns;
    let realtime_ns = sample.realtime_ns;
    // Validate the sampled wall highwater and BOOTTIME first. The wall sample
    // occurs between before/after; anchoring it at before is a conservative
    // upper projection, so time cannot move backwards on anchor replacement.
    project(durable, sample)?;
    let actual = durable
        .unix_ns
        .checked_add(
            after_ns
                .checked_sub(durable.boottime_ns)
                .ok_or(AuthorityTrustError::Invalid)?,
        )
        .ok_or(AuthorityTrustError::Invalid)?;
    if realtime_ns > actual {
        // A wall-clock step during I/O needs a new durable anchor. Do not
        // publish a projection that trails the newly sampled wall time.
        return Err(AuthorityTrustError::Unavailable);
    }
    if actual > durable.ceiling_ns {
        return Err(AuthorityTrustError::Unavailable);
    }
    Ok(HostAuthorityClockObservation {
        projection: HostAuthorityClockProjection {
            schema_version: 1,
            boot_id: durable.boot_id.clone(),
            // Keep the exact sub-ms phase when exposing an integer Unix-ms
            // anchor. Separately flooring Unix and elapsed time can make a
            // replacement projection appear to go backwards by one ms.
            anchor_boottime_ns: durable
                .boottime_ns
                .checked_sub(durable.unix_ns % 1_000_000)
                .ok_or(AuthorityTrustError::Invalid)?,
            anchor_unix_ms: durable.unix_ns / 1_000_000,
            ceiling_unix_ms: durable.ceiling_ns / 1_000_000,
        },
        observed_unix_ms: actual / 1_000_000,
    })
}

fn project(
    previous: &ClockRecord,
    sample: ClockSample,
) -> Result<ClockRecord, AuthorityTrustError> {
    if sample.after_ns < sample.before_ns
        || sample.after_ns - sample.before_ns > MAX_SAMPLE_SPAN_NS
        || previous.unix_ns.checked_add(HORIZON_NS) != Some(previous.ceiling_ns)
        || previous.wall_ns == 0
        || previous.wall_ns > previous.unix_ns
        || sample.realtime_ns < previous.wall_ns
    {
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
        // The ceiling is only a reboot rollback bound. During the same boot,
        // comparing realtime to this future bound would reject normal clocks.
        if sample.realtime_ns < previous.ceiling_ns {
            return Err(AuthorityTrustError::Invalid);
        }
        sample.realtime_ns
    };
    Ok(ClockRecord {
        boot_id: sample.boot_id,
        boottime_ns: sample.before_ns,
        unix_ns,
        wall_ns: sample.realtime_ns,
        ceiling_ns: unix_ns
            .checked_add(HORIZON_NS)
            .ok_or(AuthorityTrustError::Invalid)?,
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
    if after_ns < before_ns || after_ns - before_ns > MAX_SAMPLE_SPAN_NS {
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
#[path = "authority_host_clock_slow_tests.rs"]
mod slow_tests;

#[cfg(debug_assertions)]
struct ClockPhaseTiming {
    phase: &'static str,
    started: std::time::Instant,
    started_unix_us: Option<u128>,
    thread: std::thread::ThreadId,
    stages: Vec<(&'static str, u128)>,
    success: Option<bool>,
}

#[cfg(debug_assertions)]
impl ClockPhaseTiming {
    fn new(phase: &'static str) -> Self {
        Self {
            phase,
            started: std::time::Instant::now(),
            started_unix_us: std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .ok()
                .map(|value| value.as_micros()),
            thread: std::thread::current().id(),
            stages: Vec::new(),
            success: None,
        }
    }
    fn stage(&mut self, stage: &'static str) {
        self.stages
            .push((stage, self.started.elapsed().as_micros()));
    }
    fn finish(&mut self, success: bool) {
        self.stage("return");
        self.success = Some(success);
    }
}

#[cfg(debug_assertions)]
impl Drop for ClockPhaseTiming {
    fn drop(&mut self) {
        let elapsed_us = self.started.elapsed().as_micros();
        if elapsed_us >= 100_000 || self.success != Some(true) {
            eprintln!(
                "HEPTA_ROOT_CLOCK_PHASE_V1 phase={} thread={:?} started_unix_us={:?} elapsed_us={} success={:?} stages={:?}",
                self.phase,
                self.thread,
                self.started_unix_us,
                elapsed_us,
                self.success,
                self.stages
            );
        }
    }
}

// Diagnostic values are copied from the two original samples, without taking
// another authority-clock sample, performing I/O or changing any return path.
// Only relative durations/booleans are printed; this is never a clock proof.
#[cfg(debug_assertions)]
struct ClockInitializationObservation {
    same_boot: bool,
    sample_span_ns: Option<u64>,
    elapsed_since_anchor_ns: Option<u64>,
    horizon_ns: Option<u64>,
    wall_ahead_of_projection_ns: Option<i128>,
    projection_past_ceiling_ns: Option<i128>,
}

#[cfg(debug_assertions)]
impl ClockInitializationObservation {
    fn capture(durable: &ClockRecord, sample: &ClockSample) -> Self {
        let elapsed = sample.after_ns.checked_sub(durable.boottime_ns);
        let projected = elapsed.and_then(|elapsed| durable.unix_ns.checked_add(elapsed));
        Self {
            same_boot: sample.boot_id == durable.boot_id,
            sample_span_ns: sample.after_ns.checked_sub(sample.before_ns),
            elapsed_since_anchor_ns: elapsed,
            horizon_ns: durable.ceiling_ns.checked_sub(durable.unix_ns),
            wall_ahead_of_projection_ns: projected
                .map(|actual| i128::from(sample.realtime_ns) - i128::from(actual)),
            projection_past_ceiling_ns: projected
                .map(|actual| i128::from(actual) - i128::from(durable.ceiling_ns)),
        }
    }

    fn rejected(&self, error: &AuthorityTrustError) {
        // Classify only the already returned error. The original observer
        // remains authoritative, including its preceding Invalid checks.
        let class = if !matches!(error, AuthorityTrustError::Unavailable) {
            "original_non_unavailable_error"
        } else if !self.same_boot {
            "boot_changed"
        } else if self.wall_ahead_of_projection_ns.is_some_and(|gap| gap > 0) {
            "wall_ahead_of_durable_projection"
        } else if self.projection_past_ceiling_ns.is_some_and(|gap| gap > 0) {
            "durable_one_second_horizon_elapsed"
        } else {
            "unclassified_original_unavailable"
        };
        eprintln!(
            "HEPTA_ROOT_CLOCK_INITIAL_OBSERVATION_V1 error={error:?} class={class} same_boot={} sample_span_ns={:?} elapsed_since_anchor_ns={:?} horizon_ns={:?} wall_ahead_of_projection_ns={:?} projection_past_ceiling_ns={:?}",
            self.same_boot,
            self.sample_span_ns,
            self.elapsed_since_anchor_ns,
            self.horizon_ns,
            self.wall_ahead_of_projection_ns,
            self.projection_past_ceiling_ns,
        );
    }
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
            wall_ns: 100,
            ceiling_ns: 100 + HORIZON_NS,
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
                boottime_ns: 30,
                unix_ns: 120,
                wall_ns: 110,
                ceiling_ns: 120 + HORIZON_NS,
            })
        );
        assert_eq!(
            project(&previous(), sample("first", 30, 35, 150)),
            Ok(ClockRecord {
                boot_id: "first".into(),
                boottime_ns: 30,
                unix_ns: 150,
                wall_ns: 150,
                ceiling_ns: 150 + HORIZON_NS,
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
            project(&previous(), sample("second", 1, 2, HORIZON_NS + 99)),
            Err(AuthorityTrustError::Invalid)
        );
        assert_eq!(
            project(&previous(), sample("second", 1, 2, HORIZON_NS + 100)),
            Ok(ClockRecord {
                boot_id: "second".into(),
                boottime_ns: 1,
                unix_ns: HORIZON_NS + 100,
                wall_ns: HORIZON_NS + 100,
                ceiling_ns: 2 * HORIZON_NS + 100,
            })
        );
    }

    #[test]
    fn post_io_observation_uses_actual_sample_and_never_publishes_a_ceiling_as_now() {
        let durable = ClockRecord {
            boot_id: "first".into(),
            boottime_ns: 10_000_000,
            unix_ns: 10_000_000_000,
            wall_ns: 10_000_000_000,
            ceiling_ns: 11_000_000_000,
        };
        let observed = observe_after_io(
            &durable,
            sample("first", 20_000_000, 21_000_000, 10_010_000_000),
        )
        .unwrap();
        assert_eq!(
            observed,
            HostAuthorityClockObservation {
                projection: HostAuthorityClockProjection {
                    schema_version: 1,
                    boot_id: "first".into(),
                    anchor_boottime_ns: 10_000_000,
                    anchor_unix_ms: 10_000,
                    ceiling_unix_ms: 11_000
                },
                observed_unix_ms: 10_011,
            }
        );
        assert_eq!(
            observe_after_io(
                &durable,
                sample("first", 1_020_000_000, 1_021_000_000, 11_010_000_000)
            ),
            Err(AuthorityTrustError::Unavailable)
        );
        assert_eq!(
            observe_after_io(&durable, sample("second", 1, 2, 12_000_000_000)),
            Err(AuthorityTrustError::Unavailable)
        );
    }

    #[test]
    fn actual_os_sample_is_bounded_and_ordered() {
        let sample = sample_os_clock().unwrap();
        assert!(sample.after_ns >= sample.before_ns);
        assert!(sample.realtime_ns > 0);
    }

    #[test]
    fn post_io_forward_step_is_not_published_with_an_old_mapping() {
        let durable = ClockRecord {
            boot_id: "same-boot".into(),
            boottime_ns: 100_000_000,
            unix_ns: 10_000_000_000,
            wall_ns: 10_000_000_000,
            ceiling_ns: 11_000_000_000,
        };
        assert_eq!(
            observe_after_io(
                &durable,
                sample("same-boot", 110_000_000, 110_100_000, 10_900_000_000)
            ),
            Err(AuthorityTrustError::Unavailable)
        );
        // A higher mapping can only be published after it is first committed
        // by CAS. Returning from that durable mapping then binds all reopened
        // clocks, including if wall time falls within the original old anchor.
        let advanced = project(
            &durable,
            sample("same-boot", 110_000_000, 110_100_000, 10_900_000_000),
        )
        .unwrap();
        let observed = observe_after_io(
            &advanced,
            sample("same-boot", 115_000_000, 115_100_000, 10_905_000_000),
        )
        .unwrap();
        assert_eq!(observed.observed_unix_ms, 10_905);
        let from_projection = observed.projection.anchor_unix_ms
            + (115_100_000 - observed.projection.anchor_boottime_ns) / 1_000_000;
        assert_eq!(from_projection, observed.observed_unix_ms);
        assert_eq!(
            project(
                &advanced,
                sample("same-boot", 120_000_000, 120_100_000, 10_050_000_000)
            ),
            Err(AuthorityTrustError::Invalid)
        );
    }

    #[test]
    fn replacement_projection_keeps_submillisecond_phase_and_never_moves_backwards() {
        let durable = ClockRecord {
            boot_id: "same-boot".into(),
            boottime_ns: 10_000_000,
            unix_ns: 10_000_000_025,
            wall_ns: 10_000_000_000,
            ceiling_ns: 11_000_000_025,
        };
        let old = observe_after_io(
            &durable,
            sample("same-boot", 11_000_000, 11_000_000, 10_001_000_000),
        )
        .unwrap()
        .projection;
        let replacement = project(
            &durable,
            sample("same-boot", 11_333_333, 11_333_334, 10_001_333_333),
        )
        .unwrap();
        let new = observe_after_io(
            &replacement,
            sample("same-boot", 12_000_000, 12_000_000, 10_002_000_000),
        )
        .unwrap()
        .projection;
        for boot in [12_000_000, 12_333_333, 12_999_999, 15_333_333] {
            let old_now = old.anchor_unix_ms + (boot - old.anchor_boottime_ns) / 1_000_000;
            let new_now = new.anchor_unix_ms + (boot - new.anchor_boottime_ns) / 1_000_000;
            assert_eq!(new_now, old_now);
        }
    }
}
