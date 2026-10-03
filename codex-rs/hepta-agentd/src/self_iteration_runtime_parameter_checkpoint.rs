//! Pure same-Round command; the original mutex remains held until this read
//! actually retires, even if its reply receiver disappears.
use super::*;
use codex_hepta_agent_components::neuron::MAX_NEURON_GENERATION_MATERIAL_BYTES_V2;
use codex_hepta_agent_components::neuron::decode_neuron_generation_material_v2;
impl AgentdSelfIterationHandleV1 {
    pub(crate) async fn inspect_parameter_serving_scope(
        &self,
        host: Arc<crate::AgentdNeuronRuntimeV2Host>,
        round: AgentdSelfIterationRoundV1,
    ) -> Result<crate::ParameterServingScopeV1, AgentdError> {
        let (response, receive) = oneshot::channel();
        self.send(
            Command::InspectParameterServingScope(host, round, response),
            receive,
        )
        .await
    }
    pub(crate) async fn prepare_parameter_checkpoint(
        &self,
        host: Arc<crate::AgentdNeuronRuntimeV2Host>,
        round: AgentdSelfIterationRoundV1,
        path: PathBuf,
        pin: Digest32,
    ) -> Result<crate::PreparedParameterCheckpointV1, AgentdError> {
        let (response, receive) = oneshot::channel();
        self.send(
            Command::PrepareParameterCheckpoint(host, round, path, pin, response),
            receive,
        )
        .await
    }
}
impl SelfIterationOwner {
    fn check_parameter_round(
        &self,
        host: &Arc<crate::AgentdNeuronRuntimeV2Host>,
        round: &AgentdSelfIterationRoundV1,
    ) -> Result<u64, AgentdError> {
        if !Arc::ptr_eq(host, &self.host) || self.cancellation.is_cancelled() {
            return Err(invalid("checkpoint requires same held Neuron owner"));
        }
        let view = self
            .inspect_current_round()?
            .ok_or_else(|| invalid("checkpoint needs original Round"))?;
        if view.status.terminal
            || !crate::plasticity_runtime::input_context::permits_refresh(&view, round)
        {
            return Err(invalid("checkpoint current Round or pending effects"));
        }
        let before_clock = checkpoint_now()?;
        if !self.trust.is_current_at(before_clock) {
            return Err(invalid("checkpoint original learning trust expired"));
        }
        self.journal.check_clock(before_clock)?;
        validate_window(round, before_clock)?;
        Ok(before_clock)
    }
    pub(super) fn inspect_parameter_serving_scope(
        &self,
        host: Arc<crate::AgentdNeuronRuntimeV2Host>,
        round: AgentdSelfIterationRoundV1,
    ) -> Result<crate::ParameterServingScopeV1, AgentdError> {
        let before_clock = self.check_parameter_round(&host, &round)?;
        let (neuron_generation, configuration_digest, body_bundle_digest, scope, goal_ordinal) =
            host.parameter_serving_scope_observation()?;
        let after_clock = self.check_parameter_round(&host, &round)?;
        if after_clock < before_clock {
            return Err(invalid("checkpoint clock moved backwards"));
        }
        Ok(crate::ParameterServingScopeV1 {
            round,
            neuron_generation,
            configuration_digest,
            body_bundle_digest,
            scope,
            goal_ordinal,
        })
    }
    pub(super) fn prepare_parameter_checkpoint(
        &self,
        host: Arc<crate::AgentdNeuronRuntimeV2Host>,
        round: AgentdSelfIterationRoundV1,
        path: PathBuf,
        pin: Digest32,
    ) -> Result<crate::PreparedParameterCheckpointV1, AgentdError> {
        let before_clock = self.check_parameter_round(&host, &round)?;
        let bytes = crate::plasticity_process_bootstrap::protected_context_bytes(
            &path,
            pin,
            MAX_NEURON_GENERATION_MATERIAL_BYTES_V2 as u64,
        )?;
        let material =
            decode_neuron_generation_material_v2(&bytes).map_err(|e| invalid(e.to_string()))?;
        let (anchor, checkpoint_bytes, goal_ordinal) =
            host.prepare_parameter_checkpoint_observation(&material)?;
        if crate::plasticity_process_bootstrap::protected_context_bytes(
            &path,
            pin,
            MAX_NEURON_GENERATION_MATERIAL_BYTES_V2 as u64,
        )? != bytes
        {
            return Err(invalid("checkpoint baseline source changed"));
        }
        // Recheck the same whole held owner after source reread as well. No
        // ACK may advance during this complete observation.
        let (after_anchor, after_bytes, after_ordinal) =
            host.prepare_parameter_checkpoint_observation(&material)?;
        if after_anchor != anchor
            || after_bytes != checkpoint_bytes
            || after_ordinal != goal_ordinal
        {
            return Err(invalid(
                "checkpoint actual owner changed during full observation",
            ));
        }
        let after_clock = self.check_parameter_round(&host, &round)?;
        if after_clock < before_clock || self.cancellation.is_cancelled() {
            return Err(invalid("checkpoint clock/cancellation changed"));
        }
        let result = crate::PreparedParameterCheckpointV1 {
            round,
            neuron_generation: material.runtime.generation.get(),
            configuration_digest: material
                .runtime
                .semantic_digest()
                .map_err(|e| invalid(e.to_string()))?,
            body_bundle_digest: material
                .body
                .semantic_digest()
                .map_err(|e| invalid(e.to_string()))?,
            scope: material.scope,
            anchor,
            goal_ordinal,
            baseline_material_digest: pin,
            checkpoint_source_digest: Digest32::of_bytes(&checkpoint_bytes),
            checkpoint_bytes,
        };
        result.checkpoint(&material)?;
        Ok(result)
    }
}
fn checkpoint_now() -> Result<u64, AgentdError> {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|_| invalid("checkpoint clock"))?
        .as_millis()
        .try_into()
        .map_err(|_| invalid("checkpoint clock overflow"))
}
fn validate_window(round: &AgentdSelfIterationRoundV1, now: u64) -> Result<(), AgentdError> {
    if now < round.admitted_at_ms() || now >= round.deadline_ms() {
        return Err(invalid("checkpoint original Round window"));
    }
    Ok(())
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    #[test]
    fn expired_original_trust_rejects_live_reserved_scope_without_changing_journal() {
        use std::os::unix::fs::PermissionsExt;
        let directory = tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()
            .expect("private owner");
        let (_, material, host) =
            crate::neuron_runtime_v2::parameter_checkpoint_tests::fixture(directory.path());
        let now = checkpoint_now().expect("actual clock");
        let admitted = now - 1_000;
        let objective = material.scope.objective_digest;
        let trust = crate::self_iteration::checkpoint_test_trust(now - 60_100, objective);
        assert!(trust.is_current_at(admitted));
        assert!(!trust.is_current_at(now));
        let commit = "1".repeat(40);
        let tree = "2".repeat(40);
        let grammar = Digest32::of_bytes(b"checkpoint expiry grammar");
        let expires = now + 120_000;
        let json = serde_json::json!({"envelopeId":"checkpoint.expiry", "baseCommit":commit,"baseTree":tree,"objectiveDigest":objective.to_string(),"grammarDigest":grammar.to_string(),"allowedPaths":["original/store"],"deniedAuthorities":["promote"],"maximumFiles":2,"maximumBytes":4096,"maximumCandidates":2,"wallTimeMicros":60_000_000,"computeBudget":{"profile":"hepta.iteration-compute-budget.v1","maximumParallelSandboxes":1,"maximumMemoryBytes":4096,"maximumProcesses":2},"mandatoryChecks":["original/checkpoint"],"expiresUnixMs":expires});
        let canonical =
            crate::CanonicalIterationEnvelopeV1::decode(&serde_json::to_vec(&json).expect("JSON"))
                .expect("original canonical");
        let envelope = IterationEnvelopeV1 {
            envelope_id: StableId::new("checkpoint.expiry").expect("id"),
            base_commit: Digest32::of_bytes(commit.as_bytes()),
            base_tree: Digest32::of_bytes(tree.as_bytes()),
            objective_digest: objective,
            grammar_digest: grammar,
            maximum_files: 2,
            maximum_diff_bytes: 4096,
            maximum_candidates: 2,
            maximum_parallel_sandboxes: 1,
            expiry_unix_seconds: expires / 1000,
        };
        let mut rounds = crate::self_iteration::round::RoundJournal::default();
        let round = rounds
            .reserve(
                StableId::new("checkpoint.expired-trust").expect("Goal"),
                &canonical,
                &envelope,
                admitted,
            )
            .expect("original reservation while trust current");
        assert!(now < round.deadline_ms());
        let path = directory.path().join("expired-iteration.json");
        let mut journal = IterationJournal::open(path.clone()).expect("original journal");
        journal
            .persist_rounds(rounds)
            .expect("durable original reservation");
        let owner = SelfIterationOwner::open(journal, trust, host.clone()).expect("original owner");
        let before = std::fs::read(&path).expect("before");
        let error = owner
            .inspect_parameter_serving_scope(host, round)
            .expect_err("expiry cannot hide behind live Round deadline");
        assert!(
            error
                .to_string()
                .contains("original learning trust expired"),
            "{error}"
        );
        assert_eq!(std::fs::read(&path).expect("after"), before);
    }
}
