//! Only real emitted media or real late source audio can complete an owner decision.
use super::*;
impl Controller {
    pub(super) fn observe(
        &mut self,
        request: String,
        decision: String,
        action: usize,
        path: String,
        sha: String,
    ) -> Result<Value> {
        if self.history.pending.as_ref() != Some(&(request.clone(), decision.clone(), action)) {
            return Err("Outcome does not match pending decision".into());
        }
        let r: Value = serde_json::from_slice(&checked(&path, &sha)?)?;
        if r["schema"] != "hepta.advance.actual-outcome.v1"
            || r["request_id"] != request
            || r["decision_digest"] != decision
            || r["action"].as_u64() != Some(action as u64)
            || r["observer_sha256"] != self.spec.observer_sha256
            || r["private_truth_utility_supplied"] != false
            || r.get("target").is_some()
            || r.get("scores").is_some()
            || r["generation_started_ns"]
                .as_u64()
                .is_none_or(|t| t <= r["decision_received_ns"].as_u64().unwrap_or(u64::MAX))
            || r["observed_ns"]
                .as_u64()
                .is_none_or(|t| t <= r["generation_started_ns"].as_u64().unwrap_or(u64::MAX))
        {
            return Err("Actual outcome identity, visibility or causal order rejected".into());
        }
        let utility = r["utility_q32"]
            .as_i64()
            .ok_or("Missing observed public utility")?;
        if !(-(1_i64 << 32)..=(1_i64 << 32)).contains(&utility) {
            return Err("Unbounded observed context".into());
        }
        let (label, physical) = if action == control::ACQUIRE {
            if r["evidence_origin"] != "external_source_audio"
                || r["target_supplied"] != false
                || r["source_group_id"] != self.spec.source_group_id
            {
                return Err("Acquisition must be genuine external evidence for same source".into());
            }
            let label = r["external_audio_label"]
                .as_u64()
                .ok_or("Missing actual source CNN pair label")?;
            if label >= 100 {
                return Err("Invalid source observation class".into());
            }
            let paths = r["source_wav_paths"]
                .as_array()
                .ok_or("Missing two actual source WAVs")?;
            let hashes = r["source_wav_sha256"]
                .as_array()
                .ok_or("Missing source WAV identities")?;
            if paths.len() != 2 || hashes.len() != 2 {
                return Err("Two actual source words required".into());
            }
            for i in 0..2 {
                let bytes = media_receipt::checked(
                    paths[i].as_str().ok_or("Invalid WAV path")?,
                    hashes[i].as_str().ok_or("Invalid WAV hash")?,
                )?;
                if bytes.get(..4) != Some(b"RIFF") || bytes.get(8..12) != Some(b"WAVE") {
                    return Err("External source is not actual WAV".into());
                }
            }
            (
                Some(label),
                json!({"native_source_WAV_hashes_checked":2,"source_CNN_execution":"pinned target-free host observer"}),
            )
        } else if action < 100 {
            if r["evidence_origin"] != "own_generated_output" || r["target_belief_updated"] != false
            {
                return Err("Own output cannot supply hidden-target evidence".into());
            }
            (None, media_receipt::validate(&r)?)
        } else {
            return Err("No actual current bundle exists for stop".into());
        };
        let modulator = plasticity_modulator_digest_v1(
            self.scope.objective_digest,
            self.scope.scope_digest,
            &[FixedQ32::from_raw(utility)],
        )?;
        let identity: Digest32 = sha.parse()?;
        self.transition_started = true;
        self.ndu.append_projection(
            NduProjectionKindV1::Utility,
            identity,
            self.scope.objective_digest,
            self.scope.scope_digest,
            modulator,
        )?;
        self.ndu.select_projection(
            Digest32::of_bytes(format!("select:{identity}").as_bytes()),
            self.scope.objective_digest,
            self.scope.scope_digest,
            modulator,
        )?;
        self.history.modulator = modulator;
        self.history.utility_q32 = utility;
        let d=self.append(json!({"kind":"outcome","request_id":request,"decision_digest":decision,"observation_sha256":sha,
            "external_audio_label":label,"completed":action!=control::ACQUIRE,"physical_validation":physical,
            "numeric_context_consumed_on_next_tick":self.spec.numeric_modulation,"truth_belief_update_from_own_output":false}))?;
        Ok(json!({"outcome_digest":d.to_string(),"status":self.status()?}))
    }
}
