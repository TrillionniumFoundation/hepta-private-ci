//! Selected inference retains its bounded admission window.
//! The host refreshes owner lineage, registry and stop state at every use.

use super::FinalUseErrorV1;
use super::OpaquePinnedTabularArtifactV1;
use super::OpaquePinnedWorldModelV1;
use crate::LoadedTabularOperatorV2;
use crate::TabularOperatorPredictionV1;
use crate::world_model_v2::WorldModelPredictionV2;
use crate::world_model_v2::predict_world_model_v2;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

impl OpaquePinnedTabularArtifactV1 {
    #[must_use]
    pub const fn selection_digest(&self) -> Digest32 {
        self.selection_digest
    }

    /// Load only within the selected window. The returned value retains the
    /// window and checks it again on every prediction; it exposes no raw loader.
    pub fn load(&self, now: u64) -> Result<SelectedTabularOperatorV1, FinalUseErrorV1> {
        validate_selected_window(
            self.selected_at_unix_micros,
            self.expires_at_unix_micros,
            now,
        )?;
        let loaded =
            LoadedTabularOperatorV2::from_pinned_payload_v2(self.payload.as_ref(), &self.pin)?;
        Ok(SelectedTabularOperatorV1 {
            loaded,
            selection_digest: self.selection_digest,
            selected_at_unix_micros: self.selected_at_unix_micros,
            expires_at_unix_micros: self.expires_at_unix_micros,
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
        validate_selected_window(
            self.selected_at_unix_micros,
            self.expires_at_unix_micros,
            now,
        )?;
        self.loaded.predict(sensor, action).map_err(Into::into)
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
        validate_selected_window(
            self.selected_at_unix_micros,
            self.expires_at_unix_micros,
            now,
        )?;
        predict_world_model_v2(&self.artifact, state_id, action_id, &self.pin, now)
            .map_err(Into::into)
    }
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
