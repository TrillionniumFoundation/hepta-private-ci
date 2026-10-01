//! Selected inference retains its bounded admission window.
//! The host refreshes owner lineage, registry and stop state at every use.

use super::FinalUseErrorV1;
use super::OpaquePinnedTabularArtifactV1;
use super::OpaquePinnedWorldModelV1;
use crate::LoadedTabularOperatorV2;
use crate::TabularOperatorPredictionV1;
use crate::world_model_v2::WorldModelPredictionV2;
use crate::world_model_v2::WorldModelV2Error;
use crate::world_model_v2::predict_world_model_v2;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Instant;

#[derive(Debug)]
struct SelectionClockAnchorV1 {
    observed_at_unix_micros: u64,
    instant: Instant,
}

/// A conservative local clock; it cannot refresh owner or selector authority.
#[derive(Debug)]
pub(super) struct SelectionUseClockV1 {
    last_host_observed_at_unix_micros: AtomicU64,
    anchor: Mutex<SelectionClockAnchorV1>,
}

impl SelectionUseClockV1 {
    pub(super) fn new(selected_at: u64) -> Self {
        Self {
            last_host_observed_at_unix_micros: AtomicU64::new(selected_at),
            anchor: Mutex::new(SelectionClockAnchorV1 {
                observed_at_unix_micros: selected_at,
                instant: Instant::now(),
            }),
        }
    }

    fn observe(&self, host_now: u64) -> Result<u64, FinalUseErrorV1> {
        if host_now
            < self
                .last_host_observed_at_unix_micros
                .fetch_max(host_now, Ordering::AcqRel)
        {
            return Err(FinalUseErrorV1::ClockRegression);
        }
        let mut anchor = self
            .anchor
            .lock()
            .map_err(|_| FinalUseErrorV1::Binding("selection clock state unavailable"))?;
        let instant = Instant::now();
        let elapsed = u64::try_from(instant.duration_since(anchor.instant).as_micros())
            .map_err(|_| FinalUseErrorV1::DeadlineExceeded)?;
        let advanced = anchor
            .observed_at_unix_micros
            .checked_add(elapsed)
            .ok_or(FinalUseErrorV1::DeadlineExceeded)?;
        if host_now > advanced {
            // Only a forward host observation can move the anchor. Equal or
            // frozen host values retain elapsed time, including submicrosecond
            // fractions, rather than repeatedly resetting the monotonic origin.
            anchor.observed_at_unix_micros = host_now;
            anchor.instant = instant;
            Ok(host_now)
        } else {
            Ok(advanced)
        }
    }
}

impl OpaquePinnedTabularArtifactV1 {
    #[must_use]
    pub const fn selection_digest(&self) -> Digest32 {
        self.selection_digest
    }

    /// Load only within the selected window. The returned value retains the
    /// window and checks it again on every prediction; it exposes no raw loader.
    pub fn load(&self, now: u64) -> Result<SelectedTabularOperatorV1, FinalUseErrorV1> {
        let (loaded, _) = during_selected_window(
            self.selected_at_unix_micros,
            self.expires_at_unix_micros,
            || self.clock.observe(now),
            |_| {
                LoadedTabularOperatorV2::from_pinned_payload_v2(self.payload.as_ref(), &self.pin)
                    .map_err(Into::into)
            },
        )?;
        Ok(SelectedTabularOperatorV1 {
            loaded,
            selection_digest: self.selection_digest,
            selected_at_unix_micros: self.selected_at_unix_micros,
            expires_at_unix_micros: self.expires_at_unix_micros,
            clock: Arc::clone(&self.clock),
        })
    }
}

/// A read-only selected operator that retains its admission window.
///
/// Time checks do not observe subsequent revocation, trust rotation, registry
/// changes or stop requests. The host revalidates that state before each use.
#[derive(Debug)]
pub struct SelectedTabularOperatorV1 {
    loaded: LoadedTabularOperatorV2,
    selection_digest: Digest32,
    selected_at_unix_micros: u64,
    expires_at_unix_micros: u64,
    clock: Arc<SelectionUseClockV1>,
}

impl SelectedTabularOperatorV1 {
    #[must_use]
    pub const fn selection_digest(&self) -> Digest32 {
        self.selection_digest
    }

    pub fn predict(
        &self,
        sensor: &StableId,
        action: &StableId,
        now: u64,
    ) -> Result<TabularOperatorPredictionV1, FinalUseErrorV1> {
        let (prediction, _) = during_selected_window(
            self.selected_at_unix_micros,
            self.expires_at_unix_micros,
            || self.clock.observe(now),
            |_| self.loaded.predict(sensor, action).map_err(Into::into),
        )?;
        Ok(prediction)
    }
}

impl OpaquePinnedWorldModelV1 {
    #[must_use]
    pub const fn selection_digest(&self) -> Digest32 {
        self.selection_digest
    }

    pub fn predict(
        &self,
        state_id: &StableId,
        action_id: &StableId,
        now: u64,
    ) -> Result<WorldModelPredictionV2, FinalUseErrorV1> {
        let (prediction, finished_at) = during_selected_window(
            self.selected_at_unix_micros,
            self.expires_at_unix_micros,
            || self.clock.observe(now),
            |effective_now| {
                predict_world_model_v2(
                    &self.artifact,
                    state_id,
                    action_id,
                    &self.pin,
                    effective_now,
                )
                .map_err(Into::into)
            },
        )?;
        if finished_at > self.artifact.retained_until || finished_at > self.artifact.expires_at {
            return Err(WorldModelV2Error::Expired.into());
        }
        Ok(prediction)
    }
}

fn during_selected_window<T>(
    selected_at: u64,
    expires_at: u64,
    effective_now: impl Fn() -> Result<u64, FinalUseErrorV1>,
    operation: impl FnOnce(u64) -> Result<T, FinalUseErrorV1>,
) -> Result<(T, u64), FinalUseErrorV1> {
    let started_at = effective_now()?;
    validate_selected_window(selected_at, expires_at, started_at)?;
    let value = operation(started_at)?;
    let finished_at = effective_now()?;
    validate_selected_window(selected_at, expires_at, finished_at)?;
    Ok((value, finished_at))
}

fn validate_selected_window(
    selected_at: u64,
    expires_at: u64,
    now: u64,
) -> Result<(), FinalUseErrorV1> {
    if now < selected_at {
        return Err(FinalUseErrorV1::ClockRegression);
    }
    if now >= expires_at {
        return Err(FinalUseErrorV1::SelectionBinding(
            "selection expired at final use",
        ));
    }
    Ok(())
}

#[cfg(test)]
#[path = "final_use_selected_tests.rs"]
mod tests;
